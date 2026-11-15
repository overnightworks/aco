"""The wait on a repository's board (`specs/wait.spec.md`, WAIT-14 to WAIT-21): it ends
when `aco next` names an action or a line that waited on the operator no longer does.

A cheap check only decides when to read: the signal files of items with a waiting line
(`decide.item_signal_path`), the forge's conditional probes, a `ls-remote` of the state ref,
the hour and the earliest `until` date. What the read means is `board_read.observed_board`
and `workboard.next_action`'s alone."""

import os
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from . import (
    board_read,
    body,
    decide,
    expectations,
    forge,
    item_wait,
    protocol,
    repositories,
    store,
    workboard,
)
from .session import RunContext

PROBE_SECONDS = 60.0
FULL_READ_SECONDS = 3600.0


@dataclass(frozen=True)
class LineStatus:
    """One expectation line of an open item as the last read found it."""

    item: int
    index: int
    state: str
    waiting: bool


@dataclass(frozen=True)
class BoardReading:
    """What one read of the board tells: the item `aco next` names, every line of
    the open items, the foreign blockers still open, and the earliest `until`
    date still ahead."""

    actionable_item: int | None
    lines: tuple[LineStatus, ...]
    foreign_blockers: tuple[forge.ProbeTarget, ...]
    earliest_until: date | None


@dataclass(frozen=True)
class BoardEnd:
    """Why the wait ended: the item `aco next` names, and the lines that
    stopped waiting on the operator, in board order. At least one holds."""

    actionable_item: int | None
    changed: tuple[LineStatus, ...]


@dataclass(frozen=True)
class WaitClock:
    """The pause and the clock the wait takes, and how often a tick comes."""

    pause: Callable[[float], None]
    now: Callable[[], float]
    poll_seconds: float


@dataclass(frozen=True)
class Schedule:
    """When the last probe ran and the last read answered, and before when no read
    is tried again after one failed."""

    last_probe: float
    last_read: float
    retry_after: float = 0.0


def waits_on_the_operator(line: expectations.ExpectationLine) -> bool:
    """An option line neither ruled nor returned to its head."""
    return expectations.is_open(line) and line.returned is None


def signal_modified(signal: Path) -> int | None:
    """The signal's modification time, `None` while no ruling has touched it."""
    try:
        return signal.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    except OSError as error:
        raise protocol.ClaimUnavailableError(
            f"cannot watch the item's signal at {signal}: {error.strerror or str(error)}"
        ) from error


def ending(waiting_before: frozenset[tuple[int, int]], reading: BoardReading) -> BoardEnd | None:
    """The end `reading` brings: the action `aco next` names, and the lines of
    `waiting_before` (item and index) that no longer wait on the operator."""
    changed = tuple(
        line
        for line in reading.lines
        if (line.item, line.index) in waiting_before and not line.waiting
    )
    if reading.actionable_item is None and not changed:
        return None
    return BoardEnd(reading.actionable_item, changed)


def waiting_lines(reading: BoardReading) -> frozenset[tuple[int, int]]:
    """The item and index of each line of `reading` that waits on the operator."""
    return frozenset((line.item, line.index) for line in reading.lines if line.waiting)


def earliest_pending_until(waits: Iterable[item_wait.ItemWait | None], today: date) -> date | None:
    """The earliest `until` date among `waits` that lies after `today`: one that is
    reached already frees its item in the read that found it."""
    pending = [
        wait.until for wait in waits if isinstance(wait, item_wait.UntilWait) and wait.until > today
    ]
    return min(pending, default=None)


def probe_due(now: float, schedule: Schedule) -> bool:
    return now - schedule.last_probe >= PROBE_SECONDS


def read_due(
    now: float,
    schedule: Schedule,
    *,
    pending: bool,
    today: date,
    earliest_until: date | None,
) -> bool:
    """Whether the board is read now: a signal or probe asked for it, an hour passed since
    the last read, or `today` reached the earliest `until` date. Never before `retry_after`."""
    if now < schedule.retry_after:
        return False
    until_reached = earliest_until is not None and today >= earliest_until
    return pending or until_reached or now - schedule.last_read >= FULL_READ_SECONDS


def probe_targets(
    repository: str, foreign_blockers: tuple[forge.ProbeTarget, ...]
) -> tuple[forge.ProbeTarget, ...]:
    """The repository's newest updated issue, then each foreign blocker."""
    return (forge.ProbeTarget(repository), *foreign_blockers)


def _line_statuses(
    issues: Iterable[workboard.Issue], storage: body.Storage
) -> tuple[LineStatus, ...]:
    return tuple(
        LineStatus(
            issue.number,
            line.index,
            expectations.expectation_line_state(line),
            waits_on_the_operator(line),
        )
        for issue in issues
        for line in expectations.expectation_lines(issue.body, storage=storage)
    )


def _foreign_blockers(board: workboard.Board, repository: str) -> tuple[forge.ProbeTarget, ...]:
    references = {
        reference
        for item in board.items
        for reference in item.open_blockers
        if reference.repository != repository
    }
    return tuple(
        forge.ProbeTarget(reference.repository, reference.number)
        for reference in sorted(
            references, key=lambda reference: (reference.repository, reference.number)
        )
    )


