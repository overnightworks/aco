"""The runs a lane stored with its claim (`specs/lane-record.spec.md`, "Stored runs").

A run is begun at a start tip and later added with its end tip, the stages that ran and its lane
record. The runs of one claim are one JSON file in the state tree; this module owns the file's
shape, whether a run follows the run before it, and the merge a begin or an add makes. It
touches no git, no state ref and no clock: the ancestry fact `follows` judges by is its
argument."""

import json
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import partial
from typing import cast

from . import lane_record, protocol
from .routing_line import NO_STAGE, RoutingStage, stage_choice_fits

RUNS_FILE_VERSION = 1
RUN_ID_PATTERN = protocol.CLAIM_ID_PATTERN
TIP_PATTERN = protocol.COMMIT_PATTERN
# `land` is a stage the lane dispatches after its runs, never one a run ran.
RAN_STAGES = tuple(stage for stage in RoutingStage if stage is not RoutingStage.LAND)
_RUNS_FIELDS = ("version", "runs")
_ENTRY_FIELDS = ("run", "start_tip", "follows")
_ADDED_FIELDS = ("end_tip", "ran", "record")


class RunsAction(StrEnum):
    """What a command does to the runs, as a refusal names it."""

    BEGIN = "begin a run of"
    ADD = "add a run to"


@dataclass(frozen=True)
class RunAdded:
    """What an add stores on a begun run: the tip the run ended at, the stages that ran and the
    record its file stated."""

    end_tip: str
    ran: tuple[RoutingStage, ...]
    record: lane_record.LaneRecordFile


@dataclass(frozen=True)
class RunEntry:
    """One run in begin order: `follows` is judged once, at its begin."""

    run: str
    start_tip: str | None
    follows: bool
    added: RunAdded | None = None


@dataclass(frozen=True)
class RunsFile:
    runs: tuple[RunEntry, ...] = ()

    def entry(self, run: str) -> RunEntry | None:
        return next((entry for entry in self.runs if entry.run == run), None)

    def newest(self) -> RunEntry | None:
        return self.runs[-1] if self.runs else None

    def added_count(self) -> int:
        return sum(entry.added is not None for entry in self.runs)


class RunsFileError(Exception):
    """The first thing wrong with a stored runs file."""


class RunsRefusedError(protocol.ClaimUnavailableError):
    """A begin or an add the stored runs do not allow."""


def _no_repeated_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("a key stated twice")
    return dict(pairs)


def parse_runs(content: bytes) -> RunsFile:
    """The runs file whose bytes are `content`, validated whole: one that is not exactly the
    stored shape raises `RunsFileError`."""
    try:
        raw = json.loads(content, object_pairs_hook=_no_repeated_keys)
    except (ValueError, RecursionError) as error:
        raise RunsFileError("not valid JSON") from error
    fields = _members(raw, "the runs file", _RUNS_FIELDS)
    version = fields["version"]
    if type(version) is not int or version != RUNS_FILE_VERSION:
        raise RunsFileError(f"version must be the whole number {RUNS_FILE_VERSION}")
    listed = fields["runs"]
    if not isinstance(listed, list):
        raise RunsFileError("runs must be a list")
    entries = tuple(
        _entry(item, f"runs[{position}]")
        for position, item in enumerate(cast(list[object], listed))
    )
    if len({entry.run for entry in entries}) != len(entries):
        raise RunsFileError("a run is stored twice")
    return RunsFile(entries)


