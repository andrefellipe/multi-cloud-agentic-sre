"""Tests of the intake, agents/intake/ (plan Step 24): scenarios S1 to S9, S13 and S15.

The intake runs against moto DynamoDB and SQS, with the recorded alert manager
messages of fixtures/alertmanager/ wrapped in the SNS event Lambda receives.
Each test checks the table and the queues afterwards, and what was logged.
"""

import copy
import json
import random
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from agents.contracts.alert import AlertStatus, idempotency_key
from agents.contracts.dead_letter import DeadLetterItem
from agents.contracts.incident import EscalationReason, IncidentPatch, IncidentStatus
from agents.intake.intake import DeadLetterWriteError

MakeIntake = Callable[..., Any]
FIRING_KEY = idempotency_key(
    "a3f9c2e17b4d6085", datetime(2026, 11, 12, 23, 32, 4, 587000, tzinfo=UTC), AlertStatus.FIRING
)


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def test_req_030_critical_alert_opens_an_incident_and_hands_off_one_session_start(
    make_intake: MakeIntake,
    pipeline: Any,
    alertmanager: Any,
    telemetry: Any,
    allowed_log_fields: set[str],
) -> None:
    """REQ-030, REQ-121.1, REQ-120.6, REQ-103.2: scenario S1, up to the session hand-off.

    The recorded firing alert becomes one open incident with its timestamps; the
    session start goes to the session-start queue as contract C4 (PD-1). The
    metrics of OD-3 are emitted by component, and the log lines carry only the
    allow-listed fields of OD-2, never a label, the fingerprint or the body.
    """
    under = make_intake()

    result = under.intake.handle(alertmanager.sns_event(alertmanager.message("firing-payment")))

    assert result == {"alerts": 1, "created": 1, "session_starts": 1}
    (incident,) = pipeline.incidents()
    assert (incident.service, incident.status, incident.severity) == (
        "payment",
        IncidentStatus.OPEN,
        "critical",
    )
    assert incident.timestamps.alert_fired == at("2026-11-12T23:32:04.587+00:00")
    assert incident.timestamps.record_created == at("2026-11-12T23:32:30+00:00")
    assert pipeline.session_starts() == [
        {
            "schema_version": 1,
            "incident_id": incident.incident_id,
            "kind": "incident",
            "requested_at": "2026-11-12T23:32:30.000Z",
            "attempt": 1,
            "merge_commit_sha": None,
        }
    ]
    assert pipeline.dead_letters() == []
    assert telemetry.metrics("AlertsReceived", component="intake") == [1.0]
    assert telemetry.metrics("IncidentsCreated", component="intake") == [1.0]
    assert telemetry.metrics("AlertToRecordSeconds", component="intake") == [pytest.approx(25.413)]
    assert telemetry.metrics("LedgerWrites", component="ledger") == [1.0]
    assert {tuple(dimensions) for _, dimensions in telemetry.metric_dimensions()} == {
        ("component",)
    }
    logs = telemetry.logs()
    assert all(set(line) <= allowed_log_fields for line in logs)
    (applied,) = [line for line in logs if line["message"] == "alert applied"]
    assert (applied["outcome"], applied["incident_id"], applied["key_prefix"]) == (
        "created",
        incident.incident_id,
        FIRING_KEY[:12],
    )
    for content in ("PaymentErrorRatioHigh", "a3f9c2e17b4d6085", "sre-lab-eks", "lab-topic"):
        assert content not in telemetry.raw


