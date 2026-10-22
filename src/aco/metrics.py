"""Pure lane-metrics computation.

Turns lane events into size-class statistics and per-item estimates -- with no
git, no clock, and no forge: every timestamp is a `datetime` the caller already
holds. A `SizeClassStats` names its median (`statistics.median`) and p80
(nearest-rank) over the lanes measured for one `Size`; too few lanes
(`n < WEAK_SAMPLE_THRESHOLD`) sets `weak`, but never withholds the value --
withholding a weak number is the caller's presentation choice, not this
module's.

`Size` is defined here, the one owner of the three size letters and their
order. `body.py` reads it through the layer order; `items.py` does not import
this module.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

# The nearest-rank percentile `SizeClassStats.p80_hours` reads: the 80th
# percentile, named once so the one call site never repeats the literal.
P80_PERCENTILE = 80
# Below this many measured lanes, a size class's median/p80 rests on too few
# samples to trust; `SizeClassStats.weak`/`Estimate.weak` name that -- they
# never hide the number itself.
WEAK_SAMPLE_THRESHOLD = 3


class Size(StrEnum):
    """A work item's rough size class, small enough to estimate a lane's
    duration from.

    Declared in this order (S, M, L) so any iteration over `Size` -- for
    example when listing the measured classes -- reads in size order rather
    than the alphabetical order of the letters themselves.
    """

    SMALL = "S"
    MEDIUM = "M"
    LARGE = "L"


@dataclass(frozen=True)
class LaneEvent:
    """One claim's lifecycle, as `store.claim_lifecycle` reads it from the ref
    history. `released_at` is `None` while the claim has not yet been released;
    `rescopes` is the number of scope changes the claim lived through, not read
    by `measure` itself.
    """

    item: str
    size: Size | None
    claimed_at: datetime
    released_at: datetime | None
    rescopes: int


@dataclass(frozen=True)
class OpenItem:
    """One still-open work item, the unit `Estimate` is computed for."""

    item: str
    size: Size | None


@dataclass(frozen=True)
class SizeClassStats:
    """The measured lanes of one size, with `weak` naming rather than hiding
    a median/p80 that rests on fewer than `WEAK_SAMPLE_THRESHOLD` samples."""

    size: Size
    n: int
    median_hours: float
    p80_hours: float
    weak: bool


@dataclass(frozen=True)
class Estimate:
    """An open item's projected wall hours, read from its size class's
    median -- only produced when that class has at least one measured
    lane."""

    item: str
    size: Size
    median_hours: float
    n: int
    weak: bool


@dataclass(frozen=True)
class MetricsReport:
    """Everything `measure` computes from one set of lane events and open
    items. `incomplete` counts the lanes not yet released."""

    classes: tuple[SizeClassStats, ...]
    estimates: tuple[Estimate, ...]
    incomplete: int


def measure(lanes: Iterable[LaneEvent], open_items: Iterable[OpenItem]) -> MetricsReport:
    """Compute the size classes and per-item estimates from the given lane
    events and open items. Pure and deterministic: the same input always
    yields the same output."""

    lane_list = list(lanes)
    completed = [(lane, lane.released_at) for lane in lane_list if lane.released_at is not None]

    classes = _classes_by_size(
        [(lane.size, _hours(lane.claimed_at, released_at)) for lane, released_at in completed]
    )
    estimates = tuple(
        estimate
        for estimate in (_estimate_item(item, classes) for item in open_items)
        if estimate is not None
    )
    return MetricsReport(
        classes=classes, estimates=estimates, incomplete=len(lane_list) - len(completed)
    )


def _hours(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600


def _classes_by_size(
    sized_wall_hours: Iterable[tuple[Size | None, float]],
) -> tuple[SizeClassStats, ...]:
    grouped: dict[Size, list[float]] = {}
    for size, wall_hours in sized_wall_hours:
        if size is not None:
            grouped.setdefault(size, []).append(wall_hours)
    return tuple(_size_class_stats(size, grouped[size]) for size in Size if size in grouped)


def _size_class_stats(size: Size, hours: Sequence[float]) -> SizeClassStats:
    return SizeClassStats(
        size=size,
        n=len(hours),
        median_hours=statistics.median(hours),
        p80_hours=_nearest_rank_percentile(hours, P80_PERCENTILE),
        weak=len(hours) < WEAK_SAMPLE_THRESHOLD,
    )


def _nearest_rank_percentile(values: Sequence[float], percentile: int) -> float:
    """The nearest-rank percentile: the value at ceil(percentile/100 * n),
    1-indexed into the ascending sort. Integer ceiling division keeps this
    exact without importing `math` for the one call site."""

    ordered = sorted(values)
    rank = -(-percentile * len(ordered) // 100)
    return ordered[max(rank, 1) - 1]


def _estimate_item(item: OpenItem, classes: Sequence[SizeClassStats]) -> Estimate | None:
    if item.size is None:
        return None
    stats = next((entry for entry in classes if entry.size == item.size), None)
    if stats is None:
        return None
    return Estimate(
        item=item.item,
        size=item.size,
        median_hours=stats.median_hours,
        n=stats.n,
        weak=stats.weak,
    )
