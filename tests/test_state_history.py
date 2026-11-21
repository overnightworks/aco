"""`state_history` behaviour: the age of each live claim, read from the state ref's commit history.

Every test here drives real git subprocesses against a local bare repository, the thin
git-transport integration layer.
"""

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cli_fixtures import fresh_observation, real_git, set_git_identity
from store_fixtures import claim_intent

from aco import process, protocol, state_history, store

# A syntactically valid but locally unresolvable object id.
_UNRESOLVABLE_OBJECT_ID = protocol.ObjectId("0" * 40)


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """A commit identity for every git subprocess this test file spawns -- this
    machine may carry no git `user.name`/`user.email` at all."""
    set_git_identity(monkeypatch)


def _committed_claim(bare_remote: Path, worktree: Path, *, issue: int) -> protocol.ActiveClaim:
    """Land one real claim transition and hand back its resulting `ActiveClaim`
    -- its `opened_commit` is the real state-ref commit the transition wrote,
    not a placeholder, so a `claim_ages` walk of that history finds it."""
    state = store.commit_transition(
        observed=fresh_observation(worktree, bare_remote),
        subject=store.TransitionSubject(f"claim issue {issue}"),
        intent=claim_intent(
            identity=protocol.IssueIdentity(issue),
            branch=f"claude/issue-{issue}-cut",
            scope=(f"src/issue-{issue}.py",),
            claim_id=f"c{issue}",
            operation_id=f"op-{issue}",
        ),
    )
    return next(
        claim for claim in state.claims.values() if claim.identity == protocol.IssueIdentity(issue)
    )


def test_claim_ages_reads_the_committer_date_of_each_claim_from_one_log_walk(
    bare_remote: Path, worktree: Path, git_call_spy: Counter[str]
) -> None:
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    first = _committed_claim(bare_remote, worktree, issue=1)
    second = _committed_claim(bare_remote, worktree, issue=2)
    state = store.fetch_state(worktree=worktree, remote=str(bare_remote))
    assert state.tip is not None
    git_call_spy.clear()

    ages = state_history.claim_ages(worktree=worktree, tip=state.tip, claims=state.claims.values())

    assert set(ages) == {first.claim_id, second.claim_id}
    assert all(age.tzinfo is not None for age in ages.values())
    assert git_call_spy["log"] == 1


def test_claim_ages_dates_a_claim_by_its_own_commit_not_the_idle_tip_it_followed(
    monkeypatch: pytest.MonkeyPatch, bare_remote: Path, worktree: Path
) -> None:
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-11-18T19:07:00+00:00")
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-11-19T17:18:00+00:00")
    claim = _committed_claim(bare_remote, worktree, issue=1)
    state = store.fetch_state(worktree=worktree, remote=str(bare_remote))
    assert state.tip is not None

    ages = state_history.claim_ages(worktree=worktree, tip=state.tip, claims=(claim,))

    assert ages[claim.claim_id] == datetime(2026, 11, 19, 17, 18, tzinfo=UTC)


def test_claim_ages_refuses_a_claim_whose_opened_commit_is_the_tip(
    bare_remote: Path, worktree: Path
) -> None:
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    claim = _committed_claim(bare_remote, worktree, issue=1)

    with pytest.raises(protocol.StateLineageError, match="is not an ancestor"):
        state_history.claim_ages(worktree=worktree, tip=claim.opened_commit, claims=(claim,))


