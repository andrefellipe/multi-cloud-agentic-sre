"""Timeouts and retries of the AWS clients the pipeline creates (RD-3).

- Ledger calls (DynamoDB): 2 s, and no retry in the SDK, since the ledger makes
  its own three attempts around each whole write (contract C3, BR6.1).
- Queue sends (SQS): 2 s, with 2 retries.
- Secret reads (Secrets Manager) and metric reads (CloudWatch): 2 s, with 2 retries.

botocore counts the first try among ``max_attempts``.
"""

from __future__ import annotations

from typing import Final

from botocore.config import Config

QUEUE_SEND_ATTEMPTS: Final = 3

LEDGER_CLIENT_CONFIG: Final = Config(
    connect_timeout=2, read_timeout=2, retries={"max_attempts": 1, "mode": "standard"}
)
QUEUE_CLIENT_CONFIG: Final = Config(
    connect_timeout=2,
    read_timeout=2,
    retries={"max_attempts": QUEUE_SEND_ATTEMPTS, "mode": "standard"},
)
READ_CLIENT_CONFIG: Final = Config(
    connect_timeout=2, read_timeout=2, retries={"max_attempts": 3, "mode": "standard"}
)
