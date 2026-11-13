"""The record a released lane leaves on its release commit (`specs/lane-record.spec.md`).

The record is computed once, before the release commit is pushed. A figure that cannot be read
is unknown and has no trailer: no failure here refuses or delays a release."""

import dataclasses
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from . import checkout, protocol, store, workboard
from .routing_line import RoutingLine, RoutingStage, parse_routing_line, stage_choice_fits
from .session import RunContext


class LaneOutcome(StrEnum):
    LANDED = "landed"
    ABANDONED = "abandoned"


class LaneTrailerKey(StrEnum):
    OUTCOME = "lane_outcome"
    MERGE = "lane_merge"
    WALL_SECONDS = "lane_wall_seconds"
    FILES = "lane_files"
    ADDED = "lane_added"
    DELETED = "lane_deleted"
    BUILD = "lane_build"
    FIX = "lane_fix"
    REVIEW = "lane_review"
    TEST = "lane_test"
    GATE = "lane_gate"
    LAND = "lane_land"
    FIX_ROUNDS = "lane_fix_rounds"
    BLOCKING = "lane_blocking"
    EXPERIMENT = "lane_experiment"


def _stage_key(stage: RoutingStage) -> LaneTrailerKey:
    return LaneTrailerKey(f"lane_{stage}")


@dataclass(frozen=True)
class ProductionSize:
    files: int
    added: int
    deleted: int


@dataclass(frozen=True)
class LaneRecord:
    """What is known of one released lane; `None` is unknown, never zero."""

    outcome: LaneOutcome
    merge_commit: str | None = None
    wall_seconds: int | None = None
    size: ProductionSize | None = None
    routing: RoutingLine | None = None

    def trailers(self) -> tuple[str, ...]:
        """The `key: value` lines of every known figure, in the spec's order."""
        figures: list[tuple[LaneTrailerKey, str | int | None]] = [
            (LaneTrailerKey.OUTCOME, self.outcome),
            (LaneTrailerKey.MERGE, self.merge_commit),
            (LaneTrailerKey.WALL_SECONDS, self.wall_seconds),
        ]
        if self.size is not None:
            figures += [
                (LaneTrailerKey.FILES, self.size.files),
                (LaneTrailerKey.ADDED, self.size.added),
                (LaneTrailerKey.DELETED, self.size.deleted),
            ]
        if self.routing is not None:
            figures += [
                (_stage_key(stage), self.routing.stages[stage])
                for stage in RoutingStage
                if stage in self.routing.stages
            ]
            figures += [
                (LaneTrailerKey.FIX_ROUNDS, self.routing.fix_rounds),
                (LaneTrailerKey.BLOCKING, self.routing.blocking),
                (LaneTrailerKey.EXPERIMENT, self.routing.experiment),
            ]
        return tuple(f"{key}: {value}" for key, value in figures if value is not None)


@dataclass(frozen=True)
class ReleasedLane:
    """The release being recorded: `released_at` is Unix seconds, `merge_commit` the sha the
    forge or the trunk walk named for a landed lane, `state_tip` the state-ref tip the claim
    was read from."""

    claim: protocol.ActiveClaim
    outcome: protocol.ReleaseOutcome
    merge_commit: str | None
    released_at: int
    state_tip: str | None


def release_subject(
    context: RunContext,
    claim: protocol.ActiveClaim,
    outcome: protocol.ReleaseOutcome,
    verified_merge: str | None = None,
) -> store.TransitionSubject:
    """The release transition's subject for `claim`, carrying its lane record. `verified_merge`
    is the merge commit the forge's landing was verified to have: a github `--merged` release
    reads it nowhere else."""
    released = ReleasedLane(
        claim,
        outcome,
        _merge_commit(outcome, verified_merge),
        int(datetime.now(UTC).timestamp()),
        context.observation.tip,
    )
    record = compute_record(context.toplevel, context.config, released)
    subject = store.transition_subject("release", claim.identity, claim.branch)
    return dataclasses.replace(
        subject, trailers=record.trailers(), committed_at=released.released_at
    )


