"""Bounded subprocess execution: spawning, timing out, and bounding output.

Every process this package runs -- `gh` and `git` -- goes through this module,
the sole `subprocess` importer, so timeout, output-size and I/O-failure handling
exist in exactly one place. Failures come back as typed,
provider-neutral exceptions; only a caller that knows what command it ran and
why can turn one into a user-facing message.
"""

from __future__ import annotations

import os
import selectors
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 60
MAX_COMMAND_OUTPUT_BYTES = 8 * 1024 * 1024
_OUTPUT_CHUNK_BYTES = 64 * 1024
_PROCESS_EXIT_POLL_SECONDS = 1
_STDIN_KEY = "stdin"
_STDOUT_KEY = "stdout"
_STDERR_KEY = "stderr"

# Fallback when a failed git invocation left nothing readable on either
# stream (issue #372: one owner instead of a `checkout.py`/`store.py` copy).
UNKNOWN_GIT_FAILURE = "unknown git failure"


class IoStage(StrEnum):
    WAITING = "waiting for I/O"
    SENDING = "sending bounded input"
    READING = "reading output"
    COORDINATING = "coordinating I/O"


class ProcessError(RuntimeError):
    """A command could not be run to completion within its bounds."""


class ExecutableMissingError(ProcessError):
    def __init__(self, executable: str):
        self.executable = executable
        super().__init__(executable)


class ProcessStartFailedError(ProcessError):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class ProcessTimedOutError(ProcessError):
    pass


class ProcessIoFailedError(ProcessError):
    def __init__(self, stage: IoStage, detail: str):
        self.stage = stage
        self.detail = detail
        super().__init__(f"{stage.value}: {detail}")


class ProcessOutputTooLargeError(ProcessError):
    pass


class ProcessDidNotExitError(ProcessError):
    pass


@dataclass(frozen=True)
class BoundedResult:
    """A finished bounded command: its exit status and merged stdout+stderr."""

    exit_status: int
    output: bytes


@dataclass(frozen=True)
class CapturedResult:
    """A finished captured command, with stdout and stderr kept separate."""

    exit_status: int
    stdout: bytes
    stderr: bytes


def _stop_process(process_handle: subprocess.Popen[bytes]) -> None:
    if process_handle.poll() is not None:
        return
    process_handle.terminate()
    try:
        process_handle.wait(timeout=_PROCESS_EXIT_POLL_SECONDS)
    except subprocess.TimeoutExpired:
        process_handle.kill()
        try:
            process_handle.wait(timeout=_PROCESS_EXIT_POLL_SECONDS)
        except subprocess.TimeoutExpired as error:
            # A child that survives `kill()` is the graver fact, so it replaces the
            # timeout or oversize error this stop was about to raise, or one already
            # in flight through the reaping `finally` (which stays its `__context__`).
            raise ProcessDidNotExitError from error


def _close_process_streams(process_handle: subprocess.Popen[bytes]) -> None:
    for stream in (process_handle.stdin, process_handle.stdout, process_handle.stderr):
        if stream is None or stream.closed:
            continue
        with suppress(OSError, ValueError):
            stream.close()


def _start_bounded_process(
    command: list[str],
    *,
    env: dict[str, str] | None,
    input_data: bytes | None,
    separate_stderr: bool,
) -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(
            command,
            stdin=subprocess.PIPE if input_data is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if separate_stderr else subprocess.STDOUT,
            env=env,
        )
    except FileNotFoundError as error:
        raise ExecutableMissingError(command[0]) from error
    except OSError as error:
        raise ProcessStartFailedError(str(error)) from error


