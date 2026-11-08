"""`file_lock`: one exclusive flock on a file that stays on disk."""

import fcntl
import os
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
