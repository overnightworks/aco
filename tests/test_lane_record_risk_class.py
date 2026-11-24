"""A landing needs a lane record that names its risk class: the judgement `aco land` makes of a
record file before it merges anything (`specs/lane-record.spec.md`, "What a landing needs")."""

import pytest
from lane_record_runs_world import record_stating

from aco import lane_record, protocol

REVIEWED = "a" * 40
APPROVAL = [{"stage": "review", "verdict": "approve", "sha": REVIEWED}]
NO_RISK = "the lane record states no risk class; record risk as material or normal"
NO_VERDICT = "the lane record states no review or gate verdict, so it judged no head to land"


def refusal_of(record: lane_record.LaneRecordFile) -> str:
    with pytest.raises(protocol.ClaimUnavailableError) as refusal:
        lane_record.require_landable_record(record, REVIEWED)
    return str(refusal.value)


@pytest.mark.parametrize("risk", ["material", "normal"])
def test_a_record_naming_a_risk_class_and_approving_the_head_is_landable(risk: str) -> None:
    """Spec: LANREC-99."""
    record = record_stating(verdicts=APPROVAL, risk=risk)

    lane_record.require_landable_record(record, REVIEWED)


def test_a_record_stating_no_risk_class_refuses() -> None:
    """Spec: LANREC-99."""
    record = record_stating(verdicts=APPROVAL, risk=None)

    assert refusal_of(record) == NO_RISK


def test_a_record_without_a_verdict_and_without_a_risk_class_refuses_for_the_verdict() -> None:
    """Spec: LANREC-39, LANREC-99."""
    record = record_stating(verdicts=[], risk=None)

    assert refusal_of(record) == NO_VERDICT
