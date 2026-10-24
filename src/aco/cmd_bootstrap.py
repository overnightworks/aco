"""The `bootstrap` command (`specs/bootstrap.spec.md`)."""

from __future__ import annotations

from . import store
from .session import RunContext


def run(context: RunContext) -> int:
    """Create `refs/aco/state` if proven absent; report the existing tip
    untouched when it is already there. Forge-free: `--repo` is
    meaningless here and unused. The context's configuration is the tracked
    one, so an untracked `board.toml` refuses here too, before this
    command's own first write, as a canonical remote with no URL does."""
    canonical_remote = context.configured_canonical_remote
    print(store.bootstrap(worktree=context.toplevel, remote=canonical_remote))
    return 0
