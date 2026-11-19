"""The board's request line, driven through the real server: every answered request
writes one `request.ended` (ABRD-180, ABRD-181), no line holds a secret, a path or a
header value (ABRD-182), an exception writes its one failure line under the request's
trace (ABRD-183) and a browser that leaves mid-answer writes none (ABRD-184)."""

import threading
from collections.abc import Callable

import pytest
from aco_board_fixtures import (
    BoardClient,
    CallPhase,
    LoggedLines,
    PortOperation,
    decision_port,
    serving,
    wait_for_request_handlers,
)
from board_forge import BoardForge, item_body
from option_cards import open_option_entry

from aco import inbox, item_step
from aco.board.ports import CardChanged, CardCheck, DecisionResult, StepCheck
from aco.board.server import LOOPBACK_HOST

_REQUEST_EVENT = "request.ended"
_FAILURE_EVENT = "request_handling.failed"
_HEADERS = b" HTTP/1.1\r\nHost: x\r\n"
_TOKEN_HEADER = b"X-Board-Token: {token}\r\n"


def _with_token(path: bytes, method: bytes = b"GET") -> bytes:
    return method + b" " + path + _HEADERS + _TOKEN_HEADER + b"\r\n"


def _without_token(path: bytes, method: bytes = b"GET") -> bytes:
    return method + b" " + path + _HEADERS + b"\r\n"


def _post(body: bytes, declared_length: int) -> bytes:
    head = b"POST /api/rule" + _HEADERS + _TOKEN_HEADER
    return head + b"Content-Length: " + str(declared_length).encode() + b"\r\n\r\n" + body


def _a_forge_that_cannot_list(repository: BoardForge) -> None:
    repository.fail_listing("no forge adapter for host")


@pytest.mark.parametrize(
    ("request_template", "expected", "arrange"),
    [
        pytest.param(_without_token(b"/"), ("GET", "/", 200, "ok"), None, id="page"),
        pytest.param(
            _without_token(b"/assets/index.js"), ("GET", "/assets/", 200, "ok"), None, id="asset"
        ),
        pytest.param(
            _without_token(b"/assets/missing.js"),
            ("GET", "/assets/", 404, "ok"),
            None,
            id="missing-asset",
        ),
        pytest.param(
            _with_token(b"/api/board"), ("GET", "/api/board", 200, "ok"), None, id="board-read"
        ),
        pytest.param(
            _without_token(b"/api/board"),
            ("GET", "/api/board", 403, "ok"),
            None,
            id="board-without-token",
        ),
        pytest.param(
            _with_token(b"/api/rule"), ("GET", "/api/rule", 404, "ok"), None, id="read-of-a-post"
        ),
        pytest.param(
            _with_token(b"/api/elsewhere"), ("GET", None, 404, "ok"), None, id="unknown-api-path"
        ),
        pytest.param(_without_token(b"/elsewhere"), ("GET", None, 404, "ok"), None, id="unknown"),
        pytest.param(
            _with_token(b"/api/rule", b"PUT"),
            ("PUT", "/api/rule", 405, "ok"),
            None,
            id="wrong-method-on-api",
        ),
        pytest.param(
            _without_token(b"/", b"DELETE"), ("DELETE", "/", 405, "ok"), None, id="wrong-method"
        ),
        pytest.param(
            _without_token(b"/", b"BREW"), ("_OTHER", "/", 405, "ok"), None, id="unknown-method"
        ),
        pytest.param(
            _post(b"{}", 2), ("POST", "/api/rule", 400, "ok"), None, id="bad-decision-body"
        ),
        pytest.param(
            _post(b'{"item": 42}', 40), ("POST", "/api/rule", 408, "ok"), None, id="short-body"
        ),
        pytest.param(b"GARBAGE\r\n\r\n", ("_OTHER", None, 400, "ok"), None, id="malformed-line"),
        pytest.param(
            b"GET http://[{token}]/ HTTP/1.1\r\nHost: x\r\n\r\n",
            ("GET", None, 400, "ok"),
            None,
            id="malformed-absolute-target",
        ),
        pytest.param(
            b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\n\r\n",
            ("_OTHER", None, 414, "ok"),
            None,
            id="oversized-line",
        ),
        pytest.param(
            b"GET / HTTP/2.0\r\n\r\n", ("_OTHER", None, 505, "failed"), None, id="http-version"
        ),
        pytest.param(
            _with_token(b"/api/board"),
            ("GET", "/api/board", 502, "failed"),
            _a_forge_that_cannot_list,
            id="board-unreadable",
        ),
    ],
)
def test_every_answered_request_writes_one_request_line_with_its_outcome_status_and_route(
    repository: BoardForge,
    board: BoardClient,
    logged: LoggedLines,
    request_template: bytes,
    expected: tuple[str, str | None, int, str],
    arrange: Callable[[BoardForge], None] | None,
) -> None:
    if arrange is not None:
        arrange(repository)

    board.send_raw(request_template.replace(b"{token}", board.token.encode()))
    wait_for_request_handlers()

    [record] = logged.records()
    assert record["event"] == _REQUEST_EVENT
    assert (record["method"], record["route"], record["status"], record["outcome"]) == expected
    assert (record["service"], record["sub"], record["ip"]) == ("aco-board", None, LOOPBACK_HOST)
    assert record["duration_ms"] >= 0


