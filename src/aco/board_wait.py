"""The wait on a repository's board (`specs/wait.spec.md`, WAIT-14 to WAIT-21): it ends
when `aco next` names an action or a line that waited on the operator no longer does.

A cheap check only decides when to read: the signal files of items with a waiting line
(`decide.item_signal_path`), the forge's conditional probes, a `ls-remote` of the state ref,
the hour and the earliest `until` date; a moved signal rereads that item alone. What the
board read means is `board_read.observed_board` and `workboard.next_action`'s alone."""

import os
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path

from . import (
    board_read,
    body,
    checkout,
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

# No file time is this, so an item first watched reads as moved and its next tick reads it again:
# a ruling between the read of its lines and the first look at its signal is then still seen.
_UNSEEN = -1
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
    the open items, the foreign blockers still open, the earliest `until`
    wait still ahead, and the names of the recurring audits that are due."""

    actionable_item: int | None
    lines: tuple[LineStatus, ...]
    foreign_blockers: tuple[forge.ProbeTarget, ...]
    earliest_until: item_wait.UntilWait | None
    audits_due: tuple[str, ...] = ()
    listings: board_read.OpenListings = field(default_factory=lambda: board_read.OpenListings(()))


@dataclass(frozen=True)
class BoardEnd:
    """Why the wait ended: the item `aco next` names, the lines that
    stopped waiting on the operator, in board order, and the audits that are due,
    in entry order. At least one holds."""

    actionable_item: int | None
    changed: tuple[LineStatus, ...]
    audits_due: tuple[str, ...] = ()


@dataclass
class KeptAudits:
    """The due audits of the last complete listing and the key it was made under: the
    newest trunk landing's commit and the day."""

    key: tuple[str | None, date] | None = None
    due: tuple[str, ...] = ()


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
    if reading.actionable_item is None and not changed and not reading.audits_due:
        return None
    return BoardEnd(reading.actionable_item, changed, reading.audits_due)


def waiting_lines(reading: BoardReading) -> frozenset[tuple[int, int]]:
    """The item and index of each line of `reading` that waits on the operator."""
    return frozenset((line.item, line.index) for line in reading.lines if line.waiting)


def earliest_pending_until(
    waits: Iterable[item_wait.ItemWait | None], today: date
) -> item_wait.UntilWait | None:
    """The `until` wait among `waits` with the earliest date that `today` has not reached:
    one that is over already frees its item in the read that found it."""
    pending = [
        wait
        for wait in waits
        if isinstance(wait, item_wait.UntilWait) and not item_wait.is_over(wait, today)
    ]
    return min(pending, key=lambda wait: wait.until, default=None)


def probe_due(now: float, schedule: Schedule) -> bool:
    return now - schedule.last_probe >= PROBE_SECONDS


def read_due(
    now: float,
    schedule: Schedule,
    *,
    pending: bool,
    today: date,
    earliest_until: item_wait.UntilWait | None,
) -> bool:
    """Whether the board is read now: a signal or probe asked for it, an hour passed since
    the last read, or `today` reached the earliest `until` date. Never before `retry_after`."""
    if now < schedule.retry_after:
        return False
    until_reached = earliest_until is not None and item_wait.is_over(earliest_until, today)
    return pending or until_reached or now - schedule.last_read >= FULL_READ_SECONDS


def listings_differ(before: board_read.OpenListings, after: board_read.OpenListings) -> bool:
    """Whether the open listings differ in anything but the issues' update times, which a
    comment or a CI note moves without changing what a board or a line shows."""

    def comparable(listings: board_read.OpenListings) -> tuple[object, ...]:
        issues = tuple(replace(issue, updated_at="") for issue in listings.issues)
        return (issues, listings.pull_requests)

    return comparable(before) != comparable(after)


def probe_targets(
    repository: str, foreign_blockers: tuple[forge.ProbeTarget, ...]
) -> tuple[forge.ProbeTarget, ...]:
    """The repository's newest updated issue, then each foreign blocker."""
    return (forge.ProbeTarget(repository), *foreign_blockers)


def _item_line_statuses(
    number: int, item_body: str, storage: body.Storage
) -> tuple[LineStatus, ...]:
    return tuple(
        LineStatus(
            number,
            line.index,
            expectations.expectation_line_state(line),
            waits_on_the_operator(line),
        )
        for line in expectations.expectation_lines(item_body, storage=storage)
    )


def _line_statuses(
    issues: Iterable[workboard.Issue], storage: body.Storage
) -> tuple[LineStatus, ...]:
    return tuple(
        status
        for issue in issues
        for status in _item_line_statuses(issue.number, issue.body, storage)
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


def audits_due(
    context: RunContext, landings: tuple[checkout.TrunkLanding, ...], kept: KeptAudits
) -> tuple[str, ...]:
    """The names of the due audits, in entry order: `board_read.recurring_audit_reading`'s
    listing, made only when the key (the newest landing, the day) differs from the one `kept`
    holds. An unavailable audit is not due and keeps nothing, so the next read lists again."""
    if not context.config.audit:
        return ()
    key = (landings[-1].sha if landings else None, context.today())
    if kept.key == key:
        return kept.due
    findings = board_read.recurring_audit_reading(context, landings)
    due = tuple(finding.entry.name for finding in findings if finding.is_due)
    if all(finding.is_due for finding in findings):
        kept.key, kept.due = key, due
    return due


def read_board(
    context: RunContext, kept: KeptAudits, listings: board_read.OpenListings | None = None
) -> BoardReading:
    """One read of the open board and of `aco next`'s decision over it, over `listings` or,
    when given none, over the ones it fetches; `kept` holds the audit verdicts between reads."""
    listings = listings or board_read.fetch_open_listings(context.forge)
    issues = listings.issues
    observed = board_read.observed_board(context, listings=listings)
    projected = observed.board
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
        audits_due=audits_due(context, observed.trunk_landings, kept),
        listings=listings,
    )


def retry_seconds(failure: forge.ForgeTransientError, wall_now: datetime) -> float:
    """How long after `failure` GitHub is asked again: until the reset a rate limit named
    when that is more than `PROBE_SECONDS` away, else `PROBE_SECONDS`."""
    if isinstance(failure, forge.ForgeRateLimitedError) and failure.resets_at is not None:
        return max(PROBE_SECONDS, (failure.resets_at - wall_now).total_seconds())
    return PROBE_SECONDS


class FailureRun:
    """The failures a wait has met since a read or check last answered. It says the first of
    them once, and says a rate limit once more where the run began with another failure."""

    def __init__(self, say: Callable[[forge.ForgeTransientError], None]) -> None:
        self._say = say
        self._failing = False
        self._limited = False

    def add(self, failure: forge.ForgeTransientError) -> None:
        limited = isinstance(failure, forge.ForgeRateLimitedError)
        if not self._failing or (limited and not self._limited):
            self._say(failure)
        self._failing = True
        self._limited = self._limited or limited

    def end(self) -> None:
        self._failing = False
        self._limited = False


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
        self._until: item_wait.UntilWait | None = None
        self._schedule = Schedule(clock.now(), clock.now())
        self._pending = False
        self._listings = board_read.OpenListings(())
        self._listings_owed = False
        self._checked: board_read.OpenListings | None = None
        self._failures = FailureRun(_say_still_waiting)
        self._read_before = False
        self._audits = KeptAudits()

    def start(self) -> BoardEnd | None:
        """The first read: a failure here refuses, a rate limit apart (the first read is then
        owed at the retry time), and the state ref's tip and the probes' tokens are taken
        before it, so what changes during the read is seen."""
        # The target's own refusals (`--repo` under `state-ref`) come before anything is watched.
        _ = self._context.repository_id
        self._tip = self._tip_of_the_state_ref()
        try:
            self._probe_the_forge()
            return self._read(self._clock.now())
        except forge.ForgeRateLimitedError as limited:
            self._fail(limited, self._clock.now())
            self._pending = True
            self._read_before = True
            return None

    def tick(self) -> BoardEnd | None:
        """What one pause brings; a transient failure is said once per run of failures."""
        try:
            return self._tick(self._clock.now())
        except forge.ForgeTransientError as failure:
            self._fail(failure, self._clock.now())
            return None

    def _tick(self, now: float) -> BoardEnd | None:
        moved = self._moved_items()
        held = now < self._schedule.retry_after
        probed = probe_due(now, self._schedule)
        if probed:
            self._schedule = replace(self._schedule, last_probe=now)
            self._probe(held)
        if held:
            return None
        end = self._reread_items(moved) if moved else None
        if end is not None:
            return end
        self._check_listings()
        if self._read_due(now, self._schedule.retry_after):
            return self._read(now)
        if probed or moved:
            self._failures.end()
        return None

    def _probe(self, held: bool) -> None:
        """The state ref is asked at every probe, the forge only outside a hold; the forge's
        refusal does not skip the state ref, and a state ref failure on that tick does not
        replace the refusal, whose reset holds the next call to GitHub."""
        refused: forge.ForgeTransientError | None = None
        if not held:
            try:
                self._probe_the_forge()
            except forge.ForgeTransientError as failure:
                refused = failure
        try:
            self._probe_the_state_ref()
        except forge.ForgeTransientError:
            if refused is None:
                raise
        if refused is not None:
            raise refused

    def _read_due(self, now: float, retry_after: float) -> bool:
        return read_due(
            now,
            Schedule(self._schedule.last_probe, self._schedule.last_read, retry_after),
            pending=self._pending,
            today=self._context.today(),
            earliest_until=self._until,
        )

    def _fail(self, failure: forge.ForgeTransientError, now: float) -> None:
        """Say the failure unless its run has been said, and hold every call to GitHub for
        `retry_seconds`; a failure that names no reset never shortens a hold already set."""
        self._failures.add(failure)
        retry_after = now + retry_seconds(failure, self._context.now())
        self._schedule = replace(
            self._schedule, retry_after=max(self._schedule.retry_after, retry_after)
        )

    def _modified(self, item: int) -> int | None:
        return signal_modified(decide.item_signal_path(self._context, item, self._state))

    def _moved_items(self) -> list[int]:
        return [item for item, seen in self._signals.items() if self._modified(item) != seen]

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
        first time only takes its token. A moved repository target owes a check of the open
        listings; a blocker in another repository asks for a read when its answer is closed."""
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
            if target.number is None:
                self._listings_owed = self._listings_owed or (answer.changed and known is not None)
            else:
                self._pending = self._pending or answer.closed

    def _check_listings(self) -> None:
        """A check owed is made once no read is pending: the open listings are fetched and a
        read is asked for only when they differ from the last read's; the rows it fetched go
        to that read. A failed check stays owed."""
        if not self._listings_owed or self._pending:
            return
        fetched = board_read.fetch_open_listings(self._context.observed_afresh().forge)
        self._listings_owed = False
        if listings_differ(self._listings, fetched):
            self._checked = fetched
            self._pending = True

    def _reread_items(self, items: Sequence[int]) -> BoardEnd | None:
        """Only the items whose signal moved are read again; the signals' times are taken
        before the read, so a ruling during it moves them once more, and the lines that wait
        are those the read found; an item it could not read keeps its lines."""
        context = self._context.observed_afresh()
        taken = {item: self._modified(item) for item in items}
        lines = tuple(status for item in items for status in self._lines_of(context, item))
        reading = BoardReading(None, lines, (), None)
        end = ending(self._waiting, reading)
        if end is None:
            self._signals.update(taken)
            read = {status.item for status in lines}
            self._waiting = frozenset(
                line for line in self._waiting if line[0] not in read
            ) | waiting_lines(reading)
        return end

    def _lines_of(self, context: RunContext, item: int) -> tuple[LineStatus, ...]:
        """The item's lines now; none for an item that is closed, and for one that no
        longer reads as an item the board's own read decides."""
        try:
            fresh = decide.fresh_item(context, item, command="wait")
        except decide.InvalidTargetError:
            self._pending = True
            return ()
        if fresh.state is not forge.ItemState.OPEN:
            return ()
        return _item_line_statuses(item, fresh.body, fresh.storage)

    def _read(self, now: float) -> BoardEnd | None:
        """A fresh read; the signals' times are taken before it, so a ruling during
        it moves them again, and an item first watched reads as moved. It ends the wait or
        becomes what the next ticks compare to; the blockers it found are probed after it."""
        before = {item: self._modified(item) for item in self._signals}
        context = self._context.observed_afresh() if self._read_before else self._context
        checked, self._checked = self._checked, None
        reading = read_board(context, self._audits, checked)
        self._read_before = True
        end = ending(self._waiting, reading)
        if end is not None:
            return end
        self._waiting = waiting_lines(reading)
        self._blockers = reading.foreign_blockers
        self._until = reading.earliest_until
        watched = sorted({item for item, _index in self._waiting})
        self._signals = {item: before.get(item, _UNSEEN) for item in watched}
        self._listings = reading.listings
        self._listings_owed = False
        self._pending = False
        self._failures.end()
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
