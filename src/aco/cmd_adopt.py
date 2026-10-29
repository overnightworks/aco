"""The `adopt` command (`specs/adopt.spec.md`): checks a pull request, builds
its lane, claims it exclusively and writes its `No-Item:` line."""
# ruff: noqa: T201 - the adopt command writes its result lines to stdout

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, replace
from pathlib import Path

from . import body, checkout, cmd_claim, forge, github, policy, protocol, report, workboard
from .session import RunContext

_ADOPT_COMMAND = "adopt"
_GITHUB_ONLY_REFUSAL = (
    "aco adopt is a github command; storage = state-ref has no pull requests to adopt"
)
_BODY_CHANGED = (
    "pull request #{number} body changed after adopt wrote it; the claim stands; run adopt again"
)
_RE_READ_FAILED = (
    "pull request #{number} body could not be read before writing ({foreign}); "
    "the claim stands; run adopt again"
)
_READ_BACK_FAILED = (
    "pull request #{number} body written, but reading it back failed ({foreign}); "
    "the claim stands; run adopt again"
)
_BODY_WRITE_FAILED = {
    github.BodyWriteOutcome.REFUSED: (
        "pull request #{number} body not written ({foreign}); "
        "the claim stands; run adopt again, or release it"
    ),
    github.BodyWriteOutcome.UNKNOWN: (
        "pull request #{number} body write sent, outcome unknown ({foreign}); "
        "the claim stands; run adopt again"
    ),
}


@dataclass(frozen=True)
class _Adoption:
    """The pull request `adopt` judged, as the main checkout read it."""

    context: policy.LandingCheckContext
    detail: forge.Landing
    kind: workboard.NoItemKind

    @property
    def run(self) -> RunContext:
        return self.context.run

    @property
    def number(self) -> int:
        return self.detail.number


def _collision_refusal(standing: str, number: int) -> protocol.ClaimUnavailableError:
    return protocol.ClaimUnavailableError(
        f"{standing}; remove it, then adopt pull request #{number} again"
    )


def _moved_refusal(number: int) -> str:
    return f"pull request #{number} moved while adopt read it; run adopt again"


def _pull_request_worktree(context: RunContext, number: int) -> Path:
    return checkout.sibling_worktree_path(context.toplevel, f"pr-{number}")


def _refuse_head_branch_collisions(adoption: _Adoption) -> None:
    """ADOPT-17, ADOPT-09, ADOPT-13, ADOPT-10: the head branch must be a safe
    name, nothing may stand where the lane would be built, and the remote's
    tip must still be the head the checks read."""
    context, number = adoption.run, adoption.number
    branch = adoption.detail.source_branch
    unsafe_head = policy.unsafe_head_branch_defect(adoption.detail)
    if unsafe_head is not None:
        raise protocol.ClaimUnavailableError(f"pull request #{number} {unsafe_head.message}")
    worktree = _pull_request_worktree(context, number)
    if os.path.lexists(worktree):
        raise _collision_refusal(f"{worktree} already exists", number)
    if checkout.branch_exists(branch):
        raise _collision_refusal(f"branch {branch!r} already exists here", number)
    remote = context.configured_canonical_remote
    moved = protocol.ClaimUnavailableError(_moved_refusal(number))
    head_sha = adoption.detail.head_sha
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


def _refusal_around_forge_error(
    template: str, number: int, error: protocol.ClaimError
) -> protocol.ClaimUnavailableError:
    return protocol.ClaimUnavailableError(
        report.refusal_around_foreign_text(template, str(error), number=number)
    )


def _write_and_read_back(adoption: _Adoption, left_body: str) -> None:
    """ADOPT-24, ADOPT-25, ADOPT-27, ADOPT-28: writes `left_body`, then reads
    the body back; every failure leaves the claim standing."""
    number = adoption.number
    try:
        adoption.run.forge_writer.update_item_body(number, left_body)
    except protocol.ClaimError as error:
        template = _BODY_WRITE_FAILED[github.body_write_outcome(error)]
        raise _refusal_around_forge_error(template, number, error) from error
    try:
        written = adoption.run.forge.item_reference(number).body
    except protocol.ClaimError as error:
        raise _refusal_around_forge_error(_READ_BACK_FAILED, number, error) from error
    if written != left_body:
        raise protocol.ClaimUnavailableError(_BODY_CHANGED.format(number=number))


