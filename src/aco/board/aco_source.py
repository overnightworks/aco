"""`DecisionPort` over aco's own library, in process.

A read lists every open item through `rulings.rows`, the rows `aco rulings`
prints. A decision reads its one item through `decide.fresh_item`, runs the
board's check on aco's own lines of that read, and writes the whole card
through `decide.rule`, the writer `aco rule` uses. Every read and every write
builds its own context bound to the board's directory, so nothing read carries
over between calls or threads, and one write's read, check and write share
that one context.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .. import decide, expectations, forge, protocol, rulings, session
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


@dataclass(frozen=True)
class AcoSource:
    directory: Path

    def rows(self) -> tuple[rulings.Row, ...]:
        context = self._context()
        try:
            issues = context.forge.list_open_board_issues()
            return rulings.rows(issues, storage=context.config.storage)
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
    fresh = decide.fresh_item(context, item, command="rule")
    if fresh.state is not forge.ItemState.OPEN:
        return CardChanged()
    decision = check(expectations.expectation_lines(fresh.body, storage=fresh.storage))
    if decision is None:
        return CardChanged()
    decide.rule(context, fresh, _line_outcomes(decision), context.today())
    if isinstance(decision.answer, UnclearCardAnswer):
        return DecisionResult(DecisionStatus.RETURNED)
    return DecisionResult(DecisionStatus.RULED)


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