def test_req_140_unusable_messages_are_discarded_or_kept_whole_never_dropped(
    make_intake: MakeIntake,
    pipeline: Any,
    alertmanager: Any,
    telemetry: Any,
    exploding_ledger: Any,
) -> None:
    """REQ-030.1, REQ-140.1, REQ-033: what happens to messages the intake cannot use (S7).

    A message from another topic is discarded, logged and counted, with no
    dead-letter item (BR1.1). A message that is not valid JSON, and an event with
    no records, are kept whole in the dead-letter queue, with no retry (BR1.2).
    An unexpected error keeps the alert too, logging only its error class (BR6.2).
    """
    under = make_intake()
    firing = alertmanager.message("firing-payment")
    other_topic = "arn:aws:sns:us-east-1:123456789012:somebody-elses-topic"
    broken = alertmanager.message("unescaped-quote")

    assert under.intake.handle(alertmanager.sns_event(firing, topic_arn=other_topic)) == {
        "rejected": 1
    }
    assert under.intake.handle(alertmanager.sns_event(broken)) == {"dead_lettered": 1}
    assert under.intake.handle({"Records": []}) == {"dead_lettered": 1}
    exploding = make_intake(ledger=exploding_ledger)
    assert exploding.intake.handle(alertmanager.sns_event(firing)) == {
        "alerts": 1,
        "dead_lettered": 1,
    }

    assert pipeline.incidents() == []
    items = [DeadLetterItem.model_validate(item) for item in pipeline.dead_letters()]
    assert [(i.kind, i.reason, i.attempts) for i in items] == [
        ("alert_notification", "invalid_payload", 1),
        ("alert_notification", "invalid_payload", 1),
        ("alert", "unexpected_error", 1),
    ]
    assert items[0].original == broken
    assert json.loads(items[1].original) == {"Records": []}
    assert items[2].original == firing
    assert telemetry.metrics("NotificationsRejected", component="intake") == [1.0]
    assert telemetry.metrics("IntakeErrors", component="intake") == [1.0]
    assert telemetry.metrics(
        "AlertsDeadLettered", component="intake", reason="invalid_payload"
    ) == [
        1.0,
        1.0,
    ]
    (unexpected,) = [line for line in telemetry.logs() if line["message"] == "unexpected error"]
    assert unexpected["error_class"] == "RuntimeError"
    assert "a3f9c2e17b4d6085" not in telemetry.raw


def test_req_032_redelivered_notification_records_one_alert(
    make_intake: MakeIntake, pipeline: Any, alertmanager: Any, telemetry: Any
) -> None:
    """REQ-032, REQ-141.1: SNS delivers the same notification twice (S2, AC2.6.3).

    The second delivery changes nothing: the incident shows one alert, one
    inbound event and one session start (BR2.1, BR2.2).
    """
    under = make_intake()
    event = alertmanager.sns_event(alertmanager.message("firing-payment"))

    under.intake.handle(event)
    second = under.intake.handle(copy.deepcopy(event))

    assert second == {"alerts": 1, "duplicate": 1}
    (incident,) = pipeline.incidents()
    assert (incident.alert_count, len(incident.alerts), incident.version) == (1, 1, 1)
    assert list(pipeline.events()) == [FIRING_KEY]
    assert len(pipeline.session_starts()) == 1
    assert telemetry.metrics("AlertsDuplicate", component="intake") == [1.0]


def test_req_031_second_alert_for_the_service_attaches_with_no_second_session(
    make_intake: MakeIntake, pipeline: Any, alertmanager: Any, fake_clock: Any
) -> None:
    """REQ-031: a second alert for a service with an open incident attaches to it (S3, AC2.6.2).

    No second session start is handed off (BR3.3, BR4.4).
    """
    under = make_intake()
    under.intake.handle(alertmanager.sns_event(alertmanager.message("firing-payment")))
    fake_clock.advance(seconds=30)
    latency = alertmanager.alert(
        "b7e10f2a3c4d5e6f",
        service="payment",
        alertname="PaymentLatencyHigh",
        severity="warning",
        starts_at="2026-11-12T23:32:40.000Z",
    )

    result = under.intake.handle(alertmanager.sns_event(alertmanager.render([latency])))

    assert result == {"alerts": 1, "attached": 1}
    (incident,) = pipeline.incidents()
    assert [ref.fingerprint for ref in incident.alerts] == ["a3f9c2e17b4d6085", "b7e10f2a3c4d5e6f"]
    assert (incident.alert_count, incident.severity) == (2, "critical")
    assert len(pipeline.session_starts()) == 1


