#!/usr/bin/env python3
"""Replay the dead-letter queue's items once their cause is fixed (W5, BR6.6, RD-7).

You run it from your admin terminal, never from the coding agent's session. It
reads the dead-letter queue (LC8), recognises the shape of each item, and replays
it by its own path:

1. an item the intake wrote, of kind ``alert_notification`` or ``alert``: its
   original notification goes back through the intake function, as a message
   from the lab topic. Idempotency stops any double effect (BR2.2);
2. an on-failure record of the intake function, left after the platform's
   retries: the SNS event it carries goes back through the intake function;
3. a session start, written by the intake (kind ``session_start``) or redriven
   from the session-start queue: when its incident is still non-terminal and has
   no session started, the request goes back on the session-start queue;
   otherwise it is dropped, and the reason printed (BR4.4).

An item is deleted only after its replay succeeded or it was deliberately
dropped. An item that fails, or whose shape is not recognised, stays in the
queue and is visible again after ``--visibility-seconds``. Running the script
twice is safe. It prints one line per item, with its shape, what was done and
the result, never its content, and AWS errors by their code only.

Usage, from the repository root (it imports the repository's ``agents`` package):
    uv run python -m tools.lab.replay_dead_letters [--max-items N]

Exit status: 0 when every item was replayed or dropped, 1 when some stay in the
queue or an AWS call failed, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TextIO

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from agents.aws import LEDGER_CLIENT_CONFIG
from agents.contracts.common import format_instant, utc_now
from agents.contracts.dead_letter import DeadLetterItem, DeadLetterKind
from agents.contracts.session import SessionStartRequest
from agents.ledger.errors import StoreUnavailable
from agents.ledger.ledger import IncidentLedger, SessionStartVerdict

if TYPE_CHECKING:
    from mypy_boto3_lambda.client import LambdaClient
    from mypy_boto3_sqs.client import SQSClient
    from mypy_boto3_sqs.type_defs import MessageTypeDef

JSON = dict[str, Any]


class Shape(StrEnum):
    INTAKE_ITEM = "dead-letter item"
    ON_FAILURE = "on-failure record"
    SESSION_START = "session start"
    UNRECOGNISED = "unrecognised"


@dataclass(frozen=True)
class Settings:
    """Names, matching infra/aws/permanent, and limits."""

    region: str = "us-east-1"
    dead_letter_queue: str = "sre-lab-dead-letters"
    session_start_queue: str = "sre-lab-session-starts"
    intake_function: str = "sre-lab-intake"
    incident_table: str = "sre-lab-incidents"
    max_items: int = 100
    visibility_seconds: int = 300


@dataclass(frozen=True)
class Delivery:
    """How a replay through the intake went."""

    accepted: bool
    detail: str


IntakeInvoker = Callable[[JSON], Delivery]


@dataclass(frozen=True)
class Target:
    """Where items come from and go back to."""

    dead_letter_queue_url: str
    session_start_queue_url: str
    lab_topic_arn: str


@dataclass(frozen=True)
class Plan:
    """What one item is, and how it goes back."""

    shape: Shape
    label: str
    intake_event: JSON | None = None
    session_start: SessionStartRequest | None = None


@dataclass
class Console:
    out: TextIO = field(default_factory=lambda: sys.stdout)
    err: TextIO = field(default_factory=lambda: sys.stderr)

    def say(self, text: str) -> None:
        print(text, file=self.out, flush=True)

    def error(self, text: str) -> None:
        print(f"replay_dead_letters: {text}", file=self.err, flush=True)


def _error_code(error: Exception) -> str:
    """An AWS error by its code only: AWS messages can carry account IDs and ARNs."""
    if isinstance(error, ClientError):
        return str(error.response.get("Error", {}).get("Code", "ClientError"))
    return type(error).__name__


def sns_event(message: str, topic_arn: str) -> JSON:
    """An SNS event carrying ``message`` from the lab topic, as the intake receives one."""
    return {
        "Records": [
            {
                "EventSource": "aws:sns",
                "EventVersion": "1.0",
                "Sns": {
                    "Type": "Notification",
                    "MessageId": f"replay-{uuid.uuid4()}",
                    "TopicArn": topic_arn,
                    "Subject": "replay",
                    "Message": message,
                    "Timestamp": format_instant(utc_now()),
                },
            }
        ]
    }


def _is_on_failure_record(document: JSON) -> bool:
    payload = document.get("requestPayload")
    return (
        isinstance(document.get("requestContext"), dict)
        and isinstance(payload, dict)
        and isinstance(payload.get("Records"), list)
    )


def recognise(body: str, lab_topic_arn: str) -> Plan:
    """Tell which of the three shapes an item is, and how it goes back (BR6.6)."""
    try:
        document = json.loads(body)
    except ValueError:
        return Plan(Shape.UNRECOGNISED, "not JSON")
    if not isinstance(document, dict):
        return Plan(Shape.UNRECOGNISED, "not an object")
    if _is_on_failure_record(document):
        context = document["requestContext"]
        return Plan(Shape.ON_FAILURE, str(context.get("requestId", "")), document["requestPayload"])
    try:
        item = DeadLetterItem.model_validate(document)
    except ValidationError:
        item = None
    if item is not None and item.kind is not DeadLetterKind.SESSION_START:
        event = sns_event(item.original, lab_topic_arn)
        return Plan(Shape.INTAKE_ITEM, f"{item.dead_letter_id} ({item.kind}, {item.reason})", event)
    raw_start = item.original if item is not None else body
    try:
        request = SessionStartRequest.model_validate_json(raw_start)
    except ValidationError:
        return Plan(Shape.UNRECOGNISED, item.dead_letter_id if item else "unknown fields")
    return Plan(Shape.SESSION_START, f"incident {request.incident_id}", session_start=request)


def lambda_invoker(client: LambdaClient, function_name: str) -> IntakeInvoker:
    """Replay through the deployed intake function, waiting for its answer."""

    def invoke(event: JSON) -> Delivery:
        answer = client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(event).encode("utf-8"),
        )
        raw = answer["Payload"].read() if "Payload" in answer else b""
        result = json.loads(raw) if raw else {}
        if answer.get("FunctionError"):
            error_type = (
                result.get("errorType", "unknown") if isinstance(result, dict) else "unknown"
            )
            return Delivery(False, f"the intake failed ({error_type})")
        if isinstance(result, dict):
            return Delivery(
                True, ", ".join(f"{key} {value}" for key, value in sorted(result.items()))
            )
        return Delivery(True, "accepted")

    return invoke


def resolve_target(settings: Settings, sqs: SQSClient, lambda_client: LambdaClient) -> Target:
    """Find the two queues by name, and the lab topic the intake accepts."""
    configuration = lambda_client.get_function_configuration(FunctionName=settings.intake_function)
    variables = configuration.get("Environment", {}).get("Variables", {})
    topic = variables.get("LAB_TOPIC_ARN", "")
    if not topic:
        raise ValueError(f"the function {settings.intake_function} has no LAB_TOPIC_ARN")
    return Target(
        dead_letter_queue_url=sqs.get_queue_url(QueueName=settings.dead_letter_queue)["QueueUrl"],
        session_start_queue_url=sqs.get_queue_url(QueueName=settings.session_start_queue)[
            "QueueUrl"
        ],
        lab_topic_arn=topic,
    )


class Replayer:
    """Reads the dead-letter queue once, replaying or dropping what it can."""

    def __init__(
        self,
        settings: Settings,
        sqs: SQSClient,
        ledger: IncidentLedger,
        invoke_intake: IntakeInvoker,
        target: Target,
        console: Console,
    ) -> None:
        self._settings = settings
        self._sqs = sqs
        self._ledger = ledger
        self._invoke_intake = invoke_intake
        self._target = target
        self._console = console

    def run(self) -> int:
        seen: set[str] = set()
        kept = 0
        while len(seen) < self._settings.max_items:
            messages = self._receive(self._settings.max_items - len(seen))
            fresh = [message for message in messages if message["MessageId"] not in seen]
            if not fresh:
                break
            for message in fresh:
                seen.add(message["MessageId"])
                if not self._handle(message):
                    kept += 1
        done = len(seen) - kept
        self._console.say(
            f"{len(seen)} item(s) read; {done} replayed or dropped; {kept} left in the queue."
        )
        return 1 if kept else 0

    def _receive(self, room: int) -> list[MessageTypeDef]:
        answer = self._sqs.receive_message(
            QueueUrl=self._target.dead_letter_queue_url,
            MaxNumberOfMessages=max(1, min(10, room)),
            WaitTimeSeconds=1,
            VisibilityTimeout=self._settings.visibility_seconds,
        )
        return list(answer.get("Messages", []))

    def _handle(self, message: MessageTypeDef) -> bool:
        """Replay or drop one item; delete it when done. Return whether it is done."""
        plan = recognise(message.get("Body", ""), self._target.lab_topic_arn)
        if plan.shape is Shape.UNRECOGNISED:
            self._console.say(f"{plan.shape}: {plan.label}: left in the queue")
            return False
        try:
            done, detail = self._replay(plan)
        except (ClientError, BotoCoreError) as error:
            done, detail = False, f"failed: {_error_code(error)}"
        except StoreUnavailable as error:
            done, detail = False, f"failed: the incident table answered {error.last_error}"
        if done:
            self._sqs.delete_message(
                QueueUrl=self._target.dead_letter_queue_url, ReceiptHandle=message["ReceiptHandle"]
            )
        else:
            detail = f"{detail}; left in the queue"
        self._console.say(f"{plan.shape}: {plan.label}: {detail}")
        return done

    def _replay(self, plan: Plan) -> tuple[bool, str]:
        if plan.intake_event is not None:
            delivery = self._invoke_intake(plan.intake_event)
            prefix = "replayed through the intake" if delivery.accepted else "not replayed"
            return delivery.accepted, f"{prefix}: {delivery.detail}"
        request = plan.session_start
        if request is None:  # recognise() gives every other shape an event or a request
            return False, "nothing to replay"
        verdict = self._ledger.session_start_check(request.incident_id)
        if verdict is not SessionStartVerdict.ALLOWED:
            return True, f"dropped: {verdict}"
        self._sqs.send_message(
            QueueUrl=self._target.session_start_queue_url, MessageBody=request.model_dump_json()
        )
        return True, "sent back to the session-start queue"


def parse_args(argv: Sequence[str] | None) -> Settings:
    defaults = Settings()
    parser = argparse.ArgumentParser(
        description="Replay the dead-letter queue's items once their cause is fixed. "
        "Safe to run again."
    )
    parser.add_argument("--region", default=defaults.region)
    parser.add_argument(
        "--max-items", type=int, default=defaults.max_items, help="stop after this many items"
    )
    parser.add_argument(
        "--visibility-seconds",
        type=int,
        default=defaults.visibility_seconds,
        help="how long an item that stays is hidden before it is visible again",
    )
    args = parser.parse_args(argv)
    if args.max_items < 1 or args.visibility_seconds < 0:
        parser.error("--max-items must be 1 or more, and --visibility-seconds 0 or more")
    return Settings(
        region=args.region, max_items=args.max_items, visibility_seconds=args.visibility_seconds
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    session: boto3.Session | None = None,
    lambda_client: LambdaClient | None = None,
) -> int:
    """Replay the queue and return the exit status."""
    settings = parse_args(argv)
    console = Console()
    session = session or boto3.Session(region_name=settings.region)
    sqs = session.client("sqs")
    functions = lambda_client or session.client("lambda")
    ledger = IncidentLedger(
        session.client("dynamodb", config=LEDGER_CLIENT_CONFIG), settings.incident_table
    )
    try:
        target = resolve_target(settings, sqs, functions)
        invoke = lambda_invoker(functions, settings.intake_function)
        return Replayer(settings, sqs, ledger, invoke, target, console).run()
    except (ClientError, BotoCoreError) as error:
        console.error(f"an AWS call failed: {_error_code(error)}")
    except ValueError as error:
        console.error(str(error))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
