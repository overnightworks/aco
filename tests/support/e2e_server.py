"""The real board server behind a fake `aco`, for Playwright's E2E harness.

`frontend/e2e/global-setup.ts` spawns this as `uv run python
tests/support/e2e_server.py` and points every spec straight at the port it
prints -- no dev server, no proxy: it serves the same committed, built SPA a
live `aco serve` does. It speaks the same protocol, too
(`aco.board.server.start_board`), so a spec drives the real wire form
(`specs/serve.spec.md` ABRD-08/09/21) end to end -- the only thing fake
is `aco` itself (`aco_board_fixtures.install_fake_aco`).

One line of JSON on stdout once the server is listening:
`{"host", "port", "token", "repo_directory"}`. The repo directory lets a spec
toggle the fake `aco`'s answers between runs through the files it reads
there (`rulings.json`, `rulings-failure.txt`). Stops on SIGTERM or SIGINT,
which the launcher sends on teardown.
"""
# ruff: noqa: T201 - the server announces its address to the test that starts it

from __future__ import annotations

import json
import os
import secrets
import signal
import sys
import tempfile
import threading
from pathlib import Path
from types import FrameType
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aco_board_fixtures import DEFAULT_LABEL, install_fake_aco, named_repository, path_with

from aco.board.aco_cli import AcoCli
from aco.board.board import Board, Boards
from aco.board.server import start_board


def main() -> None:
    workspace = Path(tempfile.mkdtemp(prefix="aco-board-e2e-"))
    install_fake_aco(workspace / "bin")
    os.environ["PATH"] = path_with(workspace / "bin")
    repository = named_repository(workspace, DEFAULT_LABEL)

    boards = Boards({DEFAULT_LABEL: Board(AcoCli(directory=repository.directory))})
    running = start_board(0, boards, secrets.token_urlsafe(32))
    server_thread = threading.Thread(
        target=running.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    server_thread.start()

    served = urlsplit(running.url)
    ready = {
        "host": served.hostname,
        "port": served.port,
        "token": parse_qs(served.fragment)["t"][0],
        "repo_directory": str(repository.directory),
    }
    print(json.dumps(ready), flush=True)

    stop = threading.Event()

    def _stop(_signal_number: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    stop.wait()

    running.httpd.shutdown()
    running.httpd.server_close()
    server_thread.join()


if __name__ == "__main__":
    main()
