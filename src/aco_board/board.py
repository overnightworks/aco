"""The decision board's own rules, free of any transport.

`Board` reads every expectation line afresh from its `DecisionPort` and
writes one decision at a time through it. It knows the port only, never
the adapter behind it, and keeps no copy of a line or a ruling.
"""

from __future__ import annotations

import threading
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


@dataclass(frozen=True)
class BoardSnapshot:
    lines: tuple[ExpectationLine, ...]
    """Every line, open and ruled, in the source's own order."""

    @property
    def open_lines(self) -> tuple[ExpectationLine, ...]:
        return tuple(line for line in self.lines if line.is_open)


class Board:
    def __init__(self, decisions: DecisionPort) -> None:
        self._decisions = decisions
        # `aco rule` rewrites the whole item body, so two writes at once could
        # each drop the other's ruling; the board writes one at a time.
        self._turn = threading.Condition()
        self._writing = False
        self._closed = False

    def snapshot(self) -> BoardSnapshot:
        """A fresh read of the source; raises `DecisionSourceUnavailableError`."""
        return BoardSnapshot(self._decisions.expectation_lines())

    def decide(self, decision: Decision, fingerprint: str) -> DecisionResult:
        """Write `decision` unless the open line it names no longer reads as shown.

        The fingerprint comparison is the board's only own check: the card was
        built from an earlier read, and an open line whose shown fields changed
        since must not be ruled blind. A line that is no longer open skips the
        comparison on purpose: whether it is already ruled, out of range, or its
        item unknown is the source's own refusal, which `rule` reports.
        """
        if not self._take_turn():
            return DecisionResult(DecisionStatus.FAILED, SHUTTING_DOWN)
        try:
            return self._decide_one(decision, fingerprint)
        finally:
            self._end_turn()

    def close_writes(self) -> None:
        """Refuse every decision not yet being written, then wait for the one that is.

        A caller stopping the process calls this first, so a ruling inside the
        source's write is never cut off with its outcome unknown. Refusing
        comes first so a decision still waiting for its turn cannot slip in
        behind the running write once stopping began.
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

    def _decide_one(self, decision: Decision, fingerprint: str) -> DecisionResult:
        try:
            lines = self._decisions.expectation_lines()
        except DecisionSourceUnavailableError as error:
            return DecisionResult(DecisionStatus.FAILED, str(error))
        named = (decision.item, decision.index)
        if any(
            (line.item, line.index) == named and line.is_open and line.fingerprint != fingerprint
            for line in lines
        ):
            return DecisionResult(DecisionStatus.FAILED, LINE_CHANGED)
        return self._decisions.rule(decision)
