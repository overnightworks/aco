"""`aco adopt` through the real CLI (`specs/adopt.spec.md`): its refusals, the build, the
claim, the body write and the holder's rerun."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from cli_fixtures import (
    ADOPTED_BRANCH,
    ADOPTED_PULL_REQUEST,
    CliRun,
    count_context_reads,
    dependabot_pull_request,
    fresh_observation,
    pull_request_listing,
    push_repository_trunk,
    real_git,
    redirect_toplevel,
    run_cli,
    run_context_over,
    track_board_config,
    worktrees_and_branches,
)
from github_fixtures import FakeForge, serve_forge
from store_fixtures import (
    RaceOnceTransport,
    claim_intent,
    fail_every_state_ref_push,
    state_ref_tip,
)

from agent_coordination import checkout, cmd_claim, forge, github, protocol, store
from agent_coordination.github import GitHubForge

DEPENDENCY_PATHS_CONFIG = 'dependency_paths = ["uv.lock", "pyproject.toml"]\n'
ADOPTED_BODY = "Bump x\n\nNo-Item: deps"


def _publish_branch_tip(clone: Path, message: str) -> str:
    """A fresh commit on top of `clone`'s `HEAD`, forced onto the remote as the
    pull request's head branch; no local branch or ref moves."""
    tree = real_git(clone, "rev-parse", "HEAD^{tree}").stdout.strip()
    tip = real_git(clone, "commit-tree", tree, "-p", "HEAD", "-m", message).stdout.strip()
    real_git(clone, "push", "-q", "--force", "origin", f"{tip}:refs/heads/{ADOPTED_BRANCH}")
    return tip


@dataclass(frozen=True)
class Effects:
    """Everything a refusal before the build must leave exactly as it found it."""

    state_ref_tip: str | None
    worktrees_and_branches: tuple[str, str]
    pull_request_directory_exists: bool
    written_bodies: dict[int, str]


@dataclass
class AdoptionWorld:
    """Pull request #45 of a GitHub-form repository whose head branch sits on
    the bare remote, and the fake forge that serves it."""

    clone: Path
    remote: Path
    forge: FakeForge
    head: str

    @property
    def pull_request_directory(self) -> Path:
        return self.clone.parent / f"{self.clone.name}-worktrees" / f"pr-{ADOPTED_PULL_REQUEST}"

    def serve(self, edit: Callable[[forge.Landing], forge.Landing]) -> None:
        self.forge.landings[ADOPTED_PULL_REQUEST] = edit(self.forge.landings[ADOPTED_PULL_REQUEST])

    def list_files(self, *paths: str) -> None:
        self.forge.changes_by_number[ADOPTED_PULL_REQUEST] = pull_request_listing(
            self.head, *(forge.ChangedFile(path, None) for path in paths)
        )

    def effects(self) -> Effects:
        return Effects(
            state_ref_tip(self.remote),
            worktrees_and_branches(self.clone),
            os.path.lexists(self.pull_request_directory),
            dict(self.forge.item_bodies),
        )


