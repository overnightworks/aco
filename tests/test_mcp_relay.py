"""The process an agent host starts for `aco mcp` (`specs/mcp.spec.md`, MCP-81,
MCP-82) through `cli.main(["mcp"])`: the fresh processes it hands each line to are
real, run from a copy of the package the test changes."""

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import relay_world
from mcp_lines import call_line, relay_mcp

from aco import mcp_relay

_PING = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})
_INITIALIZE = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
_NOTIFICATION = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
_RETRY = "if aco is being reinstalled, repeat the call once the install has finished"


@pytest.fixture
def package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The copy of the package the fresh processes load."""
    copy = relay_world.copy_package(tmp_path / "installed")
    monkeypatch.setenv("PYTHONPATH", str(copy.parent))
    return copy


def _broken(package: Path, code: str) -> None:
    """Appends `code` to the copy's `cmd_mcp`, which the fresh processes run."""
    with (package / "cmd_mcp.py").open("a", encoding="utf-8") as module:
        module.write(f"\n{code}\n")


def _version(answer: dict[str, Any]) -> str:
    return answer["result"]["serverInfo"]["version"]


def test_a_message_after_a_reinstall_is_answered_by_the_installed_code(
    package: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relay_world.set_version(package, "50.0.0")

    def reinstall() -> None:
        relay_world.set_version(package, "51.0.0")

    exit_code, answers = relay_mcp(
        monkeypatch,
        "",
        _INITIALIZE,
        reinstall,
        _INITIALIZE,
    )

    assert exit_code == 0
    assert [_version(answer) for answer in answers] == ["50.0.0", "51.0.0"]


def test_a_fresh_process_that_cannot_run_is_answered_and_the_relay_serves_on(
    package: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cmd_rule = package / "cmd_rule.py"
    original = cmd_rule.read_text(encoding="utf-8")

    def break_it() -> None:
        cmd_rule.write_text("def (:\n", encoding="utf-8")

    def repair() -> None:
        cmd_rule.write_text(original, encoding="utf-8")

    exit_code, answers = relay_mcp(
        monkeypatch,
        break_it,
        call_line(1),
        _PING,
        _NOTIFICATION,
        repair,
        _PING,
    )

    [tool_call, ping_failed, ping] = answers
    assert exit_code == 0
    assert tool_call["result"]["isError"] is True
    assert tool_call["result"]["content"][0]["text"].startswith("aco could not answer this call: ")
    assert tool_call["result"]["content"][0]["text"].endswith(_RETRY)
    assert (ping_failed["id"], ping_failed["error"]["code"]) == (2, -32603)
    assert ping_failed["error"]["message"].endswith(_RETRY)
    assert ping == {"jsonrpc": "2.0", "id": 2, "result": {}}
    assert "SyntaxError" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("def serve(requests, replies):\n    raise SystemExit(3)", "exit status 3"),
        ("def serve(requests, replies):\n    return None", "it answered nothing"),
    ],
    ids=["exits non-zero without a word", "exits 0 without an answer"],
)
def test_a_fresh_process_that_gives_no_answer_to_a_request_is_answered_with_its_reason(
    package: Path, monkeypatch: pytest.MonkeyPatch, code: str, reason: str
) -> None:
    _broken(package, code)

    _, [answer] = relay_mcp(monkeypatch, _PING, _NOTIFICATION)

    assert answer["error"]["message"].startswith(f"aco could not answer this call: {reason}; ")


def _relayed(line: str, **options: float) -> dict[str, Any]:
    replies = io.StringIO()
    mcp_relay.relay([line.encode() + b"\n"], replies, **options)
    return json.loads(replies.getvalue())


def test_a_fresh_process_that_runs_past_the_bound_is_answered_with_the_bound(
    package: Path,
) -> None:
    _broken(package, "def serve(requests, replies):\n    import time\n    time.sleep(120)")

    answer = _relayed(_PING, timeout=2.0)

    assert "it ran past 2 seconds; " in answer["error"]["message"]


def test_a_fresh_process_whose_answer_is_too_large_is_answered_with_that_reason(
    package: Path,
) -> None:
    _broken(package, "def serve(requests, replies):\n    replies.write('x' * (9 * 1024 * 1024))")

    answer = _relayed(_PING)

    assert "its answer was too large; " in answer["error"]["message"]


def test_a_fresh_process_that_cannot_start_is_answered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = str(tmp_path / "no-python")
    monkeypatch.setattr(sys, "executable", missing)

    answer = _relayed(_PING)

    assert missing in answer["error"]["message"]
