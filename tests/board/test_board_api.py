"""The board's JSON API served in-process against the real `aco` over a fake forge.

Each test drives the real server, wire form, `aco` adapter and `aco`
itself; only the forge is a fake whose items and request log the test
reads, beside the calls at the board's port (specs/serve.spec.md).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
from aco_board_fixtures import (
    DEFAULT_LABEL,
    BoardClient,
    Lister,
    RecordedPort,
    Response,
    assert_guarded,
    cross_origin_headers,
    decision_port,
    rulings_lines,
    serving,
    serving_two,
)
from board_forge import BoardForge, item_body
from option_cards import open_option_entry

_ORIGIN_ELSEWHERE = {"Origin": "http://elsewhere.example"}
_OPEN_CARD = item_body(open_option_entry())


def _card_body(**overrides: object) -> str:
    fields = {
        "repo": DEFAULT_LABEL,
        "item": 42,
        "lines": [{"line": 1, "fingerprint": "any", "option": "A"}],
    }
    return json.dumps({**fields, **overrides})


def _ruled_yes_no(text: str, ruling: str, **card: str) -> dict[str, object]:
    return {"text": text, "ruling": ruling, "ruled_on": date(2026, 10, 1), **card}


def _assert_no_call(port: RecordedPort, repository: BoardForge) -> None:
    """Nothing reached the board's port, and the forge saw no request."""
    assert (port.calls(), repository.request_log()) == ((), ())


def test_the_board_lists_every_ruled_yes_no_line_under_its_item_in_acos_order(
    repository: BoardForge, board: BoardClient, port: RecordedPort, listed_items: Lister
) -> None:
    """ABRD-34, E-ABRD-03: each line is `aco rulings --json`'s line, with no
    `default`, no unset card key and no fingerprint."""
    guests = _ruled_yes_no("Guests?", "yes", question="Gäste?", example="Ja", picture="<svg/>")
    hosts = _ruled_yes_no("Hosts?", "no")
    repository.put_item(42, item_body(guests, hosts), title="Share page")
    repository.put_item(7, item_body(_ruled_yes_no("Remember me?", "later")), title="Login")

    listed = listed_items(board)

    assert listed == [
        {"number": 42, "title": "Share page", "lines": rulings_lines(repository, 42)},
        {"number": 7, "title": "Login", "lines": rulings_lines(repository, 7)},
    ]
    assert [len(item["lines"]) for item in listed] == [2, 1]
    assert all("fingerprint" not in line for item in listed for line in item["lines"])
    assert port.ruled_items() == []


def _make_a_file(directory: Path) -> None:
    shutil.rmtree(directory)
    directory.write_text("", encoding="utf-8")


def _make_unenterable(directory: Path) -> None:
    directory.chmod(0o000)


@pytest.mark.parametrize(
    "break_directory",
    [_make_a_file, _make_unenterable],
    ids=["directory-is-a-file", "directory-not-enterable"],
)
def test_a_repo_whose_directory_cannot_be_entered_carries_its_error_and_the_others_keep_theirs(
    two_repositories: tuple[BoardForge, BoardForge], break_directory: Callable[[Path], None]
) -> None:
    """ABRD-15; the sentence is aco's own failure to read that checkout."""
    repository_a, repository_b = two_repositories
    repository_a.put_item(42, _OPEN_CARD, title="Share page")
    break_directory(repository_b.directory)

    try:
        with serving_two(two_repositories) as board:
            response = board.get_board_json()
    finally:
        repository_b.directory.chmod(0o755)

    assert response.status == 200
    repos = cast(list[dict[str, Any]], response.json()["repos"])
    assert [repo["name"] for repo in repos] == ["a", "b"]
    assert repos[0]["error"] is None
    assert repos[1]["error"]
    assert [item["number"] for item in repos[0]["items"]] == [42]
    assert repos[1]["items"] == []


