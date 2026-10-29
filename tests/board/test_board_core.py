"""The board's own rules driven without any socket.

Each test calls `Board` or `Boards` over the real `aco` adapter against a
fake `aco` on PATH whose state the test sets, or over a held in-memory
`DecisionPort` where the order of concurrent decisions is the behaviour; no
server is started. The served board and `aco serve` itself also prove
one write at a time and the shutdown drain end-to-end (test_board_server,
test_board_cli).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from aco_board_fixtures import FakeAcoRepository, line, option_line, row

from aco.board.aco_cli import AcoCli
from aco.board.board import SHUTTING_DOWN, Board, Boards, wire_fingerprint
from aco.board.ports import (
    CardChanged,
    CardDecision,
    Decision,
    DecisionResult,
    DecisionStatus,
    ExpectationLine,
    Outcome,
    PostedCard,
    PostedLine,
    YesNoLine,
)

_WAIT_SECONDS = 5
_LABEL = "repo"


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

    assert isinstance(read_line, YesNoLine)
    assert read == (read_line.default, read_line.ruling, read_line.ruled_on, read_line.is_open)


def test_a_decision_after_writes_closed_is_refused_without_writing(
    repository: FakeAcoRepository,
) -> None:
    repository.set_rulings(row(42, "Share page", line(1, "Guests?")))
    board = Board(AcoCli(directory=repository.directory))
    boards = Boards({_LABEL: board})
    [shown] = board.snapshot().lines

    boards.close_writes()

    result = boards.decide(_LABEL, Decision(42, 1, Outcome.YES, None), shown.fingerprint)
    assert result == DecisionResult(DecisionStatus.FAILED, SHUTTING_DOWN)
    assert repository.rule_calls() == []


class _HeldDecisions:
    """A `DecisionPort` whose first ruling stays inside its write until released."""

    def __init__(self) -> None:
        self.writing = threading.Event()
        self.may_finish = threading.Event()
        self.ruled: list[Decision] = []
        self.ruled_cards: list[CardDecision] = []
        self.lines: tuple[ExpectationLine, ...] = ()

    def expectation_lines(self) -> tuple[ExpectationLine, ...]:
        return self.lines

    def rule(self, decision: Decision) -> DecisionResult:
        self.writing.set()
        assert self.may_finish.wait(_WAIT_SECONDS)
        self.ruled.append(decision)
        return DecisionResult(DecisionStatus.RULED, "ruled")

    def rule_card(self, decision: CardDecision) -> DecisionResult | CardChanged:
        self.writing.set()
        assert self.may_finish.wait(_WAIT_SECONDS)
        self.ruled_cards.append(decision)
        return DecisionResult(DecisionStatus.RULED)


def _card_held_in(
    repository: FakeAcoRepository, label: str, item: int = 7
) -> tuple[_HeldDecisions, PostedCard]:
    """A held port that reads item `item`'s one option line, and that card posted for `label`."""
    repository.set_rulings(row(item, "Karte", option_line()))
    [shown] = Board(AcoCli(directory=repository.directory)).snapshot().lines
    decisions = _HeldDecisions()
    decisions.lines = (shown,)
    posted = PostedCard(item, (PostedLine(shown.index, wire_fingerprint(label, shown), "A"),), None)
    return decisions, posted


def _card_waiting_for_its_turn(item: int) -> PostedCard:
    """A card that is refused for the stopped turn before it is ever read."""
    return PostedCard(item, (PostedLine(1, "shown", "A"),), None)


def _signal_when_a_decision_waits_for_its_turn(
    boards: Boards, monkeypatch: pytest.MonkeyPatch
) -> threading.Event:
    """An event set once a caller is inside the boards' turn wait.

    The event is set while that caller still holds the turn lock, so whoever
    takes the lock next, `close_writes` included, finds it already waiting.
    """
    turn = boards._turn
    entered = threading.Event()
    wait = turn.wait

    def signalling_wait(timeout: float | None = None) -> bool:
        entered.set()
        return wait(timeout)

    monkeypatch.setattr(turn, "wait", signalling_wait)
    return entered


