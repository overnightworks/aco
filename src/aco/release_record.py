"""The subject a release commits, with the lane record in its trailers
(`specs/lane-record.spec.md`), and the stored runs it computed that record from."""

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from . import body, forge, lane_record, lane_runs, protocol, state_runs, store
from .session import RunContext


@dataclass(frozen=True)
class ReleaseEvidence:
    """What a release holds beyond its claim and outcome: `verified_merge` is the merge commit
    the forge's landing was verified to have (a github `--merged` release reads it nowhere
    else), `item` the work item the landing release already read, whose body declares the size,
    `record_file` the lane record file the release was given."""

    verified_merge: str | None = None
    item: forge.ItemReference | None = None
    record_file: lane_record.LaneRecordFile | None = None


class ReleaseWrite(NamedTuple):
    """The transition a release writes: its subject, and its intent carrying the runs file the
    record was computed from."""

    subject: store.TransitionSubject
    intent: protocol.ReleaseIntent | protocol.LandingIntent


@dataclass(frozen=True)
class _StoredRuns:
    """The runs file of a claim as the release read it: its blob, and the figures it states
    (`None` where the claim stores no run)."""

    blob: protocol.ObjectId | None
    figures: lane_record.LaneFigures | None


def release_write(
    context: RunContext,
    claim: protocol.ActiveClaim,
    outcome: protocol.ReleaseOutcome,
    evidence: ReleaseEvidence,
    intent: protocol.ReleaseIntent | protocol.LandingIntent,
) -> ReleaseWrite:
    """The release transition for `claim`: its subject carries the lane record, and `intent` the
    runs file that record was computed from."""
    stored = _stored_runs(context, claim)
    released = lane_record.ReleasedLane(
        claim,
        outcome,
        _merge_commit(outcome, evidence.verified_merge),
        int(context.now().timestamp()),
        context.observation.tip,
        _declared_size(evidence.item, context.config.storage),
        _stated_figures(claim, stored.figures, evidence.record_file),
    )
    record = lane_record.compute_record(context.toplevel, context.config, released)
    subject = store.transition_subject("release", claim.identity, claim.branch)
    return ReleaseWrite(
        dataclasses.replace(subject, trailers=record.trailers(), committed_at=released.released_at),
        dataclasses.replace(intent, expected_runs=stored.blob),
    )


def _stored_runs(context: RunContext, claim: protocol.ActiveClaim) -> _StoredRuns:
    """The runs file the observation holds for `claim`: one that cannot be read states every
    figure unknown, as an unreadable routing line does, since no command could release a claim
    it refused."""
    blob = context.observation.runs.get(claim.claim_id)
    if blob is None:
        return _StoredRuns(None, None)
    try:
        runs = lane_runs.parse_runs(state_runs.read_runs_file(context.toplevel, blob))
    except lane_runs.RunsFileError, protocol.ClaimError:
        return _StoredRuns(blob, lane_record.UNKNOWN_FIGURES)
    return _StoredRuns(blob, lane_runs.lane_figures(runs) if runs.holds_runs() else None)


def _stated_figures(
    claim: protocol.ActiveClaim,
    stored: lane_record.LaneFigures | None,
    record_file: lane_record.LaneRecordFile | None,
) -> lane_record.LaneFigures | None:
    """The figures the release states: the stored runs', else the record file's, else none (the
    routing line is read); both refuse."""
    if stored is None:
        return None if record_file is None else record_file.figures()
    _refuse_record_file_beside_runs(claim, record_file)
    return stored


def _refuse_record_file_beside_runs(
    claim: protocol.ActiveClaim, record_file: lane_record.LaneRecordFile | None
) -> None:
    if record_file is not None:
        raise protocol.ClaimUnavailableError(
            naming=lambda item_label: (
                f"{protocol.claim_label(claim, item_label)} has stored runs, "
                "so aco computes its record from them; drop --record"
            )
        )


def require_landable_runs(
    toplevel: Path,
    observed: protocol.ClaimState,
    branch: str,
    record_file: lane_record.LaneRecordFile | None,
    reviewed: str,
) -> None:
    """Refuse a landing of `branch` before it merges anything when a live claim on it stores
    runs that cannot be read (LANREC-62), runs beside `--record` (LANREC-91), or runs whose last
    verdict is none, not on `reviewed` or no approval; a claim without runs judges nothing here
    (`specs/lane-record.spec.md`, "Landing with stored runs")."""
    for claim in protocol.claims_on_branch(observed.claims, branch):
        blob = observed.runs.get(claim.claim_id)
        if blob is None:
            continue
        label = protocol.claim_label(claim, protocol.forge_item_label)
        runs = lane_runs.read_stored_runs(toplevel, blob, label)
        if runs.holds_runs():
            _refuse_record_file_beside_runs(claim, record_file)
            lane_record.require_landable_verdicts(lane_runs.lane_figures(runs).verdicts, reviewed)


def _merge_commit(outcome: protocol.ReleaseOutcome, verified_merge: str | None) -> str | None:
    return outcome.commit if isinstance(outcome, protocol.LandedRelease) else verified_merge


def _declared_size(item: forge.ItemReference | None, storage: body.Storage) -> body.Size | None:
    if item is None or item.body is None:
        return None
    return body.parse_body(item.body, storage=storage).size
