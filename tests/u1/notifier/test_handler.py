"""Tests of the notifier's Lambda entry point, agents/notifier/handler.py (plan Step 30).

The handler builds the notifier from the function's environment against moto
Secrets Manager, SQS and CloudWatch. The HTTP client it builds is given a mock
transport, so no request leaves the test.
"""

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from agents.notifier import handler


@pytest.fixture
def fresh_handler() -> Iterator[None]:
    """The handler builds its notifier once per environment; each test starts a new one."""
    handler._notifier.cache_clear()
    yield
    handler._notifier.cache_clear()


@pytest.fixture
def slack_posts(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Every body the handler's own HTTP client posts, answered 200 by a mock transport."""
    posts: list[Any] = []

    def answer(request: httpx.Request) -> httpx.Response:
        posts.append(json.loads(request.content))
        return httpx.Response(200, text="ok")

    real_client = httpx.Client
    monkeypatch.setattr(
        handler.httpx,
        "Client",
        lambda **options: real_client(transport=httpx.MockTransport(answer), **options),
    )
    return posts


def test_req_140_notifier_handler_wires_queue_secret_and_slack(
    fresh_handler: None,
    slack_posts: list[Any],
    monkeypatch: pytest.MonkeyPatch,
    pipeline: Any,
    webhook_url: str,
    make_alarm_event: Callable[..., Any],
) -> None:
    """REQ-140.2, REQ-103.1: the Lambda entry point sends the notice from its environment alone.

    The queue comes from DEAD_LETTER_QUEUE_URL, the alarm from
    DEAD_LETTER_ALARM_NAME, and the webhook from the secret the code names by
    default. CloudWatch has no age datapoint yet, so the age is unknown.
    """
    monkeypatch.setenv("DEAD_LETTER_QUEUE_URL", pipeline.dead_letter_queue_url)
    monkeypatch.setenv("DEAD_LETTER_ALARM_NAME", "sre-lab-dead-letters-waiting")
    pipeline.session.client("secretsmanager").create_secret(
        Name="sre-lab/slack-webhook-url", SecretString=webhook_url
    )
    pipeline.sqs.send_message(QueueUrl=pipeline.dead_letter_queue_url, MessageBody="{}")

    assert handler.handler(make_alarm_event(), None) == {"sent": 1}

    (post,) = slack_posts
    assert "sre-lab-dead-letters: 1 item; the oldest item's age is unknown." in post["text"]


def test_req_140_notifier_that_cannot_start_counts_a_failure_and_never_raises(
    fresh_handler: None,
    slack_posts: list[Any],
    monkeypatch: pytest.MonkeyPatch,
    pipeline: Any,
    make_alarm_event: Callable[..., Any],
    telemetry: Any,
) -> None:
    """REQ-140.2: a notifier missing a setting returns a failure instead of raising (BR6.5).

    The failure is counted on NoticeFailures, whose alarm shows it, and logged
    with its error class; nothing is posted.
    """
    monkeypatch.setenv("DEAD_LETTER_QUEUE_URL", pipeline.dead_letter_queue_url)
    monkeypatch.delenv("DEAD_LETTER_ALARM_NAME", raising=False)

    assert handler.handler(make_alarm_event(), None) == {"failed": 1}

    assert slack_posts == []
    assert telemetry.metrics("NoticeFailures", component="notifier") == [1.0]
    (failure,) = telemetry.logs()
    assert (failure["reason"], failure["error_class"]) == ("start_up", "SettingsError")
