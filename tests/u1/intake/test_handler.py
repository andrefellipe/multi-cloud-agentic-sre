"""Tests of the intake's Lambda entry point, agents/intake/handler.py (plan Step 30).

The handler builds the intake from the function's environment, as Lambda runs
it, against moto DynamoDB and SQS.
"""

from collections.abc import Iterator
from typing import Any

import pytest

from agents.contracts.settings import SettingsError
from agents.intake import handler

LAB_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:sre-lab-alerts"


@pytest.fixture
def fresh_handler() -> Iterator[None]:
    """The handler builds its intake once per execution environment; each test starts a new one."""
    handler._intake.cache_clear()
    yield
    handler._intake.cache_clear()


@pytest.fixture
def function_environment(monkeypatch: pytest.MonkeyPatch, pipeline: Any) -> None:
    """The variables infra/aws/permanent/intake.tf sets on the function."""
    monkeypatch.setenv("LAB_TOPIC_ARN", LAB_TOPIC_ARN)
    monkeypatch.setenv("INCIDENT_TABLE_NAME", pipeline.table_name)
    monkeypatch.setenv("SESSION_START_QUEUE_URL", pipeline.session_start_queue_url)
    monkeypatch.setenv("DEAD_LETTER_QUEUE_URL", pipeline.dead_letter_queue_url)


def test_req_030_intake_handler_wires_the_function_environment_to_the_pipeline(
    fresh_handler: None, function_environment: None, pipeline: Any, alertmanager: Any
) -> None:
    """REQ-030, REQ-120.3: the Lambda entry point applies an SNS invocation end to end (PD-1, PD-3).

    One alert becomes one incident and one session start on the queue, and the
    second invocation reuses the intake the first one built.
    """
    event = alertmanager.sns_event(alertmanager.message("firing-payment"))

    result = handler.handler(event, None)
    built = handler._intake()
    again = handler.handler(event, None)

    assert result == {"alerts": 1, "created": 1, "session_starts": 1}
    assert again == {"alerts": 1, "duplicate": 1}
    assert handler._intake() is built
    (incident,) = pipeline.incidents()
    assert incident.service == "payment"
    (start,) = pipeline.session_starts()
    assert start["incident_id"] == incident.incident_id


def test_req_140_intake_missing_a_setting_fails_loudly_and_names_it(
    fresh_handler: None,
    function_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    alertmanager: Any,
    pipeline: Any,
) -> None:
    """REQ-140.1: an intake that cannot start raises, naming the setting, and records nothing.

    Raising is what keeps the alert: the platform retries the invocation, then
    hands the event to the on-failure destination (RD-1). A tunable outside its
    bounds stops start-up the same way; a valid one is read.
    """
    event = alertmanager.sns_event(alertmanager.message("firing-payment"))
    monkeypatch.delenv("LAB_TOPIC_ARN")
    with pytest.raises(SettingsError, match="LAB_TOPIC_ARN"):
        handler.handler(event, None)

    monkeypatch.setenv("LAB_TOPIC_ARN", LAB_TOPIC_ARN)
    monkeypatch.setenv("SRE_STALE_SESSION_MINUTES", "2")
    with pytest.raises(SettingsError, match="SRE_STALE_SESSION_MINUTES"):
        handler.handler(event, None)
    assert pipeline.incidents() == []

    monkeypatch.setenv("SRE_STALE_SESSION_MINUTES", "20")
    monkeypatch.setenv("SRE_SESSION_SEVERITIES", "critical, page")
    assert handler.handler(event, None)["created"] == 1
    settings = handler._intake()._settings.skeleton
    assert (settings.stale_session_minutes, settings.session_severities) == (
        20,
        ("critical", "page"),
    )