def _merge_commit(outcome: protocol.ReleaseOutcome, verified_merge: str | None) -> str | None:
    return outcome.commit if isinstance(outcome, protocol.LandedRelease) else verified_merge


def compute_record(
    toplevel: Path, config: workboard.BoardConfig, released: ReleasedLane
) -> LaneRecord:
    """The record of `released`, every figure read from the repository at `toplevel`."""
    opened = _unknown_if_unreadable(lambda: _claim_commit(toplevel, released))
    outcome, merge_commit = released.outcome, released.merge_commit
    if isinstance(outcome, protocol.AbandonedRelease):
        return LaneRecord(
            LaneOutcome.ABANDONED,
            wall_seconds=_seconds_between(opened, released.released_at),
            routing=parse_routing_line(outcome.explanation),
        )
    if merge_commit is None or protocol.COMMIT_PATTERN.fullmatch(merge_commit) is None:
        return LaneRecord(LaneOutcome.LANDED)
    merge = merge_commit
    landed = _unknown_if_unreadable(lambda: _read_commit(toplevel, merge))
    return LaneRecord(
        LaneOutcome.LANDED,
        merge_commit=merge,
        wall_seconds=None if landed is None else _seconds_between(opened, landed.timestamp),
        size=_unknown_if_unreadable(lambda: _production_size(toplevel, config, merge)),
        routing=None if landed is None else parse_routing_line(landed.message),
    )


def _unknown_if_unreadable[Figure](read: Callable[[], Figure]) -> Figure | None:
    try:
        return read()
    except protocol.ClaimError:
        return None


@dataclass(frozen=True)
class _Commit:
    timestamp: int
    message: str


def _read_commit(toplevel: Path, sha: str) -> _Commit:
    raw = checkout.git_output(
        ["log", "-1", "--format=%ct%n%B", sha, "--"], directory=toplevel, lossy=True
    )
    timestamp, _, message = raw.partition("\n")
    return _Commit(int(timestamp), message)


def _claim_commit(toplevel: Path, released: ReleasedLane) -> _Commit | None:
    """The state-ref commit that added the claim: the first one after its `opened_commit`, which
    is the tip that preceded it, so the idle time before the claim never counts."""
    if released.state_tip is None:
        return None
    since_opened = checkout.git_output(
        [
            "rev-list",
            "--first-parent",
            "--reverse",
            released.state_tip,
            f"^{released.claim.opened_commit}",
        ],
        directory=toplevel,
    )
    claim_commit = since_opened.partition("\n")[0]
    return _read_commit(toplevel, claim_commit) if claim_commit else None


def _seconds_between(start: _Commit | None, end: int) -> int | None:
    if start is None or end < start.timestamp:
        return None
    return end - start.timestamp


def _production_size(
    toplevel: Path, config: workboard.BoardConfig, merge: str
) -> ProductionSize | None:
    if not config.production_paths:
        return None
    raw = checkout.git_output(
        ["diff", "--numstat", "--find-renames", "-z", f"{merge}^1", merge, "--"],
        directory=toplevel,
        lossy=True,
    )
    counted = [
        (added, deleted)
        for added, deleted, path in _numstat_changes(raw)
        if _is_production(config, path)
    ]
    return ProductionSize(
        files=len(counted),
        added=sum(_line_count(added) for added, _ in counted),
        deleted=sum(_line_count(deleted) for _, deleted in counted),
    )


def _numstat_changes(raw: str) -> Iterator[tuple[str, str, str]]:
    """`(added, deleted, path)` of each file in `git diff --numstat -z`. A renamed file is one
    change, counted by its new path: git leaves its record's path empty and names the old and
    the new path in the two records that follow."""
    records = iter(raw.split("\0"))
    for record in records:
        if not record:
            continue
        added, deleted, path = record.split("\t", 2)
        if not path:
            next(records)
            path = next(records)
        yield added, deleted, path


