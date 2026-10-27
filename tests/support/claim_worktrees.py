"""The checkout a real-worktree `aco claim` or `aco rescope` scenario runs in:
a clone of the scenario's bare remote carrying the trunk files a scenario
names, the live claims other agents hold, and the linked worktree the command
is made from."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from cli_fixtures import real_git, redirect_toplevel, track_board_config
from store_fixtures import claim_intent, publish_claims_from_a_second_clone

from aco import protocol

LANE_BRANCH = "codex/issue-72-claims"


@dataclass(frozen=True)
class Standing:
    """A live claim another agent holds before this one is made."""

    scope: tuple[str, ...]
    issue: int | None = None
    branch: str = "claude/issue-55-held"
    agent: str = "Ada"

    def intent(self, claim_id: str) -> protocol.ClaimIntent:
        identity = (
            protocol.LaneIdentity() if self.issue is None else protocol.IssueIdentity(self.issue)
        )
        return claim_intent(
            identity=identity,
            agent=self.agent,
            branch=self.branch,
            scope=self.scope,
            claim_id=claim_id,
            operation_id=f"op-{claim_id}",
        )


@dataclass(frozen=True)
class Standpoint:
    """The checkout a command is made in, and the head it stands at."""

    directory: Path
    head: str


StandIn = Callable[..., Standpoint]


def make_stand_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    github_clone: Path,
    bare_remote: Path,
    trunk_files: tuple[str, ...],
) -> StandIn:
    """Where a command is made: a linked worktree on `branch`, or, unlinked,
    the repository's own checkout switched to it. The trunk carries
    `trunk_files` and is pushed, so `origin/HEAD` names `main`; `place` may
    commit more trunk files, or a board configuration, before it publishes
    the standing claims."""
    _commit_trunk(github_clone, trunk_files)

    def place(
        *,
        branch: str = LANE_BRANCH,
        linked: bool = True,
        standing: tuple[Standing, ...] = (),
        more_trunk_files: tuple[str, ...] = (),
        board_config: str | None = None,
    ) -> Standpoint:
        if board_config is not None:
            track_board_config(github_clone, board_config)
        _commit_trunk(github_clone, more_trunk_files)
        intents = tuple(held.intent(f"held-{position}") for position, held in enumerate(standing))
        publish_claims_from_a_second_clone(github_clone, bare_remote, intents)
        directory = github_clone
        if linked:
            directory = tmp_path / "lane"
            real_git(github_clone, "worktree", "add", "-q", "-b", branch, str(directory))
        elif branch != "main":
            real_git(github_clone, "checkout", "-q", "-b", branch)
        redirect_toplevel(monkeypatch, directory)
        monkeypatch.chdir(directory)
        head = real_git(directory, "rev-parse", "HEAD").stdout.strip()
        return Standpoint(directory, head)

    return place


def _commit_trunk(clone: Path, trunk_files: tuple[str, ...]) -> None:
    for name in trunk_files:
        (clone / name).parent.mkdir(parents=True, exist_ok=True)
        (clone / name).write_text("committed\n")
    real_git(clone, "add", ".")
    real_git(clone, "commit", "-q", "--allow-empty", "-m", "trunk files")
    real_git(clone, "push", "-q", "origin", "main")
