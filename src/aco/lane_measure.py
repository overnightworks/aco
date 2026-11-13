"""The figures of one group of recorded lanes (`specs/stats.spec.md`).

Pure: it takes lanes already read from the state ref and touches no git, forge or clock."""

import re
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from . import protocol
from .lane_record import LaneOutcome, LaneRecord, RecordedLane
from .routing_line import EXPERIMENT_TAG, RoutingStage

TAG_PREFIX = "tag:"
_RANGE_SEPARATOR = ".."
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


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
            raise protocol.ClaimError(
                f"group '{text}' names no tag: a tag is 1 to 40 lowercase letters, digits or '-'"
            )
        return ExperimentTag(tag)
    first, separator, last = text.partition(_RANGE_SEPARATOR)
    if not separator or _DAY.fullmatch(first) is None or _DAY.fullmatch(last) is None:
        raise protocol.ClaimError(f"group '{text}' must be FROM..TO as YYYY-MM-DD days or tag:NAME")
    try:
        days = DateRange(date.fromisoformat(first), date.fromisoformat(last))
    except ValueError as error:
        raise protocol.ClaimError(f"group '{text}' holds an impossible day") from error
    if days.last < days.first:
        raise protocol.ClaimError(f"group '{text}' ends before it starts")
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
    COST = "cost"


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
class SideStats:
    group: LaneGroup
    lanes: int
    outcomes: Mapping[LaneOutcome, int]
    figures: Mapping[FigureName, Figure]
    stages: Mapping[RoutingStage, StageChoices]


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
    """The figures of the `lanes` that `group` selects. Cost has no source, so it is unknown for
    every lane."""
    records = [lane.record for lane in lanes if selects(group, lane)]
    figures = {
        name: _figure([read(record) for record in records]) for name, read in _READ_FIGURE.items()
    }
    figures[FigureName.COST] = _figure([None] * len(records))
    outcomes = Counter(record.outcome for record in records)
    return SideStats(
        group=group,
        lanes=len(records),
        outcomes={outcome: outcomes[outcome] for outcome in LaneOutcome},
        figures=figures,
        stages={stage: _stage_choices(stage, records) for stage in RoutingStage},
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
