"""Git-state-ref tree builders and claim-intent values shared by
`tests/test_store.py` (the state-ref transport), `tests/test_protocol.py` (the
pure `apply` logic) and `tests/test_state_board.py` (the board over a raw
state tree). All import this module directly; pytest's rootless collection
puts `tests/` on `sys.path`, so a plain `import store_fixtures` resolves
here."""

from __future__ import annotations

import subprocess
from pathlib import Path

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
    )
