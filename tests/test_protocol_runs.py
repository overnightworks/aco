"""`protocol.apply` of the stored runs: the write intent's rules (a live claim, its holder, the
runs file the writer read) and what the release, the landing, the handover and the rescope do
to a claim's runs file (CAS-81..CAS-85, LANREC-61, LANREC-67, LANREC-92, HANDOVER-15, REL-68)."""

from dataclasses import replace
from functools import partial

import pytest
from lane_record_runs_world import stale_runs_sentence
from store_fixtures import STATE_WITH_TIP, claim_intent

from aco import protocol

CLAIM_ID = protocol.ClaimId("a1")
OTHER_CLAIM_ID = protocol.ClaimId("b2")
FIRST_OID = protocol.ObjectId("d" * 40)
SECOND_OID = protocol.ObjectId("e" * 40)
THIRD_OID = protocol.ObjectId("f" * 40)
ITEM_ID = "aco-000001"
ITEM_OID = protocol.ObjectId("1" * 40)
ITEM_NEW_OID = protocol.ObjectId("2" * 40)
LANDED_COMMIT = protocol.ObjectId("3" * 40)
STALE_SENTENCE = "the runs were written since this command read them"


def holder_sentence(session: str, holder: str) -> str:
    return f"{session} may not write: held by {holder}"


def runs_intent(
    *,
    claim_id: protocol.ClaimId = CLAIM_ID,
    agent: str = "Ada",
    expected: protocol.ObjectId | None = None,
    new_oid: protocol.ObjectId = FIRST_OID,
) -> protocol.RunsWriteIntent:
    return protocol.RunsWriteIntent(
        claim_id=claim_id,
        agent=agent,
        expected=expected,
        new_oid=new_oid,
        operation_id="op-runs",
        holder_refusal=partial(holder_sentence, agent),
        stale_refusal=STALE_SENTENCE,
    )


def claimed_state() -> protocol.ClaimState:
    return protocol.apply(STATE_WITH_TIP, claim_intent())


def landing_intent(
    expected_runs: protocol.ObjectId | None = None,
) -> protocol.LandingIntent:
    return protocol.LandingIntent(
        item_id=ITEM_ID,
        item_expected=ITEM_OID,
        item_new_oid=ITEM_NEW_OID,
        claim_id=CLAIM_ID,
        agent="Ada",
        role="builder",
        outcome=protocol.LandedRelease(LANDED_COMMIT),
        operation_id="op-landing",
        expected_runs=expected_runs,
    )


def release_intent(expected_runs: protocol.ObjectId | None = None) -> protocol.ReleaseIntent:
    return protocol.ReleaseIntent(
        claim_id=CLAIM_ID,
        agent="Ada",
        role="builder",
        outcome=protocol.AbandonedRelease("stopped"),
        operation_id="op-release",
        expected_runs=expected_runs,
    )


def release_or_landing(
    kind: str, expected_runs: protocol.ObjectId | None
) -> protocol.ReleaseIntent | protocol.LandingIntent:
    return release_intent(expected_runs) if kind == "release" else landing_intent(expected_runs)


def test_a_write_by_the_holder_stores_the_runs_file_under_the_claim_id() -> None:
    written = protocol.apply(claimed_state(), runs_intent())

    assert dict(written.runs) == {CLAIM_ID: FIRST_OID}


def test_a_write_replaces_the_runs_file_the_writer_read() -> None:
    first = protocol.apply(claimed_state(), runs_intent())

    second = protocol.apply(first, runs_intent(expected=FIRST_OID, new_oid=SECOND_OID))

    assert dict(second.runs) == {CLAIM_ID: SECOND_OID}


def test_a_write_changes_no_claim() -> None:
    before = claimed_state()

    written = protocol.apply(before, runs_intent())

    assert dict(written.claims) == dict(before.claims)


