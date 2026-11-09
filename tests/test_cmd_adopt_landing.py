"""Landing an adopted lane through the real CLI (`specs/release.spec.md`, `specs/adopt.spec.md`):
which of its worktrees and branches go with the release, and which stay."""

import json
import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from adoption_world import (
    AdoptionWorld,
    adopt,
    adopted_claim,
    refusal_line,
    released_line,
    remote_tip,
    repush_the_branch,
    the_forge_reads_the_branch_ready,
)
from cli_fixtures import (
    ADOPTED_BRANCH,
    ADOPTED_PULL_REQUEST,
    CliRun,
    fresh_observation,
    real_git,
    run_cli,
)
from store_fixtures import claim_intent, state_ref_tip

from aco import checkout, forge, protocol, store
from aco.workboard import MergeMethod

REMOVED = "removed"
KEPT_NOT_MERGED = "kept -- not merged into the default branch"
KEPT_DIRTY = "kept -- dirty"


def the_branch_is_re_pushed(world: AdoptionWorld) -> None:
    repush_the_branch(world, "uv.lock", "pyproject.toml")
    the_forge_reads_the_branch_ready(world)


def the_worktree_follows_the_re_push(world: AdoptionWorld) -> None:
    the_branch_is_re_pushed(world)
    real_git(world.pull_request_directory, "fetch", "-q", "origin")
    real_git(world.pull_request_directory, "reset", "-q", "--hard", world.head)


def _adopt_and_re_push(world: AdoptionWorld, capsys: pytest.CaptureFixture[str]) -> str:
    """The adopted lane after the bot's force-push, its worktree still on the adopted head,
    which is returned."""
    world.forge.merge_remote = world.remote
    adopt(capsys).expect_success()
    adopted_head = world.head
    the_branch_is_re_pushed(world)
    return adopted_head


def _land_the_new_head(world: AdoptionWorld, capsys: pytest.CaptureFixture[str], *flags: str):
    return run_cli(["land", str(ADOPTED_PULL_REQUEST), "--head", world.head, *flags], capsys)


def _worktree_line(run: CliRun) -> str:
    [line] = [line for line in run.stdout.splitlines() if line.startswith("worktree: ")]
    return line.removeprefix("worktree: ")


def _the_pair_is_there(world: AdoptionWorld) -> tuple[bool, bool]:
    branch_listed = bool(real_git(world.clone, "branch", "--list", ADOPTED_BRANCH).stdout.strip())
    return world.pull_request_directory.is_dir(), branch_listed


def _the_branch_section_is_there(world: AdoptionWorld) -> bool:
    sections = real_git(
        world.clone, "config", "--get-regexp", rf"^branch\.{ADOPTED_BRANCH}\.", check=False
    )
    return bool(sections.stdout.strip())


def _claims_on_the_branch(world: AdoptionWorld) -> tuple[protocol.ActiveClaim, ...]:
    state = store.fetch_state(worktree=world.clone, remote=str(world.remote))
    return protocol.claims_on_branch(state.claims, ADOPTED_BRANCH)


def _commit_in_the_worktree(world: AdoptionWorld) -> str:
    real_git(world.pull_request_directory, "commit", "-q", "--allow-empty", "-m", "mine")
    return real_git(world.pull_request_directory, "rev-parse", "HEAD").stdout.strip()


def _hold_a_commit(world: AdoptionWorld, adopted_head: str) -> None:
    _commit_in_the_worktree(world)


def _hold_a_modified_file(world: AdoptionWorld, adopted_head: str) -> None:
    [tracked, *_] = real_git(world.pull_request_directory, "ls-files").stdout.split()
    with (world.pull_request_directory / tracked).open("a") as handle:
        handle.write("changed\n")


def _hold_an_untracked_file(world: AdoptionWorld, adopted_head: str) -> None:
    (world.pull_request_directory / "scratch.txt").write_text("mine\n")


