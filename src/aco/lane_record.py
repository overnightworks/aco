"""The record a released lane leaves on its release commit (`specs/lane-record.spec.md`).

The record is computed once, before the release commit is pushed. A figure that cannot be read
is unknown and has no trailer: no failure here refuses or delays a release."""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from . import checkout, protocol, store, workboard
from .routing_line import RoutingLine, RoutingStage, parse_routing_line
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
                (LaneTrailerKey(f"lane_{stage}"), self.routing.stages[stage])
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
    forge or the trunk walk named for a landed lane."""

    claim: protocol.ActiveClaim
    outcome: protocol.ReleaseOutcome
    merge_commit: str | None
    released_at: int


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
        claim, outcome, _merge_commit(outcome, verified_merge), int(datetime.now(UTC).timestamp())
    )
    record = compute_record(context.toplevel, context.config, released)
    subject = store.transition_subject("release", claim.identity, claim.branch)
    return dataclasses.replace(subject, trailers=record.trailers())


def _merge_commit(outcome: protocol.ReleaseOutcome, verified_merge: str | None) -> str | None:
    return outcome.commit if isinstance(outcome, protocol.LandedRelease) else verified_merge


def compute_record(
    toplevel: Path, config: workboard.BoardConfig, released: ReleasedLane
) -> LaneRecord:
    """The record of `released`, every figure read from the repository at `toplevel`."""
    opened = _unknown_if_unreadable(lambda: _read_commit(toplevel, released.claim.opened_commit))
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
        ["diff", "--numstat", "-z", "--no-renames", f"{merge}^1", merge, "--"],
        directory=toplevel,
        lossy=True,
    )
    changes = [record.split("\t", 2) for record in raw.split("\0") if record]
    counted = [(added, deleted) for added, deleted, path in changes if _is_production(config, path)]
    return ProductionSize(
        files=len(counted),
        added=sum(_line_count(added) for added, _ in counted),
        deleted=sum(_line_count(deleted) for _, deleted in counted),
    )


def _is_production(config: workboard.BoardConfig, path: str) -> bool:
    return not config.covers_dependency_path(path) and any(
        workboard.repository_path_entry_covers(entry, path) for entry in config.production_paths
    )


def _line_count(numstat_field: str) -> int:
    """A binary file counts `-` lines in `git diff --numstat`: no lines measured."""
    return 0 if numstat_field == "-" else int(numstat_field)
