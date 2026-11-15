"""The one typed `handover` of an item's `aco` block: who took the item's claim over from
whom, why and on which day. Only the latest handover stays; the state ref's history keeps
every earlier one."""

import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import cast

from . import protocol
from .expectation_grammar import NOT_A_LOCAL_DATE
from .toml_text import toml_string

HANDOVER_KEY = "handover"
FROM_KEY = "from"
TO_KEY = "to"
REASON_KEY = "reason"
ON_KEY = "on"
REASON_TEXT_MAXIMUM = 512
_TEXT_KEYS = (FROM_KEY, TO_KEY, REASON_KEY)
_HANDOVER_KEYS = frozenset((*_TEXT_KEYS, ON_KEY))


@dataclass(frozen=True)
class ItemHandover:
    """The claim of the item went from `from_agent` to `to_agent` on `on`, for `reason`."""

    from_agent: str
    to_agent: str
    reason: str
    on: date


def _is_one_line_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not protocol.has_line_control(value)


def handover_defects(data: Mapping[str, object]) -> list[tuple[str, str]]:
    """The `(field, message)` refusals of the block's `handover`, none when it is absent."""
    if HANDOVER_KEY not in data:
        return []
    value = data[HANDOVER_KEY]
    if not isinstance(value, dict):
        return [(HANDOVER_KEY, f"{HANDOVER_KEY} must be a table")]
    table = cast("dict[str, object]", value)
    defects = [
        (f"{HANDOVER_KEY}.{key}", f"{HANDOVER_KEY}.{key} must be a non-empty one-line string")
        for key in _TEXT_KEYS
        if not _is_one_line_text(table.get(key))
    ]
    if type(table.get(ON_KEY)) is not date:
        defects.append((f"{HANDOVER_KEY}.{ON_KEY}", f"{HANDOVER_KEY}.{ON_KEY} {NOT_A_LOCAL_DATE}"))
    defects.extend(
        (f"{HANDOVER_KEY}.{key}", f"unknown key {HANDOVER_KEY}.{key}")
        for key in sorted(set(table) - _HANDOVER_KEYS)
    )
    return defects


def parse_handover(data: Mapping[str, object]) -> ItemHandover | None:
    """The block's `handover`, which `handover_defects` has already found valid."""
    value = data.get(HANDOVER_KEY)
    if value is None:
        return None
    table = cast("dict[str, object]", value)
    return ItemHandover(
        cast(str, table[FROM_KEY]),
        cast(str, table[TO_KEY]),
        cast(str, table[REASON_KEY]),
        cast(date, table[ON_KEY]),
    )


def handover_table(handover: ItemHandover) -> dict[str, object]:
    """The `handover` table of `handover`, as a block carries it."""
    return {
        FROM_KEY: handover.from_agent,
        TO_KEY: handover.to_agent,
        REASON_KEY: handover.reason,
        ON_KEY: handover.on,
    }


def render_handover(data: Mapping[str, object]) -> list[str]:
    """The block lines of the `handover` entry, none when absent."""
    handover = parse_handover(data)
    if handover is None:
        return []
    fields = (
        f"{FROM_KEY} = {toml_string(handover.from_agent)}",
        f"{TO_KEY} = {toml_string(handover.to_agent)}",
        f"{REASON_KEY} = {toml_string(handover.reason)}",
        f"{ON_KEY} = {handover.on.isoformat()}",
    )
    return ["", f"{HANDOVER_KEY} = {{ {', '.join(fields)} }}"]


def handover_route(identity: protocol.ClaimIdentity, holder: str) -> str | None:
    """The command a successor takes the claim of `identity`, held by `holder`, over with:
    only an item's claim has one."""
    if not isinstance(identity, protocol.IssueIdentity):
        return None
    return f"aco handover {identity.issue} --{FROM_KEY} {shlex.quote(holder)} --{REASON_KEY} <text>"
