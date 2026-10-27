"""The per-worktree lineage stamp under interleaved aco processes in one worktree.

Every interleaving here is driven single-threaded: a transport or a wrapped
seam runs the "other process" inside the window under test, and a second open
file description probes the stamp lock (flock conflicts across descriptions
of one process).
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from cli_fixtures import fresh_observation, real_git, set_git_identity
from store_fixtures import blob, state_ref_tip

from aco import lineage_stamp, protocol, store


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    set_git_identity(monkeypatch)


class _AfterPushTransport:
    """Pushes for real, then runs `interleaved` before the push returns."""

    def __init__(self, interleaved: Callable[[], object]) -> None:
        self._interleaved = interleaved
        self._real = store.GitPushTransport()

    def push(self, *, worktree: Path, remote: str, ref: str, new_oid: protocol.ObjectId) -> None:
        self._real.push(worktree=worktree, remote=remote, ref=ref, new_oid=new_oid)
        self._interleaved()


def _write_item(
    worktree: Path,
    remote: Path,
    item_id: str,
    transport: store.PushTransport | None = None,
) -> protocol.ObjectId:
    """One real writer: read the state, write one item, return the landed tip."""
    state = store.commit_transition(
        observed=fresh_observation(worktree, remote),
        subject=store.TransitionSubject(f"create item {item_id}"),
        intent=protocol.ItemWriteIntent(
            item_id=item_id,
            expected=None,
            new_oid=protocol.ObjectId(blob(worktree, item_id.encode())),
            operation_id=f"op-{item_id}",
        ),
        transport=transport,
    )
    assert state.tip is not None
    return state.tip


def _stamp(worktree: Path) -> protocol.ObjectId | None:
    return lineage_stamp.read(store._stamp_directory(worktree))


def _lock_is_held(worktree: Path) -> bool:
    """Whether another open file description holds the stamp lock right now."""
    descriptor = os.open(
        lineage_stamp.lock_path(store._stamp_directory(worktree)), os.O_RDWR | os.O_CREAT
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(descriptor)
    return False


def _force_state_ref(worktree: Path, remote: Path, commit: protocol.ObjectId) -> None:
    real_git(worktree, "push", "--force", str(remote), f"{commit}:{store.STATE_REF}")


def _unrelated_commit(worktree: Path, *, like: protocol.ObjectId) -> protocol.ObjectId:
    """A parentless commit on `like`'s tree: neither its ancestor nor descendant."""
    tree = real_git(worktree, "rev-parse", f"{like}^{{tree}}").stdout.strip()
    return protocol.ObjectId(
        real_git(worktree, "commit-tree", tree, "-m", "unrelated").stdout.strip()
    )


def test_a_reader_inside_a_writers_stamp_window_returns_state_and_the_stamp_ends_at_the_writer(
    bare_remote: Path, worktree: Path
) -> None:
    """CAS-76: the reader stamps the landed tip first; the writer's stamp step keeps it."""
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    reads: list[protocol.ClaimState] = []

    def read_inside_the_window() -> None:
        reads.append(store.fetch_state(worktree=worktree, remote=str(bare_remote)))

    landed = _write_item(
        worktree, bare_remote, "aco-000001", _AfterPushTransport(read_inside_the_window)
    )

    assert [state.tip for state in reads] == [landed]
    assert _stamp(worktree) == landed


def test_a_second_writer_landing_inside_a_writers_window_is_never_stamped_over(
    bare_remote: Path, worktree: Path
) -> None:
    """CAS-76: a stamp already past the first writer's commit stays."""
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    second: list[protocol.ObjectId] = []

    def second_writer_lands() -> None:
        second.append(_write_item(worktree, bare_remote, "aco-000002"))

    first = _write_item(
        worktree, bare_remote, "aco-000001", _AfterPushTransport(second_writer_lands)
    )

    assert second != [first]
    assert _stamp(worktree) == second[0]
    assert state_ref_tip(bare_remote) == str(second[0])


def test_a_writer_finding_a_diverged_stamp_refuses_as_uncertain_with_the_lineage_sentence(
    bare_remote: Path, worktree: Path
) -> None:
    """CAS-76, CAS-56: a stamp neither before nor past the landed commit."""
    tip = store.bootstrap(worktree=worktree, remote=str(bare_remote))
    stranger = _unrelated_commit(worktree, like=tip)

    def stamp_a_stranger() -> None:
        lineage_stamp.write(store._stamp_directory(worktree), stranger)

    with pytest.raises(protocol.UncertainWriteError) as refusal:
        _write_item(worktree, bare_remote, "aco-000001", _AfterPushTransport(stamp_a_stranger))

    landed = state_ref_tip(bare_remote)
    assert str(refusal.value).startswith(f"{store.STATE_REF} moved from {stranger} to {landed}")
    assert "may have been rewritten" in str(refusal.value)


