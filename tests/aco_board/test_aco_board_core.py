"""The board's own rules driven without any socket.

Each test calls `Board` over the real `aco` adapter against a fake `aco` on
PATH whose state the test sets, or over a held in-memory `DecisionPort`
where the order of concurrent decisions is the behaviour; no server is
started. One write at a time and the shutdown drain are also proven through
the served board and `aco-board serve` itself (test_aco_board_server,
test_aco_board_cli).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest
from aco_board_fixtures import FakeAcoRepository, empty_repository_with_fake_aco, line, row

from aco_board.aco_cli import AcoCli
from aco_board.board import SHUTTING_DOWN, Board
from aco_board.ports import Decision, DecisionResult, DecisionStatus, ExpectationLine, Outcome

_WAIT_SECONDS = 5


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeAcoRepository:
    return empty_repository_with_fake_aco(tmp_path, monkeypatch)


@pytest.mark.parametrize(
    ("stored", "read"),
    [
        (line(1, "Guests?", default="later"), (Outcome.LATER, None, None, True)),
        (line(1, "Links?", ruling="no"), (None, Outcome.NO, date(2026, 10, 1), False)),
        (line(1, "Older aco without a recommendation?"), (None, None, None, True)),
    ],
    ids=["open-with-recommendation", "ruled", "open-without-recommendation"],
)
def test_a_snapshot_reads_a_lines_recommendation_and_ruling(
    repository: FakeAcoRepository,
    stored: dict[str, object],
    read: tuple[Outcome | None, Outcome | None, date | None, bool],
) -> None:
    repository.set_rulings(row(42, "Share page", stored))

    [read_line] = Board(AcoCli(directory=repository.directory)).snapshot().lines

    assert read == (read_line.default, read_line.ruling, read_line.ruled_on, read_line.is_open)


def test_a_decision_after_writes_closed_is_refused_without_writing(
    repository: FakeAcoRepository,
) -> None:
    repository.set_rulings(row(42, "Share page", line(1, "Guests?")))
    board = Board(AcoCli(directory=repository.directory))
    [shown] = board.snapshot().lines

    board.close_writes()

    assert board.decide(Decision(42, 1, Outcome.YES, None), shown.fingerprint) == DecisionResult(
        DecisionStatus.FAILED, SHUTTING_DOWN
    )
    assert repository.rule_calls() == []


class _HeldDecisions:
    """A `DecisionPort` whose first ruling stays inside its write until released."""

    def __init__(self) -> None:
        self.writing = threading.Event()
        self.may_finish = threading.Event()
        self.ruled: list[Decision] = []

    def expectation_lines(self) -> tuple[ExpectationLine, ...]:
        return ()

    def rule(self, decision: Decision) -> DecisionResult:
        self.writing.set()
        assert self.may_finish.wait(_WAIT_SECONDS)
        self.ruled.append(decision)
        return DecisionResult(DecisionStatus.RULED, "ruled")


def _signal_when_a_decision_waits_for_its_turn(
    board: Board, monkeypatch: pytest.MonkeyPatch
) -> threading.Event:
    """An event set once a caller is inside the board's turn wait.

    The event is set while that caller still holds the turn lock, so whoever
    takes the lock next, `close_writes` included, finds it already waiting.
    """
    turn = board._turn
    entered = threading.Event()
    wait = turn.wait

    def signalling_wait(timeout: float | None = None) -> bool:
        entered.set()
        return wait(timeout)

    monkeypatch.setattr(turn, "wait", signalling_wait)
    return entered


def test_a_decision_waiting_for_its_turn_is_refused_once_stopping_begins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decisions = _HeldDecisions()
    board = Board(decisions)
    waiting_for_turn = _signal_when_a_decision_waits_for_its_turn(board, monkeypatch)
    running, waiting = Decision(42, 1, Outcome.YES, None), Decision(42, 2, Outcome.NO, None)

    with ThreadPoolExecutor(max_workers=3) as threads:
        running_answer = threads.submit(board.decide, running, "shown")
        assert decisions.writing.wait(_WAIT_SECONDS)
        waiting_answer = threads.submit(board.decide, waiting, "shown")
        assert waiting_for_turn.wait(_WAIT_SECONDS)
        stopping = threads.submit(board.close_writes)

        # Answered while the running write is still held: the waiting
        # decision never gets a turn after stopping began.
        assert waiting_answer.result(_WAIT_SECONDS) == DecisionResult(
            DecisionStatus.FAILED, SHUTTING_DOWN
        )
        assert not stopping.done()
        decisions.may_finish.set()
        stopping.result(_WAIT_SECONDS)

    assert running_answer.result().status is DecisionStatus.RULED
    assert decisions.ruled == [running]
