"""Tests of the incident ledger, agents/ledger/ (plan Step 22).

Every test runs against moto DynamoDB, with the table shaped as in
infra/aws/permanent, and a fake clock. Each one checks what the table holds
afterwards, not only what the ledger returned.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ulid import ULID

from agents.contracts.alert import AlertRecord, AlertStatus
from agents.contracts.incident import (
    EscalationReason,
    IncidentPatch,
    IncidentStatus,
    ReadCheck,
)
from agents.contracts.session import SessionKind, SessionStartRequest
from agents.ledger.errors import IncidentNotFoundError, StoreUnavailable, TransitionNotAllowed
from agents.ledger.ledger import ApplyOutcome, SessionStartVerdict

STARTS_AT = datetime(2026, 11, 12, 23, 32, 4, 587000, tzinfo=UTC)

MakeLedger = Callable[..., Any]
MakeAlert = Callable[..., AlertRecord]


def test_req_030_firing_alert_creates_an_open_incident_with_marker_event_and_request(
    pipeline: Any, make_ledger: MakeLedger, make_alert: MakeAlert, fake_clock: Any
) -> None:
    """REQ-030, REQ-121.1, REQ-141.1: a firing alert for a service with no incident (BR3.1, BR3.2).

    One write creates the open incident, the service's marker and the inbound
    event with its 14-day expiry, sets the latency timestamps from the alert
    (BR4.6), and, at a session severity, records the session request (BR4.2).
    """
    under = make_ledger()
    now = fake_clock.now()
    alert = make_alert("a3f9c2e17b4d6085", received_at=now)

    applied = under.ledger.apply_alert(alert, now)

    assert applied.outcome is ApplyOutcome.CREATED
    (incident,) = pipeline.incidents()
    assert incident.incident_id == applied.incident_id
    assert ULID.from_str(incident.incident_id).datetime == now
    assert (incident.status, incident.severity, incident.alert_count, incident.version) == (
        IncidentStatus.OPEN,
        "critical",
        1,
        1,
    )
    assert [ref.idempotency_key for ref in incident.alerts] == [alert.idempotency_key]
    assert incident.alerts[0].recorded_at == now
    assert incident.timestamps.alert_fired == STARTS_AT
    assert incident.timestamps.record_created == now
    assert incident.timestamps.session_requested == now
    assert (incident.session_request_count, incident.last_session_request_at) == (1, now)
    assert applied.alert_to_record_seconds == pytest.approx(25.413)
    assert applied.session_start == SessionStartRequest(
        schema_version=1,
        incident_id=incident.incident_id,
        kind=SessionKind.INCIDENT,
        requested_at=now,
        attempt=1,
    )
    assert pipeline.open_markers() == {"payment": incident.incident_id}
    event = pipeline.events()[alert.idempotency_key]
    assert (event["outcome"], event["incident_id"]) == ("created", incident.incident_id)
    assert event["expires_at"] == "2026-11-26T23:32:30.000Z"
    assert event["expires_at_epoch"] == int((now + timedelta(days=14)).timestamp())
    (stored,) = pipeline.items("incident")
    assert stored["timestamps"]["alert_fired"] == "2026-11-12T23:32:04.587Z"
    assert stored["timestamps"]["record_created"] == "2026-11-12T23:32:30.000Z"
    assert under.metrics.counts == {"LedgerWrites": 1}


def test_req_031_second_alert_attaches_without_a_second_session(
    pipeline: Any, make_ledger: MakeLedger, make_alert: MakeAlert, fake_clock: Any
) -> None:
    """REQ-031, REQ-035: a further alert for the service attaches to its open incident (BR3.3).

    The severity stays the highest (BR3.4), an unknown severity is flagged, the
    latency timestamps keep the triggering alert (BR4.6), and no second session
    is requested (BR4.4).
    """
    under = make_ledger()
    created = under.ledger.apply_alert(
        make_alert("a1", received_at=fake_clock.now()), fake_clock.now()
    )
    later = fake_clock.advance(seconds=30)
    warning = make_alert(
        "b2", severity="warning", starts_at="2026-11-12T23:32:50.000Z", received_at=later
    )
    paging = make_alert(
        "c3", severity="page", starts_at="2026-11-12T23:32:55.000Z", received_at=later
    )

    attached = under.ledger.apply_alert(warning, later)
    flagged = under.ledger.apply_alert(paging, later)

    assert (attached.outcome, attached.incident_id) == (ApplyOutcome.ATTACHED, created.incident_id)
    assert attached.session_start is None
    assert flagged.session_start is None
    assert attached.alert_to_record_seconds is None
    (incident,) = pipeline.incidents()
    assert [ref.fingerprint for ref in incident.alerts] == ["a1", "b2", "c3"]
    assert (incident.alert_count, incident.severity, incident.version) == (3, "critical", 3)
    assert incident.has_unknown_severity is True
    assert incident.timestamps.alert_fired == STARTS_AT
    assert incident.session_request_count == 1
    assert pipeline.events()[warning.idempotency_key]["outcome"] == "attached"
    assert pipeline.open_markers() == {"payment": created.incident_id}


def test_req_032_duplicate_adds_nothing_but_retries_a_stuck_session_request(
    pipeline: Any, make_ledger: MakeLedger, make_alert: MakeAlert, fake_clock: Any
) -> None:
    """REQ-032, REQ-141.1: a key already stored adds nothing to the incident (BR2.2).

    Within 120 seconds of the last request, a repeat changes nothing at all.
    After that, with still no session started, the repeat requests a session
    again (BR2.5, BR4.2), and only that request is written.
    """
    under = make_ledger()
    alert = make_alert("a3f9c2e17b4d6085", received_at=fake_clock.now())
    created = under.ledger.apply_alert(alert, fake_clock.now())

    soon = fake_clock.advance(seconds=119)
    repeat = under.ledger.apply_alert(alert, soon)

    assert (repeat.outcome, repeat.incident_id, repeat.session_start) == (
        ApplyOutcome.DUPLICATE,
        created.incident_id,
        None,
    )
    (incident,) = pipeline.incidents()
    assert (incident.alert_count, incident.version) == (1, 1)
    assert under.metrics.counts == {"LedgerWrites": 1}

    later = fake_clock.advance(seconds=1)
    retry = under.ledger.apply_alert(alert, later)

    assert retry.outcome is ApplyOutcome.DUPLICATE
    assert retry.session_start is not None
    assert retry.session_start.requested_at == later
    (incident,) = pipeline.incidents()
    assert (incident.alert_count, incident.version, incident.session_request_count) == (1, 2, 2)
    assert incident.timestamps.session_requested == created.session_start.requested_at  # type: ignore[union-attr]
    assert incident.last_session_request_at == later
    assert len(pipeline.events()) == 1


def test_req_030_resolved_alert_is_recorded_on_its_incident_even_when_terminal(
    pipeline: Any, make_ledger: MakeLedger, make_alert: MakeAlert, fake_clock: Any
) -> None:
    """REQ-030, REQ-141.1: a resolved alert finds its incident through the firing record (BR3.5).

    It sets resolved_at on the matching alert of an escalated incident without
    changing its status (BR3.6), and a second delivery of it adds nothing.
    """
    under = make_ledger()
    now = fake_clock.now()
    created = under.ledger.apply_alert(make_alert("a3f9c2e17b4d6085", received_at=now), now)
    incident_id = created.incident_id
    under.ledger.advance(
        incident_id, IncidentStatus.INVESTIGATING, IncidentPatch(session_started=now)
    )
    under.ledger.advance(
        incident_id,
        IncidentStatus.ESCALATED,
        IncidentPatch(escalation_reason=EscalationReason.SKELETON_READ_DONE),
    )
    resolved_at = fake_clock.advance(minutes=16)
    resolved = make_alert("a3f9c2e17b4d6085", status=AlertStatus.RESOLVED, received_at=resolved_at)

    applied = under.ledger.apply_alert(resolved, resolved_at)
    again = under.ledger.apply_alert(resolved, resolved_at)

    assert (applied.outcome, applied.incident_id) == (ApplyOutcome.RESOLVED_RECORDED, incident_id)
    assert again.outcome is ApplyOutcome.DUPLICATE
    incident = pipeline.incident(incident_id)
    assert incident.status is IncidentStatus.ESCALATED
    assert incident.escalation_reason is EscalationReason.SKELETON_READ_DONE
    assert incident.alerts[0].resolved_at == resolved_at
    assert incident.version == 4
    event = pipeline.events()[resolved.idempotency_key]
    assert (event["outcome"], event["incident_id"]) == ("resolved_recorded", incident_id)


def test_req_030_resolved_alert_without_a_firing_record_is_recorded_as_unmatched(
    pipeline: Any, make_ledger: MakeLedger, make_alert: MakeAlert, fake_clock: Any
) -> None:
    """REQ-030, REQ-141.1: a resolved notification with no firing record creates nothing (BR3.5).

    Its event is stored as resolved_unmatched, with no incident. The firing
    notification arriving after it still opens an incident (assumption A-02).
    """
    under = make_ledger()
    now = fake_clock.now()
    resolved = make_alert("f00d", status=AlertStatus.RESOLVED, received_at=now)

    applied = under.ledger.apply_alert(resolved, now)

    assert (applied.outcome, applied.incident_id) == (ApplyOutcome.RESOLVED_UNMATCHED, None)
    assert pipeline.incidents() == []
    assert pipeline.open_markers() == {}
    event = pipeline.events()[resolved.idempotency_key]
    assert (event["outcome"], event["incident_id"]) == ("resolved_unmatched", None)
    firing = under.ledger.apply_alert(make_alert("f00d", received_at=now), now)
    assert firing.outcome is ApplyOutcome.CREATED


def test_req_140_new_alert_releases_a_stale_session_and_opens_a_new_incident(
    pipeline: Any, make_ledger: MakeLedger, make_alert: MakeAlert, fake_clock: Any
) -> None:
    """REQ-140, REQ-031: a session that died more than 15 minutes ago is released (BR3.10).

    At exactly 15 minutes the incident is not yet stale, and an alert attaches.
    One second later, a new alert escalates it with session_lost and creates a
    new incident in the same write, moving the service's marker to it.
    """
    under = make_ledger()
    started = fake_clock.now()
    old = under.ledger.apply_alert(make_alert("a1", received_at=started), started).incident_id
    under.ledger.advance(old, IncidentStatus.INVESTIGATING, IncidentPatch(session_started=started))

    at_limit = fake_clock.advance(minutes=15)
    attached = under.ledger.apply_alert(make_alert("b2", received_at=at_limit), at_limit)
    past_limit = fake_clock.advance(seconds=1)
    created = under.ledger.apply_alert(make_alert("c3", received_at=past_limit), past_limit)

    assert (attached.outcome, attached.incident_id) == (ApplyOutcome.ATTACHED, old)
    assert created.outcome is ApplyOutcome.CREATED
    assert created.released_incident_id == old
    assert created.session_start is not None
    released = pipeline.incident(old)
    assert released.status is IncidentStatus.ESCALATED
    assert released.escalation_reason is EscalationReason.SESSION_LOST
    assert released.timestamps.escalated == past_limit
    new = pipeline.incident(created.incident_id)
    assert (new.status, [ref.fingerprint for ref in new.alerts]) == (IncidentStatus.OPEN, ["c3"])
    assert pipeline.open_markers() == {"payment": created.incident_id}


def test_req_140_repeat_or_resolved_message_releases_a_stale_session_and_opens_nothing(
    pipeline: Any, make_ledger: MakeLedger, make_alert: MakeAlert, fake_clock: Any
) -> None:
    """REQ-140, REQ-141.1: a repeat or a resolved message also frees a stuck incident (S12).

    For payment, a repeat of the same alert escalates the stale incident with
    session_lost and removes the marker, but adds no alert and opens no incident
    (BR2.5, BR3.10); a later repeat finds it terminal and does nothing (S15). For
    cart, the resolved message does the same, and records its resolution in the
    same write (BR3.5).
    """
    under = make_ledger()
    started = fake_clock.now()
    payment = make_alert("a1", received_at=started)
    cart = make_alert("b2", service="cart", received_at=started)
    stuck = [under.ledger.apply_alert(alert, started).incident_id for alert in (payment, cart)]
    for incident_id in stuck:
        under.ledger.advance(
            incident_id, IncidentStatus.INVESTIGATING, IncidentPatch(session_started=started)
        )

    stale = fake_clock.advance(minutes=16)
    repeat = under.ledger.apply_alert(payment, stale)
    cart_resolved = make_alert("b2", service="cart", status=AlertStatus.RESOLVED, received_at=stale)
    resolved = under.ledger.apply_alert(cart_resolved, stale)
    hour_later = fake_clock.advance(hours=1)
    second = under.ledger.apply_alert(payment, hour_later)

    assert (repeat.outcome, repeat.released_incident_id) == (ApplyOutcome.DUPLICATE, stuck[0])
    assert (resolved.outcome, resolved.released_incident_id) == (
        ApplyOutcome.RESOLVED_RECORDED,
        stuck[1],
    )
    assert (second.outcome, second.released_incident_id, second.session_start) == (
        ApplyOutcome.DUPLICATE,
        None,
        None,
    )
    for incident in pipeline.incidents():
        assert incident.status is IncidentStatus.ESCALATED
        assert incident.escalation_reason is EscalationReason.SESSION_LOST
        assert incident.timestamps.escalated == stale
        assert incident.alert_count == 1
    assert pipeline.incident(stuck[1]).alerts[0].resolved_at == stale
    assert pipeline.incident(stuck[0]).alerts[0].resolved_at is None
    assert pipeline.open_markers() == {}
    assert all("incident_id" not in marker for marker in pipeline.items("open_incident_marker"))


def test_req_031_advance_follows_the_state_machine_and_refuses_the_rest(
    pipeline: Any, make_ledger: MakeLedger, make_alert: MakeAlert, fake_clock: Any
) -> None:
    """REQ-031: status changes follow the state machine; anything else is refused (BR3.6, BR3.7).

    open goes to investigating with the session's start time, and investigating
    to escalated with the session's results, which removes the service's marker
    in the same write (BR5.7). Refused changes write nothing. The session-start
    check follows the same record (BR4.4).
    """
    under = make_ledger()
    now = fake_clock.now()
    incident_id = under.ledger.apply_alert(make_alert("a1", received_at=now), now).incident_id
    assert under.ledger.session_start_check(incident_id) is SessionStartVerdict.ALLOWED
    for refused in (IncidentStatus.RECOVERED, IncidentStatus.OPEN, IncidentStatus.PR_OPEN):
        with pytest.raises(TransitionNotAllowed):
            under.ledger.advance(incident_id, refused)

    investigating = under.ledger.advance(
        incident_id, IncidentStatus.INVESTIGATING, IncidentPatch(session_started=now)
    )
    assert (
        under.ledger.session_start_check(incident_id) is SessionStartVerdict.SESSION_ALREADY_STARTED
    )
    check = ReadCheck(
        namespace="otel-demo",
        succeeded=True,
        item_count=1,
        item_names=("payment-1",),
        completed_at=now,
    )
    ended = fake_clock.advance(seconds=40)
    escalated = under.ledger.advance(
        incident_id,
        IncidentStatus.ESCALATED,
        IncidentPatch(
            escalation_reason=EscalationReason.SKELETON_READ_DONE,
            read_check=check,
            tokens_used=1200,
            steps_used=2,
        ),
    )

    assert (investigating.status, investigating.version) == (IncidentStatus.INVESTIGATING, 2)
    assert escalated == pipeline.incident(incident_id)
    assert (escalated.status, escalated.version) == (IncidentStatus.ESCALATED, 3)
    assert escalated.timestamps.session_started == now
    assert escalated.timestamps.escalated == ended
    assert (escalated.read_check, escalated.tokens_used, escalated.steps_used) == (check, 1200, 2)
    assert pipeline.open_markers() == {}
    assert under.ledger.session_start_check(incident_id) is SessionStartVerdict.INCIDENT_TERMINAL
    with pytest.raises(TransitionNotAllowed):
        under.ledger.advance(incident_id, IncidentStatus.INVESTIGATING)
    missing = "01JCX8Z3T6Q4M2N7P5R9S1V3W9"
    with pytest.raises(IncidentNotFoundError):
        under.ledger.advance(missing, IncidentStatus.INVESTIGATING)
    assert under.ledger.session_start_check(missing) is SessionStartVerdict.INCIDENT_NOT_FOUND
    assert under.metrics.counts == {"LedgerWrites": 3}


def test_req_031_conflicting_write_is_read_again_and_retried_then_gives_up(
    pipeline: Any,
    make_ledger: MakeLedger,
    make_alert: MakeAlert,
    fake_clock: Any,
    interfere: Callable[..., Any],
) -> None:
    """REQ-031, REQ-033: a write that loses a race is re-read and re-applied (BR3.8, BR6.1).

    Another writer attaches an alert between this write's read and its write, so
    the version condition fails once; the second attempt attaches on top of it
    and loses nothing. When the race is lost three times, the ledger stops with
    StoreUnavailable after jittered backoff, and the alert is not stored.
    """
    now = fake_clock.now()
    other = make_ledger()
    incident_id = other.ledger.apply_alert(make_alert("a1", received_at=now), now).incident_id
    racing = iter(["c3", "d4", "e5", "f6"])

    def another_writer_attaches() -> None:
        other.ledger.apply_alert(make_alert(next(racing), received_at=now), now)

    under = make_ledger(client=interfere(pipeline.dynamodb, another_writer_attaches))

    applied = under.ledger.apply_alert(make_alert("b2", received_at=now), now)

    assert (applied.outcome, applied.incident_id) == (ApplyOutcome.ATTACHED, incident_id)
    incident = pipeline.incident(incident_id)
    assert [ref.fingerprint for ref in incident.alerts] == ["a1", "c3", "b2"]
    assert (incident.alert_count, incident.version) == (3, 3)
    assert under.metrics.counts == {"LedgerConflicts": 1, "LedgerWrites": 1}
    assert len(under.sleeps) == 1
    assert 0.0 <= under.sleeps[0] <= 0.1

    losing = make_ledger(client=interfere(pipeline.dynamodb, another_writer_attaches, times=3))
    lost = make_alert("g7", received_at=now)
    with pytest.raises(StoreUnavailable) as raised:
        losing.ledger.apply_alert(lost, now)

    assert (raised.value.attempts, raised.value.last_error) == (3, "ConditionalCheckFailed")
    assert losing.metrics.counts == {"LedgerConflicts": 3, "LedgerWriteFailures": 1}
    assert len(losing.sleeps) == 2
    assert losing.sleeps[0] <= 0.1
    assert losing.sleeps[1] <= 0.2
    assert lost.idempotency_key not in pipeline.events()
    assert pipeline.incident(incident_id).alert_count == 6


def test_req_031_hundred_alerts_are_listed_and_the_rest_counted(
    pipeline: Any, make_ledger: MakeLedger, make_alert: MakeAlert, fake_clock: Any
) -> None:
    """REQ-031, REQ-035, REQ-121: an incident lists at most 100 alerts (BR3.9).

    Later alerts are counted, their keys are stored, and they still raise the
    severity, which makes the raising alert the trigger of the latency
    timestamps and requests a session (BR3.4, BR4.6, BR4.2).
    """
    under = make_ledger()
    now = fake_clock.now()
    first = under.ledger.apply_alert(make_alert("f000", severity="info", received_at=now), now)
    for number in range(1, 101):
        alert = make_alert(f"f{number:03d}", severity="info", received_at=now)
        assert under.ledger.apply_alert(alert, now).outcome is ApplyOutcome.ATTACHED
    later = fake_clock.advance(seconds=5)
    raising = make_alert(
        "f101", severity="critical", starts_at="2026-11-12T23:32:33.000Z", received_at=later
    )

    applied = under.ledger.apply_alert(raising, later)
    repeat = under.ledger.apply_alert(raising, later)

    assert first.session_start is None
    assert applied.session_start is not None
    assert applied.alert_to_record_seconds == pytest.approx(2.0)
    assert repeat.outcome is ApplyOutcome.DUPLICATE
    (incident,) = pipeline.incidents()
    assert len(incident.alerts) == 100
    assert incident.alerts[-1].fingerprint == "f099"
    assert incident.alert_count == 102
    assert incident.severity == "critical"
    assert incident.timestamps.alert_fired == datetime(2026, 11, 12, 23, 32, 33, tzinfo=UTC)
    assert incident.timestamps.record_created == later
    assert raising.idempotency_key in pipeline.events()
