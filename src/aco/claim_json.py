"""The `--json` views of one claim that `claim`, `status`, `rescope` and `release` share."""

from .protocol import (
    ActiveClaim,
    ClaimIdentity,
    LaneIdentity,
    ResourceHold,
    ScopedClaim,
)


def touch_json(claim: ScopedClaim) -> dict[str, object]:
    return {
        **identity_json(claim.identity),
        "claim_id": claim.claim_id,
        "agent": claim.agent,
        "scope": list(claim.scope),
    }


def identity_json(identity: ClaimIdentity) -> dict[str, object]:
    """`issue`/`lane` pair for one claim's discriminated identity, for JSON output.

    A lane claim's name lives in the sibling `branch` field of the same JSON
    object, so `lane` stays a bare marker instead of duplicating it.
    """
    if isinstance(identity, LaneIdentity):
        return {"issue": None, "lane": True}
    return {"issue": identity.issue, "lane": None}


def resource_fields(resource: ResourceHold | None) -> dict[str, object]:
    if resource is None:
        return {"resource": None, "resource_value": None}
    return {"resource": resource.name, "resource_value": resource.value}


def claim_identity_fields(claim: ActiveClaim) -> dict[str, object]:
    """The one claim-identity dict every `--json` view of a live claim
    shares -- `status`, `status --path`, `claim`, and `rescope`
    each spread this instead of typing the same seven
    fields out by hand a fifth time with their own drifting order. A view
    still projects its own remaining fields explicitly beside it: `resource`/
    `resource_value` (every view but `rescope`, which names no `--resource`
    flag of its own), `whole` (`status` and `status --path` alone), and
    whatever else is that view's own (`overlaps`/`age`/`old` for `status`,
    `versioned_files`/`touches`/`checks` for `claim`)."""
    return {
        **identity_json(claim.identity),
        "claim_id": claim.claim_id,
        "agent": claim.agent,
        "role": claim.role,
        "base": claim.base,
        "branch": claim.branch,
        "scope": list(claim.scope),
    }
