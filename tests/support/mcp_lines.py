"""The standard input of an `aco mcp` run, the `tools/call` lines it reads and a run of
`aco mcp` over the board's test forge."""

import io
import json
import sys
from collections.abc import Callable, Iterator
from typing import Any

import board_forge
import pytest

from aco import cli, session


class Script:
    """Standard input that hands out its lines one by one and runs each
    callable between two of them, so the world changes while the server waits."""

    def __init__(self, *steps: str | bytes | Callable[[], None]) -> None:
        self._steps = steps

    @property
    def buffer(self) -> Iterator[bytes]:
        for step in self._steps:
            if callable(step):
                step()
            elif isinstance(step, bytes):
                yield step + b"\n"
            else:
                yield step.encode() + b"\n"


def call_line(
    request_id: int, name: str = "read_inbox", arguments: dict[str, object] | None = None
) -> str:
    params: dict[str, object] = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": params}
    )


def serve_mcp(monkeypatch: pytest.MonkeyPatch, *lines: str) -> list[dict[str, Any]]:
    """Every answer line `aco mcp` writes for `lines`, run through `cli.main(["mcp"])`
    over the board's test forge, which must end with exit code 0."""
    replies = io.StringIO()
    with monkeypatch.context() as served:
        served.setattr(session, "run_context", board_forge.run_context)
        served.setattr(sys, "stdin", Script(*lines))
        served.setattr(sys, "stdout", replies)
        assert cli.main(["mcp"]) == 0
    return [json.loads(line) for line in replies.getvalue().splitlines()]