@pytest.fixture
def world(
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> AdoptionWorld:
    """Bootstrapped state, a tracked dependency configuration, and open pull
    request #45 changing `uv.lock` and `pyproject.toml` from `dependabot/uv/x`."""
    track_board_config(github_clone, DEPENDENCY_PATHS_CONFIG)
    push_repository_trunk(github_clone, "origin")
    run_cli(["bootstrap"], capsys).expect_success()
    head = _publish_branch_tip(github_clone, "bump x")
    served = serve_forge(
        monkeypatch,
        FakeForge(
            landings={ADOPTED_PULL_REQUEST: dependabot_pull_request(head)},
            changes_by_number={
                ADOPTED_PULL_REQUEST: pull_request_listing(
                    head,
                    forge.ChangedFile("uv.lock", None),
                    forge.ChangedFile("pyproject.toml", None),
                )
            },
        ),
    )
    return AdoptionWorld(github_clone, bare_remote, served, head)


def adopt(capsys: pytest.CaptureFixture[str], *arguments: str, kind: str = "deps") -> CliRun:
    return run_cli(["adopt", str(ADOPTED_PULL_REQUEST), "--no-item", kind, *arguments], capsys)


def _fail_on_claim_state_read(monkeypatch: pytest.MonkeyPatch) -> None:
    def fetch_state(**_where: object) -> protocol.ClaimState:
        pytest.fail("adopt read claim state before judging the pull request")

    monkeypatch.setattr(store, "fetch_state", fetch_state)


@pytest.mark.parametrize(
    ("arrange", "refusal", "reads_the_forge"),
    [
        pytest.param(
            lambda world: track_board_config(world.clone, 'storage = "state-ref"\n'),
            "aco adopt is a github command; storage = state-ref has no pull requests to adopt",
            False,
            id="cell-1-state-ref",
        ),
        pytest.param(
            lambda world: (
                world.serve(lambda landing: replace(landing, merged=True, merge_commit=world.head)),
                world.forge.closed_issues.add(ADOPTED_PULL_REQUEST),
            ),
            f"pull request #{ADOPTED_PULL_REQUEST} is not open; it cannot be adopted",
            True,
            id="cell-5-merged",
        ),
    ],
)
def test_adopt_judges_the_pull_request_before_it_reads_any_claim_state(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    arrange: Callable[[AdoptionWorld], object],
    refusal: str,
    reads_the_forge: bool,
) -> None:
    """Spec: ADOPT-01, ADOPT-02 -- the refusals before the claim read touch no claim state."""
    arrange(world)
    _fail_on_claim_state_read(monkeypatch)
    before = world.effects()

    result = adopt(capsys)

    assert (result.status, result.stdout, result.stderr) == (2, "", f"ERROR: {refusal}\n")
    assert (world.forge.requests > 0) is reads_the_forge
    assert world.effects() == before


@pytest.mark.parametrize(
    ("arguments", "usage_error"),
    [
        pytest.param(
            ["45", "--no-item", "chore"],
            "aco adopt: error: argument --no-item: invalid choice: 'chore' (choose from",
            id="cell-2-unknown-kind",
        ),
        pytest.param(
            ["45"],
            "aco adopt: error: the following arguments are required: --no-item",
            id="cell-3-no-kind",
        ),
        pytest.param(
            ["45", "46", "--no-item", "deps"],
            "aco: error: unrecognized arguments: 46",
            id="cell-4-two-pull-requests",
        ),
        pytest.param(
            ["0", "--no-item", "deps"],
            "aco adopt: error: argument pull_request: 0 is not a positive number",
            id="cell-19-zero",
        ),
        pytest.param(
            ["-1", "--no-item", "deps"],
            "aco adopt: error: argument pull_request: -1 is not a positive number",
            id="cell-20-negative",
        ),
        pytest.param(
            ["abc", "--no-item", "deps"],
            "aco adopt: error: argument pull_request: invalid int value: 'abc'",
            id="cell-26-text",
        ),
    ],
)
def test_adopt_refuses_a_malformed_command_line_at_the_parser(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    usage_error: str,
) -> None:
    """Spec: ADOPT-08 -- argparse's usage block and sentence, no forge read."""
    result = run_cli(["adopt", *arguments], capsys)

    assert (result.status, result.stdout) == (2, "")
    assert result.stderr.startswith("usage: aco ")
    assert result.stderr.splitlines()[-1].startswith(usage_error)
    assert world.forge.requests == 0


def _claim_the_branch_as(
    agent: str,
    identity: protocol.ClaimIdentity | None = None,
    claim_id: str = "a1",
    *,
    role: str = "builder",
    branch: str = ADOPTED_BRANCH,
    scope: tuple[str, ...] = ("uv.lock",),
) -> Callable[[AdoptionWorld], None]:
    claimed_identity = protocol.LaneIdentity() if identity is None else identity

    def claim(world: AdoptionWorld) -> None:
        store.commit_transition(
            observed=fresh_observation(world.clone, world.remote),
            subject=store.transition_subject("claim", claimed_identity, branch),
            intent=claim_intent(
                identity=claimed_identity,
                agent=agent,
                role=role,
                branch=branch,
                base=protocol.ObjectId(world.head),
                scope=scope,
                claim_id=claim_id,
                operation_id=f"op-{claim_id}",
            ),
        )

    return claim


def _occupy_the_pull_request_path_with_a_dangling_symlink(world: AdoptionWorld) -> None:
    world.pull_request_directory.parent.mkdir(parents=True)
    world.pull_request_directory.symlink_to(world.clone.parent / "nowhere")


def _list_files_named(count: int) -> Callable[[AdoptionWorld], None]:
    return lambda world: world.list_files(*(f"file-{number:03}.txt" for number in range(count)))


@pytest.mark.parametrize(
    ("arrange", "kind", "refusal"),
    [
        pytest.param(
            lambda world: world.serve(lambda landing: replace(landing, body="Work-Item: #5")),
            "deps",
            f"pull request #{ADOPTED_PULL_REQUEST} already carries Work-Item: #5; "
            "adopt never changes a classification line",
            id="cell-6-classification-line",
        ),
        pytest.param(
            lambda world: world.serve(lambda landing: replace(landing, body=ADOPTED_BODY)),
            "deps",
            f"pull request #{ADOPTED_PULL_REQUEST} already carries No-Item: deps; "
            "adopt never changes a classification line",
            id="cell-6-own-line-without-a-claim",
        ),
        pytest.param(
            lambda world: world.list_files("uv.lock", "pyproject.toml", "src/x.py"),
            "deps",
            f"pull request #{ADOPTED_PULL_REQUEST} changes src/x.py, "
            "which dependency_paths in .aco/board.toml does not name",
            id="cell-7-path-outside-the-dependency-paths",
        ),
        pytest.param(
            _claim_the_branch_as("Bob"),
            "deps",
            f"lane '{ADOPTED_BRANCH}' is claimed by Bob (builder) "
            f"on lane '{ADOPTED_BRANCH}' branch {ADOPTED_BRANCH}",
            id="cell-8-claimed-by-bob",
        ),
        pytest.param(
            _claim_the_branch_as("Ada", role="reviewer"),
            "deps",
            f"lane '{ADOPTED_BRANCH}' is claimed by Ada (reviewer) "
            f"on lane '{ADOPTED_BRANCH}' branch {ADOPTED_BRANCH}",
            id="cell-9-the-same-agents-claim-under-another-role",
        ),
        pytest.param(
            _claim_the_branch_as("Bob\u202e"),
            "deps",
            f"lane '{ADOPTED_BRANCH}' is claimed by Bob\\u202e (builder) "
            f"on lane '{ADOPTED_BRANCH}' branch {ADOPTED_BRANCH}",
            id="cell-21-holder-name-with-a-display-control",
        ),
        pytest.param(
            lambda world: world.pull_request_directory.mkdir(parents=True),
            "deps",
            "{pull_request_directory} already exists; remove it, "
            f"then adopt pull request #{ADOPTED_PULL_REQUEST} again",
            id="cell-10-directory-in-the-way",
        ),
        pytest.param(
            _occupy_the_pull_request_path_with_a_dangling_symlink,
            "deps",
            "{pull_request_directory} already exists; remove it, "
            f"then adopt pull request #{ADOPTED_PULL_REQUEST} again",
            id="cell-22-dangling-symlink-in-the-way",
        ),
        pytest.param(
            lambda world: real_git(world.clone, "branch", ADOPTED_BRANCH),
            "deps",
            f"branch '{ADOPTED_BRANCH}' already exists here; remove it, "
            f"then adopt pull request #{ADOPTED_PULL_REQUEST} again",
            id="cell-11-local-branch",
        ),
        pytest.param(
            lambda world: world.serve(lambda landing: replace(landing, source_branch="bad..name")),
            "deps",
            f"pull request #{ADOPTED_PULL_REQUEST} head branch 'bad..name' is no safe branch name",
            id="cell-12-unsafe-branch-name",
        ),
        pytest.param(
            lambda world: _publish_branch_tip(world.clone, "moved"),
            "deps",
            f"pull request #{ADOPTED_PULL_REQUEST} moved while adopt read it; run adopt again",
            id="cell-13-tip-moved",
        ),
        pytest.param(
            lambda world: real_git(world.clone, "push", "-q", "origin", f":{ADOPTED_BRANCH}"),
            "deps",
            f"pull request #{ADOPTED_PULL_REQUEST} moved while adopt read it; run adopt again",
            id="cell-23-head-branch-gone-from-the-remote",
        ),
        pytest.param(
            _list_files_named(4),
            "fix",
            "scope is wide: 4 paths exceeds three; pass --whole REASON",
            id="cell-14-wide-scope",
        ),
        pytest.param(
            _list_files_named(257),
            "fix",
            "claim marker scope exceeds 256 entries",
            id="cell-16-scope-cap",
        ),
    ],
)
def test_adopt_refuses_before_it_builds_anything(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[[AdoptionWorld], object],
    kind: str,
    refusal: str,
) -> None:
    """Spec: ADOPT-05, ADOPT-06, ADOPT-07, ADOPT-09, ADOPT-10, ADOPT-13, ADOPT-14, ADOPT-17,
    ADOPT-32 -- each refusal names its cause and leaves the repository, the state ref and the
    body as found."""
    arrange(world)
    before = world.effects()

    result = adopt(capsys, kind=kind)

    sentence = refusal.format(pull_request_directory=world.pull_request_directory)
    assert (result.status, result.stdout, result.stderr) == (2, "", f"ERROR: {sentence}\n")
    assert world.effects() == before


def _refuse_any_fetch(world: AdoptionWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    """The head branch has already moved; adopt must not fetch it."""
    _publish_branch_tip(world.clone, "moved")

    def refuse_fetch(remote: str, branches: tuple[str, ...], *, directory: Path) -> None:
        raise AssertionError("adopt fetched a head branch that had moved")

    monkeypatch.setattr(checkout, "fetch_remote_branches", refuse_fetch)


def _move_the_branch_during_the_fetch(
    world: AdoptionWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The head branch moves after adopt compared its tip, as the fetch starts."""
    fetch = checkout.fetch_remote_branches

    def fetch_after_the_branch_moves(
        remote: str, branches: tuple[str, ...], *, directory: Path
    ) -> None:
        _publish_branch_tip(world.clone, "moved")
        fetch(remote, branches, directory=directory)

    monkeypatch.setattr(checkout, "fetch_remote_branches", fetch_after_the_branch_moves)


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(_refuse_any_fetch, id="moved-before-the-fetch"),
        pytest.param(_move_the_branch_during_the_fetch, id="moved-during-the-fetch"),
    ],
)
def test_adopt_refuses_a_head_branch_that_moved_around_its_fetch(
    world: AdoptionWorld,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[[AdoptionWorld, pytest.MonkeyPatch], None],
) -> None:
    """Spec: ADOPT-10 -- a head branch already moved is refused from the remote's tip
    without a fetch, and one that moves during the fetch is refused from the fetched tip."""
    arrange(world, monkeypatch)

    result = adopt(capsys, kind="deps")

    assert result.stderr == (
        f"ERROR: pull request #{ADOPTED_PULL_REQUEST} moved while adopt read it; run adopt again\n"
    )


def test_adopt_refuses_in_a_linked_worktree_whose_git_directory_names_no_checkout(
    world: AdoptionWorld,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: ADOPT-15 -- START-24's sentence, with `adopt` named."""
    kept_elsewhere = tmp_path / "kept-elsewhere"
    real_git(
        tmp_path,
        "init",
        "-q",
        "-b",
        "main",
        f"--separate-git-dir={tmp_path / 'store'}",
        str(kept_elsewhere),
    )
    real_git(kept_elsewhere, "commit", "-q", "--allow-empty", "-m", "initial")
    lane = tmp_path / "lane"
    real_git(kept_elsewhere, "worktree", "add", "-q", str(lane), "-b", "lane")
    monkeypatch.chdir(lane)
    redirect_toplevel(monkeypatch, lane)

    result = adopt(capsys)

    assert (result.status, result.stdout) == (2, "")
    assert re.fullmatch(
        r"ERROR: main checkout unknown: git directory .* names no checkout; "
        r"run adopt from the main checkout\n",
        result.stderr,
    )
    assert world.forge.requests == 0


LONG_NAME = "a-very-long-file-name-" + "x" * 80


@pytest.mark.parametrize(
    ("arrange", "refusal_start"),
    [
        pytest.param(
            lambda world: world.serve(
                lambda landing: replace(landing, body=f"No-Item: {'x' * 400}")
            ),
            f"ERROR: pull request #{ADOPTED_PULL_REQUEST} already carries ",
            id="cell-24-overlong-classification-line",
        ),
        pytest.param(
            lambda world: world.list_files(*(f"src/{index}/{LONG_NAME}.py" for index in range(3))),
            f"ERROR: pull request #{ADOPTED_PULL_REQUEST} changes src/0/",
            id="cell-25-three-overlong-file-names",
        ),
    ],
)
def test_adopt_cuts_an_overlong_refusal_to_one_line_of_200_characters(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[[AdoptionWorld], object],
    refusal_start: str,
) -> None:
    """Spec: ADOPT-19 -- the whole stderr is the refusal line, cut with an ellipsis."""
    arrange(world)

    result = adopt(capsys)

    assert (result.status, result.stdout) == (2, "")
    assert result.stderr.startswith(refusal_start)
    assert result.stderr.endswith("…\n")
    assert len(result.stderr) == 201


def _list_four_files(world: AdoptionWorld) -> None:
    """Four paths pass the listing's checks and are refused only at the claim
    check, after both fetches (cell 14)."""
    _list_files_named(4)(world)


BRANCHES_TO_A_MIRROR = "+refs/heads/*:refs/heads/mirror/*"
EVERYTHING_TO_ITSELF = "+refs/*:refs/*"
STATE_REF_TO_A_LOCAL_BRANCH = f"+{store.STATE_REF}:refs/heads/mirror/state"
ADOPTED_OUTCOME = (
    lambda _world: None,
    "deps",
    0,
    ("refs/heads", "refs/tags"),
    {f"refs/heads/{ADOPTED_BRANCH}"},
)
REFUSED_AFTER_BOTH_FETCHES = (
    _list_four_files,
    "fix",
    2,
    ("refs/heads", "refs/tags", store.STATE_REF),
    set(),
)


@pytest.mark.parametrize(
    ("configured_refspec", "arrange", "kind", "status", "watched_refs", "new_local_refs"),
    [
        # The claim write's own fetch honours a state-ref mapping onto a local
        # branch even for an adoption; that residual is #47's (store push).
        pytest.param(BRANCHES_TO_A_MIRROR, *ADOPTED_OUTCOME, id="adopted-branches-to-a-mirror"),
        pytest.param(EVERYTHING_TO_ITSELF, *ADOPTED_OUTCOME, id="adopted-everything-to-itself"),
        pytest.param(
            BRANCHES_TO_A_MIRROR, *REFUSED_AFTER_BOTH_FETCHES, id="refused-branches-to-a-mirror"
        ),
        pytest.param(
            EVERYTHING_TO_ITSELF, *REFUSED_AFTER_BOTH_FETCHES, id="refused-everything-to-itself"
        ),
        pytest.param(
            STATE_REF_TO_A_LOCAL_BRANCH,
            *REFUSED_AFTER_BOTH_FETCHES,
            id="refused-the-state-ref-to-a-local-branch",
        ),
    ],
)
def test_adopt_fetches_no_branch_into_a_local_ref_even_when_a_fetch_refspec_asks_to(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    configured_refspec: str,
    arrange: Callable[[AdoptionWorld], None],
    kind: str,
    status: int,
    watched_refs: tuple[str, ...],
    new_local_refs: set[str],
) -> None:
    """Spec: ADOPT-20, Never -- a configured fetch mapping stays unused: an adoption
    adds the adopted branch as its one local ref, and a refusal after both fetches
    leaves local branches, tags and the state ref as they were."""
    real_git(world.clone, "config", "--add", "remote.origin.fetch", configured_refspec)
    arrange(world)
    refs_before = set(real_git(world.clone, "for-each-ref", *watched_refs).stdout.splitlines())

    result = adopt(capsys, kind=kind)

    assert result.status == status, result.stderr
    refs_after = set(real_git(world.clone, "for-each-ref", *watched_refs).stdout.splitlines())
    assert {line.split()[-1] for line in refs_after ^ refs_before} == new_local_refs


def test_adopt_refuses_as_moved_when_the_remote_deletes_the_head_branch_during_the_fetch(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec: ADOPT-10 -- a branch that vanishes between the remote's answer and the fetch
    is the same refusal, not git's own error."""
    fetch_remote_branches = checkout.fetch_remote_branches

    def fetch_after_the_branch_vanishes(
        remote: str, branches: tuple[str, ...], *, directory: Path
    ) -> None:
        real_git(world.clone, "push", "-q", "origin", f":{ADOPTED_BRANCH}")
        fetch_remote_branches(remote, branches, directory=directory)

    monkeypatch.setattr(checkout, "fetch_remote_branches", fetch_after_the_branch_vanishes)
    before = world.effects()

    result = adopt(capsys)

    sentence = f"pull request #{ADOPTED_PULL_REQUEST} moved while adopt read it; run adopt again"
    assert (result.status, result.stdout, result.stderr) == (2, "", f"ERROR: {sentence}\n")
    assert world.effects() == before


def test_adopt_passes_git_fetch_error_through_while_the_head_branch_remains(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec: ADOPT-10 -- a failed fetch of a branch the remote still has is git's own error."""
    sentence = "the remote hung up unexpectedly"

    def fail_the_fetch(remote: str, branches: tuple[str, ...], *, directory: Path) -> None:
        raise protocol.ClaimError(sentence)

    monkeypatch.setattr(checkout, "fetch_remote_branches", fail_the_fetch)
    before = world.effects()

    result = adopt(capsys)

    assert (result.status, result.stdout, result.stderr) == (2, "", f"ERROR: {sentence}\n")
    assert world.effects() == before


def test_a_fetch_of_a_branch_the_remote_lacks_fails_loud(world: AdoptionWorld) -> None:
    """Spec: ADOPT-10 -- `adopt` asks the remote first; the fetch itself never passes silently."""
    with pytest.raises(protocol.ClaimError, match="no-such-branch"):
        checkout.fetch_remote_branches("origin", ("no-such-branch",), directory=world.clone)


def test_adopt_judges_the_main_checkouts_pin_when_a_linked_worktree_pins_state_ref(
    world: AdoptionWorld,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: ADOPT-15, Never -- a linked worktree's own `.aco/board.toml` is never read."""
    lane = tmp_path / "linked-lane"
    real_git(world.clone, "worktree", "add", "-q", str(lane), "-b", "linked-lane")
    (lane / ".aco" / "board.toml").write_text('storage = "state-ref"\n')
    monkeypatch.chdir(lane)
    redirect_toplevel(monkeypatch, lane)

    result = adopt(capsys)

    assert (result.status, result.stderr) == (0, "")
    assert world.forge.body_writes == [(ADOPTED_PULL_REQUEST, ADOPTED_BODY)]


def test_adopt_and_its_dry_run_claim_name_the_same_holder_of_a_twice_held_branch(
    world: AdoptionWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ADOPT-06, CLAIM-71 -- an issue claim and a lane claim hold the branch; the
    refusal and the claim check both name the lane holder."""
    _claim_the_branch_as("Bob", protocol.IssueIdentity(42), "b1")(world)
    _claim_the_branch_as("Carol", claim_id="c1")(world)
    arguments = cmd_claim.ClaimArguments(
        agent="Ada", base=world.head, branch=ADOPTED_BRANCH, scope=["uv.lock"]
    )
    request = cmd_claim.claim_request(arguments, adopted=True)
    context = run_context_over(world.forge)

    with pytest.raises(protocol.ClaimConflictError) as refused:
        cmd_claim.checked_claim(request, context, revision=world.head)
    result = adopt(capsys, kind="deps")

    holder = f"claimed by Carol (builder) on lane '{ADOPTED_BRANCH}' branch {ADOPTED_BRANCH}"
    assert str(refused.value).endswith(holder)
    assert result.stderr.endswith(f"{holder}\n")


def test_adopts_dry_run_claim_refuses_a_branch_another_claim_holds(world: AdoptionWorld) -> None:
    """Spec: CLAIM-71 -- the claim `adopt` would make, checked as `cmd_adopt` checks it,
    refuses with CLAIM-11's sentence and writes nothing."""
    store.commit_transition(
        observed=fresh_observation(world.clone, world.remote),
        subject=store.transition_subject("claim", protocol.IssueIdentity(42), ADOPTED_BRANCH),
        intent=claim_intent(
            identity=protocol.IssueIdentity(42),
            agent="Bob",
            claim_id="b1",
            operation_id="op-b1",
            branch=ADOPTED_BRANCH,
        ),
    )
    tip_before = state_ref_tip(world.remote)
    arguments = cmd_claim.ClaimArguments(
        agent="Ada", base=world.head, branch=ADOPTED_BRANCH, scope=["uv.lock", "pyproject.toml"]
    )

    request = cmd_claim.claim_request(arguments, adopted=True)
    context = run_context_over(world.forge)

    with pytest.raises(protocol.ClaimConflictError) as refused:
        cmd_claim.checked_claim(request, context, revision=world.head)

    assert str(refused.value) == (
        f"lane '{ADOPTED_BRANCH}' is claimed by Bob (builder) on issue #42 branch {ADOPTED_BRANCH}"
    )
    assert state_ref_tip(world.remote) == tip_before


def _adopted_claim(world: AdoptionWorld) -> protocol.ActiveClaim:
    """The one live claim on the head branch."""
    state = store.fetch_state(worktree=world.clone, remote=str(world.remote))
    [claim] = protocol.claims_on_branch(state.claims, ADOPTED_BRANCH)
    return claim


def _build_lines(world: AdoptionWorld) -> str:
    return f"worktree: {world.pull_request_directory}\nbranch: {ADOPTED_BRANCH}\n"


def _declaration(kind: str, author: str = "app/dependabot") -> str:
    return f"PR #{ADOPTED_PULL_REQUEST} by {author} declares No-Item: {kind}\n"


def _claimed_line(claim: protocol.ActiveClaim) -> str:
    return f"CLAIMED lane {ADOPTED_BRANCH}: {claim.claim_id}\n"


def _removed_pair(world: AdoptionWorld) -> str:
    return (
        f"removed worktree {world.pull_request_directory} and branch "
        f"'{ADOPTED_BRANCH}' this adopt created\n"
    )


def _refusal(sentence: str) -> str:
    return f"ERROR: pull request #{ADOPTED_PULL_REQUEST} {sentence}\n"


def _remote_branch_tip(world: AdoptionWorld) -> str:
    return real_git(
        world.clone, "ls-remote", "origin", f"refs/heads/{ADOPTED_BRANCH}"
    ).stdout.split()[0]


def test_adopt_builds_the_lane_claims_the_branch_and_appends_the_line(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec: ADOPT-20, ADOPT-12, ADOPT-14 (cell 20) -- a pull request that passes every check
    is adopted: the worktree on the head branch, the exclusive claim at the head with the
    overlap noted, one body write, the branch untouched."""
    _claim_the_branch_as(
        "Bob",
        protocol.IssueIdentity(9),
        "b9",
        branch="claude/issue-9-lock",
        scope=("pyproject.toml",),
    )(world)
    reads = count_context_reads(monkeypatch)

    result = adopt(capsys)
    claim_state_reads_by_adopt = reads.observations[world.clone]

    assert (result.status, result.stderr) == (0, "")
    claim = _adopted_claim(world)
    assert re.fullmatch(
        re.escape(_build_lines(world) + _claimed_line(claim))
        + r"\d+ of \d+ versioned files \(\d+%\); overlaps issue #9 on pyproject\.toml\n"
        + re.escape(_declaration("deps")),
        result.stdout,
    )
    assert (claim.agent, claim.role, claim.base) == ("Ada", "builder", world.head)
    assert (claim.identity, claim.scope) == (protocol.LaneIdentity(), ("pyproject.toml", "uv.lock"))
    assert world.forge.body_writes == [(ADOPTED_PULL_REQUEST, ADOPTED_BODY)]
    assert _remote_branch_tip(world) == world.head
    assert real_git(world.pull_request_directory, "rev-parse", "HEAD").stdout.strip() == world.head
    assert (
        real_git(
            world.pull_request_directory, "rev-parse", "--abbrev-ref", "@{upstream}"
        ).stdout.strip()
        == f"origin/{ADOPTED_BRANCH}"
    )
    assert claim_state_reads_by_adopt == 1


def _serve_a_human_author(world: AdoptionWorld, _monkeypatch: pytest.MonkeyPatch) -> None:
    world.serve(lambda landing: replace(landing, author="octocat"))


def _serve_an_empty_body(world: AdoptionWorld, _monkeypatch: pytest.MonkeyPatch) -> None:
    world.serve(lambda landing: replace(landing, body=""))


def _edit_the_prose_before_the_re_read(
    world: AdoptionWorld, _monkeypatch: pytest.MonkeyPatch
) -> None:
    world.forge.scripted_item_reads = [None, "Bump x, edited"]


def _run_from_a_linked_worktree(world: AdoptionWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    lane = world.clone.parent / "linked-lane"
    real_git(world.clone, "worktree", "add", "-q", str(lane), "-b", "linked-lane")
    monkeypatch.chdir(lane)
    redirect_toplevel(monkeypatch, lane)


@pytest.mark.parametrize(
    ("arrange", "arguments", "kind", "written_body", "declaration", "whole_reason"),
    [
        pytest.param(
            _serve_a_human_author,
            [],
            "fix",
            "Bump x\n\nNo-Item: fix",
            _declaration("fix", "octocat"),
            None,
            id="cell-19-human-author-fix",
        ),
        pytest.param(
            lambda world, _monkeypatch: _list_files_named(4)(world),
            ["--whole", "one pull request"],
            "fix",
            "Bump x\n\nNo-Item: fix",
            _declaration("fix"),
            "one pull request",
            id="cell-15-four-paths-with-a-whole-reason",
        ),
        pytest.param(
            _run_from_a_linked_worktree,
            [],
            "deps",
            ADOPTED_BODY,
            _declaration("deps"),
            None,
            id="cell-17-run-from-a-linked-worktree",
        ),
        pytest.param(
            _serve_an_empty_body,
            [],
            "deps",
            "No-Item: deps",
            _declaration("deps"),
            None,
            id="cell-21-empty-body",
        ),
        pytest.param(
            _edit_the_prose_before_the_re_read,
            [],
            "deps",
            "Bump x, edited\n\nNo-Item: deps",
            _declaration("deps"),
            None,
            id="cell-29-prose-edited-between-the-check-and-the-re-read",
        ),
    ],
)
def test_adopt_writes_the_line_onto_the_body_it_read_last(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    arrange: Callable[[AdoptionWorld, pytest.MonkeyPatch], None],
    arguments: list[str],
    kind: str,
    written_body: str,
    declaration: str,
    whole_reason: str | None,
) -> None:
    """Spec: ADOPT-20, ADOPT-12, ADOPT-14, ADOPT-23 -- every setting adopts to the same
    worktree path, claims it as the agent's builder lane, and writes the last-read body once."""
    arrange(world, monkeypatch)

    result = adopt(capsys, *arguments, kind=kind)

    assert (result.status, result.stderr) == (0, "")
    claim = _adopted_claim(world)
    assert result.stdout.startswith(_build_lines(world) + _claimed_line(claim))
    assert result.stdout.endswith(declaration)
    assert (claim.agent, claim.role) == ("Ada", "builder")
    assert claim.whole_reason == whole_reason
    assert world.forge.body_writes == [(ADOPTED_PULL_REQUEST, written_body)]


def test_adopt_writes_the_line_alone_when_github_answers_a_null_body(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec: ADOPT-12 (cell 22) -- the real GitHub adapter reads `"body": null` as an empty
    body, so the one PATCH it sends carries the line alone."""
    current: dict[str, str | None] = {"body": None}
    patches: list[dict[str, str]] = []

    def gh(arguments: list[str], *, input_data: bytes | None = None) -> str:
        if input_data is not None:
            patches.append(json.loads(input_data))
            current["body"] = patches[-1]["body"]
            return ""
        return json.dumps(
            {"state": "open", "title": "Bump x", "body": current["body"], "is_landing": True}
        )

    over_gh = GitHubForge(world.forge.repository, run=gh)

    class ForgeWhoseBodiesAreGitHubs:
        def __getattr__(self, name: str) -> object:
            return getattr(world.forge, name)

        item_reference = over_gh.item_reference
        update_item_body = over_gh.update_item_body

    monkeypatch.setattr(github, "GitHubForge", lambda _repository: ForgeWhoseBodiesAreGitHubs())

    adopt(capsys).expect_success()

    assert patches == [{"body": "No-Item: deps"}]


def _move_the_remote_tracking_ref_before_the_build(
    world: AdoptionWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_linked_worktree = checkout.create_linked_worktree
    tracking_ref = checkout.remote_tracking_ref("origin", ADOPTED_BRANCH)

    def build_after_the_head_ref_moves(
        path: Path, *, branch: str, start_point: str, directory: Path | None = None
    ) -> None:
        tree = real_git(world.clone, "rev-parse", "HEAD^{tree}").stdout.strip()
        moved = real_git(
            world.clone, "commit-tree", tree, "-p", world.head, "-m", "moved"
        ).stdout.strip()
        real_git(world.clone, "update-ref", tracking_ref, moved)
        create_linked_worktree(path, branch=branch, start_point=start_point, directory=directory)

    monkeypatch.setattr(checkout, "create_linked_worktree", build_after_the_head_ref_moves)


def _the_store_is_unreachable_from_the_built_worktree(
    world: AdoptionWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lane's own observation of the state ref fails, after the worktree
    exists and before any push."""
    fetch_state = store.fetch_state
    lane = world.pull_request_directory.resolve()

    def unreachable_from_the_lane(*, worktree: Path, remote: str) -> protocol.ClaimState:
        if worktree.resolve() == lane:
            raise protocol.ClaimError("fatal: unable to access the remote: connection refused")
        return fetch_state(worktree=worktree, remote=remote)

    monkeypatch.setattr(store, "fetch_state", unreachable_from_the_lane)


def _the_store_rejects_every_push(_world: AdoptionWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    fail_every_state_ref_push(
        monkeypatch, protocol.PushRejectedError("! [remote rejected] (failed to lock)")
    )


def _a_claim_lands_between_the_observation_and_the_push(
    world: AdoptionWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    racer = RaceOnceTransport(
        lambda: _claim_the_branch_as("Bob", protocol.IssueIdentity(42), "b42")(world)
    )
    monkeypatch.setattr(store, "GitPushTransport", lambda: racer)


@pytest.mark.parametrize(
    ("arrange", "refusal", "holders"),
    [
        pytest.param(
            _move_the_remote_tracking_ref_before_the_build,
            f"ERROR: pull request #{ADOPTED_PULL_REQUEST} moved while adopt read it; "
            "run adopt again\n",
            [],
            id="cell-23-built-head-differs",
        ),
        pytest.param(
            _the_store_is_unreachable_from_the_built_worktree,
            "ERROR: fatal: unable to access the remote: connection refused\n",
            [],
            id="cell-24-store-unreachable-after-the-build",
        ),
        pytest.param(
            _the_store_rejects_every_push,
            f"ERROR: {store.STATE_REF} rejected ",
            [],
            id="cell-24b-store-rejects-every-push-until-retries-run-out",
        ),
        pytest.param(
            _a_claim_lands_between_the_observation_and_the_push,
            f"ERROR: lane '{ADOPTED_BRANCH}' is claimed by Bob (builder) "
            f"on issue #42 branch {ADOPTED_BRANCH}\n",
            ["Bob"],
            id="cell-25-claim-lands-on-the-branch-under-the-push",
        ),
    ],
)
def test_adopt_removes_the_pair_it_built_when_the_claim_is_refused_after_the_build(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    arrange: Callable[[AdoptionWorld, pytest.MonkeyPatch], None],
    refusal: str,
    holders: list[str],
) -> None:
    """Spec: ADOPT-10, ADOPT-21, ADOPT-29 -- a refusal after the build drops worktree and
    branch, says so, and never writes the body; a rival's claim stays intact."""
    before = world.effects()
    arrange(world, monkeypatch)

    result = adopt(capsys)

    assert result.status == 2
    assert result.stdout == _build_lines(world)
    assert result.stderr.startswith(refusal)
    assert result.stderr.endswith(_removed_pair(world))
    assert world.effects().worktrees_and_branches == before.worktrees_and_branches
    assert not world.pull_request_directory.exists()
    assert world.forge.body_writes == []
    state = store.fetch_state(worktree=world.clone, remote=str(world.remote))
    assert [
        claim.agent for claim in protocol.claims_on_branch(state.claims, ADOPTED_BRANCH)
    ] == holders


def _the_claim_push_is_sent_and_lands_but_its_answer_is_lost(
    _world: AdoptionWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    fail_every_state_ref_push(monkeypatch, protocol.ClaimError("push timed out"), lands=True)


def _the_claim_push_is_sent_and_never_lands(
    _world: AdoptionWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    fail_every_state_ref_push(monkeypatch, protocol.ClaimError("push timed out"))


@pytest.mark.parametrize(
    ("unknown_outcome", "claim_landed", "rerun_status", "rerun_stdout", "rerun_stderr"),
    [
        pytest.param(
            _the_claim_push_is_sent_and_lands_but_its_answer_is_lost,
            True,
            0,
            "{claimed}" + _declaration("deps"),
            "",
            id="cell-27-rerun-resumes-the-landed-claim",
        ),
        pytest.param(
            _the_claim_push_is_sent_and_never_lands,
            False,
            2,
            "",
            "ERROR: {pull_request_directory} already exists; remove it, "
            f"then adopt pull request #{ADOPTED_PULL_REQUEST} again\n",
            id="cell-28-rerun-names-the-kept-pair-of-a-missing-claim",
        ),
    ],
)
def test_adopt_keeps_the_pair_of_an_unknown_claim_outcome_and_a_rerun_settles_it(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    unknown_outcome: Callable[[AdoptionWorld, pytest.MonkeyPatch], None],
    claim_landed: bool,
    rerun_status: int,
    rerun_stdout: str,
    rerun_stderr: str,
) -> None:
    """Spec: ADOPT-22, ADOPT-26, ADOPT-09 (cells 26-28) -- a claim push sent with an
    unknown outcome keeps worktree and branch; the rerun resumes a landed claim with its own id
    and one body write, and meets the kept pair of a claim that is missing."""
    with monkeypatch.context() as unknown:
        unknown_outcome(world, unknown)
        first = adopt(capsys)

    assert first.status == 2
    assert first.stderr.endswith(
        "the claim's push was sent, its outcome unknown; worktree "
        f"{world.pull_request_directory} and branch '{ADOPTED_BRANCH}' kept; "
        "run adopt again to resume it\n"
    )
    assert world.pull_request_directory.is_dir()
    assert world.forge.body_writes == []
    landed = store.fetch_state(worktree=world.clone, remote=str(world.remote)).claims
    assert bool(protocol.claims_on_branch(landed, ADOPTED_BRANCH)) is claim_landed

    rerun = adopt(capsys)

    claimed = _claimed_line(_adopted_claim(world)) if claim_landed else ""
    assert (rerun.status, rerun.stdout, rerun.stderr) == (
        rerun_status,
        rerun_stdout.format(claimed=claimed),
        rerun_stderr.format(pull_request_directory=world.pull_request_directory),
    )
    assert world.forge.body_writes == ([(ADOPTED_PULL_REQUEST, ADOPTED_BODY)] * claim_landed)


def _a_classification_line_appears_before_the_re_read(
    world: AdoptionWorld, _monkeypatch: pytest.MonkeyPatch
) -> None:
    world.forge.scripted_item_reads = [None, "Bump x\n\nWork-Item: #5"]


def _the_forge_refuses_the_write(world: AdoptionWorld, _monkeypatch: pytest.MonkeyPatch) -> None:
    world.forge.update_item_body_error = forge.ForgePermissionDeniedError("HTTP 403")


def _the_write_times_out_after_it_landed(
    world: AdoptionWorld, _monkeypatch: pytest.MonkeyPatch
) -> None:
    world.forge.update_item_body_error = forge.ForgeTransientError("timeout")
    world.forge.update_item_body_lands_before_error = True


def _the_bot_rewrites_the_body_before_the_read_back(
    world: AdoptionWorld, _monkeypatch: pytest.MonkeyPatch
) -> None:
    world.forge.scripted_item_reads = [None, None, "Bump x, rewritten by the bot"]


def _the_re_read_before_the_write_fails(
    world: AdoptionWorld, _monkeypatch: pytest.MonkeyPatch
) -> None:
    world.forge.scripted_item_reads = [None, forge.ForgeTransientError("timeout")]


def _the_read_back_fails(world: AdoptionWorld, _monkeypatch: pytest.MonkeyPatch) -> None:
    world.forge.scripted_item_reads = [None, None, forge.ForgeTransientError("timeout")]


@pytest.mark.parametrize(
    ("arrange", "refusal", "written_bodies"),
    [
        pytest.param(
            _a_classification_line_appears_before_the_re_read,
            _refusal("already carries Work-Item: #5; adopt never changes a classification line"),
            [],
            id="cell-30-line-appears-before-the-re-read",
        ),
        pytest.param(
            _the_re_read_before_the_write_fails,
            _refusal(
                "body could not be read before writing (timeout); the claim stands; run adopt again"
            ),
            [],
            id="cell-30b-re-read-fails",
        ),
        pytest.param(
            _the_forge_refuses_the_write,
            _refusal(
                "body not written (HTTP 403); the claim stands; run adopt again, or release it"
            ),
            [],
            id="cell-31-write-refused",
        ),
        pytest.param(
            _the_write_times_out_after_it_landed,
            _refusal(
                "body write sent, outcome unknown (timeout); the claim stands; run adopt again"
            ),
            [ADOPTED_BODY],
            id="cell-32-write-times-out",
        ),
        pytest.param(
            _the_bot_rewrites_the_body_before_the_read_back,
            _refusal("body changed after adopt wrote it; the claim stands; run adopt again"),
            [ADOPTED_BODY],
            id="cell-33-read-back-differs",
        ),
        pytest.param(
            _the_read_back_fails,
            _refusal(
                "body written, but reading it back failed (timeout); the claim stands; "
                "run adopt again"
            ),
            [ADOPTED_BODY],
            id="cell-34-read-back-fails",
        ),
    ],
)
def test_adopt_keeps_the_claim_and_the_pair_when_the_body_step_goes_wrong(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    arrange: Callable[[AdoptionWorld, pytest.MonkeyPatch], None],
    refusal: str,
    written_bodies: list[str],
) -> None:
    """Spec: ADOPT-23, ADOPT-24, ADOPT-25, ADOPT-27, ADOPT-28, ADOPT-33 -- each failing body
    step is one refusal line that says the claim stands; claim, worktree and branch stay, and
    the body is written at most once."""
    arrange(world, monkeypatch)

    result = adopt(capsys)

    assert (result.status, result.stderr) == (2, refusal)
    claim = _adopted_claim(world)
    assert result.stdout.startswith(_build_lines(world) + _claimed_line(claim))
    assert world.pull_request_directory.is_dir()
    assert world.forge.body_writes == [(ADOPTED_PULL_REQUEST, body) for body in written_bodies]


@pytest.mark.parametrize(
    ("interrupt", "rerun_writes"),
    [
        pytest.param(_the_forge_refuses_the_write, 1, id="cell-35-rerun-writes-the-missing-line"),
        pytest.param(
            _the_write_times_out_after_it_landed, 0, id="cell-36-rerun-keeps-the-landed-line"
        ),
    ],
)
def test_adopts_rerun_after_an_interrupted_write_completes_it_under_the_same_claim(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    interrupt: Callable[[AdoptionWorld, pytest.MonkeyPatch], None],
    rerun_writes: int,
) -> None:
    """Spec: ADOPT-26 (cells 35-36) -- the holder's rerun builds and claims nothing, writes
    the line only when it is missing, and prints the declaration with the claim's own id."""
    interrupt(world, monkeypatch)
    first = adopt(capsys)
    assert (first.status, "the claim stands" in first.stderr) == (2, True)
    claim = _adopted_claim(world)
    tip_before_rerun = state_ref_tip(world.remote)
    writes_before_rerun = len(world.forge.body_writes)
    world.forge.update_item_body_error = None

    rerun = adopt(capsys)

    assert (rerun.status, rerun.stdout, rerun.stderr) == (
        0,
        _claimed_line(claim) + _declaration("deps"),
        "",
    )
    assert world.forge.body_writes[writes_before_rerun:] == (
        [(ADOPTED_PULL_REQUEST, ADOPTED_BODY)] * rerun_writes
    )
    assert world.forge.body_writes[0] == (ADOPTED_PULL_REQUEST, ADOPTED_BODY)
    assert state_ref_tip(world.remote) == tip_before_rerun
    assert _adopted_claim(world) == claim


def _two_classification_lines(world: AdoptionWorld) -> None:
    world.serve(lambda landing: replace(landing, body="Bump x\n\nNo-Item: deps\n\nNo-Item: deps"))


def _bob_claims_the_branch_for_issue_9(world: AdoptionWorld) -> None:
    _claim_the_branch_as("Bob", protocol.IssueIdentity(9), "b9")(world)


def _a_repush_adds_a_path_outside_the_dependency_paths(world: AdoptionWorld) -> None:
    repushed = _publish_branch_tip(world.clone, "re-push")
    world.serve(lambda landing: replace(landing, head_sha=repushed))
    world.forge.changes_by_number[ADOPTED_PULL_REQUEST] = pull_request_listing(
        repushed,
        forge.ChangedFile("uv.lock", None),
        forge.ChangedFile("pyproject.toml", None),
        forge.ChangedFile("src/x.py", None),
    )


@pytest.mark.parametrize(
    ("arrange", "refusal"),
    [
        pytest.param(
            _two_classification_lines,
            _refusal(
                "carries 2 classification lines; exactly one is required; "
                "adopt never changes a classification line"
            ),
            id="cell-37-two-classification-lines",
        ),
        pytest.param(
            _bob_claims_the_branch_for_issue_9,
            f"ERROR: lane '{ADOPTED_BRANCH}' is claimed by Bob (builder) "
            f"on issue #9 branch {ADOPTED_BRANCH}\n",
            id="cell-38-a-second-claim-beside-the-holders",
        ),
        pytest.param(
            _a_repush_adds_a_path_outside_the_dependency_paths,
            _refusal("changes src/x.py, which dependency_paths in .aco/board.toml does not name"),
            id="cell-39-repush-adds-a-path-outside-the-dependency-paths",
        ),
    ],
)
def test_adopts_rerun_judges_the_pull_request_again_and_writes_nothing_when_it_refuses(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[[AdoptionWorld], None],
    refusal: str,
) -> None:
    """Spec: ADOPT-30, ADOPT-31, ADOPT-32 -- the holder's rerun re-judges the body it would
    leave and the listing at the head it reads, and a second claim on the branch ends the resume."""
    adopt(capsys).expect_success()
    arrange(world)
    effects_before_rerun = world.effects()

    rerun = adopt(capsys)

    assert (rerun.status, rerun.stdout, rerun.stderr) == (2, "", refusal)
    assert world.effects() == effects_before_rerun
    assert len(world.forge.body_writes) == 1


def test_adopt_keeps_the_words_around_an_overlong_forge_error_and_escapes_it(
    world: AdoptionWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ADOPT-24, ADOPT-19 -- the forge's text is cut and escaped, the claim-stands
    words after it stay, and the refusal is still one line of at most 200 characters."""
    world.forge.update_item_body_error = forge.ForgeNotFoundError("gone\x1b[31m" + "x" * 400)

    result = adopt(capsys)

    assert result.status == 2
    assert result.stderr.startswith(
        f"ERROR: pull request #{ADOPTED_PULL_REQUEST} body not written (gone\\x1b[31mxxx"
    )
    assert result.stderr.endswith("…); the claim stands; run adopt again, or release it\n")
    assert len(result.stderr) == 201


def test_adopts_rerun_keeps_a_line_that_appears_before_its_re_read(
    world: AdoptionWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ADOPT-26 -- the holder's own line, written by an earlier run whose answer was
    lost, is kept when it shows up between the checks and the re-read: nothing is written."""
    _claim_the_branch_as("Ada")(world)
    world.forge.scripted_item_reads = [None, ADOPTED_BODY]

    result = adopt(capsys)

    assert (result.status, result.stderr) == (0, "")
    assert result.stdout.endswith(_declaration("deps"))
    assert world.forge.body_writes == []


def test_adopt_stops_with_the_status_of_the_claim_check_phase_and_builds_nothing(
    world: AdoptionWorld, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: ADOPT-14 -- a claim check that refuses ends adopt before the build."""
    monkeypatch.setattr(cmd_claim, "checked_lane_claim", lambda *_arguments, **_keywords: 2)
    before = world.effects()

    result = adopt(capsys)

    assert (result.status, result.stdout) == (2, "")
    assert world.effects() == before
