"""Pull-request landing checks for classification, closing references, claims,
and parent requirements, `aco adopt`'s preflight, plus the claim width gate."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache

from . import body, checkout, forge, protocol, workboard
from .session import RunContext


def _scope_cost(versioned: tuple[str, ...], scope: tuple[str, ...]) -> tuple[int, int, float]:
    covered_file_count = len(checkout.paths_under_scope(versioned, scope))
    versioned_file_count = len(versioned)
    share = 0.0 if versioned_file_count == 0 else covered_file_count / versioned_file_count
    return covered_file_count, versioned_file_count, share


def _wide_scope_condition(trip: protocol.WideScopeTrip) -> str:
    """The tripped condition in words, with the numbers it was judged
    against -- what the refusal names instead of restating the whole rule."""
    if trip.reason is protocol.WideScopeReason.PATH_COUNT:
        return f"{trip.path_count} paths exceeds three"
    if trip.reason is protocol.WideScopeReason.DIRECTORY:
        noun = "directory" if len(trip.directories) == 1 else "directories"
        return f"{len(trip.directories)} {noun} in scope ({', '.join(trip.directories)})"
    covered, total = trip.covered_file_count, trip.versioned_file_count
    percent = round(100 * covered / total)
    path_word = "path" if covered == 1 else "paths"
    return f"{covered} {path_word} of {total} versioned files ({percent} %) exceeds a quarter"


def _wide_scope_refusal(trip: protocol.WideScopeTrip, *, names_body_fallback: bool) -> str:
    suffix = " or set whole in the body" if names_body_fallback else ""
    return f"scope is wide: {_wide_scope_condition(trip)}; pass --whole REASON{suffix}"


def reject_wide_scope(
    scope: tuple[str, ...],
    versioned: tuple[str, ...],
    whole_reason: str | None,
    *,
    directories: tuple[str, ...],
    whole_from_body: Callable[[], str | None] | None = None,
) -> tuple[int, int, float, str | None]:
    """`scope`'s own width gate, `whole_reason`'s own text
    admitting a wide one exactly as before -- plus, for `claim`/`start`, the effective reason
    actually used: `whole_reason` itself
    when given, else `whole_from_body()`, read only once the gate actually
    trips and the caller named none, so a narrow scope or an explicit
    `--whole` never costs the body read `whole_from_body` performs.
    `rescope` judges an issue claim by the same rule, from the
    body it already read; a lane claim names no item, passes no
    `whole_from_body`, and keeps the plain refusal. `directories` are
    the scope entries that name a directory in the tree `versioned` lists
    (`checkout.scope_directories`)."""
    covered_file_count, versioned_file_count, share = _scope_cost(versioned, scope)
    trip = wide_scope_trip(scope, versioned, directories=directories)
    if trip is None:
        return covered_file_count, versioned_file_count, share, whole_reason
    effective = whole_reason
    if effective is None and whole_from_body is not None:
        effective = whole_from_body()
    if effective is None:
        raise protocol.ClaimError(
            _wide_scope_refusal(trip, names_body_fallback=whole_from_body is not None)
        )
    return covered_file_count, versioned_file_count, share, effective


def wide_scope_trip(
    scope: tuple[str, ...], versioned: tuple[str, ...], *, directories: tuple[str, ...]
) -> protocol.WideScopeTrip | None:
    """`scope`'s width judged against the tree `versioned` lists, whose
    entries naming a directory are `directories` -- the one measure the
    width gate refuses by and `next`'s advice anticipates."""
    covered_file_count, versioned_file_count, _share = _scope_cost(versioned, scope)
    return protocol.wide_scope_trip(
        scope,
        directories=directories,
        covered_file_count=covered_file_count,
        versioned_file_count=versioned_file_count,
    )