def test_a_decision_waiting_for_its_turn_is_refused_once_stopping_begins(
    repository: FakeAcoRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ABRD-17/18: one write turn spans every configured repo, and a staged,
    event-driven drain refuses a still-waiting decision the moment stopping
    begins, without waiting for the decision already being written."""
    decisions, running = _card_held_in(repository, _LABEL)
    boards = Boards({_LABEL: Board(decisions)})
    waiting_for_turn = _signal_when_a_decision_waits_for_its_turn(boards, monkeypatch)
    waiting = _card_waiting_for_its_turn(8)

    with ThreadPoolExecutor(max_workers=3) as threads:
        running_answer = threads.submit(boards.decide_card, _LABEL, running)
        assert decisions.writing.wait(_WAIT_SECONDS)
        waiting_answer = threads.submit(boards.decide_card, _LABEL, waiting)
        assert waiting_for_turn.wait(_WAIT_SECONDS)
        stopping = threads.submit(boards.close_writes)

        # Answered while the running write is still held: the waiting
        # decision never gets a turn after stopping began.
        assert waiting_answer.result(_WAIT_SECONDS) == DecisionResult(
            DecisionStatus.FAILED, SHUTTING_DOWN
        )
        assert not stopping.done()
        decisions.may_finish.set()
        stopping.result(_WAIT_SECONDS)

    assert running_answer.result().status is DecisionStatus.RULED
    assert [card.item for card in decisions.ruled_cards] == [running.item]


def test_a_card_write_holds_the_turn_against_a_decision_waiting_behind_it(
    repository: FakeAcoRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ABRD-17, ABRD-18, ABRD-77: a card is written inside the one turn, and stopping
    refuses what waits behind it while the card write still completes."""
    decisions, posted = _card_held_in(repository, _LABEL)
    boards = Boards({_LABEL: Board(decisions)})
    waiting_for_turn = _signal_when_a_decision_waits_for_its_turn(boards, monkeypatch)

    with ThreadPoolExecutor(max_workers=3) as threads:
        running_card = threads.submit(boards.decide_card, _LABEL, posted)
        assert decisions.writing.wait(_WAIT_SECONDS)
        waiting_answer = threads.submit(boards.decide_card, _LABEL, _card_waiting_for_its_turn(8))
        assert waiting_for_turn.wait(_WAIT_SECONDS)
        stopping = threads.submit(boards.close_writes)

        assert waiting_answer.result(_WAIT_SECONDS) == DecisionResult(
            DecisionStatus.FAILED, SHUTTING_DOWN
        )
        decisions.may_finish.set()
        stopping.result(_WAIT_SECONDS)

    assert running_card.result().status is DecisionStatus.RULED
    assert [card.item for card in decisions.ruled_cards] == [posted.item]


def test_one_repos_write_blocks_a_second_repos_decision_until_its_turn(
    repository: FakeAcoRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ABRD-17: the write turn is global, not per repo -- a decision for repo
    B waits while repo A's decision is being written, even though the two
    repos never touch the same state."""
    decisions_a, card_in_a = _card_held_in(repository, "a")
    decisions_b, card_in_b = _card_held_in(repository, "b")
    boards = Boards({"a": Board(decisions_a), "b": Board(decisions_b)})
    waiting_for_turn = _signal_when_a_decision_waits_for_its_turn(boards, monkeypatch)

    with ThreadPoolExecutor(max_workers=2) as threads:
        running_in_a = threads.submit(boards.decide_card, "a", card_in_a)
        assert decisions_a.writing.wait(_WAIT_SECONDS)
        waiting_in_b = threads.submit(boards.decide_card, "b", card_in_b)
        assert waiting_for_turn.wait(_WAIT_SECONDS)

        assert not waiting_in_b.done()
        assert not decisions_b.writing.is_set()
        decisions_a.may_finish.set()

        assert decisions_b.writing.wait(_WAIT_SECONDS)
        decisions_b.may_finish.set()
        assert waiting_in_b.result(_WAIT_SECONDS).status is DecisionStatus.RULED
    assert running_in_a.result().status is DecisionStatus.RULED
