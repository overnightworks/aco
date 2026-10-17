"""`aco adopt` refuses before any write, through the real CLI (`specs/adopt.spec.md`)."""

from __future__ import annotations

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
    track_board_config,
    worktrees_and_branches,
)
from github_fixtures import FakeForge, serve_forge
from store_fixtures import claim_intent, state_ref_tip

from agent_coordination import checkout, forge, protocol, store

DEPENDENCY_PATHS_CONFIG = 'dependency_paths = ["uv.lock", "pyproject.toml"]\n'
PASSES_EVERY_CHECK = (
    f"ERROR: pull request #{ADOPTED_PULL_REQUEST} passes every adoption check; "
    "this aco does not build adoptions yet\n"
)


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


def _claim_the_branch_as(agent: str) -> Callable[[AdoptionWorld], None]:
    def claim(world: AdoptionWorld) -> None:
        lane = protocol.LaneIdentity()
        store.commit_transition(
            observed=fresh_observation(world.clone, world.remote),
            subject=store.transition_subject("claim", lane, ADOPTED_BRANCH),
            intent=claim_intent(
                identity=lane,
                agent=agent,
                branch=ADOPTED_BRANCH,
                base=protocol.ObjectId(world.head),
                scope=("uv.lock",),
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
    """Spec: ADOPT-05, ADOPT-06, ADOPT-07, ADOPT-09, ADOPT-10, ADOPT-13, ADOPT-14, ADOPT-17 --
    each refusal names its cause and leaves the repository, the state ref and the body as found."""
    arrange(world)
    before = world.effects()

    result = adopt(capsys, kind=kind)

    sentence = refusal.format(pull_request_directory=world.pull_request_directory)
    assert (result.status, result.stdout, result.stderr) == (2, "", f"ERROR: {sentence}\n")
    assert world.effects() == before


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


def test_adopt_fetches_no_branch_into_a_local_ref_even_when_a_fetch_refspec_asks_to(
    world: AdoptionWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ADOPT-18, Never -- a configured `+refs/heads/*:refs/heads/mirror/*` stays unused."""
    real_git(
        world.clone, "config", "--add", "remote.origin.fetch", "+refs/heads/*:refs/heads/mirror/*"
    )
    local_branches = real_git(world.clone, "for-each-ref", "refs/heads", "refs/tags").stdout

    result = adopt(capsys)

    assert result.stderr == PASSES_EVERY_CHECK
    assert real_git(world.clone, "for-each-ref", "refs/heads", "refs/tags").stdout == local_branches


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
    before = world.effects()

    result = adopt(capsys)

    assert (result.status, result.stdout, result.stderr) == (2, "", PASSES_EVERY_CHECK)
    assert world.effects() == before


def test_adopt_that_passes_every_check_refuses_and_writes_nothing(
    world: AdoptionWorld,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec: ADOPT-14, ADOPT-18 -- all checks pass, a wide scope given its reason, and
    still no worktree, branch, claim transition or body write; claim state read once."""
    _list_files_named(4)(world)
    before = world.effects()
    reads = count_context_reads(monkeypatch)

    result = adopt(capsys, "--whole", "one pull request", kind="fix")

    assert (result.status, result.stdout, result.stderr) == (2, "", PASSES_EVERY_CHECK)
    assert world.effects() == before
    assert sum(reads.observations.values()) == 1
