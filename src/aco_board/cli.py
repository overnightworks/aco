"""`aco-board serve [--repo PFAD]...`: start the decision board for one or
more repositories, one page and one URL for all of them."""

from __future__ import annotations

import argparse
import contextlib
import sys
from collections.abc import Sequence
from pathlib import Path

from .aco_cli import AcoCli
from .board import Board, Boards
from .server import LOOPBACK_HOST, start_board

_HIGHEST_PORT = 65535


class _DuplicateRepositoryError(Exception):
    """Two `--repo` paths resolve to the same label or the same directory."""


def _port(text: str) -> int:
    try:
        port = int(text)
    except ValueError:
        port = -1
    if not 0 <= port <= _HIGHEST_PORT:
        raise argparse.ArgumentTypeError(f"{text!r} is not a port between 0 and {_HIGHEST_PORT}")
    return port


def _directory(text: str) -> Path:
    path = Path(text)
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"{text!r} is not a directory")
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aco-board",
        description="Decide one or more repositories' open expectation lines in the browser.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser(
        "serve",
        help=f"serve the board on {LOOPBACK_HOST} with a per-start access token",
        allow_abbrev=False,
    )
    serve.add_argument(
        "--port",
        type=_port,
        default=0,
        metavar="N",
        help=f"{LOOPBACK_HOST} port to listen on; 0 (default) picks a free one",
    )
    serve.add_argument(
        "--repo",
        dest="repos",
        type=_directory,
        action="append",
        metavar="PFAD",
        help="a repository to serve, labelled by its directory name (repeatable); "
        "without it, the current directory",
    )
    return parser


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


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    paths = arguments.repos if arguments.repos is not None else [Path.cwd()]
    try:
        labelled = _labelled_repositories(paths)
    except _DuplicateRepositoryError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    boards = Boards(
        {label: Board(AcoCli(directory=directory)) for label, directory in labelled.items()}
    )
    try:
        running = start_board(arguments.port, boards)
    except OSError as error:
        print(
            f"ERROR: cannot listen on {LOOPBACK_HOST}:{arguments.port}: {error.strerror}",
            file=sys.stderr,
        )
        return 1
    print(running.url, flush=True)
    try:
        with contextlib.suppress(KeyboardInterrupt):
            running.httpd.serve_forever()
    finally:
        running.httpd.server_close()
    return 0
