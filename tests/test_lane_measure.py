"""The figures of a group of recorded lanes, computed without git from lanes already read."""

from datetime import UTC, date, datetime

import pytest

from aco import protocol
from aco.body import Size
from aco.lane_measure import (
    Basis,
    DateRange,
    FigureName,
    ItemActuals,
    NoRange,
    RemainingWork,
    item_actuals,
    lane_prices,
    measure,
    parse_group,
    remaining_work,
)
from aco.lane_record import FindingStage, LaneOutcome, LaneRecord, RecordedLane, StageCounts
from aco.routing_line import RoutingLine

NOVEMBER = DateRange(date(2026, 11, 1), date(2026, 11, 30))


def lane_with_wall_seconds(wall_seconds: int | None) -> RecordedLane:
    released_at = int(datetime(2026, 11, 2, 12, tzinfo=UTC).timestamp())
    return RecordedLane(released_at, LaneRecord(LaneOutcome.LANDED, wall_seconds=wall_seconds))


@pytest.mark.parametrize(
    ("wall_seconds", "median", "known", "unknown"),
    [
        pytest.param([], None, 0, 0, id="no-lane"),
        pytest.param([None, None], None, 0, 2, id="no-known-value"),
        pytest.param([7], 7, 1, 0, id="one-value"),
        pytest.param([5, 1, 3], 3, 3, 0, id="an-odd-count"),
        pytest.param([2, 4, 6, 8], 5, 4, 0, id="an-even-count-with-a-whole-mean"),
        pytest.param([1, 2, None], 1.5, 2, 1, id="an-even-count-with-a-half-and-an-unknown"),
    ],
)
def test_a_figure_is_the_median_of_the_known_values_with_its_own_counts(
    wall_seconds: list[int | None], median: float | None, known: int, unknown: int
) -> None:
    """Spec: STATS-07, STATS-08, STATS-09."""
    lanes = [lane_with_wall_seconds(seconds) for seconds in wall_seconds]

    figure = measure(NOVEMBER, lanes).figures[FigureName.WALL_SECONDS]

    assert (figure.median, figure.n, figure.unknown) == (median, known, unknown)


@pytest.mark.parametrize("group", ["2026-11-01..2026-11-07", "2026-11-09..2026-11-09", "tag:a-b"])
def test_a_group_prints_as_it_was_written(group: str) -> None:
    """Spec: STATS-06."""
    assert str(parse_group(group)) == group


@pytest.mark.parametrize(
    "group",
    ["", "2026-11-01", "..", "2026-11-01..", "tag", "tag:" + "a" * 41, "2026-13-01..2026-13-02"],
)
def test_a_text_that_is_no_range_and_no_tag_is_refused(group: str) -> None:
    """Spec: STATS-05, STATS-16, STATS-17."""
    with pytest.raises(protocol.ClaimError):
        parse_group(group)


RELEASED_AT = int(datetime(2026, 11, 2, 12, tzinfo=UTC).timestamp())


def finished(
    issue: int,
    wall_seconds: int | None,
    size: Size | None = None,
    *,
    released_at: int = RELEASED_AT,
    outcome: LaneOutcome = LaneOutcome.LANDED,
) -> RecordedLane:
    record = LaneRecord(outcome, wall_seconds=wall_seconds, item_size=size)
    return RecordedLane(released_at, record, issue)


def items_of(size: Size | None, seconds: list[int], first_issue: int = 1) -> list[RecordedLane]:
    return [
        finished(first_issue + index, wall_seconds, size)
        for index, wall_seconds in enumerate(seconds)
    ]


def priced(lanes: list[RecordedLane], sizes: list[Size | None]) -> RemainingWork | NoRange:
    return remaining_work(lane_prices(lanes), sizes)


def shown(work: RemainingWork) -> tuple[int, int, int, list[tuple[Size | None, int, Basis, int]]]:
    return (
        work.low_seconds,
        work.high_seconds,
        work.items,
        [(entry.size, entry.lanes, entry.basis, entry.items) for entry in work.classes],
    )


def test_no_recorded_lane_leaves_no_range() -> None:
    """Spec: ABRD-144."""
    assert priced([], [Size.SMALL]) is NoRange.NO_RECORDS


