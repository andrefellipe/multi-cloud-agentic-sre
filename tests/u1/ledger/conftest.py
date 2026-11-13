"""Fixtures for the ledger's tests (plan Step 22): moto DynamoDB, a fake clock, no sleeping."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest

from agents.contracts.alert import AlertPayload, AlertRecord, AlertStatus
from agents.contracts.settings import SkeletonSettings
from agents.ledger.ledger import IncidentLedger


@dataclass
class RecordingMetrics:
    """A MetricSink that remembers every count."""

    counts: dict[str, int] = field(default_factory=dict)

    def count(self, metric: str, value: int = 1, *, reason: str | None = None) -> None:
        self.counts[metric] = self.counts.get(metric, 0) + value


@dataclass
class LedgerUnderTest:
    ledger: IncidentLedger
    metrics: RecordingMetrics
    sleeps: list[float]


@pytest.fixture
def make_ledger(pipeline: Any, fake_clock: Any) -> Callable[..., LedgerUnderTest]:
    """Build a ledger on the moto table, with the fake clock and a recording sleep."""

    def make(client: Any = None, settings: SkeletonSettings | None = None) -> LedgerUnderTest:
        metrics = RecordingMetrics()
        sleeps: list[float] = []
        ledger = IncidentLedger(
            client or pipeline.dynamodb,
            pipeline.table_name,
            settings,
            metrics=metrics,
            clock=fake_clock.now,
            sleep=sleeps.append,
        )
        return LedgerUnderTest(ledger, metrics, sleeps)

    return make


@pytest.fixture
def make_alert() -> Callable[..., AlertRecord]:
    """Build an alert as the intake keeps it, received at ``received_at``."""

    def make(
        fingerprint: str,
        *,
        service: str = "payment",
        severity: str = "critical",
        starts_at: str = "2026-11-12T23:32:04.587Z",
        status: AlertStatus = AlertStatus.FIRING,
        received_at: datetime,
    ) -> AlertRecord:
        payload = AlertPayload.model_validate(
            {
                "labels": {
                    "alertname": "PaymentErrorRatioHigh",
                    "severity": severity,
                    "service": service,
                    "cluster": "sre-lab-eks",
                    "cloud": "aws",
                },
                "startsAt": starts_at,
                "fingerprint": fingerprint,
                "status": status.value,
            }
        )
        return AlertRecord.from_payload(payload, status, received_at)

    return make
