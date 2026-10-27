"""`aco land` refuses a pull request whose head branch it must not act on."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from cli_fixtures import run_cli
from github_fixtures import (
    MERGE_COMMIT_SHA,
    LaneLandingWorld,
    RefusalLength,
    landed_world,
    refusal_observations,
)

from aco import github, report

FORK = "stranger/fork"
LONG_UNSAFE_NAME = "x" * 400 + ".."


@dataclass(frozen=True)
class Refused:
    """A pull request whose head the land refuses with `sentence` (`{branch}` is the
    head name shown with `!r`)."""

    head_branch: str
    merged: bool
    sentence: str
    head_repository: str | None = None
    dirty_checkout: bool = False
    length: RefusalLength = RefusalLength.UNCHECKED


FORK_SENTENCE = (
    f"pull request #12 proposes a branch of {FORK}; cross-repository pull requests "
    "are not classified"
)


def unsafe_sentence(shown_branch: str) -> str:
    return f"pull request #12 head branch {shown_branch} is no safe branch name"


@pytest.fixture
def lane(
    github_clone: Path, bare_remote: Path, monkeypatch: pytest.MonkeyPatch
) -> LaneLandingWorld:
    return landed_world(github_clone, bare_remote, monkeypatch).landing


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            Refused("release/1.x", True, FORK_SENTENCE, head_repository=FORK), id="fork-rerun"
        ),
        pytest.param(
            Refused("release/1.x", True, FORK_SENTENCE, head_repository=FORK, dirty_checkout=True),
            id="fork-rerun-on-a-dirty-checkout-names-the-fork",
        ),
        pytest.param(Refused("bad..name", True, unsafe_sentence("'bad..name'")), id="dotdot-rerun"),
        pytest.param(Refused("main#x", True, unsafe_sentence("'main#x'")), id="hash-rerun"),
        pytest.param(
            Refused("main#x", False, unsafe_sentence("'main#x'")),
            id="unsafe-first-run-without-a-claim",
        ),
        pytest.param(
            Refused("bad\nname", False, unsafe_sentence("'bad\\nname'")),
            id="newline-first-run-is-escaped-on-one-line",
        ),
        pytest.param(
            Refused("bad\nname", True, unsafe_sentence("'bad\\nname'")),
            id="newline-rerun-is-escaped-on-one-line",
        ),
        pytest.param(
            Refused(
                LONG_UNSAFE_NAME,
                False,
                report.bounded_refusal(unsafe_sentence(repr(LONG_UNSAFE_NAME))),
                length=RefusalLength.EXACTLY_LIMIT,
            ),
            id="long-unsafe-name-first-run-is-cut",
        ),
        pytest.param(
            Refused(
                LONG_UNSAFE_NAME,
                True,
                report.bounded_refusal(unsafe_sentence(repr(LONG_UNSAFE_NAME))),
                length=RefusalLength.EXACTLY_LIMIT,
            ),
            id="long-unsafe-name-rerun-is-cut",
        ),
        pytest.param(
            Refused("main#x", True, unsafe_sentence("'main#x'"), head_repository=FORK),
            id="unsafe-fork-rerun-names-the-branch-first",
        ),
        pytest.param(
            Refused("main#x", False, unsafe_sentence("'main#x'"), head_repository=FORK),
            id="unsafe-fork-first-run-names-the-branch-first",
        ),
    ],
)
def test_land_refuses_a_head_it_must_not_act_on_before_any_write(
    lane: LaneLandingWorld, capsys: pytest.CaptureFixture[str], case: Refused
) -> None:
    """Spec: LANDCMD-50..53 -- an unsafe head name refuses on both paths and a merged
    pull request of another repository refuses on rerun, before anything is written,
    the unsafe name first."""
    landing = lane.forge.landings[12]
    lane.forge.landings[12] = replace(
        landing,
        source_branch=case.head_branch,
        source_repository=github.repository_id(
            case.head_repository or landing.source_repository.path
        ),
        merged=case.merged,
        merge_commit=MERGE_COMMIT_SHA if case.merged else None,
    )
    if case.dirty_checkout:
        (lane.clone / "dirty.txt").write_text("uncommitted\n")
        (lane.clone / "README").write_text("changed\n")
    capsys.readouterr()
    result = run_cli(["land", "12", "--head", lane.head], capsys)
    observed, expected = refusal_observations(lane, result, case.sentence, length=case.length)
    assert observed == expected


def test_land_still_deletes_exactly_the_branch_of_its_own_merged_pull_request(
    lane: LaneLandingWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANDCMD-50 -- a merged pull request of this repository with a safe head
    name continues as before."""
    landing = lane.forge.landings[12]
    lane.forge.landings[12] = replace(landing, merged=True, merge_commit=MERGE_COMMIT_SHA)
    capsys.readouterr()
    run_cli(["land", "12", "--head", lane.head], capsys)
    assert lane.forge.deleted_branches == [landing.source_branch]
