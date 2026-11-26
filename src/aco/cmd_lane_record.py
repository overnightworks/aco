"""The `lane-record` command (`specs/lane-record.spec.md`)."""
# ruff: noqa: T201 - the lane-record command writes its result line to stdout

import argparse
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import partial
from pathlib import Path

from . import (
    checkout,
    lane_record,
    lane_runs,
    protocol,
    refusal_text,
    report,
    store,
    usage,
    workboard,
)
from .routing_line import RoutingStage
from .session import RunContext

_INVALID = "lane record {foreign} is invalid: {defect}"
# A value the file states is cut to this, so the refusal keeps its own words and the file's path
# keeps room on one bounded line.
_STATED_VALUE_LENGTH_LIMIT = 40
_COMMIT_SUBJECT = "lane-record"
_RUN_TRAILER = "run"


class _RunsReason(StrEnum):
    """`aco lane-record begin`, `add` and `show`'s own `--json` `reason` vocabulary
    (`specs/lane-record.spec.md`): `begun`, `already_begun`, `added`, `already_added` and `shown`
    are the successes; `precondition_failed` is a claim, a holder or a stored run that does not
    allow the command, `invalid_usage` a command naming both an item and a branch or neither,
    every other refusal `unavailable`."""

    BEGUN = "begun"
    ALREADY_BEGUN = "already_begun"
    ADDED = "added"
    ALREADY_ADDED = "already_added"
    SHOWN = "shown"
    PRECONDITION_FAILED = "precondition_failed"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


class _RunsUsageError(protocol.ClaimError):
    """A begin, an add or a show that names both an item and a branch, or neither."""


_REFUSAL_REASONS: report.RefusalReasons[_RunsReason] = (
    (lane_runs.RunsRefusedError, _RunsReason.PRECONDITION_FAILED),
    (_RunsUsageError, _RunsReason.INVALID_USAGE),
)


def read_record_file(path_text: str) -> lane_record.LaneRecordFile:
    """The lane record file at `path_text`, read once and validated whole; one that is not
    exactly what the spec states refuses, naming the first thing wrong with it."""
    try:
        with Path(path_text).open("rb") as record_file:
            content = record_file.read(lane_record.RECORD_FILE_BYTES_LIMIT + 1)
        if len(content) > lane_record.RECORD_FILE_BYTES_LIMIT:
            defect = f"cannot be read (larger than {lane_record.RECORD_FILE_BYTES_LIMIT} bytes)"
        else:
            return lane_record.parse_record_file(content)
    except OSError as error:
        defect = f"cannot be read ({error.strerror})"
    except lane_record.RecordFileError as error:
        stated = refusal_text.cut_foreign_text(error.stated, _STATED_VALUE_LENGTH_LIMIT)
        defect = error.before + stated
    raise protocol.ClaimUnavailableError(
        report.refusal_around_foreign_path(_INVALID, path_text, defect=defect)
    )


def add_record_argument(command: argparse.ArgumentParser, *, writes: str) -> None:
    """`--record FILE` of a command that `writes` a release: the file is read and validated by
    the argument parse, so a malformed one refuses before the command reads or writes anything."""
    command.add_argument(
        "--record",
        metavar="FILE",
        type=read_record_file,
        help=f"the lane record file whose figures {writes}; a malformed file refuses",
    )


def _run_id(value: str) -> str:
    if lane_runs.RUN_ID_PATTERN.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a run id: 1 to 128 letters, digits, '.', '_' or '-', "
            "starting with a letter or digit"
        )
    return value


def _tip(value: str) -> str:
    if lane_runs.TIP_PATTERN.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(f"{value!r} is not a full 40-digit lowercase commit sha")
    return value


class _StagesAction(argparse.Action):
    """`--ran`: each stage that ran, once, all after one occurrence of the flag."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[str] | None,
        option_string: str | None = None,
    ) -> None:
        if getattr(namespace, self.dest, None) is not None:
            raise argparse.ArgumentError(self, "is given once, followed by every stage that ran")
        stages = tuple(RoutingStage(stage) for stage in values or ())
        repeated = next((stage for stage in stages if stages.count(stage) > 1), None)
        if repeated is not None:
            raise argparse.ArgumentError(self, f"the stage {repeated} is named twice")
        setattr(namespace, self.dest, stages)


class _ItemAndFileAction(argparse.Action):
    """`add`'s operands: the file alone, or the item and then the file."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[str] | None,
        option_string: str | None = None,
    ) -> None:
        *item, file = list(values or ())
        if len(item) > 1:
            raise argparse.ArgumentError(
                self, "is the file, after the item unless --branch is given"
            )
        namespace.item = workboard.parse_item_reference(item[0]) if item else None
        namespace.file = file


