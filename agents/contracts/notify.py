"""Contract C7: the notify interface, and the one notice Phase 1 sends.

u1 owns the interface and its fixed templates; u4 adds free-text kinds once the
output sanitizer (C6) exists. Until then only ``dead_letter_alert`` is sent, as a
fixed template with no text from any message, and ``body`` must stay empty
(ADR-006, BR6.3).

The dead-letter notice carries only the queue label, the item count and the
oldest item's age. Either number is None when the notifier could not read it:
the notice is sent anyway, saying the value is unknown, so a failed read never
stops it (BR6.5).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import AnyUrl, Field, model_validator

from agents.contracts.common import ContractModel, Instant, NonEmptyStr


class NotifyKind(StrEnum):
    DEAD_LETTER_ALERT = "dead_letter_alert"
    INCIDENT_CLOSED = "incident_closed"
    INCIDENT_ESCALATED = "incident_escalated"
    PR_OPENED = "pr_opened"


PHASE_1_KINDS: Final = frozenset({NotifyKind.DEAD_LETTER_ALERT})
"""ADR-006: the only kind the notifier sends until the output sanitizer (C6) exists."""


class DeadLetterNotice(ContractModel):
    """The fixed-template notice of ``dead_letter_alert`` (BR6.3)."""

    queue_label: NonEmptyStr
    message_count: int | None = Field(default=None, ge=0)
    oldest_age_minutes: int | None = Field(default=None, ge=0)
    raised_at: Instant


class NotifyRequest(ContractModel):
    """C7: one request to notify the human channel."""

    schema_version: Literal[1] = 1
    kind: NotifyKind
    incident_id: NonEmptyStr | None = None
    pr_url: AnyUrl | None = None
    body: str | None = None
    dead_letter: DeadLetterNotice | None = None

    @model_validator(mode="after")
    def _fixed_templates_only(self) -> Self:
        if self.body is not None:
            raise ValueError("body must be empty: free text needs the output sanitizer (C6, u4)")
        if (self.kind is NotifyKind.DEAD_LETTER_ALERT) != (self.dead_letter is not None):
            raise ValueError("dead_letter is required for dead_letter_alert, and only for it")
        return self
