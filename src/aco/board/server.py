"""The board's loopback HTTP transport.

Binds `127.0.0.1` only -- there is no host option. `/` and `/assets/**`
deliver the SPA shell and its built assets (`static.py`) to anyone on the
loopback interface, carrying no decision data, so they need no token; the
JSON API under `/api/` takes the per-start access token in exactly one
`X-Board-Token` header and checks it before any other work, whatever the
method: `GET /api/board` answers every line from a fresh read of the
decision source, `POST /api/rule` submits one decision, and every other
method is refused. A malformed or stalled request gets a fixed 4xx answer,
never a traceback; every answer, the HTTP layer's own refusals included,
carries the same guard headers, and none carries a cross-origin header, so a
page from another origin can never read one.
"""

from __future__ import annotations

import hmac
import secrets
import socket
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BufferedIOBase
from typing import cast
from urllib.parse import urlsplit

from . import api, static
from .board import Boards, all_repos_unavailable

LOOPBACK_HOST = "127.0.0.1"
TOKEN_FIELD = "t"
TOKEN_HEADER = "X-Board-Token"
PAGE_PATH = "/"
API_PREFIX = "/api/"
API_BOARD_PATH = "/api/board"
API_RULE_PATH = "/api/rule"
_FORBIDDEN = "forbidden: missing or wrong token"
_NOT_FOUND = "not found"
_BAD_CONTENT_LENGTH = "bad request: Content-Length"
_BAD_DECISION = "bad request: decision"
_BODY_INCOMPLETE = "request timeout: body incomplete"
_METHOD_NOT_ALLOWED = "method not allowed"
_SERVED_METHODS = frozenset({"GET", "POST"})
_DEFAULT_ALLOW = ", ".join(sorted(_SERVED_METHODS))
_ALLOWED_METHODS_BY_PATH = {
    PAGE_PATH: "GET",
    API_BOARD_PATH: "GET",
    API_RULE_PATH: "POST",
}
"""The one method each known fixed route serves, for a 405's `Allow` header;
an asset path (every filename under `static.ASSETS_PREFIX`) is handled
alongside these in `_allowed_methods`, and a path outside both still lives
under a method the board serves at all, so it advertises every method
(`_DEFAULT_ALLOW`)."""
_TEXT_CONTENT_TYPE = "text/plain; charset=utf-8"
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; img-src data:; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
"""The shell's one script loads from `/assets/index.js`, never inline, and a
line's picture is only ever an `<img>` data URI -- neither needs a nonce."""


def _allowed_methods(path: str) -> str:
    if path == PAGE_PATH or path.startswith(static.ASSETS_PREFIX):
        return "GET"
    return _ALLOWED_METHODS_BY_PATH.get(path, _DEFAULT_ALLOW)


_MAX_REQUEST_BYTES = 16 * 1024
"""A decision is two numbers, an outcome, a fingerprint, and a short note;
anything larger is refused before it is read."""
REQUEST_DEADLINE_SECONDS = 10.0
"""How long one socket read or write on a connection may wait, and how long
a whole request body may take to arrive; a browser sends its small request
at once, so a client still silent -- or still trickling -- after this is
dropped rather than holding a handler thread."""

_Refusal = Callable[[HTTPStatus, str], None]


class _ClientDisconnectedError(Exception):
    """Raised only by `_BoardRequestHandler._respond`'s own socket write: the
    one place a broken or reset connection is honestly the client hanging up
    rather than a server defect raising the same exception elsewhere."""


class _BoardServer(ThreadingHTTPServer):
    # `ThreadingHTTPServer` runs handlers as daemon threads, so `server_close`
    # never waits for one a stalled client holds -- only for a ruling write.

    def __init__(
        self, port: int, token: str, boards: Boards, request_deadline_seconds: float
    ) -> None:
        # Set before binding: a failed bind already calls `server_close`.
        self.boards = boards
        super().__init__((LOOPBACK_HOST, port), _BoardRequestHandler)
        self.token = token
        self.request_deadline_seconds = request_deadline_seconds

    def handle_error(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: tuple[str, int]
    ) -> None:
        """A browser that leaves mid-response is no defect: stay quiet for it
        and keep the stdlib's traceback for everything else."""
        if isinstance(sys.exc_info()[1], _ClientDisconnectedError):
            return
        super().handle_error(request, client_address)

    def server_close(self) -> None:
        """Stop listening, then wait for a ruling already being written.

        Handler threads are daemons, so the process may exit while one is
        inside `aco rule`, leaving the ruling's outcome unknown. Closing the
        boards' writes waits for that write -- as long as the source's own
        timeout lets it run -- and refuses every later one.
        """
        super().server_close()
        self.boards.close_writes()


