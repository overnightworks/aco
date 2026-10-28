"""The `rule` command (`specs/rule.spec.md`)."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TypeAlias, cast

from . import (
    board_read,
    body,
    expectation_grammar,
    expectations,
    forge,
    protocol,
    report,
    workboard,
)
from .session import RepoMeaninglessUnderStateRefError, RunContext

_LINE = "--line"
_OPTION = "--option"
_OTHER = "--other"
_NOTE = "--note"
_VIA = "--via"
_CARD_HASH = "--card-hash"
_GIVEN_FLAGS = "given_flags"


@dataclass(frozen=True)
class _GivenFlag:
    """One flag and its value as the command line wrote it."""

    name: str
    value: str | int


class _RecordGivenFlag(argparse.Action):
    """Records each flag it parses, with its value, in the order written, in
    one tuple on the namespace: `--option` and `--card-hash` belong to the
    `--line` written before them, which separate attributes cannot say."""

    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, _GIVEN_FLAGS, default=argparse.SUPPRESS, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        given = getattr(namespace, _GIVEN_FLAGS, ())
        flag = _GivenFlag(cast(str, option_string), cast(str | int, values))
        setattr(namespace, _GIVEN_FLAGS, (*given, flag))


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """`rule`'s own flags; the `--json` flag stays `cli`'s one declaration."""
    parser.add_argument(
        "item", type=workboard.parse_item_reference, help="the item whose expectation line is ruled"
    )
    parser.add_argument(
        _LINE,
        action=_RecordGivenFlag,
        type=int,
        required=True,
        metavar="N",
        help="the 1-based expectation line index, as rulings prints it; "
        "repeat it to rule several lines of the item in one write",
    )
    outcome = parser.add_mutually_exclusive_group(required=True)
    outcome.add_argument(
        _OPTION,
        action=_RecordGivenFlag,
        metavar="X",
        help="the letter of the option card's answer; with several --line, after its --line",
    )
    outcome.add_argument(_OTHER, action=_RecordGivenFlag, metavar="TEXT", help="a free-text answer")
    outcome.add_argument(
        "--unclear",
        action="store_true",
        help="send an open option line back to its head; --note says why",
    )
    parser.add_argument(
        _NOTE,
        action=_RecordGivenFlag,
        metavar="NOTE",
        help="the note sent back to the head, with --unclear",
    )
    parser.add_argument(
        _VIA,
        action=_RecordGivenFlag,
        choices=[via.value for via in expectation_grammar.RulingVia],
        help="board, chat, or default when a presented card stayed unanswered",
    )
    parser.add_argument(
        _CARD_HASH,
        action=_RecordGivenFlag,
        metavar="HASH",
        help="the hash of the card the decider saw; with several --line, after its --line",
    )


class InvalidTargetError(protocol.ClaimError):
    """`require_writable_target`'s own "no such writable item" refusal -- missing, a pull request,
    or a malformed body -- so `rule` can choose its `invalid_item` without parsing
    prose."""


def require_writable_target(
    client: forge.ForgeWriter, context: RunContext, number: int, *, command: str
) -> tuple[str, workboard.BoardConfig]:
    """`rule`'s target gate (RULE-07, RULE-08): the item must exist and not be a
    pull request, and its body must parse. Returns the live body and the board
    configuration `rule` still needs for its write."""
    config = context.config
    try:
        body = board_read.item_body_or_refuse(
            client, number, command=command, storage=config.storage
        )
        workboard.located_block_or_refuse(number, body, command=command, storage=config.storage)
    except protocol.ClaimError as error:
        raise InvalidTargetError(str(error)) from error
    return body, config


def _rule_remaining_open(new_body: str, *, storage: body.Storage) -> int:
    return sum(
        1
        for line in expectations.expectation_lines(new_body, storage=storage)
        if line.ruling is None
    )


class _RuleReason(StrEnum):
    """`aco rule`'s own `--json` `reason` vocabulary (`specs/rule.spec.md`):
    `ruled` and `returned` are the successes."""

    RULED = "ruled"
    ALREADY_RULED = "already_ruled"
    LINE_OUT_OF_RANGE = "line_out_of_range"
    INVALID_ITEM = "invalid_item"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"
    CARD_CHANGED = "card_changed"
    RETURNED = "returned"
    WITH_HEAD = "with_head"


class FlagCombinationError(protocol.ClaimError):
    """RULE-15, RULE-21, RULE-26, RULE-33..35: `--option` or `--other` without
    `--via` and `--card-hash`, either of them without one of the two, `--note`
    beside either, `--via default` beside `--other`, a blank `--other`,
    `--unclear` without `--card-hash` or with `--via`, a blank `--note` beside
    it, a line named twice, a flag with no line or twice for one, and a flag
    given once given twice."""


Outcome: TypeAlias = expectations.OptionChoice | expectations.HeadReturn


@dataclass(frozen=True)
class _NamedLine:
    """A `--line` with the `--option` and `--card-hash` that belong to it."""

    index: int
    option: str | None
    card_hash: str | None


@dataclass(frozen=True)
class _SharedFlags:
    """The flags given once, which apply to every named line (RULE-35, RULE-36)."""

    other: str | None
    note: str | None
    via: str | None


@dataclass(frozen=True)
class _LineOutcome:
    index: int
    outcome: Outcome


_GIVEN_ONCE = (_OTHER, _NOTE, _VIA)
_PER_LINE = (_OPTION, _CARD_HASH)


def _refuse_a_repeated_shared_flag(given: Sequence[_GivenFlag]) -> None:
    seen: set[str] = set()
    for flag in given:
        if flag.name in _GIVEN_ONCE and flag.name in seen:
            raise FlagCombinationError(f"{flag.name} is given twice; give it once")
        seen.add(flag.name)


def _store_a_line_flag(
    flags_of: dict[int, dict[str, str]], owner: int | None, flag: _GivenFlag
) -> None:
    if owner is None:
        raise FlagCombinationError(f"{flag.name} before the first --line belongs to no line")
    if flag.name in flags_of[owner]:
        raise FlagCombinationError(f"line {owner} has a second {flag.name}")
    flags_of[owner][flag.name] = cast(str, flag.value)


def _flags_of_each_line(given: Sequence[_GivenFlag]) -> dict[int, dict[str, str]]:
    """Each named line's `--option` and `--card-hash`: with several `--line` the
    ones written after it, with one `--line` wherever they stand. Refuses in
    written order what pairs with no line or twice (RULE-33, RULE-34)."""
    indexes = [cast(int, flag.value) for flag in given if flag.name == _LINE]
    flags_of: dict[int, dict[str, str]] = {index: {} for index in indexes}
    owner = indexes[0] if len(indexes) == 1 else None
    named: set[int] = set()
    for flag in given:
        if flag.name == _LINE:
            index = cast(int, flag.value)
            if index in named:
                raise FlagCombinationError(f"line {index} is named twice")
            named.add(index)
            owner = index if len(indexes) > 1 else owner
        elif flag.name in _PER_LINE:
            _store_a_line_flag(flags_of, owner, flag)
    return flags_of


def _named_lines(given: Sequence[_GivenFlag]) -> tuple[_NamedLine, ...]:
    lines = tuple(
        _NamedLine(index, flags.get(_OPTION), flags.get(_CARD_HASH))
        for index, flags in _flags_of_each_line(given).items()
    )
    if len(lines) > 1:
        _refuse_a_line_without_its_own_flags(lines)
    return lines


def _refuse_a_line_without_its_own_flags(lines: Sequence[_NamedLine]) -> None:
    """RULE-15's count bullets, line by line in written order."""
    letters_given = any(line.option is not None for line in lines)
    for line in lines:
        if letters_given and line.option is None:
            raise FlagCombinationError(f"line {line.index} needs its own --option after it")
        if line.card_hash is None:
            raise FlagCombinationError(f"line {line.index} needs its own --card-hash after it")


