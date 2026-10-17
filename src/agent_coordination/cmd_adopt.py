"""The `adopt` command (`specs/adopt.spec.md`): every refusal before a write."""

from __future__ import annotations

import argparse

from . import board, body, checkout, cmd_claim, policy, protocol
from .session import RunContext

_ADOPT_COMMAND = "adopt"
_GITHUB_ONLY_REFUSAL = (
    "aco adopt is a github command; storage = state-ref has no pull requests to adopt"
)


def _collision_refusal(standing: str, number: int) -> protocol.ClaimUnavailableError:
    return protocol.ClaimUnavailableError(
        f"{standing}; remove it, then adopt pull request #{number} again"
    )


def _refuse_head_branch_collisions(
    context: RunContext, number: int, head_sha: str, branch: str
) -> None:
    """ADOPT-27, ADOPT-10, ADOPT-20, ADOPT-11: the head branch must be a safe
    name, nothing may stand where the lane would be built, and the remote's
    tip must still be the head the checks read."""
    if not protocol.is_safe_branch_name(branch):
        raise protocol.ClaimUnavailableError(
            f"pull request #{number} head branch {branch!r} is no safe branch name"
        )
    worktree = checkout.sibling_worktree_path(context.toplevel, f"pr-{number}")
    if worktree.exists():
        raise _collision_refusal(f"{worktree} already exists", number)
    if checkout.branch_exists(branch):
        raise _collision_refusal(f"branch {branch!r} already exists here", number)
    context.fetched_trunk_ref()
    fetched_tip = checkout.commit_at(
        f"refs/remotes/{context.canonical_remote}/{branch}", directory=context.toplevel
    )
    if fetched_tip != head_sha:
        raise protocol.ClaimUnavailableError(
            f"pull request #{number} moved while adopt read it; run adopt again"
        )


def _refuse_unclaimable_scope(
    parsed: argparse.Namespace, context: RunContext, plan: policy.FreshAdoption, branch: str
) -> None:
    """ADOPT-23: the claim `adopt` would make, run through `claim`'s own check phase."""
    arguments = argparse.Namespace(
        issue=None,
        agent=parsed.agent,
        role=cmd_claim.DEFAULT_CLAIM_ROLE,
        base=plan.expected_head,
        branch=branch,
        scope=list(plan.scope),
        claim_id=None,
        out_of_order=None,
        whole=parsed.whole,
    )
    requested = cmd_claim.claim_request(arguments, adopted=True)
    try:
        cmd_claim.checked_claim(requested, context, revision=plan.expected_head)
    except protocol.ClaimConflictError as error:
        raise board.named_refusal(error, context.config.storage) from error


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """Judges pull request `parsed.pull_request` from the main checkout, as
    `start` does -- a linked worktree's own copy of the board configuration is
    never read -- and refuses with the first failing step; a pull request that
    passes every check is still refused, since this aco builds no adoption."""
    main = context.for_directory(
        checkout.main_checkout_root(toplevel=context.toplevel, command=_ADOPT_COMMAND),
        is_toplevel=True,
    )
    storage = main.config.storage
    if storage is not body.Storage.GITHUB:
        raise protocol.ClaimUnavailableError(_GITHUB_ONLY_REFUSAL)
    number = parsed.pull_request
    detail = main.forge.landing(number)
    outcome = policy.adoption_preflight(
        policy.LandingCheckContext(main, main.forge.repository.path, storage),
        policy.AdoptionRequest(number, board.NoItemKind(parsed.no_item)),
        detail,
        main.forge.item_reference(number),
        lambda: main.observation,
    )
    if isinstance(outcome, policy.AdoptionRefusal):
        raise protocol.ClaimUnavailableError(outcome.sentence)
    _refuse_head_branch_collisions(main, number, detail.head_sha, detail.source_branch)
    _refuse_unclaimable_scope(parsed, main, outcome, detail.source_branch)
    raise protocol.ClaimUnavailableError(
        f"pull request #{number} passes every adoption check; this aco does not build adoptions yet"
    )
