"""How the ledger's three kinds of item sit in the one incident table (SC-2).

- Incident: key ``INCIDENT#<incident_id>``; kept, with point-in-time recovery
  and deletion protection on the table.
- Open-incident marker: key ``OPEN#<service>``; it holds ``incident_id`` exactly
  while that incident is non-terminal.
- Inbound event: key ``EVENT#<idempotency_key>``; removed by the table's
  time-to-live through ``expires_at_epoch``.

Every write is an ``Update`` entry in a ``TransactWriteItems`` call, with a
condition. An update creates the item when it does not exist yet, and a marker
is released by removing its ``incident_id`` rather than by deleting it. So the
ledger needs only ``dynamodb:GetItem`` and ``dynamodb:UpdateItem``: it never puts,
deletes or scans. An update also leaves alone any attribute it does not name, so
a field a later unit adds survives a write by this code (contract C3, additive
changes).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.type_defs import (
        TransactWriteItemTypeDef,
        UniversalAttributeValueTypeDef,
        UpdateTypeDef,
    )

PK: Final = "pk"
ITEM_TYPE: Final = "item_type"
TTL_ATTRIBUTE: Final = "expires_at_epoch"
MARKER_INCIDENT: Final = "incident_id"

INCIDENT_ITEM: Final = "incident"
MARKER_ITEM: Final = "open_incident_marker"
EVENT_ITEM: Final = "inbound_event"

_SERIALIZER: Final = TypeSerializer()
_DESERIALIZER: Final = TypeDeserializer()

Key = dict[str, "UniversalAttributeValueTypeDef"]


def incident_key(incident_id: str) -> Key:
    return {PK: {"S": f"INCIDENT#{incident_id}"}}


def marker_key(service: str) -> Key:
    return {PK: {"S": f"OPEN#{service}"}}


def event_key(idempotency_key: str) -> Key:
    return {PK: {"S": f"EVENT#{idempotency_key}"}}


def serialize(value: Any) -> UniversalAttributeValueTypeDef:
    """One Python value (JSON types, ints, Decimals) as a DynamoDB attribute value."""
    serialized: UniversalAttributeValueTypeDef = _SERIALIZER.serialize(value)
    return serialized


def _plain(value: Any) -> Any:
    """Turn whole-number Decimals back into ints, through lists and maps."""
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    if isinstance(value, list):
        return [_plain(element) for element in value]
    if isinstance(value, dict):
        return {key: _plain(element) for key, element in value.items()}
    return value


def from_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """A DynamoDB item as plain Python values, ready for a contract model."""
    return {name: _plain(_DESERIALIZER.deserialize(value)) for name, value in item.items()}


@dataclass(frozen=True)
class Condition:
    """The condition of one write, with its own name and value placeholders."""

    expression: str
    names: Mapping[str, str] = field(default_factory=dict)
    values: Mapping[str, Any] = field(default_factory=dict)


ITEM_IS_NEW: Final = Condition("attribute_not_exists(#c_pk)", {"#c_pk": PK})
MARKER_IS_FREE: Final = Condition("attribute_not_exists(#c_inc)", {"#c_inc": MARKER_INCIDENT})


def version_is(version: int) -> Condition:
    """BR3.8: the item still has the version that was read."""
    return Condition("#c_ver = :c_ver", {"#c_ver": "version"}, {":c_ver": version})


def marker_points_to(incident_id: str) -> Condition:
    """BR3.1: the service's marker still names this incident."""
    return Condition("#c_inc = :c_inc", {"#c_inc": MARKER_INCIDENT}, {":c_inc": incident_id})


def update(
    table_name: str,
    key: Key,
    condition: Condition,
    set_fields: Mapping[str, Any],
    remove_fields: Sequence[str] = (),
) -> TransactWriteItemTypeDef:
    """One conditional ``Update`` entry of a transaction: set some attributes, remove others."""
    names: dict[str, str] = dict(condition.names)
    values = {placeholder: serialize(value) for placeholder, value in condition.values.items()}
    clauses = []
    for index, (name, value) in enumerate(set_fields.items()):
        names[f"#s{index}"] = name
        values[f":s{index}"] = serialize(value)
        clauses.append(f"#s{index} = :s{index}")
    expression = f"SET {', '.join(clauses)}" if clauses else ""
    removals = []
    for index, name in enumerate(remove_fields):
        names[f"#r{index}"] = name
        removals.append(f"#r{index}")
    if removals:
        expression = f"{expression} REMOVE {', '.join(removals)}".strip()
    entry: UpdateTypeDef = {
        "TableName": table_name,
        "Key": key,
        "UpdateExpression": expression,
        "ConditionExpression": condition.expression,
        "ExpressionAttributeNames": names,
    }
    if values:
        entry["ExpressionAttributeValues"] = values
    return {"Update": entry}
