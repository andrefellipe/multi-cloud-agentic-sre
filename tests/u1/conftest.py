"""Fixtures shared by u1's tests.

AWS is moto, in-process, with fake credentials and no profile, so no test reaches
a network or a real account. The incident table and the two queues are created
here with the same shape as ``infra/aws/permanent``.

Alert manager messages: assumption A-01 (``functional-spec.md``) is still open,
since no real message reached a subscriber before u1's third pull request. The
messages in ``fixtures/alertmanager/`` are therefore rendered by hand from the
template the alert manager uses (``infra/aws/permanent/templates/alertmanager.yaml.tftpl``),
character for character, with the labels the real ``PaymentErrorRatioHigh``
alert fired with on 2026-11-12. :meth:`Alertmanager.render` produces the same
text for scenario and burst messages. Every account ID, address and value here
is synthetic: ``123456789012`` is AWS's documentation account.
"""

import json
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws

from agents.contracts.incident import Incident
from agents.ledger.items import from_item

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REGION = "us-east-1"
ACCOUNT_ID = "123456789012"
LAB_TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCOUNT_ID}:sre-lab-alerts"
TABLE_NAME = "sre-lab-incidents"
SESSION_START_QUEUE = "sre-lab-session-starts"
DEAD_LETTER_QUEUE = "sre-lab-dead-letters"
DEMO_LABELS = {"cloud": "aws", "cluster": "sre-lab-eks"}

JSON = dict[str, Any]


def read_fixture(relative: str) -> str:
    """Return a fixture file's text, without the one final newline the file ends with."""
    text = (FIXTURES / relative).read_text(encoding="utf-8")
    return text.removesuffix("\n")


@dataclass(frozen=True)
class AlertSpec:
    """One alert as the alert manager renders it into a message."""

    fingerprint: str
    labels: dict[str, str]
    starts_at: str
    status: str = "firing"
    ends_at: str = "0001-01-01T00:00:00Z"


class Alertmanager:
    """Builds alert manager messages, and the SNS events that carry them to the intake."""

    def message(self, name: str) -> str:
        """A recorded message from ``fixtures/alertmanager/<name>.txt``."""
        return read_fixture(f"alertmanager/{name}.txt")

    @staticmethod
    def alert(
        fingerprint: str,
        *,
        service: str,
        severity: str = "critical",
        alertname: str = "PaymentErrorRatioHigh",
        starts_at: str = "2026-11-12T23:32:04.587Z",
        status: str = "firing",
        **extra_labels: str,
    ) -> AlertSpec:
        labels = {"alertname": alertname, "service": service, "severity": severity}
        return AlertSpec(fingerprint, {**DEMO_LABELS, **labels, **extra_labels}, starts_at, status)

    @staticmethod
    def render(alerts: Sequence[AlertSpec], status: str | None = None) -> str:
        """Render a notification exactly as the template ``sns.default.message`` does."""
        group_status = status or (
            "firing" if any(a.status == "firing" for a in alerts) else "resolved"
        )
        parts = []
        for index, alert in enumerate(alerts):
            labels = ", ".join(
                f'"{name}": "{value}"' for name, value in sorted(alert.labels.items())
            )
            parts.append(
                ("," if index else "")
                + f'\n  {{ "status": "{alert.status}",'
                + f'\n    "labels": {{{labels}}},'
                + f'\n    "startsAt": "{alert.starts_at}",'
                + f'\n    "endsAt": "{alert.ends_at}",'
                + f'\n    "fingerprint": "{alert.fingerprint}" }}'
            )
        head = f'{{ "receiver": "lab-topic", "status": "{group_status}", "alerts": ['
        return head + "".join(parts) + "\n] }"

    @staticmethod
    def sns_event(
        message: str, *, topic_arn: str = LAB_TOPIC_ARN, message_id: str | None = None
    ) -> JSON:
        """The event SNS gives the intake function for one message (one record)."""
        event: JSON = json.loads(read_fixture("sns/lambda-event.json"))
        sns = event["Records"][0]["Sns"]
        sns["Message"] = message
        sns["TopicArn"] = topic_arn
        if message_id is not None:
            sns["MessageId"] = message_id
        return event


@pytest.fixture
def alertmanager() -> Alertmanager:
    return Alertmanager()