def test_under_five_pooled_items_leave_no_range() -> None:
    """Spec: ABRD-144."""
    lanes = items_of(Size.SMALL, [60, 120, 180, 240])

    assert priced(lanes, [Size.SMALL]) is NoRange.TOO_FEW


def test_a_range_is_the_sum_of_class_medians_to_the_sum_of_class_80th_percentiles() -> None:
    """Spec: ABRD-141."""
    lanes = items_of(Size.SMALL, [100, 200, 300, 400, 500]) + items_of(
        Size.MEDIUM, [1000, 2000, 3000, 4000, 5000, 6000], first_issue=10
    )

    work = priced(lanes, [Size.SMALL, Size.MEDIUM, Size.MEDIUM])

    assert isinstance(work, RemainingWork)
    assert shown(work) == (
        300 + 2 * 3500,
        400 + 2 * 5000,
        11,
        [
            (Size.SMALL, 1, Basis.MEASURED, 5),
            (Size.MEDIUM, 2, Basis.MEASURED, 6),
        ],
    )


def test_a_class_under_five_items_and_an_unsized_lane_use_the_pooled_distribution() -> None:
    """Spec: ABRD-142, ABRD-143."""
    lanes = items_of(Size.SMALL, [10, 20, 30, 40, 50]) + items_of(
        Size.LARGE, [1000, 2000], first_issue=10
    )

    work = priced(lanes, [Size.LARGE, None])

    assert isinstance(work, RemainingWork)
    assert shown(work) == (
        2 * 40,
        2 * 1000,
        7,
        [(Size.LARGE, 1, Basis.POOLED, 7), (None, 1, Basis.POOLED, 7)],
    )


def test_an_item_is_one_sample_over_all_its_records_sized_by_its_latest_landed_one() -> None:
    """Spec: ABRD-142."""
    lanes = [
        finished(1, 100, outcome=LaneOutcome.ABANDONED),
        finished(1, 200, Size.SMALL, released_at=RELEASED_AT + 1),
        finished(1, 400, Size.LARGE, released_at=RELEASED_AT + 2),
        *items_of(Size.LARGE, [100, 200, 800, 900], first_issue=10),
    ]

    work = priced(lanes, [Size.LARGE])

    assert isinstance(work, RemainingWork)
    assert shown(work) == (700, 800, 5, [(Size.LARGE, 1, Basis.MEASURED, 5)])


@pytest.mark.parametrize(
    "unsampled",
    [
        pytest.param([finished(9, None)], id="a-record-without-wall-time"),
        pytest.param(
            [finished(9, 50), finished(9, None, released_at=RELEASED_AT + 1)],
            id="any-record-of-the-item-without-wall-time",
        ),
        pytest.param([finished(9, 50, outcome=LaneOutcome.ABANDONED)], id="an-item-never-landed"),
        pytest.param(
            [RecordedLane(RELEASED_AT, LaneRecord(LaneOutcome.LANDED, wall_seconds=50))],
            id="a-lane-without-an-issue",
        ),
    ],
)
def test_an_item_whose_time_is_not_fully_known_or_that_never_landed_is_no_sample(
    unsampled: list[RecordedLane],
) -> None:
    """Spec: ABRD-142, ABRD-144."""
    lanes = items_of(None, [10, 20, 30, 40], first_issue=100) + unsampled

    assert priced(lanes, [None]) is NoRange.TOO_FEW


def routed(issue: int, wall_seconds: int | None, fix_rounds: int | None) -> RecordedLane:
    routing = RoutingLine(stages={}, fix_rounds=fix_rounds, blocking=None, experiment=None)
    record = LaneRecord(LaneOutcome.LANDED, wall_seconds=wall_seconds, routing=routing)
    return RecordedLane(RELEASED_AT, record, issue)


def test_an_items_actuals_sum_the_wall_time_and_fix_rounds_of_all_its_records() -> None:
    """Spec: ABRD-148."""
    lanes = [routed(1, 100, 1), routed(1, 50, 2), routed(2, 7, 0)]

    assert item_actuals(lanes) == {1: ItemActuals(150, 3), 2: ItemActuals(7, 0)}


