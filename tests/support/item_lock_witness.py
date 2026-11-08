"""A fake forge that witnesses `decide`'s per-item lock, and a run of two writers
of one item that makes the second wait for the first."""

import fcntl
import io
import sys
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from github_fixtures import FakeForge

from aco import forge, workboard

WAIT_SECONDS = 10


def _held_by_another(lock: Path) -> bool:
    with lock.open("rb") as probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(probe, fcntl.LOCK_UN)
        return False


class LockWitnessForge(FakeForge):
    """Records, at every read of an item, every board listing and every body write,
    whether the item's lock file is held by another open file description: a call
    made under the per-item lock finds it held, so no second writer can read the
    item before the first one has written.
    A read answers the body last written, as a real forge does. With
    `pause_first_call`, the first recorded call waits until `release_first_call`."""

    def __init__(
        self,
        lock_directory: Path,
        *,
        issue_references: Mapping[int, forge.ItemReference],
        board_issues: Iterable[workboard.Issue] = (),
        pause_first_call: bool = False,
    ) -> None:
        super().__init__(issue_references=dict(issue_references), board_issues=tuple(board_issues))
        self.lock_directory = lock_directory
        self.lock_held_at_reads: list[bool] = []
        self.lock_held_at_listings: list[bool] = []
        self.lock_held_at_writes: list[bool] = []
        self.pause_first_call = pause_first_call
        self.first_call_reached = threading.Event()
        self.release_first_call = threading.Event()
        self._first_call_taken = False

    def item_reference(self, number: int) -> forge.ItemReference:
        reference = super().item_reference(number)
        if number in self.item_bodies:
            reference = replace(reference, body=self.item_bodies[number])
        self.lock_held_at_reads.append(self._witness())
        return reference

    def list_open_board_issues(self) -> tuple[workboard.Issue, ...]:
        self.lock_held_at_listings.append(self._witness())
        return super().list_open_board_issues()

    def update_item_body(self, number: int, body: str) -> None:
        self.lock_held_at_writes.append(self._witness())
        super().update_item_body(number, body)

    def _witness(self) -> bool:
        held = self._lock_is_held()
        if self.pause_first_call and not self._first_call_taken:
            self._first_call_taken = True
            self.first_call_reached.set()
            assert self.release_first_call.wait(WAIT_SECONDS)
        return held

    def _lock_is_held(self) -> bool:
        if not self.lock_directory.is_dir():
            return False
        locks = list(self.lock_directory.iterdir())
        return len(locks) == 1 and _held_by_another(locks[0])

    def the_lock_file(self) -> Path:
        (lock,) = self.lock_directory.iterdir()
        return lock


class _NoticeStream(io.StringIO):
    """A stderr that signals its first write."""

    def __init__(self) -> None:
        super().__init__()
        self.written = threading.Event()

    def write(self, text: str) -> int:
        count = super().write(text)
        self.written.set()
        return count


@dataclass(frozen=True)
class ContendedRun:
    statuses: tuple[int, int]
    stderr: str
    body_writes_when_the_second_waited: int


def run_second_writer_beside_the_first(
    monkeypatch: pytest.MonkeyPatch,
    client: LockWitnessForge,
    writer: Callable[[], int],
) -> ContendedRun:
    """Runs `writer` twice on `client`, which pauses the first run at its first forge
    call, inside the lock; once the second run has printed its notice to stderr,
    lets the first go on, and ends both runs."""
    stream = _NoticeStream()
    monkeypatch.setattr(sys, "stderr", stream)
    statuses: list[int] = []
    first = threading.Thread(target=lambda: statuses.append(writer()))
    second = threading.Thread(target=lambda: statuses.append(writer()))
    writes_when_waiting = -1
    first.start()
    try:
        assert client.first_call_reached.wait(WAIT_SECONDS)
        second.start()
        assert stream.written.wait(WAIT_SECONDS)
        writes_when_waiting = len(client.body_writes)
    finally:
        client.release_first_call.set()
        first.join(WAIT_SECONDS)
        if second.ident is not None:
            second.join(WAIT_SECONDS)
    assert not first.is_alive()
    assert not second.is_alive()
    first_status, second_status = statuses
    return ContendedRun((first_status, second_status), stream.getvalue(), writes_when_waiting)
