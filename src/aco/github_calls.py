"""The record of every `gh` call an aco process starts (`specs/github-calls.spec.md`): one
JSON line per call in a file of aco's state directory, so the share of GitHub's quota that
aco spends can be counted across processes after the fact."""

import json
import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from . import file_lock, github_failure, github_paging

RECORD_FILE = "github-calls.jsonl"
ROTATED_FILE = "github-calls.1.jsonl"
_ROTATION_LOCK_FILE = "github-calls.lock"
ROTATION_BYTES = 32 * 1024 * 1024
_RECORD_MODE = 0o600
_DIRECTORY_MODE = 0o700
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# A response head's status line sits at the very start of the output.
_STATUS_LINE_BYTES = 64
_NOT_MODIFIED = 304


class Outcome(StrEnum):
    ANSWERED = "answered"
    NOT_MODIFIED = "not_modified"
    RATE_LIMITED = "rate_limited"
    FAILED = "failed"


@dataclass(frozen=True)
class CallRecord:
    at: str
    command: str
    repository: str | None
    quota: github_failure.Quota
    outcome: Outcome
    pid: int
    started: str


def _now() -> str:
    return datetime.now(UTC).strftime(_TIME_FORMAT)


def outcome_of(exit_status: int | None, output: bytes) -> Outcome:
    """How a `gh` call ended: a 304 is `not_modified` whatever gh exits, `None` is a call that
    gave no answer within its bounds."""
    if exit_status is None:
        return Outcome.FAILED
    status_line = output[:_STATUS_LINE_BYTES].decode("utf-8", "replace").splitlines()
    if github_paging.status(status_line) == _NOT_MODIFIED:
        return Outcome.NOT_MODIFIED
    if exit_status == 0:
        return Outcome.ANSWERED
    # The closing message is ASCII, so a replaced byte elsewhere changes nothing it reads.
    decoded = github_paging.without_head(output.decode("utf-8", "replace").strip())
    if github_failure.is_rate_limited(decoded):
        return Outcome.RATE_LIMITED
    return Outcome.FAILED


class _Recorder:
    """The record of one process: appends its lines and warns once when one cannot be written."""

    active: ClassVar[_Recorder | None] = None

    def __init__(self, directory: Path, command: str) -> None:
        self._directory = directory
        self._command = command
        self._started = _now()
        self._failed = False
        self._lock = threading.Lock()

    def append(self, repository: str | None, call: list[str], outcome: Outcome) -> None:
        with self._lock:
            if self._failed:
                return
            line = CallRecord(
                _now(),
                self._command,
                repository,
                github_failure.quota_of(call),
                outcome,
                os.getpid(),
                self._started,
            )
            try:
                self._write(json.dumps(asdict(line), separators=(",", ":")) + "\n")
            except OSError as error:
                self._failed = True
                print(
                    f"warning: GitHub calls not recorded: {error.strerror or error}",
                    file=sys.stderr,
                )

    def _write(self, line: str) -> None:
        self._make_directories()
        descriptor = os.open(
            self._directory / RECORD_FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT, _RECORD_MODE
        )
        try:
            os.write(descriptor, line.encode())
            size = os.fstat(descriptor).st_size
        finally:
            os.close(descriptor)
        if size > ROTATION_BYTES:
            self._rotate()

    def _make_directories(self) -> None:
        missing = [
            path for path in (self._directory, *self._directory.parents) if not path.exists()
        ]
        for path in reversed(missing):
            path.mkdir(mode=_DIRECTORY_MODE, exist_ok=True)

    def _rotate(self) -> None:
        """Moves the full record aside under a lock, so that two processes never rename one
        generation twice and lose the older one."""
        record = self._directory / RECORD_FILE
        with file_lock.held(self._directory / _ROTATION_LOCK_FILE):
            if record.stat().st_size > ROTATION_BYTES:
                record.replace(self._directory / ROTATED_FILE)


@contextmanager
def recording(directory: Path, command: str) -> Iterator[None]:
    """Records every `gh` call made inside the block as a line of `command`'s in `directory`.
    One recorder serves the whole process: the board reads from worker threads."""
    _Recorder.active = _Recorder(directory, command)
    try:
        yield
    finally:
        _Recorder.active = None


def record(
    repository: str | None, call: list[str], exit_status: int | None, output: bytes = b""
) -> None:
    """Records one `gh` call that ended with `exit_status` and `output`, or with no exit status
    when it gave no answer; without `output` it is judged on its exit status alone. Does nothing
    outside `recording`."""
    if _Recorder.active is not None:
        _Recorder.active.append(repository, call, outcome_of(exit_status, output))
