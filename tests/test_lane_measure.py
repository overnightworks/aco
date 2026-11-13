"""The figures of a group of recorded lanes, computed without git from lanes already read."""

from datetime import UTC, date, datetime

import pytest

from aco import protocol
from aco.lane_measure import DateRange, FigureName, measure, parse_group
from aco.lane_record import LaneOutcome, LaneRecord, RecordedLane

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


@pytest.mark.parametrize("lanes", [0, 3])
def test_cost_is_unknown_for_every_lane(lanes: int) -> None:
    """Spec: STATS-09."""
    recorded = [lane_with_wall_seconds(1) for _ in range(lanes)]

    figure = measure(NOVEMBER, recorded).figures[FigureName.COST]

    assert (figure.median, figure.n, figure.unknown) == (None, 0, lanes)


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
