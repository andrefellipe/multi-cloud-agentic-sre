"""The dead-letter item: work the intake could not finish, kept so no alert is lost (REQ-140).

The intake writes one to the dead-letter queue (LC8) for each failure it handles
itself (BR1.2, BR1.3, BR4.5, BR6.1, BR6.2). The queue also receives two shapes
the intake does not write: the function's on-failure records, after the
platform's retries, and session starts redriven from the session-start queue.
``tools/lab/replay_dead_letters.py`` recognises all three (BR6.6).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from agents.contracts.common import ContractModel, Instant, NonEmptyStr


class DeadLetterKind(StrEnum):
    ALERT_NOTIFICATION = "alert_notification"
    ALERT = "alert"
    SESSION_START = "session_start"


class DeadLetterReason(StrEnum):
    INVALID_PAYLOAD = "invalid_payload"
    STORE_UNAVAILABLE = "store_unavailable"
    SESSION_START_FAILED = "session_start_failed"
    UNEXPECTED_ERROR = "unexpected_error"


class DeadLetterItem(ContractModel):
    """One item the intake dead-lettered.

    ``original`` is the message exactly as received: for an alert notification or
    an alert, the whole notification, which replays through the intake, where
    idempotency stops any double effect (BR6.6); for a session start, the
    SessionStartRequest. It is never posted anywhere.
    """

    schema_version: Literal[1] = 1
    dead_letter_id: NonEmptyStr
    kind: DeadLetterKind
    reason: DeadLetterReason
    original: str
    first_failed_at: Instant
    attempts: int = Field(ge=1)
