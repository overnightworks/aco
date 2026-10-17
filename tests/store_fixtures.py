"""Git-state-ref tree builders and claim-intent values."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from cli_fixtures import real_git

from agent_coordination import protocol, store

TIP = protocol.ObjectId("a" * 40)
CLAIM_BASE = protocol.ObjectId("c" * 40)
STATE_WITH_TIP = protocol.ClaimState(tip=TIP)
DEFAULT_IDENTITY = protocol.IssueIdentity(42)


def raw_tree(worktree: Path, entries: list[tuple[str, str, str, str]]) -> str:
    """Build a tree object directly from `(mode, kind, oid, name)` entries via
    `git mktree`, which does not itself verify that a referenced oid exists --
    letting tests build the dangling or wrong-kind trees `store`'s own write
    path can never produce."""
    mktree_input = "".join(f"{mode} {kind} {oid}\t{name}\n" for mode, kind, oid, name in entries)
    return (
        subprocess.run(
            ["git", "-C", str(worktree), "mktree"],
            input=mktree_input.encode(),
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .strip()
    )


def blob(worktree: Path, content: bytes) -> str:
    return (
        subprocess.run(
            ["git", "-C", str(worktree), "hash-object", "-w", "--stdin"],
            input=content,
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .strip()
    )


def push_raw_state_tree(
    remote: Path, worktree: Path, entries: list[tuple[str, str, str, str]]
) -> str:
    """Push an arbitrary top-level tree (built via `raw_tree`) onto `STATE_REF`,
    for the malformed shapes `store`'s own write path can never produce."""
    tree = raw_tree(worktree, entries)
    commit = (
        subprocess.run(
            ["git", "-C", str(worktree), "commit-tree", tree, "-m", "test fixture"],
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .strip()
    )
    subprocess.run(
        ["git", "-C", str(worktree), "push", "--force", str(remote), f"{commit}:{store.STATE_REF}"],
        check=True,
        capture_output=True,
    )
    return commit


def lineage_observation(repository: Path) -> tuple[protocol.ObjectId | None, str | None]:
    """This worktree's lineage stamp and fetch anchor -- the two
    per-worktree values a reset dry run, a live-claim refusal, or a failed
    export must leave byte-identical to whatever `fetch_state` last wrote
    (issue #298, 19.09.2026 gate finding 2)."""
    stamp = store._read_lineage_stamp(repository)
    anchor = store._run_git(repository, ["rev-parse", store._FETCH_ANCHOR_REF])
    return stamp, anchor.stdout.decode().strip() if anchor.exit_status == 0 else None


def state_ref_tip(remote: Path) -> str | None:
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", str(remote), store.STATE_REF],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.split("\t", 1)[0]


def state_ref_listing(remote: Path) -> dict[bytes, bytes]:
    """`git ls-tree -r -z` of the state ref in `remote`, raw path -> raw
    `mode kind oid`."""
    listing = subprocess.run(
        ["git", "--git-dir", str(remote), "ls-tree", "-r", "-z", store.STATE_REF],
        check=True,
        capture_output=True,
    ).stdout
    records = (record.split(b"\t", 1) for record in listing.split(b"\0") if record)
    return {path: header for header, path in records}


def claim_intent(
    *,
    identity: protocol.ClaimIdentity = DEFAULT_IDENTITY,
    agent: str = "Ada",
    role: str = "builder",
    base: protocol.ObjectId = CLAIM_BASE,
    branch: str = "claude/issue-42-cut",
    scope: tuple[str, ...] = ("src/agent_coordination/store.py",),
    claim_id: str = "a1",
    operation_id: str = "op-1",
    whole_reason: str | None = None,
    resource_name: str | None = None,
    resource_value: int | None = None,
    exclusive_branch: bool = False,
) -> protocol.ClaimIntent:
    intent = protocol.ClaimIntent(
        identity=identity,
        agent=agent,
        role=role,
        base=base,
        branch=branch,
        scope=scope,
        claim_id=protocol.ClaimId(claim_id),
        operation_id=operation_id,
        whole_reason=whole_reason,
        resource_name=resource_name,
        resource_value=resource_value,
    )
    return replace(intent, exclusive_branch=True) if exclusive_branch else intent


class RaceOnceTransport:
    """A `store.PushTransport` that lets one other writer land on
    `refs/aco/state` between this transition's own read and its first real
    push attempt (issues #359 R3, #459): `race` performs that genuine second
    `git push` -- not a monkeypatched rejection -- so the ordinary
    `commit_transition` retry loop meets a real non-fast-forward rejection
    and must actually refetch and reapply."""

    def __init__(self, race: Callable[[], object]) -> None:
        self._race: Callable[[], object] | None = race
        self._real = store.GitPushTransport()

    def push(self, *, worktree: Path, remote: str, ref: str, new_oid: protocol.ObjectId) -> None:
        if self._race is not None:
            race, self._race = self._race, None
            race()
        self._real.push(worktree=worktree, remote=remote, ref=ref, new_oid=new_oid)


def unrelated_racer_commit(worktree: Path, remote: Path) -> str:
    """Pushes one commit carrying the current state tree unchanged -- a
    writer whose own change is unrelated to the transition it races."""
    current = state_ref_tip(remote)
    tree = real_git(worktree, "rev-parse", f"{current}^{{tree}}").stdout.strip()
    racer = real_git(
        worktree, "commit-tree", tree, "-p", str(current), "-m", "unrelated racer"
    ).stdout.strip()
    real_git(worktree, "push", str(remote), f"{racer}:{store.STATE_REF}")
    return racer
