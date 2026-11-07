"""`aco mcp` (`specs/mcp.spec.md`) as a real child process over pipes, its forge
the board's test forge."""

import io
import json
import os
import select
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import IO, Any, cast

import board_forge
import pytest
from discovery_fixtures import (
    configure_root,
    isolate_config_file,
    repository_with_card,
    write_config,
)
from option_cards import open_option_entry

from aco import cli, session

_WAIT_SECONDS = 30
_CHILD_PROGRAM = (
    "import board_forge, sys; from aco import cli, session; "
    "session.run_context = board_forge.run_context; raise SystemExit(cli.main(['mcp']))"
)


@pytest.fixture(autouse=True)
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return isolate_config_file(tmp_path, monkeypatch)


@pytest.fixture
def root(tmp_path: Path, config_file: Path) -> Path:
    return configure_root(tmp_path, config_file)


@pytest.fixture(autouse=True)
def _empty_global_git_config(isolated_global_git_config: Path) -> None:
    """Real git in the child reads an empty global configuration."""


@dataclass
class _Child:
    process: subprocess.Popen[str]

    @property
    def stdin(self) -> IO[str]:
        return cast("IO[str]", self.process.stdin)

    @property
    def stdout(self) -> IO[str]:
        return cast("IO[str]", self.process.stdout)

    def send(self, message: dict[str, object] | str) -> None:
        self.stdin.write((message if isinstance(message, str) else json.dumps(message)) + "\n")
        self.stdin.flush()

    def receive(self) -> dict[str, Any]:
        ready, _, _ = select.select([self.stdout], [], [], _WAIT_SECONDS)
        assert ready, "the child answered nothing in time"
        return json.loads(self.stdout.readline())

    def ask(
        self, request_id: int, method: str, params: dict[str, object] | None = None
    ) -> dict[str, Any]:
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        answer = self.receive()
        assert answer["id"] == request_id
        return answer

    def read_inbox(self, request_id: int) -> dict[str, Any]:
        answer = self.ask(request_id, "tools/call", {"name": "read_inbox", "arguments": {}})
        return answer["result"]


@contextmanager
def _started() -> Iterator[_Child]:
    child_environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(Path(board_forge.__file__).parent), os.environ.get("PYTHONPATH", "")]
        ),
    }
    process = subprocess.Popen(  # noqa: S603 - the interpreter running these tests
        [sys.executable, "-c", _CHILD_PROGRAM],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_environment,
    )
    child = _Child(process)
    try:
        yield child
    finally:
        process.kill()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        process.wait(timeout=_WAIT_SECONDS)


def _finish(child: _Child) -> tuple[int, str, str]:
    """End the child by closing its stdin: its exit code, the rest of its
    stdout and its stderr."""
    child.stdin.close()
    rest = child.stdout.read()
    stderr = cast("IO[str]", child.process.stderr).read()
    return child.process.wait(timeout=_WAIT_SECONDS), rest, stderr


def test_a_session_lists_the_tool_and_reads_the_waiting_lines_of_every_repository(
    root: Path,
) -> None:
    repository_with_card(root / "here", 1, "Here")
    elsewhere = repository_with_card(root / "group" / "elsewhere", 2, "Elsewhere")
    ruled = {**open_option_entry(), "ruling": "A", "ruled_on": date(2026, 10, 28), "via": "board"}
    elsewhere.put_item(3, board_forge.item_body(ruled), title="Ruled")

    with _started() as child:
        initialized = child.ask(1, "initialize", {"protocolVersion": "2025-06-18"})
        child.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        child.send("")
        listed = child.ask(2, "tools/list")
        inbox = child.read_inbox(3)
        exit_code, rest, stderr = _finish(child)

    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    assert [tool["name"] for tool in listed["result"]["tools"]] == ["read_inbox"]
    assert inbox["isError"] is False
    structured = inbox["structuredContent"]
    assert structured["root"] == str(root)
    assert [
        (entry["repository"], [item["number"] for item in entry["items"]])
        for entry in structured["repositories"]
    ] == [("board-forge/elsewhere", [2]), ("board-forge/here", [1])]
    assert structured["unreadable"] == []
    assert (exit_code, rest, stderr) == (0, "", "")


