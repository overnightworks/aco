"""Decide whether a pull request or trunk commit carries its landing classification correctly."""

from __future__ import annotations

from dataclasses import dataclass

from . import board, body, forge, protocol
from .session import RunContext


def _claim_defect(
    claims: tuple[protocol.ActiveClaim, ...],
    detail: forge.Landing,
    identity: protocol.ClaimIdentity,
) -> board.ClassificationDefect | None:
    """A landing declares only what its own head branch holds a live store claim on."""
    matching = next(
        (
            claim
            for claim in claims
            if claim.identity == identity and claim.branch == detail.source_branch
        ),
        None,
    )
    if matching is None:
        subject = (
            f"claim for #{identity.issue}"
            if isinstance(identity, protocol.IssueIdentity)
            else "issue-less lane claim"
        )
        return board.ClassificationDefect(
            f"has no active {subject} on branch {detail.source_branch!r}"
        )
    return None


def _no_item_defect(
    claims: tuple[protocol.ActiveClaim, ...],
    repository: str,
    detail: forge.Landing,
) -> board.ClassificationDefect | None:
    """Why this repository does not accept an issue-less landing as declared.

    A `No-Item` lane owns no issue, so it needs its own lane claim and may
    retire nothing: a closing reference here would close an item no claim and
    no `Work-Item:` line ever named.
    """
    claim_defect = _claim_defect(claims, detail, protocol.LaneIdentity())
    if claim_defect is not None:
        return claim_defect
    closing = board.closing_references(detail.body, repository)
    if closing:
        named = ", ".join(str(reference) for reference in sorted(closing, key=str))
        return board.ClassificationDefect(
            f"declares no work item but closes {named}; name it as the work item"
        )
    return None


@dataclass(frozen=True)
class LandingCheckContext:
    """What every landing-classification helper needs beyond the pull
    request's own detail and the store's live claims: which forge to read
    and which repository owns the check -- grouped so the cluster of helpers
    below stays under the five-argument limit as claims moved from a
    `client`-read ledger walk to a separately threaded store snapshot."""

    run: RunContext
    repository: str
    storage: body.Storage

    @property
    def client(self) -> forge.ForgeReader:
        return self.run.forge


@dataclass(frozen=True)
class _ParentRequirement:
    """What an item's parent demands of the pull request that lands the item.

    `last_child` says closing the parent is *permitted* -- this landing
    closes the parent's one remaining open child; `closing_required` narrows
    that to *required*, which holds only when the parent's own `Next` line
    names no further work.
    """

    reference: board.IssueReference
    closing_required: bool
    last_child: bool


def _parent_body_finding(reference: board.IssueReference, parsed: body.ParsedBody) -> str:
    """Why a malformed parent body refuses the last-child rule before its
    `Next` line is ever consulted (#150)."""
    defect = parsed.contract.defects[0]
    return f"has parent {reference} with a {body.body_defect_text(defect)}"


def _parent_reference_defect(
    parent: board.ParentIssue, repository: str
) -> board.ClassificationDefect | None:
    """Whether the parent itself is even a same-repository container --
    checked before its body is read at all."""
    if parent.reference.repository != repository:
        return board.ClassificationDefect(
            f"has parent {parent.reference} in another repository, "
            "whose children this check cannot read"
        )
    if parent.kind is not body.ItemKind.CONTAINER:
        kind_text = parent.kind.value if parent.kind is not None else "unknown"
        return board.ClassificationDefect(
            f"has parent {parent.reference} of kind {kind_text}, which is not a "
            "container; only a container holds children"
        )
    return None


