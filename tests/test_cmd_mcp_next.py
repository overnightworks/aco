"""`aco mcp`'s `read_next` tool (`specs/mcp.spec.md`) against `aco next --json`
(`specs/next.spec.md`), both run through the real CLI over real checkouts with bare
remotes under one configured root; the forge is the only fake."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from board_fixtures import board_issue, complete_contract
from cli_fixtures import init_bare_repository, real_git, run_cli, set_git_identity
from discovery_fixtures import discovered_checkout, unreadable_checkout
from github_fixtures import FakeForge
from mcp_lines import call_line, serve_mcp

from aco import forge, github, protocol, workboard

pytestmark = pytest.mark.usefixtures("config_file", "isolated_global_git_config")

_READ_NEXT = call_line(1, "read_next")
_FORGE_DOWN = "the forge is down"


@dataclass
class _DownForge(FakeForge):
    def list_open_board_issues(self) -> tuple[workboard.Issue, ...]:
        raise protocol.ClaimError(_FORGE_DOWN)


@dataclass
class _Fleet:
    """The repositories under the configured root, each a real checkout with its own
    bare remote and the fake forge that answers for it."""

    root: Path
    bare_parent: Path
    forges: dict[str, FakeForge] = field(default_factory=dict)

    def add(self, name: str, fake: FakeForge) -> Path:
        self.forges[f"example/{name}"] = fake
        return discovered_checkout(
            self.root / name,
            f"https://github.com/example/{name}",
            init_bare_repository(self.bare_parent / f"{name}.git"),
            "",
        )

    def refs(self) -> list[str]:
        return [
            real_git(directory, "for-each-ref").stdout
            for directory in (*self.root.iterdir(), *self.bare_parent.iterdir())
            if directory.is_dir()
        ]


@pytest.fixture
def fleet(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Fleet:
    set_git_identity(monkeypatch)
    bare_parent = tmp_path / "remotes"
    bare_parent.mkdir()
    world = _Fleet(root, bare_parent)

    def forge_of(repository: forge.RepositoryId) -> FakeForge:
        return world.forges[repository.path]

    monkeypatch.setattr(github, "GitHubForge", forge_of)
    return world


def _work() -> FakeForge:
    return FakeForge(
        board_issues=(board_issue(7, "Work", complete_contract("Do the work.")),),
    )


def _next_in(
    directory: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> dict[str, Any]:
    """What `aco next --json` prints run in `directory`."""
    monkeypatch.chdir(directory)
    return json.loads(run_cli(["next", "--json"], capsys).stdout)


def _read_next(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    [answer] = serve_mcp(monkeypatch, _READ_NEXT, run_context=None)
    result = answer["result"]
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    return result["structuredContent"]


def test_each_repository_answers_what_aco_next_prints_in_its_checkout(
    fleet: _Fleet, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: MCP-95, MCP-96, NEXT-75"""
    idle = fleet.add("idle", FakeForge())
    ready = fleet.add("ready", _work())
    expected = {
        "example/idle": _next_in(idle, monkeypatch, capsys),
        "example/ready": _next_in(ready, monkeypatch, capsys),
    }

    structured = _read_next(monkeypatch)

    assert structured["root"] == str(fleet.root)
    assert {entry["repository"]: entry["next"] for entry in structured["repositories"]} == expected
    assert [payload["reason"] for payload in expected.values()] == [
        "nothing_actionable",
        "work_item",
    ]
    assert structured["unreadable"] == []


def test_a_repository_whose_board_is_refused_is_unavailable_with_the_sentence_beside_the_others(
    fleet: _Fleet, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: MCP-97"""
    down = fleet.add("down", _DownForge())
    ready = fleet.add("ready", _work())
    refused = _next_in(down, monkeypatch, capsys)

    structured = _read_next(monkeypatch)

    assert [
        (entry["repository"], entry.get("unavailable")) for entry in structured["repositories"]
    ] == [("example/down", refused["message"]), ("example/ready", None)]
    assert structured["repositories"][1]["next"] == _next_in(ready, monkeypatch, capsys)
    assert refused["message"] == _FORGE_DOWN


def test_a_checkout_discovery_cannot_read_is_listed_as_unreadable(
    fleet: _Fleet, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: MCP-95"""
    fleet.add("ready", _work())
    broken = unreadable_checkout(fleet.root / "broken", "https://github.com/example/broken.git")

    structured = _read_next(monkeypatch)

    assert [entry["directory"] for entry in structured["unreadable"]] == [str(broken)]
    assert [entry["repository"] for entry in structured["repositories"]] == ["example/ready"]


def test_reading_writes_nothing_and_a_repeat_answers_the_same(
    fleet: _Fleet, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: MCP-96"""
    ready = _work()
    fleet.add("ready", ready)
    refs_before = fleet.refs()

    first = _read_next(monkeypatch)
    second = _read_next(monkeypatch)

    assert fleet.refs() == refs_before
    assert (ready.body_writes, ready.added_labels, ready.created_issues) == ([], [], [])
    assert second == first