def _print_declaration(adoption: _Adoption) -> None:
    detail = adoption.detail
    classification = workboard.NoItemClassification(adoption.kind)
    print(workboard.pull_request_declaration(detail.number, detail.author, classification))


def _leave_the_line(adoption: _Adoption, *, resumed: bool) -> None:
    """ADOPT-23, ADOPT-33: the body is read again right before it is written, and judged
    and composed from that copy by `policy.adoption_body`, which names the
    body to write or none when the line already stands."""
    number = adoption.number
    try:
        reread = adoption.run.forge.item_reference(number).body
    except protocol.ClaimError as error:
        raise _refusal_around_forge_error(_RE_READ_FAILED, number, error) from error
    left_body = policy.adoption_body(
        adoption.context,
        replace(adoption.detail, body=reread),
        adoption.kind,
        resumed=resumed,
    )
    if isinstance(left_body, workboard.ClassificationDefect):
        raise protocol.ClaimUnavailableError(f"pull request #{number} {left_body.message}")
    if left_body is not None:
        _write_and_read_back(adoption, left_body)
    _print_declaration(adoption)


def _adopt_afresh(
    adoption: _Adoption, plan: policy.FreshAdoption, parsed: argparse.Namespace, agent: str
) -> int:
    """Steps 8 to 11: builds the lane on the head branch, claims it exclusively
    (CLAIM-71) for the listing's path set, then writes the line."""
    context, branch = adoption.run, adoption.detail.source_branch
    _refuse_head_branch_collisions(adoption)
    arguments = cmd_claim.ClaimArguments(
        agent=agent,
        base=plan.expected_head,
        branch=branch,
        scope=list(plan.scope),
        whole=parsed.whole,
    )
    requested = cmd_claim.claim_request(arguments, adopted=True)
    claim_plan = cmd_claim.checked_lane_claim(requested, context, revision=plan.expected_head)
    if isinstance(claim_plan, int):
        return claim_plan
    worktree = cmd_claim.LaneWorktree(_pull_request_worktree(context, adoption.number), branch)
    build = cmd_claim.LaneBuild(
        worktree=worktree,
        start_point=checkout.remote_tracking_ref(context.configured_canonical_remote, branch),
        command=_ADOPT_COMMAND,
        moved_refusal=_moved_refusal(adoption.number),
    )
    built = cmd_claim.claim_in_new_worktree(claim_plan, requested, context, build)
    if isinstance(built, int):
        return built
    claimed, live = built
    cmd_claim.report_claim(claim_plan, claimed, live, as_json=False)
    _leave_the_line(adoption, resumed=False)
    return 0


def _resume(adoption: _Adoption, holder: policy.HolderResume) -> int:
    """ADOPT-26: the holder's rerun builds and claims nothing; it writes the
    line only when it is missing."""
    claim = holder.claim
    print(f"CLAIMED {workboard.claim_subject(claim, adoption.context.storage)}: {claim.claim_id}")
    _leave_the_line(adoption, resumed=True)
    return 0


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
    never read -- refuses with the first failing step, and adopts it."""
    main = context.for_directory(
        checkout.main_checkout_root(toplevel=context.toplevel, command=_ADOPT_COMMAND),
        is_toplevel=True,
    )
    storage = main.config.storage
    if storage is not body.Storage.GITHUB:
        raise protocol.ClaimUnavailableError(_GITHUB_ONLY_REFUSAL)
    number = parsed.pull_request
    agent = parsed.agent
    kind = workboard.NoItemKind(parsed.no_item)
    adoption = _Adoption(
        policy.LandingCheckContext(main, main.forge.repository.path, storage),
        main.forge.landing(number),
        kind,
    )
    outcome = policy.adoption_preflight(
        adoption.context,
        policy.AdoptionRequest(number, kind, agent, cmd_claim.DEFAULT_CLAIM_ROLE),
        adoption.detail,
        main.forge.item_reference(number),
        lambda: main.observation,
    )
    if isinstance(outcome, policy.AdoptionRefusal):
        raise protocol.ClaimUnavailableError(outcome.sentence)
    if isinstance(outcome, policy.FreshAdoption):
        return _adopt_afresh(adoption, outcome, parsed, agent)
    return _resume(adoption, outcome)
