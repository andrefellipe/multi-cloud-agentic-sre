"""Contract C1: the alert notification the alert manager publishes to the lab topic.

The message is the JSON that ``infra/aws/permanent/templates/alertmanager.yaml.tftpl``
renders. The intake reads it in two steps, so that one bad alert never blocks
the others:

1. :class:`NotificationEnvelope`: the notification's status and its non-empty
   list of alerts, still unread (BR1.2);
2. :class:`AlertPayload`: each alert on its own, with its fingerprint, its start
   time and the five labels the skeleton keeps (BR1.3).

:class:`AlertRecord` is one alert as the intake keeps it: the labels cut to 256
characters (BR1.4), its own status or the notification's (BR1.6), a flag on a
start time that cannot be right (BR1.7), and its idempotency key (BR2.1).
:class:`AlertNotification` is the whole message as C1 defines it, for the JSON
Schema export.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Final

from pydantic import Field, JsonValue

from agents.contracts.common import ContractModel, Instant, NonEmptyStr, format_instant

LABEL_MAX_LENGTH: Final = 256
"""BR1.4: a kept label longer than this is cut to this many characters."""

KEPT_LABELS: Final = ("alertname", "severity", "service", "cluster", "cloud")
"""BR1.3, BR1.4, BR8.7: the labels every alert must carry, and the only ones kept."""

SUSPECT_AFTER_RECEIPT: Final = timedelta(minutes=5)
"""BR1.7: a start time further than this after the intake received the alert is suspect."""

SUSPECT_BEFORE: Final = datetime(2000, 1, 1, tzinfo=UTC)
"""BR1.7: a start time before this is suspect."""

KEY_PREFIX_LENGTH: Final = 12
"""OD-1: logs carry the first 12 characters of the idempotency key, never the labels."""

KeptLabel = Annotated[str, Field(min_length=1, max_length=LABEL_MAX_LENGTH)]


class AlertStatus(StrEnum):
    FIRING = "firing"
    RESOLVED = "resolved"


class AlertLabels(ContractModel):
    """The five labels every alert carries (BR8.7). Any other label is ignored (BR1.4).

    An empty value counts as a missing label (BR1.3).
    """

    alertname: NonEmptyStr
    severity: NonEmptyStr
    service: NonEmptyStr
    cluster: NonEmptyStr
    cloud: NonEmptyStr


class AlertPayload(ContractModel):
    """One alert of a notification (contract C1). Annotations and other fields are ignored."""

    labels: AlertLabels
    starts_at: Instant = Field(alias="startsAt")
    fingerprint: NonEmptyStr
    status: AlertStatus | None = None


class AlertNotification(ContractModel):
    """A whole alert notification, as contract C1 defines it."""

    receiver: NonEmptyStr
    status: AlertStatus
    alerts: tuple[AlertPayload, ...] = Field(min_length=1)


class NotificationEnvelope(ContractModel):
    """The first step of reading a notification: its status and its alerts, still unread.

    A message that is not JSON, or lacks the status or a non-empty list of alerts,
    fails here and is dead-lettered whole (BR1.2). Each alert is then read on its
    own with :class:`AlertPayload` (BR1.3).
    """

    status: AlertStatus
    alerts: tuple[JsonValue, ...] = Field(min_length=1)


def idempotency_key(fingerprint: str, starts_at: datetime, status: AlertStatus) -> str:
    """BR2.1: the key of one alert notification, from its fingerprint, start time and status.

    The three values are hashed as a compact JSON array, so no two different
    combinations can produce the same text. The start time is hashed in its
    instant form (``format_instant``), so it does not depend on how the message
    wrote it.
    """
    material = json.dumps(
        [fingerprint, format_instant(starts_at), status.value],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def is_suspect_start(starts_at: datetime, received_at: datetime) -> bool:
    """BR1.7: whether a start time is too far in the future, or before 2000."""
    return starts_at > received_at + SUSPECT_AFTER_RECEIPT or starts_at < SUSPECT_BEFORE


class AlertRecord(ContractModel):
    """One alert as the intake keeps it, ready for the ledger (BR1.3 to BR1.7, BR2.1)."""

    idempotency_key: NonEmptyStr
    fingerprint: NonEmptyStr
    starts_at: Instant
    starts_at_suspect: bool
    status: AlertStatus
    alertname: KeptLabel
    severity: KeptLabel
    service: KeptLabel
    cluster: KeptLabel
    cloud: KeptLabel
    truncated_labels: tuple[str, ...] = ()

    @property
    def key_prefix(self) -> str:
        """The part of the key that logs may carry (OD-1)."""
        return self.idempotency_key[:KEY_PREFIX_LENGTH]

    @classmethod
    def from_payload(
        cls, payload: AlertPayload, notification_status: AlertStatus, received_at: datetime
    ) -> AlertRecord:
        """Reduce one C1 alert to what the skeleton keeps.

        - BR1.4: the five labels are kept, each cut to 256 characters, and every
          cut label is named in ``truncated_labels``.
        - BR1.6: the alert's own status, or the notification's when it has none.
        - BR1.7: the start time is kept, and flagged when it cannot be right.
        - BR2.1: the key comes from the fingerprint, the start time and the status.
        """
        status = payload.status or notification_status
        kept: dict[str, str] = {}
        truncated: list[str] = []
        for name in KEPT_LABELS:
            value: str = getattr(payload.labels, name)
            if len(value) > LABEL_MAX_LENGTH:
                value = value[:LABEL_MAX_LENGTH]
                truncated.append(name)
            kept[name] = value
        return cls(
            idempotency_key=idempotency_key(payload.fingerprint, payload.starts_at, status),
            fingerprint=payload.fingerprint,
            starts_at=payload.starts_at,
            starts_at_suspect=is_suspect_start(payload.starts_at, received_at),
            status=status,
            alertname=kept["alertname"],
            severity=kept["severity"],
            service=kept["service"],
            cluster=kept["cluster"],
            cloud=kept["cloud"],
            truncated_labels=tuple(truncated),
        )
