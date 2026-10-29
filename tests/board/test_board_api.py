"""The board's JSON API served in-process against a fake `aco` on PATH.

Each test drives the real server, wire form, and `aco` adapter; only the
`aco` executable is a fake whose state and call log the test reads
(specs/serve.spec.md).
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from aco_board_fixtures import (
    DEFAULT_LABEL,
    BoardClient,
    FakeAcoRepository,
    Lister,
    Response,
    install_fake_aco,
    line,
    option_line,
    row,
    serving,
    serving_two,
)

from aco.board.aco_cli import AcoCli
from aco.board.ports import (
    CardDecision,
    CardLine,
    DecisionResult,
    DecisionSourceUnavailableError,
    DecisionStatus,
)

_ORIGIN_ELSEWHERE = {"Origin": "http://elsewhere.example"}


def _card_body(**overrides: object) -> str:
    fields = {
        "repo": DEFAULT_LABEL,
        "item": 42,
        "lines": [{"line": 1, "fingerprint": "any", "option": "A"}],
    }
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


def _listed_line(index: int, text: str, ruling: str, **shown: str) -> dict[str, object]:
    """A ruled yes/no line as the board lists it, without its fingerprint."""
    absent = {"question": None, "example": None, "picture": None}
    return {"index": index, "text": text, **absent, **shown, "ruling": ruling, "ruled_on": "2026-10-01"}


def test_the_board_lists_every_ruled_yes_no_line_under_its_item_in_acos_order(
    repository: FakeAcoRepository, board: BoardClient, listed_items: Lister
) -> None:
    """ABRD-34, E-ABRD-03: no `default` on the wire."""
    repository.set_rulings(
        row(
            42,
            "Share page",
            line(1, "Guests?", ruling="yes", question="Gäste?", example="Ja", picture="<svg/>"),
            line(2, "Hosts?", ruling="no"),
        ),
        row(7, "Login", line(1, "Remember me?", ruling="later")),
    )

    listed = listed_items(board)

    for item in listed:
        for listed_line in item["lines"]:
            assert isinstance(listed_line.pop("fingerprint"), str)
    assert listed == [
        {
            "number": 42,
            "title": "Share page",
            "lines": [
                _listed_line(1, "Guests?", "yes", question="Gäste?", example="Ja", picture="<svg/>"),
                _listed_line(2, "Hosts?", "no"),
            ],
        },
        {"number": 7, "title": "Login", "lines": [_listed_line(1, "Remember me?", "later")]},
    ]
    assert repository.rule_calls() == []


def _aco_without_execute_permission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_directory = tmp_path / "bin-without-execute"
    bin_directory.mkdir()
    (bin_directory / "aco").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(bin_directory))
    return tmp_path


def _working_directory_that_is_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    install_fake_aco(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    file_instead_of_directory = tmp_path / "repository"
    file_instead_of_directory.write_text("", encoding="utf-8")
    return file_instead_of_directory


def _aco_answering_bytes_that_are_not_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_directory = tmp_path / "bin-not-utf8"
    bin_directory.mkdir()
    executable = bin_directory / "aco"
    executable.write_text("#!/bin/sh\nprintf '\\377\\376'\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_directory}{os.pathsep}{os.environ['PATH']}")
    return tmp_path


_ACO_CANNOT_BE_RUN = pytest.mark.parametrize(
    ("arrange", "reason"),
    [
        (_aco_without_execute_permission, "could not be run: Permission denied"),
        (_working_directory_that_is_a_file, "could not be run: Not a directory"),
        (_aco_answering_bytes_that_are_not_utf8, "answered output that is not UTF-8"),
    ],
    ids=["no-execute-permission", "working-directory-is-a-file", "output-not-utf8"],
)


@_ACO_CANNOT_BE_RUN
def test_an_aco_that_cannot_be_run_makes_the_rulings_read_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arrange: Callable[[Path, pytest.MonkeyPatch], Path],
    reason: str,
) -> None:
    decisions = AcoCli(directory=arrange(tmp_path, monkeypatch))

    with pytest.raises(DecisionSourceUnavailableError) as unavailable:
        decisions.expectation_lines()

    assert str(unavailable.value) == f"aco rulings {reason}"


@_ACO_CANNOT_BE_RUN
def test_an_aco_that_cannot_be_run_fails_the_card_with_one_sentence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arrange: Callable[[Path, pytest.MonkeyPatch], Path],
    reason: str,
) -> None:
    decisions = AcoCli(directory=arrange(tmp_path, monkeypatch))
    card_hash = cast(str, option_line()["card_hash"])
    decision = CardDecision(42, (CardLine(1, card_hash, "A"),), None)

    result = decisions.rule_card(decision)

    assert result == DecisionResult(DecisionStatus.FAILED, f"aco rule {reason}")


def _make_a_file(directory: Path) -> None:
    shutil.rmtree(directory)
    directory.write_text("", encoding="utf-8")


def _make_unenterable(directory: Path) -> None:
    directory.chmod(0o000)


@pytest.mark.parametrize(
    ("break_directory", "error"),
    [
        (_make_a_file, "aco rulings could not be run: Not a directory"),
        (_make_unenterable, "aco rulings could not be run: Permission denied"),
    ],
    ids=["directory-is-a-file", "directory-not-enterable"],
)
def test_a_repo_whose_directory_cannot_be_entered_carries_its_error_and_the_others_keep_theirs(
    two_repositories: tuple[FakeAcoRepository, FakeAcoRepository],
    break_directory: Callable[[Path], None],
    error: str,
) -> None:
    repository_a, repository_b = two_repositories
    repository_a.set_rulings(row(42, "Share page", option_line()))
    break_directory(repository_b.directory)

    try:
        with serving_two(two_repositories) as board:
            response = board.get_board_json()
    finally:
        repository_b.directory.chmod(0o755)

    assert response.status == 200
    repos = cast(list[dict[str, Any]], response.json()["repos"])
    assert [(repo["name"], repo["error"]) for repo in repos] == [("a", None), ("b", error)]
    assert [item["number"] for item in repos[0]["items"]] == [42]
    assert repos[1]["items"] == []


@pytest.mark.parametrize(
    ("stdout", "error"),
    [
        ("not json", "aco rulings failed: exit 0 without a message"),
        ('{"ok": true, "rulings": {}}', "aco rulings --json is unreadable: rulings is not a list"),
        (
            '{"ok": true, "rulings": [1]}',
            "aco rulings --json is unreadable: a rulings row is not an object",
        ),
        (
            '{"ok": true, "rulings": [{"number": true, "title": "T", "lines": []}]}',
            "aco rulings --json is unreadable: number is not a int",
        ),
        (
            '{"ok": true, "rulings": [{"number": 1, "title": "T"}]}',
            "aco rulings --json is unreadable: #1 lines is not a list",
        ),
        (
            '{"ok": true, "rulings": [{"number": 1, "title": "T", "lines": [2]}]}',
            "aco rulings --json is unreadable: #1 has a line that is not an object",
        ),
        (
            '{"ok": true, "rulings": [{"number": 1, "title": "T", "lines": '
            '[{"index": 1, "text": "Q?", "ruling": "yes", "ruled_on": "2026-10-01", '
            '"question": 3}]}]}',
            "aco rulings --json is unreadable: question is not text",
        ),
        (
            '{"ok": true, "rulings": [{"number": 1, "title": "T", "lines": '
            '[{"index": 1, "text": "Q?", "ruled_on": null}]}]}',
            "aco rulings --json is unreadable: #1 line has no ruling",
        ),
        (
            '{"ok": true, "rulings": [{"number": 1, "title": "T", "lines": '
            '[{"index": 1, "text": "Q?", "ruling": "yes"}]}]}',
            "aco rulings --json is unreadable: #1 line has no ruled_on",
        ),
        (
            '{"ok": true, "rulings": [{"number": 1, "title": "T", "lines": '
            '[{"index": 1, "text": "Q?", "ruling": "perhaps", "ruled_on": "2026-10-01"}]}]}',
            "aco rulings --json is unreadable: ruling is not an outcome",
        ),
        (
            '{"ok": true, "rulings": [{"number": 1, "title": "T", "lines": '
            '[{"index": 1, "text": "Q?", "ruling": "yes", "ruled_on": "gestern"}]}]}',
            "aco rulings --json is unreadable: ruled_on is not a date",
        ),
        (
            '{"ok": true, "rulings": [{"number": 7, "title": "T", "lines": '
            '[{"index": 2, "text": "Q?", "default": null, "ruling": null, "ruled_on": null}]}]}',
            "aco rulings --json is unreadable: #7 line 2 is an open yes/no line; "
            "write an option card",
        ),
    ],
    ids=[
        "not-json",
        "rulings-not-a-list",
        "row-not-an-object",
        "number-not-an-int",
        "lines-not-a-list",
        "line-not-an-object",
        "question-not-text",
        "ruling-missing",
        "ruled-on-missing",
        "ruling-not-an-outcome",
        "ruled-on-not-a-date",
        "open-yes-no-line",
    ],
)
def test_unreadable_rulings_json_answers_502_with_why(
    repository: FakeAcoRepository, board: BoardClient, stdout: str, error: str
) -> None:
    repository.answer_rulings_with(stdout)

    response = board.get_board_json()

    assert response.status == 502
    assert response.json() == {"repos": [{"name": DEFAULT_LABEL, "error": error, "items": []}]}


def test_a_ruled_yes_no_line_without_a_default_key_is_listed(
    repository: FakeAcoRepository, board: BoardClient, listed_items: Lister
) -> None:
    """The board reads no `default`, so aco dropping the key changes nothing."""
    repository.answer_rulings_with(
        '{"ok": true, "rulings": [{"number": 1, "title": "T", "lines": '
        '[{"index": 1, "text": "Q?", "ruling": "no", "ruled_on": "2026-10-01"}]}]}'
    )

    [item] = listed_items(board)

    assert [(entry["ruling"], entry["ruled_on"]) for entry in item["lines"]] == [
        ("no", "2026-10-01")
    ]


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
    repository: FakeAcoRepository,
    board: BoardClient,
    presented: str | None,
    method: str,
    path: str,
    body: str | None,
) -> None:
    repository.set_rulings(row(42, "Share page", option_line()))

    response = board.call_api(method, path.format(token=board.token), body, presented=presented)

    assert response.status == 403
    assert response.json() == {"error": "forbidden: missing or wrong token"}
    assert repository.calls() == []


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
    ("method", "path", "answer", "allow"),
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
    repository: FakeAcoRepository,
    board: BoardClient,
    method: str,
    path: str,
    answer: tuple[int, dict[str, str]],
    allow: str | None,
) -> None:
    response = board.call_api(method, path, presented=board.token)

    assert answer == (response.status, response.json())
    assert response.headers.get("Allow") == allow
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

    assert response.status == 502
    assert response.json() == {"repos": [{"name": DEFAULT_LABEL, "error": error, "items": []}]}
    assert response.headers["Content-Type"] == "application/json"
    _assert_guarded(response)


def test_the_board_lists_every_configured_repo_in_order_200_on_partial_failure(
    two_repositories: tuple[FakeAcoRepository, FakeAcoRepository],
) -> None:
    repository_a, repository_b = two_repositories
    repository_a.set_rulings(row(42, "Share page", option_line()))
    repository_b.fail_rulings("ERROR: no forge adapter for host")

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
        "error": "aco rulings failed: ERROR: no forge adapter for host",
        "items": [],
    }


def test_the_board_answers_502_only_once_every_configured_repo_has_failed(
    two_repositories: tuple[FakeAcoRepository, FakeAcoRepository],
) -> None:
    repository_a, repository_b = two_repositories
    repository_a.fail_rulings("a is down")
    repository_b.fail_rulings("b is down")

    with serving_two(two_repositories) as board:
        response = board.get_board_json()

    assert response.status == 502
    assert response.json() == {
        "repos": [
            {"name": "a", "error": "aco rulings failed: a is down", "items": []},
            {"name": "b", "error": "aco rulings failed: b is down", "items": []},
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
