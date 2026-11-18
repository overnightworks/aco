"""The misses, risk and per-stage counts of a lane record, read back from release commits."""

import pytest

from aco.lane_record import FindingStage, LaneOutcome, LaneRecord, StageCounts, parse_record

OUTCOME_LINE = "lane_outcome: landed"


def message_of(*lines: str) -> str:
    return "\n".join(["release lane", "", OUTCOME_LINE, *lines])


def test_a_record_with_its_risk_and_stage_figures_renders_them_after_the_routing_lines() -> None:
    """Spec: LANREC-43, LANREC-50."""
    record = LaneRecord(
        LaneOutcome.LANDED,
        risk="material",
        counts={
            FindingStage.REVIEW: StageCounts(fix_rounds=1, blocking=3, misses=0),
            FindingStage.CI: StageCounts(fix_rounds=0, blocking=1, misses=None),
        },
    )

    assert record.trailers() == (
        OUTCOME_LINE,
        "lane_risk: material",
        "lane_fix_rounds_review: 1",
        "lane_fix_rounds_ci: 0",
        "lane_blocking_review: 3",
        "lane_blocking_ci: 1",
        "lane_misses_review: 0",
    )


@pytest.mark.parametrize(
    ("lines", "expected_lines"),
    [
        pytest.param(
            (
                "lane_misses_test: 0",
                "lane_blocking_ci: 2",
                "lane_fix_rounds_review: 1",
                "lane_risk: routine",
            ),
            (
                "lane_risk: routine",
                "lane_fix_rounds_review: 1",
                "lane_blocking_ci: 2",
                "lane_misses_test: 0",
            ),
            id="every-key-reads-back-by-name",
        ),
        pytest.param(
            ("lane_misses_ci: 1", "lane_misses_ci: 1", "lane_misses_test: 2"),
            ("lane_misses_test: 2",),
            id="a-repeated-line-is-unknown-and-the-others-still-read",
        ),
        pytest.param(
            ("lane_misses_ci: many", "lane_misses_gate: -1", "lane_blocking_ci: 3"),
            ("lane_blocking_ci: 3",),
            id="a-malformed-count-is-unknown-and-the-others-still-read",
        ),
        pytest.param(
            (
                "lane_misses_ci: 1000",
                "lane_fix_rounds_gate: 1000",
                "lane_blocking_test: 1000",
                "lane_blocking_ci: 999",
            ),
            ("lane_blocking_ci: 999",),
            id="a-count-above-999-is-unknown-and-the-others-still-read",
        ),
        pytest.param(
            ("lane_misses_ci:", "lane_fix_rounds_gate: 4"),
            ("lane_fix_rounds_gate: 4",),
            id="a-line-without-a-value",
        ),
        pytest.param(("lane_risk: very risky",), (), id="a-risk-with-whitespace"),
        pytest.param(("lane_risk: Routine",), (), id="a-risk-that-is-no-tag"),
        pytest.param(("lane_risk: a", "lane_risk: b"), (), id="a-repeated-risk"),
    ],
)
def test_each_key_of_a_stage_figure_reads_back_alone(
    lines: tuple[str, ...], expected_lines: tuple[str, ...]
) -> None:
    """Spec: LANREC-51."""
    record = parse_record(message_of(*lines))

    assert record is not None
    assert record.trailers() == (OUTCOME_LINE, *expected_lines)
