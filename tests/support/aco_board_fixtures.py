"""The decision board's arrangement: board checkouts, the board's port
recorded, the real board server, and a client for it.

`board_checkout` makes a git checkout whose items live in
`board_forge.BoardForge`; `decision_port` is the one construction of the
board's port over such a checkout, wrapped in a `RecordedPort` that logs
every call at the port.
"""

from __future__ import annotations

import errno
import http.client
import json
import os
import secrets
import select
import socket
import struct
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from email.message import Message
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import parse_qs, urlsplit

from board_fixtures import write_repository_config
from board_forge import BoardForge
from cli_fixtures import real_git

from aco import workboard
from aco.board.aco_cli import AcoCli
from aco.board.board import Board, Boards
from aco.board.ports import (
    CardChanged,
    CardDecision,
    DecisionPort,
    DecisionResult,
    ExpectationLine,
)
from aco.board.server import TOKEN_HEADER, start_board

DEFAULT_LABEL = "repo"
"""The one repo label a single-repo test gets when it does not name its own."""


def path_with(bin_directory: Path) -> str:
    return f"{bin_directory}{os.pathsep}{os.environ.get('PATH', '')}"


def board_checkout(directory: Path) -> BoardForge:
    """A git checkout at `directory` tracking an empty board configuration
    (the `github` pin), and the forge holding its items."""
    directory.mkdir(parents=True)
    real_git(directory, "init", "--quiet")
    write_repository_config(directory)
    real_git(directory, "add", workboard.CONFIG_PATH.as_posix())
    return BoardForge(directory)


class PortOperation(StrEnum):
    EXPECTATION_LINES = "expectation_lines"
    RULE_CARD = "rule_card"


class CallPhase(StrEnum):
    ENTERED = "entered"
    COMPLETED = "completed"


@dataclass(frozen=True)
class PortCall:
    operation: PortOperation
    phase: CallPhase
    item: int | None = None


@dataclass(frozen=True)
class HeldRuling:
    """`entered` is set once the held call is inside `rule_card`; it delegates
    only after `release`."""

    entered: threading.Event
    release: threading.Event
    wait_seconds: float


class RecordedPort:
    """The board's port, every call to it logged as it enters and completes.
    The lock guards only the log, never the delegated call."""

    def __init__(self, port: DecisionPort) -> None:
        self._port = port
        self._lock = threading.Lock()
        self._calls: list[PortCall] = []
        self._held: HeldRuling | None = None

    def calls(self) -> tuple[PortCall, ...]:
        with self._lock:
            return tuple(self._calls)

    def ruled_items(self) -> list[int | None]:
        """The item of every `rule_card` call that entered, in order."""
        return [
            call.item
            for call in self.calls()
            if (call.operation, call.phase) == (PortOperation.RULE_CARD, CallPhase.ENTERED)
        ]

    def hold_next_rule_card(self, wait_seconds: float) -> HeldRuling:
        held = HeldRuling(threading.Event(), threading.Event(), wait_seconds)
        with self._lock:
            self._held = held
        return held

    def expectation_lines(self) -> tuple[ExpectationLine, ...]:
        self._record(PortCall(PortOperation.EXPECTATION_LINES, CallPhase.ENTERED))
        try:
            return self._port.expectation_lines()
        finally:
            self._record(PortCall(PortOperation.EXPECTATION_LINES, CallPhase.COMPLETED))

    def rule_card(self, decision: CardDecision) -> DecisionResult | CardChanged:
        held = self._record(PortCall(PortOperation.RULE_CARD, CallPhase.ENTERED, decision.item))
        try:
            if held is not None:
                held.entered.set()
                if not held.release.wait(held.wait_seconds):
                    raise TimeoutError("the held ruling was never released")
            return self._port.rule_card(decision)
        finally:
            self._record(PortCall(PortOperation.RULE_CARD, CallPhase.COMPLETED, decision.item))

    def _record(self, call: PortCall) -> HeldRuling | None:
        """Logs `call`; an entering `rule_card` takes the hold set for it."""
        with self._lock:
            self._calls.append(call)
            if (call.operation, call.phase) != (PortOperation.RULE_CARD, CallPhase.ENTERED):
                return None
            held, self._held = self._held, None
            return held


