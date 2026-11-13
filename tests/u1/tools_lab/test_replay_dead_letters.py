"""Tests of tools/lab/replay_dead_letters.py (plan Step 28): each item replays by its own path.

SQS and DynamoDB are moto. The deployed intake function is stood in for by
``IntakeFunction``, which answers the two Lambda calls the script makes,
GetFunctionConfiguration and Invoke, by running the real intake on the same moto
table and queues. So a replay really applies, and idempotency really holds.
"""

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from agents.contracts.dead_letter import DeadLetterItem, DeadLetterKind, DeadLetterReason
from agents.contracts.incident import EscalationReason, IncidentPatch, IncidentStatus
from agents.contracts.session import SessionKind, SessionStartRequest
from agents.intake.intake import Intake, IntakeSettings
from agents.ledger.ledger import IncidentLedger
from agents.telemetry import Telemetry

ON_FAILURE_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "lambda" / "intake-on-failure.json"
)
LAB_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:sre-lab-alerts"
FAILED_AT = datetime(2026, 11, 13, 10, 0, tzinfo=UTC)


class IntakeFunction:
    """The intake function as the script sees it, running the real intake in-process."""

    def __init__(self, pipeline: Any, fake_clock: Any) -> None:
        settings = IntakeSettings(
            lab_topic_arn=LAB_TOPIC_ARN,
            incident_table_name=pipeline.table_name,
            session_start_queue_url=pipeline.session_start_queue_url,
            dead_letter_queue_url=pipeline.dead_letter_queue_url,
        )
        self.ledger = IncidentLedger(
            pipeline.dynamodb,
            pipeline.table_name,
            metrics=Telemetry("ledger"),
            clock=fake_clock.now,
        )
        self.intake = Intake(settings, self.ledger, pipeline.sqs, clock=fake_clock.now)
        self.invocations: list[Any] = []
        self.timing_out = False

    def get_function_configuration(self, FunctionName: str) -> Any:  # noqa: N803 - AWS's name
        return {
            "FunctionName": FunctionName,
            "Environment": {"Variables": {"LAB_TOPIC_ARN": LAB_TOPIC_ARN}},
        }

    def invoke(self, FunctionName: str, InvocationType: str, Payload: bytes) -> Any:  # noqa: N803
        assert (FunctionName, InvocationType) == ("sre-lab-intake", "RequestResponse")
        event = json.loads(Payload)
        self.invocations.append(event)
        if self.timing_out:
            error = {
                "errorType": "Sandbox.Timedout",
                "errorMessage": "Task timed out after 60.06 seconds",
            }
            return {
                "StatusCode": 200,
                "FunctionError": "Unhandled",
                "Payload": io.BytesIO(json.dumps(error).encode()),
            }
        result = self.intake.handle(event)
        return {"StatusCode": 200, "Payload": io.BytesIO(json.dumps(result).encode())}


def run(script: ModuleType, pipeline: Any, function: IntakeFunction) -> int:
    """Run the script once, as you would, with items that stay visible again at once."""
    return int(
        script.main(["--visibility-seconds", "0"], session=pipeline.session, lambda_client=function)
    )


def intake_item(
    original: str, dead_letter_id: str, kind: DeadLetterKind = DeadLetterKind.ALERT
) -> str:
    reason = (
        DeadLetterReason.SESSION_START_FAILED
        if kind is DeadLetterKind.SESSION_START
        else DeadLetterReason.STORE_UNAVAILABLE
    )
    item = DeadLetterItem(
        dead_letter_id=dead_letter_id,
        kind=kind,
        reason=reason,
        original=original,
        first_failed_at=FAILED_AT,
        attempts=3,
    )
    return item.model_dump_json()


def session_start(incident_id: str) -> str:
    request = SessionStartRequest(
        schema_version=1, incident_id=incident_id, kind=SessionKind.INCIDENT, requested_at=FAILED_AT
    )
    return request.model_dump_json()


