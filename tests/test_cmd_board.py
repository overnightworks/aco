"""`aco board --json` projects a container's sub-issues from other repositories."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest
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


@pytest.mark.parametrize(
    ("foreign_state", "expected_closed", "expected_foreign_children"),
    [
        pytest.param(workboard.ChildState.OPEN, 1, [str(FOREIGN_CHILD)], id="open"),
        pytest.param(workboard.ChildState.CLOSED, 2, [], id="closed"),
    ],
)
def test_board_json_counts_a_child_in_another_repository_and_names_it_only_while_open(
    foreign_state: workboard.ChildState,
    expected_closed: int,
    expected_foreign_children: list[str],
) -> None:
    """Spec: BOARD-59"""
    listed, children = container_with_children(
        CONTAINER, closed=1, open_children=(LOCAL_CHILD,), body=complete_contract("Cut it.")
    )
    container = replace(listed, children_closed=expected_closed, children_total=3)
    open_child = board_issue(LOCAL_CHILD, "Open child", complete_contract("Ship it."))
    projected = projected_board(
        (container, open_child),
        (),
        (),
        (),
        BoardConfig(),
        now=datetime(2026, 8, 21, tzinfo=UTC),
        children={CONTAINER: (*children, workboard.ForeignChild(FOREIGN_CHILD, foreign_state))},
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
    ) == (expected_closed, 3, [LOCAL_CHILD], expected_foreign_children)
