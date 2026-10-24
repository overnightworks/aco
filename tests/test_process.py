"""Behavior of `aco.process`: the bounded subprocess boundary
(`run_bounded`) and the one git
launcher (`run_git`/`git_command`/`git_failure_detail`/
`git_failure_detail_from_stderr`) `checkout` and `store` each call
rather than re-typing. The GitHub adapter's own thin
wrapper over that boundary (`github._bounded_command`) is covered in
`tests/test_github.py`; `checkout`'s and `store`'s own `ClaimError`
translations of a failed git launch are covered in their own test modules."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from aco import process


def test_git_command_prefixes_the_directory_flag_only_when_given(tmp_path: Path) -> None:
    assert process.git_command(["status"]) == ["git", "status"]
    assert process.git_command(["status"], directory=tmp_path) == [
        "git",
        "-C",
        str(tmp_path),
        "status",
    ]


@pytest.mark.parametrize(
    ("stdout", "stderr", "expected"),
    [
        (b"", b"fatal: not a git repository\n", "fatal: not a git repository"),
        (b"a stray warning on stdout\n", b"", "a stray warning on stdout"),
        (b"", b"", process.UNKNOWN_GIT_FAILURE),
    ],
)
def test_git_failure_detail_reads_stderr_then_stdout_then_the_fixed_sentence(
    stdout: bytes, stderr: bytes, expected: str
) -> None:
    result = process.CapturedResult(exit_status=1, stdout=stdout, stderr=stderr)

    assert process.git_failure_detail(result) == expected


@pytest.mark.parametrize(
    ("stdout", "stderr", "expected"),
    [
        (b"", b"fatal: not a git repository\n", "fatal: not a git repository"),
        (b"a stray warning on stdout\n", b"", process.UNKNOWN_GIT_FAILURE),
        (b"", b"", process.UNKNOWN_GIT_FAILURE),
    ],
)
def test_git_failure_detail_from_stderr_never_reads_stdout(
    stdout: bytes, stderr: bytes, expected: str
) -> None:
    """Unlike `git_failure_detail`, a command whose stdout carries nothing a
    failure message should ever quote (`fetch`, `update-ref`, ...) must fall
    back straight to `UNKNOWN_GIT_FAILURE` rather than a stray stdout line."""
    result = process.CapturedResult(exit_status=1, stdout=stdout, stderr=stderr)

    assert process.git_failure_detail_from_stderr(result) == expected


def test_run_git_launches_the_directory_scoped_git_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed: list[list[str]] = []

    def fake_run_captured(command: list[str], **_kwargs: object) -> process.CapturedResult:
        observed.append(command)
        return process.CapturedResult(exit_status=0, stdout=b"ok\n", stderr=b"")

    monkeypatch.setattr(process, "run_captured", fake_run_captured)

    result = process.run_git(["rev-parse", "HEAD"], directory=tmp_path)

    assert observed == [["git", "-C", str(tmp_path), "rev-parse", "HEAD"]]
    assert result.stdout == b"ok\n"


def test_run_captured_runs_the_command_in_the_given_directory(tmp_path: Path) -> None:
    result = process.run_captured(
        [sys.executable, "-c", "import os; print(os.getcwd())"], cwd=tmp_path
    )

    assert Path(result.stdout.decode().strip()) == tmp_path


class _FakeBoundedProcess:
    """A deterministic `subprocess.Popen`-shaped double: a real closed pipe for
    `stdout` (so the selector has a real, immediately-EOF file descriptor to
    register) plus scripted `poll`/`terminate`/`kill`/`wait`, so
    `process.run_bounded`'s stop-and-reap behavior is proven without spawning a
    child or depending on real OS scheduling.
    """

    def __init__(
        self,
        *,
        already_exited: bool = False,
        ignores_terminate: bool = False,
        survives_kill: bool = False,
    ) -> None:
        read_fd, write_fd = os.pipe()
        os.close(write_fd)
        self.stdout = os.fdopen(read_fd, "rb")
        self.stdin = None
        error_read_fd, error_write_fd = os.pipe()
        os.close(error_write_fd)
        self.stderr = os.fdopen(error_read_fd, "rb")
        self._ignores_terminate = ignores_terminate
        self._survives_kill = survives_kill
        self.events: list[str] = []
        self._exited = already_exited

    def poll(self) -> int | None:
        return 0 if self._exited else None

    def terminate(self) -> None:
        self.events.append("terminate")
        if not self._ignores_terminate:
            self._exited = True

    def kill(self) -> None:
        self.events.append("kill")
        self._exited = not self._survives_kill

    def wait(self, timeout: float = 0.0) -> int:
        if not self._exited:
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
        return 0


bounded_runners = pytest.mark.parametrize(
    "run_bounded_command",
    [process.run_bounded, process.run_bounded_captured],
    ids=["merged", "separated"],
)


@bounded_runners
def test_bounded_run_times_out_even_when_the_child_already_exited(
    monkeypatch: pytest.MonkeyPatch, run_bounded_command: Callable[..., object]
) -> None:
    """A deadline already passed by the time I/O is awaited must fail loud even
    when the child happened to finish first -- stopping an already-exited
    process is then a safe no-op, never a second signal or a raised error."""
    fake_process = _FakeBoundedProcess(already_exited=True)
    calls = {"n": 0}

    def already_past_deadline() -> float:
        calls["n"] += 1
        return 0.0 if calls["n"] == 1 else 1_000_000.0

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(process.time, "monotonic", already_past_deadline)

    with pytest.raises(process.ProcessTimedOutError):
        run_bounded_command(["fake"], timeout=5.0)

    assert fake_process.events == []
    assert fake_process.stdout.closed is True
    assert fake_process.poll() is not None


@bounded_runners
def test_bounded_run_kills_a_child_that_ignores_termination(
    monkeypatch: pytest.MonkeyPatch, run_bounded_command: Callable[..., object]
) -> None:
    """A child that survives `terminate()` (ignoring the request to stop) must
    be `kill()`ed -- proven with a deterministic process fake controlling
    `poll`/`terminate`/`kill`/`wait`, not a real child ignoring a real SIGTERM."""
    fake_process = _FakeBoundedProcess(ignores_terminate=True)

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(process.time, "monotonic", lambda: 0.0)

    with pytest.raises(process.ProcessTimedOutError):
        run_bounded_command(["fake"], timeout=-1.0)

    assert fake_process.events == ["terminate", "kill"]
    assert fake_process.stdout.closed is True
    assert fake_process.poll() is not None


@bounded_runners
def test_bounded_run_reports_a_child_that_survives_being_killed_as_not_exiting(
    monkeypatch: pytest.MonkeyPatch, run_bounded_command: Callable[..., object]
) -> None:
    """A child still alive after `kill()` and its bounded wait is a typed
    `ProcessDidNotExitError`, never the raw `subprocess.TimeoutExpired`."""
    fake_process = _FakeBoundedProcess(ignores_terminate=True, survives_kill=True)

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: fake_process)
    monkeypatch.setattr(process.time, "monotonic", lambda: 0.0)

    with pytest.raises(process.ProcessDidNotExitError):
        run_bounded_command(["fake"], timeout=-1.0)

    assert fake_process.events[:2] == ["terminate", "kill"]
    assert fake_process.stdout.closed is True


def test_run_bounded_treats_a_broken_input_pipe_as_fully_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stdin write that raises `BrokenPipeError` -- the child closed its read
    end without consuming the input -- must not fail the whole exchange: the
    write is treated as fully sent and output collection continues."""

    def broken_write(_file_descriptor: int, data: bytes) -> int:
        raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr(process.os, "write", broken_write)

    observed = process.run_bounded(
        [sys.executable, "-c", "print('done')"],
        input_data=b"unread input",
    )
    assert observed.output == b"done\n"


