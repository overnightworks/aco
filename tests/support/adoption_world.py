"""The adoption world: pull request #45 of a GitHub-form repository whose head branch sits on
the bare remote, the fake forge that serves it, and the helpers every adoption test shares.
Registered as a pytest plugin, so its `world` fixture resolves by name in every module."""

import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from cli_fixtures import (
    ADOPTED_BRANCH,
    ADOPTED_PULL_REQUEST,
    CliRun,
    dependabot_pull_request,
    pull_request_listing,
    push_repository_trunk,
    real_git,
    run_cli,
    track_board_config,
    worktrees_and_branches,
)
from github_fixtures import FakeForge, landing_readiness, serve_forge
from store_fixtures import state_ref_tip

from aco import forge, protocol, store

DEPENDENCY_PATHS_CONFIG = 'dependency_paths = ["uv.lock", "pyproject.toml"]\n'
ADOPTED_BODY = "Bump x\n\nNo-Item: deps"


def publish_branch_tip(clone: Path, message: str) -> str:
    """A fresh commit adding an empty file on top of `clone`'s `HEAD` (a squash landing needs a
    change), forced onto the remote as the pull request's head branch; no local ref moves."""
    empty_blob = real_git(clone, "hash-object", "-w", "--no-filters", "/dev/null").stdout.strip()
    real_git(clone, "update-index", "--add", "--cacheinfo", f"100644,{empty_blob},{message}.txt")
    tree = real_git(clone, "write-tree").stdout.strip()
    real_git(clone, "reset", "-q")
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
    head = publish_branch_tip(github_clone, "bump x")
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


def adopted_claim(world: AdoptionWorld) -> protocol.ActiveClaim:
    """The one live claim on the head branch."""
    state = store.fetch_state(worktree=world.clone, remote=str(world.remote))
    [claim] = protocol.claims_on_branch(state.claims, ADOPTED_BRANCH)
    return claim


def released_line(claim: protocol.ActiveClaim) -> str:
    return f"RELEASED lane {ADOPTED_BRANCH}: {claim.claim_id}\nfreed: none\nnext: none\n"


def refusal_line(sentence: str) -> str:
    return f"ERROR: pull request #{ADOPTED_PULL_REQUEST} {sentence}\n"


def remote_tip(world: AdoptionWorld, branch: str) -> str:
    return real_git(world.clone, "ls-remote", "origin", f"refs/heads/{branch}").stdout.split()[0]


def repush_the_branch(world: AdoptionWorld, *paths: str) -> str:
    """The bot's force-push: the pull request's head, its listing and the list of files all
    move to a commit that is no descendant of the old head."""
    repushed = publish_branch_tip(world.clone, "re-push")
    world.serve(lambda landing: replace(landing, head_sha=repushed))
    world.head = repushed
    world.list_files(*paths)
    return repushed


def the_forge_reads_the_branch_ready(world: AdoptionWorld) -> None:
    world.forge.readiness_by_number[ADOPTED_PULL_REQUEST] = landing_readiness(
        ADOPTED_PULL_REQUEST, head_sha=world.head
    )
