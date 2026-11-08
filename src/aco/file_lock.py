"""The one exclusive `flock` on a file: `lineage_stamp` holds one per worktree
stamp and `decide` one per item. The lock file is created beside its users and
never deleted, because unlinking a held flock file breaks the lock."""

import fcntl
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def held(path: Path, on_wait: Callable[[], None] | None = None) -> Iterator[None]:
    """Hold the exclusive lock on `path`, creating it and its directories first
    and waiting for another holder; `on_wait` is called once, before the wait,
    when another holder has it. Not re-entrant. Raises `OSError` when the
    file cannot be created or locked."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if on_wait is not None:
                on_wait()
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)