def test_req_035_info_alert_starts_no_session_and_a_later_warning_starts_one(
    make_intake: MakeIntake, pipeline: Any, alertmanager: Any, fake_clock: Any, telemetry: Any
) -> None:
    """REQ-035, REQ-121.1: below the session severities, an alert is only recorded (S4, AC2.6.5).

    The info alert opens an incident with no session (BR4.3). A warning for the
    same service attaches, raises the severity, starts one session, and becomes
    the triggering alert of the latency timestamps; the incident's creation time
    and the first alert's own times stay as they were (BR3.4, BR4.2, BR4.6).
    """
    under = make_intake()
    info = alertmanager.alert(
        "1a2b3c4d5e6f7081",
        service="cart",
        alertname="CartErrorRatioHigh",
        severity="info",
        starts_at="2026-11-12T23:32:10.000Z",
    )
    warning = alertmanager.alert(
        "8090a0b0c0d0e0f0",
        service="cart",
        alertname="CartErrorRatioHigh",
        severity="warning",
        starts_at="2026-11-12T23:33:00.000Z",
    )

    first = under.intake.handle(alertmanager.sns_event(alertmanager.render([info])))
    assert pipeline.session_starts() == []
    later = fake_clock.advance(seconds=40)
    second = under.intake.handle(alertmanager.sns_event(alertmanager.render([warning])))

    assert first == {"alerts": 1, "created": 1}
    assert second == {"alerts": 1, "attached": 1, "session_starts": 1}
    (incident,) = pipeline.incidents()
    assert incident.severity == "warning"
    assert incident.timestamps.alert_fired == at("2026-11-12T23:33:00+00:00")
    assert incident.timestamps.record_created == later
    assert incident.timestamps.session_requested == later
    assert incident.created_at == at("2026-11-12T23:32:30+00:00")
    assert incident.alerts[0].recorded_at == at("2026-11-12T23:32:30+00:00")
    (start,) = pipeline.session_starts()
    assert start["incident_id"] == incident.incident_id
    assert telemetry.metrics("AlertToRecordSeconds", component="intake") == [20.0, 10.0]


def test_req_030_resolved_message_after_escalation_is_recorded_on_its_alert(
    make_intake: MakeIntake, pipeline: Any, alertmanager: Any, fake_clock: Any
) -> None:
    """REQ-030, REQ-141.1: the resolved notification arrives after the incident was escalated (S5).

    Its incident is found through the record of the firing alert, resolved_at is
    set on the matching alert, and the status does not change (BR3.5, BR3.6).
    """
    under = make_intake()
    under.intake.handle(alertmanager.sns_event(alertmanager.message("firing-payment")))
    (incident,) = pipeline.incidents()
    started = fake_clock.advance(seconds=20)
    under.ledger.advance(
        incident.incident_id, IncidentStatus.INVESTIGATING, IncidentPatch(session_started=started)
    )
    under.ledger.advance(
        incident.incident_id,
        IncidentStatus.ESCALATED,
        IncidentPatch(escalation_reason=EscalationReason.SKELETON_READ_DONE),
    )
    resolved_at = fake_clock.advance(minutes=16)

    result = under.intake.handle(alertmanager.sns_event(alertmanager.message("resolved-payment")))

    assert result == {"alerts": 1, "resolved_recorded": 1}
    (incident,) = pipeline.incidents()
    assert incident.status is IncidentStatus.ESCALATED
    assert incident.escalation_reason is EscalationReason.SKELETON_READ_DONE
    assert incident.alerts[0].resolved_at == resolved_at
    assert len(pipeline.session_starts()) == 1


