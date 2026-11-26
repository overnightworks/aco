"""`aco mcp`'s `read_startable` tool (`specs/mcp.spec.md`) against `aco board --json`
(`specs/board.spec.md`), both run through the real CLI over real checkouts with bare
remotes under one configured root; the forge is the only fake."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from audit_world import entry_toml
from board_fixtures import board_issue, complete_contract, slice_entries
from cli_fixtures import init_bare_repository, real_git, run_cli, set_git_identity
from discovery_fixtures import discovered_checkout, unreadable_checkout
from github_fixtures import FakeForge
from mcp_lines import call_line, serve_mcp

from aco import forge, github, protocol, workboard
from aco.body import ItemKind

pytestmark = pytest.mark.usefixtures("config_file", "isolated_global_git_config")

_READ_STARTABLE = call_line(1, "read_startable")
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

    def add(self, name: str, fake: FakeForge, board_config: str = "") -> Path:
        self.forges[f"example/{name}"] = fake
        return discovered_checkout(
            self.root / name,
            f"https://github.com/example/{name}",
            init_bare_repository(self.bare_parent / f"{name}.git"),
            board_config,
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


def _busy() -> FakeForge:
    return FakeForge(
        board_issues=(
            board_issue(7, "Work", complete_contract("Do the work.", size="M")),
            board_issue(8, "Urgent work", complete_contract("Do it first."), labels=("p1",)),
            board_issue(
                9,
                "Epic",
                complete_contract("Cut it.", slice=slice_entries("First slice", "Second slice")),
                kind=ItemKind.CONTAINER,
                children_closed=0,
                children_total=0,
            ),
        ),
    )


def _board_ready_now(
    directory: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> list[dict[str, Any]]:
    """What `aco board --json` lists as `ready_now` run in `directory`."""
    monkeypatch.chdir(directory)
    return json.loads(run_cli(["board", "--json"], capsys).stdout)["ready_now"]


def _read_startable(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    [answer] = serve_mcp(monkeypatch, _READ_STARTABLE, run_context=None)
    result = answer["result"]
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    return result["structuredContent"]


def _by_repository(structured: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["repository"]: entry for entry in structured["repositories"]}


def test_every_startable_item_is_listed_in_rank_order_and_an_empty_board_answers_empty_lists(
    fleet: _Fleet, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: MCP-95, MCP-96"""
    busy = fleet.add("busy", _busy())
    fleet.add("idle", FakeForge())
    ready_now = _board_ready_now(busy, monkeypatch, capsys)

    structured = _read_startable(monkeypatch)

    answered = _by_repository(structured)
    assert structured["root"] == str(fleet.root)
    assert [item["number"] for item in answered["example/busy"]["startable"]] == [
        item["number"] for item in ready_now
    ]
    assert len(ready_now) > 1
    assert {
        "number": 7,
        "title": "Work",
        "kind": None,
        "size": "M",
        "priority_bucket": "unlabelled",
        "next": "Do the work.",
    } in answered["example/busy"]["startable"]
    assert answered["example/idle"] == {
        "repository": "example/idle",
        "startable": [],
        "uncut": [],
        "audits_due": [],
    }
    assert structured["unreadable"] == []


def test_a_container_with_uncut_slices_and_a_due_audit_are_named(
    fleet: _Fleet, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: MCP-97"""
    fleet.add("busy", _busy(), entry_toml())

    answered = _by_repository(_read_startable(monkeypatch))["example/busy"]

    assert answered["uncut"] == [{"item": 9, "index": 1, "title": "First slice", "rows": 2}]
    assert answered["audits_due"] == ["scenario"]


def test_a_repository_whose_board_is_refused_is_unavailable_with_the_sentence_beside_the_others(
    fleet: _Fleet, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: MCP-98"""
    fleet.add("down", _DownForge())
    fleet.add("ready", _work())

    structured = _read_startable(monkeypatch)

    assert [
        (entry["repository"], entry.get("unavailable"), "startable" in entry)
        for entry in structured["repositories"]
    ] == [("example/down", _FORGE_DOWN, False), ("example/ready", None, True)]


def test_a_checkout_discovery_cannot_read_is_listed_as_unreadable(
    fleet: _Fleet, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: MCP-95"""
    fleet.add("ready", _work())
    broken = unreadable_checkout(fleet.root / "broken", "https://github.com/example/broken.git")

    structured = _read_startable(monkeypatch)

    assert [entry["directory"] for entry in structured["unreadable"]] == [str(broken)]
    assert [entry["repository"] for entry in structured["repositories"]] == ["example/ready"]


def test_reading_writes_nothing_and_a_repeat_answers_the_same(
    fleet: _Fleet, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: MCP-95"""
    busy = _busy()
    fleet.add("busy", busy)
    refs_before = fleet.refs()

    first = _read_startable(monkeypatch)
    second = _read_startable(monkeypatch)

    assert fleet.refs() == refs_before
    assert (busy.body_writes, busy.added_labels, busy.created_issues) == ([], [], [])
    assert second == first
