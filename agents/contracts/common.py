"""Building blocks shared by every contract: the instant type and the base model.

Every instant in a contract is a UTC instant with millisecond precision
(REQ-121.1), written as ``2026-11-12T23:32:04.587Z``. That fixed form sorts as
text, which the incident table relies on, and it is the form the idempotency key
hashes (BR2.1).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Final

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer

SCHEMA_VERSION: Final = 1
"""The ``schema_version`` every u1 message and record carries (contract design Q2)."""


def to_utc_millis(value: datetime) -> datetime:
    """Return ``value`` in UTC, cut to whole milliseconds (REQ-121.1)."""
    try:
        utc = value.astimezone(UTC)
    except OverflowError as error:
        raise ValueError("the instant is outside the range of dates") from error
    return utc.replace(microsecond=utc.microsecond // 1000 * 1000)


def format_instant(value: datetime) -> str:
    """Write an instant in the one form every contract uses: ``YYYY-MM-DDTHH:MM:SS.mmmZ``."""
    return to_utc_millis(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def utc_now() -> datetime:
    """Return the current instant in UTC, at millisecond precision."""
    return to_utc_millis(datetime.now(UTC))


Instant = Annotated[
    AwareDatetime,
    AfterValidator(to_utc_millis),
    PlainSerializer(format_instant, return_type=str, when_used="json"),
]
"""A UTC instant with millisecond precision. An input without an offset is refused."""

NonEmptyStr = Annotated[str, Field(min_length=1)]


class ContractModel(BaseModel):
    """Base of every contract model.

    Instances are immutable, and unknown fields are ignored, so a consumer keeps
    working when a producer adds an optional field (contract design Q2).
    """

    model_config = ConfigDict(
        extra="ignore",
        frozen=True,
        validate_by_alias=True,
        validate_by_name=True,
    )