def _add_branch_argument(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--branch",
        help="the branch of the claimed issue-less lane, in place of the item",
    )


def _add_item_argument(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "item",
        nargs="?",
        type=workboard.parse_item_reference,
        help="the claimed item; give it or --branch",
    )
    _add_branch_argument(command)


def _add_run_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--run", required=True, type=_run_id, help="the run's id")
    command.add_argument("--agent", help="the acting agent's name; it must hold the claim")
    report.add_json_flag(command)


def add_parser(commands: usage.Subcommands, name: str) -> None:
    command = commands.add_parser(
        name,
        help="check a lane record file, store a run of a claimed lane with its claim, or show them",
    )
    command.subcommands = usage.Subcommands(command, "lane_record_command")
    check = command.subcommands.add_parser(
        "check", help="say whether FILE is a valid lane record file, and why not"
    )
    check.add_argument("file", metavar="FILE", help="the lane record file to check")
    begin = command.subcommands.add_parser(
        "begin", help="mark a run of a claimed item or lane, as its holder"
    )
    _add_item_argument(begin)
    _add_run_arguments(begin)
    begin.add_argument("--start-tip", type=_tip, help="the commit the run starts from")
    add = command.subcommands.add_parser(
        "add", help="store the lane record of a begun run with its claim, as its holder"
    )
    add.add_argument(
        "operands",
        nargs="+",
        action=_ItemAndFileAction,
        metavar=("ITEM_OR_FILE", "FILE"),
        help="the claimed item then the lane record file; the file alone with --branch",
    )
    _add_branch_argument(add)
    _add_run_arguments(add)
    add.add_argument("--end-tip", required=True, type=_tip, help="the commit the run ended at")
    add.add_argument(
        "--ran",
        required=True,
        nargs="+",
        action=_StagesAction,
        choices=[str(stage) for stage in lane_runs.RAN_STAGES],
        help="each stage the run ran, once",
    )
    show = command.subcommands.add_parser(
        "show", help="print the runs stored with a claim and the lane figures computed from them"
    )
    _add_item_argument(show)
    report.add_json_flag(show)


@dataclass(frozen=True)
class _ClaimRuns:
    """The runs a claim holds as one begin or add read them, and the write that replaces them."""

    context: RunContext
    claim: protocol.ActiveClaim
    agent: str
    action: lane_runs.RunsAction
    label: str
    runs: lane_runs.RunsFile
    stored: protocol.ObjectId | None

    def write(self, runs: lane_runs.RunsFile, *, run: str) -> None:
        intent = protocol.RunsWriteIntent(
            claim_id=self.claim.claim_id,
            agent=self.agent,
            expected=self.stored,
            new_oid=store.hash_blob(self.context.toplevel, lane_runs.serialize_runs(runs)),
            operation_id=uuid.uuid4().hex,
            holder_refusal=lane_runs.holder_refusal(self.action, self.label, session=self.agent),
            stale_refusal=protocol.stale_runs_sentence(self.label),
        )
        subject = store.transition_subject(_COMMIT_SUBJECT, self.claim.identity, self.claim.branch)
        self.context.transition(
            replace(subject, trailers=(f"{_RUN_TRAILER}: {run}",)),
            intent,
        )


def _session_agent(parsed: argparse.Namespace) -> str:
    """The acting agent's name; a command with none refuses before it reads anything."""
    try:
        return checkout.resolved_agent(parsed.agent)
    except protocol.ClaimError as error:
        raise lane_runs.RunsRefusedError(str(error)) from error


@dataclass(frozen=True)
class _LiveClaim:
    """The live claim of an item or lane, its label and the oid of the runs stored with it."""

    claim: protocol.ActiveClaim
    label: str
    stored: protocol.ObjectId | None


