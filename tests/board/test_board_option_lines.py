"""The decision board reads option lines beside ruled yes/no lines (specs/serve.spec.md:
ABRD-07, ABRD-34, ABRD-35, ABRD-41, ABRD-53, ABRD-56, E-ABRD-11), driven through the real
server, wire form and `aco` adapter against a fake `aco` on PATH."""

from __future__ import annotations

from typing import Any, cast

import pytest
from aco_board_fixtures import (
    BoardClient,
    FakeAcoRepository,
    Lister,
    line,
    option_line,
    picture_option,
    row,
    same_as_today_option,
    serving_two,
)

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


def _without_key(stored: dict[str, object], key: str) -> dict[str, object]:
    return {name: value for name, value in stored.items() if name != key}


def test_a_ruled_yes_no_line_is_listed_in_these_bytes_without_a_default(
    repository: FakeAcoRepository, board: BoardClient
) -> None:
    """ABRD-34, E-ABRD-03."""
    repository.set_rulings(
        row(
            42,
            "Share page",
            line(1, "Guests?", ruling="yes", question="Gäste?", example="Ja", picture="<svg/>"),
            line(2, "Hosts?", ruling="no"),
        )
    )

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
        option_line(),
        option_line(ruling="A"),
        option_line(ruling="B"),
        option_line(ruling="other", via="chat", other="Nur am Desktop.\n„Zitat“ \\ Ende"),
    ],
    ids=["open", "ruled-A", "ruled-B", "ruled-other"],
)
def test_an_option_line_is_listed_with_its_card_in_the_wire_order(
    repository: FakeAcoRepository,
    board: BoardClient,
    stored: dict[str, object],
    listed_items: Lister,
) -> None:
    """ABRD-56: `other` follows `via`, verbatim."""
    repository.set_rulings(row(12, "Song jump", stored))

    [listed] = listed_items(board)[0]["lines"]

    assert list(listed) == _OPTION_LINE_KEYS
    assert isinstance(listed.pop("fingerprint"), str)
    assert listed == {key: stored[key] for key in listed}
    stored_options = cast(list[dict[str, object]], stored["options"])
    assert [list(option) for option in listed["options"]] == [
        list(option) for option in stored_options
    ]


@pytest.mark.parametrize("via", ["board", "chat", "default"])
def test_an_option_line_lists_via_as_acos_rulings_names_it(
    repository: FakeAcoRepository, board: BoardClient, via: str, listed_items: Lister
) -> None:
    """ABRD-53, line 18: `default` stays distinguishable from `board` and `chat`."""
    repository.set_rulings(row(12, "Song jump", option_line(ruling="A", via=via)))

    [listed] = listed_items(board)[0]["lines"]

    assert listed["via"] == via


def test_an_option_line_stands_beside_a_ruled_yes_no_line_in_acos_order(
    repository: FakeAcoRepository, board: BoardClient, listed_items: Lister
) -> None:
    repository.set_rulings(
        row(12, "Song jump", option_line()),
        row(42, "Share page", line(1, "Guests?", ruling="yes")),
    )

    listed = [entry for item in listed_items(board) for entry in item["lines"]]

    assert [(entry["text"], "form" in entry) for entry in listed] == [
        ("The song stays open on the jump.", True),
        ("Guests?", False),
    ]


def test_an_unknown_key_and_a_default_on_an_option_line_do_not_matter(
    repository: FakeAcoRepository, board: BoardClient, listed_items: Lister
) -> None:
    repository.set_rulings(row(12, "Song jump", option_line(default="yes", provenance="x")))

    [listed] = listed_items(board)[0]["lines"]

    assert list(listed) == _OPTION_LINE_KEYS


def _fingerprint_of(
    board: BoardClient,
    listed_items: Lister,
    repository: FakeAcoRepository,
    stored: dict[str, object],
    number: int = 12,
) -> str:
    repository.set_rulings(row(number, "Song jump", stored))
    [listed] = listed_items(board)[0]["lines"]
    return cast(str, listed["fingerprint"])


@pytest.mark.parametrize(
    ("changes", "number", "changes_fingerprint"),
    [
        ({"card_hash": "sha256:other"}, 12, True),
        ({}, 13, True),
        ({"index": 2}, 12, True),
        ({"stored_card_hash": "sha256:other"}, 12, False),
        ({"default": "yes"}, 12, False),
        ({"via": "chat"}, 12, False),
        ({"provenance": "x"}, 12, False),
        ({"text": "Another wording."}, 12, False),
    ],
    ids=[
        "card-hash",
        "item",
        "index",
        "stored-card-hash",
        "default",
        "via",
        "unknown-key",
        "text-not-in-the-hash",
    ],
)
def test_an_option_lines_fingerprint_follows_item_index_and_card_hash_only(
    repository: FakeAcoRepository,
    board: BoardClient,
    changes: dict[str, object],
    number: int,
    changes_fingerprint: bool,
    listed_items: Lister,
) -> None:
    """ABRD-35: `via` is no part of the fingerprint."""
    before = _fingerprint_of(board, listed_items, repository, option_line())

    after = _fingerprint_of(board, listed_items, repository, option_line(**changes), number)

    assert (after != before) is changes_fingerprint


