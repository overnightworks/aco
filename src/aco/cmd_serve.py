"""The `serve` command (`specs/serve.spec.md`)."""

import argparse

from . import protocol, report
from .session import RunContext

_HIGHEST_PORT = 65535
_GLOBAL_REPO_MESSAGE = "aco serve finds its repositories itself; --repo does not apply to it"


def _port(text: str) -> int:
    try:
        port = int(text)
    except ValueError:
        port = -1
    if not 0 <= port <= _HIGHEST_PORT:
        raise argparse.ArgumentTypeError(f"{text!r} is not a port between 0 and {_HIGHEST_PORT}")
    return port


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """`serve`'s own flag."""
    parser.add_argument(
        "--port",
        type=_port,
        default=0,
        metavar="N",
        help="loopback port to listen on; 0 (default) picks a free one",
    )


def run(parsed: argparse.Namespace, _context: RunContext) -> int:
    """Start the decision board. The board builds its own context for every
    read and write of each repository it serves, so this one stays unused."""
    if parsed.repo is not None:
        return report.render_error(protocol.ClaimError(_GLOBAL_REPO_MESSAGE))
    # Imported here: only `serve` needs the board package, and loading it for
    # every `aco` call costs startup time.
    from .board import cli as board_cli  # noqa: PLC0415

    return board_cli.serve(parsed.port)
