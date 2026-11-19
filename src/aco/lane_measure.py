"""The figures of one group of recorded lanes (`specs/stats.spec.md`).

Pure: it takes lanes already read from the state ref and touches no git, forge or clock."""

import math
import re
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from . import protocol
from .body import Size
from .lane_record import FindingStage, LaneOutcome, LaneRecord, RecordedLane, StageCounts
from .routing_line import EXPERIMENT_TAG, RoutingStage

TAG_PREFIX = "tag:"
_RANGE_SEPARATOR = ".."
TAG_GRAMMAR = "1 to 40 lowercase letters, digits or '-'"
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


@dataclass(frozen=True)
class DateRange:
    """The lanes released on `first` to `last`, both days inclusive, by UTC calendar day."""

    first: date
    last: date

    def __str__(self) -> str:
        return f"{self.first.isoformat()}{_RANGE_SEPARATOR}{self.last.isoformat()}"


@dataclass(frozen=True)
class ExperimentTag:
    """The lanes whose record names this `lane_experiment` tag."""

    tag: str

    def __str__(self) -> str:
        return f"{TAG_PREFIX}{self.tag}"


type LaneGroup = DateRange | ExperimentTag


def parse_group(text: str) -> LaneGroup:
    """`FROM..TO` (ISO days) or `tag:NAME`, refused by name when it is neither."""
    if text.startswith(TAG_PREFIX):
        tag = text.removeprefix(TAG_PREFIX)
        if EXPERIMENT_TAG.fullmatch(tag) is None:
            raise protocol.ClaimError(f"group {text!r} names no tag: a tag is {TAG_GRAMMAR}")
        return ExperimentTag(tag)
    first, separator, last = text.partition(_RANGE_SEPARATOR)
    if not separator or _DAY.fullmatch(first) is None or _DAY.fullmatch(last) is None:
        raise protocol.ClaimError(f"group {text!r} must be FROM..TO as YYYY-MM-DD days or tag:NAME")
    try:
        days = DateRange(date.fromisoformat(first), date.fromisoformat(last))
    except ValueError as error:
        raise protocol.ClaimError(f"group {text!r} holds an impossible day") from error
    if days.last < days.first:
        raise protocol.ClaimError(f"group {text!r} ends before it starts")
    return days


def selects(group: LaneGroup, lane: RecordedLane) -> bool:
    if isinstance(group, ExperimentTag):
        return lane.record.routing is not None and lane.record.routing.experiment == group.tag
    day = datetime.fromtimestamp(lane.released_at, UTC).date()
    return group.first <= day <= group.last


class FigureName(StrEnum):
    WALL_SECONDS = "wall_seconds"
    FIX_ROUNDS = "fix_rounds"
    BLOCKING = "blocking"
    FILES = "files"
    ADDED = "added"
    DELETED = "deleted"


@dataclass(frozen=True)
class Figure:
    """The median of the lanes that state it, `n` of them; `unknown` lanes do not. A figure no
    lane states has no median."""

    median: int | float | None
    n: int
    unknown: int


@dataclass(frozen=True)
class StageChoices:
    """How many lanes ran a stage on each `<model>/<effort>` (or `none`), and how many state
    no choice for it."""

    counts: Mapping[str, int]
    unknown: int


@dataclass(frozen=True)
class StageTotal:
    """The sum of the values of the `n` lanes that state a stage figure; `unknown` lanes do not.
    No lane stating it has no total, never `0`."""

    total: int | None
    n: int
    unknown: int


@dataclass(frozen=True)
class StageFigures:
    """The fix rounds and misses of one finding stage."""

    fix_rounds: StageTotal
    misses: StageTotal


@dataclass(frozen=True)
class RiskBlock:
    """The lanes of one risk class, `None` for the lanes that state no risk."""

    risk: str | None
    lanes: int
    outcomes: Mapping[LaneOutcome, int]
    stages: Mapping[FindingStage, StageFigures]


@dataclass(frozen=True)
class SideStats:
    group: LaneGroup
    lanes: int
    outcomes: Mapping[LaneOutcome, int]
    figures: Mapping[FigureName, Figure]
    stages: Mapping[RoutingStage, StageChoices]
    risks: tuple[RiskBlock, ...]


def _fix_rounds(record: LaneRecord) -> int | None:
    return None if record.routing is None else record.routing.fix_rounds


def _blocking(record: LaneRecord) -> int | None:
    return None if record.routing is None else record.routing.blocking


def _files(record: LaneRecord) -> int | None:
    return None if record.size is None else record.size.files


