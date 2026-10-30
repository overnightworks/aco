"""The `serve` command (`specs/serve.spec.md`)."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import protocol, report
from .session import RunContext

_HIGHEST_PORT = 65535
_GLOBAL_REPO_MESSAGE = "aco serve reads checkout directories; pass them as aco serve --repo PATH"


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


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """`serve`'s own flags. `--repo PATH` is stored as `paths`, beside the
    global `--repo OWNER/REPO` that stays in `repo`."""
    parser.add_argument(
        "--port",
        type=_port,
        default=0,
        metavar="N",
        help="loopback port to listen on; 0 (default) picks a free one",
    )
    parser.add_argument(
        "--repo",
        dest="paths",
        type=_directory,
        action="append",
        metavar="PATH",
        help="a checkout directory to serve, labelled by its name (repeatable); "
        "without it, the current directory",
    )


def run(parsed: argparse.Namespace, _context: RunContext) -> int:
    """Start the decision board. The board builds its own context for every
    read and write of each repository it serves, so this one stays unused."""
    if parsed.repo is not None:
        return report.render_error(protocol.ClaimError(_GLOBAL_REPO_MESSAGE))
    # Imported here: only `serve` needs the board package, and loading it for
    # every `aco` call costs startup time.
    from .board import cli as board_cli  # noqa: PLC0415

    return board_cli.serve(parsed.port, parsed.paths or [Path.cwd()])
