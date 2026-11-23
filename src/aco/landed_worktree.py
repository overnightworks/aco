"""The cleanup of a landed lane's worktree and local branch after a `--merged` release."""

import argparse
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial

from . import body, checkout, forge, protocol, store, submodule_stores, workboard
from .session import RunContext


@dataclass(frozen=True)
class LandedLane:
    """The lane a `--merged` release cleans up after: `proven_tips` (the head the forge recorded as
    landed, none under `state-ref`, plus an adopted lane's `base`), `rerun` (the `release` line
    repeating this cleanup where its worktree is, REL-52), `merge_commit` (the forge's), `item`
    (the work item as the release read it)."""

    identity: protocol.ClaimIdentity
    branch: str
    proven_tips: frozenset[str]
    rerun: str
    merge_commit: str | None = None
    item: forge.ItemReference | None = None

    def landed_as(self, commit: str, item: forge.ItemReference | None) -> LandedLane:
        return LandedLane(self.identity, self.branch, self.proven_tips, self.rerun, commit, item)


def landed_lane(
    identity: protocol.ClaimIdentity,
    storage: body.Storage,
    landing: str,
    branch: str,
    proven_tips: Iterable[str],
) -> LandedLane:
    """`branch`'s lane, landed as `landing` -- a pull request number, or the verified trunk sha
    under `storage = "state-ref"` -- with its `rerun` rendered by the one advice renderer, so it
    runs as printed under either storage pin and from any checkout (REL-52)."""
    item = (
        ()
        if isinstance(identity, protocol.LaneIdentity)
        else (workboard.item_argument(identity.issue, storage),)
    )
    rerun = workboard.advice_command("release", *item, "--merged", landing, "--branch", branch)
    return LandedLane(identity, branch, frozenset(proven_tips), rerun)


_WORKTREE_KEPT_FLAG_REASON = "--keep-worktree was given"


_WORKTREE_KEPT_RAN_FROM_INSIDE_REASON = "release ran from inside it"


# Names the repair: a landing from a separate clone holds
# no lane worktree, which stays where it lives for that checkout to remove.
_WORKTREE_KEPT_NO_WORKTREE_REASON = (
    "no linked worktree on {branch} in this checkout; run {rerun} in the checkout that holds it"
)


def worktree_cleanup_outcome_text(outcome: checkout.WorktreeCleanupOutcome) -> str:
    """The tail `release` prints after `worktree: ` in text, and the exact `--json` value of its
    `worktree` field: one owner, so the two shapes can never drift apart. A branch-deletion
    failure after the worktree is already gone names both halves -- never a bare `kept`, which
    would hide that the worktree itself is gone; a section git kept after the branch itself
    went names that section, never the branch; a delete that timed out reads the branch
    unknown, never kept."""
    if not outcome.worktree.removed:
        return f"kept -- {outcome.worktree.reason}"
    if outcome.branch.fate is not checkout.BranchFate.REMOVED:
        return f"removed; branch {outcome.branch.fate} -- {outcome.branch.reason}"
    section_kept = outcome.branch.section_kept
    if section_kept is not None:
        return f"removed; {section_kept.section} section kept -- {section_kept.reason}"
    return "removed"


def cleanup_landed_worktree(
    parsed: argparse.Namespace,
    lane: LandedLane,
    context: RunContext,
    fetched_trunk_ref: Callable[[], str],
) -> checkout.WorktreeCleanupOutcome:
    """After a successful `--merged` release, remove the lane's local worktree and local branch
    when both are safe to remove, and report exactly what happened either way: loud for every
    outcome, never a silent decline. `--keep-worktree` opts out outright; a worktree cannot
    remove its own cwd, so a release running from inside it keeps both; neither needs
    `checkout.py`'s own merged/elsewhere/dirty/removal policy
    (`checkout.cleanup_landed_worktree`), since both read only this process's own cwd and
    worktree listing. A git failure at any step -- including one resolving which worktree
    matches `branch` at all -- is reported in the same `kept` line rather than swallowed. The
    run's own checkout is judged from the toplevel its context already holds, never resolved a
    second time. `fetched_trunk_ref` names the ref the lane must be merged into -- the one its
    release judged the landing on -- asked only here, so a failure to resolve it reads as
    `kept` too. The lane's `proven_tips` are the tips it may be removed on besides trunk. The
    remote branch stays the forge merge's own business either way."""
    if parsed.keep_worktree:
        return checkout.worktree_cleanup_kept(_WORKTREE_KEPT_FLAG_REASON)
    branch = lane.branch
    try:
        toplevel = context.toplevel
        others = tuple(path for path in store.list_worktrees(toplevel) if path != toplevel)
        if checkout.current_branch(directory=toplevel) == branch:
            return checkout.worktree_cleanup_kept(_WORKTREE_KEPT_RAN_FROM_INSIDE_REASON)
        matching = checkout.worktree_on_branch(others, branch)
        if matching is None:
            return checkout.worktree_cleanup_kept(
                _WORKTREE_KEPT_NO_WORKTREE_REASON.format(branch=branch, rerun=lane.rerun)
            )
        return checkout.cleanup_landed_worktree(
            matching,
            branch,
            policy=checkout.RemovalPolicy(
                fetched_trunk_ref(),
                lane.proven_tips,
                partial(submodule_stores.removal_proof, branch=branch),
            ),
            directory=toplevel,
        )
    except protocol.ClaimError as error:
        return checkout.worktree_cleanup_kept(f"git failure: {error}")
