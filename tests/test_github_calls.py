"""The record of every `gh` call (`specs/github-calls.spec.md`, CALLS-01 to CALLS-09), read from
the real record file with a fake `gh` on `PATH`."""

import contextlib
import dataclasses
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from cli_fixtures import run_cli
from rate_limit_fixtures import REST_REFUSAL

from aco import (
    file_lock,
    forge,
    github,
    github_calls,
    github_failure,
    github_probe,
    process,
    protocol,
)

# Prints `FAKE_GH_OUTPUT_HEX` (bytes in hex) or, when `FAKE_GH_FLOOD_BYTES` is set, that many
# bytes, and exits with `FAKE_GH_EXIT`, after sleeping `FAKE_GH_SLEEP_SECONDS` when set; a
# `rate_limit` read always answers an implausible reset.
FAKE_GH = """#!{python}
import os, sys, time

if "rate_limit" in sys.argv[1:]:
    print("soon")
    sys.exit(0)
if "FAKE_GH_SLEEP_SECONDS" in os.environ:
    time.sleep(float(os.environ["FAKE_GH_SLEEP_SECONDS"]))
flood = os.environ.get("FAKE_GH_FLOOD_BYTES")
if flood:
    sys.stdout.buffer.write(b"x" * int(flood))
else:
    sys.stdout.buffer.write(bytes.fromhex(os.environ.get("FAKE_GH_OUTPUT_HEX", "")))
sys.exit(int(os.environ.get("FAKE_GH_EXIT", "0")))
"""
REPOSITORY = "example/agent-coordination"
ANOTHER_REPOSITORY = "example/other"
READ = ["gh", "api", f"repos/{REPOSITORY}"]
NOT_MODIFIED = b'HTTP/2.0 304 Not Modified\r\nEtag: W/"4f9c"\r\n\r\n'
NO_RATE_LIMIT = b"gh: Not Found (HTTP 404)"


