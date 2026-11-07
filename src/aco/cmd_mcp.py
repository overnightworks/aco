"""The `mcp` command (`specs/mcp.spec.md`): the stdio loop and the inbox read
it serves."""

import argparse
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

from . import inbox, mcp_server, protocol, report, repositories, rulings, session, usage
from .session import RunContext

_GLOBAL_REPO_MESSAGE = "aco mcp finds its repositories itself; --repo does not apply to it"


def _repository_rows(repository: repositories.Repository) -> tuple[rulings.Row, ...]:
    # Looked up on the module at every call, so a replaced `run_context` (the
    # board's test forge) reaches every read.
    context = session.run_context(None).for_directory(repository.directory)
    issues = context.forge.list_open_board_issues()
    return inbox.rows(issues, storage=context.config.storage)


def read_inbox() -> dict[str, object]:
    """One fresh scan of the configured root and the read of every repository
    found; refused, naming the file or the root, when there is none to read."""
    root = repositories.configured_root(repositories.config_path(os.environ, Path.home()))
    discovery = repositories.discover(root)
    if not discovery.repositories:
        reasons = "; ".join(f"{entry.directory}: {entry.reason}" for entry in discovery.unavailable)
        raise protocol.ClaimError(f"no repository could be read under {root} ({reasons})")
    return inbox.inbox_json(inbox.read(discovery, _repository_rows))


def serve(requests: Iterable[bytes], replies: TextIO) -> None:
    """Answer each line of `requests` on `replies` until the lines end; a line
    that is no UTF-8 is answered as unparsable."""
    for request in requests:
        if not request.strip():
            continue
        try:
            answer = mcp_server.reply(request.decode("utf-8"), read_inbox)
        except UnicodeDecodeError:
            answer = mcp_server.unparsable_reply()
        if answer is not None:
            replies.write(answer + "\n")
            replies.flush()


def add_parser(commands: usage.Subcommands, name: str) -> None:
    """`mcp`'s parser: it takes no flags."""
    commands.add_parser(name, help="serve the operator's inbox to an agent host over MCP on stdio")


def run(parsed: argparse.Namespace, _context: RunContext) -> int:
    """Serve the MCP protocol on stdin and stdout until stdin ends."""
    if parsed.repo is not None:
        return report.render_error(protocol.ClaimError(_GLOBAL_REPO_MESSAGE))
    try:
        serve(sys.stdin.buffer, sys.stdout)
    except BrokenPipeError:
        # The host closed the pipe; the interpreter's own flush at exit must not
        # fail on it either.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    return 0
