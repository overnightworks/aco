"""The decision board's own rules, free of any transport.

`Board` reads every expectation line afresh from its `DecisionPort` and
writes one decision at a time through it, with no concurrency state of its
own. `Boards` composes one or more `Board`s under their repo labels: it reads
every repo in parallel, isolating a failing repo to its own `RepoUnavailable`
entry, and owns the one write turn and drain shared across all of them --
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
    Decision,
    DecisionPort,
    DecisionResult,
    DecisionSourceUnavailableError,
    DecisionStatus,
    ExpectationLine,
)

LINE_CHANGED = "Diese Zeile hat sich geändert, bitte neu laden"
SHUTTING_DOWN = "board is shutting down"


def wire_fingerprint(repo: str, line: ExpectationLine) -> str:
    """The fingerprint a card exposes across the wire: `line`'s own fingerprint
    bound to the `repo` label it was read under. The JSON API and
    `Boards.decide`'s own repo-binding check share this one function, so a
    card's content being identical in two configured repos never lets its
    fingerprint satisfy the other repo's check, even with the two labels
    swapped (issue #637)."""
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

    def decide_one(self, decision: Decision, repo: str, fingerprint: str) -> DecisionResult:
        """Write `decision` unless the open line it names no longer reads as shown.

        The fingerprint comparison is the board's only own check: the card was
        built from an earlier read, and an open line whose shown fields changed
        since must not be ruled blind. It compares `wire_fingerprint(repo, ...)`,
        not the line's own bare fingerprint, so the same content read under
        another repo's label never passes here either (issue #637). A line
        that is no longer open skips the comparison on purpose: whether it is
        already ruled, out of range, or its item unknown is the source's own
        refusal, which `rule` reports.

        Callers serialize writes across every repo (`Boards`); this method
        itself holds no lock, so it must never run concurrently with another
        call on the same `Board`.
        """
        try:
            lines = self._decisions.expectation_lines()
        except DecisionSourceUnavailableError as error:
            return DecisionResult(DecisionStatus.FAILED, str(error))
        named = (decision.item, decision.index)
        if any(
            (line.item, line.index) == named
            and line.is_open
            and wire_fingerprint(repo, line) != fingerprint
            for line in lines
        ):
            return DecisionResult(DecisionStatus.FAILED, LINE_CHANGED)
        return self._decisions.rule(decision)


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

    def decide(self, repo: str, decision: Decision, fingerprint: str) -> DecisionResult:
        """Write through `repo`'s board; `repo` must already be one of `labels`.

        `fingerprint` is `wire_fingerprint`'s value for the card as shown,
        bound to `repo`: `Board.decide_one` checks it against the same
        binding during its own fresh read, so an identical line read under
        another configured repo's label never satisfies it (issue #637).
        """
        if not self._take_turn():
            return DecisionResult(DecisionStatus.FAILED, SHUTTING_DOWN)
        try:
            return self._boards[repo].decide_one(decision, repo, fingerprint)
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