def test_req_033_table_refusing_writes_dead_letters_the_alert_after_three_attempts(
    make_intake: MakeIntake,
    pipeline: Any,
    alertmanager: Any,
    telemetry: Any,
    denying_table: Callable[[Any], Any],
    failing_queues: Callable[[Any], Any],
) -> None:
    """REQ-033, REQ-140.1: the incident table rejects writes (S6, AC2.6.4).

    The ledger makes 3 attempts with jittered backoff, then the alert sits in the
    dead-letter queue with reason store_unavailable and the message as received
    (BR6.1); the alarm on that queue sends the notice. When the dead-letter queue
    refuses the item too, the intake raises, so the platform retries the
    notification and then hands it to the on-failure destination (RD-1).
    """
    table = denying_table(pipeline.dynamodb)
    under = make_intake(dynamodb=table)
    message = alertmanager.message("firing-payment")

    result = under.intake.handle(alertmanager.sns_event(message))

    assert result == {"alerts": 1, "dead_lettered": 1}
    assert table.refused == 3
    assert len(under.sleeps) == 2
    assert under.sleeps[0] <= 0.1
    assert under.sleeps[1] <= 0.2
    (item,) = [DeadLetterItem.model_validate(item) for item in pipeline.dead_letters()]
    assert (item.kind, item.reason, item.attempts, item.original) == (
        "alert",
        "store_unavailable",
        3,
        message,
    )
    assert item.first_failed_at == at("2026-11-12T23:32:30+00:00")
    assert pipeline.incidents() == []
    assert pipeline.events() == {}
    assert pipeline.session_starts() == []
    assert telemetry.metrics("LedgerWriteFailures", component="ledger") == [1.0]
    assert telemetry.metrics(
        "AlertsDeadLettered", component="intake", reason="store_unavailable"
    ) == [1.0]
    (refused,) = [line for line in telemetry.logs() if line["level"] == "ERROR"]
    assert (refused["error_class"], refused["attempt"]) == ("AccessDeniedException", 3)

    queues = failing_queues(pipeline.sqs)
    queues.failing.add(pipeline.dead_letter_queue_url)
    nowhere = make_intake(dynamodb=denying_table(pipeline.dynamodb), sqs=queues)
    with pytest.raises(DeadLetterWriteError):
        nowhere.intake.handle(alertmanager.sns_event(message))
    assert telemetry.metrics("IntakeErrors", component="intake") == [1.0]


def test_req_140_one_bad_alert_is_kept_alone_and_the_rest_apply_in_order(
    make_intake: MakeIntake, pipeline: Any, alertmanager: Any
) -> None:
    """REQ-140.1, REQ-030: one alert in a notification lacks its service label (S8).

    That alert alone is dead-lettered and the other one is processed (BR1.3). A
    grouped notification is applied in order of start time, then fingerprint
    (BR2.4), and labels other than the five kept are dropped (BR1.4).
    """
    under = make_intake()
    partial = alertmanager.message("one-alert-missing-service")
    grouped = alertmanager.message("grouped-checkout")

    first = under.intake.handle(alertmanager.sns_event(partial))
    second = under.intake.handle(alertmanager.sns_event(grouped))

    assert first == {"alerts": 2, "created": 1, "dead_lettered": 1, "session_starts": 1}
    assert second == {"alerts": 3, "attached": 2, "created": 1, "session_starts": 1}
    (item,) = [DeadLetterItem.model_validate(item) for item in pipeline.dead_letters()]
    assert (item.kind, item.reason, item.original) == ("alert", "invalid_payload", partial)
    cart, checkout = sorted(pipeline.incidents(), key=lambda incident: incident.service)
    assert [ref.fingerprint for ref in cart.alerts] == ["c18e6f40b2d97a35"]
    assert [ref.fingerprint for ref in checkout.alerts] == [
        "e94d27a6b0c35f18",
        "0c5e8a91d2b7f436",
        "5b71e0f3c9a8d264",
    ]
    assert checkout.severity == "critical"
    assert checkout.timestamps.alert_fired == at("2026-11-12T23:40:09.730+00:00")
    assert "checkout-7c9d8b6f5" not in json.dumps(pipeline.items("incident"))