@pytest.fixture(autouse=True)
def fake_gh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A `gh` on `PATH` as described above: it answers `{}` and exits 0 until a test says
    otherwise."""
    shims = tmp_path / "gh-bin"
    shims.mkdir()
    executable = shims / "gh"
    executable.write_text(FAKE_GH.format(python=sys.executable))
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shims}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_OUTPUT_HEX", b"{}".hex())


def gh_answers(monkeypatch: pytest.MonkeyPatch, output: bytes, exit_status: int) -> None:
    monkeypatch.setenv("FAKE_GH_OUTPUT_HEX", output.hex())
    monkeypatch.setenv("FAKE_GH_EXIT", str(exit_status))


@pytest.fixture
def state_directory(tmp_path: Path) -> Path:
    return tmp_path / "state" / "aco"


def lines_of(directory: Path) -> list[dict[str, object]]:
    record = directory / github_calls.RECORD_FILE
    return [json.loads(line) for line in record.read_text().splitlines()]


def read() -> tuple[str, int]:
    return github.response_command(READ, purpose="a test call", repository=REPOSITORY)


def call(command: list[str] | None = None, repository: str | None = REPOSITORY) -> None:
    """One call through the real hook; a refusal is the caller's business, not the test's."""
    with contextlib.suppress(forge.ForgeError):
        github.response_command(command or READ, purpose="a test call", repository=repository)


@pytest.mark.parametrize(
    ("output", "exit_status", "outcome"),
    [
        pytest.param(b"{}", 0, github_calls.Outcome.ANSWERED, id="answered"),
        pytest.param(
            NOT_MODIFIED, 1, github_calls.Outcome.NOT_MODIFIED, id="304-whatever-gh-exits"
        ),
        pytest.param(NOT_MODIFIED, 0, github_calls.Outcome.NOT_MODIFIED, id="304-exiting-zero"),
        pytest.param(
            REST_REFUSAL.encode(), 1, github_calls.Outcome.RATE_LIMITED, id="rate-limited"
        ),
        pytest.param(NO_RATE_LIMIT, 1, github_calls.Outcome.FAILED, id="other-failure"),
        pytest.param(b"\xff\xfe", 0, github_calls.Outcome.ANSWERED, id="non-utf8-answer"),
    ],
)
def test_a_call_records_how_it_ended(
    monkeypatch: pytest.MonkeyPatch,
    state_directory: Path,
    output: bytes,
    exit_status: int,
    outcome: github_calls.Outcome,
) -> None:
    """Spec: CALLS-04."""
    gh_answers(monkeypatch, output, exit_status)

    with github_calls.recording(state_directory, "item"):
        call()

    assert [line["outcome"] for line in lines_of(state_directory)] == [outcome]


def test_a_non_utf8_answer_still_raises_after_it_is_recorded(
    monkeypatch: pytest.MonkeyPatch, state_directory: Path
) -> None:
    """Spec: CALLS-01, CALLS-04 -- recording judges the raw answer, before it is decoded."""
    gh_answers(monkeypatch, b"\xff\xfe", 0)

    with github_calls.recording(state_directory, "item"), pytest.raises(forge.ForgeError):
        read()

    assert len(lines_of(state_directory)) == 1


def test_a_call_that_gives_no_answer_within_its_bounds_records_failed(
    monkeypatch: pytest.MonkeyPatch, state_directory: Path
) -> None:
    """Spec: CALLS-04 -- output past the bound is no answer, and the read raises as before."""
    monkeypatch.setenv("FAKE_GH_FLOOD_BYTES", str(process.MAX_COMMAND_OUTPUT_BYTES + 1))

    with github_calls.recording(state_directory, "item"), pytest.raises(forge.ForgeError):
        read()

    assert [line["outcome"] for line in lines_of(state_directory)] == [github_calls.Outcome.FAILED]


def test_a_gh_that_cannot_be_started_records_nothing(
    monkeypatch: pytest.MonkeyPatch, state_directory: Path
) -> None:
    """Spec: CALLS-01."""
    monkeypatch.setenv("PATH", str(state_directory))

    with github_calls.recording(state_directory, "item"), pytest.raises(protocol.ClaimError):
        github.response_command(READ, purpose="a test call", repository=REPOSITORY)

    assert not (state_directory / github_calls.RECORD_FILE).exists()


@pytest.mark.parametrize(
    ("command", "quota"),
    [
        pytest.param(["gh", "api", "graphql", "-f", "query={x}"], github_failure.Quota.GRAPHQL),
        pytest.param(["gh", "api", "search/issues?q=x"], github_failure.Quota.SEARCH),
        pytest.param(["gh", "api", "rate_limit"], github_failure.Quota.UNCOUNTED),
        pytest.param(READ, github_failure.Quota.CORE),
    ],
    ids=["graphql", "search", "rate-limit-read", "core"],
)
def test_a_call_records_the_quota_it_spends(
    state_directory: Path, command: list[str], quota: github_failure.Quota
) -> None:
    """Spec: CALLS-05."""
    with github_calls.recording(state_directory, "item"):
        call(command)

    assert [line["quota"] for line in lines_of(state_directory)] == [quota]


def test_a_call_names_the_repository_of_the_component_that_made_it(
    monkeypatch: pytest.MonkeyPatch, state_directory: Path
) -> None:
    """Spec: CALLS-03 -- a forge, a probe, a probe's reset read after a refusal and a search."""
    forge_client = github.GitHubForge(github.repository_id(REPOSITORY))
    probe = github_probe.GitHubBoardProbe(github.response_command)
    gh_answers(monkeypatch, b"main", 0)

    with github_calls.recording(state_directory, "wait"):
        forge_client.default_branch()
        gh_answers(monkeypatch, b'HTTP/2.0 200 OK\r\nEtag: W/"1"\r\n\r\n[]', 0)
        probe.changed_since(forge.ProbeTarget(ANOTHER_REPOSITORY), None)
        gh_answers(monkeypatch, REST_REFUSAL.encode(), 1)
        with pytest.raises(forge.ForgeRateLimitedError):
            probe.changed_since(forge.ProbeTarget(ANOTHER_REPOSITORY), None)
        gh_answers(monkeypatch, b"{}", 0)
        github.bounded_command(["gh", "api", "search/issues?q=x"], purpose="a search")

    assert [line["repository"] for line in lines_of(state_directory)] == [
        REPOSITORY,
        ANOTHER_REPOSITORY,
        ANOTHER_REPOSITORY,
        ANOTHER_REPOSITORY,
        None,
    ]