def test_a_write_for_a_claim_id_that_holds_no_live_claim_is_refused() -> None:
    state = claimed_state()
    intent = runs_intent(claim_id=OTHER_CLAIM_ID)

    with pytest.raises(protocol.ClaimUnavailableError, match="has no active claim"):
        protocol.apply(state, intent)


def test_a_write_by_another_agent_is_refused_with_the_intents_holder_sentence() -> None:
    state = claimed_state()
    intent = runs_intent(agent="Bea")

    with pytest.raises(protocol.ClaimUnavailableError) as refusal:
        protocol.apply(state, intent)

    assert str(refusal.value) == holder_sentence("Bea", "Ada")


@pytest.mark.parametrize(
    "stored, expected",
    [
        pytest.param(None, FIRST_OID, id="the-writer-read-a-file-none-is-stored-now"),
        pytest.param(FIRST_OID, None, id="the-writer-read-none-a-file-is-stored-now"),
        pytest.param(SECOND_OID, FIRST_OID, id="the-stored-file-is-another-than-the-one-read"),
    ],
)
def test_a_write_over_runs_that_changed_since_they_were_read_is_refused(
    stored: protocol.ObjectId | None, expected: protocol.ObjectId | None
) -> None:
    state = claimed_state()
    if stored is not None:
        state = replace(state, runs={CLAIM_ID: stored})

    intent = runs_intent(expected=expected, new_oid=THIRD_OID)

    with pytest.raises(protocol.ClaimUnavailableError) as refusal:
        protocol.apply(state, intent)

    assert str(refusal.value) == STALE_SENTENCE


def test_a_write_carries_the_runs_file_of_a_claim_id_that_holds_no_live_claim() -> None:
    state = replace(claimed_state(), runs={OTHER_CLAIM_ID: SECOND_OID})

    written = protocol.apply(state, runs_intent())

    assert dict(written.runs) == {OTHER_CLAIM_ID: SECOND_OID, CLAIM_ID: FIRST_OID}


def with_runs() -> protocol.ClaimState:
    return replace(claimed_state(), runs={CLAIM_ID: FIRST_OID, OTHER_CLAIM_ID: SECOND_OID})


def test_a_release_drops_the_runs_file_of_the_released_claim_only() -> None:
    released = protocol.apply(with_runs(), release_intent(FIRST_OID))

    assert dict(released.runs) == {OTHER_CLAIM_ID: SECOND_OID}
    assert CLAIM_ID not in {claim.claim_id for claim in released.claims.values()}


def test_a_landing_drops_the_runs_file_of_the_landed_claim_only() -> None:
    state = replace(with_runs(), items={ITEM_ID: ITEM_OID})

    landed = protocol.apply(state, landing_intent(FIRST_OID))

    assert dict(landed.runs) == {OTHER_CLAIM_ID: SECOND_OID}


def test_a_release_of_a_claim_with_no_runs_file_leaves_the_runs_as_they_are() -> None:
    state = replace(claimed_state(), runs={OTHER_CLAIM_ID: SECOND_OID})

    released = protocol.apply(state, release_intent())

    assert dict(released.runs) == {OTHER_CLAIM_ID: SECOND_OID}


@pytest.mark.parametrize("kind", ["release", "landing"])
@pytest.mark.parametrize(
    "stored, expected",
    [
        pytest.param(SECOND_OID, FIRST_OID, id="the-runs-file-changed"),
        pytest.param(FIRST_OID, None, id="a-runs-file-appeared"),
        pytest.param(None, FIRST_OID, id="the-runs-file-vanished"),
    ],
)
def test_a_release_or_landing_over_runs_that_differ_from_those_it_read_is_refused(
    kind: str, stored: protocol.ObjectId | None, expected: protocol.ObjectId | None
) -> None:
    state = replace(claimed_state(), items={ITEM_ID: ITEM_OID}, runs={})
    if stored is not None:
        state = replace(state, runs={CLAIM_ID: stored})
    intent = release_or_landing(kind, expected)

    with pytest.raises(protocol.ClaimUnavailableError) as refusal:
        protocol.apply(state, intent)

    assert str(refusal.value) == stale_runs_sentence("#42")


