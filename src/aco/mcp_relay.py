"""The process an agent host starts for `aco mcp` (`specs/mcp.spec.md`, MCP-81): it
holds no tool code and hands each message to a fresh `aco mcp --direct`, so a
reinstalled aco answers the next message and the host never has to reconnect."""

import sys
from collections.abc import Iterable
from typing import TextIO

from . import mcp_server, process

# A hung child must not hang the session forever; no tool call runs this long.
CHILD_TIMEOUT_SECONDS = 600.0
_RETRY_HINT = "if aco is being reinstalled, repeat the call once the install has finished"


def child_command() -> list[str]:
    """The command of the fresh process: this interpreter, which an in-place
    reinstall keeps, and `-P`, so no `aco` in the working directory shadows the
    installed one."""
    return [sys.executable, "-P", "-m", "aco", "mcp", "--direct"]


def relay(
    requests: Iterable[bytes], replies: TextIO, *, timeout: float = CHILD_TIMEOUT_SECONDS
) -> None:
    """Hand each line of `requests` to a fresh process, which may run `timeout`
    seconds, and write its answer on `replies` until the lines end; a line the
    fresh process cannot answer is answered with the reason."""
    mcp_server.answer_lines(requests, replies, lambda request: _answer(request, timeout))


def _answer(request: bytes, timeout: float) -> str | None:
    try:
        result = process.run_bounded_captured(child_command(), input_data=request, timeout=timeout)
    except process.ProcessError as error:
        return _unanswered(request, _reason(error, timeout))
    stderr = result.stderr.decode("utf-8", errors="replace")
    sys.stderr.write(stderr)
    if result.exit_status != 0:
        lines = stderr.strip().splitlines()
        return _unanswered(request, lines[-1] if lines else f"exit status {result.exit_status}")
    answer = result.stdout.decode("utf-8", errors="replace")
    if not answer.strip():
        return _unanswered(request, "it answered nothing")
    return answer


def _reason(error: process.ProcessError, timeout: float) -> str:
    if isinstance(error, process.ProcessTimedOutError):
        return f"it ran past {timeout:g} seconds"
    if isinstance(error, process.ProcessOutputTooLargeError):
        return "its answer was too large"
    return str(error) or type(error).__name__


def _unanswered(request: bytes, reason: str) -> str | None:
    return mcp_server.unanswered_reply(
        request.decode("utf-8", errors="replace"),
        f"aco could not answer this call: {reason}; {_RETRY_HINT}",
    )