def test_every_call_leaves_exactly_one_line_of_the_declared_keys_and_no_secret(
    monkeypatch: pytest.MonkeyPatch, state_directory: Path
) -> None:
    """Spec: CALLS-01, CALLS-02, CALLS-06, CALLS-09 -- one line per round trip, so the lines
    equal the forge's own `requests`; no argument or answer reaches the file."""
    secret = "ghp_secretmarker"
    gh_answers(monkeypatch, f'{{"token":"{secret}"}}'.encode(), 0)
    client = github.GitHubForge(github.repository_id(REPOSITORY))
    gh_answers(monkeypatch, f"gh: {secret} (HTTP 404)".encode(), 1)

    with github_calls.recording(state_directory, "item"):
        github.response_command(
            [*READ, "-H", f"Authorization: token {secret}"], purpose="a test call", repository=None
        )
        with pytest.raises(forge.ForgeNotFoundError):
            client.default_branch()

    lines = lines_of(state_directory)
    declared = {field.name for field in dataclasses.fields(github_calls.CallRecord)}
    assert (len(lines), {frozenset(line) for line in lines}) == (
        client.requests + 1,
        {frozenset(declared)},
    )
    assert secret not in (state_directory / github_calls.RECORD_FILE).read_text()
    first = lines[0]
    assert list(first) == [field.name for field in dataclasses.fields(github_calls.CallRecord)]
    assert (first["command"], first["pid"]) == ("item", os.getpid())
    for moment in (first["at"], first["started"]):
        assert protocol.RFC3339_TIMESTAMP_PATTERN.fullmatch(str(moment))


def test_a_call_outside_a_recording_leaves_no_file(state_directory: Path) -> None:
    """Spec: CALLS-01 -- library use records nothing."""
    call()

    assert not state_directory.exists()


def test_the_record_is_private_and_made_with_its_missing_directories(
    state_directory: Path,
) -> None:
    """Spec: CALLS-06 -- the file is 0600, a directory it had to create 0700."""
    with github_calls.recording(state_directory, "item"):
        call()

    record = state_directory / github_calls.RECORD_FILE
    assert (record.stat().st_mode & 0o777, state_directory.stat().st_mode & 0o777) == (0o600, 0o700)


