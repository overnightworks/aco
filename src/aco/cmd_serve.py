"""The `serve` command (`specs/serve.spec.md`)."""

import argparse

from . import protocol, report, usage
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


def add_parser(commands: usage.Subcommands, name: str) -> None:
    """`serve`'s parser and its own flag."""
    serve = commands.add_parser(name, help="serve the decision board")
    serve.add_argument(
        "--port",
        type=_port,
        default=None,
        metavar="N",
        help="loopback port to listen on; 0 picks a free one; default: board_port, else 0",
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
