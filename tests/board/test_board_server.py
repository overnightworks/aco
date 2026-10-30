"""The board's HTTP transport, driven beneath any route's own behaviour.

Every scenario here is about the wire, not a particular route's decision
rules (owned by `test_board_api.py`) or its static files (owned by
`test_board_static.py`): a malformed or stalled request, a client that
leaves mid-answer, a broken decision source, loopback-only binding, and
draining a stalled connection on shutdown. Only the forge is a fake
(`board_forge.BoardForge`); the server, wire form, adapter and `aco` itself
are real.
"""

from __future__ import annotations

import json
import socket
import threading
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from aco_board_fixtures import (
    BoardClient,
    CallPhase,
    Lister,
    PortCall,
    PortOperation,
    RecordedPort,
    Response,
    decision_port,
    serving,
)
from board_forge import BoardForge, ForgeRequest, item_body
from option_cards import open_option_entry

from aco import rulings
from aco.board.ports import CardChanged, CardCheck, DecisionResult
from aco.board.server import LOOPBACK_HOST, read_before_deadline

_OPEN_CARD = item_body(open_option_entry())


def _assert_never_written(port: RecordedPort, repository: BoardForge) -> None:
    """No `rule_card` reached the port, and the forge saw no body write."""
    assert (port.ruled_items(), repository.body_writes()) == ([], [])


def _aco_traffic(
    port: RecordedPort, repository: BoardForge
) -> tuple[tuple[PortCall, ...], tuple[ForgeRequest, ...]]:
    """Every call the port saw and every request the forge saw so far; equal
    snapshots around a request mean it was answered before any aco call."""
    return port.calls(), repository.request_log()


def _post(body: bytes, length: bytes | None = None) -> bytes:
    """A raw `POST /api/rule`, its token still a `{token}` placeholder for
    the caller to fill in once the serving board has minted one."""
    declared = str(len(body)).encode() if length is None else length
    return (
        b"POST /api/rule HTTP/1.1\r\nHost: x\r\nX-Board-Token: {token}\r\nContent-Length: "
        + declared
        + b"\r\n\r\n"
        + body
    )


_NO_CONTENT_LENGTH = b"POST /api/rule HTTP/1.1\r\nHost: x\r\nX-Board-Token: {token}\r\n\r\n"


@pytest.mark.parametrize(
    "request_template",
    [
        _NO_CONTENT_LENGTH,
        _post(b"{}", b"abc"),
        _post(b"{}", b"-1"),
        _post(b"{}", b"\xd9\xa3"),
        _post(b"{}", b"9" * 5000),
        _post(b"{}", b"16385"),
        _post(b"x" * 16385),
        _post(b"[" * 16000),
        _post(b'{"item": 1' + b"0" * 5000 + b"}"),
        _post(b'{"token": "\xed\xa0\x80"}'),
    ],
    ids=[
        "no-content-length",
        "content-length-not-numeric",
        "content-length-negative",
        "content-length-non-ascii-digit",
        "content-length-past-int-limit",
        "content-length-over-limit",
        "body-over-limit",
        "body-nested-too-deep",
        "body-integer-past-int-limit",
        "body-not-utf8",
    ],
)
def test_a_malformed_api_request_gets_a_fixed_400_without_a_traceback(
    repository: BoardForge,
    board: BoardClient,
    port: RecordedPort,
    capsys: pytest.CaptureFixture[str],
    request_template: bytes,
) -> None:
    arranged = _aco_traffic(port, repository)

    answer = board.send_raw(request_template.replace(b"{token}", board.token.encode()))

    status_line, _, rest = answer.partition(b"\r\n")
    assert status_line.split(b" ")[1] == b"400"
    assert b"Traceback" not in rest
    assert str(Path(__file__).parents[2]).encode() not in rest
    assert "Traceback" not in capsys.readouterr().err
    assert _aco_traffic(port, repository) == arranged


def _decision_json(board: BoardClient) -> bytes:
    """A card on item 42's one option line, with the fingerprint the board lists now."""
    repos = cast(list[dict[str, Any]], board.get_board_json().json()["repos"])
    listed = repos[0]["items"][0]["lines"][0]
    return json.dumps(
        {
            "repo": board.repo,
            "item": 42,
            "lines": [{"line": 1, "fingerprint": listed["fingerprint"], "option": "A"}],
        }
    ).encode()


