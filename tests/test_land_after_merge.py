"""Fresh landings retain their claim and checkout when a follow-up fails."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import assert_never

import pytest
from cli_fixtures import add_lane_worktree, real_git, run_cli, stub_one_git_call, trunk_git_calls
from github_fixtures import FakeForge, LaneLandingWorld, lane_landing_world

from agent_coordination import checkout, forge, protocol, store


class FailureStage(Enum):
    DELETE = "delete"
    FETCH = "fetch"
    FETCH_CONTROLS = "fetch-controls"
    DIVERGED = "diverged"
    RELEASE = "release"


class TrunkState(Enum):
    ALIGNED = "0\t1\n"
    DIVERGED = "1\t1\n"


@dataclass(frozen=True)
class FailureCase:
    stage: FailureStage
    stderr: str
    error: str | None = None
    trunk: TrunkState = TrunkState.ALIGNED


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
        match case.stage:
            case FailureStage.DELETE:
                client.delete_error = forge.ForgeError("delete branch failed (simulated)")
            case FailureStage.RELEASE:
                client.close_error = forge.ForgeError("forge unreachable")
            case FailureStage.DIVERGED:
                real_git(github_clone, "commit", "--allow-empty", "-qm", "local trunk change")
            case FailureStage.FETCH | FailureStage.FETCH_CONTROLS:
                pass
            case _ as unreachable:
                assert_never(unreachable)
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
            "delete-error": "delete branch failed (simulated)"
            if case.stage is FailureStage.DELETE
            else None,
            "close-error": "forge unreachable" if case.stage is FailureStage.RELEASE else None,
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
        real_git(github_clone, "rev-parse", "main").stdout,
        real_git(bare_remote, "rev-parse", "main").stdout,
    )


class TestLandAfterMerge:
    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                FailureCase(
                    FailureStage.DELETE,
                    "ERROR: MERGED pull request #12 as <sha>; follow-up incomplete: "
                    "delete-branch (delete branch failed (simulated)); re-run aco land 12\n",
                ),
                id="delete-branch",
            ),
            pytest.param(
                FailureCase(
                    FailureStage.FETCH,
                    "ERROR: MERGED pull request #12 as <sha>; follow-up incomplete: "
                    "fast-forward (fatal: unreachable); re-run aco land 12\n",
                    error="fatal: unreachable",
                ),
                id="fetch-fails",
            ),
            pytest.param(
                FailureCase(
                    FailureStage.FETCH_CONTROLS,
                    "ERROR: MERGED pull request #12 as <sha>; follow-up incomplete: "
                    "fast-forward (fatal: unreachable\\n\\x1b[2Jhint: \\u202eretry); "
                    "re-run aco land 12\n",
                    error="fatal: unreachable\n\x1b[2Jhint: \u202eretry",
                ),
                id="fetch-fails-with-terminal-controls-escaped",
            ),
            pytest.param(
                FailureCase(
                    FailureStage.DIVERGED,
                    "ERROR: MERGED pull request #12 as <sha>; follow-up incomplete: "
                    "fast-forward (fatal: Not possible to fast-forward, aborting.); "
                    "re-run aco land 12\n",
                    trunk=TrunkState.DIVERGED,
                ),
                id="ff-only-fails",
            ),
            pytest.param(
                FailureCase(
                    FailureStage.RELEASE,
                    "ERROR: MERGED pull request #12 as <sha>; follow-up incomplete: "
                    "release (forge unreachable); re-run aco land 12\n",
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
        remote = real_git(landing.remote, "rev-parse", "main").stdout
        trunk = real_git(landing.clone, "rev-parse", "main").stdout
        claims = store.peek_state(worktree=landing.clone, remote=str(landing.remote)).claims
        branches = real_git(
            landing.clone, "for-each-ref", "--format=%(refname:short)", "refs/heads"
        ).stdout.splitlines()
        observed = {
            "O01": result.status,
            "O02": result.stdout,
            "O03": result.stderr.replace(remote.strip(), "<sha>"),
            "O04": result.stderr.rpartition("; ")[2],
            "O05": landing.forge.landings[12].merge_commit is not None,
            "O06": len(landing.forge.merge_calls),
            "O07": list(landing.forge.deleted_branches),
            "O08": trunk
            == (remote if world.case.stage is FailureStage.RELEASE else world.trunk_before),
            "O09": set(landing.forge.closed_issues),
            "O10": dict(landing.forge.landing_comments),
            "O11": tuple(sorted(str(claim.claim_id) for claim in claims.values())),
            "O12": world.lane.exists(),
            "O13": "codex/issue-72-claims" in branches,
            "O14": land_calls,
            "O15": remote != world.remote_before,
        }
        expected = {
            "O01": 2,
            "O02": "",
            "O03": world.case.stderr,
            "O04": "re-run aco land 12\n",
            "O05": True,
            "O06": 1,
            "O07": [] if world.case.stage is FailureStage.DELETE else ["codex/issue-72-claims"],
            "O08": True,
            "O09": set(),
            "O10": {},
            "O11": ("landing",),
            "O12": True,
            "O13": True,
            "O14": []
            if world.case.stage is FailureStage.DELETE
            else [("fetch", landing.clone.resolve())],
            "O15": True,
        }
        if world.case.stage is FailureStage.RELEASE:
            release = run_cli(
                ["release", "72", "--merged", "12", "--branch", "codex/issue-72-claims"], capsys
            )
            land_sentence = result.stderr.partition("release (")[2].rpartition(
                "); re-run aco land 12\n"
            )[0]
            release_sentence = release.stderr.removeprefix("ERROR: ").removesuffix("\n")
            observed.update(
                {
                    "S01": release.status,
                    "S02": release.stdout,
                    "S03": release.stderr,
                    "S04": land_sentence,
                    "S05": release_sentence,
                    "S06": land_sentence == release_sentence,
                }
            )
            expected.update(
                {
                    "S01": 2,
                    "S02": "",
                    "S03": "ERROR: forge unreachable\n",
                    "S04": "forge unreachable",
                    "S05": "forge unreachable",
                    "S06": True,
                }
            )
        assert observed == expected
