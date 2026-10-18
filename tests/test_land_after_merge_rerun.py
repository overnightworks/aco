"""Resume a landed lane using its immutable merge trailer and recorded head."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

import pytest
from cli_fixtures import real_git, run_cli
from github_fixtures import FakeForge, LandedWorld, landed_world

from agent_coordination import board, forge, protocol, store


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
    trailer: str | None = "Work-Item: #72\n"
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
        observed = client.landings[12].body
        expected = case.changed_body
        assert observed == expected
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
        observed = str(client.quality_config_error)
        expected = case.quality_error
        assert observed == expected
    client.quality_config_reads.clear()
    client.file_reads.clear()
    # The fake's disposable merge clone must permit a second merge fault to reach the oracle.
    shutil.rmtree(world.landing.remote.parent / "forge-merge")


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
        "merge-clone.exists": (landing.remote.parent / "forge-merge").exists(),
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
        "merge-clone.exists": False,
    }
    assert observed == expected
    if case.trailer is not None:
        observed = real_git(
            landing.remote, "show", "-s", "--format=%(trailers:only,unfold)", merge
        ).stdout.removesuffix("\n")
        expected = case.trailer
        assert observed == expected
    else:
        observed = {
            "merge.message": real_git(
                landing.remote, "show", "-s", "--format=%B", merge
            ).stdout.removesuffix("\n"),
            "merge.parents": len(
                real_git(landing.remote, "show", "-s", "--format=%P", merge).stdout.split()
            ),
        }
        expected = {
            "merge.message": "Merge pull request #12\n\nordinary merge without classification\n",
            "merge.parents": 2,
        }
        assert observed == expected
    if case.method is board.MergeMethod.SQUASH:
        observed = {
            "recorded.head": client.landings[12].head_sha,
            "lane.ancestor": real_git(
                landing.remote, "merge-base", "--is-ancestor", landing.head, merge, check=False
            ).returncode,
            "merge.parents": len(
                real_git(landing.remote, "show", "-s", "--format=%P", merge).stdout.split()
            ),
        }
        expected = {"recorded.head": landing.head, "lane.ancestor": 1, "merge.parents": 1}
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
        client.closes_on_merge = False
        client.close_error = forge.ForgeError(case.close_error) if case.close_error else None
        client.delete_error = forge.ForgeError(case.delete_error) if case.delete_error else None
        observed = {
            "auto-close": client.closes_on_merge,
            "close-error": str(client.close_error) if client.close_error else None,
            "delete-error": str(client.delete_error) if client.delete_error else None,
        }
        expected = {
            "auto-close": False,
            "close-error": case.close_error,
            "delete-error": case.delete_error,
        }
        if isinstance(case.identity, protocol.IssueIdentity):
            observed["item"] = client.item_reference(case.identity.issue).state
            expected["item"] = forge.ItemState.OPEN
        assert observed == expected

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
    return RerunWorld(shared, case, merge)


class TestLandAfterMergeRerun:
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
                    trailer="No-Item: fix\n",
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
                ),
                id="merge-trailer-survives-body-edit",
            ),
            pytest.param(
                RerunCase(
                    method=board.MergeMethod.SQUASH, arguments=("land", "12", "--head", "0000000")
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
                    trailer=None,
                    status=2,
                    stdout="",
                    stderr="ERROR: MERGED pull request #12 as {merge}; follow-up incomplete: "
                    "release (merge commit {merge} carries no `Work-Item:` or `No-Item:` trailer); "
                    "re-run aco land 12\n",
                ),
                id="missing-trailer-gap-17",
            )
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
