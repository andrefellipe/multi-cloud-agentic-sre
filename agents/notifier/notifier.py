"""Notifier: the one Slack message of Phase 1, the dead-letter notice (W4, contract C7).

The alarm "dead letters waiting" publishes to the operations alarm topic (LC10)
when the dead-letter queue goes from empty to holding items; the topic runs this
function. For each alarm message, the notifier:

1. checks that it is that alarm entering the ALARM state, and ignores anything else;
2. builds the fixed notice: the queue's configured label, its item count and its
   oldest item's age, read from the queue and its CloudWatch metric. No text from
   any message, alert or dead-letter item goes into it (BR6.3, ADR-006);
3. reads the Slack webhook URL from Secrets Manager at that moment, and keeps it
   only for this send: it is never logged, traced or stored (BR6.4);
4. posts the notice, with 3 attempts and capped backoff; when every attempt
   fails, it logs the failure and returns without raising. The alarm stays
   visible in CloudWatch (BR6.5).

The alarm notifies once, when it enters the ALARM state, so this is one notice
per alarm period while items remain. A notice lost to a Slack outage is not
repeated; the runbook's dead-letter check after each demo covers that (RD-1, OD-4).
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

import httpx
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field

from agents.contracts.common import NonEmptyStr, to_utc_millis, utc_now
from agents.contracts.notify import PHASE_1_KINDS, DeadLetterNotice, NotifyKind, NotifyRequest
from agents.contracts.settings import SkeletonSettings, require_setting
from agents.telemetry import Telemetry

if TYPE_CHECKING:
    from mypy_boto3_cloudwatch.client import CloudWatchClient
    from mypy_boto3_secretsmanager.client import SecretsManagerClient
    from mypy_boto3_sqs.client import SQSClient

DEFAULT_WEBHOOK_CREDENTIAL: Final = "sre-lab/slack-webhook-url"
POST_TIMEOUT_SECONDS: Final = 5.0
BACKOFF_BASE_SECONDS: Final = 1.0
BACKOFF_CAP_SECONDS: Final = 4.0
"""RD-1: posts are retried after 1 s, then 2 s, capped at 4 s."""
AGE_LOOKBACK: Final = timedelta(minutes=10)
REPLAY_TOOL: Final = "tools/lab/replay_dead_letters.py"

# BR6.4: these libraries log request URLs (httpx, at INFO) and bodies (botocore,
# at DEBUG). Whatever level the function's logging is set to, they never get to.
for _library in ("httpx", "httpcore", "botocore", "boto3", "urllib3"):
    logging.getLogger(_library).setLevel(logging.WARNING)


class NotifierSettings(BaseModel):
    """What the notifier is wired to, read from its environment at start-up."""

    model_config = ConfigDict(frozen=True)

    dead_letter_queue_url: NonEmptyStr
    dead_letter_alarm_name: NonEmptyStr
    webhook_credential_name: NonEmptyStr = DEFAULT_WEBHOOK_CREDENTIAL
    skeleton: SkeletonSettings = Field(default_factory=SkeletonSettings)

    @property
    def queue_name(self) -> str:
        """The dead-letter queue's name, the label of the notice and its metric dimension."""
        return self.dead_letter_queue_url.rstrip("/").rsplit("/", 1)[-1]

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> NotifierSettings:
        """Read the settings; a missing one stops start-up with an error naming it."""
        return cls(
            dead_letter_queue_url=require_setting(environ, "DEAD_LETTER_QUEUE_URL"),
            dead_letter_alarm_name=require_setting(environ, "DEAD_LETTER_ALARM_NAME"),
            webhook_credential_name=environ.get("SLACK_WEBHOOK_SECRET_ID", "").strip()
            or DEFAULT_WEBHOOK_CREDENTIAL,
            skeleton=SkeletonSettings.from_environ(environ),
        )


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def render_dead_letter_notice(notice: DeadLetterNotice) -> str:
    """The fixed template of ``dead_letter_alert`` (BR6.3). Every value is a number or config."""
    if notice.message_count is None:
        count = "item count unknown"
    else:
        count = _plural(notice.message_count, "item")
    if notice.oldest_age_minutes is None:
        age = "the oldest item's age is unknown"
    elif notice.oldest_age_minutes == 0:
        age = "the oldest is under a minute old"
    else:
        age = f"the oldest is about {_plural(notice.oldest_age_minutes, 'minute')} old"
    raised = notice.raised_at.strftime("%Y-%m-%d %H:%M")
    return (
        f":warning: Dead letters are waiting in {notice.queue_label}: {count}; {age}."
        f" Raised {raised} UTC. Nothing is lost: once the cause is fixed,"
        f" replay them with {REPLAY_TOOL}."
    )