_SHORT_DEADLINE_SECONDS = 0.2


@pytest.mark.parametrize(
    ("unfinished_template", "status"),
    [
        (b"POST /api/rule HTTP/1.1\r\nHost: x\r\n", None),
        (_post(b'{"item": 42}', b"40"), b"408"),
    ],
    ids=["headers-unfinished", "body-unfinished"],
)
def test_a_stalled_request_is_dropped_after_the_deadline_without_a_traceback(
    repository: BoardForge,
    capsys: pytest.CaptureFixture[str],
    unfinished_template: bytes,
    status: bytes | None,
) -> None:
    decisions = decision_port(repository)
    with serving(decisions, request_deadline_seconds=_SHORT_DEADLINE_SECONDS) as board:
        filled = unfinished_template.replace(b"{token}", board.token.encode())
        answer = board.send_unfinished(filled)

    assert (answer.split(b" ")[1] if answer else None) == status
    assert "Traceback" not in capsys.readouterr().err
    assert (decisions.calls(), repository.request_log()) == ((), ())


@pytest.mark.parametrize(
    "truncate", [False, True], ids=["valid-decision-ending-early", "cut-mid-object"]
)
def test_a_body_ending_before_its_declared_length_answers_408_and_rules_nothing(
    repository: BoardForge, board: BoardClient, port: RecordedPort, truncate: bool
) -> None:
    repository.put_item(42, _OPEN_CARD, title="Share page")
    decision = _decision_json(board)
    body = decision[: len(decision) // 2] if truncate else decision
    declared_length = str(len(decision) + 25).encode()
    arranged = _aco_traffic(port, repository)

    answer = board.send_raw(_post(body, declared_length).replace(b"{token}", board.token.encode()))

    response = Response.from_raw(answer)
    assert (response.status, response.json()) == (
        408,
        {"error": "request timeout: body incomplete"},
    )
    assert _aco_traffic(port, repository) == arranged


def test_a_body_still_arriving_when_its_deadline_has_passed_times_out() -> None:
    reader_end, sender_end = socket.socketpair()
    with reader_end, sender_end, reader_end.makefile("rb") as rfile:
        sender_end.sendall(b'{"item": 42}')

        with pytest.raises(TimeoutError):
            read_before_deadline(rfile, reader_end, 40, deadline_seconds=0.0)


def test_a_stalled_request_does_not_hold_up_shutdown(repository: BoardForge) -> None:
    def serve_and_stop_beneath(stalled_clients: ExitStack) -> None:
        with serving(decision_port(repository)) as board:
            stalled_clients.enter_context(board.holding_unfinished(b"GET /?t="))
            # Connections are accepted in order, so this answer means the
            # stalled one already holds a handler.
            board.send_raw(b"GET /elsewhere HTTP/1.1\r\nHost: x\r\n\r\n")

    with ExitStack() as stalled_clients:
        stopping = threading.Thread(
            target=serve_and_stop_beneath, args=(stalled_clients,), daemon=True
        )
        stopping.start()
        stopping.join(timeout=5)

        assert not stopping.is_alive()


def test_a_browser_leaving_mid_answer_prints_no_traceback(
    repository: BoardForge, capsys: pytest.CaptureFixture[str]
) -> None:
    repository.put_item(42, _OPEN_CARD, title="Share page")
    browser_left, read_returned = threading.Event(), threading.Event()
    port = decision_port(repository)

    class ReadAfterTheBrowserLeft:
        def rows(self) -> tuple[rulings.Row, ...]:
            assert browser_left.wait(timeout=10)
            try:
                return port.rows()
            finally:
                read_returned.set()

        def rule_card(self, item: int, check: CardCheck) -> DecisionResult | CardChanged:
            return port.rule_card(item, check)

    with serving(ReadAfterTheBrowserLeft()) as board:
        board.send_and_reset(
            f"GET /api/board HTTP/1.1\r\nHost: x\r\nX-Board-Token: {board.token}\r\n\r\n".encode()
        )
        browser_left.set()
        # Past the read its handler thread surely exists, so the wait below joins it.
        assert read_returned.wait(timeout=10)
        _wait_for_request_handlers()

    entered = [call.operation for call in port.calls() if call.phase is CallPhase.ENTERED]
    assert entered == [PortOperation.ROWS]
    assert "Traceback" not in capsys.readouterr().err


def test_a_browser_leaving_during_a_held_ruling_still_rules_and_frees_the_turn(
    repository: BoardForge,
    board: BoardClient,
    port: RecordedPort,
    listed_items: Lister,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The browser resets its connection while its ruling waits inside the
    port: the ruling is written, no traceback is printed, and the next
    decision is answered."""
    repository.put_item(42, _OPEN_CARD, title="Share page")
    held = port.hold_next_rule_card(10)

    board.send_and_reset(
        _post(_decision_json(board)).replace(b"{token}", board.token.encode()),
        reset_when=held.entered,
    )
    held.release.set()
    _wait_for_request_handlers()
    repository.put_item(43, _OPEN_CARD, title="Next card")
    [next_card] = [item for item in listed_items(board) if item["number"] == 43]
    answered = board.decide_card_through_api(43, next_card["lines"], ["B"])

    assert [repository.stored_entries(item)[0].get("ruling") for item in (42, 43)] == ["A", "B"]
    assert answered.json() == {"status": "ruled", "message": None}
    assert "Traceback" not in capsys.readouterr().err


class _HugeLineSource:
    """One open line far larger than the socket buffers between board and client."""

    def __init__(self, small_row: rulings.Row) -> None:
        huge_lines = tuple(replace(line, text="x" * (32 * 1024 * 1024)) for line in small_row.lines)
        self._huge_row = replace(small_row, lines=huge_lines)

    def rows(self) -> tuple[rulings.Row, ...]:
        return (self._huge_row,)

    def rule_card(self, item: int, check: CardCheck) -> DecisionResult | CardChanged:
        raise AssertionError("listing the board must not write")


def test_a_browser_that_stops_reading_is_dropped_without_a_traceback(
    repository: BoardForge, capsys: pytest.CaptureFixture[str]
) -> None:
    repository.put_item(42, _OPEN_CARD, title="Share page")
    [small_row] = decision_port(repository).rows()
    with (
        serving(
            _HugeLineSource(small_row), request_deadline_seconds=_SHORT_DEADLINE_SECONDS
        ) as board,
        board.holding_unread(
            f"GET /api/board HTTP/1.1\r\nHost: x\r\nX-Board-Token: {board.token}\r\n\r\n".encode()
        ),
    ):
        # Connections are accepted in order, so this answer means the
        # unread one already holds a handler.
        board.send_raw(b"GET /elsewhere HTTP/1.1\r\nHost: x\r\n\r\n")
        _wait_for_request_handlers()

    assert "Traceback" not in capsys.readouterr().err


class _BrokenPipeSource:
    """A decision source whose own pipe breaks: a server defect, not a client leaving."""

    def rows(self) -> tuple[rulings.Row, ...]:
        raise BrokenPipeError("aco's pipe broke")

    def rule_card(self, item: int, check: CardCheck) -> DecisionResult | CardChanged:
        raise AssertionError("the board must not write after a failed read")


def test_a_broken_pipe_inside_the_board_still_prints_its_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with serving(_BrokenPipeSource()) as board:
        board.send_raw(
            f"GET /api/board HTTP/1.1\r\nHost: x\r\nX-Board-Token: {board.token}\r\n\r\n".encode()
        )
        _wait_for_request_handlers()

    assert "BrokenPipeError: aco's pipe broke" in capsys.readouterr().err


def _wait_for_request_handlers() -> None:
    # `socketserver.ThreadingMixIn` names every handler thread after its target.
    for thread in threading.enumerate():
        if thread.name.endswith("(process_request_thread)"):
            thread.join(timeout=10)


def test_the_board_listens_on_loopback_only(board: BoardClient) -> None:
    assert board.host == LOOPBACK_HOST


def test_loading_the_board_never_writes(
    repository: BoardForge, board: BoardClient, port: RecordedPort
) -> None:
    repository.put_item(42, _OPEN_CARD, title="Share page")

    board.get_board_json()
    board.get_board_json()

    _assert_never_written(port, repository)
