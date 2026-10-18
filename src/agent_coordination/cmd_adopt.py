"""The `adopt` command (`specs/adopt.spec.md`): every refusal before a write."""

from __future__ import annotations

import argparse
import os

from . import board, body, checkout, cmd_claim, policy, protocol, report
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
    """ADOPT-17, ADOPT-09, ADOPT-13, ADOPT-10: the head branch must be a safe
    name, nothing may stand where the lane would be built, and the remote's
    tip must still be the head the checks read."""
    if not protocol.is_safe_branch_name(branch):
        raise protocol.ClaimUnavailableError(
            f"pull request #{number} head branch {branch!r} is no safe branch name"
        )
    worktree = checkout.sibling_worktree_path(context.toplevel, f"pr-{number}")
    if os.path.lexists(worktree):
        raise _collision_refusal(f"{worktree} already exists", number)
    if checkout.branch_exists(branch):
        raise _collision_refusal(f"branch {branch!r} already exists here", number)
    remote = context.configured_canonical_remote
    moved = protocol.ClaimUnavailableError(
        f"pull request #{number} moved while adopt read it; run adopt again"
    )
    if checkout.remote_branch_tip(remote, branch, directory=context.toplevel) != head_sha:
        raise moved
    try:
        checkout.fetch_remote_branches(
            remote, (branch, context.default_branch), directory=context.toplevel
        )
    except protocol.ClaimError:
        if checkout.remote_branch_tip(remote, branch, directory=context.toplevel) is not None:
            raise
        raise moved from None
    if (
        checkout.commit_at(checkout.remote_tracking_ref(remote, branch), directory=context.toplevel)
        != head_sha
    ):
        raise moved


def _refuse_unclaimable_scope(
    parsed: argparse.Namespace, context: RunContext, plan: policy.FreshAdoption, branch: str
) -> None:
    """ADOPT-14: the claim `adopt` would make, run through `claim`'s own check phase."""
    arguments = cmd_claim.ClaimArguments(
        agent=parsed.agent,
        base=plan.expected_head,
        branch=branch,
        scope=list(plan.scope),
        whole=parsed.whole,
    )
    requested = cmd_claim.claim_request(arguments, adopted=True)
    cmd_claim.checked_lane_claim(requested, context, revision=plan.expected_head)


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """Every refusal reaches the terminal as one escaped line of at most 200
    characters (`report.bounded_refusal`), whoever raised it."""
    try:
        return _judge(parsed, context)
    except protocol.ClaimError as error:
        raise protocol.ClaimUnavailableError(report.bounded_refusal(str(error))) from error


def _judge(parsed: argparse.Namespace, context: RunContext) -> int:
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
