"""Claim conflict index: identity and path overlaps among live claims."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from aco.protocol import LANE_MARKER_KEY, LaneIdentity, ScopedClaim

IdentityKey = tuple[str, int | str]


def _identity_key(claim: ScopedClaim) -> IdentityKey:
    """Hashable index key for one claim's identity: an issue number or a lane branch.

    `LaneIdentity` instances all compare equal to each other, so indexing by
    identity alone would merge every lane into one bucket; the branch already owned
    by the claim record supplies the missing distinction without giving the
    lane name a second owner.
    """
    if isinstance(claim.identity, LaneIdentity):
        return (LANE_MARKER_KEY, claim.branch)
    return ("issue", claim.identity.issue)


@dataclass(frozen=True)
class ClaimConflictIndex:
    conflict_ids: set[str]
    overlap_ids: set[str]
    claims_by_identity: dict[IdentityKey, set[str]]
    complete_paths: dict[tuple[str, ...], set[str]]
    descendant_paths: dict[tuple[str, ...], set[str]]


def claim_conflict_index(claims: tuple[ScopedClaim, ...]) -> ClaimConflictIndex:
    """Index identities and paths once for status conflict and overlap notes."""
    conflict_ids: set[str] = set()
    overlap_ids: set[str] = set()
    claims_by_identity: dict[IdentityKey, set[str]] = {}
    complete_paths: dict[tuple[str, ...], set[str]] = {}
    descendant_paths: dict[tuple[str, ...], set[str]] = {}

    for claim in claims:
        same_identity = claims_by_identity.setdefault(_identity_key(claim), set())
        if same_identity:
            conflict_ids.add(claim.claim_id)
            conflict_ids.update(same_identity)
        same_identity.add(claim.claim_id)

        for path in claim.scope:
            parts = PurePosixPath(path).parts
            matches = set(descendant_paths.get(parts, ()))
            for length in range(1, len(parts) + 1):
                matches.update(complete_paths.get(parts[:length], ()))
            matches.discard(claim.claim_id)
            if matches:
                overlap_ids.add(claim.claim_id)
                overlap_ids.update(matches)

            complete_paths.setdefault(parts, set()).add(claim.claim_id)
            for length in range(1, len(parts) + 1):
                descendant_paths.setdefault(parts[:length], set()).add(claim.claim_id)

    return ClaimConflictIndex(
        conflict_ids,
        overlap_ids,
        claims_by_identity,
        complete_paths,
        descendant_paths,
    )


def related_claim_ids(index: ClaimConflictIndex, selected: tuple[ScopedClaim, ...]) -> set[str]:
    related = {claim.claim_id for claim in selected}
    for claim in selected:
        related.update(index.claims_by_identity[_identity_key(claim)])
        related.update(overlap_peer_ids(index, claim))
    return related


def overlap_peer_ids(index: ClaimConflictIndex, claim: ScopedClaim) -> set[str]:
    related: set[str] = set()
    for path in claim.scope:
        parts = PurePosixPath(path).parts
        related.update(index.descendant_paths.get(parts, ()))
        for length in range(1, len(parts) + 1):
            related.update(index.complete_paths.get(parts[:length], ()))
    related.discard(claim.claim_id)
    return related
