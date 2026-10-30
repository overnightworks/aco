"""The real board server and the real `aco` over a test forge, for
Playwright's E2E harness.

`frontend/e2e/global-setup.ts` spawns this as `uv run python
tests/support/e2e_server.py` and points every spec straight at the port it
prints -- no dev server, no proxy: it serves the same committed, built SPA a
live `aco serve` does. It speaks the same protocol, too
(`aco.board.server.start_board`), so a spec drives the real wire form
(`specs/serve.spec.md` ABRD-08/09/21) end to end. The board's port runs
aco's own library in this process; the only thing fake is the forge, a
`board_forge.BoardForge` in a temporary checkout.

A second server beside the board, the control endpoint, arranges that
forge: `PUT /board` stores the items a spec names, rendered by aco and
refused when aco's grammar refuses them, and `GET /items/<n>/lines` reads an
item's stored lines back in aco's own line JSON.

One line of JSON on stdout once both servers listen:
`{"host", "port", "token", "control_url"}`. Stops on SIGTERM or SIGINT,
which the launcher sends on teardown.
"""
# ruff: noqa: T201 - the server announces its address to the test that starts it

from __future__ import annotations

import json
import os
import re
import secrets
import signal
import sys
import tempfile
import threading
from collections.abc import Mapping
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from types import FrameType
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import board_forge
from aco_board_fixtures import DEFAULT_LABEL, board_checkout, decision_port
from board_forge import BoardForge, StoredItem

from aco import body, expectation_grammar, expectations, rulings, session
from aco.board.board import Board, Boards
from aco.board.server import start_board

_DATE_KEYS = (
    expectation_grammar.ASKED_ON,
    "ruled_on",
    expectation_grammar.RETURNED_ON,
    expectation_grammar.WITHDRAWN_ON,
)
_ITEM_LINES_PATH = re.compile(r"/items/(?P<number>\d+)/lines")


class ArrangementRefusedError(Exception):
    """An arranged body aco's grammar refuses; carries every defect."""

    def __init__(self, defects: list[str]) -> None:
        super().__init__("; ".join(defects))
        self.defects = defects


def _dated(entry: Mapping[str, object]) -> dict[str, object]:
    """`entry` with its ISO date strings as the TOML local dates aco reads."""
    return {
        key: date.fromisoformat(value) if key in _DATE_KEYS and isinstance(value, str) else value
        for key, value in entry.items()
    }


def _stored_item(arranged: Mapping[str, object]) -> StoredItem:
    entries = arranged["entries"]
    assert isinstance(entries, list)
    raw_body = board_forge.item_body(*(_dated(entry) for entry in entries))
    parsed = body.parse_body(raw_body)
    if parsed.read_state is body.BodyReadState.MALFORMED:
        raise ArrangementRefusedError(
            [
                f"#{arranged['number']}: {body.body_defect_text(defect)}"
                for defect in parsed.contract.defects
            ]
        )
    return StoredItem(str(arranged["title"]), raw_body)


def arrange_board(repository: BoardForge, arrangement: Mapping[str, object]) -> None:
    """The forge holds exactly the arranged items, checked whole before any
    is stored, and fails its listing when the arrangement says so."""
    arranged_items = arrangement["items"]
    assert isinstance(arranged_items, list)
    items = {int(arranged["number"]): _stored_item(arranged) for arranged in arranged_items}
    repository.replace_items(items)
    listing_failure = arrangement.get("listing_failure")
    if listing_failure is not None:
        repository.fail_listing(str(listing_failure))


def stored_lines(repository: BoardForge, number: int) -> list[dict[str, object]]:
    """Item `number`'s stored lines as aco's own line JSON writes them."""
    return [
        rulings.line_json(line)
        for line in expectations.expectation_lines(repository.stored_body(number))
    ]


def control_handler(repository: BoardForge) -> type[BaseHTTPRequestHandler]:
    class ControlHandler(BaseHTTPRequestHandler):
        def do_PUT(self) -> None:
            if self.path != "/board":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            length = int(self.headers["Content-Length"])
            try:
                arrange_board(repository, json.loads(self.rfile.read(length)))
            except ArrangementRefusedError as refused:
                self._answer_json(HTTPStatus.BAD_REQUEST, {"defects": refused.defects})
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()

        def do_GET(self) -> None:
            match = _ITEM_LINES_PATH.fullmatch(self.path)
            if match is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._answer_json(HTTPStatus.OK, stored_lines(repository, int(match["number"])))

        def _answer_json(self, status: HTTPStatus, answer: object) -> None:
            encoded = json.dumps(answer).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *_args: object) -> None:
            """Silent: stdout carries only the ready line."""

    return ControlHandler


def _serve_in_background(httpd: HTTPServer) -> threading.Thread:
    thread = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    return thread


def _forge_checkout(workspace: Path) -> BoardForge:
    """A board checkout in `workspace`, with git reading an empty global
    configuration."""
    global_git_config = workspace / "gitconfig"
    global_git_config.touch()
    os.environ["GIT_CONFIG_GLOBAL"] = str(global_git_config)
    return board_checkout(workspace / DEFAULT_LABEL)


def _wait_for_stop_signal() -> None:
    stop = threading.Event()

    def _stop(_signal_number: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    stop.wait()


def main() -> None:
    session.run_context = board_forge.run_context
    repository = _forge_checkout(Path(tempfile.mkdtemp(prefix="aco-board-e2e-")))
    boards = Boards({DEFAULT_LABEL: Board(decision_port(repository))})
    running = start_board(0, boards, secrets.token_urlsafe(32))
    control = ThreadingHTTPServer(("127.0.0.1", 0), control_handler(repository))
    threads = [_serve_in_background(running.httpd), _serve_in_background(control)]

    served = urlsplit(running.url)
    control_host, control_port = control.server_address[:2]
    ready = {
        "host": served.hostname,
        "port": served.port,
        "token": parse_qs(served.fragment)["t"][0],
        "control_url": f"http://{control_host!s}:{control_port}",
    }
    print(json.dumps(ready), flush=True)
    _wait_for_stop_signal()

    for httpd in (running.httpd, control):
        httpd.shutdown()
        httpd.server_close()
    for thread in threads:
        thread.join()


if __name__ == "__main__":
    main()
