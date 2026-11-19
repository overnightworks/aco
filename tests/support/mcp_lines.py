"""The standard input of an `aco mcp` run, the `tools/call` lines it reads and a run of
`aco mcp` over the board's test forge."""

import io
import json
import sys
from collections.abc import Callable, Iterator
from typing import Any

import board_forge
import pytest
from option_cards import ask_card

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


def ask_line(request_id: int, repository: str = "board-forge/here", item: int = 1) -> str:
    card = ask_card(question="Soll der Take danach markiert bleiben?")
    return call_line(request_id, "ask", {"repository": repository, "item": item, **card})


def run_mcp(
    monkeypatch: pytest.MonkeyPatch, *steps: str | bytes | Callable[[], None]
) -> tuple[int, list[dict[str, Any]]]:
    """The exit code and every answer line of `cli.main(["mcp"])` over the board's
    test forge, reading `steps` as its standard input."""
    replies = io.StringIO()
    with monkeypatch.context() as served:
        served.setattr(session, "run_context", board_forge.run_context)
        served.setattr(sys, "stdin", Script(*steps))
        served.setattr(sys, "stdout", replies)
        exit_code = cli.main(["mcp"])
    return exit_code, [json.loads(line) for line in replies.getvalue().splitlines()]


def serve_mcp(monkeypatch: pytest.MonkeyPatch, *lines: str) -> list[dict[str, Any]]:
    """Every answer line `aco mcp` writes for `lines`, which must end with exit code 0."""
    exit_code, replies = run_mcp(monkeypatch, *lines)
    assert exit_code == 0
    return replies
