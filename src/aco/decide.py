"""The one write owner for rulings (`specs/rule.spec.md`): `aco rule` and the
decision board both read an item through the target gate and write its folded
body once, here, so every ruling takes the same path."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from . import board_read, body, expectations, protocol, workboard
from .session import RunContext

type Outcome = expectations.OptionChoice | expectations.HeadReturn


class InvalidTargetError(protocol.ClaimError):
    """The target gate's own "no such writable item" refusal -- missing, a pull request,
    or a malformed body -- so `rule` can choose its `invalid_item` without parsing
    prose."""


@dataclass(frozen=True)
class LineOutcome:
    """The outcome decided for one 1-based expectation line."""

    index: int
    outcome: Outcome


@dataclass(frozen=True)
class FreshItem:
    """One item as the target gate read it from the forge."""

    number: int
    title: str
    body: str
    storage: body.Storage


@dataclass(frozen=True)
class Committed:
    """The item as written: `lines` are every expectation line of the written body."""

    number: int
    title: str
    lines: tuple[expectations.ExpectationLine, ...]
    open_remaining: int


def fresh_item(context: RunContext, number: int) -> FreshItem:
    """The target gate (RULE-07, RULE-08): one forge read of the item, which
    must exist and not be a pull request, and whose body must parse."""
    client = context.forge_writer
    storage = context.config.storage
    try:
        reference = board_read.item_or_refuse(client, number, command="rule", storage=storage)
        current_body = reference.body or ""
        workboard.located_block_or_refuse(number, current_body, command="rule", storage=storage)
    except protocol.ClaimError as error:
        raise InvalidTargetError(str(error)) from error
    return FreshItem(number, reference.title or "", current_body, storage)


def _written_body(current_body: str, line: int, outcome: Outcome, today: date) -> str:
    if isinstance(outcome, expectations.HeadReturn):
        return expectations.return_to_head(current_body, line, outcome, today)
    return expectations.rule_option(current_body, line, outcome, today)


def rule(
    context: RunContext, fresh: FreshItem, named: Sequence[LineOutcome], today: date
) -> Committed:
    """Folds every named line over the fresh body with the one date `today` and
    writes it once. Raises `protocol.ClaimError` by name for every refusal
    (already ruled, out of range, a changed card, a bad outcome) before the
    write, so none of the lines is stored (RULE-29)."""
    new_body = fresh.body
    for line in named:
        new_body = _written_body(new_body, line.index, line.outcome, today)
    context.forge_writer.update_item_body(fresh.number, new_body)
    lines = tuple(expectations.expectation_lines(new_body, storage=fresh.storage))
    open_remaining = sum(map(expectations.is_open, lines))
    return Committed(fresh.number, fresh.title, lines, open_remaining)
