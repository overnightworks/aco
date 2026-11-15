"""A container's child counts and open children come from its sub-issue list
alone; a lagging child-count summary refuses nothing."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from board_fixtures import (
    REPOSITORY,
    board_issue,
    complete_contract,
    container_with_children,
    projected_board,
    slice_entries,
)
from cli_fixtures import freeze_cli_now, run_cli, track_board_config
from github_fixtures import FakeForge, assert_github_world, serve_forge

from aco import workboard
from aco.body import ItemKind, Storage
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
    track_board_config(github_clone, 'idea_label = "idea"\n')
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


FOREIGN_CHILD = workboard.IssueReference("other/repo", 954)


def _foreign_figures(
    progress: ContainerProgress | None,
) -> tuple[int, int, tuple[int, ...], tuple[str, ...]]:
    assert progress is not None
    return (
        progress.closed,
        progress.total,
        tuple(child.number for child in progress.open_children),
        tuple(str(reference) for reference in progress.foreign_children),
    )


def test_an_open_child_in_another_repository_counts_but_is_never_listed_as_an_open_child() -> None:
    """Spec: BOARD-59, BOARD-60"""
    listed, children = container_with_children(
        CONTAINER,
        closed=1,
        open_children=(244,),
        foreign_open=(FOREIGN_CHILD,),
        body=complete_contract("Cut the next slice."),
    )
    open_child = board_issue(244, "Open child", complete_contract("Ship it."))

    projected = projected_board(
        (listed, open_child), (), (), (), BoardConfig(), now=NOW, children={CONTAINER: children}
    )
    container_item = next(item for item in projected.items if item.number == CONTAINER)
    child_item = next(item for item in projected.items if item.number == 244)

    assert (
        _foreign_figures(container_item.container),
        child_item.container_parent,
        [item.number for item in projected.items],
    ) == ((1, 3, (244,), ("other/repo#954",)), CONTAINER, [CONTAINER, 244])


def test_an_open_child_in_another_repository_keeps_its_container_from_closing() -> None:
    """Spec: BOARD-60"""
    listed, children = container_with_children(
        CONTAINER, closed=1, foreign_open=(FOREIGN_CHILD,), body=complete_contract("keiner")
    )

    projected = projected_board(
        (listed,), (), (), (), BoardConfig(), now=NOW, children={CONTAINER: children}
    )

    assert (
        workboard.zero_cost_closes(projected),
        isinstance(workboard.next_action(projected), CloseContainerAction),
    ) == ((), False)


@pytest.mark.parametrize(
    ("foreign_open", "offered"), [((FOREIGN_CHILD,), False), ((), True)], ids=["open", "none"]
)
def test_a_landed_container_is_offered_for_closing_only_while_no_foreign_child_is_open(
    foreign_open: tuple[workboard.IssueReference, ...], offered: bool
) -> None:
    """Spec: BOARD-60"""
    listed, children = container_with_children(
        CONTAINER, closed=1, foreign_open=foreign_open, body=complete_contract("keiner")
    )
    declaring_merge = workboard.PullRequest(
        1, "Lands it", f"Work-Item: #{CONTAINER}", "branch", "2026-08-20T00:00:00Z"
    )

    projected = projected_board(
        (listed,),
        (),
        (declaring_merge,),
        (),
        BoardConfig(),
        now=NOW,
        children={CONTAINER: children},
    )

    assert (
        CONTAINER in workboard.zero_cost_closes(projected),
        CONTAINER in [item.number for item in projected.recovery],
    ) == (offered, offered)


@pytest.mark.parametrize(
    ("foreign_state", "closable"),
    [(workboard.ChildState.OPEN, None), (workboard.ChildState.CLOSED, CONTAINER)],
    ids=["open", "closed"],
)
def test_a_container_is_named_closable_only_while_no_child_in_another_repository_is_open(
    foreign_state: workboard.ChildState, closable: int | None
) -> None:
    """Spec: BOARD-60"""
    parent = workboard.ParentIssue(
        workboard.IssueReference(REPOSITORY, CONTAINER),
        complete_contract("keiner"),
        ItemKind.CONTAINER,
    )
    children = (
        workboard.ChildItem(244, workboard.ChildState.CLOSED),
        workboard.ForeignChild(FOREIGN_CHILD, foreign_state),
    )

    assert workboard.closable_container_number(parent, children, Storage.GITHUB) == closable


def test_a_container_with_an_unreadable_and_a_foreign_open_child_names_both() -> None:
    """Spec: NEXT-38"""
    unreadable = workboard.ChildItem(244, workboard.ChildState.OPEN)
    foreign = workboard.IssueReference("other/repo", 954)
    progress = ContainerProgress(
        closed=1, total=3, open_children=(unreadable,), foreign_children=(foreign,)
    )

    reason = workboard._held_children_reason(
        progress, frozenset({unreadable.number}), Storage.GITHUB
    )

    assert reason == "container; its open children do not read: #244; waiting on other/repo#954"
