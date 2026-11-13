"""Lambda entry point of the notifier (LC9): ``agents.notifier.handler.handler``.

The notifier and its clients are built once per execution environment, at the
first invocation (PD-3). It never raises (BR6.5): even a notifier that cannot
start, for a setting missing from its environment, counts a NoticeFailures and
logs the error class, so the failure shows on that metric's alarm.

Environment: ``DEAD_LETTER_QUEUE_URL``, ``DEAD_LETTER_ALARM_NAME``, optionally
``SLACK_WEBHOOK_SECRET_ID`` (default ``sre-lab/slack-webhook-url``) and the
``SRE_*`` settings of :class:`agents.contracts.settings.SkeletonSettings`.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Mapping
from typing import Any

import boto3
import httpx

from agents.aws import READ_CLIENT_CONFIG
from agents.notifier.notifier import POST_TIMEOUT_SECONDS, Notifier, NotifierSettings
from agents.telemetry import Telemetry


def build_notifier(environ: Mapping[str, str], session: boto3.Session | None = None) -> Notifier:
    """Wire the notifier to the queue, the secret, CloudWatch and Slack, with RD-3's timeouts."""
    settings = NotifierSettings.from_environ(environ)
    session = session or boto3.Session()
    return Notifier(
        settings,
        secrets=session.client("secretsmanager", config=READ_CLIENT_CONFIG),
        sqs=session.client("sqs", config=READ_CLIENT_CONFIG),
        cloudwatch=session.client("cloudwatch", config=READ_CLIENT_CONFIG),
        http=httpx.Client(timeout=POST_TIMEOUT_SECONDS, follow_redirects=False),
        telemetry=Telemetry("notifier"),
    )


@functools.cache
def _notifier() -> Notifier:
    return build_notifier(os.environ)


def handler(event: dict[str, Any], context: object) -> dict[str, int]:
    """Send the dead-letter notice for the alarm messages of one SNS invocation (W4)."""
    try:
        notifier = _notifier()
    except Exception as error:  # BR6.5: never raise; the failure shows on NoticeFailures.
        telemetry = Telemetry("notifier")
        telemetry.count("NoticeFailures")
        telemetry.log(
            "notifier not started",
            level="ERROR",
            outcome="failed",
            reason="start_up",
            error_class=type(error).__name__,
        )
        return {"failed": 1}
    return notifier.handle(event)
