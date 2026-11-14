"""`DecisionPort` over aco's own library, in process.

A read lists the members' open items once through `inbox.read_context`: the rows
`aco rulings` prints on the items a member wrote. A decision reads its one item inside
`decide.turn` (the item's lock, then the fresh read), runs the board's check on
aco's own lines of that read, and writes the whole card through `decide.rule`, the
writer `aco rule` uses. Every read and every write builds its own context bound
to the board's directory, so nothing read carries over between calls or threads,
and one write's read, check and write share that one context.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .. import decide, expectations, forge, inbox, protocol, repositories, session
from .ports import (
    CardAnswer,
    CardChanged,
    CardCheck,
    CardDecision,
    CardLine,
    DecisionResult,
    DecisionSourceUnavailableError,
    DecisionStatus,
    OtherCardAnswer,
    UnclearCardAnswer,
)

WRITTEN_OVER_NOTE = (
    "Written over a change aco had not read; that change is only in the item's edit history."
)
"""The note of a decision the forge's body check kept (ABRD-129)."""


@dataclass(frozen=True)
class _ReadItem:
    """An item as one read of the forge shows it."""

    number: int
    title: str
    lines: tuple[expectations.ExpectationLine, ...]


@dataclass(frozen=True)
class AcoSource:
    directory: Path

    def reading(self) -> inbox.Reading:
        context = self._context()
        try:
            return inbox.read_context(context)
        except protocol.ClaimError as error:
            raise DecisionSourceUnavailableError(str(error)) from error

    def rule_card(self, item: int, check: CardCheck) -> DecisionResult | CardChanged:
        context = self._context()
        try:
            return _checked_and_written(context, item, check)
        except decide.InvalidTargetError:
            return CardChanged()
        except expectations.ExpectationAlreadyRuledError as error:
            return DecisionResult(DecisionStatus.ALREADY_RULED, str(error))
        except protocol.ClaimError as error:
            return DecisionResult(DecisionStatus.FAILED, str(error))

    def _context(self) -> session.RunContext:
        # Looked up on the module at every call, so a replaced `run_context`
        # (the board's test forge) reaches every read and write.
        return session.run_context(None).for_directory(self.directory)


def _checked_and_written(
    context: session.RunContext, item: int, check: CardCheck
) -> DecisionResult | CardChanged:
    """One read of `item`, `check` on that read, then one write of the card."""
    with decide.turn(
        context, item, command="rule", environment=os.environ, home=Path.home()
    ) as fresh:
        return _checked_and_written_in_turn(context, fresh, check)


def _checked_and_written_in_turn(
    context: session.RunContext, fresh: decide.FreshItem, check: CardCheck
) -> DecisionResult | CardChanged:
    if fresh.state is not forge.ItemState.OPEN:
        return CardChanged()
    decision = check(expectations.expectation_lines(fresh.body, storage=fresh.storage))
    if decision is None:
        return CardChanged()
    returned = isinstance(decision.answer, UnclearCardAnswer)
    status = DecisionStatus.RETURNED if returned else DecisionStatus.RULED
    try:
        committed = decide.rule(
            context,
            fresh,
            _line_outcomes(decision),
            context.today(),
            state=repositories.state_directory(os.environ, Path.home()),
        )
    except forge.ForgeBodyOverwrittenError as error:
        if not error.kept:
            raise
        # The write is the newest revision and stands; only the change before it
        # is in the history alone.
        return DecisionResult(status, item=_item_as_read(context, fresh), note=WRITTEN_OVER_NOTE)
    return DecisionResult(status, item=committed)


def _item_as_read(context: session.RunContext, written: decide.FreshItem) -> _ReadItem:
    """The item as the forge holds it now, read once more."""
    fresh = decide.fresh_item(context, written.number, command="rule")
    lines = tuple(expectations.expectation_lines(fresh.body, storage=fresh.storage))
    return _ReadItem(fresh.number, fresh.title, lines)


def _line_outcomes(decision: CardDecision) -> tuple[decide.LineOutcome, ...]:
    return tuple(
        decide.LineOutcome(line.index, _outcome(line, decision.answer)) for line in decision.lines
    )


def _outcome(line: CardLine, answer: CardAnswer) -> decide.Outcome:
    if isinstance(answer, UnclearCardAnswer):
        return expectations.HeadReturn(answer.note, line.card_hash)
    chosen: str | expectations.OtherAnswer = (
        expectations.OtherAnswer(answer.text)
        if isinstance(answer, OtherCardAnswer)
        # A card without one answer for all carries a letter on every line (ABRD-77).
        else cast(str, line.letter)
    )
    # The only `via` the board writes: the cooperative path, never `chat` or
    # `default`, which belong to the operator's other writers.
    return expectations.OptionChoice(chosen, expectations.RulingVia.BOARD, line.card_hash)
