"""The record a released lane leaves on its release commit (`specs/lane-record.spec.md`).

The record is computed once, before the release commit is pushed. A figure that cannot be read
is unknown and has no trailer: no failure here refuses or delays a release."""

import dataclasses
import json
import re
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import cast

from . import body, checkout, forge, protocol, store, workboard
from .routing_line import (
    EXPERIMENT_TAG,
    RoutingLine,
    RoutingStage,
    parse_routing_line,
    stage_choice_fits,
)
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
    SIZE = "lane_size"
    BUILD = "lane_build"
    FIX = "lane_fix"
    REVIEW = "lane_review"
    TEST = "lane_test"
    GATE = "lane_gate"
    LAND = "lane_land"
    FIX_ROUNDS = "lane_fix_rounds"
    BLOCKING = "lane_blocking"
    EXPERIMENT = "lane_experiment"
    RISK = "lane_risk"
    FIX_ROUNDS_REVIEW = "lane_fix_rounds_review"
    FIX_ROUNDS_GATE = "lane_fix_rounds_gate"
    FIX_ROUNDS_CI = "lane_fix_rounds_ci"
    FIX_ROUNDS_TEST = "lane_fix_rounds_test"
    BLOCKING_REVIEW = "lane_blocking_review"
    BLOCKING_GATE = "lane_blocking_gate"
    BLOCKING_CI = "lane_blocking_ci"
    BLOCKING_TEST = "lane_blocking_test"


class FindingStage(StrEnum):
    """The stages a blocking finding is counted under; a stand-in for the gate counts as `gate`."""

    REVIEW = "review"
    GATE = "gate"
    CI = "ci"
    TEST = "test"


class VerdictStage(StrEnum):
    REVIEW = "review"
    GATE = "gate"


class Verdict(StrEnum):
    APPROVE = "approve"
    REVISE = "revise"


def _stage_key(stage: RoutingStage) -> LaneTrailerKey:
    return LaneTrailerKey(f"lane_{stage}")


_FIX_ROUNDS_KEYS = MappingProxyType(
    {
        FindingStage.REVIEW: LaneTrailerKey.FIX_ROUNDS_REVIEW,
        FindingStage.GATE: LaneTrailerKey.FIX_ROUNDS_GATE,
        FindingStage.CI: LaneTrailerKey.FIX_ROUNDS_CI,
        FindingStage.TEST: LaneTrailerKey.FIX_ROUNDS_TEST,
    }
)
_BLOCKING_KEYS = MappingProxyType(
    {
        FindingStage.REVIEW: LaneTrailerKey.BLOCKING_REVIEW,
        FindingStage.GATE: LaneTrailerKey.BLOCKING_GATE,
        FindingStage.CI: LaneTrailerKey.BLOCKING_CI,
        FindingStage.TEST: LaneTrailerKey.BLOCKING_TEST,
    }
)


@dataclass(frozen=True)
class StageCounts:
    """The fix rounds and the blocking findings of one finding stage."""

    fix_rounds: int
    blocking: int


@dataclass(frozen=True)
class JudgedVerdict:
    stage: VerdictStage
    verdict: Verdict
    sha: str


@dataclass(frozen=True)
class LaneRecordFile:
    """What a lane record file states (`specs/lane-record.spec.md`, LANREC-30..LANREC-37),
    read once: the file is never stored."""

    stages: Mapping[RoutingStage, str]
    counts: Mapping[FindingStage, StageCounts]
    verdicts: tuple[JudgedVerdict, ...]
    risk: str | None
    experiment: str | None

    def routing_line(self) -> RoutingLine:
        """The routing figures the file states, as a routing line states them."""
        return RoutingLine(
            stages=self.stages,
            fix_rounds=sum(counts.fix_rounds for counts in self.counts.values()),
            blocking=sum(counts.blocking for counts in self.counts.values()),
            experiment=self.experiment,
        )


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
    item_size: body.Size | None = None
    routing: RoutingLine | None = None
    risk: str | None = None
    counts: Mapping[FindingStage, StageCounts] = MappingProxyType({})

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
        figures.append((LaneTrailerKey.SIZE, self.item_size))
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
        figures.append((LaneTrailerKey.RISK, self.risk))
        figures += [
            (_FIX_ROUNDS_KEYS[stage], counts.fix_rounds) for stage, counts in self.counts.items()
        ]
        figures += [
            (_BLOCKING_KEYS[stage], counts.blocking) for stage, counts in self.counts.items()
        ]
        return tuple(f"{key}: {value}" for key, value in figures if value is not None)


