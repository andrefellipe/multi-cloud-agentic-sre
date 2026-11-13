"""Export the contracts as JSON Schema (contract design Q1).

The Pydantic models in ``agents/contracts/`` are the contracts; the JSON Schema
is derived from them, never written by hand. Write the schemas to a folder:

    uv run python -m agents.contracts.schema_export <folder>

Each contract becomes ``<folder>/<name>.schema.json``. With ``--check``, nothing
is written: the command compares the folder with the models and exits 1 when a
file is missing or differs, which suits a CI check.

Exit status: 0 when done (or, with ``--check``, when the folder is up to date),
1 when ``--check`` finds a difference, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from pydantic import BaseModel

from agents.contracts.alert import AlertNotification
from agents.contracts.dead_letter import DeadLetterItem
from agents.contracts.incident import InboundEvent, Incident
from agents.contracts.notify import NotifyRequest
from agents.contracts.session import AgentResult, SessionStartRequest

CONTRACT_MODELS: Final[Mapping[str, type[BaseModel]]] = MappingProxyType(
    {
        "c1-alert-notification": AlertNotification,
        "c3-incident": Incident,
        "c3-inbound-event": InboundEvent,
        "c4-session-start-request": SessionStartRequest,
        "c5-agent-result": AgentResult,
        "c7-notify-request": NotifyRequest,
        "dead-letter-item": DeadLetterItem,
    }
)
"""Each exported contract, by the file name it is written under."""


def contract_schemas() -> dict[str, dict[str, Any]]:
    """Return the JSON Schema of each contract, by name."""
    return {name: model.model_json_schema() for name, model in CONTRACT_MODELS.items()}


def render(schema: Mapping[str, Any]) -> str:
    """Return a schema as stable text: sorted keys, two-space indent, a final newline."""
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def export_schemas(folder: Path) -> list[Path]:
    """Write every contract's schema into ``folder`` and return the files written."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in contract_schemas().items():
        path = folder / f"{name}.schema.json"
        path.write_text(render(schema), encoding="utf-8")
        written.append(path)
    return written


def stale_schemas(folder: Path) -> list[str]:
    """Return the names of the contracts whose file in ``folder`` is missing or differs."""
    stale = []
    for name, schema in contract_schemas().items():
        path = folder / f"{name}.schema.json"
        if not path.is_file() or path.read_text(encoding="utf-8") != render(schema):
            stale.append(name)
    return stale


def main(argv: Sequence[str] | None = None) -> int:
    """Export or check the schemas, and return the exit status."""
    parser = argparse.ArgumentParser(description="Export the contracts as JSON Schema.")
    parser.add_argument("folder", type=Path, help="folder for the <name>.schema.json files")
    parser.add_argument(
        "--check", action="store_true", help="compare the folder with the models; write nothing"
    )
    args = parser.parse_args(argv)
    if args.check:
        stale = stale_schemas(args.folder)
        for name in stale:
            print(f"schema_export: {name}.schema.json is missing or out of date", file=sys.stderr)
        return 1 if stale else 0
    for path in export_schemas(args.folder):
        print(f"schema_export: wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