def dead_letter(pipeline: Any, *bodies: str) -> None:
    for body in bodies:
        pipeline.sqs.send_message(QueueUrl=pipeline.dead_letter_queue_url, MessageBody=body)


def test_req_140_intake_item_is_replayed_through_the_intake_and_deleted(
    replay_dead_letters: ModuleType,
    pipeline: Any,
    fake_clock: Any,
    alertmanager: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-140.1, REQ-033: an alert the intake dead-lettered goes back through the intake (BR6.6).

    Its original notification is sent as a message from the lab topic; once the
    intake has applied it, the item is deleted. The output names the item and
    the result, never its content.
    """
    function = IntakeFunction(pipeline, fake_clock)
    message = alertmanager.message("firing-payment")
    dead_letter(pipeline, intake_item(message, "01JD0000000000000000000001"))

    assert run(replay_dead_letters, pipeline, function) == 0

    (incident,) = pipeline.incidents()
    assert incident.service == "payment"
    (event,) = function.invocations
    assert (event["Records"][0]["Sns"]["TopicArn"], event["Records"][0]["Sns"]["Message"]) == (
        LAB_TOPIC_ARN,
        message,
    )
    assert pipeline.dead_letters() == []
    out = capsys.readouterr().out
    assert (
        "dead-letter item: 01JD0000000000000000000001 (alert, store_unavailable): replayed through "
        "the intake: alerts 1, created 1, session_starts 1"
    ) in out
    assert "1 item(s) read; 1 replayed or dropped; 0 left in the queue." in out
    assert "PaymentErrorRatioHigh" not in out


def test_req_140_on_failure_record_is_unwrapped_and_its_event_replayed(
    replay_dead_letters: ModuleType,
    pipeline: Any,
    fake_clock: Any,
    alertmanager: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-140.1: the intake's on-failure record, left after the platform's retries (RD-1, RD-7).

    The SNS event it carries goes back to the intake as it was, and the record
    is deleted once the alert is applied.
    """
    function = IntakeFunction(pipeline, fake_clock)
    record = json.loads(ON_FAILURE_FIXTURE.read_text(encoding="utf-8"))
    record["requestPayload"] = alertmanager.sns_event(alertmanager.message("firing-payment"))
    dead_letter(pipeline, json.dumps(record))

    assert run(replay_dead_letters, pipeline, function) == 0

    assert function.invocations == [record["requestPayload"]]
    assert len(pipeline.incidents()) == 1
    assert pipeline.dead_letters() == []
    out = capsys.readouterr().out
    assert (
        "on-failure record: d1c6a2f4-8e3b-4c7a-9f05-6b2e1d4a8c93: replayed through the intake"
        in out
    )


def test_req_140_session_starts_go_back_to_the_session_start_queue(
    replay_dead_letters: ModuleType,
    pipeline: Any,
    fake_clock: Any,
    alertmanager: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-140.1: session starts, redriven from their queue or dead-lettered by the intake.

    Each one's incident is still open with no session started, so each request
    goes back on the session-start queue, where the starter takes it (BR6.6, W2).
    """
    function = IntakeFunction(pipeline, fake_clock)
    cart = alertmanager.alert("c18e6f40b2d97a35", service="cart", alertname="CartErrorRatioHigh")
    for message in (alertmanager.message("firing-payment"), alertmanager.render([cart])):
        function.intake.handle(alertmanager.sns_event(message))
    payment_id, cart_id = (
        incident.incident_id
        for incident in sorted(pipeline.incidents(), key=lambda i: i.service != "payment")
    )
    pipeline.session_starts()
    dead_letter(
        pipeline,
        session_start(payment_id),
        intake_item(
            session_start(cart_id), "01JD0000000000000000000002", DeadLetterKind.SESSION_START
        ),
    )

    assert run(replay_dead_letters, pipeline, function) == 0

    sent = sorted(
        start["incident_id"] for start in pipeline.drain(pipeline.session_start_queue_url)
    )
    assert sent == sorted([payment_id, cart_id])
    assert pipeline.dead_letters() == []
    assert capsys.readouterr().out.count("sent back to the session-start queue") == 2


def test_req_140_session_start_for_a_finished_or_started_incident_is_dropped_with_its_reason(
    replay_dead_letters: ModuleType,
    pipeline: Any,
    fake_clock: Any,
    alertmanager: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-140.1: a session start replays only for an open incident with no session (BR6.6).

    One incident is escalated, one has its session running, and one does not
    exist: each request is dropped, deleted, and its reason printed (BR4.4).
    """
    function = IntakeFunction(pipeline, fake_clock)
    cart = alertmanager.alert("c18e6f40b2d97a35", service="cart", alertname="CartErrorRatioHigh")
    for message in (alertmanager.message("firing-payment"), alertmanager.render([cart])):
        function.intake.handle(alertmanager.sns_event(message))
    ended, running = (incident.incident_id for incident in pipeline.incidents())
    now = fake_clock.now()
    for incident_id in (ended, running):
        function.ledger.advance(
            incident_id, IncidentStatus.INVESTIGATING, IncidentPatch(session_started=now)
        )
    function.ledger.advance(
        ended,
        IncidentStatus.ESCALATED,
        IncidentPatch(escalation_reason=EscalationReason.READ_FAILED),
    )
    pipeline.session_starts()
    dead_letter(
        pipeline,
        session_start(ended),
        session_start(running),
        session_start("01JD0000000000000000000009"),
    )

    assert run(replay_dead_letters, pipeline, function) == 0

    assert pipeline.session_starts() == []
    assert pipeline.dead_letters() == []
    out = capsys.readouterr().out
    assert f"session start: incident {ended}: dropped: incident_terminal" in out
    assert f"session start: incident {running}: dropped: session_already_started" in out
    assert "session start: incident 01JD0000000000000000000009: dropped: incident_not_found" in out


def test_req_141_running_twice_is_safe_and_what_fails_stays_queued(
    replay_dead_letters: ModuleType,
    pipeline: Any,
    fake_clock: Any,
    alertmanager: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-141.1, REQ-140.1: replaying the same alert again has no double effect (BR2.2, BR6.6).

    Two copies of one dead-lettered alert, then a third in a second run, leave one
    alert on one incident and one session start. An item that is not one of the
    three shapes, and one the intake fails on, stay in the queue, and the run
    says so in its exit status.
    """
    function = IntakeFunction(pipeline, fake_clock)
    message = alertmanager.message("firing-payment")
    dead_letter(
        pipeline,
        intake_item(message, "01JD0000000000000000000003"),
        intake_item(message, "01JD0000000000000000000004"),
        "not a dead-letter item",
    )

    assert run(replay_dead_letters, pipeline, function) == 1
    dead_letter(pipeline, intake_item(message, "01JD0000000000000000000005"))
    assert run(replay_dead_letters, pipeline, function) == 1

    (incident,) = pipeline.incidents()
    assert (incident.alert_count, incident.version) == (1, 1)
    assert len(pipeline.session_starts()) == 1
    out = capsys.readouterr().out
    assert out.count("replayed through the intake: alerts 1, duplicate 1") == 2
    assert out.count("unrecognised: not JSON: left in the queue") == 2

    function.timing_out = True
    late = alertmanager.alert(
        "e94d27a6b0c35f18", service="checkout", alertname="CheckoutLatencyHigh"
    )
    dead_letter(pipeline, intake_item(alertmanager.render([late]), "01JD0000000000000000000006"))
    assert run(replay_dead_letters, pipeline, function) == 1

    assert (
        "not replayed: the intake failed (Sandbox.Timedout); left in the queue"
        in capsys.readouterr().out
    )
    left = pipeline.dead_letters()
    assert "not a dead-letter item" in left
    assert [item["dead_letter_id"] for item in left if isinstance(item, dict)] == [
        "01JD0000000000000000000006"
    ]
    assert [incident.service for incident in pipeline.incidents()] == ["payment"]