@dataclass(frozen=True)
class ReleasedLane:
    """The release being recorded: `released_at` is Unix seconds, `merge_commit` the sha the
    forge or the trunk walk named for a landed lane, `state_tip` the state-ref tip the claim
    was read from, `item_size` the size class its work item declares, `record_file` the lane
    record file the release was given, which states the routing figures instead of a routing
    line."""

    claim: protocol.ActiveClaim
    outcome: protocol.ReleaseOutcome
    merge_commit: str | None
    released_at: int
    state_tip: str | None
    item_size: body.Size | None = None
    record_file: LaneRecordFile | None = None


@dataclass(frozen=True)
class ReleaseEvidence:
    """What a release holds beyond its claim and outcome: `verified_merge` is the merge commit
    the forge's landing was verified to have (a github `--merged` release reads it nowhere
    else), `item` the work item the landing release already read, whose body declares the size,
    `record_file` the lane record file the release was given."""

    verified_merge: str | None = None
    item: forge.ItemReference | None = None
    record_file: LaneRecordFile | None = None


def release_subject(
    context: RunContext,
    claim: protocol.ActiveClaim,
    outcome: protocol.ReleaseOutcome,
    evidence: ReleaseEvidence,
) -> store.TransitionSubject:
    """The release transition's subject for `claim`, carrying its lane record."""
    released = ReleasedLane(
        claim,
        outcome,
        _merge_commit(outcome, evidence.verified_merge),
        int(context.now().timestamp()),
        context.observation.tip,
        _declared_size(evidence.item, context.config.storage),
        evidence.record_file,
    )
    record = compute_record(context.toplevel, context.config, released)
    subject = store.transition_subject("release", claim.identity, claim.branch)
    return dataclasses.replace(
        subject, trailers=record.trailers(), committed_at=released.released_at
    )


def _merge_commit(outcome: protocol.ReleaseOutcome, verified_merge: str | None) -> str | None:
    return outcome.commit if isinstance(outcome, protocol.LandedRelease) else verified_merge


def _declared_size(item: forge.ItemReference | None, storage: body.Storage) -> body.Size | None:
    if item is None or item.body is None:
        return None
    return body.parse_body(item.body, storage=storage).size


def compute_record(
    toplevel: Path, config: workboard.BoardConfig, released: ReleasedLane
) -> LaneRecord:
    """The record of `released`, every figure read from the repository at `toplevel`; the routing
    figures come from its lane record file when it has one, and from a routing line otherwise."""
    measured = _measured_record(toplevel, config, released)
    stated = released.record_file
    if stated is None:
        return measured
    return LaneRecord(
        measured.outcome,
        merge_commit=measured.merge_commit,
        wall_seconds=measured.wall_seconds,
        size=measured.size,
        item_size=measured.item_size,
        routing=stated.routing_line(),
        risk=stated.risk,
        counts=stated.counts,
    )


def _measured_record(
    toplevel: Path, config: workboard.BoardConfig, released: ReleasedLane
) -> LaneRecord:
    opened = _unknown_if_unreadable(lambda: _claim_commit(toplevel, released))
    outcome, merge_commit = released.outcome, released.merge_commit
    if isinstance(outcome, protocol.AbandonedRelease):
        return LaneRecord(
            LaneOutcome.ABANDONED,
            wall_seconds=_seconds_between(opened, released.released_at),
            routing=_routing_in(outcome.explanation, released),
        )
    if merge_commit is None or protocol.COMMIT_PATTERN.fullmatch(merge_commit) is None:
        return LaneRecord(LaneOutcome.LANDED, item_size=released.item_size)
    merge = merge_commit
    landed = _unknown_if_unreadable(lambda: _read_commit(toplevel, merge))
    return LaneRecord(
        LaneOutcome.LANDED,
        merge_commit=merge,
        wall_seconds=None if landed is None else _seconds_between(opened, landed.timestamp),
        size=_unknown_if_unreadable(lambda: _production_size(toplevel, config, merge)),
        item_size=released.item_size,
        routing=None if landed is None else _routing_in(landed.message, released),
    )


