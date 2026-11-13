"""Contract C3: the incident record, schema_version 1, owned by u1 (``entities.md``).

The Incident is defined in full, including fields that later units fill. Four
optional fields are additive to the entity model, as C3's ownership rules allow:

- ``has_unknown_severity``: BR3.4 flags a severity outside ``severity_order``;
- ``session_request_count`` and ``last_session_request_at``: BR4.2 needs the
  latest request for its 120-second window, while ``timestamps.session_requested``
  keeps the first one (BR4.6);
- ``timestamps.alert_fired_suspect``: whether ``alert_fired`` came from a start
  time flagged by BR1.7, so that latency figures can leave it out.

The state machine of ``functional-spec.md`` is :data:`ALLOWED_TRANSITIONS`. The
ledger enforces every row and refuses any other change (BR3.7). u1 uses three
rows: (none) to open, open to investigating, investigating to escalated.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal, Self

from pydantic import AnyUrl, Field, model_validator

from agents.contracts.common import ContractModel, Instant, NonEmptyStr

MAX_LISTED_ALERTS: Final = 100
"""BR3.9: an incident lists at most this many alerts; later ones are only counted."""

MAX_READ_ITEM_NAMES: Final = 50
"""BR5.6: a ReadCheck keeps at most this many pod names."""


class IncidentStatus(StrEnum):
    OPEN = "open"
    TRIAGED = "triaged"
    INVESTIGATING = "investigating"
    PR_OPEN = "pr_open"
    AWAITING_MERGE = "awaiting_merge"
    VERIFYING = "verifying"
    RECOVERED = "recovered"
    NOT_REMEDIATED = "not_remediated"
    ESCALATED = "escalated"
    CLOSED_NO_ACTION = "closed_no_action"


TERMINAL_STATUSES: Final = frozenset(
    {
        IncidentStatus.ESCALATED,
        IncidentStatus.RECOVERED,
        IncidentStatus.NOT_REMEDIATED,
        IncidentStatus.CLOSED_NO_ACTION,
    }
)
"""BR3.6: statuses an incident never leaves."""

_S = IncidentStatus
ALLOWED_TRANSITIONS: Final[Mapping[IncidentStatus | None, frozenset[IncidentStatus]]] = (
    MappingProxyType(
        {
            None: frozenset({_S.OPEN}),
            _S.OPEN: frozenset({_S.INVESTIGATING, _S.TRIAGED, _S.CLOSED_NO_ACTION, _S.ESCALATED}),
            _S.TRIAGED: frozenset({_S.INVESTIGATING, _S.ESCALATED}),
            _S.INVESTIGATING: frozenset({_S.ESCALATED, _S.PR_OPEN}),
            _S.PR_OPEN: frozenset({_S.AWAITING_MERGE, _S.ESCALATED}),
            _S.AWAITING_MERGE: frozenset({_S.VERIFYING, _S.NOT_REMEDIATED, _S.ESCALATED}),
            _S.VERIFYING: frozenset({_S.RECOVERED, _S.ESCALATED}),
            _S.ESCALATED: frozenset(),
            _S.RECOVERED: frozenset(),
            _S.NOT_REMEDIATED: frozenset(),
            _S.CLOSED_NO_ACTION: frozenset(),
        }
    )
)
"""BR3.7: the incident state machine of ``functional-spec.md``, as from-status to to-statuses.