def _shared_flags(given: Sequence[_GivenFlag]) -> _SharedFlags:
    once = {flag.name: cast(str, flag.value) for flag in given if flag.name in _GIVEN_ONCE}
    return _SharedFlags(once.get(_OTHER), once.get(_NOTE), once.get(_VIA))


def _via_and_card_hash(
    shared: _SharedFlags, line: _NamedLine, flag: str
) -> tuple[expectation_grammar.RulingVia, str]:
    if shared.via is None or line.card_hash is None:
        raise FlagCombinationError(f"{flag} needs --via and --card-hash")
    return expectation_grammar.RulingVia(shared.via), line.card_hash


def _letter_choice(
    letter: str, line: _NamedLine, shared: _SharedFlags
) -> expectations.OptionChoice:
    via, card_hash = _via_and_card_hash(shared, line, _OPTION)
    if shared.note is not None:
        raise FlagCombinationError(
            "--note does not go with --option; keep the operator's word in the item's journal"
        )
    return expectations.OptionChoice(letter, via, card_hash)


def _other_choice(text: str, line: _NamedLine, shared: _SharedFlags) -> expectations.OptionChoice:
    via, card_hash = _via_and_card_hash(shared, line, _OTHER)
    if shared.note is not None:
        raise FlagCombinationError("--note does not go with --other; its text is the answer")
    if via is expectation_grammar.RulingVia.DEFAULT:
        raise FlagCombinationError("--via default keeps only the recommended option, not --other")
    if not text.strip():
        raise FlagCombinationError("--other needs a non-empty answer")
    return expectations.OptionChoice(expectations.OtherAnswer(text), via, card_hash)


