"""A grandchild's landing closes its phase container and never the epic above it; `aco next` then
offers that epic as `close_container`."""

from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, complete_contract, container_with_children
from check_pull_request_fixtures import (
    PARENT_ISSUE,
    WORK_ITEM,
    ParentWorld,
    PullRequestCheck,
    PullRequestWorld,
    declares,
    refused,
)
from cli_fixtures import freeze_cli_now, run_cli, track_board_config
from github_fixtures import FakeForge, assert_github_world, serve_forge

TOP_EPIC = 1
PHASE_WORLD = PullRequestWorld(parent=ParentWorld(complete_contract("keiner")))
CLOSES_GRANDCHILD_AND_PHASE = f"Work-Item: #72\n\nCloses #72\nCloses #{PARENT_ISSUE}"
CLOSES_ALSO_THE_TOP_EPIC = f"{CLOSES_GRANDCHILD_AND_PHASE}\nCloses #{TOP_EPIC}"


def test_a_grandchilds_landing_closes_its_phase_and_never_the_top_epic(
    check_pull_request: PullRequestCheck,
) -> None:
    """Spec: LAND-21"""
    check_pull_request(
        declares(CLOSES_GRANDCHILD_AND_PHASE, f"Work-Item: {WORK_ITEM}", 5, PHASE_WORLD), []
    )


def test_a_grandchilds_landing_that_also_closes_the_top_epic_is_refused(
    check_pull_request: PullRequestCheck,
) -> None:
    """Spec: LAND-21, LAND-27"""
    check_pull_request(
        refused(
            CLOSES_ALSO_THE_TOP_EPIC,
            f"closes {REPOSITORY}#{TOP_EPIC} besides its work item {WORK_ITEM}; "
            "a pull request lands one item",
            5,
            PHASE_WORLD,
        ),
        [],
    )


def test_next_offers_the_top_epic_as_close_container_once_its_last_phase_closed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: NEXT-07"""
    assert_github_world(github_clone, bare_remote)
    track_board_config(github_clone, 'idea_label = "idea"\n')
    freeze_cli_now(monkeypatch)
    top_epic, phases = container_with_children(TOP_EPIC, closed=1, body=complete_contract("keiner"))
    serve_forge(
        monkeypatch,
        FakeForge(
            board_issues=(top_epic,),
            children={TOP_EPIC: phases},
        ),
    )

    result = run_cli(["next"], capsys)

    assert (result.status, result.stdout.splitlines()[0]) == (
        0,
        f"close_container #{TOP_EPIC}: 1/1 children closed, no uncut row",
    )
