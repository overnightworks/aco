"""Squashed lanes in release's own worktree/branch cleanup section."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from functools import partial
from pathlib import Path

import pytest
from cli_fixtures import fail_git_launch, real_git, run_cli, stub_one_git_call
from github_fixtures import FakeForge, LandedWorld, landed_world

from agent_coordination import board, checkout, process


class Tip(Enum):
    NONE = auto()
    RECORDED_HEAD = auto()
    INTERVENTION_COMMIT = auto()


class Intervention(Enum):
    NONE = auto()
    COMMIT_BEFORE = auto()
    COMMIT_WINDOW = auto()
    LIST_REFUSED = auto()
    LOCK = auto()
    DELETE_LAUNCH = auto()
    DELETE_TIMEOUT = auto()
    LIST_TIMEOUT = auto()
    SECTION_TIMEOUT = auto()
    RECREATE = auto()
    DOTTED = auto()
    LATIN1 = auto()


class Phase(Enum):
    BEFORE = auto()
    WINDOW = auto()
    BRANCH_EXISTS = auto()


@dataclass(frozen=True)
class CleanupCase:
    intervention: Intervention = Intervention.NONE
    command: tuple[str, ...] = ("land", "12")
    squashed_before_run: bool = False
    stdout: str = "RELEASED issue #72: landing\nfreed: none\nnext: none\nworktree: removed\n"
    stderr: str = ""
    status: int = 0
    worktree_exists: bool = False
    branch_exists: bool = False
    tip: Tip = Tip.NONE
    keys: tuple[str, ...] = ()
    own_section: bool = False
    launches: tuple[tuple[str, ...], ...] = ()
    allowed_methods: frozenset[board.MergeMethod] = frozenset({board.MergeMethod.SQUASH})
    initial_keys: tuple[str, ...] = ("branch.{lane}.remote", "branch.{lane}.merge")
    applications: int = 1
    phase: Phase = Phase.BEFORE
    existed_before: bool = True
    intervention_tip: str = "{head}"
    intervention_parent: str = "{parent}"
    locked: bool = False
    intervention_keys: tuple[str, ...] = ("branch.{lane}.remote", "branch.{lane}.merge")
    latin1: bool = False


@dataclass
class InterventionRecord:
    launches: list[list[str]] = field(default_factory=list)
    raced: str = ""
    applications: int = 0
    snapshot: dict[str, object] = field(default_factory=dict)


def branch_tip(clone: Path, branch: str) -> str | tuple[int, str] | None:
    result = real_git(
        clone, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False
    )
    return {0: result.stdout.strip(), 1: None}.get(
        result.returncode, (result.returncode, result.stderr)
    )


def configuration_keys(clone: Path) -> tuple[str, ...] | tuple[int, str]:
    result = real_git(
        clone,
        "config",
        "--local",
        "--null",
        "--name-only",
        "--get-regexp",
        r"^branch\.",
        check=False,
    )
    return {0: tuple(result.stdout.rstrip("\0").split("\0")), 1: ()}.get(
        result.returncode, (result.returncode, result.stderr)
    )


@dataclass
class CleanupIntervention:
    world: LandedWorld
    monkeypatch: pytest.MonkeyPatch
    branch: str
    record: InterventionRecord

    @property
    def clone(self) -> Path:
        return self.world.landing.clone

    def apply(self, action: Callable[[], None], phase: Phase) -> None:
        self.record.applications += 1
        before = branch_tip(self.clone, self.branch)
        action()
        parent = real_git(self.clone, "rev-parse", f"refs/heads/{self.branch}^", check=False)
        self.record.snapshot = {
            "intervention.phase": phase,
            "intervention.branch.existed-before": before is not None,
            "intervention.branch.tip-after": branch_tip(self.clone, self.branch),
            "intervention.branch.parent-after": parent.stdout.strip(),
            "intervention.config-lock.exists": (self.clone / ".git/config.lock").exists(),
            "intervention.configuration.keys": configuration_keys(self.clone),
            "intervention.latin1-description.present": (
                b'[branch "other"]\n\tdescription = caf\xe9\n'
                in (self.clone / ".git/config").read_bytes()
            ),
        }

    def before(self, action: Callable[[], None]) -> None:
        self.apply(action, Phase.BEFORE)

    def window(self, action: Callable[[], None]) -> None:
        remove = checkout.remove_linked_worktree

        def interfere_then_remove(
            path: Path, *, branch: str, landed_head: str | None = None
        ) -> checkout.WorktreeCleanupOutcome:
            self.apply(action, Phase.WINDOW)
            return remove(path, branch=branch, landed_head=landed_head)

        self.monkeypatch.setattr(checkout, "remove_linked_worktree", interfere_then_remove)

    def recreation(self, action: Callable[[], None]) -> None:
        exists = checkout.branch_exists

        def recreate_then_observe(branch: str) -> bool:
            self.apply(action, Phase.BRANCH_EXISTS)
            return exists(branch)

        self.monkeypatch.setattr(checkout, "branch_exists", recreate_then_observe)

    def nothing(self) -> None:
        pass

    def commit(self) -> None:
        real_git(self.world.lane, "commit", "-q", "--allow-empty", "-m", "after the pinned head")
        self.record.raced = real_git(self.world.lane, "rev-parse", "HEAD").stdout.strip()

    def refuse_listing(self) -> None:
        stub_one_git_call(
            self.monkeypatch,
            ["config", "--local", "--null", "--name-only", "--get-regexp", r"^branch\."],
            exit_status=3,
            stderr="fatal: the listing failed\n",
        )

    def lock(self) -> None:
        (self.clone / ".git/config.lock").touch()

    def fail_launch(self, arguments: list[str], failure: Exception) -> None:
        self.record.launches = fail_git_launch(self.monkeypatch, arguments, failure)

    def recreate(self) -> None:
        real_git(self.clone, "branch", "-q", self.branch, self.world.landing.head)

    def dotted(self) -> None:
        real_git(self.clone, "config", "--remove-section", f"branch.{self.branch}")
        real_git(self.clone, "branch", "-q", f"{self.branch}.x", self.world.landing.head)
        real_git(self.clone, "config", f"branch.{self.branch}.x.remote", "origin")

    def latin1(self) -> None:
        with (self.clone / ".git/config").open("ab") as configuration:
            configuration.write(b'[branch "other"]\n\tdescription = caf\xe9\n')

    def install(self, intervention: Intervention) -> None:
        deletion = ["update-ref", "-d"]
        listing = ["config", "--local", "--null", "--name-only", "--get-regexp", r"^branch\."]
        section = ["config", "--local", "--remove-section", f"branch.{self.branch}"]
        actions = {
            Intervention.NONE: (self.before, self.nothing),
            Intervention.COMMIT_BEFORE: (self.before, self.commit),
            Intervention.COMMIT_WINDOW: (self.window, self.commit),
            Intervention.LIST_REFUSED: (self.before, self.refuse_listing),
            Intervention.LOCK: (self.window, self.lock),
            Intervention.DELETE_LAUNCH: (
                self.before,
                partial(self.fail_launch, deletion, PermissionError("permission denied")),
            ),
            Intervention.DELETE_TIMEOUT: (
                self.before,
                partial(self.fail_launch, deletion, process.ProcessTimedOutError()),
            ),
            Intervention.LIST_TIMEOUT: (
                self.before,
                partial(self.fail_launch, listing, process.ProcessTimedOutError()),
            ),
            Intervention.SECTION_TIMEOUT: (
                self.before,
                partial(self.fail_launch, section, process.ProcessTimedOutError()),
            ),
            Intervention.RECREATE: (self.recreation, self.recreate),
            Intervention.DOTTED: (self.window, self.dotted),
            Intervention.LATIN1: (self.window, self.latin1),
        }
        timing, action = actions[intervention]
        timing(action)


def allow_squash(client: FakeForge, _head: str) -> None:
    client.allowed_methods = frozenset({board.MergeMethod.SQUASH})


def no_premerge(_world: LandedWorld) -> None:
    pass


def squash_before_run(world: LandedWorld) -> None:
    world.landing.forge.merge_landing(
        12,
        head_sha=world.landing.head,
        method=board.MergeMethod.SQUASH,
        title="feat: land the lane (#12)",
        body="Work-Item: #72",
    )


PREFIX = "RELEASED issue #72: landing\nfreed: none\nnext: none\n"
OWN_KEYS = ("branch.{lane}.remote", "branch.{lane}.merge")
PAST_HEAD = CleanupCase(
    intervention=Intervention.COMMIT_BEFORE,
    stdout=PREFIX + "worktree: kept -- not merged into the default branch\n",
    worktree_exists=True,
    branch_exists=True,
    tip=Tip.INTERVENTION_COMMIT,
    keys=OWN_KEYS,
    own_section=True,
    intervention_tip="{raced}",
    intervention_parent="{head}",
)
SECTION_KEPT = CleanupCase(keys=OWN_KEYS, own_section=True)
CONFIG_TIMEOUT = replace(
    SECTION_KEPT,
    stdout=PREFIX
    + "worktree: removed; branch.{lane} section kept -- git failure: git config timed out\n",
)
DELETE_ARGV = (("update-ref", "-d", "refs/heads/{lane}", "{head}"),)
RELEASE_COMMAND = ("release", "72", "--merged", "12")
CleanupCheck = Callable[[CleanupCase], None]


@pytest.fixture
def cleanup_check(
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> CleanupCheck:
    return partial(
        verify_cleanup,
        github_clone=github_clone,
        bare_remote=bare_remote,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(PAST_HEAD, id="land-with-the-lane-past-the-pinned-head"),
        pytest.param(
            CleanupCase(command=RELEASE_COMMAND, squashed_before_run=True),
            id="release-rerun-on-the-recorded-head",
        ),
        pytest.param(
            replace(PAST_HEAD, command=RELEASE_COMMAND, squashed_before_run=True),
            id="release-rerun-past-the-recorded-head",
        ),
    ],
)
def test_a_squashed_lane_goes_only_on_its_recorded_head(
    case: CleanupCase, cleanup_check: CleanupCheck
) -> None:
    """Keep land's Accepted residual; reruns use the recorded squash head.

    Spec: REL-43, E-REL-20, LANDCMD-18.
    """
    cleanup_check(case)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(CleanupCase(), id="clean"),
        pytest.param(
            replace(
                PAST_HEAD,
                intervention=Intervention.COMMIT_WINDOW,
                phase=Phase.WINDOW,
                worktree_exists=False,
                stdout=PREFIX
                + "worktree: removed; branch kept -- git failure: error: cannot lock ref "
                "'refs/heads/{lane}': is at {raced} but expected {head}\n",
            ),
            id="commit-raced-past-the-head",
        ),
        pytest.param(
            replace(
                SECTION_KEPT,
                intervention=Intervention.LIST_REFUSED,
                stdout=PREFIX + "worktree: removed; branch.{lane} section kept -- git failure: "
                "fatal: the listing failed\n",
            ),
            id="configuration-listing-refused",
        ),
        pytest.param(
            replace(
                SECTION_KEPT,
                intervention=Intervention.LOCK,
                phase=Phase.WINDOW,
                locked=True,
                stdout=PREFIX + "worktree: removed; branch.{lane} section kept -- git failure: "
                "error: could not lock config file .git/config\n",
            ),
            id="configuration-locked",
        ),
        pytest.param(
            replace(
                SECTION_KEPT,
                intervention=Intervention.DELETE_LAUNCH,
                branch_exists=True,
                tip=Tip.RECORDED_HEAD,
                launches=DELETE_ARGV,
                stdout=PREFIX + "worktree: removed; branch kept -- git failure: "
                "git failed to launch: permission denied\n",
            ),
            id="deletion-failed-to-start",
        ),
        pytest.param(
            replace(
                SECTION_KEPT,
                intervention=Intervention.DELETE_TIMEOUT,
                branch_exists=True,
                tip=Tip.RECORDED_HEAD,
                launches=DELETE_ARGV,
                stdout=PREFIX + "worktree: removed; branch unknown -- git update-ref timed out; "
                "check git branch --list {lane}\n",
            ),
            id="deletion-timed-out",
        ),
        pytest.param(
            replace(
                CONFIG_TIMEOUT,
                intervention=Intervention.LIST_TIMEOUT,
                launches=(
                    ("config", "--local", "--null", "--name-only", "--get-regexp", r"^branch\."),
                ),
            ),
            id="configuration-listing-timed-out",
        ),
        pytest.param(
            replace(
                CONFIG_TIMEOUT,
                intervention=Intervention.SECTION_TIMEOUT,
                launches=(("config", "--local", "--remove-section", "branch.{lane}"),),
            ),
            id="section-removal-timed-out",
        ),
        pytest.param(
            replace(
                SECTION_KEPT,
                intervention=Intervention.RECREATE,
                phase=Phase.BRANCH_EXISTS,
                existed_before=False,
                branch_exists=True,
                tip=Tip.RECORDED_HEAD,
            ),
            id="same-name-branch-recreated",
        ),
        pytest.param(
            CleanupCase(
                intervention=Intervention.DOTTED,
                phase=Phase.WINDOW,
                keys=("branch.{lane}.x.remote",),
                intervention_keys=("branch.{lane}.x.remote",),
            ),
            id="dotted-sibling-without-an-own-section",
        ),
        pytest.param(
            CleanupCase(
                intervention=Intervention.LATIN1,
                phase=Phase.WINDOW,
                keys=("branch.other.description",),
                intervention_keys=(*OWN_KEYS, "branch.other.description"),
                latin1=True,
            ),
            id="another-branch-value-not-utf-8",
        ),
    ],
)
def test_a_squashed_lane_branch_goes_by_compare_and_delete(
    case: CleanupCase, cleanup_check: CleanupCheck
) -> None:
    """Delete only the pinned branch and its own configuration section.

    Spec: REL-34, REL-42, REL-44, REL-45, REL-46, E-REL-21, E-REL-22, E-REL-23.
    """
    cleanup_check(case)


def verify_cleanup(
    case: CleanupCase,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    world = landed_world(github_clone, bare_remote, monkeypatch, extra_arrange=allow_squash)
    head = world.landing.head
    lane = "codex/issue-72-claims"
    parent = real_git(github_clone, "rev-parse", f"{head}^").stdout.strip()
    observed_initial = {
        "squash.allowed-methods": world.landing.forge.allowed_methods,
        "initial.lane.head": real_git(world.lane, "rev-parse", "HEAD").stdout.strip(),
        "initial.own-section.keys": configuration_keys(github_clone),
    }
    expected_initial = {
        "squash.allowed-methods": case.allowed_methods,
        "initial.lane.head": head,
        "initial.own-section.keys": tuple(key.format(lane=lane) for key in case.initial_keys),
    }
    assert observed_initial == expected_initial
    {False: no_premerge, True: squash_before_run}[case.squashed_before_run](world)
    observed_prepared = {"prepared.landing.merged": world.landing.forge.landings[12].merged}
    expected_prepared = {"prepared.landing.merged": case.squashed_before_run}
    assert observed_prepared == expected_prepared
    record = InterventionRecord()
    intervention = CleanupIntervention(world, monkeypatch, lane, record)
    intervention.install(case.intervention)
    capsys.readouterr()
    result = run_cli(list(case.command), capsys)
    values = {"head": head, "raced": record.raced, "lane": lane, "parent": parent}
    observed_guard = {"intervention.applications": record.applications, **record.snapshot}
    expected_guard = {
        "intervention.applications": case.applications,
        "intervention.phase": case.phase,
        "intervention.branch.existed-before": case.existed_before,
        "intervention.branch.tip-after": case.intervention_tip.format(**values),
        "intervention.branch.parent-after": case.intervention_parent.format(**values),
        "intervention.config-lock.exists": case.locked,
        "intervention.configuration.keys": tuple(
            key.format(**values) for key in case.intervention_keys
        ),
        "intervention.latin1-description.present": case.latin1,
    }
    assert observed_guard == expected_guard
    tips = {
        Tip.NONE: None,
        Tip.RECORDED_HEAD: head,
        Tip.INTERVENTION_COMMIT: record.raced,
    }
    actual_tip = branch_tip(github_clone, lane)
    keys = configuration_keys(github_clone)
    own_section = real_git(
        github_clone,
        "config",
        "--local",
        "--name-only",
        "--get-regexp",
        rf"^branch\.{lane}\.[^.]+$",
        check=False,
    )
    observed = {
        "exit": result.status,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "lane.worktree.exists": world.lane.exists(),
        "lane.branch.exists": actual_tip is not None,
        "lane.branch.tip": actual_tip,
        "configuration.keys": keys,
        "configuration.own-section.exists": {0: True, 1: False}.get(
            own_section.returncode, (own_section.returncode, own_section.stderr)
        ),
        "launch.argv": record.launches,
    }
    expected = {
        "exit": case.status,
        "stdout": case.stdout.format(**values),
        "stderr": case.stderr.format(**values),
        "lane.worktree.exists": case.worktree_exists,
        "lane.branch.exists": case.branch_exists,
        "lane.branch.tip": tips[case.tip],
        "configuration.keys": tuple(key.format(**values) for key in case.keys),
        "configuration.own-section.exists": case.own_section,
        "launch.argv": [[argument.format(**values) for argument in call] for call in case.launches],
    }
    assert observed == expected