@dataclass(frozen=True)
class RunningBoard:
    httpd: ThreadingHTTPServer
    url: str


def start_board(
    port: int,
    boards: Boards,
    *,
    request_deadline_seconds: float = REQUEST_DEADLINE_SECONDS,
) -> RunningBoard:
    """Bind `127.0.0.1:port` (0 picks a free port) with a fresh token.

    Raises `static.StaticAssetsMissingError` before binding if the frontend
    was never built, rather than start a board that can only answer its API.
    """
    static.ensure_built()
    token = secrets.token_urlsafe(32)
    httpd = _BoardServer(port, token, boards, request_deadline_seconds)
    bound_port = httpd.server_address[1]
    # A fragment, not a query: the browser never sends it back to the server,
    # so the shell at `PAGE_PATH` needs no token to answer it (ABRD-10).
    url = (
        # S5332: loopback only, no TLS by design (README.md, `aco serve`)
        f"http://{LOOPBACK_HOST}:{bound_port}{PAGE_PATH}"  # NOSONAR(S5332) loopback-only URL
        f"#{TOKEN_FIELD}={token}"
    )
    return RunningBoard(httpd=httpd, url=url)


def read_before_deadline(
    rfile: BufferedIOBase, connection: socket.socket, length: int, deadline_seconds: float
) -> bytes:
    """Up to `length` bytes, raising TimeoutError once `deadline_seconds`
    pass in total -- however steadily a slow client keeps sending."""
    deadline = time.monotonic() + deadline_seconds
    received = bytearray()
    while len(received) < length:
        seconds_left = deadline - time.monotonic()
        if seconds_left <= 0:
            raise TimeoutError
        connection.settimeout(seconds_left)
        chunk = rfile.read1(length - len(received))
        if not chunk:
            break
        received += chunk
    return bytes(received)


def _content_length(header: str) -> int | None:
    """The declared body size, or None unless it is a decimal within the limit."""
    # The length check comes first: `int()` refuses a digit string past
    # Python's conversion limit with a ValueError.
    if len(header) > len(str(_MAX_REQUEST_BYTES)) or not (header.isascii() and header.isdigit()):
        return None
    length = int(header)
    return length if length <= _MAX_REQUEST_BYTES else None