def test_run_bounded_sends_input_the_pipe_accepts_in_pieces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pipe that takes only part of the input per write must still deliver
    all of it, in order."""
    real_write = process.os.write

    def short_write(file_descriptor: int, data: bytes) -> int:
        return real_write(file_descriptor, bytes(data[:4]))

    monkeypatch.setattr(process.os, "write", short_write)

    observed = process.run_bounded(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
        input_data=b"input sent in pieces",
    )

    assert observed.output == b"input sent in pieces"


def test_run_bounded_reaps_the_child_when_the_selector_fails_to_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A selector that cannot close itself on the way out must not mask the
    command's own result -- reaping swallows that failure."""
    real_selector_class = process.selectors.DefaultSelector

    class CloseFailingSelector:
        def __init__(self) -> None:
            self._inner = real_selector_class()

        def register(self, fileobj, events, data=None):
            return self._inner.register(fileobj, events, data)

        def unregister(self, fileobj):
            return self._inner.unregister(fileobj)

        def get_map(self):
            return self._inner.get_map()

        def select(self, timeout=None):
            return self._inner.select(timeout)

        def close(self) -> None:
            raise OSError(5, "close failed")

    monkeypatch.setattr(process.selectors, "DefaultSelector", CloseFailingSelector)

    observed = process.run_bounded([sys.executable, "-c", "print('ok')"])
    assert observed.output == b"ok\n"


def test_run_bounded_captured_keeps_stdout_and_stderr_apart_and_sends_input() -> None:
    program = (
        "import sys; data = sys.stdin.buffer.read();"
        " sys.stdout.buffer.write(b'out:' + data); sys.stderr.buffer.write(b'err');"
        " sys.exit(3)"
    )

    observed = process.run_bounded_captured([sys.executable, "-c", program], input_data=b"payload")

    assert observed == process.CapturedResult(3, b"out:payload", b"err")


@pytest.mark.parametrize("noisy_stream", ["stdout", "stderr"])
def test_run_bounded_captured_refuses_output_past_the_bound_on_either_stream(
    monkeypatch: pytest.MonkeyPatch, noisy_stream: str
) -> None:
    monkeypatch.setattr(process, "MAX_COMMAND_OUTPUT_BYTES", 8)
    program = f"import sys; sys.{noisy_stream}.write('x' * 100)"

    with pytest.raises(process.ProcessOutputTooLargeError):
        process.run_bounded_captured([sys.executable, "-c", program])


@pytest.mark.parametrize(
    ("stdout", "stderr", "expected"),
    [
        pytest.param(b"", b"fatal: \xff name", "fatal: \ufffd name", id="undecodable-stderr"),
        pytest.param(b"left over", b"", "left over", id="stdout-when-stderr-is-empty"),
        pytest.param(
            b"left over", b"fatal: \xff name", "fatal: \ufffd name", id="stderr-wins-over-stdout"
        ),
        pytest.param(b"", b"", process.UNKNOWN_GIT_FAILURE, id="neither-stream"),
    ],
)
def test_lossy_git_failure_detail_reads_stderr_then_stdout_then_the_fixed_sentence_without_raising(
    stdout: bytes, stderr: bytes, expected: str
) -> None:
    assert process.git_failure_detail_lossy(process.CapturedResult(1, stdout, stderr)) == expected
