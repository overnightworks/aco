"""The `wait` command (`specs/wait.spec.md`): a session that asked the operator a
card learns the answer when it is recorded, by running this command in the
background and waking when it ends."""
# ruff: noqa: T201 - the wait command writes its result lines to stdout

import argparse
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path

from . import body, decide, expectations, forge, protocol, report, repositories, workboard
from .session import RepoMeaninglessUnderStateRefError, RunContext

# How often the item's signal file is looked at, and how often the item is read
# although the signal did not move: an answer written outside aco never touches it.
SIGNAL_POLL_SECONDS = 2.0
ITEM_READ_SECONDS = 600.0

# The pause and the clock `run` hands to the wait; a test replaces them.
pause_between_checks = time.sleep
clock = time.monotonic


add_parser = partial(
    decide.add_lines_command_parser,
    help="wait until an expectation line is ruled, returned or withdrawn",
    item_help="the item whose lines are waited on",
    lines_help="the 1-based expectation line index, as rulings prints it; "
    "repeat it to wait on several lines of the item",
)


class _WaitReason(StrEnum):
    """`aco wait`'s own `--json` `reason` vocabulary (`specs/wait.spec.md`):
    `changed` is the success."""

    CHANGED = "changed"
    INVALID_ITEM = "invalid_item"
    LINE_OUT_OF_RANGE = "line_out_of_range"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


class ItemClosedError(protocol.ClaimError):
    """WAIT-04: a closed item has nothing left to wait for."""


# Each refusal's `--json` `reason`, by its type; any other refusal is a forge
# that failed, `unavailable`.
_REFUSAL_REASONS: report.RefusalReasons[_WaitReason] = (
    (decide.InvalidTargetError, _WaitReason.INVALID_ITEM),
    (ItemClosedError, _WaitReason.INVALID_ITEM),
    (expectations.ExpectationOutOfRangeError, _WaitReason.LINE_OUT_OF_RANGE),
    (RepoMeaninglessUnderStateRefError, _WaitReason.INVALID_USAGE),
)


@dataclass(frozen=True)
class ChangedLine:
    """A named line that is no longer open, and the state `aco rulings` prints for it."""

    index: int
    state: str


def _waits_on_the_operator(line: expectations.ExpectationLine) -> bool:
    """An option line neither ruled nor returned to its head."""
    return expectations.is_open(line) and line.returned is None


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
        if not _waits_on_the_operator(lines[index - 1])
    )


def _refuse_a_closed_item(fresh: decide.FreshItem) -> None:
    if fresh.state is not forge.ItemState.OPEN:
        label = workboard.item_label(fresh.number, fresh.storage)
        raise ItemClosedError(f"{label} is closed; there is nothing to wait for")


def _modified(signal: Path) -> int | None:
    """The signal's modification time, `None` while no ruling has touched it."""
    try:
        return signal.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    except OSError as error:
        raise protocol.ClaimUnavailableError(
            f"cannot watch the item's signal at {signal}: {error.strerror or str(error)}"
        ) from error


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
    watched = _modified(signal)
    fresh = decide.fresh_item(context, number, command="wait")
    _refuse_a_closed_item(fresh)
    changed = _changed_lines(fresh, named)
    last_read = now()
    while not changed:
        pause(SIGNAL_POLL_SECONDS)
        moved = _modified(signal)
        if moved == watched and now() - last_read < ITEM_READ_SECONDS:
            continue
        watched, last_read = moved, now()
        reread = decide.fresh_item(context.observed_afresh(), number, command="wait")
        changed = _changed_lines(reread, named)
    _emit_changed(changed, number, fresh.storage, as_json=parsed.json)
    return 0


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`wait` with its own `--json` refusals for the whole command, every forge
    failure of a later read included."""
    return report.refusing_by_type(
        partial(_wait_for_lines, parsed, context, pause_between_checks, clock),
        _REFUSAL_REASONS,
        _WaitReason.UNAVAILABLE,
        as_json=parsed.json,
    )