def decision_port(repository: BoardForge) -> RecordedPort:
    """The board's port over `repository`'s checkout, recorded."""
    return RecordedPort(AcoCli(directory=repository.directory))


@contextmanager
def serving(
    decisions: DecisionPort, *, label: str = DEFAULT_LABEL, **board_options: float
) -> Iterator[BoardClient]:
    """The real board server for one repository labelled `label`, stopped on exit."""
    with serving_many({label: decisions}, **board_options) as client:
        yield client


@contextmanager
def serving_many(
    decisions_by_label: Mapping[str, DecisionPort], **board_options: float
) -> Iterator[BoardClient]:
    """The real board server for every labelled repository, stopped on exit."""
    boards = Boards({label: Board(decisions) for label, decisions in decisions_by_label.items()})
    running = start_board(0, boards, secrets.token_urlsafe(32), **board_options)
    server_thread = threading.Thread(
        target=running.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    server_thread.start()
    try:
        yield BoardClient.from_url(running.url, repos=tuple(decisions_by_label))
    finally:
        running.httpd.shutdown()
        running.httpd.server_close()
        server_thread.join()


def serving_two(
    repositories: tuple[BoardForge, BoardForge],
) -> AbstractContextManager[BoardClient]:
    """The real board server for two repositories labelled `a` and `b` -- the
    arrangement every `two_repositories`-backed test shares."""
    repository_a, repository_b = repositories
    return serving_many({"a": decision_port(repository_a), "b": decision_port(repository_b)})


@dataclass(frozen=True)
class Response:
    status: int
    body: str
    headers: Message
    """Case-insensitive, as HTTP header names are."""

    @property
    def content_security_policy(self) -> str | None:
        return self.headers.get("Content-Security-Policy")

    def json(self) -> dict[str, object]:
        parsed: dict[str, object] = json.loads(self.body)
        return parsed

    @classmethod
    def from_raw(cls, answer: bytes) -> Response:
        """An answer read straight off the socket, beneath any HTTP client."""
        head, _, body = answer.partition(b"\r\n\r\n")
        status_line, *header_lines = head.decode("latin-1").split("\r\n")
        headers = Message()
        for header_line in header_lines:
            name, _, value = header_line.partition(":")
            headers[name] = value.strip()
        return cls(int(status_line.split(" ")[1]), body.decode("utf-8"), headers)


# A board that refuses a request on its headers answers and closes without
# reading the rest; the kernel then resets the connection. The answer already
# arrived, so the reset ends the conversation instead of failing it.
_PEER_ALREADY_CLOSED = frozenset({errno.ENOTCONN, errno.EPIPE, errno.ECONNRESET})


@contextmanager
def _unless_the_peer_already_closed() -> Iterator[None]:
    try:
        yield
    except OSError as error:
        if error.errno not in _PEER_ALREADY_CLOSED:
            raise


def _received_until_closed(connection: socket.socket) -> bytes:
    received = b""
    with _unless_the_peer_already_closed():
        while chunk := connection.recv(65536):
            received += chunk
    return received


@dataclass(frozen=True)
class BoardClient:
    host: str
    port: int
    token: str
    repos: tuple[str, ...] = (DEFAULT_LABEL,)
    """Every repo label this board was started with, in configured order."""

    @property
    def repo(self) -> str:
        """The one repo most single-repo tests mean when they say none."""
        return self.repos[0]

    @classmethod
    def from_url(cls, url: str, *, repos: tuple[str, ...] = (DEFAULT_LABEL,)) -> BoardClient:
        split = urlsplit(url)
        assert split.hostname is not None
        assert split.port is not None
        return cls(split.hostname, split.port, parse_qs(split.fragment)["t"][0], repos)

    def get_shell(self) -> Response:
        """`GET /`, the SPA shell every board answers with, no token needed."""
        return self._request("GET", "/")

    def send_raw(self, request: bytes) -> bytes:
        """Send bytes as they are, beneath any HTTP client's own checks."""
        with self._connection() as connection:
            with _unless_the_peer_already_closed():
                connection.sendall(request)
                connection.shutdown(socket.SHUT_WR)
            return _received_until_closed(connection)

    def send_unfinished(self, request: bytes) -> bytes:
        """Send the start of a request, keep the connection open, and return
        whatever the board answers before it closes the connection."""
        with self._connection() as connection:
            connection.sendall(request)
            return _received_until_closed(connection)

    def send_dripping(self, head: bytes, body: bytes, interval_seconds: float) -> bytes:
        """Send `head`, then `body` one byte per interval, never pausing long
        enough to look stalled; return the answer once the board sends one."""
        with self._connection() as connection:
            connection.sendall(head)
            for byte in body:
                answer_waiting, _, _ = select.select([connection], [], [], interval_seconds)
                if answer_waiting:
                    break
                connection.sendall(bytes([byte]))
            return _received_until_closed(connection)

    @contextmanager
    def holding_unfinished(self, request: bytes) -> Iterator[None]:
        """Keep a connection open on the start of a request while inside."""
        with self._connection() as connection:
            connection.sendall(request)
            yield

    @contextmanager
    def holding_unread(self, request: bytes) -> Iterator[None]:
        """Send a whole request, then read none of the answer while inside."""
        with socket.socket() as connection:
            # A small receive window set before connecting, so the board's
            # write blocks instead of filling the kernel's buffers.
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            connection.connect((self.host, self.port))
            connection.sendall(request)
            yield

    def send_and_reset(self, request: bytes) -> None:
        """Send a whole request, then hang up with a reset before any answer."""
        with self._connection() as connection:
            connection.sendall(request)
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))

    def _connection(self) -> socket.socket:
        return socket.create_connection((self.host, self.port), timeout=30)

    def call_api(
        self,
        method: str,
        path: str,
        body: str | None = None,
        *,
        presented: str | None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """Send `presented` as the API token header, or no such header for None."""
        token_header = {} if presented is None else {TOKEN_HEADER: presented}
        return self._request(method, path, body, {**token_header, **(headers or {})})

    def get_board_json(self) -> Response:
        return self.call_api("GET", "/api/board", presented=self.token)

    def decide_card_through_api(
        self,
        item: int,
        lines: Sequence[Mapping[str, object]],
        options: Sequence[str] | None = None,
        answer: Mapping[str, object] | None = None,
        *,
        repo: str | None = None,
    ) -> Response:
        """Post a card for `lines` exactly as `GET /api/board` listed them: a letter
        from `options` per line, or `answer` (`other` or `unclear`) for all of them."""
        letters: Sequence[Mapping[str, str]] = (
            [{} for _ in lines] if options is None else [{"option": letter} for letter in options]
        )
        return self.post_rule(
            {
                "repo": self.repo if repo is None else repo,
                "item": item,
                "lines": [
                    {"line": shown["index"], "fingerprint": shown["fingerprint"], **letter}
                    for shown, letter in zip(lines, letters, strict=True)
                ],
                **(answer or {}),
            }
        )

    def post_rule(self, payload: Mapping[str, object]) -> Response:
        """Post `payload` to `/api/rule` with the board token, as given."""
        return self.call_api("POST", "/api/rule", json.dumps(payload), presented=self.token)

    def _request(
        self,
        method: str,
        path: str,
        body: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=30)
        try:
            connection.request(method, path, body=body, headers=dict(headers or {}))
            response = connection.getresponse()
            return Response(
                status=response.status,
                body=response.read().decode("utf-8"),
                headers=response.headers,
            )
        finally:
            connection.close()


class Lister(Protocol):
    """The `listed_items` fixture's reader."""

    def __call__(self, board: BoardClient, repo: str | None = None) -> list[dict[str, Any]]:
        """The items `board` lists for `repo`, its first repo unless named; the
        listing must succeed and that repo must read without an error."""
        ...


def first_listed_line(board: BoardClient) -> dict[str, Any]:
    [listed_repo] = cast(list[dict[str, Any]], board.get_board_json().json()["repos"])
    return cast(dict[str, Any], listed_repo["items"][0]["lines"][0])


def assert_guarded(response: Response) -> None:
    """The headers every answer carries, whatever its status."""
    policy = response.content_security_policy or ""
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    for directive in ("base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'"):
        assert directive in policy
    assert cross_origin_headers(response) == []


def cross_origin_headers(response: Response) -> list[str]:
    return [name for name in response.headers if name.lower().startswith("access-control-")]
