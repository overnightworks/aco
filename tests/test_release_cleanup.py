"""Release's own worktree/branch cleanup after a squashed or merged landing."""

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


@dataclass(frozen=True)
class Present:
    value: str | tuple[str, ...] | bool

    def format(self, **values: str) -> Present:
        match self.value:
            case str(template):
                return Present(template.format(**values))
            case tuple(templates):
                return Present(tuple(template.format(**values) for template in templates))
            case _:
                return self


@dataclass(frozen=True)
class Absent:
    def format(self, **values: str) -> Absent:
        return self


@dataclass(frozen=True)
class Unexpected:
    exit_status: int
    text: str


Observation = Present | Absent | Unexpected


class Intervention(Enum):
    NONE = auto()
    COMMIT_BEFORE = auto()
    COMMIT_WINDOW = auto()
    LIST_REFUSED = auto()
    LOCK = auto()
    DELETE_REFUSED = auto()
    RECREATE = auto()
    DOTTED = auto()
    LATIN1 = auto()

    def install(self, target: CleanupIntervention) -> None:
        actions = {
            Intervention.NONE: (target.before, target.nothing),
            Intervention.COMMIT_BEFORE: (target.before, target.commit),
            Intervention.COMMIT_WINDOW: (target.window, target.commit),
            Intervention.LIST_REFUSED: (target.before, target.refuse_listing),
            Intervention.DELETE_REFUSED: (target.before, target.refuse_deletion),
            Intervention.LOCK: (target.window, target.lock),
            Intervention.RECREATE: (target.recreation, target.recreate),
            Intervention.DOTTED: (target.window, target.dotted),
            Intervention.LATIN1: (target.window, target.latin1),
        }
        timing, action = actions[self]
        timing(action)


class LaunchFailure(Enum):
    LAUNCH_FAILS = auto()
    TIMES_OUT = auto()


@dataclass(frozen=True)
class LaunchIntervention:
    failure: LaunchFailure
    git_call: tuple[str, ...]

    def install(self, target: CleanupIntervention) -> None:
        failure = {
            LaunchFailure.LAUNCH_FAILS: PermissionError("permission denied"),
            LaunchFailure.TIMES_OUT: process.ProcessTimedOutError(),
        }[self.failure]
        arguments = [argument.format(lane=target.branch) for argument in self.git_call]
        target.before(partial(target.fail_launch, arguments, failure))


class Phase(Enum):
    BEFORE = auto()
    WINDOW = auto()
    BRANCH_EXISTS = auto()


PREFIX = "RELEASED issue #72: landing\nfreed: none\nnext: none\n"
OWN_KEYS = ("branch.{lane}.remote", "branch.{lane}.merge")
LISTING_ARGUMENTS = ("config", "--local", "--null", "--name-only", "--get-regexp", r"^branch\.")


@dataclass(frozen=True)
class CleanupCase:
    intervention: Intervention | LaunchIntervention = Intervention.NONE
    command: tuple[str, ...] = ("land", "12")
    premerge: board.MergeMethod | None = None
    stdout: str = PREFIX + "worktree: removed\n"
    stderr: str = ""
    status: int = 0
    worktree_exists: bool = False
    branch: Present | Absent = Absent()
    keys: Present | Absent = Absent()
    own_section: Present | Absent = Absent()
    launches: tuple[tuple[str, ...], ...] = ()
    phase: Phase = Phase.BEFORE
    existed_before: Present | Absent = Present("{head}")
    intervention_tip: Present | Absent = Present("{head}")
    intervention_parent: Present | Absent = Present("{parent}")
    locked: bool = False
    intervention_keys: Present | Absent = Present(OWN_KEYS)
    latin1: bool = False


@dataclass
class InterventionRecord:
    launches: list[list[str]] = field(default_factory=list)
    raced: str = ""
    applications: int = 0
    snapshot: dict[str, object] = field(default_factory=dict)


def branch_tip(clone: Path, branch: str) -> Observation:
    result = real_git(
        clone, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False
    )
    return {0: Present(result.stdout.strip()), 1: Absent()}.get(
        result.returncode, Unexpected(result.returncode, result.stderr)
    )


