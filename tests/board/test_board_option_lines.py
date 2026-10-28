"""The decision board reads option lines beside yes/no lines and decides them
(specs/serve.spec.md: ABRD-07, ABRD-34, ABRD-35, ABRD-41, ABRD-42, ABRD-53, ABRD-56,
E-ABRD-11), driven through the real server, wire form and `aco` adapter against a fake `aco`
on PATH."""

from __future__ import annotations

from typing import Any, cast

import pytest
from aco_board_fixtures import (
    BoardClient,
    FakeAcoRepository,
    line,
    option_line,
    picture_option,
    row,
    same_as_today_option,
    serving_two,
)

from aco.board.board import LINE_CHANGED

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
_RULE_13_SENTENCE = "line 1 is an option line; --yes, --no and --later rule only a yes/no line"
_RULE_17_SENTENCE = (
    "line 1 changed since its card was shown; show it again and rule what it shows now"
)
_RULE_18_SENTENCE = "line 1 has no option C; its options are A, B"
_RULE_04_SENTENCE = "line 1 is already ruled; a changed ruling is a new line"


def _without_key(stored: dict[str, object], key: str) -> dict[str, object]:
    return {name: value for name, value in stored.items() if name != key}


def _listed_lines(board: BoardClient) -> list[dict[str, Any]]:
    response = board.get_board_json()
    assert response.status == 200
    [repo] = cast(list[dict[str, Any]], response.json()["repos"])
    assert repo["error"] is None
    return [listed for item in repo["items"] for listed in item["lines"]]


def test_a_yes_no_line_is_listed_in_the_bytes_it_always_was(
    repository: FakeAcoRepository, board: BoardClient
) -> None:
    repository.set_rulings(
        row(
            42,
            "Share page",
            line(1, "Guests?", default="yes", question="Gäste?", example="Ja", picture="<svg/>"),
            line(2, "Hosts?", ruling="no"),
        )
    )

    response = board.get_board_json()

    assert response.body == (
        '{"repos": [{"name": "repo", "error": null, "items": [{"number": 42,'
        ' "title": "Share page", "lines": ['
        '{"index": 1, "text": "Guests?", "question": "G\\u00e4ste?", "example": "Ja",'
        ' "picture": "<svg/>", "default": "yes", "ruling": null, "ruled_on": null,'
        ' "fingerprint": "c669433f7b000568336634f65259156d38cbe612a358c9d061659917d9746574"},'
        ' {"index": 2, "text": "Hosts?", "question": null, "example": null,'
        ' "picture": null, "default": null, "ruling": "no", "ruled_on": "2026-10-01",'
        ' "fingerprint": "6e4658aa8d30aa67c1fcf4b005d2f97a730b9cbf53cc4bfc1f6d951cc867f252"}]}]}]}'
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
    repository: FakeAcoRepository, board: BoardClient, stored: dict[str, object]
) -> None:
    """ABRD-56: `other` follows `via`, verbatim."""
    repository.set_rulings(row(12, "Song jump", stored))

    [listed] = _listed_lines(board)

    assert list(listed) == _OPTION_LINE_KEYS
    assert isinstance(listed.pop("fingerprint"), str)
    assert listed == {key: stored[key] for key in listed}
    stored_options = cast(list[dict[str, object]], stored["options"])
    assert [list(option) for option in listed["options"]] == [
        list(option) for option in stored_options
    ]


@pytest.mark.parametrize("via", ["board", "chat", "default"])
def test_an_option_line_lists_via_as_acos_rulings_names_it(
    repository: FakeAcoRepository, board: BoardClient, via: str
) -> None:
    """ABRD-53, line 18: `default` stays distinguishable from `board` and `chat`."""
    repository.set_rulings(row(12, "Song jump", option_line(ruling="A", via=via)))

    [listed] = _listed_lines(board)

    assert listed["via"] == via


def test_an_option_line_stands_beside_a_yes_no_line_in_acos_order(
    repository: FakeAcoRepository, board: BoardClient
) -> None:
    repository.set_rulings(
        row(12, "Song jump", option_line()),
        row(42, "Share page", line(1, "Guests?", default="yes")),
    )

    listed = _listed_lines(board)

    assert [(entry["text"], "form" in entry) for entry in listed] == [
        ("The song stays open on the jump.", True),
        ("Guests?", False),
    ]


