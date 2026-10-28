"""How many landings on the trunk `aco next` counts since a ruling, read from a real
trunk history. The forge is the only fake."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from board_fixtures import board_issue, complete_contract, ruled_expectation
from cli_fixtures import add_lane_worktree, freeze_cli_now, push_lane_branch, real_git, run_cli
from github_fixtures import FakeForge, assert_github_world, serve_forge

RULED_ON = date(2020, 1, 1)
LANE_BRANCH = "codex/issue-10-work"


def land_on_the_trunk(monkeypatch: pytest.MonkeyPatch, clone: Path, *committed_at: str) -> None:
    """Commits on the primary checkout's `main`, pushed, so the lane's `HEAD`
    stands behind the trunk."""
    for index, moment in enumerate(committed_at):
        (clone / f"landed-{index}.txt").write_text(f"{index}\n")
        real_git(clone, "add", ".")
        monkeypatch.setenv("GIT_COMMITTER_DATE", moment)
        real_git(clone, "commit", "-q", "-m", f"land {index}")
    real_git(clone, "push", "-q", "origin", "main")


@pytest.fixture
def lane(monkeypatch: pytest.MonkeyPatch, github_clone: Path, bare_remote: Path) -> Path:
    assert_github_world(github_clone, bare_remote)
    freeze_cli_now(monkeypatch)
    issue = board_issue(
        10,
        "Work",
        complete_contract(
            "Claim #10.", expectation=[ruled_expectation("Name it.", ruled_on=RULED_ON)]
        ),
    )
    serve_forge(monkeypatch, FakeForge(board_issues=(issue,)))
    push_lane_branch(github_clone, LANE_BRANCH)
    directory = github_clone.parent / "lane"
    add_lane_worktree(github_clone, directory, LANE_BRANCH)
    monkeypatch.chdir(directory)
    return github_clone


def landings_on(day: int, count: int, *, hour: int = 0) -> tuple[str, ...]:
    return tuple(f"2020-01-{day:02d}T{hour:02d}:00:00+00:00" for _ in range(count))


@pytest.mark.parametrize(
    ("committed_at", "counted", "old"),
    [
        pytest.param(landings_on(2, 9), 10, True, id="nine-pushed-and-the-checkouts-own-make-ten"),
        pytest.param(
            (*landings_on(1, 1, hour=23), *landings_on(2, 8)),
            9,
            False,
            id="one-on-the-ruling-day-is-not-counted",
        ),
    ],
)
def test_next_counts_the_landings_on_the_remote_trunk_since_the_ruling_day(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    lane: Path,
    committed_at: tuple[str, ...],
    counted: int,
    old: bool,
) -> None:
    """Spec: NEXT-04 -- the fixture's own trunk commit, made today, is one more landing."""
    land_on_the_trunk(monkeypatch, lane, *committed_at)

    payload = json.loads(run_cli(["next", "--json"], capsys).stdout)

    assert (payload["ruling_landings"], payload["ruling_old"]) == (counted, old)


def test_next_names_an_old_ruling_in_text_and_json_when_the_item_is_pulled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], lane: Path
) -> None:
    """Spec: NEXT-04, NEXT-11."""
    land_on_the_trunk(monkeypatch, lane, *landings_on(2, 9))
    hint = "ruled 10 landings ago: refine again at the pull"

    text = run_cli(["next"], capsys)
    as_json = run_cli(["next", "--json"], capsys)
    payload = json.loads(as_json.stdout)

    assert (text.status, text.stdout) == (
        0,
        "#10 score -10: Work\nNext: Claim #10.\nRun: aco claim 10 --scope <paths>\n"
        f"scope unknown\n{hint}\nparallel: unknown (first action names no scope)\nclose: none\n",
    )
    assert as_json.status == 0
    assert (payload["ruling_landings"], payload["ruling_old"], payload["ruling_hint"]) == (
        10,
        True,
        hint,
    )
