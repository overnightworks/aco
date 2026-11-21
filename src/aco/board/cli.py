"""Start the decision board for every repository under the configured root,
one page and one URL for all of them. `aco serve` (`aco.cmd_serve`) parses the
command line and calls `serve`."""
# ruff: noqa: T201 - the board command line prints its URL and its refusals to the terminal

import contextlib
import logging
import os
import signal
import sys
from pathlib import Path
from types import FrameType

from logline import configure

from .. import __version__, protocol, repositories
from .aco_source import AcoSource
from .board import Board, Boards, Found, RepositoriesUnavailableError, RepoUnavailable
from .link import LOOPBACK_HOST
from .server import RunningBoard, start_board
from .static import StaticAssetsMissingError
from .token_store import MalformedTokenFileError, board_token, token_path

_REFUSED_EXIT_CODE = 2
_SERVICE_NAME = "aco-board"
_LOGGER = logging.getLogger(__name__)


def discovered_boards() -> Found:
    """One scan of the configured root: each repository's board under its
    `owner/repo` label, each unreadable directory as an unavailable entry."""
    try:
        root = repositories.configured_root(repositories.config_path(os.environ, Path.home()))
        discovery = repositories.discover(root)
    except protocol.ClaimError as refusal:
        raise RepositoriesUnavailableError(str(refusal)) from refusal
    return Found(
        str(discovery.root),
        {
            repository.label: Board(AcoSource(directory=repository.directory))
            for repository in discovery.repositories
        },
        tuple(
            RepoUnavailable(str(entry.directory), entry.reason) for entry in discovery.unavailable
        ),
    )


def _end_serving(_signal_number: int, _frame: FrameType | None) -> None:
    """The unit stops the board with SIGTERM, which ends serving the way Ctrl-C does."""
    raise KeyboardInterrupt


def _serve_until_stopped(running: RunningBoard) -> None:
    """Print the URL and serve until Ctrl-C or SIGTERM; the SIGTERM handler is
    in place before the URL is out and gone when serving ends."""
    previous_handler = signal.signal(signal.SIGTERM, _end_serving)
    try:
        with contextlib.suppress(KeyboardInterrupt):
            print(running.url, flush=True)
            _LOGGER.info("server_listen.started")
            running.httpd.serve_forever()
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


def _listening_port(port: int | None) -> int:
    """`port` when given, else `board_port` of the config file, else 0."""
    if port is not None:
        return port
    configured = repositories.configured_board_port(
        repositories.config_path(os.environ, Path.home())
    )
    return 0 if configured is None else configured


def serve(port: int | None) -> int:
    """Serve the repositories under the configured root on `port` (default: the
    configured `board_port`) until interrupted; 0 picks a free port."""
    os.environ.setdefault("SERVICE_VERSION", __version__)
    try:
        configure(_SERVICE_NAME)
    except ValueError as refusal:
        print(f"ERROR: {refusal}", file=sys.stderr)
        return _REFUSED_EXIT_CODE
    try:
        discovered_boards()
        port = _listening_port(port)
    except (RepositoriesUnavailableError, protocol.ClaimError) as refusal:
        print(f"ERROR: {refusal}", file=sys.stderr)
        return _REFUSED_EXIT_CODE
    boards = Boards(discovered_boards)
    try:
        token = board_token(token_path(os.environ, Path.home()))
    except MalformedTokenFileError as error:
        print(f"ERROR: {error}; delete it to start with a new one", file=sys.stderr)
        return 1
    try:
        running = start_board(port, boards, token)
    except OSError as error:
        print(
            f"ERROR: cannot listen on {LOOPBACK_HOST}:{port}: {error.strerror}",
            file=sys.stderr,
        )
        return 1
    except StaticAssetsMissingError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    try:
        _serve_until_stopped(running)
    finally:
        running.httpd.server_close()
    _LOGGER.info("server_process.finished")
    return 0
