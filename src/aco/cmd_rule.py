"""The `rule` command (`specs/rule.spec.md`)."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import cast

from . import board_read, body, expectations, forge, protocol, report, workboard
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
    parser.add_argument("--note", help="appended to the line's own text as ' Anmerkung: TEXT'")


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


def _rule_item(
    context: RunContext, number: int, line: int, ruling: str, note: str | None
) -> tuple[expectations.ExpectationLine, int]:
    """`run`'s own write: returns the newly ruled line and
    how many the item still has open; raises `protocol.ClaimError` by name
    for every refusal (already ruled, out of range, a bad outcome, a
    malformed or missing item), which `run` turns into its own
    by-name response."""
    client = context.forge_writer
    current_body, config = require_writable_target(client, context, number, command="rule")
    ruled_on = datetime.now(UTC).date()
    new_body = expectations.rule_expectation(current_body, line, ruling, ruled_on, note=note)
    client.update_item_body(number, new_body)
    ruled_line = expectations.expectation_lines(new_body, storage=config.storage)[line - 1]
    return ruled_line, _rule_remaining_open(new_body, storage=config.storage)


_RuleItemError = (
    TargetUnavailableError
    | InvalidTargetError
    | expectations.ExpectationAlreadyRuledError
    | expectations.ExpectationOutOfRangeError
)


def _rule_item_reason(error: _RuleItemError) -> _RuleReason:
    """`run`'s own mapping from `_rule_item`'s four refusals to their
    `--json` `reason`: a bad target names `unavailable`
    (forge cannot write) or `invalid_item` (missing item, pull request);
    a bad line names `already_ruled` or `line_out_of_range`."""
    if isinstance(error, TargetUnavailableError):
        return _RuleReason.UNAVAILABLE
    if isinstance(error, InvalidTargetError):
        return _RuleReason.INVALID_ITEM
    if isinstance(error, expectations.ExpectationAlreadyRuledError):
        return _RuleReason.ALREADY_RULED
    return _RuleReason.LINE_OUT_OF_RANGE


def _rule_expectation_line(parsed: argparse.Namespace, context: RunContext) -> int:
    """`rule`'s own work, every refusal raised by name for `run` to
    report."""
    number = int(parsed.item)
    ruled_line, open_remaining = _rule_item(
        context, number, parsed.line, parsed.ruling, parsed.note
    )
    storage = context.config.storage
    _emit_rule_result(number, ruled_line, open_remaining, storage, as_json=parsed.json)
    return 0


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`rule`'s own `--json` refusals, for the whole command and
    not only its first steps: the body write inside the shared
    ruling path can fail like any other forge call, and a failure there names
    this command's own `unavailable` rather than escaping the envelope."""
    as_json = parsed.json
    try:
        return _rule_expectation_line(parsed, context)
    except (
        TargetUnavailableError,
        InvalidTargetError,
        expectations.ExpectationAlreadyRuledError,
        expectations.ExpectationOutOfRangeError,
    ) as error:
        return report.refuse(_rule_item_reason(error), error, as_json=as_json)
    except RepoMeaninglessUnderStateRefError as error:
        return report.refuse(_RuleReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_RuleReason.UNAVAILABLE, error, as_json=as_json)
