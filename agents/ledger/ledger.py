"""The incident ledger (IncidentLedger, contract C3): the only code that writes the incident table.

It runs as a library in the intake (LC2) and, from u1's last pull request, in
the agent runtime (LC6) (ADR-002, ADR-007). Each change is one all-or-nothing
transaction, conditional on what was read (BR3.8). When a condition fails, the
ledger reads again and applies the change again; after ``ledger_write_attempts``
failed attempts, with jittered backoff between them, it raises StoreUnavailable
and the caller dead-letters the work (BR6.1).

``apply_alert`` is C3's ``create_or_attach``, together with the duplicate and
resolved cases that share its one write:

- a key already stored adds nothing, and only the recovery checks run on the
  incident it points to (BR2.2, BR2.5);
- a resolved alert finds its incident through the record of its firing alert and
  sets ``resolved_at``, whatever the incident's status (BR3.5);
- a firing alert attaches to its service's non-terminal incident (BR3.3, BR3.4,
  BR3.9), or creates one with its marker (BR3.1, BR3.2), or, when that incident's
  session died, releases it with ``session_lost`` and creates a new one (BR3.10);
- the inbound event is stored in the same write, with its expiry (BR2.2, BR2.3);
- when the incident now needs a session, the same write records the request,
  and the result carries the SessionStartRequest to hand off (BR4.2, PD-1).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from botocore.exceptions import BotoCoreError, ClientError
from ulid import ULID

from agents.contracts.alert import AlertRecord, AlertStatus, idempotency_key
from agents.contracts.common import SCHEMA_VERSION, utc_now
from agents.contracts.incident import (
    MAX_LISTED_ALERTS,
    AlertRef,
    EscalationReason,
    InboundEvent,
    InboundOutcome,
    Incident,
    IncidentPatch,
    IncidentStatus,
    IncidentTimestamps,
    highest_severity,
    is_transition_allowed,
)
from agents.contracts.session import SessionKind, SessionStartRequest
from agents.contracts.settings import SkeletonSettings
from agents.ledger import items
from agents.ledger.errors import IncidentNotFoundError, StoreUnavailable, TransitionNotAllowed
from agents.telemetry import MetricSink

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
    from mypy_boto3_dynamodb.type_defs import TransactWriteItemTypeDef

BACKOFF_BASE_SECONDS: Final = 0.1
BACKOFF_CAP_SECONDS: Final = 1.0
"""RD-1: jittered backoff between ledger attempts, base 100 ms, cap 1 s."""

_CONFLICT_REASONS: Final = frozenset({"ConditionalCheckFailed", "TransactionConflict"})
_RANDOM: Final = random.SystemRandom()


def new_incident_id(now: datetime) -> str:
    """A ULID whose time part is the incident's creation time, so IDs sort by it (C3)."""
    return str(ULID.from_datetime(now))


class ApplyOutcome(StrEnum):
    CREATED = "created"
    ATTACHED = "attached"
    DUPLICATE = "duplicate"
    RESOLVED_RECORDED = "resolved_recorded"
    RESOLVED_UNMATCHED = "resolved_unmatched"


@dataclass(frozen=True)
class AppliedAlert:
    """What one alert did, for the caller's logs, metrics and session hand-off."""

    outcome: ApplyOutcome
    incident_id: str | None = None
    session_start: SessionStartRequest | None = None
    released_incident_id: str | None = None
    alert_to_record_seconds: float | None = None


class SessionStartVerdict(StrEnum):
    ALLOWED = "allowed"
    INCIDENT_NOT_FOUND = "incident_not_found"
    INCIDENT_TERMINAL = "incident_terminal"
    SESSION_ALREADY_STARTED = "session_already_started"


@dataclass(frozen=True)
class _Plan:
    writes: tuple[TransactWriteItemTypeDef, ...]
    result: AppliedAlert


class _ConflictError(Exception):
    """A conditional write found an item changed since it was read (BR3.8)."""


class _StoreFailureError(Exception):
    """A call to the incident table failed."""

    def __init__(self, error_class: str) -> None:
        super().__init__(error_class)
        self.error_class = error_class


def _error_class(error: ClientError | BotoCoreError) -> str:
    if isinstance(error, ClientError):
        return str(error.response.get("Error", {}).get("Code", "ClientError"))
    return type(error).__name__


def _evolve(incident: Incident, **changes: Any) -> Incident:
    """A validated copy of ``incident`` with ``changes``."""
    return Incident.model_validate({**dict(incident), **changes})


