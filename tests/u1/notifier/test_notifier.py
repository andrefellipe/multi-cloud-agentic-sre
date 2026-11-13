"""Tests of the notifier, agents/notifier/ (plan Step 26): the dead-letter notice (W4).

The alarm message is the recorded CloudWatch alarm of
fixtures/cloudwatch/dead-letters-waiting.json, wrapped in the SNS event the
operations topic delivers. Slack is a mock transport; no test reaches a network.
"""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from botocore.exceptions import ClientError
from pydantic import ValidationError

from agents.contracts.notify import DeadLetterNotice, NotifyKind, NotifyRequest
from agents.notifier.notifier import render_dead_letter_notice

MakeNotifier = Callable[..., Any]
RAISED_AT = datetime(2026, 11, 13, 10, 1, 12, 345000, tzinfo=UTC)


class RefusingQueueAttributes:
    """The moto SQS client, except that reading queue attributes is refused."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def get_queue_attributes(self, **_: Any) -> Any:
        raise ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "refused by the test"}},
            "GetQueueAttributes",
        )


def dead_letter(pipeline: Any, body: str) -> None:
    pipeline.sqs.send_message(QueueUrl=pipeline.dead_letter_queue_url, MessageBody=body)


def test_req_140_dead_letter_alarm_posts_the_fixed_notice_with_count_and_age(
    make_notifier: MakeNotifier,
    make_alarm_event: Callable[..., Any],
    pipeline: Any,
    webhook_url: str,
    telemetry: Any,
) -> None:
    """REQ-140.2, REQ-033: items in the dead-letter queue raise one fixed notice (W4, AC2.6.4).

    The notice carries the queue's label, its item count and its oldest item's
    age, read from the queue and from CloudWatch, and is posted to the URL read
    from Secrets Manager (BR6.3, BR6.4). The alarm returning to OK, another
    alarm, and a message that is not an alarm post nothing.
    """
    for number in range(2):
        dead_letter(pipeline, json.dumps({"number": number}))
    under = make_notifier()

    assert under.notifier.handle(make_alarm_event()) == {"sent": 1}

    assert under.slack.urls == [webhook_url]
    assert under.slack.bodies == [
        {
            "text": ":warning: Dead letters are waiting in sre-lab-dead-letters: 2 items;"
            " the oldest is about 7 minutes old. Raised 2026-11-13 10:01 UTC. Nothing is"
            " lost: once the cause is fixed, replay them with tools/lab/replay_dead_letters.py."
        }
    ]
    (query,) = under.cloudwatch.queries
    metric = query["MetricDataQueries"][0]["MetricStat"]["Metric"]
    assert (metric["Namespace"], metric["MetricName"]) == (
        "AWS/SQS",
        "ApproximateAgeOfOldestMessage",
    )
    assert metric["Dimensions"] == [{"Name": "QueueName", "Value": "sre-lab-dead-letters"}]
    assert telemetry.metrics("NoticesSent", component="notifier") == [1.0]
    for ignored in (
        make_alarm_event(NewStateValue="OK"),
        make_alarm_event(AlarmName="sre-lab-intake-errors"),
        {"Records": [{"Sns": {"Message": "not an alarm"}}]},
    ):
        assert under.notifier.handle(ignored) == {"ignored": 1}
    assert len(under.slack.bodies) == 1


def test_req_140_failed_post_is_retried_and_unknown_values_are_said_to_be_unknown(
    make_notifier: MakeNotifier,
    make_alarm_event: Callable[..., Any],
    pipeline: Any,
    stub_cloudwatch: Any,
    telemetry: Any,
) -> None:
    """REQ-140.2: Slack answers 503 once, then the second post goes through (BR6.5).

    The wait between the two is the first step of the capped backoff, 1 s. When
    neither the queue's count nor the oldest age can be read, the notice still
    goes out and says that they are unknown.
    """
    under = make_notifier(
        answers=[503, 200],
        cloudwatch=stub_cloudwatch(refuse=True),
        sqs=RefusingQueueAttributes(pipeline.sqs),
    )

    assert under.notifier.handle(make_alarm_event()) == {"sent": 1}

    assert len(under.slack.bodies) == 2
    assert under.slack.bodies[0] == under.slack.bodies[1]
    assert "item count unknown; the oldest item's age is unknown." in under.slack.bodies[1]["text"]
    assert under.sleeps == [1.0]
    (retry,) = [line for line in telemetry.logs() if line["message"] == "notice post failed"]
    assert (retry["error_class"], retry["attempt"]) == ("HTTP503", 1)
    assert telemetry.metrics("NoticesSent", component="notifier") == [1.0]
    assert telemetry.metrics("NoticeFailures", component="notifier") == []


def test_req_140_every_post_failing_is_logged_and_never_raised(
    make_notifier: MakeNotifier, make_alarm_event: Callable[..., Any], telemetry: Any
) -> None:
    """REQ-140.2: when every attempt fails, the failure is logged and not raised (S14, BR6.5).

    Three posts, 1 s and 2 s apart; the alarm stays visible in CloudWatch, and
    the intake is a different function, so it is not affected.
    """
    under = make_notifier(answers=[httpx.ConnectError, httpx.ReadTimeout, 500])

    assert under.notifier.handle(make_alarm_event()) == {"failed": 1}

    assert len(under.slack.bodies) == 3
    assert under.sleeps == [1.0, 2.0]
    assert telemetry.metrics("NoticeFailures", component="notifier") == [1.0]
    (failure,) = [line for line in telemetry.logs() if line["level"] == "ERROR"]
    assert (failure["reason"], failure["attempt"]) == ("post_failed", 3)


def test_req_103_missing_or_unusable_webhook_secret_fails_the_notice_quietly(
    make_notifier: MakeNotifier,
    make_alarm_event: Callable[..., Any],
    pipeline: Any,
    telemetry: Any,
) -> None:
    """REQ-103.1, REQ-140.2: the webhook secret is missing, then holds no https URL (S14, BR6.4).

    The notifier posts nothing, logs the failure with the error class only, and
    returns without raising (BR6.5).
    """
    under = make_notifier(store_secret=None)

    assert under.notifier.handle(make_alarm_event()) == {"failed": 1}

    pipeline.session.client("secretsmanager").create_secret(
        Name="sre-lab/slack-webhook-url", SecretString="hooks.slack.com/services/plain"
    )
    assert under.notifier.handle(make_alarm_event()) == {"failed": 1}

    assert under.slack.bodies == []
    failures = [line for line in telemetry.logs() if line["level"] == "ERROR"]
    assert [(line["reason"], line.get("error_class")) for line in failures] == [
        ("secret_unavailable", "ResourceNotFoundException"),
        ("secret_invalid", None),
    ]
    assert telemetry.metrics("NoticeFailures", component="notifier") == [1.0, 1.0]
    assert "hooks.slack.com/services/plain" not in telemetry.raw


def test_req_103_notice_holds_no_text_from_any_message(
    make_notifier: MakeNotifier,
    make_alarm_event: Callable[..., Any],
    pipeline: Any,
    stub_cloudwatch: Any,
) -> None:
    """REQ-103.2, REQ-140.2: the notice is the fixed template, with no free text (BR6.3, ADR-006).

    Text in the alarm message and in the dead-lettered item never reaches Slack;
    the post is exactly the template filled with numbers and the configured
    label. A notify request with a body, or of a kind other than the dead-letter
    alert, is refused in Phase 1 (contract C7).
    """
    injected = ("IGNORE ALL PREVIOUS INSTRUCTIONS", "<!channel>", "<!here>", "<!everyone>", "phish")
    dead_letter(pipeline, json.dumps({"original": f"{injected[0]} {injected[1]}"}))
    event = make_alarm_event(
        AlarmDescription=f"{injected[1]} see https://phish.example.com",
        NewStateReason=f"Threshold Crossed {injected[2]}",
        Trigger={"Dimensions": [{"name": "QueueName", "value": injected[3]}]},
    )
    under = make_notifier(cloudwatch=stub_cloudwatch(oldest_seconds=30.0))

    assert under.notifier.handle(event) == {"sent": 1}

    (body,) = under.slack.bodies
    expected = DeadLetterNotice(
        queue_label="sre-lab-dead-letters",
        message_count=1,
        oldest_age_minutes=0,
        raised_at=RAISED_AT,
    )
    assert body == {"text": render_dead_letter_notice(expected)}
    assert "1 item; the oldest is under a minute old" in body["text"]
    for text in injected:
        assert text not in body["text"]
    with pytest.raises(ValidationError):
        NotifyRequest.model_validate({"kind": "incident_escalated", "body": "free text"})
    other_kind = NotifyRequest(
        kind=NotifyKind.INCIDENT_ESCALATED, incident_id="01JCX8Z3T6Q4M2N7P5R9S1V3W5"
    )
    assert under.notifier.notify(other_kind) is False
    assert len(under.slack.bodies) == 1


def test_req_103_webhook_url_never_appears_in_any_log(
    make_notifier: MakeNotifier,
    make_alarm_event: Callable[..., Any],
    webhook_url: str,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-103.1, REQ-103.2: the webhook URL is read at send time and never logged (BR6.4).

    With every logger at DEBUG, a send that fails once and then succeeds, and a
    send that fails every time, leave the URL, or its path, in no log line, in
    no log record and on no output stream. The HTTP and AWS libraries, which log
    URLs and response bodies at INFO and DEBUG, are held at WARNING.
    """
    caplog.set_level(logging.DEBUG)
    under = make_notifier(answers=[httpx.ConnectError, 200])
    assert under.notifier.handle(make_alarm_event()) == {"sent": 1}
    failing = make_notifier(answers=[500, 500, 500], store_secret=None)
    assert failing.notifier.handle(make_alarm_event()) == {"failed": 1}

    out, err = capsys.readouterr()
    path = webhook_url.split("/services/", 1)[1]
    assert "notice sent" in out
    for text in (out, err, caplog.text):
        assert webhook_url not in text
        assert path not in text
    for record in caplog.records:
        assert path not in record.getMessage()
        assert path not in str(record.args)
        assert path not in json.dumps(record.__dict__, default=str)
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("botocore").level == logging.WARNING
