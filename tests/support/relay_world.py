"""A copy of the aco package a test changes, and a real `aco mcp` process over pipes."""

import json
import select
import shutil
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, cast

import aco

_WAIT_SECONDS = 30


def copy_package(directory: Path) -> Path:
    """Copies the aco package into `directory`, which a process then finds first
    on its `PYTHONPATH`; returns the copy's package directory."""
    return Path(
        shutil.copytree(
            Path(aco.__file__).parent,
            directory / "aco",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    )


def set_version(package: Path, version: str) -> None:
    (package / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")


class Relay:
    """A started `aco mcp` process: a request line out, one answer line back."""

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self.process = process
        self.stdin = cast("IO[str]", process.stdin)
        self.stdout = cast("IO[str]", process.stdout)

    def send(self, message: dict[str, object]) -> None:
        self.stdin.write(json.dumps(message) + "\n")
        self.stdin.flush()

    def ask(
        self, request_id: int, method: str, params: dict[str, object] | None = None
    ) -> dict[str, Any]:
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        ready, _, _ = select.select([self.stdout], [], [], _WAIT_SECONDS)
        assert ready, "the relay answered nothing in time"
        answer = json.loads(self.stdout.readline())
        assert answer["id"] == request_id
        return answer

    def finish(self) -> tuple[int, str]:
        """Closes standard input; the exit code and everything on standard error."""
        self.stdin.close()
        stderr = cast("IO[str]", self.process.stderr).read()
        return self.process.wait(timeout=_WAIT_SECONDS), stderr


@contextmanager
def started(command: Sequence[str], environment: dict[str, str]) -> Iterator[Relay]:
    process = subprocess.Popen(  # noqa: S603 - the interpreter running these tests
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        yield Relay(process)
    finally:
        process.kill()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        process.wait(timeout=_WAIT_SECONDS)
