"""Structured logs (OD-2) and embedded metrics (OD-3) for the pipeline's components.

Logs are JSON lines from the Powertools Logger. Beside the logger's own envelope
(level, location, message, timestamp, service), a line may carry only the fields
of OD-2's allow-list: ``component``, ``incident_id``, ``key_prefix``,
``session_id``, ``outcome``, ``reason``, ``error_class``, ``duration_ms`` and
``attempt``. :meth:`Telemetry.log` accepts nothing else, so a message body, a
label, a URL or a secret cannot reach a log line by accident (REQ-103.2). The
message text itself is always a fixed string written in the code.

Metrics are CloudWatch embedded-metric lines in the namespace ``SreLab/Skeleton``,
with the dimension ``component`` and, where OD-3 lists it, ``reason``; never an
incident ID. Each metric is written on its own line as soon as it is counted, so
a crash later in the invocation loses none.
"""

from __future__ import annotations

import functools
import logging
import sys
from typing import Final, Literal, Protocol, TextIO

from aws_lambda_powertools import Logger
from aws_lambda_powertools.metrics import MetricUnit, single_metric

METRICS_NAMESPACE: Final = "SreLab/Skeleton"

Level = Literal["INFO", "WARNING", "ERROR"]


class MetricSink(Protocol):
    """Where a library counts its metrics, such as the ledger's LedgerWrites."""

    def count(self, metric: str, value: int = 1, *, reason: str | None = None) -> None: ...


class _StdoutHandler(logging.StreamHandler[TextIO]):
    """Writes each record to whatever ``sys.stdout`` is at that moment.

    Lambda collects standard output, and a test's capture replaces it per test.
    """

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stdout
        super().emit(record)


@functools.cache
def _logger(component: str) -> Logger:
    """One Powertools Logger per component and process, as Powertools expects."""
    logger = Logger(service=component, logger_handler=_StdoutHandler())
    logger.append_keys(component=component)
    return logger


class Telemetry:
    """The logs and metrics of one component: ``intake``, ``ledger``, ``notifier``."""

    def __init__(self, component: str, *, namespace: str = METRICS_NAMESPACE) -> None:
        self.component = component
        self._namespace = namespace

    def log(
        self,
        message: str,
        *,
        level: Level = "INFO",
        outcome: str | None = None,
        reason: str | None = None,
        incident_id: str | None = None,
        key_prefix: str | None = None,
        session_id: str | None = None,
        error_class: str | None = None,
        duration_ms: int | None = None,
        attempt: int | None = None,
    ) -> None:
        """Write one log line with only the allow-listed fields that are set."""
        fields = {
            "outcome": outcome,
            "reason": reason,
            "incident_id": incident_id,
            "key_prefix": key_prefix,
            "session_id": session_id,
            "error_class": error_class,
            "duration_ms": duration_ms,
            "attempt": attempt,
        }
        extra = {name: value for name, value in fields.items() if value is not None}
        logger = _logger(self.component)
        write = {"INFO": logger.info, "WARNING": logger.warning, "ERROR": logger.error}[level]
        write(message, extra=extra)

    def count(self, metric: str, value: int = 1, *, reason: str | None = None) -> None:
        """Count ``value`` occurrences of ``metric``, by ``reason`` when one is given."""
        self._emit(metric, MetricUnit.Count, value, reason)

    def seconds(self, metric: str, value: float) -> None:
        """Record a duration in seconds, such as AlertToRecordSeconds."""
        self._emit(metric, MetricUnit.Seconds, value, None)

    def _emit(self, metric: str, unit: MetricUnit, value: float, reason: str | None) -> None:
        with single_metric(
            name=metric,
            unit=unit,
            value=value,
            namespace=self._namespace,
            default_dimensions={"component": self.component},
        ) as single:
            if reason is not None:
                single.add_dimension(name="reason", value=reason)
