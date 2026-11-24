"""The lane record of a release run against an in-memory store."""

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from aco import forge, lane_record, protocol, release_record, store, workboard
from aco.routing_line import RoutingStage
from aco.session import RunContext

LANE_BRANCH = "docs/tidy-readme"
ROUTING = (
    "Routing: build sonnet-5.5/high; fix none; review opus-5.5/medium; test sonnet-5.5/medium; "
    "gate none; land haiku-5.5/low. Fix rounds: 1. Experiment: builder-sonnet. "
    "Blocking: a red check → ci"
)


def stub_lane_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """An in-memory store holds no state-ref commit, and a faked git answers no commit read,
    so its releases carry no lane record; `test_lane_record.py` drives the real one."""

    def plain_write(
        _context: object,
        claim: protocol.ActiveClaim,
        _outcome: protocol.ReleaseOutcome,
        _evidence: release_record.ReleaseEvidence,
        intent: protocol.ReleaseIntent | protocol.LandingIntent,
    ) -> release_record.ReleaseWrite:
        subject = store.transition_subject("release", claim.identity, claim.branch)
        return release_record.ReleaseWrite(subject, intent)

    monkeypatch.setattr(release_record, "release_write", plain_write)


def release_written_of(
    *,
    toplevel: Path,
    config: workboard.BoardConfig,
    tip: str | None,
    now: datetime,
    claim: protocol.ActiveClaim,
    outcome: protocol.ReleaseOutcome,
    verified_merge: str | None = None,
    item: forge.ItemReference | None = None,
    record_file: lane_record.LaneRecordFile | None = None,
    stored_runs: Mapping[str, protocol.ObjectId] | None = None,
) -> release_record.ReleaseWrite:
    """What `release_write` writes for the release of `claim`, whose observation holds the
    runs blobs of `stored_runs` by claim id (none by default); its context holds no forge, so a
    read of one fails the test."""
    context = SimpleNamespace(
        toplevel=toplevel,
        config=config,
        observation=SimpleNamespace(tip=tip, runs=stored_runs or {}),
        now=lambda: now,
    )
    evidence = release_record.ReleaseEvidence(verified_merge, item, record_file)
    intent = protocol.ReleaseIntent(
        claim_id=claim.claim_id,
        agent=claim.agent,
        role=claim.role,
        outcome=outcome,
        operation_id="op-release",
    )

    return release_record.release_write(cast(RunContext, context), claim, outcome, evidence, intent)


def release_trailers_of(
    *,
    toplevel: Path,
    config: workboard.BoardConfig,
    tip: str | None,
    now: datetime,
    claim: protocol.ActiveClaim,
    outcome: protocol.ReleaseOutcome,
    verified_merge: str | None = None,
    item: forge.ItemReference | None = None,
) -> tuple[str, ...]:
    """The trailers a release of `claim` that stores no runs writes."""
    return release_written_of(
        toplevel=toplevel,
        config=config,
        tip=tip,
        now=now,
        claim=claim,
        outcome=outcome,
        verified_merge=verified_merge,
        item=item,
    ).subject.trailers


JUDGED_SHA = "c" * 40
UNKNOWN = None


def marked(marker: str) -> dict[str, str]:
    """The stage slots of one stated record, every choice carrying `marker`."""
    return {stage: f"{stage}-{marker}/low" for stage in RoutingStage}


def four(review: int, gate: int, ci: int, test: int) -> dict[str, int]:
    """The four finding-stage counts of a record."""
    return {"review": review, "gate": gate, "ci": ci, "test": test}


def lane_record_object(**changes: object) -> dict[str, object]:
    """A valid lane record file's content, one top-level field replaced by each change."""
    record: dict[str, object] = {
        "version": 1,
        "stages": {
            "build": "sonnet-5.5/high",
            "fix": "none",
            "review": "opus-5.5/medium",
            "test": "sonnet-5.5/medium",
            "gate": "none",
            "land": "haiku-5.5/low",
        },
        "fix_rounds": {"review": 1, "gate": 0, "ci": 2, "test": 0},
        "blocking": {"review": 3, "gate": 0, "ci": 1, "test": 0},
        "misses": {"review": 0, "gate": 0, "ci": 1, "test": 0},
        "verdicts": [
            {"stage": "review", "verdict": "revise", "sha": "b" * 40},
            {"stage": "review", "verdict": "approve", "sha": JUDGED_SHA},
        ],
        "risk": "normal",
        "experiment": "builder-sonnet",
    }
    return {**record, **changes}


def write_lane_record_file(directory: Path, content: object) -> Path:
    """`content` as the JSON file `directory/lane-record.json`, which is returned."""
    path = directory / "lane-record.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


LANE_RECORD_TRAILERS = (
    "lane_build: sonnet-5.5/high",
    "lane_fix: none",
    "lane_review: opus-5.5/medium",
    "lane_test: sonnet-5.5/medium",
    "lane_gate: none",
    "lane_land: haiku-5.5/low",
    "lane_fix_rounds: 3",
    "lane_blocking: 4",
    "lane_experiment: builder-sonnet",
    "lane_risk: normal",
    "lane_fix_rounds_review: 1",
    "lane_fix_rounds_gate: 0",
    "lane_fix_rounds_ci: 2",
    "lane_fix_rounds_test: 0",
    "lane_blocking_review: 3",
    "lane_blocking_gate: 0",
    "lane_blocking_ci: 1",
    "lane_blocking_test: 0",
    "lane_misses_review: 0",
    "lane_misses_gate: 0",
    "lane_misses_ci: 1",
    "lane_misses_test: 0",
)


def approving_record_file(directory: Path, head: str) -> Path:
    """A valid lane record file in `directory` whose last verdict approves `head`."""
    approval = [{"stage": "review", "verdict": "approve", "sha": head}]
    return write_lane_record_file(directory, lane_record_object(verdicts=approval))


def land_arguments_with_record(directory: Path, head: str, pull_request: int) -> list[str]:
    """The arguments after `aco land` for `pull_request` at `head`, with a lane record file in
    `directory` approving it, for a lane whose claim stores no run."""
    record = approving_record_file(directory, head)
    return [str(pull_request), "--head", head, "--record", str(record)]