def test_claim_ages_survives_a_gc_prune_of_the_just_fetched_history(
    bare_remote: Path, worktree: Path
) -> None:
    """An unanchored fetch lands the
    fetched commits only in `FETCH_HEAD`, which is not a ref and roots
    nothing once the fetch subprocess exits -- a `git gc --prune=now` run
    against this same checkout right after `fetch_state` returns collects
    every commit `claim_ages`'s own `git log` walk needs next (nothing else
    in this worktree references the state ref's history). `fetch_state` anchors the fetched tip in
    its own per-worktree ref namespace (`_fetch_into_anchor`), so the walk
    survives the same prune.
    """
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    claim = _committed_claim(bare_remote, worktree, issue=1)
    state = store.fetch_state(worktree=worktree, remote=str(bare_remote))
    assert state.tip is not None
    real_git(worktree, "gc", "--prune=now")

    ages = state_history.claim_ages(worktree=worktree, tip=state.tip, claims=(claim,))

    assert ages[claim.claim_id].tzinfo is not None


def test_claim_ages_returns_empty_without_a_git_call_for_no_live_claims(
    bare_remote: Path, worktree: Path, git_call_spy: Counter[str]
) -> None:
    tip = store.bootstrap(worktree=worktree, remote=str(bare_remote))
    git_call_spy.clear()

    ages = state_history.claim_ages(worktree=worktree, tip=tip, claims=())

    assert ages == {}
    assert git_call_spy["log"] == 0


def test_claim_ages_refuses_a_claim_whose_opened_commit_is_not_an_ancestor_of_the_tip(
    bare_remote: Path, worktree: Path
) -> None:
    tip = store.bootstrap(worktree=worktree, remote=str(bare_remote))
    orphan_tree = store._write_bootstrap_tree(worktree)
    orphan_commit = store._commit_tree(
        worktree, tree_oid=orphan_tree, parent=None, message="unrelated root commit\n"
    )
    stray = protocol.ActiveClaim(
        identity=protocol.IssueIdentity(1),
        claim_id=protocol.ClaimId("c1"),
        agent="Ada",
        role="builder",
        base=_UNRESOLVABLE_OBJECT_ID,
        branch="claude/issue-1-cut",
        scope=("src/issue-1.py",),
        opened_commit=orphan_commit,
    )

    with pytest.raises(protocol.StateLineageError, match="is not an ancestor"):
        state_history.claim_ages(worktree=worktree, tip=tip, claims=(stray,))


def _fake_git_log_result(
    monkeypatch: pytest.MonkeyPatch, *, exit_status: int, stdout: bytes
) -> None:
    """Let every real git subprocess run except `log`, which returns a fixed
    result -- isolates `claim_ages`'s date-read/parse step from the rest of
    its plumbing."""
    real_run_captured = process.run_captured

    def fake_run_captured(arguments: list[str]) -> process.CapturedResult:
        if "log" in arguments:
            return process.CapturedResult(exit_status=exit_status, stdout=stdout, stderr=b"")
        return real_run_captured(arguments)

    monkeypatch.setattr(store.process, "run_captured", fake_run_captured)


def test_claim_ages_fails_loud_when_the_log_read_fails(
    monkeypatch: pytest.MonkeyPatch, bare_remote: Path, worktree: Path
) -> None:
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    claim = _committed_claim(bare_remote, worktree, issue=1)
    state = store.fetch_state(worktree=worktree, remote=str(bare_remote))
    assert state.tip is not None
    _fake_git_log_result(monkeypatch, exit_status=1, stdout=b"")

    with pytest.raises(protocol.ClaimError, match="cannot read the commit history"):
        state_history.claim_ages(worktree=worktree, tip=state.tip, claims=(claim,))


def test_claim_ages_fails_loud_on_a_malformed_date(
    monkeypatch: pytest.MonkeyPatch, bare_remote: Path, worktree: Path
) -> None:
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    claim = _committed_claim(bare_remote, worktree, issue=1)
    state = store.fetch_state(worktree=worktree, remote=str(bare_remote))
    assert state.tip is not None
    _fake_git_log_result(
        monkeypatch, exit_status=0, stdout=f"{claim.opened_commit}\tnot-a-date\n".encode()
    )

    with pytest.raises(protocol.ClaimError, match="malformed committer date"):
        state_history.claim_ages(worktree=worktree, tip=state.tip, claims=(claim,))
