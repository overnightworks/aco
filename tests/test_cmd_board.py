"""`aco board --json` projects a container's sub-issues from other repositories."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from board_fixtures import (
    board_issue,
    complete_contract,
    container_with_children,
    projected_board,
)

from aco import cmd_board, workboard
from aco.workboard import BoardConfig

CONTAINER = 120
LOCAL_CHILD = 121
FOREIGN_CHILD = workboard.IssueReference("overnightworks/other-repo", 954)


def test_board_json_names_an_open_child_in_another_repository_apart_from_open_children() -> None:
    """Spec: BOARD-59"""
    container, children = container_with_children(
        CONTAINER,
        closed=1,
        open_children=(LOCAL_CHILD,),
        foreign_open=(FOREIGN_CHILD,),
        body=complete_contract("Cut the next slice."),
    )
    open_child = board_issue(LOCAL_CHILD, "Open child", complete_contract("Ship it."))
    projected = projected_board(
        (container, open_child),
        (),
        (),
        (),
        BoardConfig(),
        now=datetime(2026, 8, 21, tzinfo=UTC),
        children={CONTAINER: children},
    )

    payload = cmd_board.board_payload(projected)

    items = cast("list[dict[str, object]]", payload["items"])
    shown = cast(
        "dict[str, object]", next(i for i in items if i["number"] == CONTAINER)["container"]
    )
    open_children = cast("list[dict[str, object]]", shown["open_children"])
    assert (
        shown["closed"],
        shown["total"],
        [child["number"] for child in open_children],
        shown["foreign_children"],
    ) == (1, 3, [LOCAL_CHILD], [str(FOREIGN_CHILD)])


def test_board_json_counts_a_closed_child_in_another_repository_apart_from_both_open_lists() -> None:
    """Spec: BOARD-59"""
    listed, children = container_with_children(
        CONTAINER, closed=1, open_children=(LOCAL_CHILD,), body=complete_contract("Cut it.")
    )
    container = replace(listed, children_closed=2, children_total=3)
    closed_foreign = workboard.ForeignChild(FOREIGN_CHILD, workboard.ChildState.CLOSED)
    open_child = board_issue(LOCAL_CHILD, "Open child", complete_contract("Ship it."))
    projected = projected_board(
        (container, open_child),
        (),
        (),
        (),
        BoardConfig(),
        now=datetime(2026, 8, 21, tzinfo=UTC),
        children={CONTAINER: (*children, closed_foreign)},
    )

    payload = cmd_board.board_payload(projected)

    items = cast("list[dict[str, object]]", payload["items"])
    shown = cast(
        "dict[str, object]", next(i for i in items if i["number"] == CONTAINER)["container"]
    )
    open_children = cast("list[dict[str, object]]", shown["open_children"])
    assert (
        shown["closed"],
        shown["total"],
        [child["number"] for child in open_children],
        shown["foreign_children"],
    ) == (2, 3, [LOCAL_CHILD], [])
