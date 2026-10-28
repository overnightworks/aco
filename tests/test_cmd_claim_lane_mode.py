"""`aco claim` in lane mode on a branch outside `docs/` and `fix/`, on real
temporary git worktrees and the real state ref. The forge is the only fake."""

from __future__ import annotations

from pathlib import Path

import pytest
from claim_worktrees import (
    OUTSIDE_LANE_BRANCH,
    StandIn,
    Standing,
    claim,
    issueless_lane_refusal,
    lane_held_by_ada,
    make_stand_in,
    standing_claims,
)
from store_fixtures import state_ref_tip

TRUNK_FILES = ("src/widget.py",)
HELD_SCOPE = ("src/widget.py",)


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


@pytest.mark.parametrize(
    "standing",
    [
        pytest.param((), id="no-claim"),
        pytest.param(lane_held_by_ada(OUTSIDE_LANE_BRANCH, HELD_SCOPE), id="own-lane-claim"),
    ],
)
def test_a_lane_claim_outside_docs_and_fix_is_refused_whether_or_not_a_lane_claim_holds_the_branch(
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
    standing: tuple[Standing, ...],
) -> None:
    """Spec: CLM-07. A claim names an issue or sits on a `docs/` or `fix/`
    branch; a lane claim already on the branch does not make it claimable."""
    standpoint = stand_in(branch=OUTSIDE_LANE_BRANCH, standing=standing)
    tip_before = state_ref_tip(bare_remote)
    held_before = standing_claims(standpoint)

    status = claim(scope=HELD_SCOPE, agent="Ada", issue=None)

    captured = capsys.readouterr()
    assert (status, captured.out, captured.err) == (
        2,
        "",
        issueless_lane_refusal(OUTSIDE_LANE_BRANCH),
    )
    assert state_ref_tip(bare_remote) == tip_before
    assert standing_claims(standpoint) == held_before