def _hold_a_commit_reset_away(world: AdoptionWorld, adopted_head: str) -> None:
    _commit_in_the_worktree(world)
    real_git(world.pull_request_directory, "reset", "-q", "--hard", adopted_head)


def _hold_a_detached_head(world: AdoptionWorld, adopted_head: str) -> None:
    real_git(world.pull_request_directory, "checkout", "-q", "--detach")


def _hold_a_commit_and_a_modified_file(world: AdoptionWorld, adopted_head: str) -> None:
    _hold_a_commit(world, adopted_head)
    _hold_a_modified_file(world, adopted_head)


@pytest.mark.parametrize(
    ("hold", "worktree_text", "pair_goes"),
    [
        pytest.param(
            _hold_a_commit_reset_away,
            REMOVED,
            True,
            id="a-commit-reset-away-leaves-the-pair-to-go",
        ),
        pytest.param(
            _hold_a_commit,
            KEPT_NOT_MERGED,
            False,
            id="a-commit-on-top-keeps-the-pair",
        ),
        pytest.param(
            _hold_a_commit_and_a_modified_file,
            KEPT_NOT_MERGED,
            False,
            id="a-commit-on-top-with-a-dirty-tree-reads-not-merged",
        ),
        pytest.param(
            _hold_a_modified_file,
            KEPT_DIRTY,
            False,
            id="a-modified-tracked-file-keeps-the-pair",
        ),
        pytest.param(
            _hold_an_untracked_file,
            KEPT_DIRTY,
            False,
            id="an-untracked-file-keeps-the-pair",
        ),
        pytest.param(
            _hold_a_detached_head,
            f"kept -- no linked worktree on {ADOPTED_BRANCH} in this checkout; run .*",
            False,
            id="a-detached-worktree-keeps-the-pair",
        ),
    ],
)
def test_landing_the_new_head_removes_an_adopted_lane_only_when_it_holds_nothing_of_its_own(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    hold: Callable[[AdoptionWorld, str], None],
    worktree_text: str,
    pair_goes: bool,
) -> None:
    """Spec: REL-61, REL-62, REL-63, REL-29, REL-28, REL-30, ADOPT-34, ADOPT-37 -- after the
    bot's force-push the worktree lags the pull request, yet it goes with its branch and
    section whenever its clean tip is still the head adopt built."""
    adopted_head = _adopt_and_re_push(world, capsys)
    claim = adopted_claim(world)
    assert claim.base == adopted_head
    assert _the_branch_section_is_there(world)
    hold(world, adopted_head)
    state_before = _the_pair_is_there(world)

    landed = _land_the_new_head(world, capsys)

    assert (landed.status, landed.stderr) == (0, "")
    assert landed.stdout.startswith(released_line(claim))
    assert re.fullmatch(worktree_text, _worktree_line(landed))
    assert state_before == (True, True)
    assert _the_pair_is_there(world) == ((False, False) if pair_goes else (True, True))
    assert _the_branch_section_is_there(world) == (not pair_goes)
    assert _claims_on_the_branch(world) == ()
    assert [call[1] for call in world.forge.merge_calls] == [world.head]


