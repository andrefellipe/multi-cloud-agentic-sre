"""Lambda entry point of the intake (LC2): ``agents.intake.handler.handler``.

The intake, its ledger and their AWS clients are built once per execution
environment, at the first invocation, and reused by the next ones (PD-3). A
setting missing from the environment fails that invocation with an error naming
it: the platform retries the event, then hands it to the on-failure destination,
the dead-letter queue, so no alert is lost (RD-1).

Environment: ``LAB_TOPIC_ARN``, ``INCIDENT_TABLE_NAME``, ``SESSION_START_QUEUE_URL``,
``DEAD_LETTER_QUEUE_URL``, and optionally the ``SRE_*`` settings of
:class:`agents.contracts.settings.SkeletonSettings`.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Mapping
from typing import Any

import boto3

from agents.aws import LEDGER_CLIENT_CONFIG, QUEUE_CLIENT_CONFIG
from agents.intake.intake import Intake, IntakeSettings
from agents.ledger.ledger import IncidentLedger
from agents.telemetry import Telemetry


def build_intake(environ: Mapping[str, str], session: boto3.Session | None = None) -> Intake:
    """Wire the intake to its table and queues, with the timeouts of RD-3."""
    settings = IntakeSettings.from_environ(environ)
    session = session or boto3.Session()
    ledger = IncidentLedger(
        session.client("dynamodb", config=LEDGER_CLIENT_CONFIG),
        settings.incident_table_name,
        settings.skeleton,
        metrics=Telemetry("ledger"),
    )
    sqs = session.client("sqs", config=QUEUE_CLIENT_CONFIG)
    return Intake(settings, ledger, sqs, telemetry=Telemetry("intake"))


@functools.cache
def _intake() -> Intake:
    return build_intake(os.environ)


def handler(event: dict[str, Any], context: object) -> dict[str, int]:
    """Apply the alert notifications of one SNS invocation from the lab topic (W1)."""
    return _intake().handle(event)