def _register_process_streams(
    selector: selectors.BaseSelector,
    process_handle: subprocess.Popen[bytes],
    input_data: bytes | None,
) -> memoryview | None:
    assert process_handle.stdout is not None
    selector.register(process_handle.stdout, selectors.EVENT_READ, _STDOUT_KEY)
    if process_handle.stderr is not None:
        selector.register(process_handle.stderr, selectors.EVENT_READ, _STDERR_KEY)
    if input_data is None:
        return None
    assert process_handle.stdin is not None
    os.set_blocking(process_handle.stdin.fileno(), False)
    selector.register(process_handle.stdin, selectors.EVENT_WRITE, _STDIN_KEY)
    return memoryview(input_data)


def _await_process_io_events(
    selector: selectors.BaseSelector,
    process_handle: subprocess.Popen[bytes],
    deadline: float,
) -> list[tuple[selectors.SelectorKey, int]]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        _stop_process(process_handle)
        raise ProcessTimedOutError
    try:
        events = selector.select(remaining)
    except OSError as error:
        raise ProcessIoFailedError(IoStage.WAITING, str(error)) from error
    if not events:
        _stop_process(process_handle)
        raise ProcessTimedOutError
    return events


def _write_process_input(
    key: selectors.SelectorKey,
    pending_input: memoryview,
    selector: selectors.BaseSelector,
    process_handle: subprocess.Popen[bytes],
) -> memoryview:
    # `key.fileobj` is typeshed's `int | HasFileno`, the general shape any selector
    # registration may carry; this module only ever registers `process_handle`'s own
    # streams (`_register_process_streams`), so the concretely typed stream comes
    # from there instead of narrowing the selector's wider protocol.
    stream = process_handle.stdin
    assert stream is not None
    try:
        written = os.write(stream.fileno(), pending_input)
    except BrokenPipeError:
        written = len(pending_input)
    except OSError as error:
        _stop_process(process_handle)
        raise ProcessIoFailedError(IoStage.SENDING, str(error)) from error
    remaining_input = pending_input[written:]
    if not remaining_input:
        selector.unregister(key.fileobj)
        stream.close()
    return remaining_input


def _read_process_output(
    key: selectors.SelectorKey,
    selector: selectors.BaseSelector,
    output: dict[str, bytearray],
    process_handle: subprocess.Popen[bytes],
) -> None:
    stream = process_handle.stdout if key.data == _STDOUT_KEY else process_handle.stderr
    assert stream is not None
    try:
        chunk = os.read(stream.fileno(), _OUTPUT_CHUNK_BYTES)
    except OSError as error:
        raise ProcessIoFailedError(IoStage.READING, str(error)) from error
    if not chunk:
        selector.unregister(key.fileobj)
        return
    output[key.data].extend(chunk)
    if sum(len(captured) for captured in output.values()) > MAX_COMMAND_OUTPUT_BYTES:
        _stop_process(process_handle)
        raise ProcessOutputTooLargeError


def _wait_for_process_exit(process_handle: subprocess.Popen[bytes]) -> int:
    try:
        return process_handle.wait(timeout=_PROCESS_EXIT_POLL_SECONDS)
    except subprocess.TimeoutExpired as error:
        _stop_process(process_handle)
        raise ProcessDidNotExitError from error


def _reap_bounded_process(
    selector: selectors.BaseSelector | None,
    process_handle: subprocess.Popen[bytes],
) -> None:
    try:
        if selector is not None:
            selector.close()
    except OSError:
        pass
    finally:
        _close_process_streams(process_handle)
        if process_handle.poll() is None:
            _stop_process(process_handle)


def _exchange_bounded_io(
    process_handle: subprocess.Popen[bytes], *, timeout: float, input_data: bytes | None
) -> CapturedResult:
    selector: selectors.BaseSelector | None = None
    try:
        deadline = time.monotonic() + timeout
        output = {_STDOUT_KEY: bytearray(), _STDERR_KEY: bytearray()}
        selector = selectors.DefaultSelector()
        pending_input = _register_process_streams(selector, process_handle, input_data)
        while selector.get_map():
            events = _await_process_io_events(selector, process_handle, deadline)
            for key, _ in events:
                if key.data == _STDIN_KEY:
                    assert pending_input is not None
                    pending_input = _write_process_input(
                        key, pending_input, selector, process_handle
                    )
                    continue
                _read_process_output(key, selector, output, process_handle)
        exit_status = _wait_for_process_exit(process_handle)
        return CapturedResult(exit_status, bytes(output[_STDOUT_KEY]), bytes(output[_STDERR_KEY]))
    except OSError as error:
        raise ProcessIoFailedError(IoStage.COORDINATING, str(error)) from error
    finally:
        _reap_bounded_process(selector, process_handle)