@dataclass
class FakeClock:
    """A UTC clock that moves only when a test moves it, at millisecond precision."""

    current: datetime = field(
        default_factory=lambda: datetime(2026, 11, 12, 23, 32, 30, tzinfo=UTC)
    )

    def now(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> datetime:
        self.current += timedelta(**delta)
        return self.current


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """moto for every AWS call, with fake credentials and no profile or config file."""
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with mock_aws():
        yield


@dataclass
class Pipeline:
    """The moto incident table and queues, as infra/aws/permanent creates them."""

    session: boto3.Session
    dynamodb: Any
    sqs: Any
    session_start_queue_url: str
    dead_letter_queue_url: str
    table_name: str = TABLE_NAME

    def items(self, item_type: str) -> list[JSON]:
        """Every item of one type in the table, deserialized."""
        pages = self.dynamodb.get_paginator("scan").paginate(TableName=self.table_name)
        found = [from_item(item) for page in pages for item in page["Items"]]
        return [item for item in found if item.get("item_type") == item_type]

    def incidents(self) -> list[Incident]:
        """Every incident, oldest first (incident IDs are ULIDs)."""
        found = [Incident.model_validate(item) for item in self.items("incident")]
        return sorted(found, key=lambda incident: incident.incident_id)

    def incident(self, incident_id: str) -> Incident:
        (found,) = [i for i in self.incidents() if i.incident_id == incident_id]
        return found

    def events(self) -> dict[str, JSON]:
        """Inbound events by idempotency key."""
        return {item["idempotency_key"]: item for item in self.items("inbound_event")}

    def open_markers(self) -> dict[str, str]:
        """Service to incident ID, for markers that hold an incident."""
        return {
            item["service"]: item["incident_id"]
            for item in self.items("open_incident_marker")
            if "incident_id" in item
        }

    def drain(self, queue_url: str) -> list[Any]:
        """Receive every message on a queue, and keep them hidden for the test.

        Each body is parsed as JSON; a body that is not JSON is returned as text.
        """
        bodies: list[Any] = []
        while True:
            answer = self.sqs.receive_message(
                QueueUrl=queue_url, MaxNumberOfMessages=10, VisibilityTimeout=600
            )
            messages = answer.get("Messages", [])
            if not messages:
                return bodies
            for message in messages:
                try:
                    bodies.append(json.loads(message["Body"]))
                except ValueError:
                    bodies.append(message["Body"])

    def dead_letters(self) -> list[JSON]:
        return self.drain(self.dead_letter_queue_url)

    def session_starts(self) -> list[JSON]:
        return self.drain(self.session_start_queue_url)


def create_pipeline(session: boto3.Session) -> Pipeline:
    """Create the table and the queues in moto, shaped as in infra/aws/permanent."""
    dynamodb = session.client("dynamodb")
    dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    dynamodb.update_time_to_live(
        TableName=TABLE_NAME,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at_epoch"},
    )
    sqs = session.client("sqs")
    dead_letters = sqs.create_queue(
        QueueName=DEAD_LETTER_QUEUE, Attributes={"MessageRetentionPeriod": "1209600"}
    )["QueueUrl"]
    dead_letter_arn = sqs.get_queue_attributes(QueueUrl=dead_letters, AttributeNames=["QueueArn"])[
        "Attributes"
    ]["QueueArn"]
    session_starts = sqs.create_queue(
        QueueName=SESSION_START_QUEUE,
        Attributes={
            "VisibilityTimeout": "30",
            "MessageRetentionPeriod": "86400",
            "RedrivePolicy": json.dumps(
                {"deadLetterTargetArn": dead_letter_arn, "maxReceiveCount": 3}
            ),
        },
    )["QueueUrl"]
    return Pipeline(session, dynamodb, sqs, session_starts, dead_letters)


@pytest.fixture
def pipeline(aws: None) -> Pipeline:
    """A fresh incident table and queues in moto."""
    return create_pipeline(boto3.Session(region_name=REGION))


class InterferingClient:
    """The real DynamoDB client, except that ``before_write`` runs before each of the
    first ``times`` transactions: another writer acting between a read and its write."""

    def __init__(self, client: Any, before_write: Callable[[], None], times: int) -> None:
        self._client = client
        self._before_write = before_write
        self.remaining = times

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def transact_write_items(self, **arguments: Any) -> Any:
        if self.remaining > 0:
            self.remaining -= 1
            self._before_write()
        return self._client.transact_write_items(**arguments)


@pytest.fixture
def interfere() -> Callable[..., InterferingClient]:
    """Wrap a client so that another writer acts before its first ``times`` transactions."""

    def wrap(client: Any, before_write: Callable[[], None], times: int = 1) -> InterferingClient:
        return InterferingClient(client, before_write, times)

    return wrap


@dataclass
class TelemetryCapture:
    """The JSON lines the components printed: Powertools log lines and embedded metrics."""

    read: Callable[[], str]
    lines: list[JSON] = field(default_factory=list)
    raw: str = ""

    def refresh(self) -> None:
        text = self.read()
        self.raw += text
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("{"):
                self.lines.append(json.loads(line))

    def logs(self) -> list[JSON]:
        self.refresh()
        return [line for line in self.lines if "_aws" not in line]

    def metrics(self, name: str, **dimensions: str) -> list[float]:
        """The values emitted for one metric, optionally only those with these dimensions.

        Embedded metric format allows a single value or a list of values.
        """
        self.refresh()
        values: list[float] = []
        for line in self.lines:
            if (
                name in line
                and "_aws" in line
                and all(line.get(k) == v for k, v in dimensions.items())
            ):
                value = line[name]
                values.extend(float(v) for v in (value if isinstance(value, list) else [value]))
        return values

    def metric_dimensions(self) -> list[tuple[str, list[str]]]:
        """Each metric line's metric name and its dimension names, in order."""
        self.refresh()
        found = []
        for line in self.lines:
            if "_aws" in line:
                directive = line["_aws"]["CloudWatchMetrics"][0]
                for metric in directive["Metrics"]:
                    found.append((metric["Name"], list(directive["Dimensions"][0])))
        return found


@pytest.fixture
def telemetry(capsys: pytest.CaptureFixture[str]) -> TelemetryCapture:
    """What the components under test print to standard output, parsed."""
    return TelemetryCapture(read=lambda: capsys.readouterr().out)
