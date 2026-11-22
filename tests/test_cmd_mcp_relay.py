"""`aco mcp`, the process an agent host starts (`specs/mcp.spec.md`, MCP-81 to
MCP-84), over real pipes: one relay process lives across a reinstall."""

import os
import sys
from pathlib import Path

import relay_world


def _environment(package: Path) -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(package.parent)}


def test_one_relay_answers_from_the_installed_code_before_and_after_a_reinstall(
    tmp_path: Path,
) -> None:
    package = relay_world.copy_package(tmp_path)
    relay_world.set_version(package, "50.0.0")
    command = [sys.executable, "-P", "-m", "aco", "mcp"]

    with relay_world.started(command, _environment(package)) as relay:
        before = relay.ask(1, "initialize")
        relay_world.set_version(package, "51.0.0")
        after = relay.ask(2, "initialize")
        listed = relay.ask(3, "tools/list")
        exit_code, stderr = relay.finish()

    assert before["result"]["serverInfo"]["version"] == "50.0.0"
    assert after["result"]["serverInfo"]["version"] == "51.0.0"
    assert len(listed["result"]["tools"]) > 0
    assert (exit_code, stderr) == (0, "")


def test_a_broken_install_is_answered_loudly_and_the_next_call_after_the_repair_works(
    tmp_path: Path,
) -> None:
    package = relay_world.copy_package(tmp_path)
    broken = package / "cmd_rule.py"
    original = broken.read_text(encoding="utf-8")
    command = [sys.executable, "-P", "-m", "aco", "mcp"]

    with relay_world.started(command, _environment(package)) as relay:
        assert relay.ask(0, "ping")["result"] == {}
        broken.write_text("def (:\n", encoding="utf-8")
        refused = relay.ask(1, "tools/call", {"name": "read_inbox"})
        ping = relay.ask(2, "ping")
        broken.write_text(original, encoding="utf-8")
        repaired = relay.ask(3, "ping")

    assert refused["result"]["isError"] is True
    assert ping["error"]["code"] == -32603
    assert repaired["result"] == {}


def test_a_host_that_closed_its_pipe_ends_the_relay_without_a_traceback(tmp_path: Path) -> None:
    package = relay_world.copy_package(tmp_path)
    command = [sys.executable, "-P", "-m", "aco", "mcp"]

    with relay_world.started(command, _environment(package)) as relay:
        relay.stdout.close()
        relay.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        exit_code, stderr = relay.finish()

    assert (exit_code, stderr) == (0, "")