def test_a_record_that_cannot_be_written_warns_once_and_costs_the_command_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Spec: CALLS-08."""
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the state directory should be")
    gh_answers(monkeypatch, b"main", 0)

    with github_calls.recording(blocked, "item"):
        answers = [
            github.response_command(READ, purpose="a test call", repository=REPOSITORY)
            for _ in range(3)
        ]

    warnings = capsys.readouterr().err.splitlines()
    assert (
        answers,
        len(warnings),
        warnings[0].startswith("warning: GitHub calls not recorded"),
    ) == (
        [("main", 0)] * 3,
        1,
        True,
    )


def test_a_record_past_the_bound_moves_aside_and_the_next_call_starts_a_fresh_one(
    state_directory: Path,
) -> None:
    """Spec: CALLS-07 -- the older generation is replaced, never kept beside two others."""
    state_directory.mkdir(parents=True)
    record = state_directory / github_calls.RECORD_FILE
    rotated = state_directory / github_calls.ROTATED_FILE
    record.touch()
    os.truncate(record, github_calls.ROTATION_BYTES)
    rotated.write_text("the older generation")

    with github_calls.recording(state_directory, "item"):
        call()
        call()

    fresh = lines_of(state_directory)
    assert (
        rotated.stat().st_size > github_calls.ROTATION_BYTES,
        len(fresh),
        sorted(path.name for path in state_directory.glob("github-calls*.jsonl")),
    ) == (True, 1, sorted([github_calls.RECORD_FILE, github_calls.ROTATED_FILE]))


def test_a_command_prints_the_same_with_a_record_it_can_write_and_one_it_cannot(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_world: Path,
    tmp_path: Path,
) -> None:
    """Spec: CALLS-08, CALLS-09 -- the record changes no command's stdout."""
    gh_answers(monkeypatch, NO_RATE_LIMIT, 1)
    monkeypatch.chdir(github_world)
    command = ["--repo", REPOSITORY, "item", "show", "7", "--json"]
    writable = tmp_path / "writable"
    unwritable = tmp_path / "unwritable"
    unwritable.write_text("a file where the state directory should be")
    monkeypatch.setenv("XDG_STATE_HOME", str(writable))

    first = run_cli(command, capsys)
    monkeypatch.setenv("XDG_STATE_HOME", str(unwritable))
    second = run_cli(command, capsys)

    recorded = lines_of(writable / "aco")
    assert (first.stdout, first.status) == (second.stdout, second.status)
    assert {line["command"] for line in recorded} == {"item"}


@pytest.mark.parametrize(
    ("exit_status", "outcome"),
    [
        pytest.param(0, github_calls.Outcome.ANSWERED, id="answered"),
        pytest.param(1, github_calls.Outcome.FAILED, id="failed"),
    ],
)
def test_a_repository_discovery_records_a_graphql_call_without_a_repository(
    monkeypatch: pytest.MonkeyPatch,
    state_directory: Path,
    exit_status: int,
    outcome: github_calls.Outcome,
) -> None:
    """Spec: CALLS-03, CALLS-04, CALLS-05 -- discovery is judged on its exit status alone."""
    gh_answers(monkeypatch, REPOSITORY.encode(), exit_status)

    with github_calls.recording(state_directory, "claim"), contextlib.suppress(protocol.ClaimError):
        github.discover_repository(remote_url="/not/a/github/remote")

    assert [
        (line["repository"], line["quota"], line["outcome"]) for line in lines_of(state_directory)
    ] == [(None, github_failure.Quota.GRAPHQL, outcome)]


def test_a_repository_discovery_that_times_out_records_failed(
    monkeypatch: pytest.MonkeyPatch, state_directory: Path
) -> None:
    """Spec: CALLS-04."""

    monkeypatch.setattr(github, "GH_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setenv("FAKE_GH_SLEEP_SECONDS", "30")

    with github_calls.recording(state_directory, "claim"), pytest.raises(protocol.ClaimError):
        github.discover_repository(remote_url="/not/a/github/remote")

    assert [line["outcome"] for line in lines_of(state_directory)] == [github_calls.Outcome.FAILED]


def test_a_record_another_process_moved_aside_meanwhile_is_not_moved_again(
    monkeypatch: pytest.MonkeyPatch, state_directory: Path
) -> None:
    """Spec: CALLS-07 -- the size is judged again under the lock, so one generation is never
    renamed twice and the older one lost."""
    state_directory.mkdir(parents=True)
    record = state_directory / github_calls.RECORD_FILE
    record.touch()
    os.truncate(record, github_calls.ROTATION_BYTES)
    held = file_lock.held

    @contextlib.contextmanager
    def held_after_another_process_rotated(path: Path) -> Iterator[None]:
        with held(path):
            os.truncate(record, 0)
            yield

    monkeypatch.setattr(file_lock, "held", held_after_another_process_rotated)

    with github_calls.recording(state_directory, "item"):
        call()

    assert not (state_directory / github_calls.ROTATED_FILE).exists()
