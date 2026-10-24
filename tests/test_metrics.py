from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from aco.metrics import (
    Estimate,
    LaneEvent,
    OpenItem,
    Size,
    SizeClassStats,
    measure,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _lane(
    item: str,
    claimed_at: datetime,
    released_at: datetime | None,
    *,
    size: Size | None = None,
) -> LaneEvent:
    """One `LaneEvent`, every field defaulted to the value a proof that does
    not care about it can ignore."""
    return LaneEvent(
        item=item, size=size, claimed_at=claimed_at, released_at=released_at, rescopes=0
    )


def _completed_lane(item: str, size: Size, hours: float) -> LaneEvent:
    """A lane claimed at `BASE` and released `hours` later -- the one shape
    the size-class and estimate proofs need repeated with different data."""
    return _lane(item, BASE, BASE + timedelta(hours=hours), size=size)


# Three S-lanes and two M-lanes, shared by the
# size-class and estimate proofs so both read the same measured world.
_THREE_S_TWO_M_LANES = [
    _completed_lane("s1", Size.SMALL, 1.0),
    _completed_lane("s2", Size.SMALL, 2.0),
    _completed_lane("s3", Size.SMALL, 4.0),
    _completed_lane("m1", Size.MEDIUM, 3.0),
    _completed_lane("m2", Size.MEDIUM, 5.0),
]


@pytest.mark.parametrize(
    ("size", "hours", "expected"),
    [
        (
            Size.SMALL,
            (1.0, 2.0, 4.0),
            SizeClassStats(Size.SMALL, n=3, median_hours=2.0, p80_hours=4.0, weak=False),
        ),
        (
            Size.MEDIUM,
            (3.0, 5.0),
            SizeClassStats(Size.MEDIUM, n=2, median_hours=4.0, p80_hours=5.0, weak=True),
        ),
        (Size.LARGE, (), None),
    ],
)
def test_size_class_stats_from_measured_lanes(
    size: Size, hours: tuple[float, ...], expected: SizeClassStats | None
) -> None:
    """n, median, and nearest-rank p80 per size class; a class with no
    measured lane (L here) produces no `SizeClassStats` at all."""
    lanes = [_completed_lane(f"{size}-{index}", size, hour) for index, hour in enumerate(hours)]
    report = measure(lanes, open_items=())
    matching = next((entry for entry in report.classes if entry.size is size), None)
    assert matching == expected


@pytest.mark.parametrize(
    ("open_item", "expected"),
    [
        (
            OpenItem("open-s", Size.SMALL),
            Estimate("open-s", Size.SMALL, median_hours=2.0, n=3, weak=False),
        ),
        (
            OpenItem("open-m", Size.MEDIUM),
            Estimate("open-m", Size.MEDIUM, median_hours=4.0, n=2, weak=True),
        ),
        (OpenItem("open-none", None), None),
        (OpenItem("open-l", Size.LARGE), None),
    ],
)
def test_estimate_only_for_sized_items_with_a_measured_class(
    open_item: OpenItem, expected: Estimate | None
) -> None:
    """An open item gets an estimate only when it carries a size AND that
    size's class has at least one measured lane; `weak` follows the class's
    own `n < 3`. No size, or a size with no measured class (L here), yields
    no estimate -- counted elsewhere, never guessed."""
    report = measure(_THREE_S_TWO_M_LANES, open_items=(open_item,))
    matching = next((entry for entry in report.estimates if entry.item == open_item.item), None)
    assert matching == expected


@pytest.mark.parametrize(
    ("released_at", "expected_incomplete", "expected_measured_lanes"),
    [
        (BASE + timedelta(hours=2), 0, 1),
        (None, 1, 0),
    ],
)
def test_completion_gates_measurement(
    released_at: datetime | None, expected_incomplete: int, expected_measured_lanes: int
) -> None:
    """A lane without a release is counted in `incomplete`, never measured
    and never sorted into a class."""
    lane = _lane("x", BASE, released_at, size=Size.SMALL)
    report = measure([lane], open_items=())
    assert report.incomplete == expected_incomplete
    assert sum(entry.n for entry in report.classes) == expected_measured_lanes


@pytest.mark.parametrize(
    "build_lanes",
    [
        lambda: [_completed_lane("s1", Size.SMALL, 2.0)],
        lambda: [
            _completed_lane("m1", Size.MEDIUM, 4.0),
            _lane("stuck", BASE, None, size=Size.LARGE),
        ],
    ],
)
def test_measure_is_deterministic_for_the_same_input(
    build_lanes: Callable[[], list[LaneEvent]],
) -> None:
    """No randomness and no clock inside the module: computing twice from
    freshly built, equal input yields an equal `MetricsReport`."""
    open_items = (OpenItem("open-s", Size.SMALL),)
    first = measure(build_lanes(), open_items)
    second = measure(build_lanes(), open_items)
    assert first == second
