"""The world and the check shared by the release cleanup test modules."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from functools import partial
from pathlib import Path
from typing import Protocol

import pytest
from cli_fixtures import (
    fail_git_launch,
    real_git,
    run_cli,
    stub_one_git_call,
)
from github_fixtures import LANDING_DEFAULT_BRANCH, FakeForge, LandedWorld, landed_world

from aco import checkout, process, workboard


@dataclass(frozen=True)
class Present:
    value: str | tuple[str, ...]

    def format(self, **values: str) -> Present:
        match self.value:
            case str(template):
                return Present(template.format(**values))
            case tuple(templates):
                return Present(tuple(template.format(**values) for template in templates))


@dataclass(frozen=True)
class Absent:
    def format(self, **values: str) -> Absent:
        return self


@dataclass(frozen=True)
class Unexpected:
    exit_status: int
    text: str


Observation = Present | Absent | Unexpected


@dataclass(frozen=True)
class JsonOutput:
    worktree_text: str

    def format(self, **values: str) -> str:
        envelope = {
            "ok": True,
            "reason": "merged",
            "outcome": "merged #12",
            "issue": 72,
            "lane": None,
            "branch": values["lane"],
            "claim_id": "landing",
            "agent": "Ada",
            "role": "builder",
            "freed": [],
            "next": None,
            "parent_closable": None,
            "worktree": self.worktree_text.format(**values),
        }
        return json.dumps(envelope) + "\n"


class InstallsIntervention(Protocol):
    def install(self, target: CleanupIntervention) -> None: ...


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
    DIRTY = auto()
    CHECKED_ELSEWHERE = auto()
    GIT_FAILURE = auto()
    FOREIGN_COMMIT_READ_FAILS = auto()
    INSIDE = auto()
    NO_WORKTREE = auto()

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
            Intervention.DIRTY: (target.before, target.dirty),
            Intervention.CHECKED_ELSEWHERE: (target.before, target.check_out_elsewhere),
            Intervention.GIT_FAILURE: (target.before, target.fail_worktree_resolution),
            Intervention.FOREIGN_COMMIT_READ_FAILS: (
                target.before,
                target.fail_commit_read_of_a_worktree_listed_first,
            ),
            Intervention.INSIDE: (target.before, target.run_from_inside),
            Intervention.NO_WORKTREE: (target.before, target.remove_lane_worktree),
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


@dataclass(frozen=True)
class SubmoduleIntervention:
    """The lane worktree's submodule populated, then `mutation` applied to it."""

    mutation: Mutation

    def install(self, target: CleanupIntervention) -> None:
        target.before(partial(target.submodule, self.mutation))


class Phase(Enum):
    BEFORE = auto()
    WINDOW = auto()
    BRANCH_EXISTS = auto()


PREFIX = "RELEASED issue #72: landing\nfreed: none\nnext: none\n"
OWN_KEYS = ("branch.{lane}.remote", "branch.{lane}.merge")
LISTING_ARGUMENTS = ("config", "--local", "--null", "--name-only", "--get-regexp", r"^branch\.")


@dataclass(frozen=True)
class CleanupCase:
    intervention: InstallsIntervention = Intervention.NONE
    command: tuple[str, ...] = ("land", "12")
    premerge: workboard.MergeMethod | None = None
    stdout: str | JsonOutput = PREFIX + "worktree: removed\n"
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
    lane_status: Present | Absent = Present("")
    landing_branch: str = LANDING_DEFAULT_BRANCH
    workplace: str = "{clone}"
    trunk_submodule: bool = False
    nested_submodule: bool = False


@dataclass
class InterventionRecord:
    launches: list[list[str]] = field(default_factory=list)
    raced: str = ""
    bystander: str = ""
    applications: int = 0
    snapshot: dict[str, object] = field(default_factory=dict)


def branch_tip(clone: Path, branch: str) -> Observation:
    result = real_git(
        clone, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False
    )
    return {0: Present(result.stdout.strip()), 1: Absent()}.get(
        result.returncode, Unexpected(result.returncode, result.stderr)
    )


def listed_keys(clone: Path, pattern: str) -> Observation:
    result = real_git(
        clone, "config", "--local", "--null", "--name-only", "--get-regexp", pattern, check=False
    )
    return {0: Present(tuple(result.stdout.rstrip("\0").split("\0"))), 1: Absent()}.get(
        result.returncode, Unexpected(result.returncode, result.stderr)
    )


def configuration_keys(clone: Path) -> Observation:
    return listed_keys(clone, r"^branch\.")


def own_section_keys(clone: Path, lane: str) -> Observation:
    return listed_keys(clone, rf"^branch\.{lane}\.[^.]+$")