@pytest.mark.parametrize(
    "malformed",
    [
        option_line(ruling="C"),
        option_line(ruling="yes"),
        option_line(ruling=7),
        option_line(recommended="C"),
        option_line(recommended="E"),
        option_line(recommended=None),
        option_line(options=[picture_option("B"), same_as_today_option("A")]),
        option_line(options=[picture_option("A"), same_as_today_option("C")]),
        option_line(options=[]),
        option_line(options=[picture_option(letter) for letter in "ABCDE"]),
        option_line(options="none"),
        option_line(options=["A"]),
        option_line(options=[picture_option(), same_as_today_option(cost=5)]),
        option_line(options=[picture_option(), same_as_today_option(same_as_today=False)]),
        option_line(problem=5),
        option_line(picture=5),
        option_line(options=[picture_option(picture=5), same_as_today_option()]),
        option_line(ruling="A", ruled_on="tomorrow"),
        option_line(form="cards"),
        option_line(form=None),
        _without_key(option_line(), "via"),
        option_line(ruling="A", via="phone"),
        option_line(ruling="A", via="Board"),
        option_line(ruling="A", via=5),
        option_line(ruling="other", via="chat"),
        option_line(ruling="other", via="chat", other="  "),
        option_line(ruling="other", via="chat", other=5),
        option_line(ruling="A", other="x"),
        option_line(other="x"),
    ],
    ids=[
        "ruling-not-a-letter-of-the-options",
        "yes-no-ruling",
        "ruling-not-text",
        "recommended-not-a-letter-of-the-options",
        "recommended-no-letter",
        "recommended-null",
        "letters-swapped",
        "letter-out-of-position",
        "no-options",
        "more-options-than-letters",
        "options-not-a-list",
        "option-not-an-object",
        "option-field-wrong-type",
        "option-neither-picture-nor-same-as-today",
        "line-field-wrong-type",
        "picture-wrong-type",
        "option-picture-wrong-type",
        "ruled-on-not-a-date",
        "unknown-form",
        "form-null",
        "via-missing",
        "via-unknown-value",
        "via-wrong-case",
        "via-not-text",
        "other-missing-on-a-line-ruled-other",
        "other-blank",
        "other-not-text",
        "other-beside-a-letter",
        "other-on-an-open-line",
    ],
)
def test_a_malformed_option_line_makes_only_its_repository_unreadable(
    two_repositories: tuple[FakeAcoRepository, FakeAcoRepository], malformed: dict[str, object]
) -> None:
    """ABRD-07, ABRD-53."""
    error_in_a = _error_in_a_beside_a_usable_b(two_repositories, malformed)

    assert error_in_a.startswith("aco rulings --json is unreadable: ")


def test_an_open_yes_no_line_makes_only_its_repository_unreadable_with_its_sentence(
    two_repositories: tuple[FakeAcoRepository, FakeAcoRepository],
) -> None:
    """ABRD-07, ABRD-15: no writer is left for it, and it is never skipped silently."""
    error_in_a = _error_in_a_beside_a_usable_b(two_repositories, line(3, "Guests?"))

    assert error_in_a == (
        "aco rulings --json is unreadable: #12 line 3 is an open yes/no line; write an option card"
    )


def _error_in_a_beside_a_usable_b(
    two_repositories: tuple[FakeAcoRepository, FakeAcoRepository], line_in_a: dict[str, object]
) -> str:
    """Repo `a`'s error with item 12 holding `line_in_a`, once `b` listed beside it."""
    repository_a, repository_b = two_repositories
    repository_a.set_rulings(row(12, "Song jump", line_in_a))
    repository_b.set_rulings(row(42, "Share page", option_line(index=1, text="Guests?")))

    with serving_two(two_repositories) as board:
        response = board.get_board_json()

    repos = cast(list[dict[str, Any]], response.json()["repos"])
    assert response.status == 200
    assert repos[0]["items"] == []
    assert repos[1]["error"] is None
    assert [item["number"] for item in repos[1]["items"]] == [42]
    return cast(str, repos[0]["error"])
