"""Fixtures for the intake's tests (plan Step 24): the intake on moto, and failing AWS calls."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from botocore.exceptions import ClientError

from agents.intake.intake import Intake, IntakeSettings
from agents.ledger.ledger import IncidentLedger
from agents.telemetry import Telemetry

ALLOWED_LOG_FIELDS = {
    "level",
    "location",
    "message",
    "timestamp",
    "service",
    "component",
    "incident_id",
    "key_prefix",
    "session_id",
    "outcome",
    "reason",
    "error_class",
    "duration_ms",
    "attempt",
}
"""The Powertools envelope, plus OD-2's allow-list."""


def client_error(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "refused by the test"}}, operation)


class DenyingTable:
    """The moto DynamoDB client, except that every transaction is refused (scenario S6)."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.refused = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def transact_write_items(self, **_: Any) -> Any:
        self.refused += 1
        raise client_error("AccessDeniedException", "TransactWriteItems")


class FailingQueues:
    """The moto SQS client, except that sends to the queues in ``failing`` are refused."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.failing: set[str] = set()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def send_message(self, **arguments: Any) -> Any:
        if arguments["QueueUrl"] in self.failing:
            raise client_error("AWS.SimpleQueueService.NonExistentQueue", "SendMessage")
        return self._client.send_message(**arguments)


class ExplodingLedger:
    """A ledger with a bug: every write raises something no one expected (BR6.2)."""

    def apply_alert(self, *_: Any) -> Any:
        raise RuntimeError("payment PaymentErrorRatioHigh a3f9c2e17b4d6085")


@dataclass
class IntakeUnderTest:
    intake: Intake
    ledger: Any
    sleeps: list[float]


@pytest.fixture
def make_intake(pipeline: Any, fake_clock: Any) -> Callable[..., IntakeUnderTest]:
    """Build the intake on the moto table and queues, with the fake clock and no sleeping."""
    settings = IntakeSettings(
        lab_topic_arn="arn:aws:sns:us-east-1:123456789012:sre-lab-alerts",
        incident_table_name=pipeline.table_name,
        session_start_queue_url=pipeline.session_start_queue_url,
        dead_letter_queue_url=pipeline.dead_letter_queue_url,
    )

    def make(dynamodb: Any = None, sqs: Any = None, ledger: Any = None) -> IntakeUnderTest:
        sleeps: list[float] = []
        ledger = ledger or IncidentLedger(
            dynamodb or pipeline.dynamodb,
            pipeline.table_name,
            settings.skeleton,
            metrics=Telemetry("ledger"),
            clock=fake_clock.now,
            sleep=sleeps.append,
        )
        intake = Intake(
            settings,
            ledger,
            sqs or pipeline.sqs,
            telemetry=Telemetry("intake"),
            clock=fake_clock.now,
        )
        return IntakeUnderTest(intake, ledger, sleeps)

    return make


@pytest.fixture
def denying_table() -> Callable[[Any], DenyingTable]:
    return DenyingTable


@pytest.fixture
def failing_queues() -> Callable[[Any], FailingQueues]:
    return FailingQueues


@pytest.fixture
def exploding_ledger() -> ExplodingLedger:
    return ExplodingLedger()


@pytest.fixture
def allowed_log_fields() -> set[str]:
    return ALLOWED_LOG_FIELDS
