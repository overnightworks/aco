"""Git-state-ref tree builders and claim-intent values."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest
from cli_fixtures import fresh_observation, real_git

from aco import protocol, store

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
    remote: Path,
    worktree: Path,
    entries: list[tuple[str, str, str, str]],
    *,
    successor_of: str | None = None,
) -> str:
    """Push an arbitrary top-level tree (built via `raw_tree`) onto `STATE_REF`,
    for the malformed shapes `store`'s own write path can never produce. A
    `successor_of` commit keeps the history a reader has already fetched
    intact; without it the history is replaced by a parentless commit."""
    tree = raw_tree(worktree, entries)
    parent = [] if successor_of is None else ["-p", successor_of]
    commit = (
        subprocess.run(
            ["git", "-C", str(worktree), "commit-tree", tree, *parent, "-m", "test fixture"],
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
    export must leave byte-identical to whatever `fetch_state` last wrote."""
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
    scope: tuple[str, ...] = ("src/aco/store.py",),
    claim_id: str = "a1",
    operation_id: str = "op-1",
    whole_reason: str | None = None,
    resource_name: str | None = None,
    resource_value: int | None = None,
    exclusive_branch: bool = False,
) -> protocol.ClaimIntent:
    return protocol.ClaimIntent(
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
        exclusive_branch=exclusive_branch,
    )


class RaceOnceTransport:
    """A `store.PushTransport` that lets one other writer land on
    `refs/aco/state` between this transition's own read and its first real
    push attempt: `race` performs that genuine second
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


def fail_every_state_ref_push(
    monkeypatch: pytest.MonkeyPatch, error: protocol.ClaimError, *, lands: bool = False
) -> None:
    """Every push of the state ref ends in `error`, the push itself made first
    when `lands` -- a lost answer after the remote advanced."""
    real_push = store.GitPushTransport.push

    def push_then_fail(
        transport: store.GitPushTransport,
        *,
        worktree: Path,
        remote: str,
        ref: str,
        new_oid: protocol.ObjectId,
    ) -> None:
        if lands:
            real_push(transport, worktree=worktree, remote=remote, ref=ref, new_oid=new_oid)
        raise error

    monkeypatch.setattr(store.GitPushTransport, "push", push_then_fail)


def unrelated_racer_commit(worktree: Path, remote: Path) -> str:
    """Pushes one commit carrying the current state tree unchanged -- a
    writer whose own change is unrelated to the transition it races."""
    current = state_ref_tip(remote)
    if current is None:
        raise AssertionError(f"no state ref to race in {remote}")
    tree = real_git(worktree, "rev-parse", f"{current}^{{tree}}").stdout.strip()
    racer = real_git(
        worktree, "commit-tree", tree, "-p", str(current), "-m", "unrelated racer"
    ).stdout.strip()
    real_git(worktree, "push", str(remote), f"{racer}:{store.STATE_REF}")
    return racer


def publish_claims_from_a_second_clone(
    landing_clone: Path,
    remote: Path,
    intents: tuple[protocol.ClaimIntent, ...],
    *,
    bootstrapped_at: str | None = None,
) -> protocol.ClaimState:
    """Publish fixture claims without stamping or anchoring the landing clone.

    `bootstrapped_at` dates the bootstrap commit alone: the commit the first
    claim's `opened_commit` names, which `aco status` reads its age from."""
    seed = landing_clone.parent / "seed"
    real_git(landing_clone.parent, "clone", "-q", str(remote), str(seed))
    observed = seed.resolve() != landing_clone.resolve()
    expected = True
    assert observed == expected
    observed = (
        real_git(seed, "rev-parse", "--absolute-git-dir").stdout
        != real_git(landing_clone, "rev-parse", "--absolute-git-dir").stdout
    )
    assert observed == expected
    with patch.dict(os.environ, {"GIT_COMMITTER_DATE": bootstrapped_at} if bootstrapped_at else {}):
        store.bootstrap(worktree=seed, remote=str(remote))
    for intent in intents:
        store.commit_transition(
            observed=fresh_observation(seed, remote),
            subject=store.transition_subject("claim", intent.identity, intent.branch),
            intent=intent,
        )
    return store.peek_state(worktree=seed, remote=str(remote))


def twin_claim_key(original: protocol.ClaimIntent) -> str:
    return f"{protocol.claim_key(original.identity, original.branch)}-twin"


def push_claim_record(
    remote: Path, worktree: Path, *, source_key: str, key: str, edit: Callable[[str], str]
) -> None:
    """Write `claims/<key>.toml` into the state ref as `edit` of `claims/<source_key>.toml`
    -- a state no command writes, such as a second record on one identity
    (`aco status` calls it a CONFLICT) or a claim opened outside the ref's history."""
    tip = state_ref_tip(remote)
    assert tip is not None
    real_git(worktree, "fetch", "-q", str(remote), store.STATE_REF)
    record = real_git(remote, "cat-file", "-p", f"{tip}:claims/{source_key}.toml").stdout
    edited = blob(worktree, edit(record).encode())
    entries = {
        line.split("\t")[1]: line.split()[2]
        for line in real_git(remote, "ls-tree", f"{tip}:claims").stdout.splitlines()
    }
    claims = raw_tree(
        worktree,
        [("100644", "blob", oid, name) for name, oid in {**entries, f"{key}.toml": edited}.items()],
    )
    top = [line.split(maxsplit=3) for line in real_git(remote, "ls-tree", tip).stdout.splitlines()]
    tree = raw_tree(
        worktree,
        [(mode, kind, claims if name == "claims" else oid, name) for mode, kind, oid, name in top],
    )
    commit = real_git(worktree, "commit-tree", tree, "-p", tip, "-m", "edited claim").stdout.strip()
    real_git(worktree, "push", "-q", str(remote), f"{commit}:{store.STATE_REF}")