def lane_status(lane: Path) -> Observation:
    if not lane.exists():
        return Absent()
    return Present(real_git(lane, "status", "--porcelain").stdout)


SUBMODULE = "sub"
NESTED_SUBMODULE = "inner"
SUBMODULE_UPSTREAM = "submodule-upstream"
ALLOW_FILE_TRANSPORT = ("-c", "protocol.file.allow=always")


@dataclass(frozen=True)
class SubmoduleSite:
    """The lane's populated submodule: its repository under the lane's own git directory, its
    working directory and the repository it was cloned from."""

    lane: Path
    store: Path
    working_directory: Path
    upstream: Path

    def git(self, *arguments: str) -> str:
        return real_git(self.working_directory, *arguments).stdout.strip()

    def unique_commit(self) -> str:
        """A commit on top of the submodule's `HEAD` that no ref names yet."""
        return self.git("commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "only here")


Mutation = Callable[[SubmoduleSite], None]


def one_commit_repository(path: Path) -> Path:
    """A repository on `main` at `path` holding one commit, which submodule clones start from."""
    path.mkdir()
    real_git(path, "init", "-q", "-b", "main")
    (path / "submodule.txt").write_text("submodule\n")
    real_git(path, "add", "submodule.txt")
    real_git(path, "commit", "-q", "-m", "submodule")
    return path


def add_trunk_submodule(clone: Path, *, nested: bool) -> None:
    """Trunk gains the gitlink `SUBMODULE` on a one-commit repository beside the clone, so every
    lane branch cut from it holds it unpopulated; with `nested`, that repository holds the gitlink
    `NESTED_SUBMODULE` itself."""
    upstream = one_commit_repository(clone.parent / SUBMODULE_UPSTREAM)
    if nested:
        inner = one_commit_repository(clone.parent / f"{SUBMODULE_UPSTREAM}-{NESTED_SUBMODULE}")
        real_git(
            upstream, *ALLOW_FILE_TRANSPORT, "submodule", "add", "-q", str(inner), NESTED_SUBMODULE
        )
        real_git(upstream, "commit", "-q", "-m", "add a nested submodule")
    real_git(clone, *ALLOW_FILE_TRANSPORT, "submodule", "add", "-q", str(upstream), SUBMODULE)
    real_git(clone, "commit", "-q", "-m", "add a submodule")
    real_git(clone, "push", "-q", "origin", "main")


def lane_submodule_store(lane: Path) -> Path:
    git_directory = real_git(lane, "rev-parse", "--absolute-git-dir").stdout.strip()
    return Path(git_directory) / "modules" / SUBMODULE


def populate_submodule(lane: Path) -> SubmoduleSite:
    real_git(lane, *ALLOW_FILE_TRANSPORT, "submodule", "update", "-q", "--init", "--recursive")
    return SubmoduleSite(
        lane=lane,
        store=lane_submodule_store(lane),
        working_directory=lane / SUBMODULE,
        upstream=lane.parent / SUBMODULE_UPSTREAM,
    )


def leave_populated(site: SubmoduleSite) -> None:
    """Populating the submodule is the whole arrangement."""


def deinitialise(site: SubmoduleSite) -> None:
    real_git(site.lane, "submodule", "deinit", "-q", "-f", SUBMODULE)


def clone_nested_store(site: SubmoduleSite) -> None:
    real_git(site.lane, "clone", "-q", str(site.upstream), str(site.store / "modules" / "inner"))


def hold_ref(name: str) -> Mutation:
    """A commit on the ref `name` that no remote-tracking ref reaches."""

    def update(site: SubmoduleSite) -> None:
        site.git("update-ref", name, site.unique_commit())

    return update


def hold_annotated_tag(site: SubmoduleSite) -> None:
    site.git("tag", "-a", "-m", "only here", "annotated", site.unique_commit())


def hold_note(site: SubmoduleSite) -> None:
    site.git("notes", "add", "-m", "only here", "HEAD")


def hold_stash_entry(site: SubmoduleSite) -> None:
    (site.working_directory / "submodule.txt").write_text("changed\n")
    site.git("stash", "push", "-q")


def hold_detached_commit_then_deinitialise(site: SubmoduleSite) -> None:
    site.git("checkout", "-q", "--detach", site.unique_commit())
    deinitialise(site)


def add_linked_worktree(site: SubmoduleSite) -> None:
    site.git("worktree", "add", "-q", "--detach", str(site.lane.parent / "submodule-worktree"))


def drop_remote_tracking_refs(site: SubmoduleSite) -> None:
    site.git("remote", "remove", "origin")


MISSING_OBJECT = "1" * 40


def hold_unreadable_ref(site: SubmoduleSite) -> None:
    (site.store / "refs" / "heads" / "ghost").write_text(MISSING_OBJECT + "\n")


def lock_the_lane(site: SubmoduleSite) -> None:
    real_git(site.lane, "worktree", "lock", "--reason", "in use", str(site.lane))


def dirty_the_submodule_despite(
    *configuration: str, in_lane: bool = True, nested: bool = False
) -> Mutation:
    """An untracked file in the submodule (or the one nested in it), with the `git config`
    arguments `configuration` set to hide it from `git status`: in the lane, or with `in_lane`
    false in the submodule's own repository."""

    def dirty(site: SubmoduleSite) -> None:
        directory = site.working_directory / NESTED_SUBMODULE if nested else site.working_directory
        (directory / "scratch.txt").write_text("uncommitted\n")
        if in_lane:
            real_git(site.lane, "config", *configuration)
        else:
            site.git("config", *configuration)

    return dirty


def hide_untracked_files(site: SubmoduleSite) -> None:
    (site.lane / "scratch.txt").write_text("uncommitted\n")
    real_git(site.lane, "config", "status.showUntrackedFiles", "no")


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
            "intervention.lane.status": lane_status(self.world.lane),
            "intervention.landing.branch": real_git(
                self.clone, "branch", "--show-current"
            ).stdout.strip(),
            "intervention.workplace": (
                str(Path.cwd()),
                checkout.git_output(["rev-parse", "--show-toplevel"]),
            ),
        }

    def before(self, action: Callable[[], None]) -> None:
        self.apply(action, Phase.BEFORE)

    def window(self, action: Callable[[], None]) -> None:
        remove = checkout.remove_linked_worktree

        def interfere_then_remove(
            path: Path, *, branch: str, landed_head: str | None = None, force: bool = False
        ) -> checkout.WorktreeCleanupOutcome:
            self.apply(action, Phase.WINDOW)
            return remove(path, branch=branch, landed_head=landed_head, force=force)

        self.monkeypatch.setattr(checkout, "remove_linked_worktree", interfere_then_remove)

    def recreation(self, action: Callable[[], None]) -> None:
        exists = checkout.branch_exists

        def recreate_then_observe(branch: str) -> bool:
            self.apply(action, Phase.BRANCH_EXISTS)
            return exists(branch)

        self.monkeypatch.setattr(checkout, "branch_exists", recreate_then_observe)

    def nothing(self) -> None:
        pass

    def submodule(self, mutation: Mutation) -> None:
        mutation(populate_submodule(self.world.lane))

    def commit(self) -> None:
        real_git(self.world.lane, "commit", "-q", "--allow-empty", "-m", "after the pinned head")
        self.record.raced = real_git(self.world.lane, "rev-parse", "HEAD").stdout.strip()

    def dirty(self) -> None:
        (self.world.lane / "scratch.txt").write_text("uncommitted\n")

    def check_out_elsewhere(self) -> None:
        real_git(self.clone, "worktree", "remove", str(self.world.lane))
        real_git(self.clone, "checkout", "-q", self.branch)
        bystander = self.clone.parent / "bystander"
        real_git(
            self.clone, "worktree", "add", "-q", str(bystander), "-b", "codex/issue-1-bystander"
        )
        self.monkeypatch.chdir(bystander)
        self.record.bystander = str(bystander)

    def run_from_inside(self) -> None:
        self.monkeypatch.chdir(self.world.lane)

    def remove_lane_worktree(self) -> None:
        real_git(self.clone, "worktree", "remove", str(self.world.lane))

    def fail_worktree_resolution(self) -> None:
        stub_one_git_call(
            self.monkeypatch,
            [
                "rev-parse",
                "--path-format=absolute",
                "--show-toplevel",
                "--git-dir",
                "--git-common-dir",
            ],
            exit_status=128,
            stderr="fatal: cannot change to 'gone': No such file or directory",
        )

    def fail_commit_read_of_a_worktree_listed_first(self) -> None:
        """A candidate on another branch that git lists before the lane's
        own worktree, whose commit read exits 128: cleanup must keep the
        lane rather than read the failure as that candidate having none."""
        foreign = self.clone.parent / "aaa-foreign"
        real_git(self.clone, "worktree", "add", "-q", str(foreign), "-b", "codex/issue-1-foreign")
        stub_one_git_call(
            self.monkeypatch,
            ["rev-parse", "--verify", "--quiet", "HEAD"],
            exit_status=128,
            stderr="fatal: broken",
            directory=foreign,
        )

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
    client.allowed_methods = frozenset({workboard.MergeMethod.SQUASH})


