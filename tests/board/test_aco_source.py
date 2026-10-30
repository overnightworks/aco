"""The board's aco source over the real aco and the file-backed forge
(specs/serve.spec.md): what one read lists (ABRD-06, ABRD-07, ABRD-60) and
what a decision on a card changed since the page read does to the item
(ABRD-02, ABRD-41)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest
from aco_board_fixtures import BoardClient, Lister, first_listed_line, serving_two
from board_forge import BoardForge, ForgeOperation, ForgeRequest, item_body
from option_cards import open_option_entry

from aco.board.board import LINE_CHANGED

_ITEM = 12
_OTHER_ITEM = 42
_WITHDRAWN = {"text": "Taken back.", "withdrawn_on": date(2026, 10, 2)}
_MALFORMED = item_body({**_WITHDRAWN, "unknown": True})
"""A withdrawn line with a key BODY-105 refuses: the whole item is malformed."""


def test_a_withdrawn_line_is_not_listed_and_its_neighbours_keep_their_indexes(
    repository: BoardForge, board: BoardClient, listed_items: Lister
) -> None:
    """ABRD-60: a real tombstone (BODY-104) between two open option lines."""
    entries = (open_option_entry("First."), _WITHDRAWN, open_option_entry("Third."))
    repository.put_item(_ITEM, item_body(*entries))

    [item] = listed_items(board)

    assert [(line["index"], line["text"]) for line in item["lines"]] == [
        (1, "First."),
        (3, "Third."),
    ]


def test_an_item_of_only_withdrawn_lines_is_not_listed(
    repository: BoardForge, board: BoardClient, listed_items: Lister
) -> None:
    """ABRD-60."""
    repository.put_item(_ITEM, item_body(_WITHDRAWN))
    repository.put_item(_OTHER_ITEM, item_body(open_option_entry()))

    assert [item["number"] for item in listed_items(board)] == [_OTHER_ITEM]


def test_a_malformed_item_is_not_listed_and_its_repository_stays_readable(
    repository: BoardForge, board: BoardClient, listed_items: Lister
) -> None:
    """ABRD-07, RUL-20."""
    repository.put_item(_ITEM, _MALFORMED)
    repository.put_item(_OTHER_ITEM, item_body(open_option_entry()))

    assert [item["number"] for item in listed_items(board)] == [_OTHER_ITEM]


def test_one_page_load_lists_each_repository_once(
    two_repositories: tuple[BoardForge, BoardForge],
) -> None:
    """ABRD-06: one listing per configured repository, and no item read."""
    for repository in two_repositories:
        repository.put_item(_ITEM, item_body(open_option_entry()))

    with serving_two(two_repositories) as board:
        board.get_board_json()

    assert [repository.request_log() for repository in two_repositories] == [
        (ForgeRequest(ForgeOperation.LIST_OPEN_ISSUES),)
    ] * 2


def _removed(repository: BoardForge) -> None:
    repository.remove_item(_ITEM)


def _made_malformed(repository: BoardForge) -> None:
    repository.put_item(_ITEM, _MALFORMED)


def _closed(repository: BoardForge) -> None:
    repository.close_item(_ITEM)


@pytest.mark.parametrize(
    "change", [_removed, _made_malformed, _closed], ids=["removed", "malformed", "closed"]
)
def test_a_card_whose_item_changed_since_the_page_read_is_refused_and_nothing_written(
    repository: BoardForge, board: BoardClient, change: Callable[[BoardForge], None]
) -> None:
    """ABRD-02, ABRD-41."""
    repository.put_item(_ITEM, item_body(open_option_entry()))
    shown = first_listed_line(board)
    change(repository)

    answered = board.decide_card_through_api(_ITEM, [shown], ["A"])

    assert answered.json() == {"status": "failed", "message": LINE_CHANGED}
    assert repository.body_writes() == []
