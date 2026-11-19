"""The real board server and the real `aco` over a test forge, for
Playwright's E2E harness.

`frontend/e2e/global-setup.ts` spawns this as `uv run python
tests/support/e2e_server.py` and points every spec straight at the port it
prints -- no dev server, no proxy: it serves the same committed, built SPA a
live `aco serve` does. It speaks the same protocol, too
(`aco.board.server.start_board`), so a spec drives the real wire form
(`specs/serve.spec.md` ABRD-08/09/21) end to end. The board's port runs
aco's own library in this process; the only thing fake is the forge, a
`board_forge.BoardForge` in a checkout under the root of a temporary config
file, which the board finds by the production discovery.

A second server beside the board, the control endpoint, arranges that
forge: `PUT /board` stores the items a spec names, rendered by aco and
refused when aco's grammar refuses them, `GET /items/<n>/lines` reads an
item's stored lines back in aco's own line JSON, and `GET /items/<n>/now`
reads the `now` of its stored block. An arrangement's `lane_records` are the
finished items whose release commits the state ref holds.

One line of JSON on stdout once both servers listen:
`{"host", "port", "token", "control_url", "repository"}`; the board's request lines
follow it, logline unconfigured, and the launcher reads only the first line. Stops on
SIGTERM or SIGINT, which the launcher sends on teardown.
"""
# ruff: noqa: T201 - the server announces its address to the test that starts it

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
from aco_board_fixtures import (
    DEFAULT_LABEL,
    board_checkout,
    land_item,
    rulings_lines,
)
from board_fixtures import holding_for_the_operator
from board_forge import BoardForge, ReleasedItem, StoredItem, child_list, seed_lane_records

from aco import body, expectation_grammar, session
from aco.board.board import Boards
from aco.board.cli import discovered_boards
from aco.board.server import start_board
from aco.lane_record import LaneOutcome, LaneRecord
from aco.routing_line import RoutingLine

_DATE_KEYS = (
    expectation_grammar.ASKED_ON,
    "ruled_on",
    expectation_grammar.RETURNED_ON,
    expectation_grammar.WITHDRAWN_ON,
)
_FIRST_RELEASE = 1_700_000_000
_ITEM_LINES_PATH = re.compile(r"/items/(?P<number>\d+)/lines")
_ITEM_NOW_PATH = re.compile(r"/items/(?P<number>\d+)/now")


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


def _held(raw_body: str, arranged: Mapping[str, object]) -> str:
    step = arranged.get("step")
    return holding_for_the_operator(raw_body, step if isinstance(step, dict) else None)


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
    container = arranged.get("container")
    children = (
        child_list(closed=container["closed"], open=container["open"])
        if isinstance(container, dict)
        else None
    )
    parent = arranged.get("parent")
    return StoredItem(
        str(arranged["title"]),
        _held(raw_body, arranged) if arranged.get("waiting") or arranged.get("step") else raw_body,
        kind=body.ItemKind.CONTAINER.value if container is not None else None,
        children=children,
        parent=parent if isinstance(parent, int) else None,
    )


def _routing_of(entry: Mapping[str, object]) -> RoutingLine | None:
    rounds = entry.get("fix_rounds")
    if rounds is None:
        return None
    return RoutingLine(stages={}, fix_rounds=int(str(rounds)), blocking=None, experiment=None)


def _released_items(arranged: object) -> list[ReleasedItem]:
    """The finished items an arrangement names, each `{"issue", "wall_seconds"}` and optionally
    `"fix_rounds"`, as release commits dated one second apart."""
    assert isinstance(arranged, list)
    return [
        ReleasedItem(
            int(entry["issue"]),
            LaneRecord(
                LaneOutcome.LANDED,
                wall_seconds=int(entry["wall_seconds"]),
                routing=_routing_of(entry),
            ),
            _FIRST_RELEASE + position,
        )
        for position, entry in enumerate(arranged)
    ]


def arrange_board(repository: BoardForge, arrangement: Mapping[str, object]) -> None:
    """The forge holds exactly the arranged items, checked whole before any
    is stored, and fails its listing when the arrangement says so."""
    arranged_items = arrangement["items"]
    assert isinstance(arranged_items, list)
    items = {int(arranged["number"]): _stored_item(arranged) for arranged in arranged_items}
    repository.replace_items(items)
    landed = arrangement.get("landed", [])
    assert isinstance(landed, list)
    for number in landed:
        land_item(repository, int(number))
    seed_lane_records(repository, _released_items(arrangement.get("lane_records", [])))
    listing_failure = arrangement.get("listing_failure")
    if listing_failure is not None:
        repository.fail_listing(str(listing_failure))


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
            if (match := _ITEM_NOW_PATH.fullmatch(self.path)) is not None:
                stored = body.locate_block(repository.stored_body(int(match["number"]))).data
                self._answer_json(HTTPStatus.OK, stored.get("now"))
                return
            match = _ITEM_LINES_PATH.fullmatch(self.path)
            if match is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._answer_json(HTTPStatus.OK, rulings_lines(repository, int(match["number"])))

        def _answer_json(self, status: HTTPStatus, answer: object) -> None:
            encoded = json.dumps(answer).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *_args: object) -> None:
            """Silent: the control server writes no access line of its own."""

    return ControlHandler


def _serve_in_background(httpd: HTTPServer) -> threading.Thread:
    thread = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    return thread


def _forge_checkout(workspace: Path) -> BoardForge:
    """A board checkout under the root the config file in `workspace` names,
    with git reading an empty global configuration; the board finds it by the
    production discovery."""
    global_git_config = workspace / "gitconfig"
    global_git_config.touch()
    os.environ["GIT_CONFIG_GLOBAL"] = str(global_git_config)
    root = workspace / "root"
    config_file = workspace / "config" / "aco" / "config.toml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(f'root = "{root}"\n', encoding="utf-8")
    os.environ["XDG_CONFIG_HOME"] = str(workspace / "config")
    os.environ["XDG_STATE_HOME"] = str(workspace / "state")
    return board_checkout(root / DEFAULT_LABEL)


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
    boards = Boards(discovered_boards)
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
        "repository": str(repository.repository),
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
