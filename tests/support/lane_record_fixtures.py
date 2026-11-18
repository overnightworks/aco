"""The lane record of a release run against an in-memory store."""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from aco import forge, lane_record, protocol, store, workboard
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

    def plain_subject(
        _context: object,
        claim: protocol.ActiveClaim,
        _outcome: protocol.ReleaseOutcome,
        _evidence: lane_record.ReleaseEvidence,
    ) -> store.TransitionSubject:
        return store.transition_subject("release", claim.identity, claim.branch)

    monkeypatch.setattr(lane_record, "release_subject", plain_subject)


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
    """The trailers `release_subject` puts on the release of `claim`; its context holds no
    forge, so a read of one fails the test."""
    context = SimpleNamespace(
        toplevel=toplevel, config=config, observation=SimpleNamespace(tip=tip), now=lambda: now
    )
    evidence = lane_record.ReleaseEvidence(verified_merge, item)

    return lane_record.release_subject(cast(RunContext, context), claim, outcome, evidence).trailers


JUDGED_SHA = "c" * 40


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
        "risk": "routine",
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
    "lane_risk: routine",
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
