"""The one read-modify-write of expectation lines (`specs/rule.spec.md`,
`specs/withdraw.spec.md`): `aco rule`, `aco withdraw` and the decision board
read an item through the target gate and write its folded body once, here,
so every ruling and every withdrawal takes the same path."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from . import board_read, body, expectations, forge, protocol, workboard
from .session import RunContext

type Outcome = expectations.OptionChoice | expectations.HeadReturn


class InvalidTargetError(protocol.ClaimError):
    """The target gate's own "no such writable item" refusal -- missing, a pull request,
    or a malformed body -- so a command can choose its `invalid_item` without parsing
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


def fresh_item(context: RunContext, number: int, *, command: str) -> FreshItem:
    """The target gate (RULE-07, RULE-08, WITHDRAW-10, WITHDRAW-11): one forge
    read of the item, which must exist and not be a pull request, and whose
    body must parse; its refusals name `command`. A failed forge read stays a
    `forge.ForgeError`, never a refused target (RULE-11, WITHDRAW-13)."""
    client = context.forge_writer
    storage = context.config.storage
    try:
        reference = board_read.item_or_refuse(client, number, command=command, storage=storage)
        current_body = reference.body or ""
        workboard.located_block_or_refuse(number, current_body, command=command, storage=storage)
    except forge.ForgeError:
        raise
    except protocol.ClaimError as error:
        raise InvalidTargetError(str(error)) from error
    return FreshItem(number, reference.title or "", current_body, storage)


def _written_body(current_body: str, line: int, outcome: Outcome, today: date) -> str:
    if isinstance(outcome, expectations.HeadReturn):
        return expectations.return_to_head(current_body, line, outcome, today)
    return expectations.rule_option(current_body, line, outcome, today)


def _committed(context: RunContext, fresh: FreshItem, new_body: str) -> Committed:
    """Writes `new_body` once and reads back the lines it holds."""
    context.forge_writer.update_item_body(fresh.number, new_body)
    lines = tuple(expectations.expectation_lines(new_body, storage=fresh.storage))
    open_remaining = sum(map(expectations.is_open, lines))
    return Committed(fresh.number, fresh.title, lines, open_remaining)


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
    return _committed(context, fresh, new_body)


def withdraw(
    context: RunContext, fresh: FreshItem, indexes: Sequence[int], today: date
) -> Committed:
    """Withdraws every named line of the fresh body with the one date `today`
    and writes it once. Raises `protocol.ClaimError` by name for every refusal
    (out of range, already withdrawn, ruled) before the write, so none of the
    lines is stored (WITHDRAW-04)."""
    new_body = fresh.body
    for index in indexes:
        new_body = expectations.withdraw_line(new_body, index, today)
    return _committed(context, fresh, new_body)
