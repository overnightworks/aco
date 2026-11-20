"""A waiting item is never ready (`specs/next.spec.md`), by its `wait` and today's date."""

from collections.abc import Mapping
from datetime import date

import pytest
from board_fixtures import (
    block_dependency,
    board_issue,
    complete_contract,
    projected_board,
    request,
    slice_entries,
    store_claim_from_request,
)

from aco import workboard
from aco.body import ItemKind
from aco.workboard import BoardConfig

NUMBER = 301
STEP = "Rotate the deploy key."


def _item(
    wait: Mapping[str, object] | None,
    today: date,
    labels: tuple[str, ...] = (),
    claimed: bool = False,
):
    scope = ["src/widget.py"]
    contract = (
        complete_contract("Claim it.", scope=scope)
        if wait is None
        else complete_contract("Claim it.", scope=scope, wait=wait)
    )
    issue = board_issue(NUMBER, "Held", contract, labels=labels)
    claims = (store_claim_from_request(request(issue=NUMBER)),) if claimed else ()
    board = projected_board((issue,), (), (), claims, BoardConfig(), today=today)
    return board, board.items[0]


@pytest.mark.parametrize(
    ("wait", "reason"),
    [
        pytest.param(
            {"trigger": "A second machine exists.", "since": date(2026, 11, 1)},
            "waiting: A second machine exists.",
            id="trigger",
        ),
        pytest.param(
            {"until": date(2026, 12, 1), "since": date(2026, 11, 1)},
            "waiting: until 2026-12-01",
            id="until-in-the-future",
        ),
    ],
)
def test_a_waiting_item_is_never_ready_and_never_named_first(
    wait: Mapping[str, object], reason: str
) -> None:
    board, item = _item(wait, date(2026, 11, 15))

    assert item.actionable_reason == reason
    assert item.wait == reason.removeprefix("waiting: ")
    assert item not in board.ready_now
    assert workboard.highest_scored_actionable(board) is None


def test_an_operator_wait_without_the_label_waits_on_the_operator() -> None:
    board, item = _item({"operator": STEP, "since": date(2026, 11, 1)}, date(2026, 11, 15))

    assert item.waits_on_operator
    assert item.actionable_reason == workboard.WAITING_ON_OPERATOR
    assert item not in board.ready_now


def test_a_claimed_item_with_an_operator_wait_names_the_step_as_its_waiting_reason() -> None:
    _, item = _item(
        {"operator": STEP, "since": date(2026, 11, 1)}, date(2026, 11, 15), claimed=True
    )

    assert not item.waits_on_operator
    assert item.actionable_reason == f"waiting: {STEP}"


def test_the_label_without_an_operator_wait_holds_nothing() -> None:
    board, item = _item(None, date(2026, 11, 15), (workboard.NEEDS_OPERATOR_LABEL,))

    assert not item.waits_on_operator
    assert item.actionable_reason is None
    assert item in board.ready_now


WAITS_WITH_REASON = [
    pytest.param(
        {"trigger": "A second machine exists."},
        "waiting: A second machine exists.",
        id="trigger",
    ),
    pytest.param({"until": date(2026, 12, 1)}, "waiting: until 2026-12-01", id="until"),
]


def _waiting_container_board(
    wait: Mapping[str, object], rows: list[dict[str, object]]
) -> workboard.Board:
    contract = complete_contract("Cut it.", slice=rows, wait={**wait, "since": date(2026, 11, 1)})
    issue = workboard.Issue(
        NUMBER,
        "Held epic",
        (),
        contract,
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=ItemKind.CONTAINER,
        children_closed=1,
        children_total=1,
    )
    return projected_board((issue,), (), (), (), BoardConfig(), today=date(2026, 11, 15))


@pytest.mark.parametrize(("wait", "reason"), WAITS_WITH_REASON)
def test_a_container_with_a_wait_and_an_uncut_row_is_never_cut(
    wait: Mapping[str, object], reason: str
) -> None:
    board = _waiting_container_board(wait, slice_entries("Scheibe A"))
    item = board.items[0]

    assert workboard.next_action(board) is None
    assert item.actionable_reason == reason
    assert not item.waits_on_operator


def test_a_container_with_an_open_blocker_and_an_uncut_row_is_never_cut() -> None:
    """NEXT-69."""
    contract = complete_contract("Cut it.", slice=slice_entries("Scheibe A"))
    issue = workboard.Issue(
        NUMBER,
        "Blocked epic",
        (),
        contract,
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=ItemKind.CONTAINER,
        children_closed=1,
        children_total=1,
        blocked_by_count=1,
    )
    board = projected_board(
        (issue,),
        (),
        (),
        (),
        BoardConfig(),
        today=date(2026, 11, 15),
        dependencies={NUMBER: (block_dependency(9),)},
    )

    assert workboard.next_action(board) is None
    assert board.items[0].actionable_reason == "blocked by #9"


@pytest.mark.parametrize(("wait", "reason"), WAITS_WITH_REASON)
def test_a_container_with_a_wait_and_no_uncut_row_is_closed_never_named_first(
    wait: Mapping[str, object], reason: str
) -> None:
    """NEXT-59."""
    board = _waiting_container_board(wait, [])
    item = board.items[0]

    assert workboard.next_action(board) is None
    assert workboard.zero_cost_closes(board) == (NUMBER,)
    assert item.actionable_reason == reason


def test_a_container_with_an_operator_wait_and_no_uncut_row_is_closed_never_named_first() -> None:
    """NEXT-39."""
    board = _waiting_container_board({"operator": STEP}, [])

    assert workboard.next_action(board) is None
    assert workboard.zero_cost_closes(board) == (NUMBER,)


@pytest.mark.parametrize(
    "today",
    [
        pytest.param(date(2026, 12, 1), id="on-the-day"),
        pytest.param(date(2027, 3, 1), id="after"),
    ],
)
def test_an_until_wait_frees_the_item_once_the_injected_today_reaches_the_date(
    today: date,
) -> None:
    wait = {"until": date(2026, 12, 1), "since": date(2026, 11, 1)}

    board, item = _item(wait, today)

    assert item.actionable_reason is None
    assert item.wait is None
    assert workboard.highest_scored_actionable(board) is item