def configuration_keys(clone: Path) -> Observation:
    result = real_git(clone, *LISTING_ARGUMENTS, check=False)
    return {0: Present(tuple(result.stdout.rstrip("\0").split("\0"))), 1: Absent()}.get(
        result.returncode, Unexpected(result.returncode, result.stderr)
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
        self.record.snapshot = {
            "intervention.phase": phase,
            "intervention.branch.existed-before": before,
            "intervention.branch.tip-after": branch_tip(self.clone, self.branch),
            "intervention.branch.parent-after": branch_tip(self.clone, f"{self.branch}^"),
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
            list(LISTING_ARGUMENTS),
            exit_status=3,
            stderr="fatal: the listing failed\n",
        )

    def refuse_deletion(self) -> None:
        stub_one_git_call(
            self.monkeypatch,
            ["branch", "-d", self.branch],
            exit_status=1,
            stderr="error: branch not fully merged",
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


def allow_squash(client: FakeForge, _head: str) -> None:
    client.allowed_methods = frozenset({board.MergeMethod.SQUASH})


def no_premerge(_world: LandedWorld) -> None:
    pass


def merge_before_run(world: LandedWorld, *, method: board.MergeMethod) -> None:
    world.landing.forge.merge_landing(
        12,
        head_sha=world.landing.head,
        method=method,
        title="feat: land the lane (#12)",
        body="Work-Item: #72",
    )


PAST_HEAD = CleanupCase(
    intervention=Intervention.COMMIT_BEFORE,
    stdout=PREFIX + "worktree: kept -- not merged into the default branch\n",
    worktree_exists=True,
    branch=Present("{raced}"),
    keys=Present(OWN_KEYS),
    own_section=Present(True),
    intervention_tip=Present("{raced}"),
    intervention_parent=Present("{head}"),
)
SECTION_KEPT = CleanupCase(keys=Present(OWN_KEYS), own_section=Present(True))
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
            CleanupCase(command=RELEASE_COMMAND, premerge=board.MergeMethod.SQUASH),
            id="release-rerun-on-the-recorded-head",
        ),
        pytest.param(
            replace(PAST_HEAD, command=RELEASE_COMMAND, premerge=board.MergeMethod.SQUASH),
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
                intervention=LaunchIntervention(LaunchFailure.LAUNCH_FAILS, ("update-ref", "-d")),
                branch=Present("{head}"),
                launches=DELETE_ARGV,
                stdout=PREFIX + "worktree: removed; branch kept -- git failure: "
                "git failed to launch: permission denied\n",
            ),
            id="deletion-failed-to-start",
        ),
        pytest.param(
            replace(
                SECTION_KEPT,
                intervention=LaunchIntervention(LaunchFailure.TIMES_OUT, ("update-ref", "-d")),
                branch=Present("{head}"),
                launches=DELETE_ARGV,
                stdout=PREFIX + "worktree: removed; branch unknown -- git update-ref timed out; "
                "check git branch --list {lane}\n",
            ),
            id="deletion-timed-out",
        ),
        pytest.param(
            replace(
                CONFIG_TIMEOUT,
                intervention=LaunchIntervention(LaunchFailure.TIMES_OUT, LISTING_ARGUMENTS),
                launches=(
                    ("config", "--local", "--null", "--name-only", "--get-regexp", r"^branch\."),
                ),
            ),
            id="configuration-listing-timed-out",
        ),
        pytest.param(
            replace(
                CONFIG_TIMEOUT,
                intervention=LaunchIntervention(
                    LaunchFailure.TIMES_OUT,
                    ("config", "--local", "--remove-section", "branch.{lane}"),
                ),
                launches=(("config", "--local", "--remove-section", "branch.{lane}"),),
            ),
            id="section-removal-timed-out",
        ),
        pytest.param(
            replace(
                SECTION_KEPT,
                intervention=Intervention.RECREATE,
                phase=Phase.BRANCH_EXISTS,
                existed_before=Absent(),
                branch=Present("{head}"),
            ),
            id="same-name-branch-recreated",
        ),
        pytest.param(
            CleanupCase(
                intervention=Intervention.DOTTED,
                phase=Phase.WINDOW,
                keys=Present(("branch.{lane}.x.remote",)),
                intervention_keys=Present(("branch.{lane}.x.remote",)),
            ),
            id="dotted-sibling-without-an-own-section",
        ),
        pytest.param(
            CleanupCase(
                intervention=Intervention.LATIN1,
                phase=Phase.WINDOW,
                keys=Present(("branch.other.description",)),
                intervention_keys=Present((*OWN_KEYS, "branch.other.description")),
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


MERGED = CleanupCase(command=RELEASE_COMMAND, premerge=board.MergeMethod.MERGE)
MERGED_BRANCH_KEPT = replace(
    MERGED, branch=Present("{head}"), keys=Present(OWN_KEYS), own_section=Present(True)
)
JSON_OUTPUT = (
    '{{"ok": true, "reason": "merged", "outcome": "merged #12", "issue": 72, '
    '"lane": null, "branch": "{lane}", "claim_id": "landing", "agent": "Ada", '
    '"role": "builder", "freed": [], "next": null, "parent_closable": null, '
    '"worktree": "{worktree}"}}\n'
)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(MERGED, id="clean"),
        pytest.param(
            replace(
                MERGED,
                command=(*RELEASE_COMMAND, "--json"),
                stdout=JSON_OUTPUT.replace("{worktree}", "removed"),
            ),
            id="clean-json",
        ),
        pytest.param(
            replace(
                MERGED_BRANCH_KEPT,
                intervention=Intervention.DELETE_REFUSED,
                stdout=PREFIX + "worktree: removed; branch kept -- git failure: "
                "error: branch not fully merged\n",
            ),
            id="branch-deletion-refused",
        ),
        pytest.param(
            replace(
                MERGED_BRANCH_KEPT,
                intervention=Intervention.DELETE_REFUSED,
                command=(*RELEASE_COMMAND, "--json"),
                stdout=JSON_OUTPUT.replace(
                    "{worktree}",
                    "removed; branch kept -- git failure: error: branch not fully merged",
                ),
            ),
            id="branch-deletion-refused-json",
        ),
        pytest.param(
            replace(
                MERGED_BRANCH_KEPT,
                intervention=LaunchIntervention(LaunchFailure.LAUNCH_FAILS, ("branch", "-d")),
                launches=(("branch", "-d", "{lane}"),),
                stdout=PREFIX + "worktree: removed; branch kept -- git failure: "
                "git failed to launch: permission denied\n",
            ),
            id="branch-deletion-failed-to-start",
        ),
        pytest.param(
            replace(
                MERGED_BRANCH_KEPT,
                intervention=LaunchIntervention(LaunchFailure.TIMES_OUT, ("branch", "-d")),
                launches=(("branch", "-d", "{lane}"),),
                stdout=PREFIX + "worktree: removed; branch unknown -- git branch timed out; "
                "check git branch --list {lane}\n",
            ),
            id="branch-deletion-timed-out",
        ),
    ],
)
def test_a_merged_lane_branch_goes_by_branch_delete(
    case: CleanupCase, cleanup_check: CleanupCheck
) -> None:
    """Remove a merged worktree and report the branch deletion's result.

    Spec: REL-25, REL-34, REL-35, REL-45, E-REL-08, E-REL-16, E-REL-17, E-REL-22.
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
        "forge.allowed-methods": world.landing.forge.allowed_methods,
        "initial.lane.head": real_git(world.lane, "rev-parse", "HEAD").stdout.strip(),
        "initial.own-section.keys": configuration_keys(github_clone),
    }
    expected_initial = {
        "forge.allowed-methods": frozenset({board.MergeMethod.SQUASH}),
        "initial.lane.head": head,
        "initial.own-section.keys": Present(OWN_KEYS).format(lane=lane),
    }
    assert observed_initial == expected_initial
    {
        None: no_premerge,
        board.MergeMethod.SQUASH: partial(merge_before_run, method=board.MergeMethod.SQUASH),
        board.MergeMethod.MERGE: partial(merge_before_run, method=board.MergeMethod.MERGE),
    }[case.premerge](world)
    observed_prepared = {
        "prepared.landing.merged": world.landing.forge.landings[12].merged,
        "prepared.merge.methods": tuple(call[2] for call in world.landing.forge.merge_calls),
    }
    expected_prepared = {
        "prepared.landing.merged": case.premerge is not None,
        "prepared.merge.methods": () if case.premerge is None else (case.premerge,),
    }
    assert observed_prepared == expected_prepared
    record = InterventionRecord()
    intervention = CleanupIntervention(world, monkeypatch, lane, record)
    case.intervention.install(intervention)
    capsys.readouterr()
    result = run_cli(list(case.command), capsys)
    values = {"head": head, "raced": record.raced, "lane": lane, "parent": parent}
    observed_guard = {"intervention.applications": record.applications, **record.snapshot}
    expected_guard = {
        "intervention.applications": 1,
        "intervention.phase": case.phase,
        "intervention.branch.existed-before": case.existed_before.format(**values),
        "intervention.branch.tip-after": case.intervention_tip.format(**values),
        "intervention.branch.parent-after": case.intervention_parent.format(**values),
        "intervention.config-lock.exists": case.locked,
        "intervention.configuration.keys": case.intervention_keys.format(**values),
        "intervention.latin1-description.present": case.latin1,
    }
    assert observed_guard == expected_guard
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
        "lane.branch": actual_tip,
        "configuration.keys": keys,
        "configuration.own-section.exists": {0: Present(True), 1: Absent()}.get(
            own_section.returncode, Unexpected(own_section.returncode, own_section.stderr)
        ),
        "launch.argv": record.launches,
    }
    expected = {
        "exit": case.status,
        "stdout": case.stdout.format(**values),
        "stderr": case.stderr.format(**values),
        "lane.worktree.exists": case.worktree_exists,
        "lane.branch": case.branch.format(**values),
        "configuration.keys": case.keys.format(**values),
        "configuration.own-section.exists": case.own_section,
        "launch.argv": [[argument.format(**values) for argument in call] for call in case.launches],
    }
    assert observed == expected