@pytest.mark.parametrize("presented", [None, "wrong", "ä" * 43], ids=["none", "wrong", "latin-1"])
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/board", None),
        ("GET", "/api/board?t={token}", None),
        ("POST", "/api/rule", _card_body()),
        ("POST", "/api/rule", "not json"),
        ("GET", "/api/elsewhere", None),
        ("PUT", "/api/rule", _card_body()),
        ("DELETE", "/api/board", None),
        ("PATCH", "/api/rule", _card_body()),
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
    repository: BoardForge,
    port: RecordedPort,
    board: BoardClient,
    presented: str | None,
    method: str,
    path: str,
    body: str | None,
) -> None:
    repository.put_item(42, _OPEN_CARD, title="Share page")

    response = board.call_api(method, path.format(token=board.token), body, presented=presented)

    assert response.status == 403
    assert response.json() == {"error": "forbidden: missing or wrong token"}
    _assert_no_call(port, repository)


@pytest.mark.parametrize(
    ("body", "headers", "error"),
    [
        ("not json", {}, "bad request: decision"),
        ("[1, 2, 3]", {}, "bad request: decision"),
        ("{}", {}, "bad request: decision"),
        (_card_body(), {"Content-Length": "abc"}, "bad request: Content-Length"),
    ],
    ids=[
        "not-json",
        "json-not-an-object",
        "empty-object",
        "content-length",
    ],
)
def test_a_malformed_api_decision_is_refused_with_an_error_envelope_without_aco(
    repository: BoardForge,
    port: RecordedPort,
    board: BoardClient,
    body: str,
    headers: dict[str, str],
    error: str,
) -> None:
    response = board.call_api("POST", "/api/rule", body, presented=board.token, headers=headers)

    assert (response.status, response.json()) == (400, {"error": error})
    _assert_no_call(port, repository)


def test_a_repeated_token_header_is_refused_even_when_both_carry_the_token(
    repository: BoardForge, board: BoardClient, port: RecordedPort
) -> None:
    token_header = b"X-Board-Token: " + board.token.encode() + b"\r\n"
    answer = board.send_raw(b"GET /api/board HTTP/1.1\r\nHost: x\r\n" + token_header * 2 + b"\r\n")

    response = Response.from_raw(answer)
    assert (response.status, response.json()) == (
        403,
        {"error": "forbidden: missing or wrong token"},
    )
    _assert_no_call(port, repository)


_NOT_FOUND = (404, {"error": "not found"})
_METHOD_NOT_ALLOWED = (405, {"error": "method not allowed"})


@pytest.mark.parametrize(
    ("method", "path", "expected", "allow"),
    [
        ("GET", "/api/elsewhere", _NOT_FOUND, None),
        ("GET", "/api/rule", _NOT_FOUND, None),
        ("POST", "/api/board", _NOT_FOUND, None),
        ("PUT", "/api/rule", _METHOD_NOT_ALLOWED, "POST"),
        ("DELETE", "/api/board", _METHOD_NOT_ALLOWED, "GET"),
        ("OPTIONS", "/api/elsewhere", _METHOD_NOT_ALLOWED, "GET, POST"),
    ],
    ids=["unknown", "rule-by-get", "board-by-post", "put", "delete", "options"],
)
def test_an_api_request_outside_its_routes_answers_why_as_json(
    repository: BoardForge,
    port: RecordedPort,
    board: BoardClient,
    method: str,
    path: str,
    expected: tuple[int, dict[str, str]],
    allow: str | None,
) -> None:
    status, body = expected
    response = board.call_api(method, path, presented=board.token)

    assert response.status == status
    assert response.json() == body
    assert response.headers.get("Allow") == allow
    _assert_no_call(port, repository)


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
    repository: BoardForge, send_body: Callable[[BoardClient, bytes], bytes]
) -> None:
    port = decision_port(repository)
    with serving(port, request_deadline_seconds=0.2) as board:
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
    assert_guarded(response)
    _assert_no_call(port, repository)