class _BoardRequestHandler(BaseHTTPRequestHandler):
    def _server(self) -> _BoardServer:
        # `_BoardServer.__init__` is this handler's only constructor.
        return cast(_BoardServer, self.server)

    def setup(self) -> None:
        # The per-server form of `StreamRequestHandler.timeout`, whose class
        # attribute every board would share; set before the request is read.
        super().setup()
        self.connection.settimeout(self._server().request_deadline_seconds)

    def _authorized(self, candidate: str | None) -> bool:
        # The token is ASCII, so a non-ASCII candidate (a lone surrogate
        # included) is simply wrong; `compare_digest` raises on one.
        return (
            candidate is not None
            and candidate.isascii()
            and hmac.compare_digest(candidate, self._server().token)
        )

    def _respond(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
        *,
        allow: str | None = None,
    ) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if allow is not None:
                self.send_header("Allow", allow)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as error:
            raise _ClientDisconnectedError from error

    def _refuse_as_text(
        self, status: HTTPStatus, sentence: str, *, allow: str | None = None
    ) -> None:
        self._respond(status, sentence.encode("utf-8"), _TEXT_CONTENT_TYPE, allow=allow)

    def _refuse_as_json(
        self, status: HTTPStatus, sentence: str, *, allow: str | None = None
    ) -> None:
        self._respond(
            status, api.error_json(sentence).encode("utf-8"), api.JSON_CONTENT_TYPE, allow=allow
        )

    def parse_request(self) -> bool:
        """Answer a method the board does not serve here, so the stdlib never
        dispatches it to its bare 501 -- the API's token check comes first."""
        if not super().parse_request():
            return False
        if self.command in _SERVED_METHODS:
            return True
        # Its body, if any, stays unread, so the connection cannot carry on.
        self.close_connection = True
        path = urlsplit(self.path).path
        allow = _allowed_methods(path)
        if path.startswith(API_PREFIX):
            self._answer_api(lambda: self._refuse_method(allow))
        else:
            self._refuse_as_text(HTTPStatus.METHOD_NOT_ALLOWED, _METHOD_NOT_ALLOWED, allow=allow)
        return False

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """The HTTP layer's own refusal of a request it could not parse, sent
        with the board's guard headers. The request line may not have parsed,
        so neither the path nor the stdlib's message -- which echoes the
        request -- shapes the answer."""
        del message, explain
        self.close_connection = True
        # A request line refused before its version parsed leaves the stdlib's
        # HTTP/0.9 default, under which `send_response` writes no status line
        # and no header at all; the board answers in its own version instead.
        self.request_version = self.protocol_version
        self._refuse_as_text(HTTPStatus(code), HTTPStatus(code).phrase.lower())

    def do_GET(self) -> None:
        split = urlsplit(self.path)
        if split.path.startswith(API_PREFIX):
            self._answer_api(self._get_board if split.path == API_BOARD_PATH else None)
            return
        if split.path == PAGE_PATH:
            served = static.shell()
            self._respond(HTTPStatus.OK, served.content, served.content_type)
            return
        if split.path.startswith(static.ASSETS_PREFIX):
            asset = static.asset(split.path)
            if asset is None:
                self._refuse_as_text(HTTPStatus.NOT_FOUND, _NOT_FOUND)
                return
            self._respond(HTTPStatus.OK, asset.content, asset.content_type)
            return
        self._refuse_as_text(HTTPStatus.NOT_FOUND, _NOT_FOUND)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith(API_PREFIX):
            self._answer_api(self._post_rule if path == API_RULE_PATH else None)
            return
        if path == PAGE_PATH or path.startswith(static.ASSETS_PREFIX):
            self._refuse_as_text(
                HTTPStatus.METHOD_NOT_ALLOWED, _METHOD_NOT_ALLOWED, allow=_allowed_methods(path)
            )
            return
        self._refuse_as_text(HTTPStatus.NOT_FOUND, _NOT_FOUND)

    def _answer_api(self, route: Callable[[], None] | None) -> None:
        """Check the header token before anything else -- the path, the body,
        or the board -- so a request without it never reaches aco."""
        if not self._authorized(self._header_token()):
            self._refuse_as_json(HTTPStatus.FORBIDDEN, _FORBIDDEN)
            return
        if route is None:
            self._refuse_as_json(HTTPStatus.NOT_FOUND, _NOT_FOUND)
            return
        route()

    def _header_token(self) -> str | None:
        # Two token headers are refused rather than one of them picked: a
        # proxy and a client disagreeing on which counts is no authorization.
        presented = self.headers.get_all(TOKEN_HEADER) or []
        return presented[0] if len(presented) == 1 else None

    def _refuse_method(self, allow: str) -> None:
        self._refuse_as_json(HTTPStatus.METHOD_NOT_ALLOWED, _METHOD_NOT_ALLOWED, allow=allow)

    def _get_board(self) -> None:
        readings = self._server().boards.snapshot()
        status = HTTPStatus.BAD_GATEWAY if all_repos_unavailable(readings) else HTTPStatus.OK
        self._respond(status, api.board_json(readings).encode("utf-8"), api.JSON_CONTENT_TYPE)

    def _post_rule(self) -> None:
        raw = self._read_body(self._refuse_as_json)
        if raw is None:
            return
        request = api.parse_decision_request(raw)
        if request is None or not self._repo_known(request.repo):
            self._refuse_as_json(HTTPStatus.BAD_REQUEST, _BAD_DECISION)
            return
        self._decide(request)

    def _repo_known(self, repo: str) -> bool:
        """Whether `repo` names one of this server's configured repos -- checked
        before any `aco` call, so a request for an unknown repo never reaches it."""
        return repo in self._server().boards.labels

    def _read_body(self, refuse: _Refusal) -> bytes | None:
        """The whole declared body, or None once `refuse` has answered why not."""
        length = _content_length(self.headers.get("Content-Length", ""))
        if length is None:
            refuse(HTTPStatus.BAD_REQUEST, _BAD_CONTENT_LENGTH)
            return None
        deadline_seconds = self._server().request_deadline_seconds
        try:
            body = read_before_deadline(self.rfile, self.connection, length, deadline_seconds)
        except TimeoutError:
            body = None
        # The read shrank the socket timeout; restore it before writing a
        # refusal, so that answer is not cut short by the nearly exhausted
        # deadline it is reporting.
        self.connection.settimeout(deadline_seconds)
        if body is None or len(body) < length:
            refuse(HTTPStatus.REQUEST_TIMEOUT, _BODY_INCOMPLETE)
            return None
        return body

    def _decide(self, request: api.DecisionRequest) -> None:
        result = self._server().boards.decide(request.repo, request.decision, request.fingerprint)
        self._respond(
            HTTPStatus.OK, api.decision_result_json(result).encode("utf-8"), api.JSON_CONTENT_TYPE
        )

    def log_message(self, format: str, *_args: object) -> None:
        # The default request log would print the page URL, token included,
        # to the terminal; the printed start URL is the board's only output.
        return
