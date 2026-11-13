"""The lane record of a release run against an in-memory store."""

import pytest

from aco import lane_record, protocol, store


def stub_lane_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """An in-memory store holds no state-ref commit, and a faked git answers no commit read,
    so its releases carry no lane record; `test_lane_record.py` drives the real one."""

    def plain_subject(
        _context: object,
        claim: protocol.ActiveClaim,
        _outcome: protocol.ReleaseOutcome,
        _verified_merge: str | None = None,
    ) -> store.TransitionSubject:
        return store.transition_subject("release", claim.identity, claim.branch)

    monkeypatch.setattr(lane_record, "release_subject", plain_subject)