def test_a_connection_closed_before_a_request_line_writes_nothing(
    board: BoardClient, logged: LoggedLines
) -> None:
    board.send_raw(b"")
    wait_for_request_handlers()

    assert logged.records() == []


def test_no_line_holds_the_token_a_path_a_query_or_a_header_value(
    board: BoardClient, logged: LoggedLines, capsys: pytest.CaptureFixture[str]
) -> None:
    secret_marker = b"marker-4f2a9"
    requests = [
        b"GET /api/board?t={token}&q=" + secret_marker + _HEADERS + _TOKEN_HEADER + b"\r\n",
        b"GET /" + secret_marker + _HEADERS + b"X-Other: " + secret_marker + b"\r\n\r\n",
        b"GET /" + _HEADERS + b"traceparent: not-a-traceparent-" + secret_marker + b"\r\n\r\n",
        b"GET /"
        + _HEADERS
        + b"traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01\r\n"
        + b"tracestate: vendor="
        + secret_marker
        + b"\r\n\r\n",
        b"GET /"
        + _HEADERS
        + b"traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01\r\n"
        + b"tracestate: "
        + secret_marker
        + b"\r\n\r\n",
        b"GET http://[{token}]/ HTTP/1.1\r\nHost: x\r\n\r\n",
        b"GET http://[" + secret_marker + b"]/ HTTP/1.1\r\nHost: x\r\n\r\n",
    ]

    for request in requests:
        board.send_raw(request.replace(b"{token}", board.token.encode()))
    wait_for_request_handlers()

    written = logged.text() + capsys.readouterr().err
    assert len(logged.with_event(_REQUEST_EVENT)) == len(requests)
    assert [secret_marker.decode() in written, board.token in written] == [False, False]
    assert "0af7651916cd43dd8448eb211c80319c" in written


class _FailingSource:
    """A decision source that fails the board's read with `error`."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def reading(self) -> inbox.Reading:
        raise self._error

    def rule_card(self, item: int, check: CardCheck) -> DecisionResult | CardChanged:
        raise AssertionError("the board must not write after a failed read")

    def answer_step(
        self, item: int, result: item_step.StepResult, check: StepCheck
    ) -> DecisionResult | CardChanged:
        raise AssertionError("the board must not write after a failed read")


@pytest.mark.parametrize(
    "error",
    [RuntimeError("the source broke"), BrokenPipeError("aco's pipe broke")],
    ids=["runtime-error", "broken-pipe-inside-the-board"],
)
def test_an_unexpected_exception_writes_a_failed_request_line_then_one_failure_line_in_its_trace(
    logged: LoggedLines, capsys: pytest.CaptureFixture[str], error: Exception
) -> None:
    with serving(_FailingSource(error)) as board:
        board.send_raw(_with_token(b"/api/board").replace(b"{token}", board.token.encode()))
        wait_for_request_handlers()

    [request_line, failure_line] = logged.records()
    assert (request_line["event"], request_line["outcome"], request_line["status"]) == (
        _REQUEST_EVENT,
        "failed",
        500,
    )
    assert failure_line["event"] == _FAILURE_EVENT
    assert failure_line["error_type"] == type(error).__name__
    assert failure_line["exception"].endswith(f"{type(error).__name__}: {error}")
    assert failure_line["trace_id"] == request_line["trace_id"]
    assert request_line["trace_id"] is not None
    assert capsys.readouterr().err == ""


def test_a_browser_leaving_mid_answer_reads_ok_with_the_status_sent_and_writes_no_failure_line(
    repository: BoardForge, logged: LoggedLines
) -> None:
    repository.put_item(42, item_body(open_option_entry()), title="Share page")
    browser_left, read_returned = threading.Event(), threading.Event()
    port = decision_port(repository)

    class ReadAfterTheBrowserLeft:
        def reading(self) -> inbox.Reading:
            assert browser_left.wait(timeout=10)
            try:
                return port.reading()
            finally:
                read_returned.set()

        def rule_card(self, item: int, check: CardCheck) -> DecisionResult | CardChanged:
            return port.rule_card(item, check)

        def answer_step(
            self, item: int, result: item_step.StepResult, check: StepCheck
        ) -> DecisionResult | CardChanged:
            return port.answer_step(item, result, check)

    with serving(ReadAfterTheBrowserLeft()) as board:
        board.send_and_reset(_with_token(b"/api/board").replace(b"{token}", board.token.encode()))
        browser_left.set()
        # Past the read its handler thread surely exists, so the wait below joins it.
        assert read_returned.wait(timeout=10)
        wait_for_request_handlers()

    entered = [call.operation for call in port.calls() if call.phase is CallPhase.ENTERED]
    assert entered == [PortOperation.READING]
    [request_line] = logged.records()
    assert (request_line["outcome"], request_line["status"]) == ("ok", 200)
