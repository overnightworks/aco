"""The `withdraw` command (`specs/withdraw.spec.md`): a head takes back its own
expectation line before anyone has ruled it, or its own step."""
# ruff: noqa: T201 - the withdraw command writes its result line to stdout

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from functools import partial
from pathlib import Path

from . import body, decide, expectations, protocol, report, usage, workboard
from .session import RepoMeaninglessUnderStateRefError, RunContext


def add_parser(commands: usage.Subcommands, name: str) -> None:
    """No `--via` and no `--card-hash`: withdrawing decides nothing for the operator."""
    parser = commands.add_parser(
        name, help="withdraw an expectation line or the step of your own that nobody has answered"
    )
    parser.add_argument(
        "item",
        type=workboard.parse_item_reference,
        help="the item whose expectation line or step is withdrawn",
    )
    form = parser.add_mutually_exclusive_group(required=True)
    form.add_argument(
        "--line",
        dest="lines",
        action="append",
        type=int,
        metavar="N",
        help="the 1-based expectation line index, as rulings prints it; "
        "repeat it to withdraw several lines of the item in one write",
    )
    form.add_argument(
        "--step",
        action="store_true",
        help="take back the item's step: its wait, its step table and the label needs-operator",
    )
    report.add_json_flag(parser)


class _WithdrawReason(StrEnum):
    """`aco withdraw`'s own `--json` `reason` vocabulary (`specs/withdraw.spec.md`):
    `withdrawn` is the success."""

    WITHDRAWN = "withdrawn"
    ALREADY_WITHDRAWN = "already_withdrawn"
    ALREADY_RULED = "already_ruled"
    LINE_OUT_OF_RANGE = "line_out_of_range"
    INVALID_ITEM = "invalid_item"
    INVALID_USAGE = "invalid_usage"
    NO_STEP = "no_step"
    UNAVAILABLE = "unavailable"


class LineNamedTwiceError(protocol.ClaimError):
    """WITHDRAW-09: a `--line` naming a line an earlier `--line` named."""


# Each refusal's `--json` `reason`, by its type; any other refusal is a
# forge that failed, `unavailable`; the forge's check of a write that landed is
# `report.refusing_by_type`'s own answer.
_REFUSAL_REASONS: report.RefusalReasons[_WithdrawReason] = (
    (decide.InvalidTargetError, _WithdrawReason.INVALID_ITEM),
    (expectations.ExpectationOutOfRangeError, _WithdrawReason.LINE_OUT_OF_RANGE),
    (expectations.ExpectationWithdrawnError, _WithdrawReason.ALREADY_WITHDRAWN),
    (expectations.ExpectationAlreadyRuledError, _WithdrawReason.ALREADY_RULED),
    (decide.NoStepError, _WithdrawReason.NO_STEP),
    (LineNamedTwiceError, _WithdrawReason.INVALID_USAGE),
    (RepoMeaninglessUnderStateRefError, _WithdrawReason.INVALID_USAGE),
)


def _named_once(indexes: Sequence[int]) -> tuple[int, ...]:
    """The named lines in written order, refusing one named twice before any forge call."""
    named: set[int] = set()
    for index in indexes:
        if index in named:
            raise LineNamedTwiceError(f"line {index} is named twice")
        named.add(index)
    return tuple(indexes)


def _emit_withdrawn(
    committed: decide.Committed,
    indexes: Sequence[int],
    withdrawn_on: date,
    storage: body.Storage,
    *,
    as_json: bool,
) -> None:
    if as_json:
        which = (
            {"index": indexes[0]}
            if len(indexes) == 1
            else {"lines": [{"index": index} for index in indexes]}
        )
        report.emit_json(
            True,
            _WithdrawReason.WITHDRAWN,
            item=committed.number,
            **which,
            withdrawn_on=withdrawn_on.isoformat(),
            open=committed.open_remaining,
        )
        return
    noun = "line" if len(indexes) == 1 else "lines"
    print(
        f"WITHDRAWN {workboard.item_label(committed.number, storage)} {noun} "
        f"{', '.join(map(str, indexes))}; {committed.open_remaining} line(s) still open"
    )


def _withdraw_lines(parsed: argparse.Namespace, context: RunContext) -> int:
    """`withdraw`'s own work, every refusal raised by name for `run` to report."""
    indexes = _named_once(parsed.lines)
    today = context.today()
    with decide.turn(
        context, int(parsed.item), command="withdraw", environment=os.environ, home=Path.home()
    ) as fresh:
        committed = decide.withdraw(
            context,
            fresh,
            indexes,
            today,
            state=fresh.state_directory,
        )
    _emit_withdrawn(committed, indexes, today, fresh.storage, as_json=parsed.json)
    return 0


def _emit_step_withdrawn(
    withdrawn: decide.StepWithdrawn, number: int, storage: body.Storage, *, as_json: bool
) -> None:
    if withdrawn.label_note is not None:
        print(f"WARNING: {withdrawn.label_note}", file=sys.stderr)
    if as_json:
        note = {} if withdrawn.label_note is None else {"note": withdrawn.label_note}
        report.emit_json(True, _WithdrawReason.WITHDRAWN, item=number, step=withdrawn.step, **note)
        return
    print(f"WITHDRAWN {workboard.item_label(number, storage)} step")


def _withdraw_step(parsed: argparse.Namespace, context: RunContext) -> int:
    """The step form's own work; every refusal is raised by name for `run` to report."""
    with decide.turn(
        context, int(parsed.item), command="withdraw", environment=os.environ, home=Path.home()
    ) as fresh:
        withdrawn = decide.withdraw_step(context, fresh)
    _emit_step_withdrawn(withdrawn, fresh.number, fresh.storage, as_json=parsed.json)
    return 0


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`withdraw` with its own `--json` refusals for the whole command, the
    body write inside the shared path included; the forge's check of a write
    that landed is `overwritten` or `not_verified`."""
    return report.refusing_by_type(
        partial(_withdraw_step if parsed.step else _withdraw_lines, parsed, context),
        _REFUSAL_REASONS,
        _WithdrawReason.UNAVAILABLE,
        as_json=parsed.json,
    )