def read_board(context: RunContext) -> BoardReading:
    """One read of the open board and of `aco next`'s decision over it."""
    issues = context.forge.list_open_board_issues()
    projected = board_read.observed_board(context, issues=issues).board
    storage = context.config.storage
    action = workboard.next_action(projected)
    github = storage is body.Storage.GITHUB
    return BoardReading(
        actionable_item=None if action is None else workboard.next_action_item(action).number,
        lines=_line_statuses(issues, storage),
        foreign_blockers=_foreign_blockers(projected, context.repository_id.path) if github else (),
        earliest_until=earliest_pending_until(
            (body.parse_body(issue.body, storage=storage).wait for issue in issues), context.today()
        ),
    )


def _say_still_waiting(failure: forge.ForgeTransientError) -> None:
    sys.stderr.write(f"WARNING: the board could not be read, still waiting: {failure}\n")
    sys.stderr.flush()


class _BoardWatch:
    """The run of one wait: what the last read found, the tokens of the probes and the
    state ref's tip, and the signals' times, each as they stood when it was read."""

    def __init__(self, context: RunContext, clock: WaitClock) -> None:
        self._context = context
        self._clock = clock
        self._state = repositories.state_directory(os.environ, Path.home())
        self._github = context.config.storage is body.Storage.GITHUB
        self._tokens: dict[forge.ProbeTarget, str] = {}
        self._tip: protocol.ObjectId | None = None
        self._blockers: tuple[forge.ProbeTarget, ...] = ()
        self._waiting: frozenset[tuple[int, int]] = frozenset()
        self._signals: dict[int, int | None] = {}
        self._until: date | None = None
        self._schedule = Schedule(clock.now(), clock.now())
        self._pending = False
        self._failing = False
        self._read_before = False

    def start(self) -> BoardEnd | None:
        """The first read: a failure here refuses, and the state ref's tip and the
        probes' tokens are taken before it, so what changes during the read is seen."""
        # The target's own refusals (`--repo` under `state-ref`) come before anything is watched.
        _ = self._context.repository_id
        self._tip = self._tip_of_the_state_ref()
        self._probe_the_forge()
        return self._read(self._clock.now())

    def tick(self) -> BoardEnd | None:
        """What one pause brings; a transient failure is said once per run of failures."""
        now = self._clock.now()
        try:
            return self._tick(now)
        except forge.ForgeTransientError as failure:
            self._fail(failure, now)
            return None

    def _tick(self, now: float) -> BoardEnd | None:
        self._pending = self._pending or self._a_signal_moved()
        if probe_due(now, self._schedule):
            self._schedule = replace(self._schedule, last_probe=now)
            self._probe_the_forge()
            self._probe_the_state_ref()
            self._failing = False
        due = read_due(
            now,
            self._schedule,
            pending=self._pending,
            today=self._context.today(),
            earliest_until=self._until,
        )
        return self._read(now) if due else None

    def _fail(self, failure: forge.ForgeTransientError, now: float) -> None:
        if not self._failing:
            _say_still_waiting(failure)
        self._failing = True
        self._schedule = replace(self._schedule, retry_after=now + PROBE_SECONDS)

    def _modified(self, item: int) -> int | None:
        return signal_modified(decide.item_signal_path(self._context, item, self._state))

    def _a_signal_moved(self) -> bool:
        return any(self._modified(item) != seen for item, seen in self._signals.items())

    def _tip_of_the_state_ref(self) -> protocol.ObjectId | None:
        try:
            return store.ls_remote_state(
                self._context.toplevel, self._context.configured_canonical_remote
            )
        except protocol.ClaimError as error:
            raise forge.ForgeTransientError(str(error)) from error

    def _probe_the_state_ref(self) -> None:
        tip = self._tip_of_the_state_ref()
        self._pending = self._pending or tip != self._tip
        self._tip = tip

    def _probe_the_forge(self) -> None:
        """Under `github` storage one conditional question per target; a target seen the
        first time only takes its token."""
        if not self._github:
            return
        targets = probe_targets(self._context.repository_id.path, self._blockers)
        self._tokens = {
            target: token for target, token in self._tokens.items() if target in targets
        }
        for target in targets:
            known = self._tokens.get(target)
            answer = self._context.board_probe.changed_since(target, known)
            self._tokens[target] = answer.token
            self._pending = self._pending or (answer.changed and known is not None)

    def _read(self, now: float) -> BoardEnd | None:
        """A fresh read; the signals' times are taken before it, so a ruling during
        it moves them again. It ends the wait or becomes what the next ticks compare to."""
        before = {item: self._modified(item) for item in self._signals}
        context = self._context.observed_afresh() if self._read_before else self._context
        reading = read_board(context)
        self._read_before = True
        end = ending(self._waiting, reading)
        if end is not None:
            return end
        self._waiting = waiting_lines(reading)
        self._blockers = reading.foreign_blockers
        self._until = reading.earliest_until
        watched = sorted({item for item, _index in self._waiting})
        self._signals = {
            item: before[item] if item in before else self._modified(item) for item in watched
        }
        self._pending = False
        self._failing = False
        self._schedule = Schedule(now, now)
        self._probe_the_forge()
        return None


def wait_for_board(context: RunContext, clock: WaitClock) -> BoardEnd:
    """Wait until `aco next` names an action or a line that waited on the operator
    stops. Refusals and failures that are not transient are raised."""
    watch = _BoardWatch(context, clock)
    end = watch.start()
    while end is None:
        clock.pause(clock.poll_seconds)
        end = watch.tick()
    return end