class IncidentLedger:
    """Reads and conditional writes of incidents, markers and inbound events (contract C3)."""

    def __init__(
        self,
        client: DynamoDBClient,
        table_name: str,
        settings: SkeletonSettings | None = None,
        *,
        metrics: MetricSink | None = None,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
        new_id: Callable[[datetime], str] = new_incident_id,
    ) -> None:
        self._client = client
        self._table = table_name
        self._settings = settings or SkeletonSettings()
        self._metrics = metrics
        self._clock = clock
        self._sleep = sleep
        self._new_id = new_id

    # Reads -----------------------------------------------------------------

    def get_incident(self, incident_id: str) -> Incident | None:
        """Return the incident, or None when there is none, with a consistent read."""
        try:
            return self._read_incident(incident_id)
        except _StoreFailureError as failure:
            raise StoreUnavailable(1, failure.error_class) from failure

    def session_start_check(self, incident_id: str) -> SessionStartVerdict:
        """BR4.4, BR6.6: whether a session may start for this incident now."""
        incident = self.get_incident(incident_id)
        if incident is None:
            return SessionStartVerdict.INCIDENT_NOT_FOUND
        if incident.is_terminal:
            return SessionStartVerdict.INCIDENT_TERMINAL
        if incident.timestamps.session_started is not None:
            return SessionStartVerdict.SESSION_ALREADY_STARTED
        return SessionStartVerdict.ALLOWED

    # Writes ----------------------------------------------------------------

    def apply_alert(self, alert: AlertRecord, received_at: datetime) -> AppliedAlert:
        """Apply one alert in one all-or-nothing write; see the module docstring.

        Raises StoreUnavailable after ``ledger_write_attempts`` failed attempts.
        """
        return self._run(lambda: self._apply_once(alert, received_at))

    def advance(
        self, incident_id: str, to_status: IncidentStatus, patch: IncidentPatch | None = None
    ) -> Incident:
        """Change an incident's status along the state machine, with the patch, in one write.

        Raises TransitionNotAllowed when the state machine has no such row (BR3.6,
        BR3.7), IncidentNotFoundError, or StoreUnavailable. A terminal status removes
        the service's marker in the same write (BR3.1), and escalated sets
        ``timestamps.escalated`` (BR5.7).
        """
        return self._run(
            lambda: self._advance_once(incident_id, to_status, patch or IncidentPatch())
        )

    # Attempts --------------------------------------------------------------

    def _run[T](self, attempt_once: Callable[[], T]) -> T:
        attempts = self._settings.ledger_write_attempts
        last_error = "unknown"
        for attempt in range(1, attempts + 1):
            try:
                return attempt_once()
            except _ConflictError:
                self._count("LedgerConflicts")
                last_error = "ConditionalCheckFailed"
            except _StoreFailureError as failure:
                last_error = failure.error_class
            if attempt < attempts:
                ceiling = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
                self._sleep(_RANDOM.uniform(0.0, ceiling))
        self._count("LedgerWriteFailures")
        raise StoreUnavailable(attempts, last_error)

    def _apply_once(self, alert: AlertRecord, received_at: datetime) -> AppliedAlert:
        now = self._clock()
        event = self._read_event(alert.idempotency_key)
        if event is not None:
            plan = self._plan_duplicate(event, now)
        elif alert.status is AlertStatus.RESOLVED:
            plan = self._plan_resolved(alert, received_at, now)
        else:
            plan = self._plan_firing(alert, received_at, now)
        if plan.writes:
            self._transact(plan.writes)
        return plan.result

    def _advance_once(
        self, incident_id: str, to_status: IncidentStatus, patch: IncidentPatch
    ) -> Incident:
        now = self._clock()
        current = self._read_incident(incident_id)
        if current is None:
            raise IncidentNotFoundError(incident_id)
        if not is_transition_allowed(current.status, to_status):
            raise TransitionNotAllowed(current.status, to_status)
        timestamps = current.timestamps
        if patch.session_started is not None:
            timestamps = timestamps.model_copy(update={"session_started": patch.session_started})
        if to_status is IncidentStatus.ESCALATED:
            timestamps = timestamps.model_copy(update={"escalated": now})
        changes = patch.model_dump(exclude_none=True, exclude={"session_started"})
        updated = _evolve(
            current, **changes, status=to_status, timestamps=timestamps, version=current.version + 1
        )
        writes = [self._put_incident(updated, current.version)]
        if updated.is_terminal:
            writes.append(self._release_marker(current.service, current.incident_id))
        self._transact(writes)
        return updated

    # Plans -----------------------------------------------------------------

    def _plan_firing(self, alert: AlertRecord, received_at: datetime, now: datetime) -> _Plan:
        marked_id = self._read_marker(alert.service)
        current = self._read_incident(marked_id) if marked_id else None
        if current is not None and not current.is_terminal and not self._is_stale(current, now):
            updated = self._with_alert(current, alert, now)
            updated, start = self._with_session_request(updated, now)
            trigger_changed = updated.timestamps.record_created != current.timestamps.record_created
            writes = (
                self._put_incident(updated, current.version),
                self._put_event(alert, received_at, InboundOutcome.ATTACHED, current.incident_id),
            )
            latency = _record_latency(updated) if trigger_changed else None
            return _Plan(
                writes,
                AppliedAlert(ApplyOutcome.ATTACHED, current.incident_id, start, None, latency),
            )
        created, start = self._with_session_request(self._new_incident(alert, now), now)
        new_writes = [self._create_incident(created)]
        released_id = None
        if marked_id is None:
            new_writes.append(self._claim_marker(alert.service, created.incident_id))
        else:
            if current is not None and self._is_stale(current, now):
                new_writes.append(self._put_incident(self._released(current, now), current.version))
                released_id = current.incident_id
            new_writes.append(self._move_marker(alert.service, marked_id, created.incident_id))
        new_writes.append(
            self._put_event(alert, received_at, InboundOutcome.CREATED, created.incident_id)
        )
        result = AppliedAlert(
            ApplyOutcome.CREATED, created.incident_id, start, released_id, _record_latency(created)
        )
        return _Plan(tuple(new_writes), result)

    def _plan_duplicate(self, event: InboundEvent, now: datetime) -> _Plan:
        """BR2.2, BR2.5: a repeat adds nothing, but may free a stale incident or retry its start."""
        incident = self._read_incident(event.incident_id) if event.incident_id else None
        if incident is None:
            return _Plan((), AppliedAlert(ApplyOutcome.DUPLICATE, event.incident_id))
        writes: tuple[TransactWriteItemTypeDef, ...]
        if self._is_stale(incident, now):
            writes = (
                self._put_incident(self._released(incident, now), incident.version),
                self._release_marker(incident.service, incident.incident_id),
            )
            result = AppliedAlert(
                ApplyOutcome.DUPLICATE,
                incident.incident_id,
                released_incident_id=incident.incident_id,
            )
            return _Plan(writes, result)
        updated, start = self._with_session_request(incident, now)
        if start is None:
            return _Plan((), AppliedAlert(ApplyOutcome.DUPLICATE, incident.incident_id))
        writes = (self._put_incident(updated, incident.version),)
        return _Plan(writes, AppliedAlert(ApplyOutcome.DUPLICATE, incident.incident_id, start))

    def _plan_resolved(self, alert: AlertRecord, received_at: datetime, now: datetime) -> _Plan:
        """BR3.5: record the resolution on the incident of the firing alert, if it is known."""
        firing_key = idempotency_key(alert.fingerprint, alert.starts_at, AlertStatus.FIRING)
        firing = self._read_event(firing_key)
        incident = (
            self._read_incident(firing.incident_id) if firing and firing.incident_id else None
        )
        if incident is None:
            event = self._put_event(alert, received_at, InboundOutcome.RESOLVED_UNMATCHED, None)
            return _Plan((event,), AppliedAlert(ApplyOutcome.RESOLVED_UNMATCHED))
        updated = self._with_resolution(incident, firing_key, now)
        writes: list[TransactWriteItemTypeDef] = []
        released_id = None
        if self._is_stale(updated, now):
            updated = self._released(updated, now)
            released_id = incident.incident_id
            writes.append(self._release_marker(incident.service, incident.incident_id))
        if updated != incident:
            writes.insert(0, self._put_incident(updated, incident.version))
        writes.append(
            self._put_event(
                alert, received_at, InboundOutcome.RESOLVED_RECORDED, incident.incident_id
            )
        )
        result = AppliedAlert(
            ApplyOutcome.RESOLVED_RECORDED, incident.incident_id, released_incident_id=released_id
        )
        return _Plan(tuple(writes), result)

    # Incident changes ------------------------------------------------------

    def _new_incident(self, alert: AlertRecord, now: datetime) -> Incident:
        """BR3.2, BR4.6: a new open incident, triggered by this alert."""
        return Incident(
            incident_id=self._new_id(now),
            service=alert.service,
            status=IncidentStatus.OPEN,
            severity=alert.severity,
            alerts=(_alert_ref(alert, now),),
            alert_count=1,
            timestamps=IncidentTimestamps(
                alert_fired=alert.starts_at,
                alert_fired_suspect=alert.starts_at_suspect,
                record_created=now,
            ),
            has_unknown_severity=alert.severity not in self._settings.severity_order,
            created_at=now,
        )

    def _with_alert(self, incident: Incident, alert: AlertRecord, now: datetime) -> Incident:
        """BR3.3, BR3.4, BR3.9, BR4.6: attach one alert to a non-terminal incident."""
        settings = self._settings
        listed = incident.alerts
        if len(listed) < MAX_LISTED_ALERTS:
            listed = (*listed, _alert_ref(alert, now))
        severity = highest_severity(incident.severity, alert.severity, settings.severity_order)
        timestamps = incident.timestamps
        rose_to_session = (
            incident.severity not in settings.session_severities
            and severity in settings.session_severities
        )
        if rose_to_session:
            timestamps = timestamps.model_copy(
                update={
                    "alert_fired": alert.starts_at,
                    "alert_fired_suspect": alert.starts_at_suspect,
                    "record_created": now,
                }
            )
        return _evolve(
            incident,
            alerts=listed,
            alert_count=incident.alert_count + 1,
            severity=severity,
            has_unknown_severity=incident.has_unknown_severity
            or alert.severity not in settings.severity_order,
            timestamps=timestamps,
        )

    def _with_session_request(
        self, incident: Incident, now: datetime
    ) -> tuple[Incident, SessionStartRequest | None]:
        """BR4.2, BR4.3: record a session request when the incident needs one.

        ``timestamps.session_requested`` keeps the first request (BR4.6);
        ``last_session_request_at`` holds the latest, for the 120-second window.
        """
        if not self._needs_session(incident, now):
            return incident, None
        timestamps = incident.timestamps
        if timestamps.session_requested is None:
            timestamps = timestamps.model_copy(update={"session_requested": now})
        updated = _evolve(
            incident,
            timestamps=timestamps,
            last_session_request_at=now,
            session_request_count=incident.session_request_count + 1,
        )
        request = SessionStartRequest(
            schema_version=SCHEMA_VERSION,
            incident_id=incident.incident_id,
            kind=SessionKind.INCIDENT,
            requested_at=now,
            attempt=1,
        )
        return updated, request

    def _needs_session(self, incident: Incident, now: datetime) -> bool:
        settings = self._settings
        if incident.is_terminal or incident.timestamps.session_started is not None:
            return False
        if incident.severity not in settings.session_severities:
            return False
        last = incident.last_session_request_at
        window = timedelta(seconds=settings.session_start_deadline_seconds)
        return last is None or now - last >= window

    def _is_stale(self, incident: Incident, now: datetime) -> bool:
        """BR3.10: investigating, with a session that started too long ago and never ended."""
        started = incident.timestamps.session_started
        limit = timedelta(minutes=self._settings.stale_session_minutes)
        return (
            incident.status is IncidentStatus.INVESTIGATING
            and started is not None
            and now - started > limit
        )

    @staticmethod
    def _released(incident: Incident, now: datetime) -> Incident:
        """BR3.10: a stale incident escalated with ``session_lost``."""
        return _evolve(
            incident,
            status=IncidentStatus.ESCALATED,
            escalation_reason=EscalationReason.SESSION_LOST,
            timestamps=incident.timestamps.model_copy(update={"escalated": now}),
        )

    @staticmethod
    def _with_resolution(incident: Incident, firing_key: str, now: datetime) -> Incident:
        """BR3.5: set ``resolved_at`` on the listed alert of that firing key, once."""
        listed = list(incident.alerts)
        for index, ref in enumerate(listed):
            if ref.idempotency_key == firing_key:
                if ref.resolved_at is not None:
                    return incident
                listed[index] = ref.model_copy(update={"resolved_at": now})
                return _evolve(incident, alerts=tuple(listed))
        return incident

    # Items -----------------------------------------------------------------

    def _read(self, key: items.Key) -> dict[str, Any] | None:
        try:
            answer = self._client.get_item(TableName=self._table, Key=key, ConsistentRead=True)
        except (ClientError, BotoCoreError) as error:
            raise _StoreFailureError(_error_class(error)) from error
        item = answer.get("Item")
        return items.from_item(item) if item else None

    def _read_incident(self, incident_id: str) -> Incident | None:
        document = self._read(items.incident_key(incident_id))
        return Incident.model_validate(document) if document else None

    def _read_event(self, key: str) -> InboundEvent | None:
        document = self._read(items.event_key(key))
        return InboundEvent.model_validate(document) if document else None

    def _read_marker(self, service: str) -> str | None:
        document = self._read(items.marker_key(service))
        marked = document.get(items.MARKER_INCIDENT) if document else None
        return str(marked) if marked else None

    def _transact(self, writes: Sequence[TransactWriteItemTypeDef]) -> None:
        try:
            self._client.transact_write_items(TransactItems=list(writes))
        except ClientError as error:
            reasons = {
                reason.get("Code") for reason in error.response.get("CancellationReasons", [])
            }
            if reasons & _CONFLICT_REASONS:
                raise _ConflictError from error
            raise _StoreFailureError(_error_class(error)) from error
        except BotoCoreError as error:
            raise _StoreFailureError(_error_class(error)) from error
        self._count("LedgerWrites")

    def _create_incident(self, incident: Incident) -> TransactWriteItemTypeDef:
        fields = incident.model_dump(mode="json")
        fields.update({items.ITEM_TYPE: items.INCIDENT_ITEM, "version": 1})
        key = items.incident_key(incident.incident_id)
        return items.update(self._table, key, items.ITEM_IS_NEW, fields)

    def _put_incident(self, incident: Incident, read_version: int) -> TransactWriteItemTypeDef:
        """Write every field of ``incident``, if its version is still ``read_version`` (BR3.8)."""
        fields = incident.model_dump(mode="json")
        fields.update({items.ITEM_TYPE: items.INCIDENT_ITEM, "version": read_version + 1})
        key = items.incident_key(incident.incident_id)
        return items.update(self._table, key, items.version_is(read_version), fields)

    def _put_event(
        self,
        alert: AlertRecord,
        received_at: datetime,
        outcome: InboundOutcome,
        incident_id: str | None,
    ) -> TransactWriteItemTypeDef:
        """BR2.2, BR2.3: the inbound event, kept ``idempotency_ttl_days`` after receipt."""
        event = InboundEvent(
            idempotency_key=alert.idempotency_key,
            received_at=received_at,
            outcome=outcome,
            incident_id=incident_id,
            expires_at=received_at + timedelta(days=self._settings.idempotency_ttl_days),
        )
        fields = event.model_dump(mode="json")
        fields[items.ITEM_TYPE] = items.EVENT_ITEM
        fields[items.TTL_ATTRIBUTE] = int(event.expires_at.timestamp())
        key = items.event_key(alert.idempotency_key)
        return items.update(self._table, key, items.ITEM_IS_NEW, fields)

    def _claim_marker(self, service: str, incident_id: str) -> TransactWriteItemTypeDef:
        fields = {
            items.ITEM_TYPE: items.MARKER_ITEM,
            "service": service,
            items.MARKER_INCIDENT: incident_id,
        }
        return items.update(self._table, items.marker_key(service), items.MARKER_IS_FREE, fields)

    def _move_marker(self, service: str, old_id: str, new_id: str) -> TransactWriteItemTypeDef:
        condition = items.marker_points_to(old_id)
        fields = {items.MARKER_INCIDENT: new_id}
        return items.update(self._table, items.marker_key(service), condition, fields)

    def _release_marker(self, service: str, incident_id: str) -> TransactWriteItemTypeDef:
        condition = items.marker_points_to(incident_id)
        key = items.marker_key(service)
        return items.update(self._table, key, condition, {}, remove_fields=(items.MARKER_INCIDENT,))

    def _count(self, metric: str) -> None:
        if self._metrics is not None:
            self._metrics.count(metric)


def _alert_ref(alert: AlertRecord, now: datetime) -> AlertRef:
    return AlertRef(
        idempotency_key=alert.idempotency_key,
        fingerprint=alert.fingerprint,
        alertname=alert.alertname,
        severity=alert.severity,
        starts_at=alert.starts_at,
        starts_at_suspect=alert.starts_at_suspect,
        recorded_at=now,
        truncated_labels=alert.truncated_labels,
    )


def _record_latency(incident: Incident) -> float | None:
    """AlertToRecordSeconds (OD-3): skipped when the start time is suspect (BR1.7)."""
    timestamps = incident.timestamps
    if timestamps.alert_fired_suspect:
        return None
    return (timestamps.record_created - timestamps.alert_fired).total_seconds()
