"""A container with an open or returned option line, or an operator `wait`, is never
closable (NEXT-73, LAND-92), and ruling the line makes it closable again."""

import pytest
from board_fixtures import complete_contract, ruled_expectation
from option_cards import open_option_entry, returned_option_entry

from aco import workboard
from aco.body import BodyReadState, ItemKind, Storage, parse_body

CHILDREN = (workboard.ChildItem(80, workboard.ChildState.CLOSED, "Child"),)
PARENT = workboard.IssueReference("owner/repo", 5)

HELD_AND_CLOSABLE = [
    pytest.param(
        [open_option_entry()], workboard.ParentCompletion.HELD, None, id="an-open-option-line"
    ),
    pytest.param(
        [returned_option_entry()],
        workboard.ParentCompletion.HELD,
        None,
        id="a-returned-option-line",
    ),
    pytest.param(
        [ruled_expectation("Alt")], workboard.ParentCompletion.REQUIRED, 5, id="a-ruled-line"
    ),
    pytest.param(
        [ruled_expectation("Alt"), open_option_entry()],
        workboard.ParentCompletion.HELD,
        None,
        id="a-ruled-line-beside-an-open-one",
    ),
]


@pytest.mark.parametrize(("lines", "completion", "closable"), HELD_AND_CLOSABLE)
def test_an_option_line_decides_whether_a_parent_is_closable(
    lines: list[dict[str, object]],
    completion: workboard.ParentCompletion,
    closable: int | None,
) -> None:
    """Spec: NEXT-73, NEXT-74, LAND-92, LAND-93"""
    raw = complete_contract("keiner", expectation=lines)
    parsed = parse_body(raw, storage=Storage.GITHUB)
    parent = workboard.ParentIssue(PARENT, raw, ItemKind.CONTAINER)

    assert parsed.read_state is BodyReadState.VALID
    assert (
        workboard.parent_completion(parsed),
        workboard.closable_container_number(parent, CHILDREN, Storage.GITHUB),
    ) == (completion, closable)
