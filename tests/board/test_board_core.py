"""The board's own rules driven without any socket.

Each test calls `Board` or `Boards` over the board's port on the real `aco`
over a fake forge, or over a held in-memory `DecisionPort` where the order
of concurrent decisions is the behaviour; no server is started. Two card
posts on different items at once are held at the port itself, so the
second one's wait for its turn is seen in the port log (ABRD-03, ABRD-17).
The served board and `aco serve` itself also prove the shutdown drain
end-to-end (test_board_server, test_board_cli).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from aco_board_fixtures import CallPhase, PortCall, decision_port
from board_forge import BoardForge, item_body
from option_cards import open_option_entry

from aco import expectations, rulings
from aco.board.board import SHUTTING_DOWN, Board, Boards, wire_fingerprint
from aco.board.ports import (
    CardChanged,
    CardCheck,
    CardDecision,
    CardLine,
    DecisionResult,
    DecisionStatus,
    PostedCard,
    PostedLine,
)

_WAIT_SECONDS = 5
_LABEL = "repo"


def test_a_snapshot_reads_a_ruled_yes_no_lines_ruling_and_date(repository: BoardForge) -> None:
    links = {"text": "Links?", "ruling": "no", "ruled_on": date(2026, 10, 1)}
    repository.put_item(42, item_body(links), title="Share page")

    [row] = Board(decision_port(repository)).snapshot().rows

    [read_line] = row.lines
    assert isinstance(read_line, expectations.YesNoLine)
    assert (read_line.ruling, read_line.ruled_on) == ("no", date(2026, 10, 1))


def _lines_of(rows: tuple[rulings.Row, ...], item: int) -> tuple[expectations.ExpectationLine, ...]:
    [row] = [row for row in rows if row.number == item]
    return row.lines


class _HeldDecisions:
    """A `DecisionPort` whose first ruling stays inside its write until released."""

    def __init__(self) -> None:
        self.writing = threading.Event()
        self.may_finish = threading.Event()
        self.ruled_cards: list[CardDecision] = []
        self.read: tuple[rulings.Row, ...] = ()

    def rows(self) -> tuple[rulings.Row, ...]:
        return self.read

    def rule_card(self, item: int, check: CardCheck) -> DecisionResult | CardChanged:
        """Checks the posted card on its item's lines, as the real source does on its read."""
        decision = check(_lines_of(self.read, item))
        assert decision is not None
        self.writing.set()
        assert self.may_finish.wait(_WAIT_SECONDS)
        self.ruled_cards.append(decision)
        return DecisionResult(DecisionStatus.RULED)


def _posted(rows: tuple[rulings.Row, ...], label: str, item: int) -> PostedCard:
    """Item `item`'s one option line among `rows`, posted `A` for `label`."""
    [shown] = _lines_of(rows, item)
    assert isinstance(shown, expectations.OptionLine)
    fingerprint = wire_fingerprint(label, item, shown)
    return PostedCard(item, (PostedLine(shown.index, fingerprint, "A"),), None)


def _card_held_in(
    repository: BoardForge, label: str, item: int = 7
) -> tuple[_HeldDecisions, PostedCard]:
    """A held port that reads item `item`'s one option line, and that card posted for `label`."""
    repository.put_item(item, item_body(open_option_entry()))
    decisions = _HeldDecisions()
    decisions.read = Board(decision_port(repository)).snapshot().rows
    return decisions, _posted(decisions.read, label, item)


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


def _each_call_completes_before_the_next_enters(calls: tuple[PortCall, ...]) -> bool:
    entering, completing = calls[0::2], calls[1::2]
    return len(entering) == len(completing) and all(
        (entered.phase, completed.phase) == (CallPhase.ENTERED, CallPhase.COMPLETED)
        and (entered.operation, entered.item) == (completed.operation, completed.item)
        for entered, completed in zip(entering, completing, strict=True)
    )


def test_card_posts_on_two_items_at_once_are_both_stored_one_at_a_time(
    repository: BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ABRD-03, ABRD-17: the second decision makes no port call while the
    first is inside its write, and neither write is lost."""
    for item in (42, 7):
        repository.put_item(item, item_body(open_option_entry()))
    port = decision_port(repository)
    rows = Board(port).snapshot().rows
    first, second = _posted(rows, _LABEL, 42), _posted(rows, _LABEL, 7)
    boards = Boards({_LABEL: Board(port)})
    waiting_for_turn = _signal_when_a_decision_waits_for_its_turn(boards, monkeypatch)
    held = port.hold_next_rule_card(_WAIT_SECONDS)

    with ThreadPoolExecutor(max_workers=2) as threads:
        running = threads.submit(boards.decide_card, _LABEL, first)
        assert held.entered.wait(_WAIT_SECONDS)
        calls_while_held = port.calls()
        waiting = threads.submit(boards.decide_card, _LABEL, second)
        assert waiting_for_turn.wait(_WAIT_SECONDS)

        assert port.calls() == calls_while_held
        held.release.set()
        answers = [running.result(_WAIT_SECONDS).status, waiting.result(_WAIT_SECONDS).status]

    assert answers == [DecisionStatus.RULED, DecisionStatus.RULED]
    assert [repository.stored_entries(item)[0]["ruling"] for item in (42, 7)] == ["A", "A"]
    assert _each_call_completes_before_the_next_enters(port.calls())


def test_a_decision_waiting_for_its_turn_is_refused_once_stopping_begins(
    repository: BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ABRD-17/18/77: one write turn spans every configured repo, and a staged,
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
    [shown] = _lines_of(decisions.read, running.item)
    assert isinstance(shown, expectations.OptionLine)
    assert decisions.ruled_cards == [
        CardDecision(
            running.item,
            (CardLine(shown.index, shown.card_hash, running.lines[0].letter),),
            None,
        )
    ]


def test_one_repos_write_blocks_a_second_repos_decision_until_its_turn(
    repository: BoardForge, monkeypatch: pytest.MonkeyPatch
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