def reject_ungrounded_comma_scope(
    scope: tuple[str, ...], versioned: tuple[str, ...], *, flag: str
) -> None:
    """Refuse a scope entry that contains a comma and matches no versioned
    file -- the shape `{flag} a.py,b.py` takes when passed as one flag from
    habit instead of one path per flag. Stored verbatim, that
    single entry names a path nothing tracks, so the claim protects nothing:
    the lane's real files stay uncovered and no overlap check can ever fire
    for them.

    Never call this over `--drop`: a value the live claim already holds is a
    fact about the claim, not a typo about the checkout, and dropping a value
    the claim does not hold is already refused by `combined_scope` with a
    truer sentence naming the claim rather than the checkout -- adding this
    check there would either block the very repair this refusal exists to
    leave open (dropping an already-claimed ungrounded value), or never fire
    at all (a not-yet-dropped value the claim lacks is refused first).

    Splitting on the comma would be the old, wrong fix: it made
    a real comma-bearing filename unrepresentable. So a real comma-bearing
    path that names a versioned file, or a directory holding one, still
    passes here -- `paths_under_scope` matches either. So does a comma-free
    path that does not exist yet, since a lane routinely claims files it is
    about to create; only a comma with no match among versioned files is the
    signature this refuses.
    """
    for entry in scope:
        if "," in entry and not checkout.paths_under_scope(versioned, (entry,)):
            raise protocol.ClaimError(
                f"{entry!r} matches no versioned file; one {flag} path per flag, so its comma "
                f"is read literally -- repeat {flag} for a second path"
            )


def _claim_defect(
    claims: tuple[protocol.ActiveClaim, ...],
    detail: forge.Landing,
    identity: protocol.ClaimIdentity,
) -> workboard.ClassificationDefect | None:
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
        return workboard.ClassificationDefect(
            f"has no active {subject} on branch {detail.source_branch!r}"
        )
    return None


def listed_paths(
    changes: forge.PullRequestChanges, expected_head: str
) -> workboard.ClassificationDefect | frozenset[str]:
    if changes.before != changes.after or changes.before.head_sha != expected_head:
        return workboard.ClassificationDefect(
            "changed while aco listed its files; run the command again"
        )
    if len(changes.files) != changes.before.changed_files:
        return workboard.ClassificationDefect(
            f"lists {len(changes.files)} of its {changes.before.changed_files} changed files; "
            "aco judges only a complete listing"
        )
    return frozenset(
        path
        for file in changes.files
        for path in (file.path, file.previous_path)
        if path is not None
    )


def dependency_rule_defect(
    config: workboard.BoardConfig,
    listed: Callable[[], workboard.ClassificationDefect | frozenset[str]],
) -> workboard.ClassificationDefect | None:
    if not config.dependency_paths:
        return workboard.ClassificationDefect(
            f"declares No-Item: deps, but {workboard.CONFIG_PATH.as_posix()} "
            "names no dependency_paths"
        )
    paths = listed()
    if isinstance(paths, workboard.ClassificationDefect):
        return paths
    outside = sorted(path for path in paths if not config.covers_dependency_path(path))
    if outside:
        named = protocol.named_with_overflow_count(
            tuple(
                workboard.truncated_display_name(protocol.terminal_text(path)) for path in outside
            )
        )
        return workboard.ClassificationDefect(
            f"changes {named}, which dependency_paths in "
            f"{workboard.CONFIG_PATH.as_posix()} does not name"
        )
    return None


def _no_item_defect(
    context: LandingCheckContext,
    claims: tuple[protocol.ActiveClaim, ...],
    detail: forge.Landing,
    kind: workboard.NoItemKind,
    expected_head: str,
) -> workboard.ClassificationDefect | None:
    """Why this repository does not accept an issue-less landing as declared.

    A `No-Item` lane owns no issue, so it needs its own lane claim and may
    retire nothing: a closing reference here would close an item no claim and
    no `Work-Item:` line ever named. A deps lane must also stay inside the
    configured dependency paths, proven by a complete listing at the expected head.
    """
    claim_defect = _claim_defect(claims, detail, protocol.LaneIdentity())
    if claim_defect is not None:
        return claim_defect
    closing_defect = closing_reference_defect(detail.body, context.repository)
    if closing_defect is not None:
        return closing_defect
    if kind is workboard.NoItemKind.DEPS:
        return dependency_rule_defect(
            context.run.config,
            lambda: listed_paths(context.client.pull_request_changes(detail.number), expected_head),
        )
    return None


