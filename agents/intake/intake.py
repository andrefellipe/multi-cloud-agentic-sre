"""EventIntake: turns alert notifications from the lab topic into incident changes (W1, PD-1).

For each SNS record, the intake:

1. records ``received_at``, and discards a message from any topic other than
   the lab topic, logging and counting it (BR1.1);
2. reads the notification; one that cannot be read is dead-lettered whole, with
   reason ``invalid_payload`` and no retry (BR1.2);
3. reads each alert on its own: a bad alert is dead-lettered alone and the rest
   go on (BR1.3); the good ones keep only what the skeleton needs (BR1.4, BR1.6,
   BR1.7). Bad alerts are dead-lettered in the order they arrived;
4. applies the good alerts in order of start time, then fingerprint (BR2.4),
   each with one ledger write (BR2.1 to BR4.6). An alert the incident table does
   not take after the ledger's attempts is dead-lettered with
   ``store_unavailable`` (BR6.1), and one that fails in any other way with
   ``unexpected_error`` (BR6.2);
5. hands each session request the ledger recorded to the session-start queue,
   and moves on: it never calls the agent runtime or waits for a session (PD-1).
   A request the queue does not take is dead-lettered with
   ``session_start_failed``; the next alert for the service asks again (BR4.5).

Every failure ends in a dead-letter item before the work counts as handled. If
the dead-letter queue itself refuses an item, the intake finishes the other
alerts and then raises, so that the platform retries the notification and finally
hands it to the function's on-failure destination (RD-1). Alerts already
applied are duplicates on a retry and change nothing (BR2.2).

Logs and metrics follow OD-2 and OD-3: no message body, label or URL is ever
logged, only the first 12 characters of an alert's key.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ulid import ULID

from agents.aws import QUEUE_SEND_ATTEMPTS
from agents.contracts.alert import AlertPayload, AlertRecord, NotificationEnvelope
from agents.contracts.common import NonEmptyStr, utc_now
from agents.contracts.dead_letter import DeadLetterItem, DeadLetterKind, DeadLetterReason
from agents.contracts.session import SessionStartRequest
from agents.contracts.settings import SkeletonSettings, require_setting
from agents.ledger.errors import StoreUnavailable
from agents.ledger.ledger import AppliedAlert, ApplyOutcome, IncidentLedger
from agents.telemetry import Telemetry

if TYPE_CHECKING:
    from mypy_boto3_sqs.client import SQSClient


class IntakeSettings(BaseModel):
    """What the intake is wired to, read from its environment at start-up."""

    model_config = ConfigDict(frozen=True)

    lab_topic_arn: NonEmptyStr
    incident_table_name: NonEmptyStr
    session_start_queue_url: NonEmptyStr
    dead_letter_queue_url: NonEmptyStr
    skeleton: SkeletonSettings = Field(default_factory=SkeletonSettings)

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> IntakeSettings:
        """Read the settings; a missing one stops start-up with an error naming it."""
        return cls(
            lab_topic_arn=require_setting(environ, "LAB_TOPIC_ARN"),
            incident_table_name=require_setting(environ, "INCIDENT_TABLE_NAME"),
            session_start_queue_url=require_setting(environ, "SESSION_START_QUEUE_URL"),
            dead_letter_queue_url=require_setting(environ, "DEAD_LETTER_QUEUE_URL"),
            skeleton=SkeletonSettings.from_environ(environ),
        )


class DeadLetterWriteError(Exception):
    """The dead-letter queue refused an item, so the notification must be retried (RD-1)."""

    def __init__(self, unsaved: int) -> None:
        super().__init__(f"{unsaved} dead-letter item(s) could not be saved")
        self.unsaved = unsaved


def new_dead_letter_id(now: datetime) -> str:
    return str(ULID.from_datetime(now))


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _error_class(error: Exception) -> str:
    if isinstance(error, ClientError):
        return str(error.response.get("Error", {}).get("Code", "ClientError"))
    return type(error).__name__


@dataclass
class _Tally:
    """What one invocation did, returned as its result."""

    counts: Counter[str] = field(default_factory=Counter)
    unsaved: int = 0


class Intake:
    """EventIntake's alert path (W1)."""

    def __init__(
        self,
        settings: IntakeSettings,
        ledger: IncidentLedger,
        sqs: SQSClient,
        *,
        telemetry: Telemetry | None = None,
        clock: Callable[[], datetime] = utc_now,
        new_id: Callable[[datetime], str] = new_dead_letter_id,
    ) -> None:
        self._settings = settings
        self._ledger = ledger
        self._sqs = sqs
        self._telemetry = telemetry or Telemetry("intake")
        self._clock = clock
        self._new_id = new_id

    def handle(self, event: object) -> dict[str, int]:
        """Process one invocation's SNS records, and return what was done.

        Raises DeadLetterWriteError when a dead-letter item could not be saved.
        """
        tally = _Tally()
        records = event.get("Records") if isinstance(event, Mapping) else None
        if isinstance(records, list) and records:
            for record in records:
                self._handle_record(tally, record)
        else:
            self._dead_letter(
                tally,
                DeadLetterKind.ALERT_NOTIFICATION,
                DeadLetterReason.INVALID_PAYLOAD,
                _dumps(event),
            )
        if tally.unsaved:
            raise DeadLetterWriteError(tally.unsaved)
        return dict(sorted(tally.counts.items()))

    def _handle_record(self, tally: _Tally, record: object) -> None:
        received_at = self._clock()
        sns = record.get("Sns") if isinstance(record, Mapping) else None
        if not isinstance(sns, Mapping) or not isinstance(sns.get("Message"), str):
            self._dead_letter(
                tally,
                DeadLetterKind.ALERT_NOTIFICATION,
                DeadLetterReason.INVALID_PAYLOAD,
                _dumps(record),
            )
            return
        if sns.get("TopicArn") != self._settings.lab_topic_arn:
            tally.counts["rejected"] += 1
            self._telemetry.count("NotificationsRejected")
            self._telemetry.log(
                "notification from another topic discarded",
                level="WARNING",
                outcome="rejected",
                reason="wrong_topic",
            )
            return
        message: str = sns["Message"]
        try:
            self._handle_message(tally, message, received_at)
        except Exception as error:  # BR6.2: the notification is kept, whatever failed.
            self._unexpected(tally, error, DeadLetterKind.ALERT_NOTIFICATION, message)

    def _handle_message(self, tally: _Tally, message: str, received_at: datetime) -> None:
        try:
            envelope = NotificationEnvelope.model_validate_json(message)
        except ValidationError:
            self._dead_letter(
                tally, DeadLetterKind.ALERT_NOTIFICATION, DeadLetterReason.INVALID_PAYLOAD, message
            )
            return
        alerts: list[AlertRecord] = []
        for raw in envelope.alerts:
            tally.counts["alerts"] += 1
            self._telemetry.count("AlertsReceived")
            try:
                payload = AlertPayload.model_validate(raw)
            except ValidationError:
                self._dead_letter(
                    tally, DeadLetterKind.ALERT, DeadLetterReason.INVALID_PAYLOAD, message
                )
                continue
            alerts.append(AlertRecord.from_payload(payload, envelope.status, received_at))
        for alert in sorted(alerts, key=lambda alert: (alert.starts_at, alert.fingerprint)):
            self._apply(tally, alert, message, received_at)

    def _apply(
        self, tally: _Tally, alert: AlertRecord, message: str, received_at: datetime
    ) -> None:
        try:
            applied = self._ledger.apply_alert(alert, received_at)
        except StoreUnavailable as error:
            self._telemetry.log(
                "alert not recorded: the incident table refused every attempt",
                level="ERROR",
                outcome="dead_lettered",
                reason=DeadLetterReason.STORE_UNAVAILABLE,
                key_prefix=alert.key_prefix,
                error_class=error.last_error,
                attempt=error.attempts,
            )
            self._dead_letter(
                tally,
                DeadLetterKind.ALERT,
                DeadLetterReason.STORE_UNAVAILABLE,
                message,
                attempts=error.attempts,
                key_prefix=alert.key_prefix,
            )
            return
        except Exception as error:  # BR6.2: dead-letter the alert, never drop it.
            self._unexpected(tally, error, DeadLetterKind.ALERT, message, alert.key_prefix)
            return
        self._record(tally, alert, applied)
        if applied.session_start is not None:
            self._hand_off(tally, applied.session_start)

    def _record(self, tally: _Tally, alert: AlertRecord, applied: AppliedAlert) -> None:
        tally.counts[applied.outcome.value] += 1
        if applied.outcome is ApplyOutcome.DUPLICATE:
            self._telemetry.count("AlertsDuplicate")
        if applied.outcome is ApplyOutcome.CREATED:
            self._telemetry.count("IncidentsCreated")
        if applied.alert_to_record_seconds is not None:
            self._telemetry.seconds("AlertToRecordSeconds", applied.alert_to_record_seconds)
        self._telemetry.log(
            "alert applied",
            outcome=applied.outcome.value,
            incident_id=applied.incident_id,
            key_prefix=alert.key_prefix,
        )
        if applied.released_incident_id is not None:
            tally.counts["released"] += 1
            self._telemetry.log(
                "stale session released",
                level="WARNING",
                outcome="escalated",
                reason="session_lost",
                incident_id=applied.released_incident_id,
            )

    def _hand_off(self, tally: _Tally, request: SessionStartRequest) -> None:
        """PD-1: put the request on the session-start queue, and move on."""
        body = request.model_dump_json()
        try:
            self._sqs.send_message(
                QueueUrl=self._settings.session_start_queue_url, MessageBody=body
            )
        except (ClientError, BotoCoreError) as error:
            self._telemetry.log(
                "session start not handed off",
                level="ERROR",
                outcome="dead_lettered",
                reason=DeadLetterReason.SESSION_START_FAILED,
                incident_id=request.incident_id,
                error_class=_error_class(error),
            )
            self._dead_letter(
                tally,
                DeadLetterKind.SESSION_START,
                DeadLetterReason.SESSION_START_FAILED,
                body,
                attempts=QUEUE_SEND_ATTEMPTS,
                incident_id=request.incident_id,
            )
            return
        tally.counts["session_starts"] += 1
        self._telemetry.log(
            "session start handed off", outcome="session_requested", incident_id=request.incident_id
        )

    def _unexpected(
        self,
        tally: _Tally,
        error: Exception,
        kind: DeadLetterKind,
        original: str,
        key_prefix: str | None = None,
    ) -> None:
        """BR6.2: count and log the error class, never the content, and keep the work."""
        self._telemetry.count("IntakeErrors")
        self._telemetry.log(
            "unexpected error",
            level="ERROR",
            outcome="dead_lettered",
            reason=DeadLetterReason.UNEXPECTED_ERROR,
            key_prefix=key_prefix,
            error_class=_error_class(error),
        )
        self._dead_letter(
            tally, kind, DeadLetterReason.UNEXPECTED_ERROR, original, key_prefix=key_prefix
        )

    def _dead_letter(
        self,
        tally: _Tally,
        kind: DeadLetterKind,
        reason: DeadLetterReason,
        original: str,
        *,
        attempts: int = 1,
        key_prefix: str | None = None,
        incident_id: str | None = None,
    ) -> None:
        """Keep work the intake could not finish on the dead-letter queue (REQ-140.1)."""
        now = self._clock()
        item = DeadLetterItem(
            dead_letter_id=self._new_id(now),
            kind=kind,
            reason=reason,
            original=original,
            first_failed_at=now,
            attempts=attempts,
        )
        try:
            self._sqs.send_message(
                QueueUrl=self._settings.dead_letter_queue_url, MessageBody=item.model_dump_json()
            )
        except (ClientError, BotoCoreError) as error:
            tally.unsaved += 1
            self._telemetry.count("IntakeErrors")
            self._telemetry.log(
                "dead-letter item not saved; the notification will be retried",
                level="ERROR",
                outcome="unsaved",
                reason=reason,
                key_prefix=key_prefix,
                incident_id=incident_id,
                error_class=_error_class(error),
            )
            return
        tally.counts["dead_lettered"] += 1
        self._telemetry.count("AlertsDeadLettered", reason=reason)
        self._telemetry.log(
            "work dead-lettered",
            level="WARNING",
            outcome="dead_lettered",
            reason=reason,
            key_prefix=key_prefix,
            incident_id=incident_id,
        )
