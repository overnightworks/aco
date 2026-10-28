"""`aco release` in lane mode, whatever the branch's prefix, on real temporary
git worktrees and the real state ref. The forge is the only fake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY
from claim_worktrees import (
    OUTSIDE_LANE_BRANCH,
    StandIn,
    Standing,
    issueless_lane_refusal,
    lane_held_by_ada,
    make_stand_in,
    standing_claims,
)
from cli_fixtures import count_context_reads, run_cli
from store_fixtures import state_ref_tip

TRUNK_FILES = ("src/widget.py",)
HELD_SCOPE = ("src/widget.py",)
DOCS_BRANCH = "docs/x"
ISSUE_CLAIM_OF_BOB = Standing(HELD_SCOPE, issue=42, branch=OUTSIDE_LANE_BRANCH, agent="Bob")


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


def lane_release_arguments(*flags: str) -> list[str]:
    """`aco release` without an item, as Ada abandons the lane with `flags`."""
    return ["--repo", REPOSITORY, "release", "--agent", "Ada", *flags, "--abandoned", "stopped"]


@pytest.mark.parametrize(
    "standing",
    [
        pytest.param((), id="no-claim"),
        pytest.param((ISSUE_CLAIM_OF_BOB,), id="issue-claim-on-the-branch"),
    ],
)
def test_a_lane_release_on_a_branch_outside_docs_and_fix_without_a_lane_claim_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
    standing: tuple[Standing, ...],
) -> None:
    """Spec: REL-03, REL-57, CAS-53. Only a lane claim makes a branch outside
    `docs/` and `fix/` releasable; the refusal reads the state ref once."""
    stand_in(branch=OUTSIDE_LANE_BRANCH, standing=standing)
    tip_before = state_ref_tip(bare_remote)
    reads = count_context_reads(monkeypatch)

    result = run_cli(lane_release_arguments("--branch", OUTSIDE_LANE_BRANCH), capsys)

    assert (result.status, result.stdout, result.stderr) == (
        2,
        "",
        issueless_lane_refusal(OUTSIDE_LANE_BRANCH),
    )
    assert state_ref_tip(bare_remote) == tip_before
    assert sum(reads.observations.values()) == 1


@pytest.mark.parametrize(
    "branch_flags",
    [
        pytest.param(("--branch", OUTSIDE_LANE_BRANCH), id="named-branch"),
        pytest.param((), id="checkout-branch"),
    ],
)
def test_a_lane_release_releases_the_lane_claim_a_branch_outside_docs_and_fix_holds(
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    branch_flags: tuple[str, ...],
) -> None:
    """Spec: REL-57, REL-04. Whatever the prefix, the lane claim the branch
    holds is the one released; the branch is the named one, else the checkout's."""
    standpoint = stand_in(
        branch=OUTSIDE_LANE_BRANCH, standing=lane_held_by_ada(OUTSIDE_LANE_BRANCH, HELD_SCOPE)
    )

    result = run_cli([*lane_release_arguments(*branch_flags), "--json"], capsys)

    released = json.loads(result.stdout)
    assert (result.status, result.stderr) == (0, "")
    assert (released["ok"], released["reason"], released["lane"]) == (True, "abandoned", True)
    assert standing_claims(standpoint) == []


def test_a_lane_release_on_a_docs_branch_reads_the_state_ref_once(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: REL-03, CAS-53."""
    standpoint = stand_in(branch=DOCS_BRANCH, standing=lane_held_by_ada(DOCS_BRANCH, HELD_SCOPE))
    [held] = standing_claims(standpoint)
    reads = count_context_reads(monkeypatch)

    result = run_cli(lane_release_arguments("--branch", DOCS_BRANCH), capsys)

    assert (result.status, result.stdout, result.stderr) == (
        0,
        f"RELEASED lane {DOCS_BRANCH}: {held.claim_id}\n",
        "",
    )
    assert sum(reads.observations.values()) == 1
