"""The `status` command (`specs/status.spec.md`)."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from . import (
    board_read,
    body,
    protocol,
    report,
    workboard,
)
from .session import (
    LaneSharedReading,
    LaneSharedUnavailable,
    RunContext,
    lane_shared_files,
    trunk_lane_shared_reading,
)


def _status_claims(
    claims: tuple[protocol.ActiveClaim, ...], issue: int | None
) -> tuple[tuple[protocol.ActiveClaim, ...], protocol.ClaimConflictIndex]:
    selected = tuple(
        claim
        for claim in claims
        if issue is None
        or (isinstance(claim.identity, protocol.IssueIdentity) and claim.identity.issue == issue)
    )
    index = protocol.claim_conflict_index(claims)
    if not selected:
        return (), index
    related_ids = (
        {claim.claim_id for claim in claims}
        if issue is None
        else protocol.related_claim_ids(index, selected)
    )
    related = tuple(claim for claim in claims if claim.claim_id in related_ids)
    return related, index


def _overlap_subjects(
    claims_by_id: Mapping[str, protocol.ActiveClaim], peer_ids: set[str]
) -> list[dict[str, object]]:
    return [
        {
            **protocol.identity_json(peer.identity),
            "claim_id": peer.claim_id,
            "agent": peer.agent,
        }
        for claim_id in sorted(peer_ids)
        if (peer := claims_by_id.get(claim_id)) is not None
    ]


def _overlap_note(
    claims_by_id: Mapping[str, protocol.ActiveClaim], peer_ids: set[str], storage: body.Storage
) -> str | None:
    peers = [claims_by_id[claim_id] for claim_id in sorted(peer_ids) if claim_id in claims_by_id]
    if not peers:
        return None
    return "overlaps " + ", ".join(
        f"{workboard.claim_subject(claim, storage)} ({claim.claim_id})" for claim in peers
    )


@dataclass(frozen=True)
class _ClaimReportContext:
    """`index` and `storage` together (issue #292): the two facts every
    claim in one `status` read shares -- bundled so adding `storage`
    beside the pre-existing `index` never pushes a caller past PLR0913's
    five-argument ceiling."""

    index: protocol.ClaimConflictIndex
    storage: body.Storage


def _print_claim_status_lines(
    claim: protocol.ActiveClaim,
    claims_by_id: Mapping[str, protocol.ActiveClaim],
    context: _ClaimReportContext,
    opened_at: datetime,
    observed_at: datetime,
) -> None:
    state = "CONFLICT" if claim.claim_id in context.index.conflict_ids else "CLAIMED"
    print(
        f"{state} {workboard.claim_subject(claim, context.storage)}: {claim.agent} ({claim.role}) "
        f"base={claim.base} branch={claim.branch} claim={claim.claim_id}"
        f"{workboard.claim_age_suffix(opened_at, observed_at)}"
    )
    for path in claim.scope:
        print(f"  {path}")
    if claim.resource is not None:
        print(f"  resource {claim.resource.name}={claim.resource.value}")
    if claim.whole_reason is not None:
        print(f"  whole: {claim.whole_reason}")
    note = _overlap_note(
        claims_by_id, protocol.overlap_peer_ids(context.index, claim), context.storage
    )
    if note is not None:
        print(f"  {note}")


def _print_related_claims(
    claims: tuple[protocol.ActiveClaim, ...],
    related: tuple[protocol.ActiveClaim, ...],
    context: _ClaimReportContext,
    ages: Mapping[str, datetime],
    observed_at: datetime,
) -> int:
    claims_by_id: dict[str, protocol.ActiveClaim] = {claim.claim_id: claim for claim in claims}
    for claim in related:
        _print_claim_status_lines(claim, claims_by_id, context, ages[claim.claim_id], observed_at)
    return 2 if any(claim.claim_id in context.index.conflict_ids for claim in related) else 0


def _status(
    claims: tuple[protocol.ActiveClaim, ...],
    issue: int | None,
    ages: Mapping[str, datetime],
    storage: body.Storage,
    lane_shared: LaneSharedReading = (),
) -> int:
    """Every related claim's block, then the lane-shared files once (issue
    #575), named only beside a claim that may write them."""
    observed_at = datetime.now(UTC)
    related, index = _status_claims(claims, issue)
    if related:
        context = _ClaimReportContext(index, storage)
        exit_code = _print_related_claims(claims, related, context, ages, observed_at)
        shared = lane_shared_line(lane_shared)
        if shared is not None:
            print(shared)
        return exit_code
    subject = "repository" if issue is None else f"issue {workboard.item_label(issue, storage)}"
    print(f"UNCLAIMED {subject}")
    return 0


class _StatusReason(StrEnum):
    """`aco status`'s own `--json` `reason` vocabulary (issue #406,
    `specs/status.spec.md` STAT-03/STAT-05): `claimed`, `unclaimed`, and
    `conflict` are its own three read states. `status` is forge-free
    (STAT-16) and never resolves a repository target, so it names no
    `invalid_usage` of its own -- only `unavailable`, reached when
    `store.fetch_state` refuses a rewritten or malformed state ref."""

    CLAIMED = "claimed"
    UNCLAIMED = "unclaimed"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


def _status_claim_json(
    claim: protocol.ActiveClaim,
    claims_by_id: Mapping[str, protocol.ActiveClaim],
    index: protocol.ClaimConflictIndex,
    ages: Mapping[str, datetime],
    observed_at: datetime,
) -> dict[str, object]:
    age, old = workboard.claim_age_fields(ages[claim.claim_id], observed_at)
    return {
        **protocol.claim_identity_fields(claim),
        **protocol.resource_fields(claim.resource),
        **({"whole": claim.whole_reason} if claim.whole_reason is not None else {}),
        "overlaps": _overlap_subjects(claims_by_id, protocol.overlap_peer_ids(index, claim)),
        "state": "CONFLICT" if claim.claim_id in index.conflict_ids else "CLAIMED",
        "age": age,
        "old": old,
    }


def _status_json(
    claims: tuple[protocol.ActiveClaim, ...],
    issue: int | None,
    ages: Mapping[str, datetime],
    tip: protocol.ObjectId | None,
    lane_shared: LaneSharedReading = (),
) -> int:
    observed_at = datetime.now(UTC)
    related, index = _status_claims(claims, issue)
    if not related:
        reason = _StatusReason.UNCLAIMED
    elif any(claim.claim_id in index.conflict_ids for claim in related):
        reason = _StatusReason.CONFLICT
    else:
        reason = _StatusReason.CLAIMED
    claims_by_id: dict[str, protocol.ActiveClaim] = {claim.claim_id: claim for claim in claims}
    claims_payload = [
        _status_claim_json(claim, claims_by_id, index, ages, observed_at) for claim in related
    ]
    report.emit_json(
        reason is not _StatusReason.CONFLICT,
        reason,
        issue=issue,
        tip=tip,
        claims=claims_payload,
        **lane_shared_json(lane_shared),
    )
    return 2 if reason is _StatusReason.CONFLICT else 0


def _status_path(
    claims: tuple[protocol.ActiveClaim, ...],
    path: str,
    storage: body.Storage,
    lane_shared: LaneSharedReading,
) -> None:
    """`path`'s holders; with none, `LANE-SHARED` for a file the trunk's
    `lane_shared` names, which any claim may write (issue #586), else
    `UNCLAIMED`. A defective trunk configuration adds its own line."""
    holders = protocol.claims_holding_path(claims, path)
    if holders:
        _print_path_holders(holders, path, storage)
    elif path in lane_shared_files(lane_shared):
        print(f"LANE-SHARED {path}")
    else:
        print(f"UNCLAIMED {path}")
    if isinstance(lane_shared, LaneSharedUnavailable):
        print(_lane_shared_unavailable_line(lane_shared))


def _print_path_holders(
    holders: tuple[protocol.ActiveClaim, ...], path: str, storage: body.Storage
) -> None:
    for claim in holders:
        print(
            f"CLAIMED {path} {workboard.claim_subject(claim, storage)}: "
            f"{claim.agent} ({claim.role}) "
            f"claim={claim.claim_id}"
        )
        if claim.whole_reason is not None:
            print(f"  whole: {claim.whole_reason}")
    if len(holders) > 1:
        print(
            "overlap: "
            + ", ".join(
                f"{workboard.claim_subject(claim, storage)} ({claim.claim_id})" for claim in holders
            )
        )


def _lane_shared_unavailable_line(unavailable: LaneSharedUnavailable) -> str:
    return f"lane-shared: unavailable ({unavailable.defect})"


def lane_shared_line(lane_shared: LaneSharedReading) -> str | None:
    """The one line `status` and `brief` name the repository's lane-shared
    registry files with (issue #575), so a builder comparing its changes
    with its claim scope counts them as allowed: an entry naming no file the
    trunk tracks is marked so, never shown as a grant, and a defective trunk
    configuration names its defect (issue #586); `None` when none is
    configured."""
    if isinstance(lane_shared, LaneSharedUnavailable):
        return _lane_shared_unavailable_line(lane_shared)
    if not lane_shared:
        return None
    return "lane-shared: " + ", ".join(
        entry.path if entry.names_a_file else f"{entry.path} (names no file)"
        for entry in lane_shared
    )


def lane_shared_json(lane_shared: LaneSharedReading) -> dict[str, object]:
    """`lane_shared` and `lane_shared_unavailable`, the `--json` form of
    `lane_shared_line` (issue #586): the entries with whether each names a
    trunk-tracked file, or `null` beside the defect that hides them."""
    if isinstance(lane_shared, LaneSharedUnavailable):
        return {"lane_shared": None, "lane_shared_unavailable": lane_shared.defect}
    return {
        "lane_shared": [
            {"path": entry.path, "names_a_file": entry.names_a_file} for entry in lane_shared
        ],
        "lane_shared_unavailable": None,
    }


def _status_path_json(
    claims: tuple[protocol.ActiveClaim, ...], path: str, lane_shared: LaneSharedReading
) -> int:
    holders = protocol.claims_holding_path(claims, path)
    reason = _StatusReason.UNCLAIMED if not holders else _StatusReason.CLAIMED
    claims_payload = [
        {
            **protocol.claim_identity_fields(claim),
            **protocol.resource_fields(claim.resource),
            **({"whole": claim.whole_reason} if claim.whole_reason is not None else {}),
            "state": "CLAIMED",
        }
        for claim in holders
    ]
    report.emit_json(
        True, reason, path=path, claims=claims_payload, **lane_shared_json(lane_shared)
    )
    return 0


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`status` reads live claims from the store directly (issue #176),
    routed by `cli._COMMANDS` without forge resolution (a cut-over
    repository may have no ledger issue left at all).
    It is forge-free (issue #245): `--repo` is meaningless here and unused.
    Every `protocol.ClaimError` `_status_read` can raise -- a rewritten or
    malformed state ref -- reports through `report.refuse` as `unavailable` (issue
    #406): `status` names no `invalid_usage` of its own (see `_StatusReason`).
    """
    try:
        return _status_read(parsed, context)
    except protocol.ClaimError as error:
        return report.refuse(_StatusReason.UNAVAILABLE, error, as_json=parsed.json)


def _status_read(parsed: argparse.Namespace, context: RunContext) -> int:
    worktree = context.toplevel
    state = context.observation
    claims = tuple(state.claims.values())
    lane_shared = trunk_lane_shared_reading(context.configured_canonical_remote, context.toplevel)
    if parsed.path is not None:
        # `--path` prints no age, so it never reads a claim's ancestry: a
        # lineage break in one unrelated claim must not stop this answer
        # (README "status --path").
        if parsed.json:
            return _status_path_json(claims, parsed.path, lane_shared)
        _status_path(claims, parsed.path, context.config.storage, lane_shared)
        return 0
    ages = board_read.claim_ages(worktree, state)
    issue = protocol.optional_issue_number(parsed.issue)
    if parsed.json:
        return _status_json(claims, issue, ages, state.tip, lane_shared)
    return _status(claims, issue, ages, context.config.storage, lane_shared)