def merge_before_run(world: LandedWorld, *, method: workboard.MergeMethod) -> None:
    world.landing.forge.merge_landing(
        12,
        head_sha=world.landing.head,
        method=method,
        title="feat: land the lane (#12)",
        body="Work-Item: #72",
    )


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


MERGED = CleanupCase(command=RELEASE_COMMAND, premerge=workboard.MergeMethod.MERGE)
MERGED_BRANCH_KEPT = replace(
    MERGED, branch=Present("{head}"), keys=Present(OWN_KEYS), own_section=Present(OWN_KEYS)
)


def rendered(identifier: str, worktree_text: str, case: CleanupCase) -> tuple[object, ...]:
    return (
        pytest.param(replace(case, stdout=PREFIX + f"worktree: {worktree_text}\n"), id=identifier),
        pytest.param(
            replace(case, command=(*case.command, "--json"), stdout=JsonOutput(worktree_text)),
            id=f"{identifier}-json",
        ),
    )


def assert_initial_state(world: LandedWorld, github_clone: Path, lane: str) -> None:
    head = world.landing.head
    observed = {
        "forge.allowed-methods": world.landing.forge.allowed_methods,
        "initial.lane.head": real_git(world.lane, "rev-parse", "HEAD").stdout.strip(),
        "initial.own-section.keys": configuration_keys(github_clone),
    }
    expected = {
        "forge.allowed-methods": frozenset({workboard.MergeMethod.SQUASH}),
        "initial.lane.head": head,
        "initial.own-section.keys": Present(OWN_KEYS).format(lane=lane),
    }
    assert observed == expected