def test_a_forge_that_cannot_list_answers_502_with_acos_reason(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-20."""
    repository.fail_listing("no forge adapter for host")

    response = board.get_board_json()

    assert response.status == 502
    assert response.json() == {
        "repos": [
            {
                "name": DEFAULT_LABEL,
                "error": "no forge adapter for host",
                "items": [],
            }
        ]
    }
    assert response.headers["Content-Type"] == "application/json"
    assert_guarded(response)


def test_the_board_lists_every_configured_repo_in_order_200_on_partial_failure(
    two_repositories: tuple[BoardForge, BoardForge],
) -> None:
    """ABRD-15."""
    repository_a, repository_b = two_repositories
    repository_a.put_item(42, _OPEN_CARD, title="Share page")
    repository_b.fail_listing("no forge adapter for host")

    with serving_two(two_repositories) as board:
        response = board.get_board_json()

    assert response.status == 200
    payload = response.json()
    repos = cast(list[dict[str, Any]], payload["repos"])
    assert [repo["name"] for repo in repos] == ["a", "b"]
    assert repos[0]["error"] is None
    [item] = repos[0]["items"]
    assert (item["number"], [listed["index"] for listed in item["lines"]]) == (42, [1])
    assert repos[1] == {
        "name": "b",
        "error": "no forge adapter for host",
        "items": [],
    }


def test_the_board_answers_502_only_once_every_configured_repo_has_failed(
    two_repositories: tuple[BoardForge, BoardForge],
) -> None:
    repository_a, repository_b = two_repositories
    repository_a.fail_listing("a is down")
    repository_b.fail_listing("b is down")

    with serving_two(two_repositories) as board:
        response = board.get_board_json()

    assert response.status == 502
    assert response.json() == {
        "repos": [
            {"name": "a", "error": "a is down", "items": []},
            {"name": "b", "error": "b is down", "items": []},
        ]
    }


@pytest.mark.parametrize(
    ("method", "path", "body", "presented_own_token", "status", "content_type", "allow"),
    [
        ("GET", "/api/board", None, True, 200, "application/json", None),
        ("POST", "/api/rule", _card_body(item=7), True, 200, "application/json", None),
        ("GET", "/api/board", None, False, 403, "application/json", None),
        ("POST", "/api/rule", "not json", True, 400, "application/json", None),
        ("GET", "/api/elsewhere", None, True, 404, "application/json", None),
        ("OPTIONS", "/api/rule", None, False, 403, "application/json", None),
        ("PUT", "/api/rule", _card_body(), False, 403, "application/json", None),
        ("PUT", "/api/rule", _card_body(), True, 405, "application/json", "POST"),
        ("HEAD", "/api/board", None, False, 403, "application/json", None),
        ("HEAD", "/api/board", None, True, 405, "application/json", "GET"),
        ("GET", "/", None, False, 200, "text/html; charset=utf-8", None),
        ("GET", "/assets/index.js", None, False, 200, "text/javascript; charset=utf-8", None),
        ("PUT", "/", None, False, 405, "text/plain; charset=utf-8", "GET"),
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
        "shell-needs-no-token",
        "asset-needs-no-token",
        "shell-put-not-allowed",
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
    allow: str | None,
) -> None:
    presented = board.token if presented_own_token else None
    response = board.call_api(
        method, path.format(token=board.token), body, presented=presented, headers=_ORIGIN_ELSEWHERE
    )

    assert response.status == status
    assert response.headers["Content-Type"] == content_type
    assert response.headers.get("Allow") == allow
    assert_guarded(response)


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
    repository: BoardForge,
    board: BoardClient,
    port: RecordedPort,
    request_bytes: bytes,
    status: int,
) -> None:
    response = Response.from_raw(board.send_raw(request_bytes))

    assert response.status == status
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert_guarded(response)
    _assert_no_call(port, repository)


def test_a_head_request_answers_with_headers_only(board: BoardClient) -> None:
    response = Response.from_raw(board.send_raw(b"HEAD /api/board HTTP/1.1\r\nHost: x\r\n\r\n"))

    assert (response.status, response.body) == (403, "")


def test_a_cross_origin_preflight_is_granted_nothing(
    repository: BoardForge, board: BoardClient, port: RecordedPort
) -> None:
    preflight = {
        **_ORIGIN_ELSEWHERE,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-board-token",
    }

    response = board.call_api("OPTIONS", "/api/rule", presented=None, headers=preflight)

    assert response.status >= 400
    assert cross_origin_headers(response) == []
    _assert_no_call(port, repository)
