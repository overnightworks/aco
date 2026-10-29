"""Start the decision board for one or more repositories, one page and one
URL for all of them. `aco serve` (`aco.cmd_serve`) parses the command line
and calls `serve`."""
# ruff: noqa: T201 - the board command line prints its URL and its refusals to the terminal

from __future__ import annotations

import contextlib
import sys
from collections.abc import Sequence
from pathlib import Path

from .aco_cli import AcoCli
from .board import Board, Boards
from .server import LOOPBACK_HOST, start_board
from .static import StaticAssetsMissingError


class _DuplicateRepositoryError(Exception):
    """Two `--repo` paths resolve to the same label or the same directory."""


def _labelled_repositories(paths: Sequence[Path]) -> dict[str, Path]:
    """Each path resolved and labelled by its directory name, in given order.

    Two paths that resolve to the same label -- the same directory under
    different names included -- would let a ruling meant for one land in the
    other, so the board refuses to start rather than guess.
    """
    labelled: dict[str, Path] = {}
    for path in paths:
        resolved = path.resolve()
        label = resolved.name
        existing = labelled.get(label)
        if existing is not None:
            raise _DuplicateRepositoryError(
                f"two repositories named {label}: {existing}, {resolved}"
            )
        labelled[label] = resolved
    return labelled


def serve(port: int, paths: Sequence[Path]) -> int:
    """Serve `paths` on `port` until interrupted; 0 picks a free port."""
    try:
        labelled = _labelled_repositories(paths)
    except _DuplicateRepositoryError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    boards = Boards(
        {label: Board(AcoCli(directory=directory)) for label, directory in labelled.items()}
    )
    try:
        running = start_board(port, boards)
    except OSError as error:
        print(
            f"ERROR: cannot listen on {LOOPBACK_HOST}:{port}: {error.strerror}",
            file=sys.stderr,
        )
        return 1
    except StaticAssetsMissingError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(running.url, flush=True)
    try:
        with contextlib.suppress(KeyboardInterrupt):
            running.httpd.serve_forever()
    finally:
        running.httpd.server_close()
    return 0