def _members(
    value: object, where: str, required: Collection[str], optional: Collection[str] = ()
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RunsFileError(f"{where} must be an object")
    members = cast(dict[str, object], value)
    unknown = members.keys() - set(required) - set(optional)
    if unknown:
        raise RunsFileError(f"{where} has an unknown key {min(unknown)!r}")
    missing = set(required) - members.keys()
    if missing:
        raise RunsFileError(f"{where} lacks {min(missing)!r}")
    return members


def _tip(value: object, where: str) -> str:
    if not isinstance(value, str) or TIP_PATTERN.fullmatch(value) is None:
        raise RunsFileError(f"{where} must be a full 40-digit commit sha")
    return value


def _entry(value: object, where: str) -> RunEntry:
    members = _members(value, where, _ENTRY_FIELDS, _ADDED_FIELDS)
    run = members["run"]
    if not isinstance(run, str) or RUN_ID_PATTERN.fullmatch(run) is None:
        raise RunsFileError(f"{where}.run must be a run id")
    start_tip = members["start_tip"]
    follows = members["follows"]
    if not isinstance(follows, bool):
        raise RunsFileError(f"{where}.follows must be true or false")
    stored = [name for name in _ADDED_FIELDS if name in members]
    if stored and len(stored) != len(_ADDED_FIELDS):
        raise RunsFileError(f"{where} states only some of {', '.join(_ADDED_FIELDS)}")
    return RunEntry(
        run=run,
        start_tip=None if start_tip is None else _tip(start_tip, f"{where}.start_tip"),
        follows=follows,
        added=_added(members, where) if stored else None,
    )


def _added(members: Mapping[str, object], where: str) -> RunAdded:
    ran = members["ran"]
    stages = tuple(cast(list[object], ran)) if isinstance(ran, list) else ()
    if (
        not stages
        or not all(isinstance(stage, str) and stage in RAN_STAGES for stage in stages)
        or len(set(stages)) != len(stages)
    ):
        raise RunsFileError(f"{where}.ran must list each stage that ran once")
    try:
        record = lane_record.parse_record_file(json.dumps(members["record"]).encode())
    except lane_record.RecordFileError as error:
        raise RunsFileError(f"{where}.record {error}") from error
    return RunAdded(
        end_tip=_tip(members["end_tip"], f"{where}.end_tip"),
        ran=tuple(RoutingStage(stage) for stage in cast(list[str], stages)),
        record=record,
    )


def serialize_runs(runs: RunsFile) -> bytes:
    """`runs` as the bytes of its file."""
    stored = {
        "version": RUNS_FILE_VERSION,
        "runs": [_entry_object(entry) for entry in runs.runs],
    }
    return (json.dumps(stored, indent=2) + "\n").encode()


def _entry_object(entry: RunEntry) -> dict[str, object]:
    stored: dict[str, object] = {
        "run": entry.run,
        "start_tip": entry.start_tip,
        "follows": entry.follows,
    }
    if entry.added is not None:
        stored["end_tip"] = entry.added.end_tip
        stored["ran"] = [str(stage) for stage in entry.added.ran]
        stored["record"] = record_object(entry.added.record)
    return stored


def record_object(record: lane_record.LaneRecordFile) -> dict[str, object]:
    """The record as its file states it: a key the file omitted is absent."""
    stored: dict[str, object] = {
        "version": lane_record.RECORD_FILE_VERSION,
        "stages": {str(stage): choice for stage, choice in record.stages.items()},
        "fix_rounds": {str(stage): count for stage, count in record.fix_rounds.items()},
        "blocking": {str(stage): count for stage, count in record.blocking.items()},
    }
    if record.misses is not None:
        stored["misses"] = {str(stage): count for stage, count in record.misses.items()}
    stored["verdicts"] = [
        {"stage": str(judged.stage), "verdict": str(judged.verdict), "sha": judged.sha}
        for judged in record.verdicts
    ]
    for name in ("risk", "experiment"):
        tag = getattr(record, name)
        if tag is not None:
            stored[name] = tag
    return stored


def _sequence(runs: RunsFile) -> tuple[RunAdded | None, ...]:
    """The runs the lane is made of, in begin order, `None` for a lost run: one stands before
    each entry that does not follow, and an entry without a record is one."""
    elements: list[RunAdded | None] = []
    for entry in runs.runs:
        if not entry.follows:
            elements.append(None)
        elements.append(entry.added)
    return tuple(elements)


def is_complete(runs: RunsFile) -> bool:
    """Whether the lane holds no lost run, judged now as a release would judge it."""
    return None not in _sequence(runs)


def _stage_figure(sequence: Sequence[RunAdded | None], stage: RoutingStage) -> str | None:
    """The stage's choice from the element that decides it: the first run that ran `build`, the
    last that ran any other stage. A lost run decides too, and its choice is unknown; where no run
    ran the stage, the choice is `none` if the stage may be, else unknown."""
    ran = [element for element in sequence if element is None or stage in element.ran]
    if not ran:
        return NO_STAGE if stage_choice_fits(stage, NO_STAGE) else None
    decisive = ran[0] if stage is RoutingStage.BUILD else ran[-1]
    return None if decisive is None else decisive.record.stages[stage]


def _land_figure(newest: RunEntry | None) -> str | None:
    """The newest entry's `land` choice; unknown without a record."""
    if newest is None or newest.added is None:
        return None
    return newest.added.record.stages[RoutingStage.LAND]


def _total(counts: Iterable[int | None]) -> int | None:
    stated = list(counts)
    return None if None in stated else min(sum(cast(list[int], stated)), lane_record.MAXIMUM_COUNT)


def _counts(
    sequence: Sequence[RunAdded | None],
) -> dict[lane_record.FindingStage, lane_record.StageCounts]:
    """The counts summed over the known records and clamped; all unknown when a run is lost, and
    the misses unknown when a known record states none."""
    if None in sequence:
        return dict.fromkeys(lane_record.FindingStage, lane_record.StageCounts(None, None, None))
    stated = [element.record.stage_counts() for element in sequence if element is not None]
    return {
        stage: lane_record.StageCounts(
            _total(counts[stage].fix_rounds for counts in stated),
            _total(counts[stage].blocking for counts in stated),
            _total(counts[stage].misses for counts in stated),
        )
        for stage in lane_record.FindingStage
    }


def lane_figures(runs: RunsFile) -> lane_record.LaneFigures:
    """The figures of the lane the stored `runs` make up, for a lane with at least one entry:
    which stages a run ran comes from its `ran`, never from its record's slots, and aco counts no
    miss of its own."""
    sequence = _sequence(runs)
    known = [element.record for element in sequence if element is not None]
    newest = runs.newest()
    stages = {stage: _stage_figure(sequence, stage) for stage in RAN_STAGES}
    stages[RoutingStage.LAND] = _land_figure(newest)
    tags = {record.experiment for record in known}
    return lane_record.LaneFigures(
        stages=stages,
        risk=None if newest is None or newest.added is None else newest.added.record.risk,
        experiment=tags.pop() if len(tags) == 1 and None not in sequence else None,
        counts=_counts(sequence),
        verdicts=tuple(judged for record in known for judged in record.verdicts),
    )


def end_tip_to_follow(runs: RunsFile) -> str | None:
    """The end tip a run begun now must descend from to follow: the newest stored run's, `None`
    while there is none or it has not been added yet."""
    newest = runs.newest()
    return None if newest is None or newest.added is None else newest.added.end_tip


def follows(earlier: RunEntry | None, start_tip: str | None, *, descends: bool) -> bool:
    """Whether a run begun at `start_tip` follows `earlier`, the newest stored run: the first run
    without a start tip does, and a later one when `earlier` ended at its start tip or at an
    ancestor of it (`descends`, which git answers). A tip git cannot read does not descend."""
    if earlier is None:
        return start_tip is None
    return earlier.added is not None and start_tip is not None and descends


@dataclass(frozen=True)
class Merged:
    """The runs after a merge, and whether the merge changed them."""

    runs: RunsFile
    changed: bool


def _tip_text(tip: str | None) -> str:
    return "none" if tip is None else tip


def begin(runs: RunsFile, *, run: str, start_tip: str | None, follows: bool, label: str) -> Merged:
    """`runs` with `run` begun at `start_tip`; `follows` is stored only for a run not begun
    yet. The same begin again changes nothing; another start tip, or a begin after the run's
    add, refuses."""
    existing = runs.entry(run)
    if existing is None:
        return Merged(RunsFile((*runs.runs, RunEntry(run, start_tip, follows))), changed=True)
    if existing.added is not None:
        raise RunsRefusedError(f"run {run} of {label} was added already; it cannot be begun again")
    if existing.start_tip != start_tip:
        raise RunsRefusedError(
            f"run {run} of {label} was begun with start tip {_tip_text(existing.start_tip)}, "
            f"not {_tip_text(start_tip)}"
        )
    return Merged(runs, changed=False)


def add(runs: RunsFile, *, run: str, added: RunAdded, label: str) -> Merged:
    """`runs` with `added` stored on the begun `run`. The same entry again changes nothing;
    another entry under an added run, and a run not begun, refuse."""
    existing = runs.entry(run)
    if existing is None:
        raise RunsRefusedError(
            f"run {run} of {label} was not begun; run aco lane-record begin first"
        )
    if existing.added is None:
        stored = tuple(
            replace(entry, added=added) if entry is existing else entry for entry in runs.runs
        )
        return Merged(RunsFile(stored), changed=True)
    if existing.added != added:
        raise RunsRefusedError(f"run {run} of {label} has another entry stored already")
    return Merged(runs, changed=False)


def require_ran_stages_run(record: lane_record.LaneRecordFile, ran: Sequence[RoutingStage]) -> None:
    """Refuse a `--ran` stage whose slot in the record is `none`."""
    for stage in ran:
        if record.stages[stage] == NO_STAGE:
            raise RunsRefusedError(f"the record's stage {stage} is none, which --ran contradicts")


def _holder_sentence(action: RunsAction, label: str, session: str, holder: str) -> str:
    return f"only the holder may {action} {label} (holder={holder!r}, this session={session!r})"


def holder_refusal(action: RunsAction, label: str, *, session: str) -> Callable[[str], str]:
    """The refusal of `session` as a non-holder of `label`, as a function of the holder."""
    return partial(_holder_sentence, action, label, session)


def stale_refusal(label: str) -> str:
    return (
        f"the stored runs of {label} were written since this command read them; "
        "run the same command again"
    )