def run_bounded(
    command: list[str],
    *,
    input_data: bytes | None = None,
    env: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> BoundedResult:
    """Run `command` to completion, merging stdout and stderr, bounded by `timeout`
    and `MAX_COMMAND_OUTPUT_BYTES`.

    Raises a typed `ProcessError` subclass whenever the command cannot be run to
    completion. A nonzero exit status is not one of those failures -- it comes
    back as an ordinary `BoundedResult` for the caller to interpret, since only
    the caller knows what a nonzero exit from this particular command means.
    """
    merged = _run_bounded_process(
        command, input_data=input_data, env=env, timeout=timeout, separate_stderr=False
    )
    return BoundedResult(merged.exit_status, merged.stdout)


def run_bounded_captured(
    command: list[str],
    *,
    input_data: bytes | None = None,
    env: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> CapturedResult:
    """`run_bounded` with stdout and stderr kept separate, for a caller that
    parses stdout as data (a git object id) and must not find stderr noise in
    it. The one bound `MAX_COMMAND_OUTPUT_BYTES` covers both streams together;
    errors and the nonzero-exit contract are `run_bounded`'s."""
    return _run_bounded_process(
        command, input_data=input_data, env=env, timeout=timeout, separate_stderr=True
    )


def _run_bounded_process(
    command: list[str],
    *,
    input_data: bytes | None,
    env: dict[str, str] | None,
    timeout: float,
    separate_stderr: bool,
) -> CapturedResult:
    process_handle = _start_bounded_process(
        command, env=env, input_data=input_data, separate_stderr=separate_stderr
    )
    return _exchange_bounded_io(process_handle, timeout=timeout, input_data=input_data)


def run_captured(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    cwd: Path | None = None,
) -> CapturedResult:
    """Run `command` to completion with stdout and stderr captured separately,
    in `cwd` when given, else in this process's own working directory.

    Raises `ExecutableMissingError` or `ProcessTimedOutError`; a nonzero exit status
    comes back as an ordinary `CapturedResult`. Bytes are returned undecoded,
    universal-newline handling left to the caller, so this reproduces
    `subprocess.run(check=False, capture_output=True)` rather than duplicating
    the bounded I/O machinery `run_bounded` needs for streamed input.
    """
    try:
        completed = subprocess.run(
            command, check=False, capture_output=True, timeout=timeout, env=env, cwd=cwd
        )
    except FileNotFoundError as error:
        raise ExecutableMissingError(command[0]) from error
    except subprocess.TimeoutExpired as error:
        raise ProcessTimedOutError from error
    return CapturedResult(completed.returncode, completed.stdout, completed.stderr)


def git_command(arguments: list[str], *, directory: Path | None = None) -> list[str]:
    """Build a `git arguments` command, `-C directory` prefixed when given --
    the one argv shape `checkout` and `store` each assembled by hand
    (issue #372), on two layers that may not import each other."""
    return ["git", *(["-C", str(directory)] if directory is not None else []), *arguments]


# Git reads a pathspec by what these variables inherited from the caller
# say. Only `GIT_LITERAL_PATHSPECS` is set for a read that names a path
# literally; the others contradict it (git refuses the combination) or
# make a command refuse an ordinary path.
_LITERAL_PATHSPEC_VARIABLE = "GIT_LITERAL_PATHSPECS"
_CONTRADICTING_PATHSPEC_VARIABLES = (
    "GIT_ICASE_PATHSPECS",
    "GIT_GLOB_PATHSPECS",
    "GIT_NOGLOB_PATHSPECS",
)


def _literal_pathspec_environment() -> dict[str, str]:
    """This process's environment with every path read literally by git,
    whatever pathspec settings the caller inherited."""
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in _CONTRADICTING_PATHSPEC_VARIABLES
    }
    environment[_LITERAL_PATHSPEC_VARIABLE] = "1"
    return environment


def run_git(
    arguments: list[str], *, directory: Path | None = None, literal_pathspecs: bool = False
) -> CapturedResult:
    """Launch `git arguments`, in `directory` when given via `-C`, capturing
    stdout and stderr separately. `literal_pathspecs` makes git read every
    path argument as plain name characters, whatever pathspec environment
    this process inherited -- for a caller that passes a path without magic.
    Raises `ExecutableMissingError` or
    `ProcessTimedOutError`; whether an unlisted `OSError` should also fail
    closed is each caller's own call to make around this one, since callers
    disagree (issue #372)."""
    command = git_command(arguments, directory=directory)
    if literal_pathspecs:
        return run_captured(command, env=_literal_pathspec_environment())
    return run_captured(command)


def _git_failure_detail(stderr: bytes, stdout: bytes, *, errors: str = "strict") -> str:
    """The bytes-level core every git failure-detail reader below shares
    (issue #392 review round 2): decode-and-strip `stderr`, falling back to
    the same treatment of `stdout`, falling back to `UNKNOWN_GIT_FAILURE`
    when neither carried anything. Each public reader below is a thin
    adapter feeding this the two streams its own result shape actually
    carries -- never a second copy of this decode/strip/fallback logic.

    `errors` defaults to strict, matching `git_failure_detail`'s and
    `git_failure_detail_from_stderr`'s long-standing contract: invalid UTF-8
    in git's own stderr raises `UnicodeDecodeError` rather than silently
    replacing it, since `store._delete_export_ref` (issue #298) relies on
    that raise reaching its own `(ClaimError, OSError, ValueError)` catch
    and carrying the decode failure itself into the leftover description it
    returns. `git_failure_detail_lossy` opts into `errors="replace"`
    instead, preserving its own pre-existing lenient behaviour."""
    return (
        stderr.decode(errors=errors).strip()
        or stdout.decode(errors=errors).strip()
        or UNKNOWN_GIT_FAILURE
    )


def git_failure_detail(result: CapturedResult) -> str:
    """A finished `git` invocation's stderr, falling back to stdout, falling
    back to `UNKNOWN_GIT_FAILURE` when neither stream carried anything.

    For a command whose successful stdout is itself meaningful (`git log`,
    `git ls-tree`, `git bundle create`, ...), a stray leftover on stdout from
    a *failed* run is still the best available detail. Use
    `git_failure_detail_from_stderr` instead for a command whose stdout never
    carries the result -- `fetch`, `update-ref`, and the like -- where
    falling back to it would report unrelated stdout content, not the
    failure (issue #372 R1)."""
    return _git_failure_detail(result.stderr, result.stdout)


def git_failure_detail_from_stderr(result: CapturedResult) -> str:
    """A finished `git` invocation's stderr alone, falling back to
    `UNKNOWN_GIT_FAILURE` when it carried nothing -- stdout is never read,
    unlike `git_failure_detail` (issue #372 R1); see that function's
    docstring for which of the two modes a caller wants."""
    return _git_failure_detail(result.stderr, b"")


def git_failure_detail_lossy(result: CapturedResult) -> str:
    """`git_failure_detail` for a command run with piped stdin (`hash-object`,
    `mktree`), decoding with replacement instead of raising: the claim store
    surfaces such a failure as a `ClaimError`, never as a decode error (issue
    #390 finding 7)."""
    return _git_failure_detail(result.stderr, result.stdout, errors="replace")