def test_a_fetch_refuses_a_rollback_to_an_ancestor_of_its_stamp(
    bare_remote: Path, worktree: Path
) -> None:
    """CAS-11 stays: a tip that does not descend from the stamp refuses, an ancestor included."""
    first = store.bootstrap(worktree=worktree, remote=str(bare_remote))
    second = _write_item(worktree, bare_remote, "aco-000001")
    _force_state_ref(worktree, bare_remote, first)

    with pytest.raises(
        protocol.StateLineageError, match=f"moved from {second} to {first} without {second}"
    ):
        store.fetch_state(worktree=worktree, remote=str(bare_remote))


def test_a_fetch_holds_the_stamp_lock_from_its_probe_through_its_ancestry_check(
    monkeypatch: pytest.MonkeyPatch, bare_remote: Path, worktree: Path
) -> None:
    """CAS-75: held at the `ls-remote` probe, before any tip is read, and at the check."""
    first = store.bootstrap(worktree=worktree, remote=str(bare_remote))
    _write_item(worktree, bare_remote, "aco-000001")
    lineage_stamp.write(store._stamp_directory(worktree), first)  # the check must compare
    held_at_probe: list[bool] = []
    held_at_check: list[bool] = []
    real_probe = store._ls_remote_state
    real_is_ancestor = store._is_ancestor

    def probe(checked_worktree: Path, remote: str) -> protocol.ObjectId | None:
        held_at_probe.append(_lock_is_held(worktree))
        return real_probe(checked_worktree, remote)

    def is_ancestor_factory(checked_worktree: Path) -> lineage_stamp.IsAncestor:
        real = real_is_ancestor(checked_worktree)

        def is_ancestor(ancestor: protocol.ObjectId, descendant: protocol.ObjectId) -> bool:
            held_at_check.append(_lock_is_held(worktree))
            return real(ancestor, descendant)

        return is_ancestor

    monkeypatch.setattr(store, "_ls_remote_state", probe)
    monkeypatch.setattr(store, "_is_ancestor", is_ancestor_factory)

    store.fetch_state(worktree=worktree, remote=str(bare_remote))

    assert (held_at_probe, held_at_check) == ([True], [True])
    assert _lock_is_held(worktree) is False


def test_a_writers_stamp_step_holds_the_stamp_lock_while_it_judges_ancestry(
    monkeypatch: pytest.MonkeyPatch, bare_remote: Path, worktree: Path
) -> None:
    """CAS-76: the stamp (the old tip) differs from the landed commit, so ancestry is asked."""
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    held_at_check: list[bool] = []
    real_is_ancestor = store._is_ancestor

    def is_ancestor_factory(checked_worktree: Path) -> lineage_stamp.IsAncestor:
        real = real_is_ancestor(checked_worktree)

        def is_ancestor(ancestor: protocol.ObjectId, descendant: protocol.ObjectId) -> bool:
            held_at_check.append(_lock_is_held(worktree))
            return real(ancestor, descendant)

        return is_ancestor

    monkeypatch.setattr(store, "_is_ancestor", is_ancestor_factory)

    _write_item(worktree, bare_remote, "aco-000001")

    assert held_at_check == [True]


def test_reset_clears_each_worktrees_stamp_under_its_lock_and_the_next_fetch_accepts_a_fresh_ref(
    monkeypatch: pytest.MonkeyPatch, bare_remote: Path, worktree: Path
) -> None:
    """CAS-77, CAS-10: the unlink runs under the lock; an unrelated ref is then a first sight."""
    tip = store.bootstrap(worktree=worktree, remote=str(bare_remote))
    store.fetch_state(worktree=worktree, remote=str(bare_remote))
    held_at_unlink: list[bool] = []
    real_remove = lineage_stamp.remove

    def remove_noting_the_lock(stamp_directory: Path) -> None:
        held_at_unlink.append(_lock_is_held(worktree))
        real_remove(stamp_directory)

    monkeypatch.setattr(lineage_stamp, "remove", remove_noting_the_lock)

    store.clear_lineage_stamps(worktree=worktree)

    assert held_at_unlink == [True]
    assert _stamp(worktree) is None
    _force_state_ref(worktree, bare_remote, _unrelated_commit(worktree, like=tip))
    assert store.fetch_state(worktree=worktree, remote=str(bare_remote)).tip is not None


def test_a_peek_never_creates_the_stamp_lock(
    bare_remote: Path, worktree: Path, tmp_path: Path
) -> None:
    """CAS-75: only a fetch or a writer takes the lock; a peek leaves no file behind."""
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    linked = tmp_path / "linked"
    real_git(worktree, "worktree", "add", "-q", "-b", "lane", str(linked))

    store.peek_state(worktree=linked, remote=str(bare_remote))

    assert not lineage_stamp.lock_path(store._stamp_directory(linked)).exists()
