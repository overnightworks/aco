"""Land's trunk update, repository reminder, cleanup and incomplete follow-up."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest
from cli_fixtures import (
    MainBranchState,
    add_lane_worktree,
    init_bare_repository,
    local_branches,
    move_trunk,
    real_git,
    run_cli,
    stub_one_git_call,
    track_board_config,
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


class CanonicalRemote(Enum):
    ORIGIN = "origin"
    HUB = "hub"


@dataclass(frozen=True)
class TrunkCase:
    canonical: CanonicalRemote
    main: MainBranchState
    arguments: tuple[str, ...] = ("land", "12")
    stdout: str = "RELEASED issue #72: landing\nfreed: none\nnext: none\nworktree: removed\n"
    status: int = 0
    stderr: str = ""
    fetch_calls: tuple[str, ...] = ("fetch",)
    origin_calls: tuple[str, ...] | None = None
    lane_exists: bool = False
    expected_trunk: ExpectedTrunk = ExpectedTrunk.FAST_FORWARDED


@dataclass
class TrunkWorld:
    landing: LaneLandingWorld
    case: TrunkCase
    lane: Path


class PackageFile(Enum):
    OWN = '[project]\nname = "agent-coordination"\n'
    OTHER = '[project]\nname = "other-package"\n'
    ABSENT = None
    INVALID = "[\n"
    PROJECT_SCALAR = 'project = "agent-coordination"\n'


@dataclass(frozen=True)
class PackageCase:
    package: PackageFile
    stdout: str
    rerun_stdout: str | None = None
    arguments: tuple[str, ...] = ("land", "12")
    status: int = 0
    stderr: str = ""
    rerun_status: int = 0
    rerun_stderr: str = ""


@dataclass
class PackageWorld:
    landing: LaneLandingWorld
    case: PackageCase


@dataclass(frozen=True)
class KeepCase:
    arguments: tuple[str, ...] = ("land", "12", "--keep-worktree")
    status: int = 0
    stdout: str = (
        "RELEASED issue #72: landing\nfreed: none\nnext: none\n"
        "worktree: kept -- --keep-worktree was given\n"
    )
    stderr: str = ""
    lane_exists: bool = True
    lane_status: str = ""
    branches: frozenset[str] = frozenset({"main", "codex/issue-72-claims"})
    claims: tuple[str, ...] = ()


@dataclass
class KeepWorld:
    landing: LaneLandingWorld
    case: KeepCase
    lane: Path


@pytest.fixture
def keep_world(
    request: pytest.FixtureRequest,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> KeepWorld:
    case: KeepCase = request.param
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("GIT_DISCOVERY_ACROSS_FILESYSTEM", "1")
    lane = github_clone.parent / "lane"

    def arrange(client: FakeForge, _head: str) -> None:
        add_lane_worktree(github_clone, lane, "codex/issue-72-claims")
        observed = {
            "locale": os.environ["LC_ALL"],
            "discovery": os.environ["GIT_DISCOVERY_ACROSS_FILESYSTEM"],
            "checkout.branch": real_git(github_clone, "branch", "--show-current").stdout,
            "checkout.status": real_git(github_clone, "status", "--porcelain").stdout,
            "landing.merged": client.landings[12].merged,
        }
        expected = {
            "locale": "C",
            "discovery": "1",
            "checkout.branch": "main\n",
            "checkout.status": "",
            "landing.merged": False,
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
    return KeepWorld(landing, case, lane)


@pytest.fixture
def package_world(
    request: pytest.FixtureRequest,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> PackageWorld:
    case: PackageCase = request.param
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("GIT_DISCOVERY_ACROSS_FILESYSTEM", "1")
    lane = github_clone.parent / "lane"

    def arrange(client: FakeForge, _head: str) -> None:
        if case.package.value is not None:
            (github_clone / "pyproject.toml").write_text(case.package.value)
            real_git(github_clone, "add", "pyproject.toml")
            real_git(github_clone, "commit", "-qm", "package identity")
            real_git(github_clone, "push", "-q", "origin", LANDING_DEFAULT_BRANCH)
        add_lane_worktree(github_clone, lane, "codex/issue-72-claims")
        package = real_git(github_clone, "show", "HEAD:pyproject.toml", check=False)
        lane_file = lane / "pyproject.toml"
        observed = {
            "locale": os.environ["LC_ALL"],
            "discovery": os.environ["GIT_DISCOVERY_ACROSS_FILESYSTEM"],
            "checkout.branch": real_git(github_clone, "branch", "--show-current").stdout,
            "checkout.status": real_git(github_clone, "status", "--porcelain").stdout,
            "landing.merged": client.landings[12].merged,
            "package.trunk": package.stdout if package.returncode == 0 else None,
            "package.lane": lane_file.read_text() if lane_file.exists() else None,
        }
        expected = {
            "locale": "C",
            "discovery": "1",
            "checkout.branch": "main\n",
            "checkout.status": "",
            "landing.merged": False,
            "package.trunk": case.package.value,
            "package.lane": None,
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
    return PackageWorld(landing, case)


@pytest.fixture
def hub_remote(github_clone: Path, bare_remote: Path) -> Path:
    """Publish the configured canonical trunk beside the origin decoy."""
    remote = init_bare_repository(github_clone.parent / "hub.git")
    url = "https://github.com/example/agent-coordination.git"
    real_git(github_clone, "config", f"url.{remote}.insteadOf", url)
    real_git(github_clone, "remote", "add", "hub", url)
    old_tip = real_git(bare_remote, "rev-parse", "main").stdout.strip()
    track_board_config(github_clone, 'canonical_remote = "hub"\n')
    trunk = real_git(github_clone, "rev-parse", "trunk").stdout.strip()
    real_git(github_clone, "push", "-q", "hub", "trunk", f"{old_tip}:refs/heads/main")
    real_git(remote, "symbolic-ref", "HEAD", "refs/heads/trunk")
    real_git(github_clone, "remote", "set-head", "hub", "--delete")
    observed = {
        "hub.board-config": real_git(github_clone, "show", "HEAD:.aco/board.toml").stdout,
        "hub.url": real_git(github_clone, "config", "remote.hub.url").stdout,
        "hub.remote-head": real_git(remote, "symbolic-ref", "HEAD").stdout,
        "hub.trunk": real_git(remote, "rev-parse", "trunk").stdout.strip(),
        "hub.main": real_git(remote, "rev-parse", "main").stdout.strip(),
        "hub.head-status": real_git(
            github_clone, "show-ref", "--verify", "--quiet", "refs/remotes/hub/HEAD", check=False
        ).returncode,
    }
    expected = {
        "hub.board-config": 'canonical_remote = "hub"\n',
        "hub.url": "https://github.com/example/agent-coordination.git\n",
        "hub.remote-head": "refs/heads/trunk\n",
        "hub.trunk": trunk,
        "hub.main": old_tip,
        "hub.head-status": 1,
    }
    assert observed == expected
    return remote


@pytest.fixture
def trunk_world(
    request: pytest.FixtureRequest,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TrunkWorld:
    case: TrunkCase = request.param
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("GIT_DISCOVERY_ACROSS_FILESYSTEM", "1")
    move_trunk(github_clone, bare_remote, main_state=case.main)
    real_git(github_clone, "remote", "set-head", "origin", "--delete")
    observed = real_git(
        github_clone, "show-ref", "--verify", "--quiet", "refs/remotes/origin/HEAD", check=False
    ).returncode
    expected = 1
    assert observed == expected
    remote = bare_remote
    config = ""
    if case.canonical is CanonicalRemote.HUB:
        remote = request.getfixturevalue("hub_remote")
        config = 'canonical_remote = "hub"\n'
    lane = github_clone.parent / "lane"

    def arrange(client: FakeForge, head: str) -> None:
        if case.canonical is CanonicalRemote.HUB:
            real_git(github_clone, "push", "-q", "hub", "codex/issue-72-claims")
            observed = {
                "hub.lane": real_git(remote, "rev-parse", "codex/issue-72-claims").stdout.strip(),
                "hub.merge-remote": client.merge_remote,
            }
            expected = {"hub.lane": head, "hub.merge-remote": remote}
            assert observed == expected
        add_lane_worktree(github_clone, lane, "codex/issue-72-claims")
        observed = {
            "locale": os.environ["LC_ALL"],
            "discovery": os.environ["GIT_DISCOVERY_ACROSS_FILESYSTEM"],
            "checkout.branch": real_git(github_clone, "branch", "--show-current").stdout,
            "checkout.status": real_git(github_clone, "status", "--porcelain").stdout,
            "landing.merged": client.landings[12].merged,
        }
        expected = {
            "locale": "C",
            "discovery": "1",
            "checkout.branch": "trunk\n",
            "checkout.status": "",
            "landing.merged": False,
        }
        assert observed == expected

    landing = lane_landing_world(
        github_clone,
        remote,
        monkeypatch,
        identity=protocol.IssueIdentity(72),
        branch="codex/issue-72-claims",
        body="Work-Item: #72\n\nCloses #72",
        methods=None,
        default_branch="trunk",
        head_config=config,
        arrange=arrange,
    )
    return TrunkWorld(landing, case, lane)


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
        "keep_world", [pytest.param(KeepCase(), id="keep-worktree")], indirect=True
    )
    def test_keeps_the_requested_worktree(
        self, keep_world: KeepWorld, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: REL-26.
        Land's Never 2 delegates cleanup; #17 owns the missing explicit land sentence.
        """
        landing = keep_world.landing
        case = keep_world.case
        capsys.readouterr()
        result = run_cli(list(case.arguments), capsys)
        claims = store.peek_state(worktree=landing.clone, remote=str(landing.remote)).claims
        observed = {
            "exit": result.status,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "lane.exists": keep_world.lane.exists(),
            "lane.head": real_git(
                landing.clone,
                "rev-parse",
                "--verify",
                "--quiet",
                "refs/heads/codex/issue-72-claims",
                check=False,
            ).stdout.strip(),
            "lane.status": real_git(keep_world.lane, "status", "--porcelain").stdout
            if keep_world.lane.exists()
            else None,
            "branches": local_branches(landing.clone),
            "claims": tuple(sorted(str(claim.claim_id) for claim in claims.values())),
        }
        expected = {
            "exit": case.status,
            "stdout": case.stdout,
            "stderr": case.stderr,
            "lane.exists": case.lane_exists,
            "lane.head": landing.head,
            "lane.status": case.lane_status,
            "branches": case.branches,
            "claims": case.claims,
        }
        assert observed == expected

    @pytest.mark.parametrize(
        "package_world",
        [
            pytest.param(
                PackageCase(
                    PackageFile.OWN,
                    "RELEASED issue #72: landing\nfreed: none\nnext: none\nworktree: removed\n"
                    "reinstall: uv tool install --force --from . agent-coordination\n",
                    "LANDED pull request #12 already; nothing left to release\n"
                    "worktree: kept -- no linked worktree on codex/issue-72-claims "
                    "in this checkout; "
                    "run aco release 72 --merged 12 --branch codex/issue-72-claims "
                    "in the checkout that holds it\n",
                ),
                id="this-package",
            ),
            pytest.param(
                PackageCase(
                    PackageFile.OTHER,
                    "RELEASED issue #72: landing\nfreed: none\nnext: none\nworktree: removed\n",
                ),
                id="another-package",
            ),
            pytest.param(
                PackageCase(
                    PackageFile.ABSENT,
                    "RELEASED issue #72: landing\nfreed: none\nnext: none\nworktree: removed\n",
                ),
                id="no-pyproject-toml",
            ),
            pytest.param(
                PackageCase(
                    PackageFile.INVALID,
                    "RELEASED issue #72: landing\nfreed: none\nnext: none\nworktree: removed\n",
                ),
                id="invalid-pyproject-toml",
            ),
            pytest.param(
                PackageCase(
                    PackageFile.PROJECT_SCALAR,
                    "RELEASED issue #72: landing\nfreed: none\nnext: none\nworktree: removed\n",
                ),
                id="project-is-not-a-table",
            ),
        ],
        indirect=True,
    )
    def test_prints_the_repository_reminder(
        self, package_world: PackageWorld, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: LANDCMD-17, LANDCMD-38.
        The own-package rerun proves "no LANDCMD-17 line follows".
        """
        case = package_world.case
        capsys.readouterr()
        result = run_cli(list(case.arguments), capsys)
        observed = {"exit": result.status, "stdout": result.stdout, "stderr": result.stderr}
        expected = {"exit": case.status, "stdout": case.stdout, "stderr": case.stderr}
        if case.rerun_stdout is not None:
            rerun = run_cli(list(case.arguments), capsys)
            observed.update(
                {
                    "rerun.exit": rerun.status,
                    "rerun.stdout": rerun.stdout,
                    "rerun.stderr": rerun.stderr,
                }
            )
            expected.update(
                {
                    "rerun.exit": case.rerun_status,
                    "rerun.stdout": case.rerun_stdout,
                    "rerun.stderr": case.rerun_stderr,
                }
            )
        assert observed == expected

    @pytest.mark.parametrize(
        "trunk_world",
        [
            pytest.param(
                TrunkCase(CanonicalRemote.ORIGIN, MainBranchState.REMOTE_LEFTOVER),
                id="origin-trunk-fast-forwards",
            ),
            pytest.param(
                TrunkCase(CanonicalRemote.HUB, MainBranchState.REMOTE_LEFTOVER, origin_calls=()),
                id="hub-trunk-fast-forwards",
            ),
            pytest.param(
                TrunkCase(CanonicalRemote.ORIGIN, MainBranchState.ABSENT),
                id="origin-without-main-fast-forwards",
            ),
        ],
        indirect=True,
    )
    def test_uses_the_forges_trunk(
        self,
        trunk_world: TrunkWorld,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Spec: LANDCMD-20, LANDCMD-21, REL-37, REL-38, REL-25."""
        landing = trunk_world.landing
        case = trunk_world.case
        calls = trunk_git_calls(monkeypatch, case.canonical.value)
        origin_calls = trunk_git_calls(monkeypatch, "origin")
        capsys.readouterr()
        result = run_cli(list(case.arguments), capsys)
        land_calls = list(calls)
        origin_land_calls = list(origin_calls)
        observed = {
            "exit": result.status,
            "stderr": result.stderr,
            "stdout": result.stdout,
            "fetch.calls": land_calls,
            "trunk": real_git(landing.clone, "rev-parse", "trunk").stdout.strip(),
            "lane.exists": trunk_world.lane.exists(),
        }
        expected_trunks = {ExpectedTrunk.FAST_FORWARDED: landing.forge.landings[12].merge_commit}
        expected = {
            "exit": case.status,
            "stderr": case.stderr,
            "stdout": case.stdout,
            "fetch.calls": [(call, landing.clone.resolve()) for call in case.fetch_calls],
            "trunk": expected_trunks[case.expected_trunk],
            "lane.exists": case.lane_exists,
        }
        if case.origin_calls is not None:
            observed["origin.calls"] = origin_land_calls
            expected["origin.calls"] = [
                (call, landing.clone.resolve()) for call in case.origin_calls
            ]
        assert observed == expected

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
