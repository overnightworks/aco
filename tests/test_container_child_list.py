"""A container's child counts and open children come from its sub-issue list
alone; a lagging child-count summary refuses nothing."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from board_fixtures import (
    complete_contract,
    container_with_children,
    projected_board,
    slice_entries,
)
from cli_fixtures import freeze_cli_now, run_cli, track_board_config
from github_fixtures import FakeForge, assert_github_world, serve_forge

from aco import workboard
from aco.body import Storage
from aco.workboard import BoardConfig, CloseContainerAction, ContainerProgress

CONTAINER = 243
NOW = datetime(2026, 8, 21, tzinfo=UTC)


def _stale_summary(container: workboard.Issue, *, closed: int, total: int) -> workboard.Issue:
    return replace(container, children_closed=closed, children_total=total)


def _progress_figures(progress: ContainerProgress | None) -> tuple[int, int, tuple[int, ...]]:
    assert progress is not None
    return progress.closed, progress.total, tuple(child.number for child in progress.open_children)


def test_a_summary_still_counting_an_open_child_yields_to_a_list_of_closed_children() -> None:
    """Spec: BOARD-58"""
    listed, children = container_with_children(
        CONTAINER, closed=2, body=complete_contract("keiner")
    )
    container = _stale_summary(listed, closed=1, total=2)

    projected = projected_board(
        (container,), (), (), (), BoardConfig(), now=NOW, children={CONTAINER: children}
    )
    action = workboard.next_action(projected)

    assert _progress_figures(projected.items[0].container) == (2, 2, ())
    assert isinstance(action, CloseContainerAction)


def test_a_summary_counting_every_child_closed_yields_to_a_list_holding_an_open_one() -> None:
    """Spec: BOARD-58"""
    listed, children = container_with_children(
        CONTAINER, closed=1, open_children=(244,), body=complete_contract("Cut the next slice.")
    )
    container = _stale_summary(listed, closed=2, total=2)

    projected = projected_board(
        (container,), (), (), (), BoardConfig(), now=NOW, children={CONTAINER: children}
    )
    item = projected.items[0]

    assert (
        _progress_figures(item.container),
        item.actionable_reason,
        workboard.zero_cost_closes(projected),
        isinstance(workboard.next_action(projected), CloseContainerAction),
    ) == ((1, 2, (244,)), "container; claim a child", (), False)


@pytest.mark.parametrize(
    ("open_children", "named"), [((), True), ((244,), False)], ids=["no-open-child", "open-child"]
)
def test_a_container_without_an_open_listed_child_is_read_for_its_nesting_parent(
    open_children: tuple[int, ...], named: bool
) -> None:
    """Spec: BOARD-58"""
    listed, children = container_with_children(
        CONTAINER,
        closed=1,
        open_children=open_children,
        body=complete_contract("keiner", slice=slice_entries("Scheibe")),
    )
    container = _stale_summary(listed, closed=0, total=1)

    named_containers = workboard.childless_containers_with_uncut_rows(
        (container,), {CONTAINER: children}, Storage.GITHUB
    )

    assert (named_containers == (CONTAINER,)) is named


def test_next_names_a_container_closable_whose_summary_lags_its_closed_children(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: BOARD-58, NEXT-07"""
    assert_github_world(github_clone, bare_remote)
    track_board_config(github_clone, 'body_contract = "block"\nidea_label = "idea"\n')
    freeze_cli_now(monkeypatch)
    listed, children = container_with_children(
        CONTAINER, closed=2, body=complete_contract("keiner")
    )
    serve_forge(
        monkeypatch,
        FakeForge(
            board_issues=(_stale_summary(listed, closed=1, total=2),),
            children={CONTAINER: children},
        ),
    )

    result = run_cli(["next"], capsys)

    assert (result.status, result.stdout.splitlines()[0]) == (
        0,
        f"close_container #{CONTAINER}: 2/2 children closed, no Next work",
    )