def test_req_140_failed_session_hand_off_is_kept_and_requested_again_later(
    make_intake: MakeIntake,
    pipeline: Any,
    alertmanager: Any,
    fake_clock: Any,
    failing_queues: Callable[[Any], Any],
) -> None:
    """REQ-140.1, REQ-141.1: a session start that cannot be handed off is not lost (S9).

    The request is dead-lettered with session_start_failed and the incident stays
    open (BR4.5). Within 120 seconds of the request, a repeat of the same alert
    asks for nothing; after that, the repeat asks again (BR2.5), and so does the
    next new alert for the service while no session has started (BR4.2).
    """
    queues = failing_queues(pipeline.sqs)
    queues.failing.add(pipeline.session_start_queue_url)
    under = make_intake(sqs=queues)
    firing = alertmanager.sns_event(alertmanager.message("firing-payment"))

    assert under.intake.handle(firing) == {"alerts": 1, "created": 1, "dead_lettered": 1}
    (item,) = [DeadLetterItem.model_validate(item) for item in pipeline.dead_letters()]
    (incident,) = pipeline.incidents()
    assert (item.kind, item.reason, item.attempts) == ("session_start", "session_start_failed", 3)
    assert json.loads(item.original)["incident_id"] == incident.incident_id
    assert incident.status is IncidentStatus.OPEN
    queues.failing.clear()

    fake_clock.advance(seconds=60)
    assert under.intake.handle(firing) == {"alerts": 1, "duplicate": 1}
    retried_at = fake_clock.advance(seconds=60)
    assert under.intake.handle(firing) == {"alerts": 1, "duplicate": 1, "session_starts": 1}
    (start,) = pipeline.session_starts()
    assert start["requested_at"] == "2026-11-12T23:34:30.000Z"
    fake_clock.advance(seconds=121)
    another = alertmanager.alert(
        "d4c3b2a1f0e9d8c7", service="payment", starts_at="2026-11-12T23:36:00.000Z"
    )
    assert under.intake.handle(alertmanager.sns_event(alertmanager.render([another]))) == {
        "alerts": 1,
        "attached": 1,
        "session_starts": 1,
    }
    (incident,) = pipeline.incidents()
    assert incident.session_request_count == 3
    assert incident.timestamps.session_requested == at("2026-11-12T23:32:30+00:00")
    assert retried_at < incident.last_session_request_at  # type: ignore[operator]


def test_req_031_simultaneous_alerts_share_one_incident_and_repeats_after_escalation_add_nothing(
    make_intake: MakeIntake,
    pipeline: Any,
    alertmanager: Any,
    fake_clock: Any,
    telemetry: Any,
    interfere: Callable[..., Any],
) -> None:
    """REQ-031, REQ-141.1: two alerts for one service at the same moment (S13), then a repeat (S15).

    Two intake executions race: the other one creates the incident between this
    one's read and its write, so this one's create fails its condition and, read
    again, attaches (BR3.1, BR3.8). One incident, one session start. After the
    incident is escalated, the alert manager's hourly repeat of the still-firing
    alert has the same key, so it adds nothing and opens nothing (BR2.3, BR2.5).
    """
    first_alert = alertmanager.alert("1111aaaa2222bbbb", service="payment")
    second_alert = alertmanager.alert(
        "3333cccc4444dddd",
        service="payment",
        alertname="PaymentLatencyHigh",
        severity="warning",
        starts_at="2026-11-12T23:32:05.000Z",
    )
    other = make_intake()

    def other_execution() -> None:
        other.intake.handle(alertmanager.sns_event(alertmanager.render([second_alert])))

    racing = make_intake(dynamodb=interfere(pipeline.dynamodb, other_execution))
    first_event = alertmanager.sns_event(alertmanager.render([first_alert]))

    assert racing.intake.handle(first_event) == {"alerts": 1, "attached": 1}
    (incident,) = pipeline.incidents()
    assert {ref.fingerprint for ref in incident.alerts} == {"1111aaaa2222bbbb", "3333cccc4444dddd"}
    assert incident.alert_count == 2
    assert len(pipeline.session_starts()) == 1
    assert telemetry.metrics("LedgerConflicts", component="ledger") == [1.0]

    now = fake_clock.now()
    other.ledger.advance(
        incident.incident_id, IncidentStatus.INVESTIGATING, IncidentPatch(session_started=now)
    )
    other.ledger.advance(
        incident.incident_id,
        IncidentStatus.ESCALATED,
        IncidentPatch(escalation_reason=EscalationReason.SKELETON_READ_DONE),
    )
    fake_clock.advance(hours=1)

    assert other.intake.handle(copy.deepcopy(first_event)) == {"alerts": 1, "duplicate": 1}
    assert len(pipeline.incidents()) == 1
    assert pipeline.session_starts() == []


SERVICES = (
    "frontend",
    "cart",
    "checkout",
    "payment",
    "currency",
    "shipping",
    "email",
    "recommendation",
    "ad",
    "product-catalog",
    "quote",
    "accounting",
    "fraud-detection",
    "image-provider",
    "flagd",
)


