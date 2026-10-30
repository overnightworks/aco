"""The board's JSON API deciding option cards through the real server, wire form and
`aco` adapter against the real `aco` over a fake forge (specs/serve.spec.md): reading
fresh on every listing, keeping no copy of a decision, the repos a card is written to,
and what a forge that cannot list does to a card post."""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest
from aco_board_fixtures import (
    BoardClient,
    Lister,
    RecordedPort,
    first_listed_line,
    serving_two,
)
from board_forge import BoardForge, ForgeOperation, ForgeRequest, item_body
from option_cards import open_option_entry

from aco.board.board import LINE_CHANGED

_ITEM = 42
_OPEN_CARD = item_body(open_option_entry())
_YES_NO = {"text": "Guests?", "ruling": "yes", "ruled_on": date(2026, 10, 1)}
_READ = ForgeRequest(ForgeOperation.READ_ITEM, _ITEM)
_WRITE = ForgeRequest(ForgeOperation.WRITE_BODY, _ITEM)


def _ruled_a() -> dict[str, object]:
    return {**open_option_entry(), "ruling": "A", "ruled_on": date(2026, 10, 28), "via": "board"}


@pytest.mark.parametrize(
    ("items", "listed"),
    [
        ((), []),
        (
            (
                (42, "Share page", item_body(open_option_entry(), _ruled_a())),
                (7, "Login", _OPEN_CARD),
            ),
            [(42, "Share page", [(1, None), (2, "A")]), (7, "Login", [(1, None)])],
        ),
    ],
    ids=["nothing", "open-and-ruled-in-acos-order"],
)
def test_the_board_lists_every_option_line_under_its_item_in_acos_order(
    repository: BoardForge,
    board: BoardClient,
    port: RecordedPort,
    items: tuple[tuple[int, str, str], ...],
    listed: list[tuple[int, str, list[tuple[int, str | None]]]],
    listed_items: Lister,
) -> None:
    for number, title, raw_body in items:
        repository.put_item(number, raw_body, title=title)

    shown = listed_items(board)

    assert [
        (
            item["number"],
            item["title"],
            [(entry["index"], entry["ruling"]) for entry in item["lines"]],
        )
        for item in shown
    ] == listed
    assert port.ruled_items() == []
    assert repository.body_writes() == []


def test_the_board_reads_fresh_on_every_listing(
    repository: BoardForge, board: BoardClient, listed_items: Lister
) -> None:
    repository.put_item(1, _OPEN_CARD, title="Removed between loads")
    first = listed_items(board)
    repository.remove_item(1)
    repository.put_item(2, item_body(_YES_NO, open_option_entry()), title="Added between loads")

    second = listed_items(board)

    assert [
        [(item["number"], [entry["index"] for entry in item["lines"]]) for item in listing]
        for listing in (first, second)
    ] == [[(1, [1])], [(2, [1, 2])]]


def test_the_board_keeps_no_copy_of_a_decision(
    repository: BoardForge, board: BoardClient, listed_items: Lister
) -> None:
    repository.put_item(_ITEM, _OPEN_CARD, title="Share page")
    board.decide_card_through_api(_ITEM, [first_listed_line(board)], ["A"])

    repository.put_item(_ITEM, _OPEN_CARD, title="Share page")

    assert [(item["number"], item["lines"][0]["ruling"]) for item in listed_items(board)] == [
        (_ITEM, None)
    ]


def test_a_forge_that_cannot_read_the_item_during_a_card_post_keeps_the_line_undecided(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-79."""
    repository.put_item(_ITEM, _OPEN_CARD, title="Share page")
    shown = first_listed_line(board)
    repository.fail_item_reads("no forge adapter for host")

    answer = board.decide_card_through_api(_ITEM, [shown], ["A"])

    assert answer.json() == {"status": "failed", "message": "no forge adapter for host"}
    assert repository.item_requests() == (_READ,)


@pytest.mark.parametrize(
    ("target_repo", "expected_status", "expected_message", "requests"),
    [("a", "ruled", None, ((_READ, _WRITE), ())), ("b", "failed", LINE_CHANGED, ((), (_READ,)))],
    ids=["its-own-repo", "a-different-repo-with-an-identical-card"],
)
def test_a_card_only_writes_the_repo_its_fingerprint_was_read_from(
    two_repositories: tuple[BoardForge, BoardForge],
    target_repo: str,
    expected_status: str,
    expected_message: str | None,
    requests: tuple[tuple[ForgeRequest, ...], tuple[ForgeRequest, ...]],
) -> None:
    """ABRD-16/21: a card decided against its own repo writes there; posted
    against another configured repo instead -- even one holding an identical
    card -- it is refused like a changed line on that repo's one read, no
    write in either repo."""
    for repository in two_repositories:
        repository.put_item(_ITEM, _OPEN_CARD, title="Share page")

    with serving_two(two_repositories) as board:
        [listed_repo_a, _] = cast(list[dict[str, Any]], board.get_board_json().json()["repos"])
        listed_in_a = listed_repo_a["items"][0]["lines"][0]

        answer = board.decide_card_through_api(_ITEM, [listed_in_a], ["A"], repo=target_repo)

    assert answer.json() == {"status": expected_status, "message": expected_message}
    assert tuple(repository.item_requests() for repository in two_repositories) == requests