def _require_one_target(parsed: argparse.Namespace) -> None:
    if (parsed.item is None) == (parsed.branch is None):
        raise _RunsUsageError(usage.ITEM_OR_BRANCH_SENTENCE)


def _live_claim(parsed: argparse.Namespace, context: RunContext) -> _LiveClaim:
    """The live claim of the item or lane the command names, whoever holds it; one without a
    claim refuses."""
    try:
        storage = context.config.storage
        if parsed.branch is None:
            label = workboard.item_label(parsed.item, storage)
            identity: protocol.ClaimIdentity = protocol.IssueIdentity(parsed.item)
        else:
            label = f"lane {parsed.branch}"
            identity = protocol.LaneIdentity()
        claim = workboard.selected_store_claim(
            context.observation, identity, parsed.branch, None, storage
        )
    except protocol.ClaimError as error:
        raise lane_runs.RunsRefusedError(str(error)) from error
    return _LiveClaim(claim, label, context.observation.runs.get(claim.claim_id))


def _open_runs(
    parsed: argparse.Namespace, context: RunContext, action: lane_runs.RunsAction, agent: str
) -> _ClaimRuns:
    """The runs of the item's claim, for the session `agent` that holds it; any other refuses
    before the stored runs are read."""
    live = _live_claim(parsed, context)
    if live.claim.agent != agent:
        raise lane_runs.RunsRefusedError(
            lane_runs.holder_refusal(action, live.label, session=agent)(live.claim.agent)
        )
    runs = _stored_runs(context, live)
    return _ClaimRuns(context, live.claim, agent, action, live.label, runs, live.stored)


def _stored_runs(context: RunContext, live: _LiveClaim) -> lane_runs.RunsFile:
    """The runs stored with `live`, none when it stores none; unusable ones are unavailable."""
    if live.stored is None:
        return lane_runs.RunsFile()
    return lane_runs.read_stored_runs(context.toplevel, live.stored, live.label)


def _descends(directory: Path, ancestor: str, tip: str) -> bool:
    """Whether `ancestor` is `tip` or one of its ancestors; a commit git cannot read is none."""
    try:
        checkout.git_output(["merge-base", "--is-ancestor", ancestor, tip], directory=directory)
    except checkout.GitExitError:
        return False
    return True


def _follows(opened: _ClaimRuns, start_tip: str | None) -> bool:
    earlier_end = lane_runs.end_tip_to_follow(opened.runs)
    descends = (
        earlier_end is not None
        and start_tip is not None
        and _descends(opened.context.toplevel, earlier_end, start_tip)
    )
    return lane_runs.follows(opened.runs.newest(), start_tip, descends=descends)


def _begin(parsed: argparse.Namespace, context: RunContext) -> int:
    opened = _open_runs(parsed, context, lane_runs.RunsAction.BEGIN, _session_agent(parsed))
    merged = lane_runs.begin(
        opened.runs,
        run=parsed.run,
        start_tip=parsed.start_tip,
        follows=_follows(opened, parsed.start_tip),
        label=opened.label,
    )
    if merged.changed:
        opened.write(merged.runs, run=parsed.run)
    entry = merged.runs.entry(parsed.run)
    assert entry is not None  # noqa: S101 - a begin stores the run or finds it stored
    if parsed.json:
        reason = _RunsReason.BEGUN if merged.changed else _RunsReason.ALREADY_BEGUN
        report.emit_json(
            True,
            reason,
            item=parsed.item,
            branch=opened.claim.branch,
            run=entry.run,
            follows=entry.follows,
        )
    else:
        verb = "BEGAN" if merged.changed else "ALREADY BEGUN"
        print(f"{verb} run {parsed.run} of {opened.label}")
    return 0