def test_an_unknown_key_and_a_default_on_an_option_line_do_not_matter(
    repository: FakeAcoRepository, board: BoardClient
) -> None:
    repository.set_rulings(row(12, "Song jump", option_line(default="yes", provenance="x")))

    [listed] = _listed_lines(board)

    assert list(listed) == _OPTION_LINE_KEYS


def _fingerprint_of(
    repository: FakeAcoRepository, board: BoardClient, stored: dict[str, object], number: int = 12
) -> str:
    repository.set_rulings(row(number, "Song jump", stored))
    [listed] = _listed_lines(board)
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
) -> None:
    """ABRD-35: `via` is no part of the fingerprint."""
    before = _fingerprint_of(repository, board, option_line())

    after = _fingerprint_of(repository, board, option_line(**changes), number)

    assert (after != before) is changes_fingerprint


def test_an_option_lines_fingerprint_never_satisfies_another_repos_check(
    two_repositories: tuple[FakeAcoRepository, FakeAcoRepository],
) -> None:
    repository_a, repository_b = two_repositories
    for repository in two_repositories:
        repository.set_rulings(row(12, "Song jump", option_line()))
    repository_a.refuse_rule("invalid_usage", _RULE_13_SENTENCE)
    repository_b.refuse_rule("invalid_usage", _RULE_13_SENTENCE)

    with serving_two(two_repositories) as board:
        [listed_in_a] = [
            entry
            for repo in cast(list[dict[str, Any]], board.get_board_json().json()["repos"])
            if repo["name"] == "a"
            for item in repo["items"]
            for entry in item["lines"]
        ]
        answer = board.decide_through_api(listed_in_a, 12, "yes", repo="b")

    assert answer.json() == {"status": "failed", "message": LINE_CHANGED}
    assert repository_b.rule_calls() == []


@pytest.mark.parametrize("ruling", [None, "A"], ids=["open", "ruled"])
def test_a_yes_no_decision_on_an_option_line_writes_nothing_and_says_why(
    repository: FakeAcoRepository, board: BoardClient, ruling: str | None
) -> None:
    repository.set_rulings(row(12, "Song jump", option_line(ruling=ruling)))
    repository.refuse_rule("invalid_usage", _RULE_13_SENTENCE)
    before = repository.rulings_state()
    [listed] = _listed_lines(board)

    answer = board.decide_through_api(listed, 12, "yes")

    assert answer.status == 200
    assert answer.json() == {"status": "failed", "message": f"aco rule failed: {_RULE_13_SENTENCE}"}
    assert repository.rulings_state() == before


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
    repository_a, repository_b = two_repositories
    repository_a.set_rulings(row(12, "Song jump", malformed))
    repository_b.set_rulings(row(42, "Share page", line(1, "Guests?", default="yes")))

    with serving_two(two_repositories) as board:
        response = board.get_board_json()

    repos = cast(list[dict[str, Any]], response.json()["repos"])
    assert response.status == 200
    assert repos[0]["error"].startswith("aco rulings --json is unreadable: ")
    assert repos[0]["items"] == []
    assert repos[1]["error"] is None
    assert [item["number"] for item in repos[1]["items"]] == [42]


@pytest.mark.parametrize(
    "decision",
    [
        {"outcome": "yes", "option": "A"},
        {},
        {"outcome": None, "option": None},
        {"outcome": None, "option": "A"},
        {"outcome": "yes", "option": None},
    ],
    ids=["both", "neither", "both-null", "outcome-null-with-option", "option-null-with-outcome"],
)
def test_a_post_without_lines_naming_no_outcome_or_one_beside_an_option_is_refused(
    repository: FakeAcoRepository, board: BoardClient, decision: dict[str, object]
) -> None:
    """ABRD-42."""
    repository.set_rulings(row(12, "Song jump", option_line()))
    [listed] = _listed_lines(board)
    calls_before = repository.calls()

    answer = board.post_rule(
        {
            "repo": board.repo,
            "item": 12,
            "line": 1,
            "fingerprint": listed["fingerprint"],
            **decision,
        }
    )

    assert answer.status == 400
    assert answer.json() == {"error": "bad request: decision"}
    assert repository.calls() == calls_before