class _Script:
    """Standard input that hands out its lines one by one and runs each
    callable between two of them, so the world changes while the server waits."""

    def __init__(self, *steps: str | Callable[[], None]) -> None:
        self._steps = steps

    def __iter__(self) -> Iterator[str]:
        for step in self._steps:
            if callable(step):
                step()
            else:
                yield step + "\n"


def _call_line(request_id: int) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "read_inbox"},
        }
    )


def _arrive(root: Path) -> None:
    repository_with_card(root / "arrived", 1, "Arrived")


def _serve_in_process(
    monkeypatch: pytest.MonkeyPatch, *steps: str | Callable[[], None]
) -> tuple[int, list[dict[str, Any]]]:
    """`aco mcp` through its entry point over the board's test forge: the exit
    code and every answer line."""
    replies = io.StringIO()
    monkeypatch.setattr(session, "run_context", board_forge.run_context)
    monkeypatch.setattr(sys, "stdin", _Script(*steps))
    monkeypatch.setattr(sys, "stdout", replies)
    exit_code = cli.main(["mcp"])
    return exit_code, [json.loads(line) for line in replies.getvalue().splitlines()]


def test_every_call_scans_afresh_and_a_refusal_is_a_tool_error_the_next_call_recovers_from(
    root: Path, config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_text = config_file.read_text(encoding="utf-8")
    config_file.unlink()

    exit_code, answers = _serve_in_process(
        monkeypatch,
        "",
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        _call_line(1),
        lambda: write_config(config_file, config_text),
        _call_line(2),
        lambda: _arrive(root),
        _call_line(3),
    )

    missing, empty, found = (answer["result"] for answer in answers)
    assert (exit_code, missing["isError"]) == (0, True)
    assert str(config_file) in missing["content"][0]["text"]
    assert empty["isError"] is True
    assert str(root) in empty["content"][0]["text"]
    assert [entry["repository"] for entry in found["structuredContent"]["repositories"]] == [
        "board-forge/arrived"
    ]


def test_a_repository_whose_read_fails_is_listed_as_unavailable_beside_the_others(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_with_card(root / "good", 1, "Good")
    repository_with_card(root / "broken", 2, "Broken").fail_listing("the forge is down")

    _, [answer] = _serve_in_process(monkeypatch, _call_line(1))

    assert [
        (entry["repository"], entry.get("unavailable"))
        for entry in answer["result"]["structuredContent"]["repositories"]
    ] == [("board-forge/broken", "the forge is down"), ("board-forge/good", None)]


class _ClosedPipe(io.StringIO):
    """Standard output whose reader is gone, over a descriptor the test owns."""

    def __init__(self, descriptor: int) -> None:
        super().__init__()
        self._descriptor = descriptor

    def write(self, text: str) -> int:
        raise BrokenPipeError

    def fileno(self) -> int:
        return self._descriptor


def test_a_broken_pipe_ends_the_server_with_exit_0(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_with_card(root / "here", 1, "Here")
    read_end, write_end = os.pipe()
    os.close(read_end)
    monkeypatch.setattr(session, "run_context", board_forge.run_context)
    monkeypatch.setattr(sys, "stdin", _Script(_call_line(1)))
    monkeypatch.setattr(sys, "stdout", _ClosedPipe(write_end))
    try:
        exit_code = cli.main(["mcp"])
    finally:
        os.close(write_end)

    assert exit_code == 0


def test_a_host_that_closed_its_pipe_ends_the_server_without_a_traceback() -> None:
    with _started() as child:
        child.stdout.close()
        child.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        child.stdin.close()
        stderr = cast("IO[str]", child.process.stderr).read()
        exit_code = child.process.wait(timeout=_WAIT_SECONDS)

    assert (exit_code, stderr) == (0, "")


def test_the_global_repo_is_refused_before_anything_is_served(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(["--repo", "owner/name", "mcp"])

    captured = capsys.readouterr()
    assert (exit_code, captured.out) == (2, "")
    assert (
        captured.err
        == "ERROR: aco mcp finds its repositories itself; --repo does not apply to it\n"
    )
