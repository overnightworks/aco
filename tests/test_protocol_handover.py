"""`protocol.apply` of a `HandoverIntent`: the holder changes, nothing else does, and a
claim that is not there or not held by the named agent is refused before any change."""

from dataclasses import replace
from types import MappingProxyType

import pytest
from board_fixtures import standing_active_claim

from aco import protocol

HELD = standing_active_claim("Ada", claim_id="held")
STATE = protocol.ClaimState(
    tip=protocol.ObjectId("a" * 40),
    claims=MappingProxyType({protocol.claim_key(HELD.identity, HELD.branch): HELD}),
)


def _handover(*, claim_id: str = "held", previous_agent: str = "Ada") -> protocol.HandoverIntent:
    return protocol.HandoverIntent(
        claim_id=protocol.ClaimId(claim_id),
        previous_agent=previous_agent,
        agent="Grace",
        operation_id="handover-op",
    )


def test_a_handover_changes_the_holder_and_nothing_else_of_the_claim() -> None:
    applied = protocol.apply(STATE, _handover())

    [claim] = applied.claims.values()
    assert claim == replace(HELD, agent="Grace")


@pytest.mark.parametrize(
    ("intent", "match"),
    [
        pytest.param(
            _handover(claim_id="other"), "has no active claim to hand over", id="no-such-claim"
        ),
        pytest.param(
            _handover(previous_agent="Bob"),
            "held by 'Ada', not by 'Bob'",
            id="not-held-by-the-named-agent",
        ),
    ],
)
def test_a_refused_handover_leaves_the_claim_as_it_stood(
    intent: protocol.HandoverIntent, match: str
) -> None:
    with pytest.raises(protocol.ClaimUnavailableError, match=match):
        protocol.apply(STATE, intent)

    assert tuple(STATE.claims.values()) == (HELD,)