def _is_production(config: workboard.BoardConfig, path: str) -> bool:
    return not config.covers_dependency_path(path) and any(
        workboard.repository_path_entry_covers(entry, path) for entry in config.production_paths
    )


def _line_count(numstat_field: str) -> int:
    """A binary file counts `-` lines in `git diff --numstat`: no lines measured."""
    return 0 if numstat_field == "-" else int(numstat_field)


@dataclass(frozen=True)
class RecordedLane:
    """One released lane as its release commit records it; `released_at` is the commit's
    committer date in Unix seconds."""

    released_at: int
    record: LaneRecord


_WHOLE_NUMBER = re.compile(r"[0-9]+")


def recorded_lanes(toplevel: Path, state_tip: str | None) -> tuple[RecordedLane, ...]:
    """Every lane recorded on the first-parent history of `state_tip`, newest first. The keys are
    read by name from the commit messages: underscore keys are not git trailer tokens, so no
    git trailer tooling reads them."""
    if state_tip is None:
        return ()
    raw = checkout.git_output(
        ["log", "--first-parent", "-z", "--format=%ct%n%B", state_tip, "--"],
        directory=toplevel,
        lossy=True,
    )
    lanes: list[RecordedLane] = []
    for entry in filter(None, raw.split("\0")):
        committed_at, _, message = entry.partition("\n")
        record = parse_record(message)
        if record is not None:
            lanes.append(RecordedLane(int(committed_at), record))
    return tuple(lanes)


def parse_record(message: str) -> LaneRecord | None:
    """The record `message` carries, or `None` when it carries no valid `lane_outcome`. A figure
    whose line is missing, repeated or malformed is unknown."""
    values = _trailer_values(message)
    outcome = values.get(LaneTrailerKey.OUTCOME, "")
    if outcome not in LaneOutcome:
        return None
    return LaneRecord(
        outcome=LaneOutcome(outcome),
        merge_commit=values.get(LaneTrailerKey.MERGE),
        wall_seconds=_whole_number(values.get(LaneTrailerKey.WALL_SECONDS)),
        size=_recorded_size(values),
        routing=_recorded_routing(values),
    )


def _trailer_values(message: str) -> Mapping[LaneTrailerKey, str]:
    """The value of each lane key that `message` states exactly once and well formed: a repeat
    makes the key ambiguous even when its separator or value is malformed."""
    stated: dict[LaneTrailerKey, list[str | None]] = {}
    for line in message.splitlines():
        key, colon, rest = line.partition(":")
        if colon and key in LaneTrailerKey:
            stated.setdefault(LaneTrailerKey(key), []).append(
                rest.removeprefix(" ") if rest.startswith(" ") else None
            )
    return {
        key: values[0]
        for key, values in stated.items()
        if len(values) == 1 and values[0] is not None
    }


def _whole_number(text: str | None) -> int | None:
    return int(text) if text is not None and _WHOLE_NUMBER.fullmatch(text) else None


def _recorded_size(values: Mapping[LaneTrailerKey, str]) -> ProductionSize | None:
    files, added, deleted = (
        _whole_number(values.get(key))
        for key in (LaneTrailerKey.FILES, LaneTrailerKey.ADDED, LaneTrailerKey.DELETED)
    )
    if files is None or added is None or deleted is None:
        return None
    return ProductionSize(files, added, deleted)


def _recorded_routing(values: Mapping[LaneTrailerKey, str]) -> RoutingLine:
    stages = {
        stage: values[_stage_key(stage)]
        for stage in RoutingStage
        if stage_choice_fits(stage, values.get(_stage_key(stage), ""))
    }
    return RoutingLine(
        stages=MappingProxyType(stages),
        fix_rounds=_whole_number(values.get(LaneTrailerKey.FIX_ROUNDS)),
        blocking=_whole_number(values.get(LaneTrailerKey.BLOCKING)),
        experiment=values.get(LaneTrailerKey.EXPERIMENT),
    )
