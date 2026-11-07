"""Start the decision board for every repository under the configured root,
one page and one URL for all of them. `aco serve` (`aco.cmd_serve`) parses the
command line and calls `serve`."""
# ruff: noqa: T201 - the board command line prints its URL and its refusals to the terminal

import contextlib
import os
import sys
from pathlib import Path

from .. import protocol, repositories
from .aco_source import AcoSource
from .board import Board, Boards, Found, RepositoriesUnavailableError, RepoUnavailable
from .server import LOOPBACK_HOST, start_board
from .static import StaticAssetsMissingError
from .token_store import MalformedTokenFileError, board_token, token_path

_REFUSED_EXIT_CODE = 2


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


def serve(port: int) -> int:
    """Serve the repositories under the configured root on `port` until
    interrupted; 0 picks a free port."""
    try:
        discovered_boards()
    except RepositoriesUnavailableError as refusal:
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
    print(running.url, flush=True)
    try:
        with contextlib.suppress(KeyboardInterrupt):
            running.httpd.serve_forever()
    finally:
        running.httpd.server_close()
    return 0
