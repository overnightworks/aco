"""The decision board's own rules, free of any transport.

`Board` reads every expectation line afresh from its `DecisionPort` and
writes one whole option card at a time through it, with no
concurrency state of its own. `Boards` composes one or more `Board`s under their
repo labels: it reads every repo in parallel, isolating a failing repo to its own
`RepoUnavailable` entry, and owns the one write turn and drain shared across all of them --
including the single-repo case, so that lock never exists twice.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from .ports import (
    CardChanged,
    CardDecision,
    CardLine,
    DecisionPort,
    DecisionResult,
    DecisionSourceUnavailableError,
    DecisionStatus,
    ExpectationLine,
    OptionLine,
    PostedCard,
)

LINE_CHANGED = "Diese Zeile hat sich geändert, bitte neu laden"
SHUTTING_DOWN = "board is shutting down"


def wire_fingerprint(repo: str, line: ExpectationLine) -> str:
    """The fingerprint a card exposes across the wire: `line`'s own fingerprint
    bound to the `repo` label it was read under. The JSON API and
    `checked_card`'s own repo-binding check share this one function, so a
    card's content being identical in two configured repos never lets its
    fingerprint satisfy the other repo's check, even with the two labels
    swapped."""
    bound = json.dumps([repo, line.fingerprint], ensure_ascii=False)
    return hashlib.sha256(bound.encode("utf-8", "surrogatepass")).hexdigest()


@dataclass(frozen=True)
class BoardSnapshot:
    lines: tuple[ExpectationLine, ...]
    """Every line, open and ruled, in the source's own order."""


@dataclass(frozen=True)
class RepoSnapshot:
    name: str
    lines: tuple[ExpectationLine, ...]
    """Every line of this repo, open and ruled, in its source's own order."""


@dataclass(frozen=True)
class RepoUnavailable:
    name: str
    reason: str
    """The one sentence `DecisionSourceUnavailableError` carried for this repo."""


RepoReading = RepoSnapshot | RepoUnavailable


def all_repos_unavailable(readings: Sequence[RepoReading]) -> bool:
    """True once every configured repo's read failed and the board has nothing to show."""
    return all(isinstance(reading, RepoUnavailable) for reading in readings)


class Board:
    def __init__(self, decisions: DecisionPort) -> None:
        self._decisions = decisions

    def snapshot(self) -> BoardSnapshot:
        """A fresh read of the source; raises `DecisionSourceUnavailableError`."""
        return BoardSnapshot(self._decisions.expectation_lines())

    def decide_card(self, posted: PostedCard, repo: str) -> DecisionResult:
        """Write `posted` with one call unless it no longer reads as the card shown.

        The check and the write share one fresh read, so each hash written is the
        one the check compared. Callers serialize writes across every repo
        (`Boards`); this method itself holds no lock, so it must never run
        concurrently with another call on the same `Board`.
        """
        try:
            lines = self._decisions.expectation_lines()
        except DecisionSourceUnavailableError as error:
            return DecisionResult(DecisionStatus.FAILED, str(error))
        checked = checked_card(posted, repo, lines)
        if checked is None:
            return DecisionResult(DecisionStatus.FAILED, LINE_CHANGED)
        written = self._decisions.rule_card(checked)
        if isinstance(written, CardChanged):
            return DecisionResult(DecisionStatus.FAILED, LINE_CHANGED)
        return written


def checked_card(
    posted: PostedCard, repo: str, lines: Sequence[ExpectationLine]
) -> CardDecision | None:
    """The posted card as a decision on the lines just read, or None when it no
    longer reads as shown: every posted line must be an option line of the item,
    each open one with its posted fingerprint, and every open option line of the
    item must be posted. A posted line that is no longer open is the source's own
    refusal to make."""
    options = {
        line.index: line
        for line in lines
        if isinstance(line, OptionLine) and line.item == posted.item
    }
    checked: list[CardLine] = []
    for posted_line in posted.lines:
        shown = options.get(posted_line.index)
        if shown is None or (
            shown.is_open and wire_fingerprint(repo, shown) != posted_line.fingerprint
        ):
            return None
        checked.append(CardLine(posted_line.index, shown.card_hash, posted_line.letter))
    posted_indexes = {posted_line.index for posted_line in posted.lines}
    if any(line.is_open and index not in posted_indexes for index, line in options.items()):
        return None
    return CardDecision(posted.item, tuple(checked), posted.answer)


class Boards:
    """One or more repos' `Board`s under their labels, sharing one write turn.

    `aco rule` rewrites a whole item body, so two writes at once -- even in
    different repos, since nothing here needs that to be safe -- could each
    leave the outcome of a stopped write unknown; this is the single owner of
    that rule, always, even when only one repo is configured.
    """

    def __init__(self, boards: Mapping[str, Board]) -> None:
        self._boards = dict(boards)
        self._turn = threading.Condition()
        self._writing = False
        self._closed = False

    @property
    def labels(self) -> tuple[str, ...]:
        """Every configured repo's label, in configured order."""
        return tuple(self._boards)

    def snapshot(self) -> tuple[RepoReading, ...]:
        """Every configured repo read in parallel, in configured order.

        A repo whose read raises becomes its own `RepoUnavailable` entry; the
        others' readings are unaffected.
        """
        with ThreadPoolExecutor(max_workers=len(self._boards)) as executor:
            futures = {
                label: executor.submit(board.snapshot) for label, board in self._boards.items()
            }
            return tuple(_reading(label, futures[label]) for label in self._boards)

    def decide_card(self, repo: str, posted: PostedCard) -> DecisionResult:
        """Write a whole card through `repo`'s board in the one write turn;
        `repo` must already be one of `labels`."""
        if not self._take_turn():
            return DecisionResult(DecisionStatus.FAILED, SHUTTING_DOWN)
        try:
            return self._boards[repo].decide_card(posted, repo)
        finally:
            self._end_turn()

    def close_writes(self) -> None:
        """Refuse every decision not yet being written, then wait for the one that is.

        A caller stopping the process calls this first, so a ruling inside a
        repo's write is never cut off with its outcome unknown. Refusing comes
        first so a decision still waiting for its turn cannot slip in behind
        the running write once stopping began.
        """
        with self._turn:
            self._closed = True
            self._turn.notify_all()
            self._turn.wait_for(lambda: not self._writing)

    def _take_turn(self) -> bool:
        """Wait until no decision is being written; False once writes closed."""
        with self._turn:
            self._turn.wait_for(lambda: self._closed or not self._writing)
            if self._closed:
                return False
            self._writing = True
            return True

    def _end_turn(self) -> None:
        with self._turn:
            self._writing = False
            self._turn.notify_all()


def _reading(label: str, future: Future[BoardSnapshot]) -> RepoReading:
    try:
        return RepoSnapshot(label, future.result().lines)
    except DecisionSourceUnavailableError as error:
        return RepoUnavailable(label, str(error))