def assert_prepared_state(world: LandedWorld, case: CleanupCase) -> None:
    observed = {
        "prepared.landing.merged": world.landing.forge.landings[12].merged,
        "prepared.merge.methods": tuple(call[2] for call in world.landing.forge.merge_calls),
    }
    expected = {
        "prepared.landing.merged": case.premerge is not None,
        "prepared.merge.methods": () if case.premerge is None else (case.premerge,),
    }
    assert observed == expected


def assert_intervention(
    case: CleanupCase, record: InterventionRecord, values: dict[str, str]
) -> None:
    observed = {"intervention.applications": record.applications, **record.snapshot}
    expected = {
        "intervention.applications": 1,
        "intervention.phase": case.phase,
        "intervention.branch.existed-before": case.existed_before.format(**values),
        "intervention.branch.tip-after": case.intervention_tip.format(**values),
        "intervention.branch.parent-after": case.intervention_parent.format(**values),
        "intervention.config-lock.exists": case.locked,
        "intervention.configuration.keys": case.intervention_keys.format(**values),
        "intervention.latin1-description.present": case.latin1,
        "intervention.lane.status": case.lane_status,
        "intervention.landing.branch": case.landing_branch.format(**values),
        "intervention.workplace": (case.workplace.format(**values),) * 2,
    }
    assert observed == expected


def verify_cleanup(
    case: CleanupCase,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if case.trunk_submodule:
        add_trunk_submodule(github_clone, nested=case.nested_submodule)
    world = landed_world(github_clone, bare_remote, monkeypatch, extra_arrange=allow_squash)
    head = world.landing.head
    lane = "codex/issue-72-claims"
    parent = real_git(github_clone, "rev-parse", f"{head}^").stdout.strip()
    assert_initial_state(world, github_clone, lane)
    if case.premerge is not None:
        merge_before_run(world, method=case.premerge)
    assert_prepared_state(world, case)
    store = lane_submodule_store(world.lane)
    record = InterventionRecord()
    case.intervention.install(CleanupIntervention(world, monkeypatch, lane, record))
    capsys.readouterr()
    arguments = [*case.command, "--head", head] if case.command[0] == "land" else list(case.command)
    result = run_cli(arguments, capsys)
    merged_line = f"merged: {world.landing.forge.landings[12].merge_commit}\n"
    values = {
        "head": head,
        "raced": record.raced,
        "lane": lane,
        "parent": parent,
        "clone": str(github_clone),
        "bystander": record.bystander,
        "worktree": str(world.lane),
        "store": str(store),
    }
    assert_intervention(case, record, values)
    observed = {
        "exit": result.status,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "lane.worktree.exists": world.lane.exists(),
        "lane.branch": branch_tip(github_clone, lane),
        "configuration.keys": configuration_keys(github_clone),
        "configuration.own-section.keys": own_section_keys(github_clone, lane),
        "launch.argv": record.launches,
    }
    expected = {
        "exit": case.status,
        "stdout": case.stdout.format(**values) + (merged_line if case.command[0] == "land" else ""),
        "stderr": case.stderr.format(**values),
        "lane.worktree.exists": case.worktree_exists,
        "lane.branch": case.branch.format(**values),
        "configuration.keys": case.keys.format(**values),
        "configuration.own-section.keys": case.own_section.format(**values),
        "launch.argv": [[argument.format(**values) for argument in call] for call in case.launches],
    }
    assert observed == expected