def closing_reference_defect(body: str, repository: str) -> workboard.ClassificationDefect | None:
    """Why an issue-less body cannot close the items it names."""
    closing = workboard.closing_references(body, repository)
    if closing:
        named = ", ".join(str(reference) for reference in sorted(closing, key=str))
        return workboard.ClassificationDefect(
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

    `last_child` says this landing closes the parent's one remaining open
    child, the only case in which closing the parent can be required or
    permitted; `completion` is what the parent's own body says about closing
    it, and `FORBIDDEN` holds whether or not this is the last child.
    """

    reference: workboard.IssueReference
    completion: workboard.ParentCompletion
    last_child: bool


def _parent_body_finding(reference: workboard.IssueReference, parsed: body.ParsedBody) -> str:
    """Why a malformed parent body refuses the last-child rule before its
    `Next` line is ever consulted."""
    defect = parsed.contract.defects[0]
    return f"has parent {reference} with a {body.body_defect_text(defect)}"


def _parent_reference_defect(
    parent: workboard.ParentIssue, repository: str
) -> workboard.ClassificationDefect | None:
    """Whether the parent itself is even a same-repository container --
    checked before its body is read at all."""
    if parent.reference.repository != repository:
        return workboard.ClassificationDefect(
            f"has parent {parent.reference} in another repository, "
            "whose children this check cannot read"
        )
    if parent.kind is not body.ItemKind.CONTAINER:
        kind_text = parent.kind.value if parent.kind is not None else "unknown"
        return workboard.ClassificationDefect(
            f"has parent {parent.reference} of kind {kind_text}, which is not a "
            "container; only a container holds children"
        )
    return None


def _parent_requirement(
    context: LandingCheckContext,
    item: workboard.IssueReference,
) -> _ParentRequirement | workboard.ClassificationDefect | None:
    """The parent's demand, read from GitHub's sub-issue relation and its
    body under the repository's own pin.

    Closing a parent's last open child completes the parent only when the
    parent holds no uncut `[[slice]]` row and its own `Next` line names no
    further work; with only `Next` work left, the landing may close the
    parent (its one remaining child) but need not. A parent keeping other
    open children stays open, and must say what happens next.
    """
    parent = context.client.parent_issue(item.number)
    if parent is None:
        return None
    reference_defect = _parent_reference_defect(parent, context.repository)
    if reference_defect is not None:
        return reference_defect
    parsed_parent = body.parse_body(parent.body, storage=context.storage)
    if parsed_parent.read_state is not body.BodyReadState.VALID:
        return workboard.ClassificationDefect(_parent_body_finding(parent.reference, parsed_parent))
    remaining = tuple(
        child
        for child in context.client.list_children(parent.reference.number)
        if child.state is workboard.ChildState.OPEN and child.number != item.number
    )
    completion = workboard.parent_completion(parsed_parent)
    if not remaining:
        return _ParentRequirement(parent.reference, completion, True)
    if not parsed_parent.contract.next:
        children = "child" if len(remaining) == 1 else "children"
        return workboard.ClassificationDefect(
            f"leaves parent {parent.reference} open with {len(remaining)} other open "
            f"{children}, whose body carries no Next line"
        )
    return _ParentRequirement(parent.reference, completion, False)


def _parent_closing_defect(
    closing: frozenset[workboard.IssueReference],
    requirement: _ParentRequirement | None,
) -> workboard.ClassificationDefect | None:
    """Whether closing the parent, or leaving it open, contradicts its body (LAND-21, LAND-79)."""
    if requirement is None:
        return None
    parent_closed = requirement.reference in closing
    if parent_closed and requirement.completion is workboard.ParentCompletion.FORBIDDEN:
        return workboard.ClassificationDefect(
            f"closes parent {requirement.reference} although its body still holds "
            "an uncut slice row; cut it or delete the row first"
        )
    if (
        requirement.last_child
        and requirement.completion is workboard.ParentCompletion.REQUIRED
        and not parent_closed
    ):
        return workboard.ClassificationDefect(
            f"closes the last open child of parent {requirement.reference}; close the parent too"
        )
    return None


def _closing_defect(
    detail: forge.Landing,
    repository: str,
    item: workboard.IssueReference,
    requirement: _ParentRequirement | None,
) -> workboard.ClassificationDefect | None:
    """Which issues this landing must close, and that it closes nothing else."""
    closing = workboard.closing_references(detail.body, repository)
    if item not in closing:
        return workboard.ClassificationDefect(
            f"carries no closing reference for its work item {item}"
        )
    parent_defect = _parent_closing_defect(closing, requirement)
    if parent_defect is not None:
        return parent_defect
    permitted_parent = (
        {requirement.reference} if requirement is not None and requirement.last_child else set()
    )
    besides = tuple(sorted(closing - {item} - permitted_parent, key=str))
    if besides:
        named = ", ".join(str(reference) for reference in besides)
        return workboard.ClassificationDefect(
            f"closes {named} besides its work item {item}; a pull request lands one item"
        )
    return None


def _work_item_defect(
    context: LandingCheckContext,
    claims: tuple[protocol.ActiveClaim, ...],
    detail: forge.Landing,
    item: workboard.IssueReference,
) -> workboard.ClassificationDefect | None:
    """Why this repository does not accept `item` as the landing pull request's work item."""
    if item.repository != context.repository:
        return workboard.ClassificationDefect(
            f"names work item {item} of another repository, which holds no claim here"
        )
    claim_defect = _claim_defect(claims, detail, protocol.IssueIdentity(item.number))
    if claim_defect is not None:
        return claim_defect
    requirement = _parent_requirement(context, item)
    if isinstance(requirement, workboard.ClassificationDefect):
        return requirement
    return _closing_defect(detail, context.repository, item, requirement)


def cross_repository_defect(
    repository: str, detail: forge.Landing
) -> workboard.ClassificationDefect | None:
    """Why a pull request from another repository's branch is never classified (LAND-12)."""
    if detail.source_repository.path != repository:
        return workboard.ClassificationDefect(
            f"proposes a branch of {detail.source_repository}; cross-repository pull "
            "requests are not classified"
        )
    return None


def unsafe_head_branch_defect(detail: forge.Landing) -> workboard.ClassificationDefect | None:
    """Why a pull request with an unsafe head branch name is never acted on (ADOPT-17)."""
    if not protocol.is_safe_branch_name(detail.source_branch):
        return workboard.ClassificationDefect(
            f"head branch {detail.source_branch!r} is no safe branch name"
        )
    return None


def _target_branch_defect(
    context: LandingCheckContext, detail: forge.Landing
) -> workboard.ClassificationDefect | None:
    default_branch = context.run.default_branch
    if detail.target_branch != default_branch:
        return workboard.ClassificationDefect(
            f"targets {detail.target_branch!r}, not the default branch {default_branch!r}"
        )
    return None


def structural_classification(
    context: LandingCheckContext, detail: forge.Landing
) -> workboard.Classification | workboard.ClassificationDefect:
    """The classification `check <pr>` and `land` both start from: whether this pull request's own
    shape -- its source repository,
    its `Work-Item:`/`No-Item:` line, its target branch -- names one item at
    all. Never touches a claim, a parent, or a closing reference: `land`'s
    own preflight checks the named item's live open state between this and
    `classification_defect` (LANDCMD-08 before claim validation)."""
    cross_repository = cross_repository_defect(context.repository, detail)
    if cross_repository is not None:
        return cross_repository
    classification = workboard.parse_pull_request_classification(detail.body, context.repository)
    if isinstance(classification, workboard.ClassificationDefect):
        return classification
    target_branch = _target_branch_defect(context, detail)
    if target_branch is not None:
        return target_branch
    return classification


def classification_defect(
    context: LandingCheckContext,
    claims: tuple[protocol.ActiveClaim, ...],
    detail: forge.Landing,
    classification: workboard.Classification,
    *,
    expected_head: str,
) -> workboard.ClassificationDefect | None:
    """Whether `classification`'s own claim, parent, and closing rules hold: the second half of
    `cmd_check._checked_classification`, split out so
    a caller needing a live-store read only for this half (`land`'s own
    preflight, which fetches store state no earlier than this) never pays
    for one just to read the pull request's own shape."""
    if isinstance(classification, workboard.NoItemClassification):
        return _no_item_defect(context, claims, detail, classification.kind, expected_head)
    return _work_item_defect(context, claims, detail, classification.item)


@dataclass(frozen=True)
class AdoptionRequest:
    number: int
    kind: workboard.NoItemKind
    agent: str
    role: str


@dataclass(frozen=True)
class FreshAdoption:
    """What `adoption_preflight` proved adoptable: the claim's scope (LAND-74's
    path set) and the head it was judged at."""

    scope: tuple[str, ...]
    expected_head: str


@dataclass(frozen=True)
class HolderResume:
    """The branch's one live claim is the asking session's own builder lane
    claim: its rerun resumes it (ADOPT-26)."""

    claim: protocol.ActiveClaim


@dataclass(frozen=True)
class AdoptionRefusal:
    sentence: str


def _adoption_refusal(number: int, defect: workboard.ClassificationDefect) -> AdoptionRefusal:
    return AdoptionRefusal(f"pull request #{number} {defect.message}")


def _is_resumable_claim(claim: protocol.ActiveClaim, agent: str, role: str) -> bool:
    return isinstance(claim.identity, protocol.LaneIdentity) and protocol.held_by(
        claim, agent, role
    )


def adoption_holder(
    claims: Mapping[str, protocol.ActiveClaim],
    branch: str,
    storage: body.Storage,
    agent: str,
    role: str,
) -> AdoptionRefusal | HolderResume | None:
    """ADOPT-06, ADOPT-26, ADOPT-32: a live claim on the head branch refuses,
    naming the first claim that is not `agent`'s own lane claim as `role`; that
    one claim, alone there, is the holder's to resume."""
    holders = protocol.branch_holders(claims, branch)
    if not holders:
        return None
    foreign = next(
        (claim for claim in holders if not _is_resumable_claim(claim, agent, role)), None
    )
    if foreign is None:
        return HolderResume(holders[0])
    return AdoptionRefusal(
        protocol.claimed_by_sentence(
            protocol.LaneIdentity(), branch, foreign, workboard.item_labeller(storage)
        )
    )


def _line_defect(
    body_text: str, state: workboard.ClassificationLineState, *, resumed: bool
) -> workboard.ClassificationDefect | None:
    """ADOPT-05, ADOPT-30: adopt never changes a classification line; only a
    resumed rerun keeps its own."""
    if state is workboard.ClassificationLine.ABSENT or (
        resumed and state is workboard.ClassificationLine.PRESENT
    ):
        return None
    if resumed and isinstance(state, workboard.MalformedClassificationLines):
        return workboard.ClassificationDefect(
            f"{state.defect.message}; adopt never changes a classification line"
        )
    live_line = (
        state.line
        if isinstance(state, workboard.OtherClassificationLine)
        else workboard.live_classification_line(body_text)
    )
    return workboard.ClassificationDefect(
        f"already carries {live_line}; adopt never changes a classification line"
    )


def adoption_body(
    context: LandingCheckContext,
    detail: forge.Landing,
    kind: workboard.NoItemKind,
    *,
    resumed: bool,
) -> workboard.ClassificationDefect | str | None:
    """The one decider of what `aco adopt` writes: the body it leaves on the
    pull request, `None` when `detail.body` already reads as adopt leaves it
    (a resumed rerun keeps its own line, ADOPT-26), or why it is no issue-less
    landing: it already carries a classification line (ADOPT-05), it would not
    read `No-Item: <kind>` once the line is added (ADOPT-11), it targets
    another branch than the default (ADOPT-04), or it closes an item
    (ADOPT-07)."""
    state = workboard.classification_line_state(detail.body, kind, context.repository)
    line_defect = _line_defect(detail.body, state, resumed=resumed)
    if line_defect is not None:
        return line_defect
    prospective = (
        detail.body
        if state is workboard.ClassificationLine.PRESENT
        else workboard.body_with_classification(detail.body, kind)
    )
    classification = workboard.parse_pull_request_classification(prospective, context.repository)
    if isinstance(classification, workboard.ClassificationDefect):
        return workboard.ClassificationDefect(
            f"body would not read No-Item: {kind} with the line added: {classification.message}"
        )
    defect = _target_branch_defect(context, detail) or closing_reference_defect(
        prospective, context.repository
    )
    if defect is not None:
        return defect
    return None if state is workboard.ClassificationLine.PRESENT else prospective


def _adoption_scope(
    context: LandingCheckContext, detail: forge.Landing, kind: workboard.NoItemKind
) -> workboard.ClassificationDefect | frozenset[str]:
    """The listing's path set when the dependency rule (`deps`) and the
    listing's own completeness (LAND-73, LAND-75, LAND-76) hold and it names
    a file (ADOPT-16); the listing is read once, and only past the
    configuration check."""

    @cache
    def listing() -> workboard.ClassificationDefect | frozenset[str]:
        return listed_paths(context.client.pull_request_changes(detail.number), detail.head_sha)

    if kind is workboard.NoItemKind.DEPS:
        dependency_defect = dependency_rule_defect(context.run.config, listing)
        if dependency_defect is not None:
            return dependency_defect
    listed = listing()
    if not listed:
        return workboard.ClassificationDefect("changes no file; there is nothing to adopt")
    return listed


def _judged_scope(
    context: LandingCheckContext,
    detail: forge.Landing,
    kind: workboard.NoItemKind,
    *,
    resumed: bool,
) -> workboard.ClassificationDefect | frozenset[str]:
    """The listing's path set, once the body adopt would leave passes its own
    checks: the listing is read only past them."""
    left_body = adoption_body(context, detail, kind, resumed=resumed)
    if isinstance(left_body, workboard.ClassificationDefect):
        return left_body
    return _adoption_scope(context, detail, kind)


def adoption_preflight(
    context: LandingCheckContext,
    request: AdoptionRequest,
    detail: forge.Landing,
    reference: forge.ItemReference,
    claims_provider: Callable[[], protocol.ClaimState],
) -> FreshAdoption | HolderResume | AdoptionRefusal:
    """Every refusal of `aco adopt` that comes before its build, in the one
    order of `specs/adopt.spec.md`: the first failing step wins. `detail` and
    `reference` are the caller's reads; the claims are read once, only past
    the pull request's own openness and repository, and the listing only past
    the body's checks, as `cmd_land._land_preflight` orders its reads. The
    holder's rerun (ADOPT-26) is judged by the same steps on the body it
    would leave (ADOPT-31)."""
    if reference.state is not forge.ItemState.OPEN:
        return AdoptionRefusal(f"pull request #{request.number} is not open; it cannot be adopted")
    cross_repository = cross_repository_defect(context.repository, detail)
    if cross_repository is not None:
        return _adoption_refusal(request.number, cross_repository)
    holder = adoption_holder(
        claims_provider().claims, detail.source_branch, context.storage, request.agent, request.role
    )
    if isinstance(holder, AdoptionRefusal):
        return holder
    scope = _judged_scope(context, detail, request.kind, resumed=holder is not None)
    if isinstance(scope, workboard.ClassificationDefect):
        return _adoption_refusal(request.number, scope)
    if holder is not None:
        return holder
    return FreshAdoption(tuple(sorted(scope)), detail.head_sha)
