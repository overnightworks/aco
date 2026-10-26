"""The `rule` command (`specs/rule.spec.md`)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
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
    outcome.add_argument("--yes", action="store_const", dest="ruling", const="yes")
    outcome.add_argument("--no", action="store_const", dest="ruling", const="no")
    outcome.add_argument("--later", action="store_const", dest="ruling", const="later")
    # The option flags stay out of --help and usage so the yes/no refusals stay byte-identical.
    outcome.add_argument("--option", metavar="X", help=argparse.SUPPRESS)
    parser.add_argument("--note", help="appended to the line's own text as ' Anmerkung: TEXT'")
    parser.add_argument(
        "--via",
        choices=[via.value for via in expectation_grammar.RulingVia],
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--card-hash", metavar="HASH", help=argparse.SUPPRESS
    )


class TargetUnavailableError(protocol.ClaimError):
    """`require_writable_target`'s own "forge cannot write" refusal -- a distinct type from
    `InvalidTargetError` so `ask`/`rule` can
    each choose their own `unavailable` without parsing prose."""


class InvalidTargetError(protocol.ClaimError):
    """`require_writable_target`'s own "no such writable item" refusal -- missing, a pull request,
    or a malformed body -- so
    `ask`/`rule` can each choose their own `invalid_item` without parsing
    prose."""


def require_writable_target(
    client: forge.ForgeWriter, context: RunContext, number: int, *, command: str
) -> tuple[str, workboard.BoardConfig]:
    """`ask` and `rule`'s shared target gate (RULE-06..08, cited verbatim by
    `specs/ask.spec.md`): the forge must accept a body write, the item must
    exist and not be a pull request, and its body must parse -- in that
    order, unchanged from before it was factored out of both
    commands. Returns the live body and the board configuration `ask`/
    `rule` still need for their own write."""
    try:
        board_read.require_update_item_body(client, command=command)
    except protocol.ClaimError as error:
        raise TargetUnavailableError(str(error)) from error
    config = board_read.load_board_config(client, context)
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
    `ruled` the only success."""

    RULED = "ruled"
    ALREADY_RULED = "already_ruled"
    LINE_OUT_OF_RANGE = "line_out_of_range"
    INVALID_ITEM = "invalid_item"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"
    CARD_CHANGED = "card_changed"


class FlagCombinationError(protocol.ClaimError):
    """RULE-15: `--option` without `--via` and `--card-hash`, either of them
    without `--option`, or `--note` beside `--option`."""


@dataclass(frozen=True)
class YesNoOutcome:
    """`--yes`, `--no` or `--later`, with its optional note."""

    ruling: str
    note: str | None


Outcome: TypeAlias = YesNoOutcome | expectations.OptionChoice


def _outcome(parsed: argparse.Namespace) -> Outcome:
    """The one outcome the flags name, or RULE-15's refusal of their
    combination -- before any forge call."""
    option_flags = (parsed.via, parsed.card_hash)
    if parsed.option is None:
        if any(flag is not None for flag in option_flags):
            raise FlagCombinationError("--via and --card-hash go only with --option")
        return YesNoOutcome(parsed.ruling, parsed.note)
    if parsed.via is None or parsed.card_hash is None:
        raise FlagCombinationError("--option needs --via and --card-hash")
    if parsed.note is not None:
        raise FlagCombinationError(
            "--note does not go with --option; keep the operator's word in the item's journal"
        )
    via = expectation_grammar.RulingVia(parsed.via)
    return expectations.OptionChoice(parsed.option, via, parsed.card_hash)


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


def _ruled_body(current_body: str, line: int, outcome: Outcome) -> str:
    ruled_on = datetime.now(UTC).date()
    if isinstance(outcome, YesNoOutcome):
        return expectations.rule_expectation(
            current_body, line, outcome.ruling, ruled_on, note=outcome.note
        )
    return expectations.rule_option(current_body, line, outcome, ruled_on)


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
    new_body = _ruled_body(current_body, line, outcome)
    client.update_item_body(number, new_body)
    ruled_line = expectations.expectation_lines(new_body, storage=config.storage)[line - 1]
    return ruled_line, _rule_remaining_open(new_body, storage=config.storage)


# Each refusal's `--json` `reason`, by its type; any other refusal is a
# forge that failed, `unavailable`.
_REFUSAL_REASONS: tuple[tuple[type[protocol.ClaimError], _RuleReason], ...] = (
    (TargetUnavailableError, _RuleReason.UNAVAILABLE),
    (InvalidTargetError, _RuleReason.INVALID_ITEM),
    (expectations.ExpectationAlreadyRuledError, _RuleReason.ALREADY_RULED),
    (expectations.ExpectationOutOfRangeError, _RuleReason.LINE_OUT_OF_RANGE),
    (expectations.ExpectationCardChangedError, _RuleReason.CARD_CHANGED),
    (expectations.ExpectationLineFormError, _RuleReason.INVALID_USAGE),
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
