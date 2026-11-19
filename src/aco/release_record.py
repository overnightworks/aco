"""The subject a release commits, with the lane record in its trailers
(`specs/lane-record.spec.md`)."""

import dataclasses
from dataclasses import dataclass

from . import body, forge, lane_record, protocol, store
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


def release_subject(
    context: RunContext,
    claim: protocol.ActiveClaim,
    outcome: protocol.ReleaseOutcome,
    evidence: ReleaseEvidence,
) -> store.TransitionSubject:
    """The release transition's subject for `claim`, carrying its lane record."""
    released = lane_record.ReleasedLane(
        claim,
        outcome,
        _merge_commit(outcome, evidence.verified_merge),
        int(context.now().timestamp()),
        context.observation.tip,
        _declared_size(evidence.item, context.config.storage),
        evidence.record_file,
    )
    record = lane_record.compute_record(context.toplevel, context.config, released)
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
