"""The errors of contract C3, and the ledger's own.

C3 names four errors: TransitionNotAllowed, LockHeld, ConditionalCheckFailed and
StoreUnavailable. They keep the contract's names, without the ``Error`` suffix
the linter asks for, so code and contract read the same. Messages name statuses,
attempts and error classes, never alert content, so a caller may log them.
"""

from __future__ import annotations

from agents.contracts.incident import IncidentStatus


class LedgerError(Exception):
    """Base of every error the ledger raises."""


class TransitionNotAllowed(LedgerError):  # noqa: N818 - the name contract C3 gives it
    """BR3.6, BR3.7: the state machine has no row from the incident's status to the one asked."""

    def __init__(self, from_status: IncidentStatus, to_status: IncidentStatus) -> None:
        super().__init__(f"the incident may not go from {from_status} to {to_status}")
        self.from_status = from_status
        self.to_status = to_status


class LockHeld(LedgerError):  # noqa: N818 - the name contract C3 gives it
    """The service's remediation lock is held by another incident (REQ-064).

    Raised by ``acquire_service_lock``, which u6 adds to the ledger; u1 has no lock.
    """


class ConditionalCheckFailed(LedgerError):  # noqa: N818 - the name contract C3 gives it
    """A condition the caller set on a write did not hold."""


class StoreUnavailable(LedgerError):  # noqa: N818 - the name contract C3 gives it
    """BR3.8, BR6.1: the incident table did not take the write after every attempt.

    The caller dead-letters the work with reason ``store_unavailable``.
    """

    def __init__(self, attempts: int, last_error: str) -> None:
        super().__init__(f"the incident table refused {attempts} attempts; last: {last_error}")
        self.attempts = attempts
        self.last_error = last_error


class IncidentNotFoundError(LedgerError):
    """The incident asked for does not exist."""

    def __init__(self, incident_id: str) -> None:
        super().__init__(f"incident {incident_id} does not exist")
        self.incident_id = incident_id
