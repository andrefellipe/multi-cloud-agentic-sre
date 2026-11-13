"""Contracts C4 (session start) and C5 (agent result envelope).

C4 is the message the intake puts on the session-start queue (PD-1); the session
starter hands it to the agent runtime (u1's last pull request). C5 is the
envelope every agent role returns to AgentSession: u1 owns the envelope, and each
role's unit owns its payload, so the payload is kept as plain JSON here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from agents.contracts.common import ContractModel, Instant, NonEmptyStr
from agents.contracts.incident import ToolCallRecord


class SessionKind(StrEnum):
    INCIDENT = "incident"
    VERIFIER = "verifier"


class SessionStartRequest(ContractModel):
    """C4: asks the agent runtime to start a session for an incident."""

    schema_version: Literal[1]
    incident_id: NonEmptyStr
    kind: SessionKind
    requested_at: Instant
    attempt: int = Field(default=1, ge=1, le=3)
    merge_commit_sha: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _merge_commit_for_verifier_only(self) -> Self:
        verifier = self.kind is SessionKind.VERIFIER
        if verifier != (self.merge_commit_sha is not None):
            raise ValueError("merge_commit_sha is required for a verifier session, and only then")
        return self


class AgentRole(StrEnum):
    TRIAGE = "triage"
    INVESTIGATOR = "investigator"
    REMEDIATOR = "remediator"
    REVIEWER = "reviewer"
    VERIFIER = "verifier"


class AgentOutcome(StrEnum):
    OK = "ok"
    ESCALATE = "escalate"
    DENIED = "denied"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ERROR = "error"


class AgentResult(ContractModel):
    """C5: what an agent role returns to AgentSession.

    AgentSession validates every result against this envelope, and treats an
    invalid one as ``outcome=error``. The role payloads (triage, investigation,
    remediation, review, verification) belong to u5, u6 and u7.
    """

    schema_version: Literal[1] = 1
    role: AgentRole
    incident_id: NonEmptyStr
    outcome: AgentOutcome
    payload: dict[str, JsonValue] | None = None
    tool_calls: tuple[ToolCallRecord, ...] = ()
    tokens_used: int = Field(default=0, ge=0)
    steps_used: int = Field(default=0, ge=0)
