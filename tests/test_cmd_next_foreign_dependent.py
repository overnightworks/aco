"""`aco next` scores an item for each open item that names it as a blocker, in
any repository, and ranks it as a blocker (NEXT-72)."""

from dataclasses import replace

import pytest
from board_fixtures import board_issue, complete_contract
from cli_fixtures import freeze_cli_now, run_cli
from github_fixtures import FakeForge, serve_forge

ROOT = 10
CLEANUP = 11


def _serve_root_with_foreign_dependent(monkeypatch: pytest.MonkeyPatch) -> None:
    root = replace(board_issue(ROOT, "Root", complete_contract("Claim #10.")), open_dependents=1)
    cleanup = board_issue(CLEANUP, "Cleanup", complete_contract("Claim #11."), labels=("cleanup",))
    freeze_cli_now(monkeypatch)
    serve_forge(monkeypatch, FakeForge(board_issues=(cleanup, root)))


@pytest.mark.usefixtures("github_world")
def test_next_ranks_an_item_with_a_foreign_open_dependent_first_with_twenty_added(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: NEXT-72"""
    _serve_root_with_foreign_dependent(monkeypatch)

    result = run_cli(["next"], capsys)

    assert (result.status, result.stdout.splitlines()[0]) == (0, "#10 score 10: Root")