def _add(parsed: argparse.Namespace, context: RunContext) -> int:
    agent = _session_agent(parsed)
    try:
        record = read_record_file(parsed.file)
    except protocol.ClaimUnavailableError as error:
        raise lane_runs.RunsRefusedError(str(error)) from error
    lane_runs.require_ran_stages_run(record, parsed.ran)
    opened = _open_runs(parsed, context, lane_runs.RunsAction.ADD, agent)
    added = lane_runs.RunAdded(parsed.end_tip, parsed.ran, record)
    merged = lane_runs.add(opened.runs, run=parsed.run, added=added, label=opened.label)
    if merged.changed:
        opened.write(merged.runs, run=parsed.run)
    stored = merged.runs.added_count()
    if parsed.json:
        reason = _RunsReason.ADDED if merged.changed else _RunsReason.ALREADY_ADDED
        report.emit_json(
            True,
            reason,
            item=parsed.item,
            branch=opened.claim.branch,
            run=parsed.run,
            stored=stored,
        )
    else:
        verb = "ADDED" if merged.changed else "ALREADY ADDED"
        print(f"{verb} run {parsed.run} to {opened.label}: {stored} stored")
    return 0


def _run_object(entry: lane_runs.RunEntry) -> dict[str, object]:
    added = entry.added
    return {
        "run": entry.run,
        "start_tip": entry.start_tip,
        "follows": entry.follows,
        "end_tip": None if added is None else added.end_tip,
        "ran": None if added is None else [str(stage) for stage in added.ran],
        "record": None if added is None else lane_runs.record_object(added.record),
    }


def _counts_object(figures: lane_record.LaneFigures, kind: str) -> dict[str, int] | None:
    """One count kind per finding stage: a whole object, or `None` when a stage's is unknown."""
    counts = {str(stage): getattr(figures.counts[stage], kind) for stage in figures.counts}
    return None if None in counts.values() else counts


def _lane_object(figures: lane_record.LaneFigures) -> dict[str, object]:
    return {
        "stages": {str(stage): choice for stage, choice in figures.stages.items()},
        "fix_rounds": _counts_object(figures, "fix_rounds"),
        "blocking": _counts_object(figures, "blocking"),
        "misses": _counts_object(figures, "misses"),
        "verdicts": lane_runs.verdict_objects(figures.verdicts),
        "risk": figures.risk,
        "experiment": figures.experiment,
    }


def _compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def _run_line(entry: lane_runs.RunEntry, label: str) -> str:
    added = entry.added
    recorded = "no record" if added is None else f"end {added.end_tip}, ran {' '.join(added.ran)}"
    follows = "follows" if entry.follows else "does not follow"
    return f"run {entry.run} of {label}: start {entry.start_tip or 'none'}, {recorded}, {follows}"


def _print_shown(label: str, runs: lane_runs.RunsFile, lane: Mapping[str, object]) -> None:
    for entry in runs.runs:
        print(_run_line(entry, label))
        if entry.added is not None:
            print(f"  record {_compact(lane_runs.record_object(entry.added.record))}")
    state = "complete" if lane_runs.is_complete(runs) else "incomplete"
    print(f"lane {label}: {state}")
    print(f"  record {_compact(lane)}")


def _show(parsed: argparse.Namespace, context: RunContext) -> int:
    live = _live_claim(parsed, context)
    stored = _stored_runs(context, live)
    shown = stored.holds_runs()
    lane = _lane_object(lane_runs.lane_figures(stored)) if shown else None
    if parsed.json:
        report.emit_json(
            True,
            _RunsReason.SHOWN,
            item=parsed.item,
            branch=live.claim.branch,
            claim_id=live.claim.claim_id,
            runs=[_run_object(entry) for entry in stored.runs],
            complete=lane_runs.is_complete(stored) if shown else None,
            lane=lane,
        )
    elif lane is None:
        print(f"{live.label} has no stored runs")
    else:
        _print_shown(live.label, stored, lane)
    return 0


_RUNS_COMMANDS = {"begin": _begin, "add": _add, "show": _show}


def _run_naming_one_target(
    work: Callable[[argparse.Namespace, RunContext], int],
    parsed: argparse.Namespace,
    context: RunContext,
) -> int:
    _require_one_target(parsed)
    return work(parsed, context)


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    work = _RUNS_COMMANDS.get(parsed.lane_record_command)
    if work is not None:
        return report.refusing_by_type(
            partial(_run_naming_one_target, work, parsed, context),
            _REFUSAL_REASONS,
            _RunsReason.UNAVAILABLE,
            as_json=parsed.json,
        )
    read_record_file(parsed.file)
    print(f"lane record {protocol.terminal_text(parsed.file)} is valid")
    return 0
