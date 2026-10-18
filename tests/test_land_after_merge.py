"""Fresh landings retain their claim and checkout when a follow-up fails."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest
from cli_fixtures import (
    add_lane_worktree,
    local_branches,
    real_git,
    run_cli,
    stub_one_git_call,
    trunk_git_calls,
)
from github_fixtures import LANDING_DEFAULT_BRANCH, FakeForge, LaneLandingWorld, lane_landing_world

from agent_coordination import checkout, forge, protocol, store


class TrunkState(Enum):
    ALIGNED = "0\t1\n"
    DIVERGED = "1\t1\n"


class ExpectedTrunk(Enum):
    UNCHANGED = "unchanged"
    FAST_FORWARDED = "fast-forwarded"


@dataclass(frozen=True)
class FailureCase:
    stderr: str
    error: str | None = None
    trunk: TrunkState = TrunkState.ALIGNED
    delete_error: str | None = None
    close_error: str | None = None
    deleted_branches: tuple[str, ...] = ("codex/issue-72-claims",)
    fetch_calls: tuple[str, ...] = ("fetch",)
    expected_trunk: ExpectedTrunk = ExpectedTrunk.UNCHANGED


@dataclass
class FailureWorld:
    landing: LaneLandingWorld
    case: FailureCase
    lane: Path
    trunk_before: str
    remote_before: str


@pytest.fixture
def world(
    request: pytest.FixtureRequest,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> FailureWorld:
    case: FailureCase = request.param
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("GIT_DISCOVERY_ACROSS_FILESYSTEM", "1")
    real_git(github_clone, "config", "advice.diverging", "false")
    lane = github_clone.parent / "lane"

    def arrange(client: FakeForge, _head: str) -> None:
        add_lane_worktree(github_clone, lane, "codex/issue-72-claims")
        client.closes_on_merge = False
        client.delete_error = forge.ForgeError(case.delete_error) if case.delete_error else None
        client.close_error = forge.ForgeError(case.close_error) if case.close_error else None
        if case.trunk is TrunkState.DIVERGED:
            real_git(github_clone, "commit", "--allow-empty", "-qm", "local trunk change")
        observed = {
            "locale": os.environ["LC_ALL"],
            "branch": real_git(github_clone, "branch", "--show-current").stdout,
            "status": real_git(github_clone, "status", "--porcelain").stdout,
            "item": client.item_reference(72).state,
            "auto-close": client.closes_on_merge,
            "delete-error": str(client.delete_error) if client.delete_error else None,
            "close-error": str(client.close_error) if client.close_error else None,
            "topology": real_git(
                github_clone, "rev-list", "--left-right", "--count", "main...codex/issue-72-claims"
            ).stdout,
            "advice": real_git(github_clone, "config", "advice.diverging").stdout,
            "merged": client.landings[12].merged,
        }
        expected = {
            "locale": "C",
            "branch": "main\n",
            "status": "",
            "item": forge.ItemState.OPEN,
            "auto-close": False,
            "delete-error": case.delete_error,
            "close-error": case.close_error,
            "topology": case.trunk.value,
            "advice": "false\n",
            "merged": False,
        }
        assert observed == expected

    landing = lane_landing_world(
        github_clone,
        bare_remote,
        monkeypatch,
        identity=protocol.IssueIdentity(72),
        branch="codex/issue-72-claims",
        body="Work-Item: #72\n\nCloses #72",
        methods=None,
        arrange=arrange,
    )
    if case.error is not None:
        stub_one_git_call(monkeypatch, ["fetch", "origin"], exit_status=1, stderr=case.error)
        probe = checkout._git_run(["fetch", "origin"], directory=github_clone)
        observed = (probe.exit_status, probe.stderr)
        expected = (1, case.error.encode())
        assert observed == expected
    return FailureWorld(
        landing,
        case,
        lane,
        real_git(github_clone, "rev-parse", LANDING_DEFAULT_BRANCH).stdout.strip(),
        real_git(bare_remote, "rev-parse", LANDING_DEFAULT_BRANCH).stdout.strip(),
    )


class TestLandAfterMerge:
    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                FailureCase(
                    "ERROR: MERGED pull request #12 as <sha>; follow-up incomplete: "
                    "delete-branch (delete branch failed (simulated)); re-run aco land 12\n",
                    delete_error="delete branch failed (simulated)",
                    deleted_branches=(),
                    fetch_calls=(),
                ),
                id="delete-branch",
            ),
            pytest.param(
                FailureCase(
                    "ERROR: MERGED pull request #12 as <sha>; follow-up incomplete: "
                    "fast-forward (fatal: unreachable); re-run aco land 12\n",
                    error="fatal: unreachable",
                ),
                id="fetch-fails",
            ),
            pytest.param(
                FailureCase(
                    "ERROR: MERGED pull request #12 as <sha>; follow-up incomplete: "
                    "fast-forward (fatal: unreachable\\n\\x1b[2Jhint: \\u202eretry); "
                    "re-run aco land 12\n",
                    error="fatal: unreachable\n\x1b[2Jhint: \u202eretry",
                ),
                id="fetch-fails-with-terminal-controls-escaped",
            ),
            pytest.param(
                FailureCase(
                    "ERROR: MERGED pull request #12 as <sha>; follow-up incomplete: "
                    "fast-forward (fatal: Not possible to fast-forward, aborting.); "
                    "re-run aco land 12\n",
                    trunk=TrunkState.DIVERGED,
                ),
                id="ff-only-fails",
            ),
            pytest.param(
                FailureCase(
                    "ERROR: MERGED pull request #12 as <sha>; follow-up incomplete: "
                    "release (forge unreachable); re-run aco land 12\n",
                    close_error="forge unreachable",
                    expected_trunk=ExpectedTrunk.FAST_FORWARDED,
                ),
                id="release-fails",
            ),
        ],
        indirect=True,
    )
    def test_reports_incomplete_follow_up(
        self,
        world: FailureWorld,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Spec: LANDCMD-15, LANDCMD-26, LANDCMD-21, REL-24.
        Each failed step retains recoverable state and prints its own error and retry.
        """
        landing = world.landing
        calls = trunk_git_calls(monkeypatch, "origin")
        capsys.readouterr()
        result = run_cli(["land", "12"], capsys)
        land_calls = list(calls)
        remote = real_git(landing.remote, "rev-parse", landing.default_branch).stdout.strip()
        trunk = real_git(landing.clone, "rev-parse", landing.default_branch).stdout.strip()
        claims = store.peek_state(worktree=landing.clone, remote=str(landing.remote)).claims
        branches = local_branches(landing.clone)
        expected_trunks = {
            ExpectedTrunk.UNCHANGED: world.trunk_before,
            ExpectedTrunk.FAST_FORWARDED: landing.forge.landings[12].merge_commit,
        }
        observed = {
            "exit": result.status,
            "stdout": result.stdout,
            "stderr": result.stderr.replace(remote.strip(), "<sha>"),
            "merge.recorded": landing.forge.landings[12].merge_commit is not None,
            "merge.calls": len(landing.forge.merge_calls),
            "deleted.branches": tuple(landing.forge.deleted_branches),
            "trunk": trunk,
            "closed.items": set(landing.forge.closed_issues),
            "landing.comments": dict(landing.forge.landing_comments),
            "claims": tuple(sorted(str(claim.claim_id) for claim in claims.values())),
            "lane.exists": world.lane.exists(),
            "lane.branch.exists": "codex/issue-72-claims" in branches,
            "fetch.calls": land_calls,
            "remote.moved": remote != world.remote_before,
        }
        expected = {
            "exit": 2,
            "stdout": "",
            "stderr": world.case.stderr,
            "merge.recorded": True,
            "merge.calls": 1,
            "deleted.branches": world.case.deleted_branches,
            "trunk": expected_trunks[world.case.expected_trunk],
            "closed.items": set(),
            "landing.comments": {},
            "claims": ("landing",),
            "lane.exists": True,
            "lane.branch.exists": True,
            "fetch.calls": [(call, landing.clone.resolve()) for call in world.case.fetch_calls],
            "remote.moved": True,
        }
        if world.case.close_error is not None:
            release = run_cli(
                ["release", "72", "--merged", "12", "--branch", "codex/issue-72-claims"], capsys
            )
            land_sentence = result.stderr.partition("release (")[2].rpartition(
                "); re-run aco land 12\n"
            )[0]
            release_sentence = release.stderr.removeprefix("ERROR: ").removesuffix("\n")
            observed.update(
                {
                    "release.exit": release.status,
                    "release.stdout": release.stdout,
                    "release.stderr": release.stderr,
                    "land.release-sentence": land_sentence,
                    "release.sentence": release_sentence,
                    "release.sentence-equal": land_sentence == release_sentence,
                }
            )
            expected.update(
                {
                    "release.exit": 2,
                    "release.stdout": "",
                    "release.stderr": f"ERROR: {world.case.close_error}\n",
                    "land.release-sentence": world.case.close_error,
                    "release.sentence": world.case.close_error,
                    "release.sentence-equal": True,
                }
            )
        assert observed == expected
