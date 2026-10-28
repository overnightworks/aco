"""How `aco next` and `aco board` report an item whose `whole` is not one bounded
line, on a real checkout and the real state ref. The forge is the only fake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from board_fixtures import complete_contract
from claim_worktrees import ISSUE, assert_no_item_body_written, serve_body
from cli_fixtures import run_cli
from github_fixtures import FakeForge, assert_github_world
from store_fixtures import state_ref_tip

DEFECT = "body malformed: whole: whole reason must be one bounded non-empty line"


@pytest.fixture
def malformed_whole(
    monkeypatch: pytest.MonkeyPatch, github_clone: Path, bare_remote: Path
) -> FakeForge:
    assert_github_world(github_clone, bare_remote)
    return serve_body(monkeypatch, complete_contract("Ship it.", scope=["a.py"], whole="x" * 513))


def test_next_names_an_item_with_a_malformed_whole_under_skipped(
    malformed_whole: FakeForge, bare_remote: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BODY-52, NEXT-36."""
    result = run_cli(["next"], capsys)

    assert (result.status, result.stdout.endswith(f"\nSKIPPED\n#{ISSUE}: {DEFECT}\n")) == (3, True)
    assert_no_item_body_written(malformed_whole)
    assert state_ref_tip(bare_remote) is None


def test_board_json_lists_an_item_with_a_malformed_whole_as_not_actionable(
    malformed_whole: FakeForge, bare_remote: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BODY-52, NEXT-36."""
    result = run_cli(["board", "--json"], capsys)

    row = next(row for row in json.loads(result.stdout)["items"] if row["number"] == ISSUE)
    assert (result.status, row["actionable"], row["actionable_reason"]) == (0, False, DEFECT)
    assert_no_item_body_written(malformed_whole)
    assert state_ref_tip(bare_remote) is None
