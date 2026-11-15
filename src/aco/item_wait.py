"""The one typed `wait` of an item's `aco` block: what it is waiting for, since when."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import cast

from . import protocol
from .expectation_grammar import NOT_A_LOCAL_DATE

WAIT_KEY = "wait"
SINCE_KEY = "since"
OPERATOR_KEY = "operator"
UNTIL_KEY = "until"
TRIGGER_KEY = "trigger"
_KIND_KEYS = (OPERATOR_KEY, UNTIL_KEY, TRIGGER_KEY)
_WAIT_KEYS = frozenset((*_KIND_KEYS, SINCE_KEY))


@dataclass(frozen=True)
class OperatorWait:
    """Waits on a step only the operator can take."""

    step: str
    since: date


@dataclass(frozen=True)
class UntilWait:
    """Waits until a date: over once today is on or after it."""

    until: date
    since: date


@dataclass(frozen=True)
class TriggerWait:
    """Waits on a fact that an agent or the operator sees come true."""

    trigger: str
    since: date


ItemWait = OperatorWait | UntilWait | TriggerWait


def wait_defects(data: Mapping[str, object]) -> list[tuple[str, str]]:
    """The `(field, message)` refusals of the block's `wait`, none when it is absent."""
    if WAIT_KEY not in data:
        return []
    value = data[WAIT_KEY]
    if not isinstance(value, dict):
        return [(WAIT_KEY, f"{WAIT_KEY} must be a table")]
    table = cast("dict[str, object]", value)
    named = [key for key in _KIND_KEYS if key in table]
    defects: list[tuple[str, str]] = []
    if len(named) != 1:
        defects.append(
            (
                WAIT_KEY,
                f"{WAIT_KEY} must name exactly one of {OPERATOR_KEY}, {UNTIL_KEY}, {TRIGGER_KEY}",
            )
        )
    for key in named:
        if not _is_valid(key, table[key]):
            reason = NOT_A_LOCAL_DATE if key == UNTIL_KEY else "must be a non-empty string"
            defects.append((f"{WAIT_KEY}.{key}", f"{WAIT_KEY}.{key} {reason}"))
    if type(table.get(SINCE_KEY)) is not date:
        defects.append((f"{WAIT_KEY}.{SINCE_KEY}", f"{WAIT_KEY}.{SINCE_KEY} {NOT_A_LOCAL_DATE}"))
    defects.extend(
        (f"{WAIT_KEY}.{key}", f"unknown key {WAIT_KEY}.{key}")
        for key in sorted(set(table) - _WAIT_KEYS)
    )
    return defects


def _is_valid(key: str, value: object) -> bool:
    if key == UNTIL_KEY:
        return type(value) is date
    return isinstance(value, str) and bool(value.strip())


def parse_wait(data: Mapping[str, object]) -> ItemWait | None:
    """The block's `wait`, which `wait_defects` has already found valid."""
    value = data.get(WAIT_KEY)
    if value is None:
        return None
    table = cast("dict[str, object]", value)
    since = cast(date, table[SINCE_KEY])
    if OPERATOR_KEY in table:
        return OperatorWait(cast(str, table[OPERATOR_KEY]).strip(), since)
    if UNTIL_KEY in table:
        return UntilWait(cast(date, table[UNTIL_KEY]), since)
    return TriggerWait(cast(str, table[TRIGGER_KEY]).strip(), since)


def is_over(wait: ItemWait, today: date) -> bool:
    """Whether `today` frees the item: only an `until` wait ends by itself."""
    return isinstance(wait, UntilWait) and today >= wait.until


def wait_text(wait: ItemWait) -> str:
    """What the wait waits for, in the words `next` prints."""
    match wait:
        case OperatorWait(step=step):
            return step
        case UntilWait(until=until):
            return f"until {until.isoformat()}"
        case TriggerWait(trigger=trigger):
            return trigger


def operator_wait_table(
    step: str, today: date, block: Mapping[str, object] | None = None
) -> dict[str, object]:
    """The `wait` table that holds `step` for the operator. A `block` already
    holding that step for the operator keeps its `since`, so a repeat is no new wait."""
    held = None if block is None or wait_defects(block) else parse_wait(block)
    since = held.since if isinstance(held, OperatorWait) and held.step == step else today
    return {OPERATOR_KEY: step, SINCE_KEY: since}


def render_wait(data: Mapping[str, object]) -> list[str]:
    """The block lines of the `wait` entry, none when absent."""
    wait = parse_wait(data)
    if wait is None:
        return []
    since = f"{SINCE_KEY} = {wait.since.isoformat()}"
    match wait:
        case OperatorWait(step=step):
            kind = f"{OPERATOR_KEY} = {protocol.toml_string(step)}"
        case UntilWait(until=until):
            kind = f"{UNTIL_KEY} = {until.isoformat()}"
        case TriggerWait(trigger=trigger):
            kind = f"{TRIGGER_KEY} = {protocol.toml_string(trigger)}"
    return ["", f"{WAIT_KEY} = {{ {kind}, {since} }}"]


def active_wait_text(wait: ItemWait | None, today: date) -> str | None:
    """`wait_text` of a wait that still holds on `today`, `None` for none or an over one."""
    return None if wait is None or is_over(wait, today) else wait_text(wait)
