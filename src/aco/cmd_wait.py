"""The `wait` command (`specs/wait.spec.md`): a session that asked the operator a
card learns the answer when it is recorded, and an idle head learns that its board
has something to do, by running this command in the background and waking when it
ends."""
# ruff: noqa: T201 - the wait command writes its result lines to stdout

import argparse
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path

from . import (
    board_wait,
    body,
    decide,
    expectations,
    forge,
    protocol,
    report,
    repositories,
    usage,
    workboard,
)
from .session import RepoMeaninglessUnderStateRefError, RunContext

# How often the item's signal file is looked at, and how often the item is read
# although the signal did not move: an answer written outside aco never touches it.
SIGNAL_POLL_SECONDS = 2.0
ITEM_READ_SECONDS = 600.0

# The pause and the clock `run` hands to the wait; a test replaces them.
pause_between_checks = time.sleep
clock = time.monotonic


def add_parser(commands: usage.Subcommands, name: str) -> None:
    """`wait`'s parser: the item with its repeatable `--line N`, or neither of them
    to wait on the repository's board."""
    parser = commands.add_parser(
        name,
        help="wait until an expectation line is ruled, returned or withdrawn, "
        "or, with no item, until the board has something to do",
    )
    report.add_lines_arguments(
        parser,
        item_help="the item whose lines are waited on; leave it out to wait on the board",
        lines_help="the 1-based expectation line index, as rulings prints it; "
        "repeat it to wait on several lines of the item",
        optional=True,
    )


class _WaitReason(StrEnum):
    """`aco wait`'s own `--json` `reason` vocabulary (`specs/wait.spec.md`):
    `changed` and `actionable` are the successes."""

    CHANGED = "changed"
    ACTIONABLE = "actionable"
    INVALID_ITEM = "invalid_item"
    LINE_OUT_OF_RANGE = "line_out_of_range"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


class ItemClosedError(protocol.ClaimError):
    """WAIT-04: a closed item has nothing left to wait for."""


class HalfATargetError(protocol.ClaimError):
    """WAIT-21: `--line` without an item, or an item without `--line`."""


# Each refusal's `--json` `reason`, by its type; any other refusal is a forge
# that failed, `unavailable`.
_REFUSAL_REASONS: report.RefusalReasons[_WaitReason] = (
    (decide.InvalidTargetError, _WaitReason.INVALID_ITEM),
    (ItemClosedError, _WaitReason.INVALID_ITEM),
    (expectations.ExpectationOutOfRangeError, _WaitReason.LINE_OUT_OF_RANGE),
    (RepoMeaninglessUnderStateRefError, _WaitReason.INVALID_USAGE),
    (HalfATargetError, _WaitReason.INVALID_USAGE),
)


@dataclass(frozen=True)
class ChangedLine:
    """A named line that is no longer open, and the state `aco rulings` prints for it."""

    index: int
    state: str


def _changed_lines(fresh: decide.FreshItem, named: Sequence[int]) -> tuple[ChangedLine, ...]:
    """The named lines of the fresh item that no longer wait on the operator, in
    the item's order."""
    lines = expectations.expectation_lines(fresh.body, storage=fresh.storage)
    for index in named:
        if not 1 <= index <= len(lines):
            raise expectations.ExpectationOutOfRangeError(
                f"line {index} out of range: this item has {len(lines)} expectation line(s)"
            )
    return tuple(
        ChangedLine(index, expectations.expectation_line_state(lines[index - 1]))
        for index in sorted(named)
        if not board_wait.waits_on_the_operator(lines[index - 1])
    )


def _refuse_a_closed_item(fresh: decide.FreshItem) -> None:
    if fresh.state is not forge.ItemState.OPEN:
        label = workboard.item_label(fresh.number, fresh.storage)
        raise ItemClosedError(f"{label} is closed; there is nothing to wait for")


def _emit_changed(
    changed: Sequence[ChangedLine], number: int, storage: body.Storage, *, as_json: bool
) -> None:
    if as_json:
        lines = [{"index": line.index, "state": line.state} for line in changed]
        report.emit_json(True, _WaitReason.CHANGED, item=number, lines=lines)
        return
    label = workboard.item_label(number, storage)
    for line in changed:
        print(f"CHANGED {label} line {line.index}: {line.state}")


def _reread_or_failure(
    context: RunContext, number: int
) -> decide.FreshItem | forge.ForgeTransientError:
    """A later read of the item, fresh from the store; a transient forge failure
    is returned, every other refusal raised."""
    try:
        return decide.fresh_item(context.observed_afresh(), number, command="wait")
    except forge.ForgeTransientError as error:
        return error


def _say_still_waiting(failure: forge.ForgeTransientError) -> None:
    sys.stderr.write(f"WARNING: the item could not be read, still waiting: {failure}\n")
    sys.stderr.flush()


