"""Fixtures for the notifier's tests (plan Step 26).

Secrets Manager and SQS are moto; Slack is an httpx mock transport that records
every body posted to it; CloudWatch's metric read is a stub answering with the
response shape of GetMetricData. The webhook URL is generated per test, so a
test can search all output for it.
"""

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from botocore.exceptions import ClientError

from agents.notifier.notifier import Notifier, NotifierSettings
from agents.telemetry import Telemetry

ALARM_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cloudwatch" / "dead-letters-waiting.json"
)
ALARM_NAME = "sre-lab-dead-letters-waiting"
OPS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:sre-lab-ops-alarms"


@dataclass
class FakeSlack:
    """An incoming webhook. Each post takes the next answer: a status code or an exception."""

    url: str
    answers: list[int | type[httpx.HTTPError]] = field(default_factory=list)
    bodies: list[Any] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        self.bodies.append(json.loads(request.content))
        answer = self.answers.pop(0) if self.answers else 200
        if isinstance(answer, int):
            return httpx.Response(answer, text="ok" if answer == 200 else "no_service")
        raise answer("refused by the test", request=request)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))


class StubCloudWatch:
    """GetMetricData for the queue's ApproximateAgeOfOldestMessage, or a refusal."""

    def __init__(self, oldest_seconds: float | None = 420.0, refuse: bool = False) -> None:
        self.oldest_seconds = oldest_seconds
        self.refuse = refuse
        self.queries: list[Any] = []

    def get_metric_data(self, **arguments: Any) -> Any:
        self.queries.append(arguments)
        if self.refuse:
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "refused by the test"}},
                "GetMetricData",
            )
        values = [] if self.oldest_seconds is None else [self.oldest_seconds, 60.0]
        return {"MetricDataResults": [{"Id": "oldest", "Label": "oldest", "Values": values}]}


@dataclass
class NotifierUnderTest:
    notifier: Notifier
    slack: FakeSlack
    cloudwatch: StubCloudWatch
    sleeps: list[float]


def alarm_event(**changes: Any) -> dict[str, Any]:
    """The SNS event the operations topic gives the notifier for one alarm message."""
    alarm = json.loads(ALARM_FIXTURE.read_text(encoding="utf-8"))
    alarm.update(changes)
    return {
        "Records": [
            {
                "EventSource": "aws:sns",
                "EventVersion": "1.0",
                "Sns": {
                    "Type": "Notification",
                    "TopicArn": OPS_TOPIC_ARN,
                    "Subject": f'ALARM: "{ALARM_NAME}" in US East (N. Virginia)',
                    "Message": json.dumps(alarm),
                    "Timestamp": "2026-11-13T10:01:12.512Z",
                },
            }
        ]
    }


@pytest.fixture
def webhook_url() -> str:
    """A synthetic incoming-webhook URL, new for each test."""
    return (
        "https://hooks.slack.com/services/"
        f"T{secrets.token_hex(4).upper()}/B{secrets.token_hex(4).upper()}/{secrets.token_urlsafe(18)}"
    )


@pytest.fixture
def make_notifier(pipeline: Any, webhook_url: str) -> Callable[..., NotifierUnderTest]:
    """Build the notifier on moto's queue and secret, with the fake Slack and no sleeping."""
    settings = NotifierSettings(
        dead_letter_queue_url=pipeline.dead_letter_queue_url, dead_letter_alarm_name=ALARM_NAME
    )

    def make(
        *,
        answers: list[Any] | None = None,
        cloudwatch: StubCloudWatch | None = None,
        sqs: Any = None,
        store_secret: str | None = webhook_url,
    ) -> NotifierUnderTest:
        if store_secret is not None:
            pipeline.session.client("secretsmanager").create_secret(
                Name=settings.webhook_credential_name, SecretString=store_secret
            )
        slack = FakeSlack(webhook_url, list(answers or []))
        sleeps: list[float] = []
        stub = cloudwatch or StubCloudWatch()
        notifier = Notifier(
            settings,
            secrets=pipeline.session.client("secretsmanager"),
            sqs=sqs or pipeline.sqs,
            cloudwatch=stub,  # type: ignore[arg-type]
            http=slack.client(),
            telemetry=Telemetry("notifier"),
            sleep=sleeps.append,
        )
        return NotifierUnderTest(notifier, slack, stub, sleeps)

    return make


@pytest.fixture
def make_alarm_event() -> Callable[..., dict[str, Any]]:
    return alarm_event


@pytest.fixture
def stub_cloudwatch() -> type[StubCloudWatch]:
    return StubCloudWatch