@pytest.mark.parametrize("kind", ["release", "landing"])
def test_a_refused_release_or_landing_names_the_item_in_the_form_its_caller_asks_for(
    kind: str,
) -> None:
    state = replace(claimed_state(), items={ITEM_ID: ITEM_OID}, runs={CLAIM_ID: SECOND_OID})
    intent = release_or_landing(kind, FIRST_OID)

    with pytest.raises(protocol.ClaimUnavailableError) as refusal:
        protocol.apply(state, intent)

    assert refusal.value.named(lambda number: f"aco-{number:06d}") == stale_runs_sentence(
        "aco-000042"
    )


@pytest.mark.parametrize("kind", ["release", "landing"])
def test_a_refused_release_or_landing_of_a_lane_claim_names_its_claim_id(kind: str) -> None:
    lane = claim_intent(identity=protocol.LaneIdentity(), branch="docs/tidy-readme")
    state = replace(
        protocol.apply(STATE_WITH_TIP, lane),
        items={ITEM_ID: ITEM_OID},
        runs={CLAIM_ID: SECOND_OID},
    )
    intent = release_or_landing(kind, FIRST_OID)

    with pytest.raises(protocol.ClaimUnavailableError) as refusal:
        protocol.apply(state, intent)

    assert refusal.value.named(lambda number: f"aco-{number:06d}") == stale_runs_sentence(CLAIM_ID)


@pytest.mark.parametrize("kind", ["release", "landing"])
def test_a_write_to_another_claims_runs_file_is_applied_over(kind: str) -> None:
    runs = {CLAIM_ID: FIRST_OID, OTHER_CLAIM_ID: THIRD_OID}
    state = replace(claimed_state(), items={ITEM_ID: ITEM_OID}, runs=runs)
    intent = release_or_landing(kind, FIRST_OID)

    applied = protocol.apply(state, intent)

    assert dict(applied.runs) == {OTHER_CLAIM_ID: THIRD_OID}


def test_a_handover_keeps_the_runs_file_and_the_new_holder_may_write() -> None:
    handover = protocol.HandoverIntent(
        claim_id=CLAIM_ID, previous_agent="Ada", agent="Bea", operation_id="op-handover"
    )

    handed_over = protocol.apply(with_runs(), handover)
    written = protocol.apply(
        handed_over, runs_intent(agent="Bea", expected=FIRST_OID, new_oid=THIRD_OID)
    )

    assert dict(handed_over.runs) == dict(with_runs().runs)
    assert written.runs[CLAIM_ID] == THIRD_OID


def test_the_previous_holder_is_refused_after_a_handover() -> None:
    handover = protocol.HandoverIntent(
        claim_id=CLAIM_ID, previous_agent="Ada", agent="Bea", operation_id="op-handover"
    )
    handed_over = protocol.apply(with_runs(), handover)

    intent = runs_intent(agent="Ada", expected=FIRST_OID)

    with pytest.raises(protocol.ClaimUnavailableError) as refusal:
        protocol.apply(handed_over, intent)

    assert str(refusal.value) == holder_sentence("Ada", "Bea")


def test_a_rescope_keeps_the_runs_file() -> None:
    rescope = protocol.RescopeIntent(
        claim_id=CLAIM_ID,
        agent="Ada",
        role="builder",
        scope=("src/other.py",),
        operation_id="op-rescope",
    )

    rescoped = protocol.apply(with_runs(), rescope)

    assert dict(rescoped.runs) == dict(with_runs().runs)


def test_the_stale_runs_sentence_names_the_item_and_the_command_to_run_again() -> None:
    assert protocol.stale_runs_sentence("#42") == stale_runs_sentence("#42")
