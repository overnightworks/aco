"""The checkout a real-worktree `aco claim` or `aco rescope` scenario runs in:
a clone of the scenario's bare remote carrying the trunk files a scenario
names, the live claims other agents hold, and the linked worktree the command
is made from."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, board_issue, complete_contract
from cli_fixtures import real_git, redirect_toplevel, track_board_config
from github_fixtures import FakeForge, serve_forge
from store_fixtures import claim_intent, publish_claims_from_a_second_clone

from aco import cli as issue_claim
from aco import forge, protocol, store

ISSUE = 72
LANE_BRANCH = "codex/issue-72-claims"
LANE_MODE_BRANCH = "docs/lane-cleanup"


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


def serve_item(monkeypatch: pytest.MonkeyPatch, scope: tuple[str, ...]) -> None:
    body = complete_contract("Build it.", scope=list(scope), whole="The scenario claims it as one.")
    served = FakeForge(
        board_issues=(board_issue(ISSUE, "Claims", body),),
        issue_references={ISSUE: forge.ItemReference(forge.ItemState.OPEN, "Claims", body)},
    )
    serve_forge(monkeypatch, served)


def claim(
    *flags: str,
    scope: tuple[str, ...] = ("src",),
    agent: str | None = "Codex Sol",
    issue: int | None = ISSUE,
) -> int:
    """`aco claim` as an agent runs it: the item `issue` (none for a lane
    claim), `agent` (none leaves the identity to the environment) and `scope`."""
    number = [] if issue is None else [str(issue)]
    agent_flags = [] if agent is None else ["--agent", agent]
    scope_flags = [part for path in scope for part in ("--scope", path)]
    return issue_claim.main(
        ["--repo", REPOSITORY, "claim", *number, *agent_flags, *scope_flags, *flags]
    )


def standing_claims(standpoint: Standpoint) -> list[protocol.ActiveClaim]:
    state = store.fetch_state(worktree=standpoint.directory, remote="origin")
    return list(state.claims.values())


def claimed_here(standpoint: Standpoint) -> protocol.ActiveClaim:
    [claimed] = [
        held
        for held in standing_claims(standpoint)
        if held.identity == protocol.IssueIdentity(ISSUE)
    ]
    return claimed


def assert_json_refusal_object(err: str, out: str, *, reason: str) -> None:
    """`--json` refusal (`specs/output.spec.md` OUT-01, OUT-03): stdout holds
    the object `ok`, `reason`, `message` in that order, its `message` the
    sentence stderr printed after `ERROR: `. Compares the raw JSON text, so a
    reordering of that sequence fails."""
    assert err.startswith("ERROR: ")
    message = err.removeprefix("ERROR: ").rstrip("\n")
    expected = {"ok": False, "reason": reason, "message": message}
    assert out == json.dumps(expected) + "\n"
    assert json.loads(out) == expected


def _commit_trunk(clone: Path, trunk_files: tuple[str, ...]) -> None:
    for name in trunk_files:
        (clone / name).parent.mkdir(parents=True, exist_ok=True)
        (clone / name).write_text("committed\n")
    real_git(clone, "add", ".")
    real_git(clone, "commit", "-q", "--allow-empty", "-m", "trunk files")
    real_git(clone, "push", "-q", "origin", "main")
