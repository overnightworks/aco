"""`lineage_stamp`: the stamp's verdicts and lock, with no git."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

import pytest

from aco import lineage_stamp
from aco.protocol import ObjectId

_OLD = ObjectId("a" * 40)
_NEW = ObjectId("b" * 40)
_OTHER = ObjectId("c" * 40)


def _ancestry(*pairs: tuple[ObjectId, ObjectId]) -> lineage_stamp.IsAncestor:
    return lambda ancestor, descendant: (ancestor, descendant) in pairs


def _never_asked(_ancestor: ObjectId, _descendant: ObjectId) -> bool:
    raise AssertionError("ancestry must not be asked")


@pytest.mark.parametrize(
    ("stamped", "tip", "is_ancestor", "verdict", "stamp_after"),
    [
        pytest.param(
            None, _NEW, _never_asked, lineage_stamp.Verdict.ACCEPTED, _NEW, id="first-observation"
        ),
        pytest.param(
            _NEW, _NEW, _never_asked, lineage_stamp.Verdict.ACCEPTED, _NEW, id="unchanged"
        ),
        pytest.param(
            _OLD,
            _NEW,
            _ancestry((_OLD, _NEW)),
            lineage_stamp.Verdict.ACCEPTED,
            _NEW,
            id="descendant",
        ),
        pytest.param(_OLD, _NEW, _ancestry(), lineage_stamp.Diverged(_OLD), _OLD, id="unrelated"),
        pytest.param(
            _NEW,
            _OLD,
            _ancestry((_OLD, _NEW)),
            lineage_stamp.Diverged(_NEW),
            _NEW,
            id="rolled-back-to-an-ancestor",
        ),
    ],
)
def test_check_and_stamp_judges_a_fetched_tip_against_the_stamp(
    tmp_path: Path,
    stamped: ObjectId | None,
    tip: ObjectId,
    is_ancestor: lineage_stamp.IsAncestor,
    verdict: lineage_stamp.Verdict | lineage_stamp.Diverged,
    stamp_after: ObjectId,
) -> None:
    if stamped is not None:
        lineage_stamp.write(tmp_path, stamped)

    assert lineage_stamp.check_and_stamp(tmp_path, tip, is_ancestor) == verdict
    assert lineage_stamp.read(tmp_path) == stamp_after


@pytest.mark.parametrize(
    ("stamped", "is_ancestor", "verdict", "stamp_after"),
    [
        pytest.param(None, _never_asked, lineage_stamp.Verdict.ACCEPTED, _NEW, id="missing"),
        pytest.param(_NEW, _never_asked, lineage_stamp.Verdict.KEPT, _NEW, id="already-there"),
        pytest.param(
            _OLD, _ancestry((_OLD, _NEW)), lineage_stamp.Verdict.ACCEPTED, _NEW, id="advances"
        ),
        pytest.param(
            _OTHER, _ancestry((_NEW, _OTHER)), lineage_stamp.Verdict.KEPT, _OTHER, id="already-past"
        ),
        pytest.param(_OTHER, _ancestry(), lineage_stamp.Diverged(_OTHER), _OTHER, id="diverged"),
    ],
)
def test_advance_moves_a_writers_stamp_forward_and_never_back(
    tmp_path: Path,
    stamped: ObjectId | None,
    is_ancestor: lineage_stamp.IsAncestor,
    verdict: lineage_stamp.Verdict | lineage_stamp.Diverged,
    stamp_after: ObjectId,
) -> None:
    if stamped is not None:
        lineage_stamp.write(tmp_path, stamped)

    assert lineage_stamp.advance(tmp_path, _NEW, is_ancestor) == verdict
    assert lineage_stamp.read(tmp_path) == stamp_after


def test_write_cleans_up_its_temp_file_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(lineage_stamp.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        lineage_stamp.write(tmp_path, _NEW)

    assert list(tmp_path.glob(".last-oid-*")) == []


def test_the_lock_excludes_a_second_holder_until_it_is_released_and_stays_on_disk(
    tmp_path: Path,
) -> None:
    def second_holder_blocked() -> bool:
        descriptor = os.open(lineage_stamp.lock_path(tmp_path), os.O_RDWR)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            os.close(descriptor)
        return False

    with lineage_stamp.locked(tmp_path):
        inside = second_holder_blocked()

    assert (inside, second_holder_blocked()) == (True, False)


def test_remove_deletes_the_stamp_and_tolerates_none(tmp_path: Path) -> None:
    lineage_stamp.write(tmp_path, _NEW)

    lineage_stamp.remove(tmp_path)
    lineage_stamp.remove(tmp_path)

    assert lineage_stamp.read(tmp_path) is None
