"""The board's JSON API served in-process against a fake `aco` on PATH.

Each test drives the real server, wire form, and `aco` adapter; only the
`aco` executable is a fake whose state and call log the test reads (issue
#631, specs/aco-board.spec.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

import pytest
from aco_board_fixtures import (
    BoardClient,
    FakeAcoRepository,
    Response,
    line,
    row,
    serving,
)

from aco_board.aco_cli import AcoCli
from aco_board.board import LINE_CHANGED
from aco_board.ports import NOTE_MAX_LENGTH

_ORIGIN_ELSEWHERE = {"Origin": "http://elsewhere.example"}


def _listed_items(board: BoardClient) -> list[dict[str, Any]]:
    response = board.get_board_json()
    assert response.status == 200
    return cast(list[dict[str, Any]], response.json()["items"])


def _decision_body(**overrides: object) -> str:
    fields = {"item": 42, "line": 1, "fingerprint": "any", "outcome": "yes", "note": None}
    return json.dumps({**fields, **overrides})


def _assert_guarded(response: Response) -> None:
    """The headers every answer carries, whatever its status."""
    policy = response.content_security_policy or ""
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    for directive in ("base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'"):
        assert directive in policy
    assert _cross_origin_headers(response) == []


def _cross_origin_headers(response: Response) -> list[str]:
    return [name for name in response.headers if name.lower().startswith("access-control-")]


@pytest.mark.parametrize(
    ("rows", "items"),
    [
        ((), []),
        (
            (
                row(
                    42,
                    "Share page",
                    line(
                        1,
                        "Guests?",
                        question="Gäste?",
                        example="Ja",
                        picture="<svg/>",
                        default="yes",
                    ),
                    line(2, "Hosts?", ruling="no"),
                ),
                row(7, "Login", line(1, "Remember me?")),
            ),
            [
                {
                    "number": 42,
                    "title": "Share page",
                    "lines": [
                        {
                            "index": 1,
                            "text": "Guests?",
                            "question": "Gäste?",
                            "example": "Ja",
                            "picture": "<svg/>",
                            "default": "yes",
                            "ruling": None,
                            "ruled_on": None,
                        },
                        {
                            "index": 2,
                            "text": "Hosts?",
                            "question": None,
                            "example": None,
                            "picture": None,
                            "default": None,
                            "ruling": "no",
                            "ruled_on": "2026-10-01",
                        },
                    ],
                },
                {
                    "number": 7,
                    "title": "Login",
                    "lines": [
                        {
                            "index": 1,
                            "text": "Remember me?",
                            "question": None,
                            "example": None,
                            "picture": None,
                            "default": None,
                            "ruling": None,
                            "ruled_on": None,
                        }
                    ],
                },
            ],
        ),
    ],
    ids=["nothing", "open-and-ruled-in-acos-order"],
)
def test_the_board_lists_every_line_under_its_item_in_acos_order(
    repository: FakeAcoRepository,
    board: BoardClient,
    rows: tuple[dict[str, object], ...],
    items: list[dict[str, object]],
) -> None:
    repository.set_rulings(*rows)

    listed = _listed_items(board)

    for item in listed:
        for listed_line in item["lines"]:
            assert isinstance(listed_line.pop("fingerprint"), str)
    assert listed == items
    assert repository.rule_calls() == []


@pytest.mark.parametrize("outcome", ["yes", "no", "later"])
def test_a_line_decided_as_listed_is_written_through_aco_rule(
    repository: FakeAcoRepository, board: BoardClient, outcome: str
) -> None:
    repository.set_rulings(row(42, "Share page", line(1, "Guests?", default="yes")))
    listed_line = _listed_items(board)[0]["lines"][0]

    answer = board.decide_through_api(listed_line, 42, outcome)

    assert answer.status == 200
    assert answer.json() == {"status": "ruled", "message": None}
    assert repository.rule_calls() == [["rule", "42", "--line", "1", f"--{outcome}", "--json"]]
    assert _listed_items(board)[0]["lines"][0]["ruling"] == outcome


@pytest.mark.parametrize(
    ("changed", "answer"),
    [
        (
            line(1, "Guests?", default="no"),
            {"status": "failed", "message": LINE_CHANGED},
        ),
        (
            line(1, "Guests?", ruling="no", default="yes"),
            {
                "status": "already_ruled",
                "message": "line 1 is already ruled; a changed ruling is a new line",
            },
        ),
    ],
    ids=["recommendation-changed", "ruled-elsewhere"],
)
def test_a_line_changed_since_listing_answers_why_without_writing(
    repository: FakeAcoRepository,
    board: BoardClient,
    changed: dict[str, object],
    answer: dict[str, object],
) -> None:
    repository.set_rulings(row(42, "Share page", line(1, "Guests?", default="yes")))
    listed_line = _listed_items(board)[0]["lines"][0]
    repository.set_rulings(row(42, "Share page", changed))
    stored_before = repository.rulings_state()

    response = board.decide_through_api(listed_line, 42, "yes")

    assert (response.status, response.json()) == (200, answer)
    assert repository.rulings_state() == stored_before


@pytest.mark.parametrize("presented", [None, "wrong", "ä" * 43], ids=["none", "wrong", "latin-1"])
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/board", None),
        ("GET", "/api/board?t={token}", None),
        ("POST", "/api/rule", _decision_body()),
        ("POST", "/api/rule", "not json"),
        ("GET", "/api/elsewhere", None),
        ("PUT", "/api/rule", _decision_body()),
        ("DELETE", "/api/board", None),
        ("PATCH", "/api/rule", _decision_body()),
        ("OPTIONS", "/api/board", None),
        ("BREW", "/api/board", None),
    ],
    ids=[
        "board",
        "board-query-token",
        "rule",
        "rule-malformed",
        "unknown-route",
        "put",
        "delete",
        "patch",
        "options",
        "unknown-method",
    ],
)
def test_an_api_request_without_the_header_token_is_refused_before_any_aco_call(
    repository: FakeAcoRepository,
    board: BoardClient,
    presented: str | None,
    method: str,
    path: str,
    body: str | None,
) -> None:
    repository.set_rulings(row(42, "Share page", line(1, "Guests?")))

    response = board.call_api(method, path.format(token=board.token), body, presented=presented)

    assert response.status == 403
    assert response.json() == {"error": "forbidden: missing or wrong token"}
    assert repository.calls() == []


@pytest.mark.parametrize(
    ("body", "headers", "error"),
    [
        ("not json", {}, "bad request: decision"),
        (_decision_body(outcome="maybe"), {}, "bad request: decision"),
        (_decision_body(line=0), {}, "bad request: decision"),
        (_decision_body(note="x" * (NOTE_MAX_LENGTH + 1)), {}, "bad request: decision"),
        ("{}", {"Content-Length": "abc"}, "bad request: Content-Length"),
    ],
    ids=["not-json", "outcome-unknown", "line-zero", "note-too-long", "content-length"],
)
def test_a_malformed_api_decision_is_refused_with_an_error_envelope_without_aco(
    repository: FakeAcoRepository,
    board: BoardClient,
    body: str,
    headers: dict[str, str],
    error: str,
) -> None:
    response = board.call_api("POST", "/api/rule", body, presented=board.token, headers=headers)

    assert (response.status, response.json()) == (400, {"error": error})
    assert repository.calls() == []


def test_a_repeated_token_header_is_refused_even_when_both_carry_the_token(
    repository: FakeAcoRepository, board: BoardClient
) -> None:
    token_header = b"X-Board-Token: " + board.token.encode() + b"\r\n"
    answer = board.send_raw(b"GET /api/board HTTP/1.1\r\nHost: x\r\n" + token_header * 2 + b"\r\n")

    response = Response.from_raw(answer)
    assert (response.status, response.json()) == (
        403,
        {"error": "forbidden: missing or wrong token"},
    )
    assert repository.calls() == []


_NOT_FOUND = (404, {"error": "not found"})
_METHOD_NOT_ALLOWED = (405, {"error": "method not allowed"})


@pytest.mark.parametrize(
    ("method", "path", "answer"),
    [
        ("GET", "/api/elsewhere", _NOT_FOUND),
        ("GET", "/api/rule", _NOT_FOUND),
        ("POST", "/api/board", _NOT_FOUND),
        ("PUT", "/api/rule", _METHOD_NOT_ALLOWED),
        ("DELETE", "/api/board", _METHOD_NOT_ALLOWED),
        ("OPTIONS", "/api/elsewhere", _METHOD_NOT_ALLOWED),
    ],
    ids=["unknown", "rule-by-get", "board-by-post", "put", "delete", "options"],
)
def test_an_api_request_outside_its_routes_answers_why_as_json(
    repository: FakeAcoRepository,
    board: BoardClient,
    method: str,
    path: str,
    answer: tuple[int, dict[str, str]],
) -> None:
    response = board.call_api(method, path, presented=board.token)

    assert (response.status, response.json()) == answer
    assert repository.calls() == []


_BODY_LENGTH = 40


def _send_part_and_stall(board: BoardClient, head: bytes) -> bytes:
    return board.send_unfinished(head + b'{"item": 42}')


def _drip_slower_than_the_deadline(board: BoardClient, head: bytes) -> bytes:
    # Forty bytes a twentieth of a second apart take two seconds, ten times
    # the deadline, while no single pause comes near it.
    return board.send_dripping(head, b"x" * _BODY_LENGTH, interval_seconds=0.05)


@pytest.mark.parametrize(
    "send_body",
    [_send_part_and_stall, _drip_slower_than_the_deadline],
    ids=["stalled", "dripping"],
)
def test_an_api_body_not_complete_by_the_deadline_answers_408_as_json(
    repository: FakeAcoRepository, send_body: Callable[[BoardClient, bytes], bytes]
) -> None:
    with serving(AcoCli(directory=repository.directory), request_deadline_seconds=0.2) as board:
        answer = send_body(
            board,
            b"POST /api/rule HTTP/1.1\r\nHost: x\r\nX-Board-Token: "
            + board.token.encode()
            + f"\r\nContent-Length: {_BODY_LENGTH}\r\n\r\n".encode(),
        )

    response = Response.from_raw(answer)
    assert (response.status, response.json()) == (
        408,
        {"error": "request timeout: body incomplete"},
    )
    _assert_guarded(response)
    assert repository.calls() == []


def _fail_rulings(repository: FakeAcoRepository) -> None:
    repository.fail_rulings("ERROR: no forge adapter for host")


def _answer_rulings_unreadably(repository: FakeAcoRepository) -> None:
    repository.answer_rulings_with('{"ok": true, "rulings": {}}')


def _hang_rulings(repository: FakeAcoRepository) -> None:
    repository.delay("rulings", 30)


@pytest.mark.parametrize(
    ("break_aco", "timeout_seconds", "error"),
    [
        (_fail_rulings, 120.0, "aco rulings failed: ERROR: no forge adapter for host"),
        (
            _answer_rulings_unreadably,
            120.0,
            "aco rulings --json is unreadable: rulings is not a list",
        ),
        (_hang_rulings, 1.0, "aco rulings did not answer within 1 seconds"),
    ],
    ids=["aco-fails", "aco-unreadable", "aco-hangs"],
)
def test_an_unavailable_aco_answers_502_with_its_reason(
    repository: FakeAcoRepository,
    break_aco: Callable[[FakeAcoRepository], None],
    timeout_seconds: float,
    error: str,
) -> None:
    break_aco(repository)
    decisions = AcoCli(directory=repository.directory, timeout_seconds=timeout_seconds)

    with serving(decisions) as board:
        response = board.get_board_json()

    assert (response.status, response.json()) == (502, {"error": error})
    assert response.headers["Content-Type"] == "application/json"
    _assert_guarded(response)


@pytest.mark.parametrize(
    ("method", "path", "body", "presented_own_token", "status", "content_type"),
    [
        ("GET", "/api/board", None, True, 200, "application/json"),
        ("POST", "/api/rule", _decision_body(item=7), True, 200, "application/json"),
        ("GET", "/api/board", None, False, 403, "application/json"),
        ("POST", "/api/rule", "not json", True, 400, "application/json"),
        ("GET", "/api/elsewhere", None, True, 404, "application/json"),
        ("OPTIONS", "/api/rule", None, False, 403, "application/json"),
        ("PUT", "/api/rule", _decision_body(), False, 403, "application/json"),
        ("PUT", "/api/rule", _decision_body(), True, 405, "application/json"),
        ("HEAD", "/api/board", None, False, 403, "application/json"),
        ("HEAD", "/api/board", None, True, 405, "application/json"),
        ("GET", "/?t={token}", None, False, 200, "text/html; charset=utf-8"),
        ("GET", "/", None, False, 403, "text/plain; charset=utf-8"),
        ("PUT", "/", None, False, 405, "text/plain; charset=utf-8"),
    ],
    ids=[
        "api-board",
        "api-rule",
        "api-forbidden",
        "api-bad-request",
        "api-not-found",
        "api-options-forbidden",
        "api-put-forbidden",
        "api-put-not-allowed",
        "api-head-forbidden",
        "api-head-not-allowed",
        "legacy-page",
        "legacy-forbidden",
        "legacy-put-not-allowed",
    ],
)
def test_every_answer_is_uncached_unreferred_framed_by_none_and_never_cross_origin(
    board: BoardClient,
    method: str,
    path: str,
    body: str | None,
    presented_own_token: bool,
    status: int,
    content_type: str,
) -> None:
    presented = board.token if presented_own_token else None
    response = board.call_api(
        method, path.format(token=board.token), body, presented=presented, headers=_ORIGIN_ELSEWHERE
    )

    assert response.status == status
    assert response.headers["Content-Type"] == content_type
    _assert_guarded(response)


@pytest.mark.parametrize(
    ("request_bytes", "status"),
    [
        (b"GET /api/board HTTP/9.9\r\nHost: x\r\n\r\n", 505),
        (b"GET /api/board HTTP/1.1 extra\r\nHost: x\r\n\r\n", 400),
        (b"GET /api/board HTTP/1.1\r\n" + b"X: y\r\n" * 101 + b"\r\n", 431),
        (b"GET /" + b"a" * 65537 + b" HTTP/1.1\r\n\r\n", 414),
    ],
    ids=["version-unsupported", "request-line-malformed", "too-many-headers", "line-too-long"],
)
def test_a_request_the_http_layer_cannot_parse_is_refused_with_every_guard_header(
    repository: FakeAcoRepository, board: BoardClient, request_bytes: bytes, status: int
) -> None:
    response = Response.from_raw(board.send_raw(request_bytes))

    assert response.status == status
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    _assert_guarded(response)
    assert repository.calls() == []


def test_a_head_request_answers_with_headers_only(board: BoardClient) -> None:
    response = Response.from_raw(board.send_raw(b"HEAD /api/board HTTP/1.1\r\nHost: x\r\n\r\n"))

    assert (response.status, response.body) == (403, "")


def test_a_cross_origin_preflight_is_granted_nothing(
    repository: FakeAcoRepository, board: BoardClient
) -> None:
    preflight = {
        **_ORIGIN_ELSEWHERE,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-board-token",
    }

    response = board.call_api("OPTIONS", "/api/rule", presented=None, headers=preflight)

    assert response.status >= 400
    assert _cross_origin_headers(response) == []
    assert repository.calls() == []