def _parent_requirement(
    context: LandingCheckContext,
    item: board.IssueReference,
) -> _ParentRequirement | board.ClassificationDefect | None:
    """The parent's demand, read from GitHub's sub-issue relation and its
    body under the repository's own pin (#150).

    Closing a parent's last open child completes the parent only when the
    parent's own `Next` line names no further work; otherwise the container
    keeps dispatching slices, and the landing may close the parent (its one
    remaining child) but need not. A parent keeping other open children
    stays open, and must say what happens next.
    """
    parent = context.client.parent_issue(item.number)
    if parent is None:
        return None
    reference_defect = _parent_reference_defect(parent, context.repository)
    if reference_defect is not None:
        return reference_defect
    parsed_parent = body.parse_body(parent.body, storage=context.storage)
    if parsed_parent.read_state is not body.BodyReadState.VALID:
        return board.ClassificationDefect(_parent_body_finding(parent.reference, parsed_parent))
    remaining = tuple(
        child
        for child in context.client.list_children(parent.reference.number)
        if child.state is board.ChildState.OPEN and child.number != item.number
    )
    if not remaining:
        return _ParentRequirement(
            parent.reference,
            not board.has_further_work(parsed_parent.contract.next),
            True,
        )
    if not parsed_parent.contract.next:
        children = "child" if len(remaining) == 1 else "children"
        return board.ClassificationDefect(
            f"leaves parent {parent.reference} open with {len(remaining)} other open "
            f"{children}, whose body carries no Next line"
        )
    return _ParentRequirement(parent.reference, False, False)


def _closing_defect(
    detail: forge.Landing,
    repository: str,
    item: board.IssueReference,
    requirement: _ParentRequirement | None,
) -> board.ClassificationDefect | None:
    """Which issues this landing must close, and that it closes nothing else."""
    closing = board.closing_references(detail.body, repository)
    if item not in closing:
        return board.ClassificationDefect(f"carries no closing reference for its work item {item}")
    if (
        requirement is not None
        and requirement.closing_required
        and requirement.reference not in closing
    ):
        return board.ClassificationDefect(
            f"closes the last open child of parent {requirement.reference}; close the parent too"
        )
    permitted_parent = (
        {requirement.reference} if requirement is not None and requirement.last_child else set()
    )
    besides = tuple(sorted(closing - {item} - permitted_parent, key=str))
    if besides:
        named = ", ".join(str(reference) for reference in besides)
        return board.ClassificationDefect(
            f"closes {named} besides its work item {item}; a pull request lands one item"
        )
    return None


def _work_item_defect(
    context: LandingCheckContext,
    claims: tuple[protocol.ActiveClaim, ...],
    detail: forge.Landing,
    item: board.IssueReference,
) -> board.ClassificationDefect | None:
    """Why this repository does not accept `item` as the landing pull request's work item."""
    if item.repository != context.repository:
        return board.ClassificationDefect(
            f"names work item {item} of another repository, which holds no claim here"
        )
    claim_defect = _claim_defect(claims, detail, protocol.IssueIdentity(item.number))
    if claim_defect is not None:
        return claim_defect
    requirement = _parent_requirement(context, item)
    if isinstance(requirement, board.ClassificationDefect):
        return requirement
    return _closing_defect(detail, context.repository, item, requirement)


def structural_classification(
    context: LandingCheckContext, detail: forge.Landing
) -> board.Classification | board.ClassificationDefect:
    """The classification `check <pr>` and `land` both start from (issue
    #405): whether this pull request's own shape -- its source repository,
    its `Work-Item:`/`No-Item:` line, its target branch -- names one item at
    all. Never touches a claim, a parent, or a closing reference: `land`'s
    own preflight checks the named item's live open state between this and
    `classification_defect` (LANDCMD-08 before claim validation, issue #405
    review/gate finding)."""
    if detail.source_repository.path != context.repository:
        return board.ClassificationDefect(
            f"proposes a branch of {detail.source_repository}; cross-repository pull "
            "requests are not classified"
        )
    classification = board.parse_pull_request_classification(detail.body, context.repository)
    if isinstance(classification, board.ClassificationDefect):
        return classification
    default_branch = context.run.default_branch
    if detail.target_branch != default_branch:
        return board.ClassificationDefect(
            f"targets {detail.target_branch!r}, not the default branch {default_branch!r}"
        )
    return classification


def classification_defect(
    context: LandingCheckContext,
    claims: tuple[protocol.ActiveClaim, ...],
    detail: forge.Landing,
    classification: board.Classification,
) -> board.ClassificationDefect | None:
    """Whether `classification`'s own claim, parent, and closing rules hold
    (issue #405): the second half of `cli._checked_classification`, split out so
    a caller needing a live-store read only for this half (`land`'s own
    preflight, which fetches store state no earlier than this) never pays
    for one just to read the pull request's own shape."""
    if isinstance(classification, board.NoItemClassification):
        return _no_item_defect(claims, context.repository, detail)
    return _work_item_defect(context, claims, detail, classification.item)
