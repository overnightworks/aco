"""The decision board reads option lines beside ruled yes/no lines (specs/serve.spec.md:
ABRD-34, ABRD-35, ABRD-53, ABRD-56), driven through the real server, wire form and `aco`
adapter against the real `aco` over a fake forge."""

from __future__ import annotations

from datetime import date

import pytest
from aco_board_fixtures import BoardClient, Lister, rulings_lines
from board_forge import BoardForge, item_body
from option_cards import open_option_entry

_RULED_ON = date(2026, 10, 28)
_YES_NO = {"text": "Guests?", "ruling": "yes", "ruled_on": date(2026, 10, 1)}


def _ruled(ruling: str, via: str, **answer: str) -> dict[str, object]:
    return {**open_option_entry(), "ruling": ruling, "ruled_on": _RULED_ON, "via": via, **answer}


@pytest.mark.parametrize(
    "stored",
    [
        open_option_entry(),
        _ruled("A", "board"),
        _ruled("B", "board"),
        _ruled("other", "chat", other="Nur am Desktop.\n„Zitat“ \\ Ende"),
    ],
    ids=["open", "ruled-A", "ruled-B", "ruled-other"],
)
def test_an_option_line_is_listed_as_acos_rulings_renders_it_with_its_fingerprint_last(
    repository: BoardForge, board: BoardClient, stored: dict[str, object], listed_items: Lister
) -> None:
    """ABRD-34, ABRD-56: `aco rulings --json`'s line, `other` verbatim, in its key order."""
    repository.put_item(12, item_body(stored), title="Song jump")

    [listed] = listed_items(board)[0]["lines"]

    [rendered] = rulings_lines(repository, 12)
    keys = list(listed)
    assert isinstance(listed.pop("fingerprint"), str)
    assert keys == [*rendered, "fingerprint"]
    assert listed == rendered
    assert [list(option) for option in listed["options"]] == [
        list(option) for option in rendered["options"]
    ]


@pytest.mark.parametrize("via", ["board", "chat", "default"])
def test_an_option_line_lists_via_as_acos_rulings_names_it(
    repository: BoardForge, board: BoardClient, via: str, listed_items: Lister
) -> None:
    """ABRD-53, line 18: `default` stays distinguishable from `board` and `chat`."""
    repository.put_item(12, item_body(_ruled("A", via)), title="Song jump")

    [listed] = listed_items(board)[0]["lines"]

    assert listed["via"] == via


def test_an_option_line_stands_beside_a_ruled_yes_no_line_in_acos_order(
    repository: BoardForge, board: BoardClient, listed_items: Lister
) -> None:
    repository.put_item(12, item_body(open_option_entry()), title="Song jump")
    repository.put_item(42, item_body(_YES_NO), title="Share page")

    listed = [entry for item in listed_items(board) for entry in item["lines"]]

    assert [(entry["text"], "form" in entry) for entry in listed] == [
        (open_option_entry()["text"], True),
        ("Guests?", False),
    ]


def _fingerprint_of(
    board: BoardClient,
    listed_items: Lister,
    repository: BoardForge,
    lines: tuple[dict[str, object], ...],
    number: int = 12,
) -> str:
    repository.put_item(number, item_body(*lines), title="Song jump")
    [item] = [item for item in listed_items(board) if item["number"] == number]
    return str(item["lines"][-1]["fingerprint"])


@pytest.mark.parametrize(
    ("lines", "number", "changes_fingerprint"),
    [
        (({**open_option_entry(), "question": "Soll dein Lied offen bleiben?"},), 12, True),
        ((open_option_entry(),), 13, True),
        ((_YES_NO, open_option_entry()), 12, True),
        ((_ruled("A", "board"),), 12, False),
        ((_ruled("A", "chat"),), 12, False),
    ],
    ids=["card-edit", "item", "index", "ruled", "via"],
)
def test_an_option_lines_fingerprint_follows_item_index_and_card_hash_only(
    repository: BoardForge,
    board: BoardClient,
    lines: tuple[dict[str, object], ...],
    number: int,
    changes_fingerprint: bool,
    listed_items: Lister,
) -> None:
    """ABRD-35: `via` is no part of the fingerprint."""
    before = _fingerprint_of(board, listed_items, repository, (open_option_entry(),))

    after = _fingerprint_of(board, listed_items, repository, lines, number)

    assert (after != before) is changes_fingerprint
