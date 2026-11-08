"""The standard input of an `aco mcp` run and the `tools/call` lines it reads."""

import json
from collections.abc import Callable, Iterator


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
