"""The per-worktree lineage stamp: the last state tip this worktree observed
or wrote, which `store` compares every fetched tip against (CAS-09..11).

Every read-modify-write of the stamp happens under `locked`, an exclusive
`flock` on a file beside the stamp (CAS-75..77). The module knows no git:
callers pass the stamp directory and an ancestry predicate.
"""

from __future__ import annotations

import fcntl
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .protocol import ObjectId

_STAMP_FILENAME = "last-oid"
_LOCK_FILENAME = "last-oid.lock"

IsAncestor = Callable[[ObjectId, ObjectId], bool]
"""Whether the first commit is an ancestor of the second."""


class Verdict(Enum):
    ACCEPTED = "accepted"
    KEPT = "kept"


@dataclass(frozen=True)
class Diverged:
    """The stamp `previous` is not on the line the new commit continues."""

    previous: ObjectId


def lock_path(stamp_directory: Path) -> Path:
    return stamp_directory / _LOCK_FILENAME


@contextmanager
def locked(stamp_directory: Path) -> Iterator[None]:
    """Hold this worktree's exclusive stamp lock. Not re-entrant. The lock
    file is never deleted: unlinking a held flock file breaks the lock."""
    stamp_directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path(stamp_directory), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def read(stamp_directory: Path) -> ObjectId | None:
    try:
        content = (stamp_directory / _STAMP_FILENAME).read_text().strip()
    except FileNotFoundError:
        return None
    return ObjectId(content) if content else None


def write(stamp_directory: Path, commit: ObjectId) -> None:
    """Record `commit` via temp file + `os.replace`."""
    stamp_directory.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=stamp_directory, prefix=".last-oid-")
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(f"{commit}\n")
        os.replace(temp_name, stamp_directory / _STAMP_FILENAME)
    except BaseException:
        with suppress(OSError):
            os.remove(temp_name)
        raise


def check_and_stamp(
    stamp_directory: Path, tip: ObjectId, is_ancestor: IsAncestor
) -> Verdict | Diverged:
    """A fetched `tip` is accepted and stamped when no stamp exists, it equals
    the stamp, or it descends from it; anything else, an ancestor rollback
    included, is `Diverged`. Caller holds `locked`.

    Cannot see: a rewrite that branched before this worktree's first fetch;
    a missing stamp is a first observation.
    """
    previous = read(stamp_directory)
    if previous is not None and previous != tip and not is_ancestor(previous, tip):
        return Diverged(previous)
    write(stamp_directory, tip)
    return Verdict.ACCEPTED


def advance(stamp_directory: Path, commit: ObjectId, is_ancestor: IsAncestor) -> Verdict | Diverged:
    """A writer's stamp after its push landed `commit` (CAS-76): written when
    missing, advanced to a descendant, kept when already at or past `commit`
    (a second writer landed in between), else `Diverged`."""
    with locked(stamp_directory):
        previous = read(stamp_directory)
        if previous == commit:
            return Verdict.KEPT
        if previous is None or is_ancestor(previous, commit):
            write(stamp_directory, commit)
            return Verdict.ACCEPTED
        if is_ancestor(commit, previous):
            return Verdict.KEPT
        return Diverged(previous)


def remove(stamp_directory: Path) -> None:
    """Delete the stamp; caller holds `locked`."""
    (stamp_directory / _STAMP_FILENAME).unlink(missing_ok=True)
