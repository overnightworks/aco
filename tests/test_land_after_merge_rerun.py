"""Resume a landed lane using its immutable merge trailer and recorded head."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

import pytest
from cli_fixtures import (
    CliRun,
    configure_github_remote,
    fresh_observation,
    local_branches,
    real_git,
    redirect_toplevel,
    run_cli,
    without_git_identity,
)
from github_fixtures import (
    FakeForge,
    LandedWorld,
    LandingWorld,
    arrange_follow_up_failures,
    landed_world,
    landing_world,
)
from store_fixtures import claim_intent, state_ref_tip

from agent_coordination import board, checkout, forge, protocol, store


@dataclass(frozen=True)
class SeparateCase:
    identity: protocol.ClaimIdentity = field(default_factory=lambda: protocol.IssueIdentity(72))
    branch: str = "codex/issue-72-claims"
    body: str = "Work-Item: #72\n\nCloses #72"
    before_claim: str | None = None
    race_claim: str | None = None
    release_command: str = "aco release 72 --merged 12 --branch codex/issue-72-claims"
    keep_arguments: tuple[str, ...] = ()
    land_status: int = 0
    land_stdout: str = (
        "LANDED pull request #12 already; nothing left to release\n"
        "worktree: kept -- no linked worktree on codex/issue-72-claims in this checkout; "
        "run aco release 72 --merged 12 --branch codex/issue-72-claims "
        "in the checkout that holds it\n"
    )
    land_stderr: str = ""
    release_status: int = 0
    release_stdout: str = (
        "LANDED pull request #12 already; nothing left to release\nworktree: removed\n"
    )
    release_stderr: str = ""
    merge_calls: int = 1
    closed_items: frozenset[int] = frozenset()
    comments: dict[int, str] = field(default_factory=dict)
    issue_reads: tuple[int, ...] = ()
    claims: tuple[tuple[protocol.ClaimIdentity, str, str], ...] = ()
    lane_exists: bool = False
    branch_exists: bool = False
    publications: int = 0
    author_name: str = "Lander"
    author_email: str = "lander@example.com"


@dataclass(frozen=True)
class SeparateWorld:
    landing: LandingWorld
    original: Path
    lane: Path
    head: str
    case: SeparateCase


def separate_claims(world: SeparateWorld) -> tuple[tuple[protocol.ClaimIdentity, str, str], ...]:
    claims = store.peek_state(worktree=world.landing.clone, remote=str(world.landing.remote)).claims
    return tuple(
        sorted(
            ((claim.identity, claim.branch, str(claim.claim_id)) for claim in claims.values()),
            key=lambda claim: (claim[1], claim[2]),
        )
    )


@pytest.fixture
def separate_world(
    request: pytest.FixtureRequest,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> SeparateWorld:
    case: SeparateCase = request.param

    def arrange(client: FakeForge, _head: str) -> None:
        client.allowed_methods = frozenset({board.MergeMethod.SQUASH})
        client.closes_on_merge = True

    original = landed_world(
        github_clone,
        bare_remote,
        monkeypatch,
        identity=case.identity,
        branch=case.branch,
        body=case.body,
        extra_arrange=arrange,
    )
    real_git(github_clone, "config", "user.name", "Original")
    real_git(github_clone, "config", "user.email", "original@example.com")
    clone = github_clone.parent / "landing-clone"
    real_git(github_clone.parent, "clone", "-q", str(bare_remote), str(clone))
    configure_github_remote(clone, bare_remote)
    without_git_identity(monkeypatch, clone)
    real_git(clone, "config", "user.name", "Lander")
    real_git(clone, "config", "user.email", "lander@example.com")
    redirect_toplevel(monkeypatch, clone)
    monkeypatch.chdir(clone)
    landing = landing_world(
        clone,
        bare_remote,
        original.landing.forge,
        remote_tip=str(original.landing.unchanged["remote"]),
    )
    observed = {
        "landing.linked-worktrees": tuple(
            path for path in store.list_worktrees(clone) if path != clone
        ),
        "landing.lane-branch.exists": case.branch in local_branches(clone),
        "original.lane.head": real_git(original.lane, "rev-parse", "HEAD").stdout.strip(),
        "environment.GIT_AUTHOR_NAME": os.environ.get("GIT_AUTHOR_NAME"),
        "environment.GIT_COMMITTER_NAME": os.environ.get("GIT_COMMITTER_NAME"),
        "environment.GIT_AUTHOR_EMAIL": os.environ.get("GIT_AUTHOR_EMAIL"),
        "environment.GIT_COMMITTER_EMAIL": os.environ.get("GIT_COMMITTER_EMAIL"),
        "environment.EMAIL": os.environ.get("EMAIL"),
        "landing.user.name": real_git(clone, "config", "--local", "user.name").stdout,
        "landing.user.email": real_git(clone, "config", "--local", "user.email").stdout,
        "original.user.name": real_git(github_clone, "config", "--local", "user.name").stdout,
        "original.user.email": real_git(github_clone, "config", "--local", "user.email").stdout,
        "allowed.methods": landing.forge.allowed_methods,
        "closes-on-merge": landing.forge.closes_on_merge,
        "toplevel": Path(checkout.git_output(["rev-parse", "--show-toplevel"])),
        "cwd": Path.cwd(),
    }
    expected = {
        "landing.linked-worktrees": (),
        "landing.lane-branch.exists": False,
        "original.lane.head": original.landing.head,
        "environment.GIT_AUTHOR_NAME": None,
        "environment.GIT_COMMITTER_NAME": None,
        "environment.GIT_AUTHOR_EMAIL": None,
        "environment.GIT_COMMITTER_EMAIL": None,
        "environment.EMAIL": None,
        "landing.user.name": "Lander\n",
        "landing.user.email": "lander@example.com\n",
        "original.user.name": "Original\n",
        "original.user.email": "original@example.com\n",
        "allowed.methods": frozenset({board.MergeMethod.SQUASH}),
        "closes-on-merge": True,
        "toplevel": clone,
        "cwd": clone,
    }
    assert observed == expected
    return SeparateWorld(landing, github_clone, original.lane, original.landing.head, case)


def publish_separate_claim(world: SeparateWorld, claim_id: str) -> str | None:
    identity = protocol.IssueIdentity(72)
    written = store.commit_transition(
        observed=fresh_observation(world.original, world.landing.remote),
        subject=store.transition_subject("claim", identity, world.case.branch),
        intent=claim_intent(
            identity=identity,
            branch=world.case.branch,
            claim_id=claim_id,
            operation_id=claim_id + "-op",
        ),
    )
    return written.tip


@dataclass
class SeparateRelease:
    world: SeparateWorld
    tip: str | None
    publications: int = 0

    def run(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> CliRun:
        case = self.world.case
        redirect_toplevel(monkeypatch, self.world.original)
        monkeypatch.chdir(self.world.original)
        race_claim = case.race_claim
        if race_claim is not None:
            client = self.world.landing.forge
            original_landing = client.landing

            def landing(number: int) -> forge.Landing:
                if self.publications == 0:
                    self.tip = publish_separate_claim(self.world, race_claim)
                    self.publications += 1
                return original_landing(number)

            monkeypatch.setattr(client, "landing", landing)
        # Execute the release command whose printed spelling land_stdout verifies.
        return run_cli([*shlex.split(case.release_command)[1:], *case.keep_arguments], capsys)


def prepare_separate_rerun(
    world: SeparateWorld, capsys: pytest.CaptureFixture[str]
) -> tuple[str, SeparateRelease]:
    capsys.readouterr()
    initial = run_cli(["land", "12"], capsys)
    client = world.landing.forge
    merge = client.landings[12].merge_commit
    observed = {
        "initial-land.exit": initial.status,
        "merge.commit": real_git(world.landing.remote, "rev-parse", "main").stdout.strip(),
        "merge.calls": len(client.merge_calls),
        "claims": separate_claims(world),
        "lane.exists": world.lane.exists(),
        "lane.branch.head": real_git(world.original, "rev-parse", world.case.branch).stdout.strip(),
        "recorded.head": client.landings[12].head_sha,
        "merge.parents": len(
            real_git(world.landing.remote, "show", "-s", "--format=%P", str(merge)).stdout.split()
        ),
        "lane.ancestor": real_git(
            world.landing.remote, "merge-base", "--is-ancestor", world.head, str(merge), check=False
        ).returncode,
    }
    expected = {
        "initial-land.exit": 0,
        "merge.commit": merge,
        "merge.calls": 1,
        "claims": (),
        "lane.exists": True,
        "lane.branch.head": world.head,
        "recorded.head": world.head,
        "merge.parents": 1,
        "lane.ancestor": 1,
    }
    assert observed == expected
    client.closed_issues.discard(72)
    client.landing_comments.clear()
    client.issue_reference_lookups.clear()
    tip = state_ref_tip(world.landing.remote)
    before_claims = ()
    if world.case.before_claim is not None:
        tip = publish_separate_claim(world, world.case.before_claim)
        before_claims = world.case.claims
    release = SeparateRelease(world, tip)
    observed = {
        "closed.items": frozenset(client.closed_issues),
        "landing.comments": client.landing_comments,
        "issue.reads": tuple(client.issue_reference_lookups),
        "claims": separate_claims(world),
        "state.tip": state_ref_tip(world.landing.remote),
    }
    expected = {
        "closed.items": frozenset(),
        "landing.comments": {},
        "issue.reads": (),
        "claims": before_claims,
        "state.tip": tip,
    }
    assert observed == expected
    return str(merge), release


class RerunPreparation(Enum):
    FAILED_LAND = "failed-land"
    FORGE_MERGE = "forge-merge"


@dataclass(frozen=True)
class RerunCase:
    preparation: RerunPreparation = RerunPreparation.FORGE_MERGE
    identity: protocol.ClaimIdentity = field(default_factory=lambda: protocol.IssueIdentity(72))
    branch: str = "codex/issue-72-claims"
    body: str = "Work-Item: #72\n\nCloses #72"
    method: board.MergeMethod = board.MergeMethod.MERGE
    title: str = "feat: land the lane (#12)"
    merge_body: str = "Work-Item: #72"
    merge_trailers: str = "Work-Item: #72\n"
    merge_message: str = "feat: land the lane (#12)\n\nWork-Item: #72\n"
    merge_parents: int = 2
    lane_ancestor: int = 0
    off_trunk: bool = False
    close_error: str | None = None
    delete_error: str | None = None
    initial_stderr: str = ""
    initial_status: int = 2
    initial_stdout: str = ""
    changed_body: str | None = None
    mergeable_state: str | None = None
    checks: tuple[forge.CheckRun, ...] = ()
    head_config: str | None = ""
    quality_error: str | None = None
    arguments: tuple[str, ...] = ("land", "12")
    status: int = 0
    stdout: str = "RELEASED issue #72: landing\nfreed: none\nnext: none\nworktree: removed\n"
    stderr: str = ""
    merge_calls: int = 1
    closed_items: frozenset[int] = frozenset({72})
    claims: tuple[str, ...] = ()
    quality_reads: tuple[str, ...] = ()
    head_config_reads: tuple[tuple[Path, str], ...] = ()
    lane_exists: bool = False
    lane_head: str = ""


@dataclass(frozen=True)
class RerunWorld:
    world: LandedWorld
    case: RerunCase
    merge: str


def prepare_merge(world: LandedWorld, case: RerunCase, capsys: pytest.CaptureFixture[str]) -> str:
    landing = world.landing
    client = landing.forge
    capsys.readouterr()
    if case.preparation is RerunPreparation.FAILED_LAND:
        result = run_cli(["land", "12"], capsys)
        merge = real_git(landing.remote, "rev-parse", landing.default_branch).stdout.strip()
        observed = {"exit": result.status, "stdout": result.stdout, "stderr": result.stderr}
        expected = {
            "exit": case.initial_status,
            "stdout": case.initial_stdout,
            "stderr": case.initial_stderr.format(merge=merge),
        }
        assert observed == expected
        return merge
    return client.merge_landing(
        12, head_sha=landing.head, method=case.method, title=case.title, body=case.merge_body
    )


def arrange_rerun(world: LandedWorld, case: RerunCase) -> None:
    client = world.landing.forge
    client.close_error = None
    client.delete_error = None
    if case.changed_body is not None:
        client.landings[12] = replace(client.landings[12], body=case.changed_body)
    if case.mergeable_state is not None:
        client.readiness_by_number[12] = replace(
            client.readiness_by_number[12],
            mergeable_state=case.mergeable_state,
            checks=case.checks,
        )
        client.head_board_config = case.head_config
        observed = {
            "readiness.mergeability": client.landing_readiness(12).mergeable_state,
            "readiness.checks": client.landing_readiness(12).checks,
            "head.configuration": client.head_board_config,
        }
        expected = {
            "readiness.mergeability": case.mergeable_state,
            "readiness.checks": case.checks,
            "head.configuration": case.head_config,
        }
        assert observed == expected
    if case.quality_error is not None:
        client.quality_config_error = forge.ForgeError(case.quality_error)
    client.quality_config_reads.clear()
    client.file_reads.clear()


def verify_merge(world: LandedWorld, case: RerunCase, merge: str) -> None:
    landing = world.landing
    client = landing.forge
    claims = store.peek_state(worktree=landing.clone, remote=str(landing.remote)).claims
    observed = {
        "landing.merged": client.landings[12].merged,
        "merge.commit": real_git(
            landing.remote, "rev-parse", landing.default_branch
        ).stdout.strip(),
        "merge.calls": len(client.merge_calls),
        "closed.items": set(client.closed_issues),
        "claims": tuple((c.identity, c.branch, str(c.claim_id)) for c in claims.values()),
        "close-error": client.close_error,
        "delete-error": client.delete_error,
        "lane.head": real_git(world.lane, "rev-parse", "HEAD").stdout.strip(),
        "quality.reads": tuple(client.quality_config_reads),
        "head-config.reads": tuple(client.file_reads),
        "merge.trailers": real_git(
            landing.remote, "show", "-s", "--format=%(trailers:only,unfold)", merge
        ).stdout.removesuffix("\n"),
        "merge.message": real_git(
            landing.remote, "show", "-s", "--format=%B", merge
        ).stdout.removesuffix("\n"),
        "merge.parents": len(
            real_git(landing.remote, "show", "-s", "--format=%P", merge).stdout.split()
        ),
        "recorded.head": client.landings[12].head_sha,
        "lane.ancestor": real_git(
            landing.remote, "merge-base", "--is-ancestor", landing.head, merge, check=False
        ).returncode,
    }
    expected = {
        "landing.merged": True,
        "merge.commit": client.landings[12].merge_commit,
        "merge.calls": 1,
        "closed.items": set(),
        "claims": ((case.identity, case.branch, "landing"),),
        "close-error": None,
        "delete-error": None,
        "lane.head": landing.head,
        "quality.reads": (),
        "head-config.reads": (),
        "merge.trailers": case.merge_trailers,
        "merge.message": case.merge_message,
        "merge.parents": case.merge_parents,
        "recorded.head": landing.head,
        "lane.ancestor": case.lane_ancestor,
    }
    assert observed == expected


@pytest.fixture
def world(
    request: pytest.FixtureRequest,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> RerunWorld:
    case: RerunCase = request.param

    def arrange(client: FakeForge, _head: str) -> None:
        arrange_follow_up_failures(client, case.close_error, case.delete_error)

    shared = landed_world(
        github_clone,
        bare_remote,
        monkeypatch,
        identity=case.identity,
        branch=case.branch,
        body=case.body,
        extra_arrange=arrange,
    )
    merge = prepare_merge(shared, case, capsys)
    arrange_rerun(shared, case)
    verify_merge(shared, case, merge)
    if case.off_trunk:
        landing = shared.landing
        client = landing.forge
        client.landings[12] = replace(client.landings[12], merge_commit=landing.head)
        observed = {
            "trunk.trailers": real_git(
                landing.remote, "show", "-s", "--format=%(trailers:only,unfold)", merge
            ).stdout.removesuffix("\n"),
            "recorded.on-first-parent": client.landings[12].merge_commit
            in real_git(landing.remote, "rev-list", "--first-parent", merge).stdout.splitlines(),
        }
        expected = {"trunk.trailers": case.merge_trailers, "recorded.on-first-parent": False}
        assert observed == expected
        merge = landing.head
    return RerunWorld(shared, case, merge)


FOREIGN_LANE = SeparateCase(
    identity=protocol.LaneIdentity(),
    branch="dependabot/x",
    body="No-Item: fix",
    release_command="aco release --merged 12 --branch dependabot/x",
    land_stdout="LANDED pull request #12 already; nothing left to release\n"
    "worktree: kept -- no linked worktree on dependabot/x in this checkout; "
    "run aco release --merged 12 --branch dependabot/x "
    "in the checkout that holds it\n",
)
RACE_RELEASE_STDOUT = (
    "LANDED pull request #12 already; nothing left to release\n"
    "worktree: kept -- claimed again while this release ran\n"
)
KEEP_RELEASE_STDOUT = (
    "LANDED pull request #12 already; nothing left to release\n"
    "worktree: kept -- --keep-worktree was given\n"
)


class TestLandAfterMergeRerun:
    @pytest.mark.parametrize(
        "separate_world",
        [
            pytest.param(
                SeparateCase(
                    land_stdout="RELEASED issue #72: landing\nfreed: none\nnext: none\n"
                    "worktree: kept -- no linked worktree on codex/issue-72-claims "
                    "in this checkout; "
                    "run aco release 72 --merged 12 --branch codex/issue-72-claims "
                    "in the checkout that holds it\n",
                    lane_exists=True,
                    branch_exists=True,
                ),
                id="local-identity",
            )
        ],
        indirect=True,
    )
    def test_lands_from_a_separate_clone(
        self, separate_world: SeparateWorld, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: LANDCMD-25, E-LANDCMD-18a. Local identity releases; the original lane stays."""
        world = separate_world
        case = world.case
        capsys.readouterr()
        result = run_cli(["land", "12"], capsys)
        observed = {
            "land.exit": result.status,
            "land.stdout": result.stdout,
            "land.stderr": result.stderr,
            "merge.calls": len(world.landing.forge.merge_calls),
            "claims": separate_claims(world),
            "lane.exists": world.lane.exists(),
            "lane.branch.exists": world.case.branch in local_branches(world.original),
            "release.author.name": real_git(
                world.landing.remote, "show", "-s", "--format=%an", store.STATE_REF, check=False
            ).stdout.strip(),
            "release.author.email": real_git(
                world.landing.remote, "show", "-s", "--format=%ae", store.STATE_REF, check=False
            ).stdout.strip(),
        }
        expected = {
            "land.exit": case.land_status,
            "land.stdout": case.land_stdout,
            "land.stderr": case.land_stderr,
            "merge.calls": case.merge_calls,
            "claims": case.claims,
            "lane.exists": case.lane_exists,
            "lane.branch.exists": case.branch_exists,
            "release.author.name": case.author_name,
            "release.author.email": case.author_email,
        }
        assert observed == expected

    @pytest.mark.parametrize(
        "separate_world",
        [
            pytest.param(SeparateCase(), id="issue-removes-the-lane"),
            pytest.param(
                SeparateCase(
                    race_claim="reopened-claim",
                    publications=1,
                    release_stdout=RACE_RELEASE_STDOUT,
                    claims=(
                        (protocol.IssueIdentity(72), "codex/issue-72-claims", "reopened-claim"),
                    ),
                    lane_exists=True,
                    branch_exists=True,
                ),
                id="issue-a-claim-taken-meanwhile-keeps-the-lane",
            ),
            pytest.param(
                SeparateCase(
                    keep_arguments=("--keep-worktree",),
                    release_stdout=KEEP_RELEASE_STDOUT,
                    lane_exists=True,
                    branch_exists=True,
                ),
                id="issue-the-keep-worktree-flag-keeps-the-lane",
            ),
            pytest.param(
                FOREIGN_LANE,
                id="foreign-lane-removes-the-lane",
            ),
            pytest.param(
                replace(
                    FOREIGN_LANE,
                    race_claim="reopened-claim",
                    publications=1,
                    release_stdout=RACE_RELEASE_STDOUT,
                    claims=((protocol.IssueIdentity(72), "dependabot/x", "reopened-claim"),),
                    lane_exists=True,
                    branch_exists=True,
                ),
                id="foreign-lane-a-claim-taken-meanwhile-keeps-the-lane",
            ),
            pytest.param(
                replace(
                    FOREIGN_LANE,
                    keep_arguments=("--keep-worktree",),
                    release_stdout=KEEP_RELEASE_STDOUT,
                    lane_exists=True,
                    branch_exists=True,
                ),
                id="foreign-lane-the-keep-worktree-flag-keeps-the-lane",
            ),
        ],
        indirect=True,
    )
    def test_releases_in_the_original_checkout(
        self,
        separate_world: SeparateWorld,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Spec: E-LANDCMD-18a, LANDCMD-38, REL-26, REL-47, REL-55, REL-59, E-REL-24."""
        world = separate_world
        case = world.case
        merge, release = prepare_separate_rerun(world, capsys)
        before_tip = release.tip
        land_result = run_cli(["land", "12"], capsys)
        land_tip = state_ref_tip(world.landing.remote)
        release_result = release.run(monkeypatch, capsys)
        observed_guard = {
            "race.publications.after": release.publications,
            "follow-up.cwd": Path.cwd(),
            "follow-up.toplevel": Path(checkout.git_output(["rev-parse", "--show-toplevel"])),
        }
        expected_guard = {
            "race.publications.after": case.publications,
            "follow-up.cwd": world.original,
            "follow-up.toplevel": world.original,
        }
        assert observed_guard == expected_guard
        observed = {
            "land.exit": land_result.status,
            "land.stdout": land_result.stdout,
            "land.stderr": land_result.stderr,
            "release.exit": release_result.status,
            "release.stdout": release_result.stdout,
            "release.stderr": release_result.stderr,
            "merge.calls": len(world.landing.forge.merge_calls),
            "closed.items": frozenset(world.landing.forge.closed_issues),
            "landing.comments": world.landing.forge.landing_comments,
            "issue.reads": tuple(world.landing.forge.issue_reference_lookups),
            "claims": separate_claims(world),
            "state.tip": state_ref_tip(world.landing.remote),
            "land.state.tip": land_tip,
            "lane.exists": world.lane.exists(),
            "lane.branch.exists": case.branch in local_branches(world.original),
        }
        expected = {
            "land.exit": case.land_status,
            "land.stdout": case.land_stdout,
            "land.stderr": case.land_stderr.format(merge=merge),
            "release.exit": case.release_status,
            "release.stdout": case.release_stdout,
            "release.stderr": case.release_stderr,
            "merge.calls": case.merge_calls,
            "closed.items": case.closed_items,
            "landing.comments": case.comments,
            "issue.reads": case.issue_reads,
            "claims": case.claims,
            "state.tip": release.tip,
            "land.state.tip": before_tip,
            "lane.exists": case.lane_exists,
            "lane.branch.exists": case.branch_exists,
        }
        assert observed == expected

    @pytest.mark.parametrize(
        "separate_world",
        [
            pytest.param(
                replace(
                    FOREIGN_LANE,
                    before_claim="bob-claim",
                    land_status=2,
                    land_stdout="",
                    land_stderr="ERROR: MERGED pull request #12 as {merge}; follow-up incomplete: "
                    "release (branch 'dependabot/x' is not an issueless lane; "
                    "pass an issue number, "
                    "or check out a branch prefixed 'docs/' or 'fix/'); re-run aco land 12\n",
                    claims=((protocol.IssueIdentity(72), "dependabot/x", "bob-claim"),),
                    lane_exists=True,
                    branch_exists=True,
                ),
                id="foreign-lane-an-issue-claim-taken-since-the-release-refuses",
            ),
        ],
        indirect=True,
    )
    def test_refuses_a_foreign_lane_with_an_issue_claim(
        self, separate_world: SeparateWorld, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: REL-58. An issue claim prevents an issueless rerun from releasing the lane."""
        world = separate_world
        case = world.case
        merge, release = prepare_separate_rerun(world, capsys)
        before_tip = release.tip
        result = run_cli(["land", "12"], capsys)
        observed_guard = {
            "race.publications.after": release.publications,
            "follow-up.cwd": Path.cwd(),
            "follow-up.toplevel": Path(checkout.git_output(["rev-parse", "--show-toplevel"])),
        }
        expected_guard = {
            "race.publications.after": case.publications,
            "follow-up.cwd": world.landing.clone,
            "follow-up.toplevel": world.landing.clone,
        }
        assert observed_guard == expected_guard
        observed = {
            "land.exit": result.status,
            "land.stdout": result.stdout,
            "land.stderr": result.stderr,
            "merge.calls": len(world.landing.forge.merge_calls),
            "closed.items": frozenset(world.landing.forge.closed_issues),
            "landing.comments": world.landing.forge.landing_comments,
            "issue.reads": tuple(world.landing.forge.issue_reference_lookups),
            "claims": separate_claims(world),
            "state.tip": state_ref_tip(world.landing.remote),
            "land.state.tip": state_ref_tip(world.landing.remote),
            "lane.exists": world.lane.exists(),
            "lane.branch.exists": case.branch in local_branches(world.original),
        }
        expected = {
            "land.exit": case.land_status,
            "land.stdout": case.land_stdout,
            "land.stderr": case.land_stderr.format(merge=merge),
            "merge.calls": case.merge_calls,
            "closed.items": case.closed_items,
            "landing.comments": case.comments,
            "issue.reads": case.issue_reads,
            "claims": case.claims,
            "state.tip": release.tip,
            "land.state.tip": before_tip,
            "lane.exists": case.lane_exists,
            "lane.branch.exists": case.branch_exists,
        }
        assert observed == expected

    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                RerunCase(
                    mergeable_state="dirty",
                    checks=(forge.CheckRun("ci", "failure"),),
                    head_config=None,
                    quality_error="GitHub returned HTTP 500",
                ),
                id="skips-fresh-preflight",
            ),
            pytest.param(
                RerunCase(
                    preparation=RerunPreparation.FAILED_LAND,
                    close_error="forge unreachable (simulated)",
                    merge_message="Merge pull request #12\n\nCloses #72\n\nWork-Item: #72\n",
                    initial_stderr="ERROR: MERGED pull request #12 as {merge}; "
                    "follow-up incomplete: "
                    "release (forge unreachable (simulated)); re-run aco land 12\n",
                    quality_error="GitHub returned HTTP 500",
                ),
                id="work-item-resumes-release",
            ),
            pytest.param(
                RerunCase(
                    preparation=RerunPreparation.FAILED_LAND,
                    identity=protocol.LaneIdentity(),
                    branch="dependabot/x",
                    body="No-Item: fix",
                    merge_body="No-Item: fix",
                    merge_trailers="No-Item: fix\n",
                    merge_message="Merge pull request #12\n\nNo-Item: fix\n",
                    delete_error="delete branch failed (simulated)",
                    initial_stderr="ERROR: MERGED pull request #12 as {merge}; "
                    "follow-up incomplete: "
                    "delete-branch (delete branch failed (simulated)); re-run aco land 12\n",
                    quality_error="GitHub returned HTTP 500",
                    stdout="RELEASED lane dependabot/x: landing\nfreed: none\nnext: none\n"
                    "worktree: removed\n",
                    closed_items=frozenset(),
                ),
                id="no-item-resumes-delete",
            ),
            pytest.param(
                RerunCase(
                    preparation=RerunPreparation.FAILED_LAND,
                    close_error="forge unreachable (simulated)",
                    initial_stderr="ERROR: MERGED pull request #12 as {merge}; "
                    "follow-up incomplete: "
                    "release (forge unreachable (simulated)); re-run aco land 12\n",
                    changed_body="Advances #72",
                    merge_message="Merge pull request #12\n\nCloses #72\n\nWork-Item: #72\n",
                ),
                id="merge-trailer-survives-body-edit",
            ),
            pytest.param(
                RerunCase(
                    method=board.MergeMethod.SQUASH,
                    merge_parents=1,
                    lane_ancestor=1,
                    arguments=("land", "12", "--head", "0000000"),
                ),
                id="squash-rerun-on-recorded-head",
            ),
        ],
        indirect=True,
    )
    def test_resumes(self, world: RerunWorld, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-18, E-LANDCMD-18, LANDCMD-32, REL-43, LAND-64.
        Land's Never 2/3/4 resume release once, using the immutable merge trailer.
        """
        landing = world.world.landing
        client = landing.forge
        case = world.case
        capsys.readouterr()
        result = run_cli(list(case.arguments), capsys)
        claims = store.peek_state(worktree=landing.clone, remote=str(landing.remote)).claims
        observed = {
            "exit": result.status,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "merge.calls": len(client.merge_calls),
            "closed.items": frozenset(client.closed_issues),
            "claims": tuple(sorted(str(c.claim_id) for c in claims.values())),
            "quality.reads": tuple(client.quality_config_reads),
            "head-config.reads": tuple(client.file_reads),
            "lane.exists": world.world.lane.exists(),
            "lane.head": real_git(
                landing.clone,
                "rev-parse",
                "--verify",
                "--quiet",
                f"refs/heads/{case.branch}",
                check=False,
            ).stdout.strip(),
        }
        expected = {
            "exit": case.status,
            "stdout": case.stdout,
            "stderr": case.stderr,
            "merge.calls": case.merge_calls,
            "closed.items": case.closed_items,
            "claims": case.claims,
            "quality.reads": case.quality_reads,
            "head-config.reads": case.head_config_reads,
            "lane.exists": case.lane_exists,
            "lane.head": case.lane_head,
        }
        assert observed == expected

    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                RerunCase(
                    title="Merge pull request #12",
                    merge_body="ordinary merge without classification",
                    merge_trailers="",
                    merge_message=(
                        "Merge pull request #12\n\nordinary merge without classification\n"
                    ),
                    status=2,
                    stdout="",
                    stderr="ERROR: MERGED pull request #12 as {merge}; follow-up incomplete: "
                    "release (merge commit {merge} carries no `Work-Item:` or `No-Item:` trailer); "
                    "re-run aco land 12\n",
                ),
                id="missing-trailer-gap-17",
            ),
            pytest.param(
                RerunCase(
                    off_trunk=True,
                    status=2,
                    stdout="",
                    stderr="ERROR: MERGED pull request #12 as {merge}; follow-up incomplete: "
                    "release (merge commit {merge} carries no `Work-Item:` or `No-Item:` trailer); "
                    "re-run aco land 12\n",
                ),
                id="off-trunk-merge-commit-gap-17",
            ),
        ],
        indirect=True,
    )
    def test_reports_missing_trailer(
        self, world: RerunWorld, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: LANDCMD-18, LAND-62, LAND-64.
        Issue #17 owns the gap between land's current error and release's trailer contract.
        """
        case = world.case
        capsys.readouterr()
        result = run_cli(list(case.arguments), capsys)
        observed = {"exit": result.status, "stdout": result.stdout, "stderr": result.stderr}
        expected = {
            "exit": case.status,
            "stdout": case.stdout,
            "stderr": case.stderr.format(merge=world.merge),
        }
        assert observed == expected