def test_a_release_run_from_inside_the_adopted_worktree_keeps_the_pair(
    world: AdoptionWorld, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: REL-27, REL-61 -- a worktree cannot remove its own working directory."""
    _adopt_and_re_push(world, capsys)
    monkeypatch.chdir(world.pull_request_directory)

    _merge_on_the_forge(world)
    released = run_cli(
        ["release", "--merged", str(ADOPTED_PULL_REQUEST), "--branch", ADOPTED_BRANCH], capsys
    )

    assert _worktree_line(released) == "kept -- release ran from inside it"
    assert _the_pair_is_there(world) == (True, True)


def test_landing_the_new_head_keeps_the_pair_when_asked_to(
    world: AdoptionWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: REL-26, REL-61 -- `--keep-worktree` outranks the adopted lane's proof."""
    _adopt_and_re_push(world, capsys)

    landed = _land_the_new_head(world, capsys, "--keep-worktree")

    assert _worktree_line(landed) == "kept -- --keep-worktree was given"
    assert _the_pair_is_there(world) == (True, True)


def test_a_branch_that_moves_between_the_check_and_the_delete_stays_with_its_commit(
    world: AdoptionWorld, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: REL-62, REL-34 -- the branch goes by compare-and-delete on the adopted head, so a
    commit made in the window is never lost."""
    _adopt_and_re_push(world, capsys)
    remove = checkout.remove_linked_worktree
    commits: list[str] = []

    def commit_then_remove(
        path: Path, *, branch: str, landed_head: str | None = None
    ) -> checkout.WorktreeCleanupOutcome:
        commits.append(_commit_in_the_worktree(world))
        return remove(path, branch=branch, landed_head=landed_head)

    monkeypatch.setattr(checkout, "remove_linked_worktree", commit_then_remove)

    landed = _land_the_new_head(world, capsys)

    assert re.fullmatch(r"removed; branch kept -- git failure: .*", _worktree_line(landed))
    [commit] = commits
    assert real_git(world.clone, "rev-parse", ADOPTED_BRANCH).stdout.strip() == commit
    assert not world.pull_request_directory.exists()


def test_a_landing_the_forge_refuses_removes_nothing_and_keeps_the_claim(
    world: AdoptionWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: REL-61, LANDCMD-37 -- the proof is read only after a successful merge."""
    _adopt_and_re_push(world, capsys)
    claim = adopted_claim(world)
    world.forge.merge_error = forge.ForgeError("merge refused")

    landed = _land_the_new_head(world, capsys)

    assert (landed.status, landed.stderr) == (2, "ERROR: merge refused\n")
    assert _the_pair_is_there(world) == (True, True)
    assert _claims_on_the_branch(world) == (claim,)


def test_a_release_of_a_pull_request_the_forge_does_not_show_merged_removes_nothing(
    world: AdoptionWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: REL-61, REL-16 -- an unverified landing frees no worktree and no claim."""
    _adopt_and_re_push(world, capsys)
    claim = adopted_claim(world)

    released = run_cli(
        ["release", "--merged", str(ADOPTED_PULL_REQUEST), "--branch", ADOPTED_BRANCH], capsys
    )

    assert (released.status, released.stdout, released.stderr) == (
        2,
        "",
        refusal_line("is not merged"),
    )
    assert _the_pair_is_there(world) == (True, True)
    assert _claims_on_the_branch(world) == (claim,)


def _merge_on_the_forge(world: AdoptionWorld) -> None:
    landing = world.forge.landings[ADOPTED_PULL_REQUEST]
    world.forge.merge_remote = world.remote
    world.forge.merge_landing(
        ADOPTED_PULL_REQUEST,
        head_sha=world.head,
        method=MergeMethod.SQUASH,
        title=landing.title,
        body=landing.body,
    )


@pytest.mark.parametrize(
    ("flags", "expect_json"),
    [
        pytest.param((), False, id="in-text"),
        pytest.param(("--json",), True, id="in-json"),
    ],
)
def test_a_standalone_release_of_the_merged_pull_request_removes_the_adopted_pair(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    flags: tuple[str, ...],
    expect_json: bool,
) -> None:
    """Spec: REL-61, REL-35, REL-57 -- `aco release --merged` cleans up as `aco land` does."""
    _adopt_and_re_push(world, capsys)
    _merge_on_the_forge(world)

    released = run_cli(
        ["release", "--merged", str(ADOPTED_PULL_REQUEST), "--branch", ADOPTED_BRANCH, *flags],
        capsys,
    )

    assert released.status == 0
    worktree_text = (
        json.loads(released.stdout)["worktree"] if expect_json else _worktree_line(released)
    )
    assert worktree_text == REMOVED
    assert _the_pair_is_there(world) == (False, False)
    assert _claims_on_the_branch(world) == ()


def test_a_rerun_with_no_live_claim_keeps_the_lagging_pair(
    world: AdoptionWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: REL-47, REL-29, REL-61 -- the rerun has no claim and so no adopted head."""
    _adopt_and_re_push(world, capsys)
    _land_the_new_head(world, capsys, "--keep-worktree")

    rerun = run_cli(
        ["release", "--merged", str(ADOPTED_PULL_REQUEST), "--branch", ADOPTED_BRANCH], capsys
    )

    assert _worktree_line(rerun) == KEPT_NOT_MERGED
    assert _the_pair_is_there(world) == (True, True)


def test_giving_up_a_re_pushed_adopted_lane_keeps_the_pair(
    world: AdoptionWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: REL-33, ADOPT-35 -- an abandoned release removes nothing."""
    _adopt_and_re_push(world, capsys)

    abandoned = run_cli(["release", "--branch", ADOPTED_BRANCH, "--abandoned", "R"], capsys)

    assert abandoned.status == 0
    assert _the_pair_is_there(world) == (True, True)


def test_an_issue_claim_beside_the_adopted_lane_stands_when_the_lane_goes(
    world: AdoptionWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: REL-61, CLAIM-10 -- landing the lane releases the lane's claim alone."""
    _adopt_and_re_push(world, capsys)
    lane = adopted_claim(world)
    issue = protocol.IssueIdentity(7)
    store.commit_transition(
        observed=fresh_observation(world.clone, world.remote),
        subject=store.transition_subject("claim", issue, "issue-7"),
        intent=claim_intent(
            identity=issue,
            agent=lane.agent,
            role=lane.role,
            branch="issue-7",
            base=lane.base,
            scope=("README.md",),
            claim_id="i7",
            operation_id="op-i7",
        ),
    )

    landed = _land_the_new_head(world, capsys)

    assert _worktree_line(landed) == REMOVED
    state = store.fetch_state(worktree=world.clone, remote=str(world.remote))
    assert [claim.identity for claim in state.claims.values()] == [issue]


@pytest.mark.parametrize(
    ("identity", "branch", "body"),
    [
        pytest.param(protocol.LaneIdentity(), "fix/x", "Fix x\n\nNo-Item: fix", id="fix-lane"),
        pytest.param(
            protocol.IssueIdentity(7), "issue-7", "Closes #7\n\nWork-Item: #7", id="issue-claim"
        ),
    ],
)
def test_a_claim_that_is_no_adopted_lane_is_kept_at_its_claimed_base_when_merged_at_another_head(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    identity: protocol.ClaimIdentity,
    branch: str,
    body: str,
) -> None:
    """Spec: REL-63, REL-29 -- only an adopted lane meets REL-61: a `fix/` lane or an issue
    claim may hold commits that were never pushed."""
    lane_directory = world.clone.parent / "claimed-lane"
    real_git(world.clone, "worktree", "add", "-q", "-b", branch, str(lane_directory))
    (lane_directory / "fix.txt").write_text("fix\n")
    real_git(lane_directory, "add", "fix.txt")
    real_git(lane_directory, "commit", "-q", "-m", "fix")
    tip = real_git(lane_directory, "rev-parse", "HEAD").stdout.strip()
    real_git(lane_directory, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
    store.commit_transition(
        observed=fresh_observation(world.clone, world.remote),
        subject=store.transition_subject("claim", identity, branch),
        intent=claim_intent(
            identity=identity,
            agent="Ada",
            role="builder",
            branch=branch,
            base=protocol.ObjectId(tip),
            scope=("README.md",),
            claim_id="c1",
            operation_id="op-c1",
        ),
    )
    world.serve(lambda landing: replace(landing, source_branch=branch, body=body))
    world.forge.merge_remote = world.remote
    world.forge.merge_landing(
        ADOPTED_PULL_REQUEST,
        head_sha=world.head,
        method=MergeMethod.SQUASH,
        title="Fix x",
        body=body,
    )

    item = () if isinstance(identity, protocol.LaneIdentity) else (str(identity.issue),)
    released = run_cli(
        ["release", *item, "--merged", str(ADOPTED_PULL_REQUEST), "--branch", branch], capsys
    )

    assert _worktree_line(released) == KEPT_NOT_MERGED
    assert lane_directory.is_dir()
    assert real_git(world.clone, "rev-parse", "--verify", branch).stdout.strip() == tip


@pytest.mark.parametrize(
    ("arrange", "reviews_the_first_head", "status", "worktree_outcome", "merged"),
    [
        pytest.param(
            the_forge_reads_the_branch_ready,
            True,
            0,
            "removed",
            True,
            id="landing-the-head-adopted-releases-the-lane-and-removes-the-pair",
        ),
        pytest.param(
            the_branch_is_re_pushed,
            True,
            2,
            "",
            False,
            id="landing-the-reviewed-head-after-a-re-push-refuses-and-keeps-the-claim",
        ),
        pytest.param(
            the_worktree_follows_the_re_push,
            False,
            0,
            "removed",
            True,
            id="landing-the-new-head-with-the-worktree-pulled-removes-the-pair",
        ),
        pytest.param(
            the_branch_is_re_pushed,
            False,
            0,
            "removed",
            True,
            id="landing-the-new-head-with-the-worktree-behind-removes-the-pair",
        ),
    ],
)
def test_an_adopted_lane_lands_or_is_refused_by_the_head_it_is_given(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[[AdoptionWorld], None],
    reviews_the_first_head: bool,
    status: int,
    worktree_outcome: str,
    merged: bool,
) -> None:
    """Spec: ADOPT-34, LANDCMD-31, LANDCMD-12, LANDCMD-13, REL-57, REL-25, REL-61 --
    `aco land --head` lands an adopted lane like any lane, but only at the head it is told to
    review; the trailer is the adopted line, the clean worktree goes with the merged lane."""
    world.forge.merge_remote = world.remote
    adopt(capsys).expect_success()
    claim = adopted_claim(world)
    first_head = world.head
    arrange(world)
    current_head = world.head
    reviewed_head = first_head if reviews_the_first_head else current_head
    trunk_before = remote_tip(world, "main")
    state_before = state_ref_tip(world.remote)

    landed = run_cli(["land", str(ADOPTED_PULL_REQUEST), "--head", reviewed_head], capsys)

    refusal = refusal_line(
        f"head is {current_head}, not the reviewed {reviewed_head}; "
        "review the new head before landing"
    )
    merge_commit = world.forge.landings[ADOPTED_PULL_REQUEST].merge_commit
    expected_stdout = (
        released_line(claim) + f"worktree: {worktree_outcome}\nmerged: {merge_commit}\n"
    )
    expected_run = (status, expected_stdout, "") if merged else (status, "", refusal)
    observed_run = (landed.status, landed.stdout, landed.stderr)
    merged_heads = [call[1] for call in world.forge.merge_calls]
    trunk_moved = remote_tip(world, "main") != trunk_before
    state_moved = state_ref_tip(world.remote) != state_before
    worktree_removed = not world.pull_request_directory.exists()
    branch_kept = ADOPTED_BRANCH in real_git(world.clone, "branch", "--list").stdout
    claims_left = protocol.claims_on_branch(
        store.fetch_state(worktree=world.clone, remote=str(world.remote)).claims,
        ADOPTED_BRANCH,
    )
    assert observed_run == expected_run
    assert merged_heads == ([current_head] if merged else [])
    assert trunk_moved == merged
    assert state_moved == merged
    assert worktree_removed == (worktree_outcome == "removed")
    assert branch_kept == (worktree_outcome != "removed")
    assert _the_branch_section_is_there(world) == (worktree_outcome != "removed")
    assert claims_left == (() if merged else (claim,))
    if merged:
        [(_number, _head, _method, _title, merge_body)] = world.forge.merge_calls
        assert merge_body.splitlines()[-1] == "No-Item: deps"