None is the state before an incident exists. Every non-terminal status may also
go to escalated (session error, budget cap or kill switch, from u5 on).
"""


def is_transition_allowed(from_status: IncidentStatus | None, to_status: IncidentStatus) -> bool:
    """BR3.7: whether the state machine has the row ``from_status`` to ``to_status``."""
    return to_status in ALLOWED_TRANSITIONS[from_status]


def severity_rank(severity: str, order: Sequence[str]) -> int:
    """BR3.4: the rank of a severity; 0 is the highest.

    A value not in ``order`` ranks below every listed one. Severities are compared
    exactly, as written.
    """
    return order.index(severity) if severity in order else len(order)


def highest_severity(current: str, new: str, order: Sequence[str]) -> str:
    """BR3.4: the higher-ranked of two severities; on a tie the current one stays."""
    return new if severity_rank(new, order) < severity_rank(current, order) else current


class EscalationReason(StrEnum):
    SKELETON_READ_DONE = "skeleton_read_done"
    READ_FAILED = "read_failed"
    MODEL_MADE_NO_CALL = "model_made_no_call"
    STEP_CAP_REACHED = "step_cap_reached"
    SESSION_ERROR = "session_error"
    SESSION_LOST = "session_lost"


class SessionEndReason(StrEnum):
    READ_OK = "read_ok"
    READ_FAILED = "read_failed"
    MODEL_MADE_NO_CALL = "model_made_no_call"
    STEP_CAP_REACHED = "step_cap_reached"
    SESSION_ERROR = "session_error"
    SESSION_LOST = "session_lost"


class TriageDecision(StrEnum):
    ACT = "act"
    NO_ACTION = "no_action"
    DUPLICATE = "duplicate"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolDecision(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"


class DenyReason(StrEnum):
    NOT_IN_CATALOGUE = "not_in_catalogue"
    PATH_NOT_ALLOWED = "path_not_allowed"
    WRITES_DISABLED = "writes_disabled"
    KILL_SWITCH = "kill_switch"
    POLICY = "policy"


class ReadErrorKind(StrEnum):
    TIMEOUT = "timeout"
    DENIED = "denied"
    UNREACHABLE = "unreachable"
    INVALID_RESPONSE = "invalid_response"


class AlertRef(ContractModel):
    """One alert as recorded on an incident."""

    idempotency_key: NonEmptyStr
    fingerprint: NonEmptyStr
    alertname: NonEmptyStr
    severity: NonEmptyStr
    starts_at: Instant
    starts_at_suspect: bool = False
    recorded_at: Instant
    resolved_at: Instant | None = None
    truncated_labels: tuple[str, ...] = ()


class IncidentTimestamps(ContractModel):
    """The instants behind the latency targets of REQ-120 (REQ-121.1)."""

    alert_fired: Instant
    alert_fired_suspect: bool = False
    record_created: Instant
    session_requested: Instant | None = None
    session_started: Instant | None = None
    escalated: Instant | None = None
    pr_opened: Instant | None = None
    merged: Instant | None = None
    verified: Instant | None = None


class ToolCallRecord(ContractModel):
    """One tool call of a session (contract C5 ``tool_calls``)."""

    tool: NonEmptyStr
    started_at: Instant
    duration_ms: int = Field(ge=0)
    decision: ToolDecision
    deny_reason: DenyReason | None = None


class SessionSummary(ContractModel):
    """What an incident keeps about its last session."""

    session_id: NonEmptyStr
    ended_reason: SessionEndReason
    ended_at: Instant
    tool_calls: tuple[ToolCallRecord, ...] = ()


class ReadCheck(ContractModel):
    """The skeleton's one Rancher read, taken from the tool's response (BR5.6)."""

    tool: Literal["k8s_read"] = "k8s_read"
    namespace: NonEmptyStr
    resource: Literal["pods"] = "pods"
    succeeded: bool
    item_count: int | None = Field(default=None, ge=0)
    item_names: tuple[str, ...] = Field(default=(), max_length=MAX_READ_ITEM_NAMES)
    error_kind: ReadErrorKind | None = None
    completed_at: Instant


class Incident(ContractModel):
    """One problem with one service, from its first alert to a terminal status (contract C3)."""

    incident_id: NonEmptyStr
    schema_version: Literal[1] = 1
    service: NonEmptyStr
    status: IncidentStatus = IncidentStatus.OPEN
    severity: NonEmptyStr
    alerts: tuple[AlertRef, ...] = Field(min_length=1, max_length=MAX_LISTED_ALERTS)
    alert_count: int = Field(ge=1)
    timestamps: IncidentTimestamps
    escalation_reason: EscalationReason | None = None
    last_session: SessionSummary | None = None
    read_check: ReadCheck | None = None
    triage_decision: TriageDecision | None = None
    root_cause: str | None = None
    evidence_links: tuple[AnyUrl, ...] = ()
    confidence: Confidence | None = None
    injection_flags: tuple[str, ...] = ()
    pr_url: AnyUrl | None = None
    revert_count: int = Field(default=0, ge=0, le=1)
    tokens_used: int = Field(default=0, ge=0)
    steps_used: int = Field(default=0, ge=0)
    estimated_cost_usd: Decimal | None = None
    created_at: Instant
    version: int = Field(default=1, ge=1)
    has_unknown_severity: bool = False
    session_request_count: int = Field(default=0, ge=0)
    last_session_request_at: Instant | None = None

    @model_validator(mode="after")
    def _count_covers_the_listed_alerts(self) -> Self:
        if self.alert_count < len(self.alerts):
            raise ValueError("alert_count is lower than the number of listed alerts")
        return self

    @property
    def is_terminal(self) -> bool:
        """BR3.6: whether the incident has reached a status it never leaves."""
        return self.status in TERMINAL_STATUSES


class IncidentPatch(ContractModel):
    """The fields a status change may also set (C3 ``advance``). Unset fields stay as they are."""

    escalation_reason: EscalationReason | None = None
    session_started: Instant | None = None
    last_session: SessionSummary | None = None
    read_check: ReadCheck | None = None
    tokens_used: int | None = Field(default=None, ge=0)
    steps_used: int | None = Field(default=None, ge=0)


class InboundOutcome(StrEnum):
    CREATED = "created"
    ATTACHED = "attached"
    RESOLVED_RECORDED = "resolved_recorded"
    RESOLVED_UNMATCHED = "resolved_unmatched"


class InboundEvent(ContractModel):
    """The record that one alert notification was already applied (BR2.2, BR2.3).

    Stored by the ledger in the same write as the incident change it caused. The
    record under an alert's firing key is also how a later resolved notification
    finds that alert's incident (BR3.5).
    """

    idempotency_key: NonEmptyStr
    source: Literal["alert"] = "alert"
    received_at: Instant
    outcome: InboundOutcome
    incident_id: NonEmptyStr | None = None
    expires_at: Instant

    @model_validator(mode="after")
    def _incident_unless_unmatched(self) -> Self:
        unmatched = self.outcome is InboundOutcome.RESOLVED_UNMATCHED
        if unmatched != (self.incident_id is None):
            raise ValueError("incident_id is absent exactly when the outcome is resolved_unmatched")
        return self
