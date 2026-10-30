"""The board's aco source over the real aco and the file-backed forge
(specs/serve.spec.md): what one read lists (ABRD-06, ABRD-07, ABRD-60), and
what one decision reads and writes (ABRD-02, ABRD-41, ABRD-78)."""

from __future__ import annotations

import http.client
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
_READ = ForgeRequest(ForgeOperation.READ_ITEM, _ITEM)
_WRITE = ForgeRequest(ForgeOperation.WRITE_BODY, _ITEM)


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


def _withdrawn(repository: BoardForge) -> None:
    """ABRD-60: the posted line became a real tombstone (BODY-104)."""
    repository.put_item(_ITEM, item_body(_WITHDRAWN))


@pytest.mark.parametrize(
    "change",
    [_removed, _made_malformed, _closed, _withdrawn],
    ids=["removed", "malformed", "closed", "withdrawn"],
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
    assert repository.item_requests() == (_READ,)


def test_a_decision_reads_its_item_once_and_writes_it_once(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-78: no listing, one read of the item, one write of its body."""
    repository.put_item(_ITEM, item_body(open_option_entry()))
    shown = first_listed_line(board)
    page_read = repository.requests

    answered = board.decide_card_through_api(_ITEM, [shown], ["A"])

    assert answered.json() == {"status": "ruled", "message": None}
    assert repository.request_log()[page_read:] == (_READ, _WRITE)


def test_a_listing_that_fails_after_the_page_read_does_not_fail_a_decision(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-02: a decision reads its own item, never the listing."""
    repository.put_item(_ITEM, item_body(open_option_entry()))
    shown = first_listed_line(board)
    repository.fail_listing("the listing is down")

    answered = board.decide_card_through_api(_ITEM, [shown], ["A"])

    assert answered.json() == {"status": "ruled", "message": None}
    assert repository.body_writes() == [_ITEM]


def test_an_item_read_that_fails_during_a_decision_is_relayed_and_nothing_written(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-41, E-ABRD-06: the read's own sentence, with no prefix."""
    repository.put_item(_ITEM, item_body(open_option_entry()))
    shown = first_listed_line(board)
    repository.fail_item_reads("the item read is down")

    answered = board.decide_card_through_api(_ITEM, [shown], ["A"])

    assert answered.json() == {"status": "failed", "message": "the item read is down"}
    assert repository.item_requests() == (_READ,)


def test_an_unexpected_error_inside_the_write_fails_the_request_and_frees_the_turn(
    repository: BoardForge, board: BoardClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """ABRD-03: the request fails loudly, the board answers the next one, and
    the next decision is stored."""
    repository.put_item(_ITEM, item_body(open_option_entry()))
    shown = first_listed_line(board)
    repository.break_next_write("the write broke")

    with pytest.raises(http.client.RemoteDisconnected):
        board.decide_card_through_api(_ITEM, [shown], ["A"])

    assert "RuntimeError: the write broke" in capsys.readouterr().err
    answered = board.decide_card_through_api(_ITEM, [first_listed_line(board)], ["A"])
    assert answered.json() == {"status": "ruled", "message": None}
    assert repository.stored_entries(_ITEM)[0]["ruling"] == "A"
