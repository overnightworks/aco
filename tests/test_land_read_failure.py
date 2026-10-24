"""A GitHub read that fails before the merge refuses naming what was read."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from cli_fixtures import run_cli
from github_fixtures import (
    MERGE_COMMIT_SHA,
    FakeForge,
    LaneLandingWorld,
    RefusalLength,
    landed_world,
    refusal_observations,
)

from aco import forge

JSON_ERROR = "unexpected end of JSON input"
PULL_REQUEST_STEP = "the pull request"
PRECONDITIONS_STEP = "its landing preconditions"
MERGE_RULES_STEP = "its merge rules"
LONG_CONTROLS = "\x1b[31m" + "x" * 400


@dataclass(frozen=True)
class ReadFailure:
    """`call`-th call of the forge's `read` raises `error`; `step` names it, or
    `None` where the refusal keeps the forge's bare text."""

    read: str
    error: forge.ForgeError
    step: str | None
    call: int = 1
    rerun: bool = False
    length: RefusalLength = RefusalLength.UNCHECKED


def with_json_error(read: str, step: str, call: int = 1, rerun: bool = False) -> ReadFailure:
    return ReadFailure(read, forge.ForgeError(JSON_ERROR), step, call, rerun)


def fail_on_call(
    monkeypatch: pytest.MonkeyPatch, client: FakeForge, failure: ReadFailure
) -> list[int]:
    """Make `failure.read` raise on its `failure.call`-th call; the returned
    list gains one entry per call, so a test counts how often it ran."""
    calls: list[int] = []
    original = getattr(client, failure.read)

    def read(*arguments: object) -> object:
        calls.append(len(calls) + 1)
        if calls[-1] == failure.call:
            raise failure.error
        return original(*arguments)

    monkeypatch.setattr(client, failure.read, read)
    return calls


@pytest.fixture
def lane(
    github_clone: Path, bare_remote: Path, monkeypatch: pytest.MonkeyPatch
) -> LaneLandingWorld:
    return landed_world(github_clone, bare_remote, monkeypatch).landing


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(with_json_error("landing", PULL_REQUEST_STEP), id="pull-request"),
        pytest.param(
            with_json_error("landing", PULL_REQUEST_STEP, rerun=True), id="pull-request-rerun"
        ),
        pytest.param(
            with_json_error("landing_readiness", PRECONDITIONS_STEP), id="preconditions-readiness"
        ),
        pytest.param(
            with_json_error("landing", PRECONDITIONS_STEP, call=2), id="preconditions-detail"
        ),
        pytest.param(
            with_json_error("allowed_merge_methods", MERGE_RULES_STEP), id="merge-rules-settings"
        ),
        pytest.param(with_json_error("branch_merge_rules", MERGE_RULES_STEP), id="merge-rules"),
        pytest.param(
            ReadFailure(
                "landing_readiness",
                forge.ForgeTransientError("GitHub returned HTTP 502"),
                PRECONDITIONS_STEP,
            ),
            id="transient",
        ),
        pytest.param(
            ReadFailure(
                "landing_readiness",
                forge.ForgeMalformedResponseError("not JSON"),
                PRECONDITIONS_STEP,
            ),
            id="malformed",
        ),
        pytest.param(
            ReadFailure(
                "landing_readiness", forge.ForgeNotFoundError("GitHub returned HTTP 404"), None
            ),
            id="not-found-keeps-its-text",
        ),
        pytest.param(
            ReadFailure(
                "landing_readiness",
                forge.ForgePermissionDeniedError("GitHub returned HTTP 403"),
                None,
            ),
            id="permission-denied-keeps-its-text",
        ),
        pytest.param(
            ReadFailure(
                "landing_readiness", forge.ForgeUnsupportedError("not supported here"), None
            ),
            id="unsupported-keeps-its-text",
        ),
        pytest.param(
            ReadFailure(
                "allowed_merge_methods",
                forge.ForgeError(LONG_CONTROLS),
                MERGE_RULES_STEP,
                length=RefusalLength.EXACTLY_LIMIT,
            ),
            id="long-text-with-controls-is-cut-and-the-advice-stays",
        ),
    ],
)
def test_a_failed_read_refuses_naming_what_was_read(
    lane: LaneLandingWorld,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: ReadFailure,
) -> None:
    """Spec: LANDCMD-46, LANDCMD-47, LANDCMD-48, LANDCMD-49 -- the refusal names what was read
    and advises a re-run; the failed read ran once, and nothing was written."""
    if failure.rerun:
        merged = replace(lane.forge.landings[12], merged=True, merge_commit=MERGE_COMMIT_SHA)
        lane.forge.landings[12] = merged
    calls = fail_on_call(monkeypatch, lane.forge, failure)
    prefix = "pull request #12 was not merged: reading "
    suffix = "); re-run aco land 12"
    if failure.step is None:
        sentence = str(failure.error)
    elif failure.length is RefusalLength.UNCHECKED:
        sentence = f"{prefix}{failure.step} failed ({failure.error}{suffix}"
    else:
        shown_controls = "\\x1b[31m"
        # 200 characters in all: `ERROR: `, the words around the text, the text cut to fit and `…`.
        room = 200 - len("ERROR: ") - len(f"{prefix}{failure.step} failed ({suffix}")
        sentence = (
            f"{prefix}{failure.step} failed "
            f"({shown_controls}{'x' * (room - len(shown_controls) - 1)}…{suffix}"
        )
    capsys.readouterr()
    result = run_cli(["land", "12", "--head", lane.head], capsys)
    observed, expected = refusal_observations(lane, result, sentence, length=failure.length)
    observed["failed read runs"] = len(calls)
    expected["failed read runs"] = failure.call
    assert observed == expected