@dataclass(frozen=True)
class AlarmChange:
    """What the notifier reads from a CloudWatch alarm message: name, new state, time."""

    name: str
    new_state: str
    changed_at: datetime | None


def read_alarm(record: object) -> AlarmChange | None:
    """Read one SNS record carrying a CloudWatch alarm message, or return None."""
    sns = record.get("Sns") if isinstance(record, Mapping) else None
    message = sns.get("Message") if isinstance(sns, Mapping) else None
    if not isinstance(message, str):
        return None
    try:
        alarm = json.loads(message)
    except ValueError:
        return None
    if not isinstance(alarm, dict):
        return None
    name, state = alarm.get("AlarmName"), alarm.get("NewStateValue")
    if not isinstance(name, str) or not isinstance(state, str):
        return None
    return AlarmChange(name, state, _instant(alarm.get("StateChangeTime")))


def _instant(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return to_utc_millis(parsed) if parsed.tzinfo is not None else None


def _error_class(error: Exception) -> str:
    if isinstance(error, ClientError):
        return str(error.response.get("Error", {}).get("Code", "ClientError"))
    return type(error).__name__


class Notifier:
    """The Notifier of Phase 1: dead-letter notices only (contract C7, ADR-006)."""

    def __init__(
        self,
        settings: NotifierSettings,
        *,
        secrets: SecretsManagerClient,
        sqs: SQSClient,
        cloudwatch: CloudWatchClient,
        http: httpx.Client,
        telemetry: Telemetry | None = None,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._secrets = secrets
        self._sqs = sqs
        self._cloudwatch = cloudwatch
        self._http = http
        self._telemetry = telemetry or Telemetry("notifier")
        self._clock = clock
        self._sleep = sleep

    def handle(self, event: object) -> dict[str, int]:
        """Send one notice per dead-letter alarm in the event. Never raises (BR6.5)."""
        tally: Counter[str] = Counter()
        records = event.get("Records") if isinstance(event, Mapping) else None
        for record in records if isinstance(records, list) else []:
            try:
                tally[self._handle_record(record)] += 1
            except Exception as error:  # BR6.5: a failed notice never breaks the caller.
                tally["failed"] += 1
                self._failure("notice failed", "unexpected_error", error_class=type(error).__name__)
        return dict(sorted(tally.items()))

    def notify(self, request: NotifyRequest) -> bool:
        """C7 in Phase 1: post one fixed-template notice; True when sent. Never raises."""
        if request.kind not in PHASE_1_KINDS or request.dead_letter is None:
            self._failure(
                "notice refused: Phase 1 sends dead-letter notices only", "kind_not_in_phase_1"
            )
            return False
        text = render_dead_letter_notice(request.dead_letter)
        url = self._webhook_url()
        return url is not None and self._post(url, text)

    def _handle_record(self, record: object) -> str:
        alarm = read_alarm(record)
        expected = self._settings.dead_letter_alarm_name
        if alarm is None or alarm.name != expected or alarm.new_state != "ALARM":
            self._telemetry.log("alarm message ignored", outcome="ignored")
            return "ignored"
        now = self._clock()
        notice = DeadLetterNotice(
            queue_label=self._settings.queue_name,
            message_count=self._item_count(),
            oldest_age_minutes=self._oldest_age_minutes(now),
            raised_at=alarm.changed_at or now,
        )
        sent = self.notify(NotifyRequest(kind=NotifyKind.DEAD_LETTER_ALERT, dead_letter=notice))
        return "sent" if sent else "failed"

    def _webhook_url(self) -> str | None:
        """BR6.4: the webhook URL, read from Secrets Manager now, held only for this send."""
        try:
            answer = self._secrets.get_secret_value(SecretId=self._settings.webhook_credential_name)
        except (ClientError, BotoCoreError) as error:
            self._failure(
                "notice not sent: the webhook secret could not be read",
                "secret_unavailable",
                error_class=_error_class(error),
            )
            return None
        url = answer.get("SecretString", "").strip()
        if not url.startswith("https://"):
            self._failure(
                "notice not sent: the webhook secret is not an https URL", "secret_invalid"
            )
            return None
        return url

    def _post(self, url: str, text: str) -> bool:
        """BR6.5: up to ``notifier_attempts`` posts, 1 s then 2 s apart, capped at 4 s."""
        attempts = self._settings.skeleton.notifier_attempts
        for attempt in range(1, attempts + 1):
            try:
                response = self._http.post(url, json={"text": text}, timeout=POST_TIMEOUT_SECONDS)
            except httpx.HTTPError as error:
                failure = type(error).__name__
            else:
                if response.is_success:
                    self._telemetry.count("NoticesSent")
                    self._telemetry.log("notice sent", outcome="sent", attempt=attempt)
                    return True
                failure = f"HTTP{response.status_code}"
            self._telemetry.log(
                "notice post failed",
                level="WARNING",
                outcome="retry",
                error_class=failure,
                attempt=attempt,
            )
            if attempt < attempts:
                self._sleep(min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)))
        self._failure(
            "notice not sent after every attempt; the alarm stays in CloudWatch",
            "post_failed",
            attempt=attempts,
        )
        return False

    def _item_count(self) -> int | None:
        """Items in the dead-letter queue: waiting, plus being received right now."""
        try:
            attributes = self._sqs.get_queue_attributes(
                QueueUrl=self._settings.dead_letter_queue_url,
                AttributeNames=[
                    "ApproximateNumberOfMessages",
                    "ApproximateNumberOfMessagesNotVisible",
                ],
            )["Attributes"]
            waiting = int(attributes.get("ApproximateNumberOfMessages", "0"))
            return waiting + int(attributes.get("ApproximateNumberOfMessagesNotVisible", "0"))
        except (ClientError, BotoCoreError, KeyError, ValueError) as error:
            self._telemetry.log(
                "dead-letter count not read",
                level="WARNING",
                outcome="unknown",
                error_class=_error_class(error),
            )
            return None

    def _oldest_age_minutes(self, now: datetime) -> int | None:
        """The queue's ApproximateAgeOfOldestMessage, from CloudWatch, in whole minutes."""
        try:
            answer = self._cloudwatch.get_metric_data(
                MetricDataQueries=[
                    {
                        "Id": "oldest",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": "AWS/SQS",
                                "MetricName": "ApproximateAgeOfOldestMessage",
                                "Dimensions": [
                                    {"Name": "QueueName", "Value": self._settings.queue_name}
                                ],
                            },
                            "Period": 60,
                            "Stat": "Maximum",
                        },
                        "ReturnData": True,
                    }
                ],
                StartTime=now - AGE_LOOKBACK,
                EndTime=now,
                ScanBy="TimestampDescending",
            )
        except (ClientError, BotoCoreError) as error:
            self._telemetry.log(
                "oldest age not read",
                level="WARNING",
                outcome="unknown",
                error_class=_error_class(error),
            )
            return None
        for result in answer.get("MetricDataResults", []):
            values = result.get("Values", [])
            if values:
                return max(0, int(values[0] // 60))
        return None

    def _failure(
        self,
        message: str,
        reason: str,
        *,
        error_class: str | None = None,
        attempt: int | None = None,
    ) -> None:
        self._telemetry.count("NoticeFailures")
        self._telemetry.log(
            message,
            level="ERROR",
            outcome="failed",
            reason=reason,
            error_class=error_class,
            attempt=attempt,
        )