def _head_return(line: _NamedLine, shared: _SharedFlags) -> expectations.HeadReturn:
    if line.card_hash is None:
        raise FlagCombinationError("--unclear needs --card-hash")
    if shared.via is not None:
        raise FlagCombinationError("--via does not go with --unclear; nothing is decided")
    if shared.note is not None and not shared.note.strip():
        raise FlagCombinationError("a blank --note says nothing; leave it out")
    return expectations.HeadReturn(shared.note, line.card_hash)


def _outcome(line: _NamedLine, shared: _SharedFlags) -> Outcome:
    """The one outcome the flags name for `line`, or RULE-15's refusal of their
    combination -- before any forge call."""
    if line.option is not None:
        return _letter_choice(line.option, line, shared)
    if shared.other is not None:
        return _other_choice(shared.other, line, shared)
    return _head_return(line, shared)


def _line_outcomes(parsed: argparse.Namespace) -> tuple[_LineOutcome, ...]:
    """Every named line with its outcome, refused in RULE-35, RULE-33/34, RULE-15
    order -- before any forge call."""
    given: tuple[_GivenFlag, ...] = parsed.given_flags
    _refuse_a_repeated_shared_flag(given)
    lines = _named_lines(given)
    shared = _shared_flags(given)
    return tuple(_LineOutcome(line.index, _outcome(line, shared)) for line in lines)


def _emit_rule_result(
    number: int,
    lines: Sequence[expectations.ExpectationLine],
    open_remaining: int,
    storage: body.Storage,
    *,
    as_json: bool,
) -> None:
    ruled_on = cast(date, lines[0].ruled_on).isoformat()
    rulings = [(line.index, cast(str, line.ruling)) for line in lines]
    if as_json:
        which = (
            {"index": rulings[0][0], "ruling": rulings[0][1]}
            if len(rulings) == 1
            else {"lines": [{"index": index, "ruling": ruling} for index, ruling in rulings]}
        )
        report.emit_json(
            True, _RuleReason.RULED, item=number, **which, ruled_on=ruled_on, open=open_remaining
        )
        return
    noun = "line" if len(rulings) == 1 else "lines"
    named = ", ".join(f"{index} {ruling}" for index, ruling in rulings)
    print(
        f"RULED {workboard.item_label(number, storage)} {noun} {named}; "
        f"{open_remaining} line(s) still open"
    )


def _written_body(current_body: str, line: int, outcome: Outcome, today: date) -> str:
    if isinstance(outcome, expectations.HeadReturn):
        return expectations.return_to_head(current_body, line, outcome, today)
    return expectations.rule_option(current_body, line, outcome, today)


