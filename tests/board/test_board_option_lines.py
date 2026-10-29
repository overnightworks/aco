"""The decision board reads option lines beside ruled yes/no lines (specs/serve.spec.md:
ABRD-34, ABRD-35, ABRD-53, ABRD-56, E-ABRD-03), driven through the real server, wire form
and `aco` adapter against the real `aco` over a fake forge."""

from __future__ import annotations

from datetime import date
from typing import cast

import pytest
from aco_board_fixtures import BoardClient, Lister
from board_forge import BoardForge, item_body
from option_cards import open_option_entry

_OPTION_LINE_KEYS = [
    "index",
    "form",
    "text",
    "question",
    "problem",
    "picture",
    "caption",
    "decision_kind",
    "area",
    "topic",
    "recommended",
    "reason",
    "options",
    "ruling",
    "ruled_on",
    "via",
    "other",
    "returned_on",
    "returned_note",
    "fingerprint",
]
_CARD_KEYS = (
    "text",
    "question",
    "problem",
    "picture",
    "caption",
    "decision_kind",
    "area",
    "topic",
    "recommended",
    "reason",
)
_RULED_ON = date(2026, 10, 28)
_YES_NO = {"text": "Guests?", "ruling": "yes", "ruled_on": date(2026, 10, 1)}


def _ruled(ruling: str, via: str, **answer: str) -> dict[str, object]:
    return {**open_option_entry(), "ruling": ruling, "ruled_on": _RULED_ON, "via": via, **answer}


def _wire_options(entry: dict[str, object]) -> list[dict[str, object]]:
    """`entry`'s options as the board lists them: each lettered by its position."""
    options = cast(list[dict[str, object]], entry["option"])
    return [{"letter": letter, **option} for letter, option in zip("ABCD", options, strict=False)]


def _wire(entry: dict[str, object]) -> dict[str, object]:
    """`entry` as the board lists it as line 1, without its fingerprint."""
    ruled_on = entry.get("ruled_on")
    return {
        "index": 1,
        "form": "options",
        **{key: entry[key] for key in _CARD_KEYS},
        "options": _wire_options(entry),
        "ruling": entry.get("ruling"),
        "ruled_on": ruled_on.isoformat() if isinstance(ruled_on, date) else None,
        "via": entry.get("via"),
        "other": entry.get("other"),
        "returned_on": None,
        "returned_note": None,
    }


def test_a_ruled_yes_no_line_is_listed_in_these_bytes_without_a_default(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-34, E-ABRD-03."""
    guests = {**_YES_NO, "question": "Gäste?", "example": "Ja", "picture": "<svg/>"}
    hosts = {"text": "Hosts?", "ruling": "no", "ruled_on": date(2026, 10, 1)}
    repository.put_item(42, item_body(guests, hosts), title="Share page")

    response = board.get_board_json()

    assert response.body == (
        '{"repos": [{"name": "repo", "error": null, "items": [{"number": 42,'
        ' "title": "Share page", "lines": ['
        '{"index": 1, "text": "Guests?", "question": "G\\u00e4ste?", "example": "Ja",'
        ' "picture": "<svg/>", "ruling": "yes", "ruled_on": "2026-10-01",'
        ' "fingerprint": "9d1396572d67571a0688f719f1d30db85f2cd5d6a89399945fda04b9cf259a93"},'
        ' {"index": 2, "text": "Hosts?", "question": null, "example": null,'
        ' "picture": null, "ruling": "no", "ruled_on": "2026-10-01",'
        ' "fingerprint": "98be3926ecb0b8cf749b8a5a2450def8c02fae835eb262499c6c3b34590d1448"}]}]}]}'
    )


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
def test_an_option_line_is_listed_with_its_card_in_the_wire_order(
    repository: BoardForge, board: BoardClient, stored: dict[str, object], listed_items: Lister
) -> None:
    """ABRD-56: `other` follows `via`, verbatim."""
    repository.put_item(12, item_body(stored), title="Song jump")

    [listed] = listed_items(board)[0]["lines"]

    assert list(listed) == _OPTION_LINE_KEYS
    assert isinstance(listed.pop("fingerprint"), str)
    assert listed == _wire(stored)
    assert [list(option) for option in listed["options"]] == [
        list(option) for option in _wire_options(stored)
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
