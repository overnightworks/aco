"""The lane record of a release run against an in-memory store."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from aco import forge, lane_record, protocol, store, workboard
from aco.session import RunContext


def stub_lane_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """An in-memory store holds no state-ref commit, and a faked git answers no commit read,
    so its releases carry no lane record; `test_lane_record.py` drives the real one."""

    def plain_subject(
        _context: object,
        claim: protocol.ActiveClaim,
        _outcome: protocol.ReleaseOutcome,
        _verified_merge: str | None = None,
        item: forge.ItemReference | None = None,
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

    return lane_record.release_subject(
        cast(RunContext, context), claim, outcome, verified_merge, item
    ).trailers