def _first_read(
    context: RunContext, number: int, pause: Callable[[float], None]
) -> decide.FreshItem:
    """The item's first read. Any failure but a rate limit refuses; a rate limit is said once,
    and the read is tried again at the retry time (WAIT-22)."""
    failures = board_wait.FailureRun(_say_still_waiting)
    reading = context
    while True:
        try:
            return decide.fresh_item(reading, number, command="wait")
        except forge.ForgeRateLimitedError as limited:
            failures.add(limited)
            pause(board_wait.retry_seconds(limited, context.now()))
            reading = context.observed_afresh()


def _read_due(*, moved: bool, now: float, last_read: float, retry_at: float | None) -> bool:
    """Whether the item is read now: at the retry time a rate limit set, and then not before
    even if the signal moved; otherwise when the signal moved or `ITEM_READ_SECONDS` passed."""
    if retry_at is not None:
        return now >= retry_at
    return moved or now - last_read >= ITEM_READ_SECONDS


def _retry_at(failure: forge.ForgeTransientError, context: RunContext, now: float) -> float | None:
    """When a failed read is tried again: at the reset a rate limit named, else on the
    ordinary schedule (`None`)."""
    if not isinstance(failure, forge.ForgeRateLimitedError):
        return None
    return now + board_wait.retry_seconds(failure, context.now())


def _wait_for_lines(
    parsed: argparse.Namespace,
    context: RunContext,
    pause: Callable[[float], None],
    now: Callable[[], float],
) -> int:
    """`wait`'s own work, every refusal raised by name for `run` to report. The
    item is read once, then again only when its signal moved or `ITEM_READ_SECONDS`
    passed; the signal's time is taken before each read, so a ruling between the
    two moves it again. A reread observes the state ref anew: under `state-ref`
    a context reads it once."""
    number = int(parsed.item)
    named = tuple(dict.fromkeys(parsed.lines))
    # The target's own refusals (`--repo` under `state-ref`) come before anything is watched.
    _ = context.repository_id
    state = repositories.state_directory(os.environ, Path.home())
    signal = decide.item_signal_path(context, number, state)
    watched = board_wait.signal_modified(signal)
    fresh = _first_read(context, number, pause)
    _refuse_a_closed_item(fresh)
    changed = _changed_lines(fresh, named)
    last_read = now()
    failures = board_wait.FailureRun(_say_still_waiting)
    retry_at: float | None = None
    while not changed:
        pause(SIGNAL_POLL_SECONDS)
        moved = board_wait.signal_modified(signal)
        if not _read_due(moved=moved != watched, now=now(), last_read=last_read, retry_at=retry_at):
            continue
        watched, last_read = moved, now()
        reread = _reread_or_failure(context, number)
        if isinstance(reread, forge.ForgeTransientError):
            failures.add(reread)
            retry_at = _retry_at(reread, context, now())
            continue
        failures.end()
        retry_at = None
        _refuse_a_closed_item(reread)
        changed = _changed_lines(reread, named)
    _emit_changed(changed, number, fresh.storage, as_json=parsed.json)
    return 0


def _emit_board_end(end: board_wait.BoardEnd, storage: body.Storage, *, as_json: bool) -> None:
    changed = [
        {
            "item": workboard.item_json_reference(line.item, storage),
            "index": line.index,
            "state": line.state,
        }
        for line in end.changed
    ]
    if as_json:
        if end.actionable_item is None:
            report.emit_json(True, _WaitReason.CHANGED, lines=changed)
        else:
            item = workboard.item_json_reference(end.actionable_item, storage)
            lines = {"lines": changed} if changed else {}
            report.emit_json(True, _WaitReason.ACTIONABLE, item=item, **lines)
        return
    if end.actionable_item is not None:
        print(f"ACTIONABLE {workboard.item_label(end.actionable_item, storage)}")
    for line in end.changed:
        print(f"CHANGED {workboard.item_label(line.item, storage)} line {line.index}: {line.state}")


def _wait_on_the_board(
    parsed: argparse.Namespace,
    context: RunContext,
    pause: Callable[[float], None],
    now: Callable[[], float],
) -> int:
    """WAIT-14: the repository's board, until `aco next` names an action or a line
    that waited on the operator stops."""
    end = board_wait.wait_for_board(context, board_wait.WaitClock(pause, now, SIGNAL_POLL_SECONDS))
    _emit_board_end(end, context.config.storage, as_json=parsed.json)
    return 0


def _wait(
    parsed: argparse.Namespace,
    context: RunContext,
    pause: Callable[[float], None],
    now: Callable[[], float],
) -> int:
    """The board without an item, the item's lines with one; either without the other refuses."""
    if (parsed.item is None) != (parsed.lines is None):
        raise HalfATargetError("wait needs an item together with --line, or neither of them")
    if parsed.item is None:
        return _wait_on_the_board(parsed, context, pause, now)
    return _wait_for_lines(parsed, context, pause, now)


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`wait` with its own `--json` refusals for the whole command."""
    return report.refusing_by_type(
        partial(_wait, parsed, context, pause_between_checks, clock),
        _REFUSAL_REASONS,
        _WaitReason.UNAVAILABLE,
        as_json=parsed.json,
    )
