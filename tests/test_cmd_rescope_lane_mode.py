"""`aco rescope` in lane mode on a branch outside `docs/` and `fix/`, on real
temporary git worktrees and the real state ref. The forge is the only fake."""

from __future__ import annotations

from pathlib import Path

import pytest
from board_fixtures import REPOSITORY
from claim_worktrees import (
    OUTSIDE_LANE_BRANCH,
    StandIn,
    issueless_lane_refusal,
    lane_held_by_ada,
    make_stand_in,
    standing_claims,
)
from cli_fixtures import run_cli
from store_fixtures import state_ref_tip

TRUNK_FILES = ("src/widget.py",)
HELD_SCOPE = ("src/widget.py",)
NEW_FILE = "src/new.py"


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


def lane_rescope_arguments(directory: Path) -> list[str]:
    """`aco rescope` without an item, as Ada adds `NEW_FILE` from `directory`."""
    return ["--repo", REPOSITORY, "rescope", "--agent", "Ada", "--add", f"{directory}/{NEW_FILE}"]


def test_a_rescope_adds_a_path_to_the_lane_claim_a_branch_outside_docs_and_fix_holds(
    stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: RESC-27, RESC-12."""
    standpoint = stand_in(
        branch=OUTSIDE_LANE_BRANCH, standing=lane_held_by_ada(OUTSIDE_LANE_BRANCH, HELD_SCOPE)
    )
    [before] = standing_claims(standpoint)

    result = run_cli(lane_rescope_arguments(standpoint.directory), capsys)

    [after] = standing_claims(standpoint)
    assert (result.status, result.stdout, result.stderr) == (
        0,
        f"RESCOPED lane {OUTSIDE_LANE_BRANCH}: {before.claim_id}\n",
        "",
    )
    assert (after.claim_id, after.scope) == (before.claim_id, (NEW_FILE, *HELD_SCOPE))


def test_a_rescope_on_a_branch_outside_docs_and_fix_no_lane_claim_holds_is_refused(
    stand_in: StandIn, bare_remote: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: RESC-27, CLM-07."""
    standpoint = stand_in(branch=OUTSIDE_LANE_BRANCH)
    tip_before = state_ref_tip(bare_remote)

    result = run_cli(lane_rescope_arguments(standpoint.directory), capsys)

    assert (result.status, result.stdout, result.stderr) == (
        2,
        "",
        issueless_lane_refusal(OUTSIDE_LANE_BRANCH),
    )
    assert state_ref_tip(bare_remote) == tip_before
