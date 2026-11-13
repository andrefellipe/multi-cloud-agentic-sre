"""SkeletonSettings: the tunable values of the skeleton, read at start-up (``entities.md``).

Each one has the default of ``entities.md`` and can be set through an environment
variable named ``SRE_`` plus the field name in capitals, for example
``SRE_SESSION_SEVERITIES=critical,warning``. A missing or invalid value stops
start-up with an error naming the variable.

The entity's two deployment names live with the component that needs them: the
lab topic with the intake (``LAB_TOPIC_ARN``), and the model ID with the session
(u1's last pull request). The settings that only the session or Terraform use
(the demo namespace, the step cap, the start attempts and the notice period)
arrive with the code that reads them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from pydantic import Field, ValidationError

from agents.contracts.common import ContractModel, NonEmptyStr

ENV_PREFIX: Final = "SRE_"
_LIST_FIELDS: Final = frozenset({"session_severities", "severity_order"})


class SettingsError(ValueError):
    """A setting is missing or invalid. The message names the environment variable."""


def require_setting(environ: Mapping[str, str], name: str) -> str:
    """Return the environment variable ``name``, or stop with an error naming it."""
    value = environ.get(name, "").strip()
    if not value:
        raise SettingsError(f"the environment variable {name} is not set")
    return value


class SkeletonSettings(ContractModel):
    """Thresholds and limits of the skeleton, with the defaults of ``entities.md``."""

    session_severities: tuple[NonEmptyStr, ...] = Field(
        default=("critical", "warning"), min_length=1
    )
    severity_order: tuple[NonEmptyStr, ...] = Field(
        default=("critical", "warning", "info"), min_length=1
    )
    idempotency_ttl_days: int = Field(default=14, ge=1)
    stale_session_minutes: int = Field(default=15, ge=5)
    ledger_write_attempts: int = Field(default=3, ge=1)
    session_start_deadline_seconds: int = Field(default=120, ge=1)
    notifier_attempts: int = Field(default=3, ge=1)

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> SkeletonSettings:
        """Read every setting from its ``SRE_*`` variable; an unset variable keeps the default.

        List values are comma-separated.
        """
        values: dict[str, object] = {}
        for name in cls.model_fields:
            raw = environ.get(f"{ENV_PREFIX}{name.upper()}")
            if raw is None:
                continue
            if name in _LIST_FIELDS:
                values[name] = tuple(part.strip() for part in raw.split(",") if part.strip())
            else:
                values[name] = raw.strip()
        try:
            return cls.model_validate(values)
        except ValidationError as error:
            first = error.errors()[0]
            variable = f"{ENV_PREFIX}{str(first['loc'][0]).upper()}"
            message = f"the environment variable {variable} is invalid: {first['msg']}"
            raise SettingsError(message) from None