@pytest.mark.parametrize(
    ("lanes", "expected"),
    [
        pytest.param(
            [routed(1, None, 1), routed(1, 50, 1)], ItemActuals(None, 2), id="a-record-lacks-time"
        ),
        pytest.param(
            [routed(1, 10, None), routed(1, 50, 1)],
            ItemActuals(60, None),
            id="a-record-lacks-rounds",
        ),
        pytest.param([finished(1, 10)], ItemActuals(10, None), id="a-record-without-routing"),
    ],
)
def test_an_item_with_a_record_lacking_a_figure_has_that_figure_unknown(
    lanes: list[RecordedLane], expected: ItemActuals
) -> None:
    """Spec: ABRD-148."""
    assert item_actuals(lanes) == {1: expected}


def test_a_lane_released_without_an_issue_belongs_to_no_item() -> None:
    """Spec: ABRD-148."""
    lane = RecordedLane(RELEASED_AT, LaneRecord(LaneOutcome.LANDED, wall_seconds=5))

    assert item_actuals([lane]) == {}


def lane_of_risk(
    risk: str | None,
    counts: dict[FindingStage, StageCounts] | None = None,
    outcome: LaneOutcome = LaneOutcome.LANDED,
) -> RecordedLane:
    record = LaneRecord(outcome, risk=risk, counts={} if counts is None else counts)
    return RecordedLane(RELEASED_AT, record)


def block_summaries(lanes: list[RecordedLane]) -> list[tuple[str | None, int]]:
    return [(block.risk, block.lanes) for block in measure(NOVEMBER, lanes).risks]


@pytest.mark.parametrize(
    ("lanes", "expected"),
    [
        pytest.param([], [], id="no-lane-has-no-block"),
        pytest.param(
            [lane_of_risk("normal"), lane_of_risk("material"), lane_of_risk("normal")],
            [("material", 1), ("normal", 2)],
            id="one-block-per-risk-ordered-by-name",
        ),
        pytest.param(
            [lane_of_risk(None), lane_of_risk("zeta"), lane_of_risk("alpha")],
            [("alpha", 1), ("zeta", 1), (None, 1)],
            id="lanes-without-a-risk-come-last",
        ),
        pytest.param([lane_of_risk("normal")], [("normal", 1)], id="no-none-block-without-lanes"),
    ],
)
def test_a_group_has_one_block_per_risk_class_its_lanes_state(
    lanes: list[RecordedLane], expected: list[tuple[str | None, int]]
) -> None:
    """Spec: STATS-23, STATS-25."""
    assert block_summaries(lanes) == expected


def test_a_block_counts_the_outcomes_of_its_own_lanes() -> None:
    """Spec: STATS-23."""
    lanes = [
        lane_of_risk("normal"),
        lane_of_risk("normal", outcome=LaneOutcome.ABANDONED),
        lane_of_risk("material"),
    ]

    blocks = {block.risk: block.outcomes for block in measure(NOVEMBER, lanes).risks}

    assert blocks == {
        "normal": {LaneOutcome.LANDED: 1, LaneOutcome.ABANDONED: 1},
        "material": {LaneOutcome.LANDED: 1, LaneOutcome.ABANDONED: 0},
    }


def test_a_stage_total_sums_the_known_values_and_counts_the_lanes_that_state_none() -> None:
    """Spec: STATS-24."""
    lanes = [
        lane_of_risk("material", {FindingStage.CI: StageCounts(2, 3, 1)}),
        lane_of_risk("material", {FindingStage.CI: StageCounts(1, None, None)}),
        lane_of_risk("material"),
    ]

    stages = measure(NOVEMBER, lanes).risks[0].stages

    ci, review = stages[FindingStage.CI], stages[FindingStage.REVIEW]
    assert [(figure.total, figure.n, figure.unknown) for figure in (ci.fix_rounds, ci.misses)] == [
        (3, 2, 1),
        (1, 1, 2),
    ]
    assert [
        (figure.total, figure.n, figure.unknown) for figure in (review.fix_rounds, review.misses)
    ] == [
        (None, 0, 3),
        (None, 0, 3),
    ]
