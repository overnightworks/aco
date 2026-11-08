"""`file_lock`: one exclusive flock on a file that stays on disk."""

import fcntl
import os
import threading
from pathlib import Path

import pytest

from aco import file_lock


def _is_locked_by_someone(path: Path) -> bool:
    descriptor = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(descriptor)
    return False


def test_the_lock_excludes_a_second_holder_until_released_and_the_file_stays(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "directory" / "item"
    with file_lock.held(path):
        inside = _is_locked_by_someone(path)
    assert (inside, _is_locked_by_someone(path)) == (True, False)


def test_a_lock_file_that_cannot_be_created_raises_os_error(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    path = blocker / "item"
    with pytest.raises(OSError), file_lock.held(path):
        pass


def test_the_notice_comes_once_when_another_holder_has_the_lock_and_never_when_it_is_free(
    tmp_path: Path,
) -> None:
    path = tmp_path / "item"
    notices: list[str] = []
    waiting = threading.Event()
    acquired = threading.Event()

    def say_waiting() -> None:
        notices.append("waiting")
        waiting.set()

    def contender() -> None:
        with file_lock.held(path, say_waiting):
            acquired.set()

    thread = threading.Thread(target=contender)
    try:
        with file_lock.held(path, say_waiting):
            free_notices = list(notices)
            thread.start()
            assert waiting.wait(timeout=10)
            acquired_while_held = acquired.is_set()
    finally:
        if thread.ident is not None:
            thread.join(timeout=10)
    assert (free_notices, notices, acquired_while_held, acquired.is_set()) == (
        [],
        ["waiting"],
        False,
        True,
    )


def test_a_contender_that_asks_for_no_notice_waits_for_the_holder_in_silence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "stamp"
    refused = threading.Event()
    released = threading.Event()
    acquired = threading.Event()
    released_when_acquired: list[bool] = []
    flock = fcntl.flock

    def flock_noting_a_refusal(descriptor: int, operation: int) -> None:
        try:
            flock(descriptor, operation)
        except BlockingIOError:
            refused.set()
            raise

    monkeypatch.setattr(fcntl, "flock", flock_noting_a_refusal)

    def contender() -> None:
        with file_lock.held(path):
            released_when_acquired.append(released.is_set())
            acquired.set()

    thread = threading.Thread(target=contender)
    try:
        with file_lock.held(path):
            thread.start()
            assert refused.wait(timeout=10)
            released.set()
    finally:
        if thread.ident is not None:
            thread.join(timeout=10)
    assert (released_when_acquired, acquired.is_set()) == ([True], True)