def burst_messages(alertmanager: Any) -> tuple[list[str], list[Any]]:
    """200 alerts in one minute across 15 services, in the three shapes of SC-1.

    - 60 single-alert notifications;
    - 100 alerts in 5 grouped notifications of 20, grouped by service and alert
      name as the alert manager groups them;
    - 36 late joiners, each re-notified with the group it joins (the earlier
      alert is a repeat);
    - 4 malformed alerts, each in a notification of its own.

    Returns the messages, in delivery order, and the 196 well-formed alerts.
    """
    rng = random.Random(20261113)  # noqa: S311 - reproducible test data, not security

    def alert(number: int, service: str, alertname: str, second: float) -> Any:
        return alertmanager.alert(
            f"{number:016x}",
            service=service,
            alertname=alertname,
            severity=rng.choice(("critical", "warning", "warning", "info", "info")),
            starts_at=f"2026-11-12T23:40:{second:06.3f}Z",
        )

    names = ("ErrorRatioHigh", "LatencyHigh")
    singles = [alert(n, SERVICES[n % len(SERVICES)], rng.choice(names), n * 0.5) for n in range(60)]
    groups = [
        [
            alert(60 + 20 * g + i, SERVICES[g], "LatencyHigh", 30 + 4 * g + 0.1 * i)
            for i in range(20)
        ]
        for g in range(5)
    ]
    joiners = [
        alert(160 + j, singles[j].labels["service"], singles[j].labels["alertname"], 50 + 0.25 * j)
        for j in range(36)
    ]
    malformed = [
        alertmanager.alert("bad0000000000001", service="cart", severity=""),
        alertmanager.alert("", service="cart"),
        alertmanager.alert("bad0000000000003", service="cart", starts_at="soon"),
        alertmanager.alert("bad0000000000004", service="cart"),
    ]
    del malformed[-1].labels["service"]
    messages = [alertmanager.render([spec]) for spec in singles]
    messages += [alertmanager.render(group) for group in groups]
    messages += [alertmanager.render([singles[j], joiners[j]]) for j in range(36)]
    messages += [alertmanager.render([spec]) for spec in malformed]
    return messages, singles + [spec for group in groups for spec in group] + joiners


def test_req_140_burst_of_200_alerts_is_all_recorded_or_dead_lettered(
    make_intake: MakeIntake, pipeline: Any, alertmanager: Any, fake_clock: Any
) -> None:
    """REQ-120.5, REQ-140.1, REQ-031: a burst of 200 alerts in mixed shapes loses no alert.

    Every well-formed alert is recorded once on its service's incident, every
    malformed one is in the dead-letter queue, each service has exactly one open
    incident, and each incident at a session severity has exactly one session
    start. This is the local burst with recorded fixtures; the burst against the
    real lab waits for the Lambda concurrency increase.
    """
    fake_clock.current = datetime(2026, 11, 12, 23, 41, 0, tzinfo=UTC)
    messages, alerts = burst_messages(alertmanager)
    under = make_intake()

    totals: Counter[str] = Counter()
    for number, message in enumerate(messages):
        totals.update(under.intake.handle(alertmanager.sns_event(message, message_id=f"m{number}")))

    assert len(alerts) == 196
    assert totals["alerts"] == 60 + 100 + 2 * 36 + 4
    assert totals["dead_lettered"] == 4
    assert totals["duplicate"] == 36
    events = pipeline.events()
    expected_keys = {
        idempotency_key(
            spec.fingerprint, at(spec.starts_at.replace("Z", "+00:00")), AlertStatus.FIRING
        )
        for spec in alerts
    }
    assert set(events) == expected_keys
    assert all(event["incident_id"] for event in events.values())
    incidents = pipeline.incidents()
    assert sum(incident.alert_count for incident in incidents) == 196
    assert sorted(incident.service for incident in incidents) == sorted(SERVICES)
    assert pipeline.open_markers() == {i.service: i.incident_id for i in incidents}
    dead = [DeadLetterItem.model_validate(item) for item in pipeline.dead_letters()]
    assert [(item.kind, item.reason) for item in dead] == [("alert", "invalid_payload")] * 4
    starts = Counter(start["incident_id"] for start in pipeline.session_starts())
    needing = {i.incident_id for i in incidents if i.severity in ("critical", "warning")}
    assert set(starts) == needing
    assert set(starts.values()) == {1}