def _routing_in(text: str, released: ReleasedLane) -> RoutingLine | None:
    return parse_routing_line(text) if released.record_file is None else None


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
    committer date in Unix seconds, `issue` the work item its subject names, `None` for a lane
    released without one."""

    released_at: int
    record: LaneRecord
    issue: int | None = None


_WHOLE_NUMBER = re.compile(r"\d+", re.ASCII)
_RELEASE_SUBJECT = re.compile(r"release issue (?P<issue>[1-9]\d*)", re.ASCII)


def released_issue(subject: str) -> int | None:
    """The issue number a release transition's subject (`store.transition_subject`) names;
    `None` for a lane release and for any other transition."""
    named = _RELEASE_SUBJECT.fullmatch(subject)
    return None if named is None else int(named["issue"])


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
            subject = message.partition("\n")[0]
            lanes.append(RecordedLane(int(committed_at), record, released_issue(subject)))
    return tuple(lanes)


def parse_record(message: str) -> LaneRecord | None:
    """The record `message` carries, or `None` when it carries no valid `lane_outcome`. A figure
    whose line is missing, repeated or malformed is unknown."""
    values = _trailer_values(message)
    outcome = values.get(LaneTrailerKey.OUTCOME, "")
    if outcome not in LaneOutcome:
        return None
    item_size = values.get(LaneTrailerKey.SIZE, "")
    return LaneRecord(
        outcome=LaneOutcome(outcome),
        merge_commit=values.get(LaneTrailerKey.MERGE),
        wall_seconds=_whole_number(values.get(LaneTrailerKey.WALL_SECONDS)),
        size=_recorded_size(values),
        item_size=body.Size(item_size) if item_size in body.Size else None,
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


RECORD_FILE_VERSION = 1
_MAXIMUM_COUNT = 999
_RECORD_FIELDS = ("version", "stages", "fix_rounds", "blocking", "verdicts")
_OPTIONAL_RECORD_FIELDS = ("risk", "experiment")
_VERDICT_FIELDS = ("stage", "verdict", "sha")


class RecordFileError(Exception):
    """The first thing wrong with a lane record file, as a phrase that follows its name. A value
    the file states stands apart as `stated`, so the caller can cut it alone and keep the words."""

    def __init__(self, before: str, stated: str = "", after: str = "") -> None:
        super().__init__(before + stated + after)
        self.before = before
        self.stated = stated
        self.after = after


# A valid file is a few hundred bytes of counts and tags plus one short entry per verdict; a file
# past this is never one, and a reader that holds it whole would run out of memory on a special
# file such as /dev/zero.
RECORD_FILE_BYTES_LIMIT = 1024 * 1024


def parse_record_file(content: bytes) -> LaneRecordFile:
    """The lane record file whose bytes are `content`, validated whole: one that is not exactly
    what the spec states raises `RecordFileError`."""
    try:
        raw = json.loads(content, object_pairs_hook=_keys_once)
    except (ValueError, RecursionError) as error:
        raise RecordFileError("not valid JSON") from error
    return _record_file(raw)


def _keys_once(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise RecordFileError("a key stated twice")
    return dict(pairs)


def _record_file(raw: object) -> LaneRecordFile:
    fields = _members(raw, "the record", _RECORD_FIELDS, _OPTIONAL_RECORD_FIELDS)
    version = fields["version"]
    if type(version) is not int or version != RECORD_FILE_VERSION:
        raise RecordFileError(
            "version ",
            json.dumps(version),
            f" is unknown; this aco reads version {RECORD_FILE_VERSION}",
        )
    fix_rounds = _counts_by_stage(fields["fix_rounds"], "fix_rounds")
    blocking = _counts_by_stage(fields["blocking"], "blocking")
    return LaneRecordFile(
        stages=_stage_choices(fields["stages"]),
        counts={stage: StageCounts(fix_rounds[stage], blocking[stage]) for stage in FindingStage},
        verdicts=_verdicts(fields["verdicts"]),
        risk=_optional_tag(fields, "risk"),
        experiment=_optional_tag(fields, "experiment"),
    )


def _members(
    value: object, where: str, required: Collection[str], optional: Collection[str] = ()
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RecordFileError(f"{where} must be an object")
    members = cast(dict[str, object], value)
    for name in members:
        if name not in required and name not in optional:
            raise RecordFileError(f"{where} has an unknown key ", repr(name))
    for name in map(str, required):
        if name not in members:
            raise RecordFileError(f"{where} lacks {name!r}")
    return members


def _stage_choices(value: object) -> dict[RoutingStage, str]:
    members = _members(value, "stages", tuple(RoutingStage))
    choices: dict[RoutingStage, str] = {}
    for stage in RoutingStage:
        choice = members[stage]
        if not isinstance(choice, str) or not stage_choice_fits(stage, choice):
            raise RecordFileError(f"stage {stage} must be <model>/<effort> or none")
        choices[stage] = choice
    return choices


def _counts_by_stage(value: object, where: str) -> dict[FindingStage, int]:
    members = _members(value, where, tuple(FindingStage))
    counts: dict[FindingStage, int] = {}
    for stage in FindingStage:
        count = members[stage]
        if type(count) is not int or not 0 <= count <= _MAXIMUM_COUNT:
            raise RecordFileError(
                f"{where}.{stage} must be a whole number from 0 to {_MAXIMUM_COUNT}"
            )
        counts[stage] = count
    return counts


def _verdicts(value: object) -> tuple[JudgedVerdict, ...]:
    if not isinstance(value, list):
        raise RecordFileError("verdicts must be a list")
    return tuple(
        _verdict(item, f"verdicts[{position}]")
        for position, item in enumerate(cast(list[object], value))
    )


def _verdict(value: object, where: str) -> JudgedVerdict:
    members = _members(value, where, _VERDICT_FIELDS)
    stage, verdict, sha = (members[name] for name in _VERDICT_FIELDS)
    if not isinstance(stage, str) or stage not in VerdictStage:
        raise RecordFileError(f"{where}.stage must be one of {', '.join(VerdictStage)}")
    if not isinstance(verdict, str) or verdict not in Verdict:
        raise RecordFileError(f"{where}.verdict must be one of {', '.join(Verdict)}")
    if not isinstance(sha, str) or protocol.COMMIT_PATTERN.fullmatch(sha) is None:
        raise RecordFileError(f"{where}.sha must be a full 40-digit commit sha")
    return JudgedVerdict(VerdictStage(stage), Verdict(verdict), sha)


def _optional_tag(fields: Mapping[str, object], name: str) -> str | None:
    if name not in fields:
        return None
    tag = fields[name]
    if not isinstance(tag, str) or EXPERIMENT_TAG.fullmatch(tag) is None:
        raise RecordFileError(f"{name} must be 1 to 40 lowercase letters, digits and `-`")
    return tag


def require_abandoned_release(record: LaneRecordFile | None, abandoned: str | None) -> None:
    """Refuse a `release` given a lane record file for a landing: `aco land` takes it there."""
    if record is not None and abandoned is None:
        raise protocol.ClaimUnavailableError("--record applies to --abandoned only")


def require_landing_head(record: LaneRecordFile | None, reviewed: str) -> None:
    """Refuse a landing whose lane record file judged another commit than `reviewed` (a full
    sha or a prefix of one): nothing is merged or written for it. A landing without a record
    file has nothing to compare."""
    if record is None:
        return
    if not record.verdicts:
        raise protocol.ClaimUnavailableError(
            "the lane record states no review or gate verdict, so it judged no head to land"
        )
    judged = record.verdicts[-1].sha
    if not judged.startswith(reviewed):
        raise protocol.ClaimUnavailableError(
            f"the lane record's last verdict judged {judged}, not the reviewed {reviewed}"
        )
