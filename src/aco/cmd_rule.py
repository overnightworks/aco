"""The `rule` command (`specs/rule.spec.md`)."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
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


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """`rule`'s own flags; the `--json` flag stays `cli`'s one declaration."""
    parser.add_argument(
        "item", type=workboard.parse_item_reference, help="the item whose expectation line is ruled"
    )
    parser.add_argument(
        "--line",
        type=int,
        required=True,
        metavar="N",
        help="the 1-based expectation line index, as rulings prints it",
    )
    outcome = parser.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--option", metavar="X", help="the letter of the option card's answer")
    outcome.add_argument("--other", metavar="TEXT", help="a free-text answer")
    outcome.add_argument(
        "--unclear",
        action="store_true",
        help="send an open option line back to its head; --note says why",
    )
    parser.add_argument("--note", help="the note sent back to the head, with --unclear")
    parser.add_argument(
        "--via",
        choices=[via.value for via in expectation_grammar.RulingVia],
        help="board, chat, or default when a presented card stayed unanswered",
    )
    parser.add_argument("--card-hash", metavar="HASH", help="the hash of the card the decider saw")


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
    """RULE-15, RULE-21, RULE-26: `--option` or `--other` without `--via` and
    `--card-hash`, either of them without one of the two, `--note` beside
    either, `--via default` beside `--other`, a blank `--other`, `--unclear`
    without `--card-hash` or with `--via`, or a blank `--note` beside it."""


Outcome: TypeAlias = expectations.OptionChoice | expectations.HeadReturn


def _require_via_and_card_hash(parsed: argparse.Namespace, flag: str) -> None:
    if parsed.via is None or parsed.card_hash is None:
        raise FlagCombinationError(f"{flag} needs --via and --card-hash")


def _letter_choice(parsed: argparse.Namespace) -> expectations.OptionChoice:
    _require_via_and_card_hash(parsed, "--option")
    if parsed.note is not None:
        raise FlagCombinationError(
            "--note does not go with --option; keep the operator's word in the item's journal"
        )
    via = expectation_grammar.RulingVia(parsed.via)
    return expectations.OptionChoice(parsed.option, via, parsed.card_hash)


def _other_choice(parsed: argparse.Namespace) -> expectations.OptionChoice:
    _require_via_and_card_hash(parsed, "--other")
    if parsed.note is not None:
        raise FlagCombinationError("--note does not go with --other; its text is the answer")
    via = expectation_grammar.RulingVia(parsed.via)
    if via is expectation_grammar.RulingVia.DEFAULT:
        raise FlagCombinationError("--via default keeps only the recommended option, not --other")
    if not parsed.other.strip():
        raise FlagCombinationError("--other needs a non-empty answer")
    return expectations.OptionChoice(expectations.OtherAnswer(parsed.other), via, parsed.card_hash)


def _head_return(parsed: argparse.Namespace) -> expectations.HeadReturn:
    if parsed.card_hash is None:
        raise FlagCombinationError("--unclear needs --card-hash")
    if parsed.via is not None:
        raise FlagCombinationError("--via does not go with --unclear; nothing is decided")
    if parsed.note is not None and not parsed.note.strip():
        raise FlagCombinationError("a blank --note says nothing; leave it out")
    return expectations.HeadReturn(parsed.note, parsed.card_hash)


def _outcome(parsed: argparse.Namespace) -> Outcome:
    """The one outcome the flags name, or RULE-15's refusal of their
    combination -- before any forge call."""
    if parsed.option is not None:
        return _letter_choice(parsed)
    if parsed.other is not None:
        return _other_choice(parsed)
    return _head_return(parsed)


def _emit_rule_result(
    number: int,
    line: expectations.ExpectationLine,
    open_remaining: int,
    storage: body.Storage,
    *,
    as_json: bool,
) -> None:
    ruling = cast(str, line.ruling)
    ruled_on = cast(date, line.ruled_on)
    if as_json:
        report.emit_json(
            True,
            _RuleReason.RULED,
            item=number,
            index=line.index,
            ruling=ruling,
            ruled_on=ruled_on.isoformat(),
            open=open_remaining,
        )
        return
    print(
        f"RULED {workboard.item_label(number, storage)} line {line.index} {ruling}; "
        f"{open_remaining} line(s) still open"
    )


def _written_body(current_body: str, line: int, outcome: Outcome) -> str:
    today = datetime.now(UTC).date()
    if isinstance(outcome, expectations.HeadReturn):
        return expectations.return_to_head(current_body, line, outcome, today)
    return expectations.rule_option(current_body, line, outcome, today)


def _emit_returned_result(
    number: int,
    line: expectations.OptionLine,
    open_remaining: int,
    storage: body.Storage,
    *,
    as_json: bool,
) -> None:
    returned = cast(expectations.ReturnedToHead, line.returned)
    if as_json:
        report.emit_json(
            True,
            _RuleReason.RETURNED,
            item=number,
            index=line.index,
            returned_on=returned.returned_on.isoformat(),
            open=open_remaining,
        )
        return
    print(
        f"RETURNED {workboard.item_label(number, storage)} line {line.index} to its head; "
        f"{open_remaining} line(s) still open"
    )


def _rule_item(
    context: RunContext, number: int, line: int, outcome: Outcome
) -> tuple[expectations.ExpectationLine, int]:
    """`run`'s own write: returns the newly ruled line and
    how many the item still has open; raises `protocol.ClaimError` by name
    for every refusal (already ruled, out of range, a bad outcome, a
    malformed or missing item), which `run` turns into its own
    by-name response."""
    client = context.forge_writer
    current_body, config = require_writable_target(client, context, number, command="rule")
    new_body = _written_body(current_body, line, outcome)
    client.update_item_body(number, new_body)
    ruled_line = expectations.expectation_lines(new_body, storage=config.storage)[line - 1]
    return ruled_line, _rule_remaining_open(new_body, storage=config.storage)


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


def _rule_expectation_line(parsed: argparse.Namespace, context: RunContext) -> int:
    """`rule`'s own work, every refusal raised by name for `run` to
    report."""
    outcome = _outcome(parsed)
    number = int(parsed.item)
    ruled_line, open_remaining = _rule_item(context, number, parsed.line, outcome)
    storage = context.config.storage
    if isinstance(outcome, expectations.HeadReturn):
        returned_line = cast(expectations.OptionLine, ruled_line)
        _emit_returned_result(number, returned_line, open_remaining, storage, as_json=parsed.json)
    else:
        _emit_rule_result(number, ruled_line, open_remaining, storage, as_json=parsed.json)
    return 0


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`rule`'s own `--json` refusals, for the whole command and
    not only its first steps: the body write inside the shared
    ruling path can fail like any other forge call, and a failure there names
    this command's own `unavailable` rather than escaping the envelope."""
    try:
        return _rule_expectation_line(parsed, context)
    except protocol.ClaimError as error:
        return report.refuse(_refusal_reason(error), error, as_json=parsed.json)
