"""A landing needs a lane record that names its risk class: the judgement `aco land` makes of a
record file before it merges anything (`specs/lane-record.spec.md`, "What a landing needs")."""

import json

import pytest
from lane_record_fixtures import lane_record_object

from aco import lane_record, protocol

REVIEWED = "a" * 40
NO_RISK = "the lane record states no risk class; record risk as material or normal"
NO_VERDICT = "the lane record states no review or gate verdict, so it judged no head to land"


def record_stating(**changes: object) -> lane_record.LaneRecordFile:
    """The valid record file with `changes`, where a change to `None` leaves the field out."""
    approval = [{"stage": "review", "verdict": "approve", "sha": REVIEWED}]
    content = lane_record_object(**{"verdicts": approval, **changes})
    stated = {name: value for name, value in content.items() if value is not None}
    return lane_record.parse_record_file(json.dumps(stated).encode())


def refusal_of(record: lane_record.LaneRecordFile) -> str:
    with pytest.raises(protocol.ClaimUnavailableError) as refusal:
        lane_record.require_landable_record(record, REVIEWED)
    return str(refusal.value)


@pytest.mark.parametrize("risk", ["material", "normal"])
def test_a_record_naming_a_risk_class_and_approving_the_head_is_landable(risk: str) -> None:
    """Spec: LANREC-99."""
    record = record_stating(risk=risk)

    lane_record.require_landable_record(record, REVIEWED)


def test_a_record_stating_no_risk_class_refuses() -> None:
    """Spec: LANREC-99."""
    record = record_stating(risk=None)

    assert refusal_of(record) == NO_RISK


def test_a_record_without_a_verdict_and_without_a_risk_class_refuses_for_the_verdict() -> None:
    """Spec: LANREC-39, LANREC-99."""
    record = record_stating(risk=None, verdicts=[])

    assert refusal_of(record) == NO_VERDICT