def _added(record: LaneRecord) -> int | None:
    return None if record.size is None else record.size.added


def _deleted(record: LaneRecord) -> int | None:
    return None if record.size is None else record.size.deleted


def _wall_seconds(record: LaneRecord) -> int | None:
    return record.wall_seconds


_READ_FIGURE: Mapping[FigureName, Callable[[LaneRecord], int | None]] = {
    FigureName.WALL_SECONDS: _wall_seconds,
    FigureName.FIX_ROUNDS: _fix_rounds,
    FigureName.BLOCKING: _blocking,
    FigureName.FILES: _files,
    FigureName.ADDED: _added,
    FigureName.DELETED: _deleted,
}


def measure(group: LaneGroup, lanes: Iterable[RecordedLane]) -> SideStats:
    """The figures of the `lanes` that `group` selects."""
    records = [lane.record for lane in lanes if selects(group, lane)]
    figures = {
        name: _figure([read(record) for record in records]) for name, read in _READ_FIGURE.items()
    }
    return SideStats(
        group=group,
        lanes=len(records),
        outcomes=_outcomes(records),
        figures=figures,
        stages={stage: _stage_choices(stage, records) for stage in RoutingStage},
        risks=_risk_blocks(records),
    )


def _outcomes(records: Sequence[LaneRecord]) -> dict[LaneOutcome, int]:
    outcomes = Counter(record.outcome for record in records)
    return {outcome: outcomes[outcome] for outcome in LaneOutcome}


def _risk_blocks(records: Sequence[LaneRecord]) -> tuple[RiskBlock, ...]:
    """One block per risk class the lanes state, ordered by name, the lanes without one last."""
    classes = sorted(
        {record.risk for record in records}, key=lambda risk: (risk is None, risk or "")
    )
    return tuple(
        _risk_block(risk, [record for record in records if record.risk == risk]) for risk in classes
    )


def _risk_block(risk: str | None, records: Sequence[LaneRecord]) -> RiskBlock:
    return RiskBlock(
        risk=risk,
        lanes=len(records),
        outcomes=_outcomes(records),
        stages={
            stage: StageFigures(
                fix_rounds=_stage_total(
                    _stage_values(records, stage, lambda counts: counts.fix_rounds)
                ),
                misses=_stage_total(_stage_values(records, stage, lambda counts: counts.misses)),
            )
            for stage in FindingStage
        },
    )


def _stage_values(
    records: Sequence[LaneRecord], stage: FindingStage, read: Callable[[StageCounts], int | None]
) -> list[int | None]:
    return [read(record.counts[stage]) if stage in record.counts else None for record in records]


def _stage_total(values: Sequence[int | None]) -> StageTotal:
    known = [value for value in values if value is not None]
    return StageTotal(
        total=sum(known) if known else None, n=len(known), unknown=len(values) - len(known)
    )


def _figure(values: Sequence[int | None]) -> Figure:
    known = [value for value in values if value is not None]
    return Figure(
        median=_whole_if_whole(statistics.median(known)) if known else None,
        n=len(known),
        unknown=len(values) - len(known),
    )


def _whole_if_whole(median: int | float) -> int | float:
    return int(median) if median == int(median) else median


def _stage_choices(stage: RoutingStage, records: Sequence[LaneRecord]) -> StageChoices:
    chosen = [
        record.routing.stages[stage]
        for record in records
        if record.routing is not None and stage in record.routing.stages
    ]
    return StageChoices(counts=dict(Counter(chosen)), unknown=len(records) - len(chosen))


MINIMUM_ITEMS = 5
"""The finished items a distribution needs before it prices a lane."""
_UPPER_PERCENT = 80


class NoRange(StrEnum):
    """Why remaining work has no range, as its sentence."""

    UNREADABLE = "lane records unreadable"
    NO_RECORDS = "no lane records"
    TOO_FEW = "not enough lane records yet"


class Basis(StrEnum):
    """Whether a size class was priced from its own items or from all finished items."""

    MEASURED = "measured"
    POOLED = "pooled"


@dataclass(frozen=True)
class LaneTime:
    """The agent time of one lane over `items` finished items: the median as `aco stats` reads
    it and the nearest-rank 80th percentile, both in seconds."""

    median_seconds: float
    upper_seconds: int
    items: int


@dataclass(frozen=True)
class LanePrices:
    """What a lane costs, from the finished items of `recorded` lanes: per size class once the
    class has `MINIMUM_ITEMS`, else pooled over all sizes, which has none under that count."""

    recorded: int
    by_size: Mapping[Size, LaneTime]
    pooled: LaneTime | None


