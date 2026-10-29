"""The `withdraw` command (`specs/withdraw.spec.md`): a head takes back its own
expectation line before anyone has ruled it."""
# ruff: noqa: T201 - the withdraw command writes its result line to stdout

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
from enum import StrEnum

from . import body, decide, expectations, protocol, report, usage, workboard
from .session import RepoMeaninglessUnderStateRefError, RunContext


def add_parser(commands: usage.Subcommands, name: str) -> None:
    """`withdraw`'s parser: no `--via` and no `--card-hash`, since it decides
    nothing for the operator."""
    withdraw = commands.add_parser(
        name, help="withdraw an expectation line of your own that nobody has ruled"
    )
    withdraw.add_argument(
        "item",
        type=workboard.parse_item_reference,
        help="the item whose expectation line is withdrawn",
    )
    withdraw.add_argument(
        "--line",
        dest="lines",
        action="append",
        type=int,
        required=True,
        metavar="N",
        help="the 1-based expectation line index, as rulings prints it; "
        "repeat it to withdraw several lines of the item in one write",
    )
    report.add_json_flag(withdraw)


class _WithdrawReason(StrEnum):
    """`aco withdraw`'s own `--json` `reason` vocabulary (`specs/withdraw.spec.md`):
    `withdrawn` is the success."""

    WITHDRAWN = "withdrawn"
    ALREADY_WITHDRAWN = "already_withdrawn"
    ALREADY_RULED = "already_ruled"
    LINE_OUT_OF_RANGE = "line_out_of_range"
    INVALID_ITEM = "invalid_item"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


class LineNamedTwiceError(protocol.ClaimError):
    """WITHDRAW-09: a `--line` naming a line an earlier `--line` named."""


# Each refusal's `--json` `reason`, by its type; any other refusal is a
# forge that failed, `unavailable`.
_REFUSAL_REASONS: tuple[tuple[type[protocol.ClaimError], _WithdrawReason], ...] = (
    (decide.InvalidTargetError, _WithdrawReason.INVALID_ITEM),
    (expectations.ExpectationOutOfRangeError, _WithdrawReason.LINE_OUT_OF_RANGE),
    (expectations.ExpectationWithdrawnError, _WithdrawReason.ALREADY_WITHDRAWN),
    (expectations.ExpectationAlreadyRuledError, _WithdrawReason.ALREADY_RULED),
    (LineNamedTwiceError, _WithdrawReason.INVALID_USAGE),
    (RepoMeaninglessUnderStateRefError, _WithdrawReason.INVALID_USAGE),
)


def _refusal_reason(error: protocol.ClaimError) -> _WithdrawReason:
    return next(
        (reason for kind, reason in _REFUSAL_REASONS if isinstance(error, kind)),
        _WithdrawReason.UNAVAILABLE,
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
    fresh = decide.fresh_item(context, int(parsed.item), command="withdraw")
    today = context.today()
    committed = decide.withdraw(context, fresh, indexes, today)
    _emit_withdrawn(committed, indexes, today, fresh.storage, as_json=parsed.json)
    return 0


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`withdraw` with its own `--json` refusals for the whole command, the
    body write inside the shared path included."""
    try:
        return _withdraw_lines(parsed, context)
    except protocol.ClaimError as error:
        return report.refuse(_refusal_reason(error), error, as_json=parsed.json)
