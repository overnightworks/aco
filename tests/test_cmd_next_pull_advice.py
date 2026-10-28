"""Where `aco next` advises `claim` and where `start`, and the claim it advises for a nested
container's one row, run as printed, on real checkouts. The forge is the only fake."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, board_issue, complete_contract
from cli_fixtures import (
    add_lane_worktree,
    arguments_bash_hands_aco,
    push_lane_branch,
    real_git,
    run_cli,
)
from github_fixtures import FakeForge, assert_github_world, serve_forge
from store_fixtures import publish_claims_from_a_second_clone

from aco import body, forge, store, workboard
from aco.workboard import ChildItem, ChildState, Issue

LANE_BRANCH = "codex/issue-72-claims"
NESTED = 299
NESTED_LANE_BRANCH = "codex/issue-299-nested-epic"
ROW_SCOPE = ("docs/nested.md", "src/it's here.py")
RUN_FROM_THE_PRIMARY = "Run: aco start 72 --slug=ship-it\n"
RUN_FROM_A_LANE = "Run: aco claim 72\n"


@pytest.fixture
def served_item(
    monkeypatch: pytest.MonkeyPatch, github_clone: Path, bare_remote: Path
) -> FakeForge:
    assert_github_world(github_clone, bare_remote)
    item = board_issue(72, "Ship it", complete_contract("Ship it.", scope=["a.py"]))
    return serve_forge(monkeypatch, FakeForge(board_issues=(item,)))


def lane_worktree(clone: Path, branch: str = LANE_BRANCH) -> Path:
    push_lane_branch(clone, branch)
    lane = clone.parent / "lane"
    add_lane_worktree(clone, lane, branch)
    return lane


def detached_lane(clone: Path) -> Path:
    lane = clone.parent / "detached"
    real_git(clone, "worktree", "add", "-q", "--detach", str(lane), "main")
    return lane


def trunk_lane(clone: Path) -> Path:
    real_git(clone, "checkout", "-q", "-b", "elsewhere")
    lane = clone.parent / "trunk-lane"
    real_git(clone, "worktree", "add", "-q", str(lane), "main")
    return lane


def primary_on_a_feature_branch(clone: Path) -> Path:
    real_git(clone, "checkout", "-q", "-b", "feature")
    return clone


@pytest.mark.usefixtures("served_item")
@pytest.mark.parametrize(
    ("arrange", "expected"),
    [
        pytest.param(lambda clone: clone, RUN_FROM_THE_PRIMARY, id="primary-on-the-trunk"),
        pytest.param(lane_worktree, RUN_FROM_A_LANE, id="linked-worktree-on-a-lane-branch"),
        pytest.param(
            primary_on_a_feature_branch, RUN_FROM_THE_PRIMARY, id="primary-on-a-feature-branch"
        ),
        pytest.param(detached_lane, RUN_FROM_THE_PRIMARY, id="detached-linked-worktree"),
        pytest.param(trunk_lane, RUN_FROM_THE_PRIMARY, id="linked-worktree-on-the-trunk-branch"),
    ],
)
def test_next_advises_claim_only_in_a_linked_worktree_on_a_lane_branch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    arrange: Callable[[Path], Path],
    expected: str,
) -> None:
    """Spec: NEXT-02, NEXT-41."""
    monkeypatch.chdir(arrange(github_clone))

    stdout = run_cli(["next"], capsys).expect_success()

    assert expected in stdout


def nested_contract(top_level_scope: tuple[str, ...] | None) -> str:
    row = [{"index": 1, "title": "Scheibe Z", "scope": list(ROW_SCOPE)}]
    if top_level_scope is None:
        return complete_contract("keiner", slice=row)
    return complete_contract("keiner", slice=row, scope=list(top_level_scope))


def nested_container(contract: str) -> Issue:
    return Issue(
        NESTED,
        "Nested epic",
        (),
        contract,
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=1,
        children_total=1,
    )


def serve_nested_container(monkeypatch: pytest.MonkeyPatch, nested: Issue) -> FakeForge:
    parent = workboard.ParentIssue(
        workboard.IssueReference(REPOSITORY, 298), "", body.ItemKind.CONTAINER
    )
    return serve_forge(
        monkeypatch,
        FakeForge(
            board_issues=(nested,),
            children={NESTED: (ChildItem(300, ChildState.CLOSED),)},
            parents={NESTED: parent},
        ),
    )


@pytest.mark.parametrize(
    ("top_level_scope", "expected_claim"),
    [
        pytest.param(
            None,
            "aco claim 299 --scope=docs/nested.md --scope='src/it'\"'\"'s here.py'",
            id="row-scope-only",
        ),
        pytest.param(("docs/top.md",), "aco claim 299", id="own-top-level-scope"),
    ],
)
def test_next_names_a_nested_rows_exact_scope_and_that_claim_runs_as_printed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
    tmp_path: Path,
    top_level_scope: tuple[str, ...] | None,
    expected_claim: str,
) -> None:
    """Spec: NEXT-03, NEXT-27, NEXT-29, NEXT-16."""
    assert_github_world(github_clone, bare_remote)
    publish_claims_from_a_second_clone(github_clone, bare_remote, ())
    lane = lane_worktree(github_clone, NESTED_LANE_BRANCH)
    monkeypatch.chdir(lane)
    contract = nested_contract(top_level_scope)
    nested = nested_container(contract)
    served = serve_nested_container(monkeypatch, nested)

    before_retype = run_cli(["next"], capsys)
    assert before_retype.status == 3, before_retype.stderr
    repair = before_retype.stdout.split(f"\n#{NESTED}: ", 1)[1].splitlines()[0]
    retyped = replace(nested, kind=body.ItemKind.TASK, children_closed=None, children_total=None)
    served.board_issues = (retyped,)
    served.issue_references[NESTED] = forge.ItemReference(
        forge.ItemState.OPEN, "Nested epic", contract
    )
    after_retype = run_cli(["next"], capsys)
    assert after_retype.status == 0, after_retype.stderr
    run_line = after_retype.stdout.split("\nRun: ", 1)[1].splitlines()[0]
    bash_status, claim_arguments = arguments_bash_hands_aco(run_line, tmp_path)
    claimed = run_cli(claim_arguments, capsys)

    assert repair.split(" and claim it with ", 1)[1] == f"{expected_claim} --out-of-order <reason>"
    assert run_line == expected_claim
    assert "\nparallel: none\nscope unknown: none\n" in after_retype.stdout
    assert (before_retype.status, after_retype.status, bash_status, claimed.status) == (
        3,
        0,
        0,
        0,
    ), claimed.stderr
    state = store.peek_state(worktree=lane, remote=str(bare_remote))
    assert tuple(claim.scope for claim in state.claims.values()) == (top_level_scope or ROW_SCOPE,)