def _emit_returned_result(
    number: int,
    lines: Sequence[expectations.OptionLine],
    open_remaining: int,
    storage: body.Storage,
    *,
    as_json: bool,
) -> None:
    returned_on = cast(expectations.ReturnedToHead, lines[0].returned).returned_on.isoformat()
    indexes = [line.index for line in lines]
    if as_json:
        which = (
            {"index": indexes[0]}
            if len(indexes) == 1
            else {"lines": [{"index": index} for index in indexes]}
        )
        report.emit_json(
            True,
            _RuleReason.RETURNED,
            item=number,
            **which,
            returned_on=returned_on,
            open=open_remaining,
        )
        return
    noun = "line" if len(indexes) == 1 else "lines"
    print(
        f"RETURNED {workboard.item_label(number, storage)} {noun} "
        f"{', '.join(map(str, indexes))} to its head; {open_remaining} line(s) still open"
    )


def _rule_item(
    context: RunContext, number: int, named: Sequence[_LineOutcome], today: date
) -> tuple[tuple[expectations.ExpectationLine, ...], int]:
    """`run`'s own write: folds every named line over the body read once, with the
    one date `today`, and writes it once; returns the newly ruled lines and how many the
    item still has open. Raises `protocol.ClaimError` by name for every refusal
    (already ruled, out of range, a bad outcome, a malformed or missing item)
    before the write, so none of the lines is stored, which `run` turns into
    its own by-name response."""
    client = context.forge_writer
    current_body, config = require_writable_target(client, context, number, command="rule")
    new_body = current_body
    for line in named:
        new_body = _written_body(new_body, line.index, line.outcome, today)
    client.update_item_body(number, new_body)
    lines = expectations.expectation_lines(new_body, storage=config.storage)
    ruled = tuple(lines[line.index - 1] for line in named)
    return ruled, _rule_remaining_open(new_body, storage=config.storage)


# Each refusal's `--json` `reason`, by its type; any other refusal is a
# forge that failed, `unavailable`.
_REFUSAL_REASONS: tuple[tuple[type[protocol.ClaimError], _RuleReason], ...] = (
    (InvalidTargetError, _RuleReason.INVALID_ITEM),
    (expectations.ExpectationAlreadyRuledError, _RuleReason.ALREADY_RULED),
    (expectations.ExpectationOutOfRangeError, _RuleReason.LINE_OUT_OF_RANGE),
    (expectations.ExpectationCardChangedError, _RuleReason.CARD_CHANGED),
    (expectations.ExpectationLineFormError, _RuleReason.INVALID_USAGE),
    (expectations.ExpectationWithHeadError, _RuleReason.WITH_HEAD),
    (expectations.ExpectationOptionChoiceError, _RuleReason.INVALID_USAGE),
    (FlagCombinationError, _RuleReason.INVALID_USAGE),
    (RepoMeaninglessUnderStateRefError, _RuleReason.INVALID_USAGE),
)


def _refusal_reason(error: protocol.ClaimError) -> _RuleReason:
    return next(
        (reason for kind, reason in _REFUSAL_REASONS if isinstance(error, kind)),
        _RuleReason.UNAVAILABLE,
    )


def _rule_expectation_lines(parsed: argparse.Namespace, context: RunContext) -> int:
    """`rule`'s own work, every refusal raised by name for `run` to
    report."""
    named = _line_outcomes(parsed)
    number = int(parsed.item)
    ruled, open_remaining = _rule_item(context, number, named, context.today())
    storage = context.config.storage
    if isinstance(named[0].outcome, expectations.HeadReturn):
        returned = cast(tuple[expectations.OptionLine, ...], ruled)
        _emit_returned_result(number, returned, open_remaining, storage, as_json=parsed.json)
    else:
        _emit_rule_result(number, ruled, open_remaining, storage, as_json=parsed.json)
    return 0


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`rule`'s own `--json` refusals, for the whole command and
    not only its first steps: the body write inside the shared
    ruling path can fail like any other forge call, and a failure there names
    this command's own `unavailable` rather than escaping the envelope."""
    try:
        return _rule_expectation_lines(parsed, context)
    except protocol.ClaimError as error:
        return report.refuse(_refusal_reason(error), error, as_json=parsed.json)