@dataclass(frozen=True)
class PricedClass:
    """`lanes` lanes of `size` (`None`: no declared size) priced on `basis` from `items` items."""

    size: Size | None
    lanes: int
    basis: Basis
    items: int


@dataclass(frozen=True)
class RemainingWork:
    """The agent time left as a range in seconds; `items` is the finished items pooled."""

    low_seconds: int
    high_seconds: int
    items: int
    classes: tuple[PricedClass, ...]


@dataclass(frozen=True)
class _FinishedItem:
    wall_seconds: int
    size: Size | None


def _by_issue(lanes: Iterable[RecordedLane]) -> dict[int, list[RecordedLane]]:
    """The lanes grouped by the work item their release names; a lane without one is dropped."""
    by_issue: dict[int, list[RecordedLane]] = {}
    for lane in lanes:
        if lane.issue is not None:
            by_issue.setdefault(lane.issue, []).append(lane)
    return by_issue


def _finished_items(lanes: Iterable[RecordedLane]) -> tuple[_FinishedItem, ...]:
    """One sample per work item that has a landed lane: the sum of its records' wall time, sized
    by its latest landed record. An item with a record of unknown wall time is no sample."""
    finished: list[_FinishedItem] = []
    for records in _by_issue(lanes).values():
        landed = [lane for lane in records if lane.record.outcome is LaneOutcome.LANDED]
        wall = [lane.record.wall_seconds for lane in records]
        if landed and None not in wall:
            latest = max(landed, key=lambda lane: lane.released_at)
            finished.append(
                _FinishedItem(
                    sum(seconds for seconds in wall if seconds is not None), latest.record.item_size
                )
            )
    return tuple(finished)


@dataclass(frozen=True)
class ItemActuals:
    """What one work item's lanes took: the sum of their wall seconds and fix rounds, each
    `None` when any of its records lacks it."""

    wall_seconds: int | None
    fix_rounds: int | None


def _sum_if_known(values: Iterable[int | None]) -> int | None:
    known = list(values)
    return None if None in known else sum(value for value in known if value is not None)


def item_actuals(lanes: Iterable[RecordedLane]) -> dict[int, ItemActuals]:
    """The actuals of every work item that has a record among `lanes`, by issue number."""
    return {
        issue: ItemActuals(
            _sum_if_known(lane.record.wall_seconds for lane in records),
            _sum_if_known(_fix_rounds(lane.record) for lane in records),
        )
        for issue, records in _by_issue(lanes).items()
    }


def _lane_time(seconds: Sequence[int]) -> LaneTime | None:
    if len(seconds) < MINIMUM_ITEMS:
        return None
    ordered = sorted(seconds)
    rank = math.ceil(_UPPER_PERCENT * len(ordered) / 100)
    return LaneTime(float(statistics.median(ordered)), ordered[rank - 1], len(ordered))


def lane_prices(lanes: Iterable[RecordedLane]) -> LanePrices:
    """The prices of a lane from `lanes`, newest first or in any order."""
    recorded = tuple(lanes)
    items = _finished_items(recorded)
    by_size = {
        size: price
        for size in Size
        if (price := _lane_time([item.wall_seconds for item in items if item.size is size]))
        is not None
    }
    return LanePrices(len(recorded), by_size, _lane_time([item.wall_seconds for item in items]))


def remaining_work(
    prices: LanePrices | None, sizes: Iterable[Size | None]
) -> RemainingWork | NoRange:
    """The range for one lane per entry of `sizes`: each lane at its class's median to 80th
    percentile, or the pooled one when its class has too few items. No range when the lane
    records could not be read (`prices` is `None`), without records, or while the pooled
    distribution is under `MINIMUM_ITEMS` items."""
    if prices is None:
        return NoRange.UNREADABLE
    if prices.recorded == 0:
        return NoRange.NO_RECORDS
    if prices.pooled is None:
        return NoRange.TOO_FEW
    counts = Counter(sizes)
    classes: list[PricedClass] = []
    low = high = 0.0
    for size in (*Size, None):
        if not counts[size]:
            continue
        measured = None if size is None else prices.by_size.get(size)
        price = prices.pooled if measured is None else measured
        classes.append(
            PricedClass(
                size,
                counts[size],
                Basis.POOLED if measured is None else Basis.MEASURED,
                price.items,
            )
        )
        low += counts[size] * price.median_seconds
        high += counts[size] * price.upper_seconds
    return RemainingWork(round(low), round(high), prices.pooled.items, tuple(classes))
