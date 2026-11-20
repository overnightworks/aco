"""The parent hint `release --merged` and `item close` share (NEXT-07)."""

from board_fixtures import REPOSITORY, complete_contract
from github_fixtures import WORK_ITEM_ISSUE, FakeForge

from aco import board_read, body, workboard

PHASE = 79
TOP_EPIC = 1


def test_a_grandchilds_landing_names_its_phase_and_never_the_top_epic() -> None:
    """NEXT-07: the phase lost its last open child; the epic above it still has the phase open."""
    contract = complete_contract("keiner")
    client = FakeForge(
        parents={
            WORK_ITEM_ISSUE: workboard.ParentIssue(
                workboard.IssueReference(REPOSITORY, PHASE), contract, body.ItemKind.CONTAINER
            ),
            PHASE: workboard.ParentIssue(
                workboard.IssueReference(REPOSITORY, TOP_EPIC), contract, body.ItemKind.CONTAINER
            ),
        },
        children={
            PHASE: (workboard.ChildItem(WORK_ITEM_ISSUE, workboard.ChildState.CLOSED, "Child"),),
            TOP_EPIC: (workboard.ChildItem(PHASE, workboard.ChildState.OPEN, "Phase"),),
        },
        closed_issues={WORK_ITEM_ISSUE},
    )

    named = board_read.parent_closable_number(client, WORK_ITEM_ISSUE, body.Storage.GITHUB)

    assert (named, TOP_EPIC in client.closed_issues) == (PHASE, False)
