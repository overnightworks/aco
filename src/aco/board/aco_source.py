"""`DecisionPort` over aco's own library, in process.

A read lists every open item through `rulings.rows`, the rows `aco rulings`
prints. A decision reads its one item through `decide.fresh_item`, runs the
board's check on that read, and writes the whole card through `decide.rule`,
the writer `aco rule` uses. Every read and every write builds its own context
bound to the board's directory, so nothing read carries over between calls or
threads, and one write's read, check and write share that one context.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .. import decide, expectations, forge, protocol, rulings, session
from .ports import (
    OPTION_LETTERS,
    CardAnswer,
    CardChanged,
    CardCheck,
    CardDecision,
    CardLine,
    CardOption,
    DecisionResult,
    DecisionSourceUnavailableError,
    DecisionStatus,
    ExpectationLine,
    OptionLetter,
    OptionLine,
    OtherAnswer,
    OtherCardAnswer,
    Outcome,
    RulingVia,
    UnclearCardAnswer,
    YesNoLine,
)


@dataclass(frozen=True)
class AcoSource:
    directory: Path

    def expectation_lines(self) -> tuple[ExpectationLine, ...]:
        context = self._context()
        try:
            issues = context.forge.list_open_board_issues()
            rows = rulings.rows(issues, storage=context.config.storage)
        except protocol.ClaimError as error:
            raise DecisionSourceUnavailableError(str(error)) from error
        return tuple(
            line for row in rows for line in _board_lines(row.number, row.title, row.lines)
        )

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
    lines = expectations.expectation_lines(fresh.body, storage=fresh.storage)
    decision = check(_board_lines(item, fresh.title, lines))
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
        else cast(OptionLetter, line.letter)
    )
    # The only `via` the board writes: the cooperative path, never `chat` or
    # `default`, which belong to the operator's other writers.
    return expectations.OptionChoice(chosen, expectations.RulingVia.BOARD, line.card_hash)


def _board_lines(
    item: int, title: str, lines: Iterable[expectations.ExpectationLine]
) -> tuple[ExpectationLine, ...]:
    """`lines` in the board's types; a withdrawn line is not listed (ABRD-60)."""
    return tuple(
        _yes_no_line(item, title, line)
        if isinstance(line, expectations.YesNoLine)
        else _option_line(item, title, line)
        for line in lines
        if not isinstance(line, expectations.WithdrawnLine)
    )


def _yes_no_line(item: int, title: str, line: expectations.YesNoLine) -> YesNoLine:
    return YesNoLine(
        item=item,
        item_title=title,
        index=line.index,
        text=line.text,
        question=line.question,
        example=line.example,
        picture=line.picture,
        ruling=Outcome(line.ruling),
        ruled_on=line.ruled_on,
    )


def _option_line(item: int, title: str, line: expectations.OptionLine) -> OptionLine:
    decision, returned = line.decision, line.returned
    return OptionLine(
        item=item,
        item_title=title,
        index=line.index,
        text=line.text,
        question=line.question,
        problem=line.problem,
        picture=line.picture,
        caption=line.caption,
        decision_kind=line.decision_kind.value,
        area=line.area,
        topic=line.topic,
        recommended=_letter(line.recommended),
        reason=line.reason,
        options=tuple(_card_option(option) for option in line.options),
        ruling=None if decision is None else _ruling(decision.answer),
        ruled_on=line.ruled_on,
        via=None if decision is None else RulingVia(decision.via.value),
        returned_on=None if returned is None else returned.returned_on,
        returned_note=None if returned is None else returned.note,
        card_hash=line.card_hash,
    )


def _ruling(answer: str | expectations.OtherAnswer) -> OptionLetter | OtherAnswer:
    if isinstance(answer, expectations.OtherAnswer):
        return OtherAnswer(answer.text)
    return _letter(answer)


def _card_option(option: expectations.CardOption) -> CardOption:
    result = option.result
    return CardOption(
        letter=_letter(option.letter),
        name=option.name,
        effect=option.effect,
        picture=None if result is None else result.picture,
        caption=None if result is None else result.caption,
        notice=option.notice,
        cost=option.cost,
        undo=option.undo.value,
        undo_how=option.undo_how,
        contract=option.contract,
    )


def _letter(letter: str) -> OptionLetter:
    """aco's grammar letters a card's options A to D by position, so every letter
    it names is one of the board's."""
    return OPTION_LETTERS[OPTION_LETTERS.index(letter)]
