"""A waiting item is never ready (`specs/next.spec.md`): the wait the block carries, today's date."""

from datetime import date

import pytest
from board_fixtures import board_issue, complete_contract, projected_board

from aco import workboard
from aco.workboard import BoardConfig

NUMBER = 301
STEP = "Rotate the deploy key."


def _item(wait: dict[str, object] | None, today: date, labels: tuple[str, ...] = ()):
    entries: dict[str, object] = {"scope": ["src/widget.py"]}
    if wait is not None:
        entries["wait"] = wait
    issue = board_issue(NUMBER, "Held", complete_contract("Claim it.", **entries), labels=labels)
    board = projected_board((issue,), (), (), (), BoardConfig(), today=today)
    return board, board.items[0]


@pytest.mark.parametrize(
    ("wait", "labels", "reason"),
    [
        pytest.param(
            {"operator": STEP, "since": date(2026, 11, 1)},
            (),
            f"waiting: {STEP}",
            id="operator-wait-without-the-label",
        ),
        pytest.param(
            {"trigger": "A second machine exists.", "since": date(2026, 11, 1)},
            (),
            "waiting: A second machine exists.",
            id="trigger",
        ),
        pytest.param(
            {"until": date(2026, 12, 1), "since": date(2026, 11, 1)},
            (),
            "waiting: until 2026-12-01",
            id="until-in-the-future",
        ),
        pytest.param(
            {"operator": STEP, "since": date(2026, 11, 1)},
            (workboard.NEEDS_OPERATOR_LABEL,),
            f"waiting: {STEP}",
            id="operator-wait-beside-the-label",
        ),
    ],
)
def test_a_waiting_item_is_never_ready_and_never_named_first(
    wait: dict[str, object], labels: tuple[str, ...], reason: str
) -> None:
    board, item = _item(wait, date(2026, 11, 15), labels)

    assert item.actionable_reason == reason
    assert item.wait == reason.removeprefix("waiting: ")
    assert item not in board.ready_now
    assert workboard.highest_scored_actionable(board) is None


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
