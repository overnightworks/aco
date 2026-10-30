"""A stored card answers with the item as it was written (ABRD-09, ABRD-71): the
same item `GET /api/board` lists next, fingerprints included; a refusal carries
no item."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from aco_board_fixtures import BoardClient, Lister
from board_forge import BoardForge, item_body
from option_cards import group_body, open_option_entry

from aco.board.api import decision_result_json
from aco.board.board import LINE_CHANGED
from aco.board.ports import DecisionResult, DecisionStatus
from aco.expectations import WithdrawnLine

_ITEM = 7
_TITLE = "Share page"


def _listed_item(board: BoardClient, listed_items: Lister) -> dict[str, Any]:
    [item] = [item for item in listed_items(board) if item["number"] == _ITEM]
    return item


@pytest.mark.parametrize(
    ("raw_body", "options", "answer", "status"),
    [
        (item_body(open_option_entry()), ["A"], None, "ruled"),
        (group_body(), ["A", "B"], None, "ruled"),
        (group_body(), None, {"other": 'a "quoted"\nanswer'}, "ruled"),
        (group_body(), None, {"unclear": True, "note": "Was kostet B?"}, "returned"),
    ],
    ids=["one-point", "card-of-points", "other-with-quotes-and-newline", "unclear-with-note"],
)
def test_a_stored_card_answers_with_the_item_the_next_listing_shows(
    repository: BoardForge,
    board: BoardClient,
    listed_items: Lister,
    raw_body: str,
    options: list[str] | None,
    answer: dict[str, object] | None,
    status: str,
) -> None:
    """ABRD-09, ABRD-71."""
    repository.put_item(_ITEM, raw_body, title=_TITLE)
    open_lines = [
        line for line in _listed_item(board, listed_items)["lines"] if "fingerprint" in line
    ]

    answered = board.decide_card_through_api(_ITEM, open_lines, options, answer)

    assert answered.json() == {
        "status": status,
        "message": None,
        "item": _listed_item(board, listed_items),
    }


def test_a_card_changed_since_the_page_read_answers_without_an_item(
    repository: BoardForge, board: BoardClient, listed_items: Lister
) -> None:
    """ABRD-09, E-ABRD-04."""
    repository.put_item(_ITEM, item_body(open_option_entry()), title=_TITLE)
    [shown] = _listed_item(board, listed_items)["lines"]
    repository.put_item(_ITEM, group_body(), title=_TITLE)

    answered = board.decide_card_through_api(_ITEM, [shown], ["A"])

    assert answered.json() == {"status": "failed", "message": LINE_CHANGED}


def test_a_failed_item_read_answers_without_an_item(
    repository: BoardForge, board: BoardClient, listed_items: Lister
) -> None:
    """ABRD-09."""
    repository.put_item(_ITEM, item_body(open_option_entry()), title=_TITLE)
    [shown] = _listed_item(board, listed_items)["lines"]
    repository.fail_item_reads("the item read is down")

    answered = board.decide_card_through_api(_ITEM, [shown], ["A"])

    assert answered.json() == {"status": "failed", "message": "the item read is down"}


def test_a_stored_item_of_only_withdrawn_lines_is_not_answered_without_an_item() -> None:
    withdrawn = WithdrawnLine(index=0, text="Taken back.", withdrawn_on=date(2026, 10, 2))
    stored = DecisionResult(
        DecisionStatus.RULED, item=SimpleNamespace(number=_ITEM, title=_TITLE, lines=(withdrawn,))
    )

    with pytest.raises(ValueError, match="lists no line"):
        decision_result_json(stored, "repo")
