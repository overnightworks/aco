"""The decision board reads option lines beside yes/no lines and decides them
(specs/serve.spec.md: ABRD-07, ABRD-34, ABRD-35, ABRD-39..42, E-ABRD-11,
E-ABRD-12), driven through the real server, wire form and `aco` adapter
against a fake `aco` on PATH."""

from __future__ import annotations

from typing import Any, cast

import pytest
from aco_board_fixtures import (
    BoardClient,
    FakeAcoRepository,
    line,
    row,
    serving_two,
)

from aco.board.board import LINE_CHANGED

_SVG = '<svg xmlns="http://www.w3.org/2000/svg"/>'
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
    "fingerprint",
]
_RULE_13_SENTENCE = "line 1 is an option line; --yes, --no and --later rule only a yes/no line"
_RULE_17_SENTENCE = (
    "line 1 changed since its card was shown; show it again and rule what it shows now"
)
_RULE_18_SENTENCE = "line 1 has no option C; its options are A, B"
_RULE_04_SENTENCE = "line 1 is already ruled; a changed ruling is a new line"


def _picture_option(letter: str = "A", **changes: object) -> dict[str, object]:
    return {
        "letter": letter,
        "name": "Song stays open",
        "effect": "The app jumps itself.",
        "picture": _SVG,
        "caption": "Still open",
        "notice": "You stay in your song.",
        "cost": "More code.",
        "undo": "reversible",
        "undo_how": "Any time.",
        "contract": "The song stays open.",
        **changes,
    }


def _same_as_today_option(letter: str = "B", **changes: object) -> dict[str, object]:
    return {
        "letter": letter,
        "name": "As today",
        "effect": "The browser jumps.",
        "same_as_today": True,
        "notice": "You pick the song again.",
        "cost": "None.",
        "undo": "final",
        "undo_how": "Nothing is built.",
        "contract": "The link stays a link.",
        **changes,
    }


def option_line(*, ruling: object = None, **changes: object) -> dict[str, object]:
    """RUL-13's option line, E-RUL-07's card, open unless `ruling` is a letter."""
    card_hash = "sha256:b3f1720e7b5b083f5ae59eaf99559b438d1e729dc9034e3ea534cf5806f23b8a"
    return {
        "index": 1,
        "form": "options",
        "text": "The song stays open on the jump.",
        "ruling": ruling,
        "ruled_on": "2026-10-28" if ruling is not None else None,
        "default": None,
        "card_hash": card_hash,
        "stored_card_hash": card_hash if ruling is not None else None,
        "question": "Keep the song open?",
        "problem": "The jump closes your song.",
        "picture": _SVG,
        "caption": "Today",
        "decision_kind": "product",
        "area": "Song page",
        "topic": "Jump",
        "recommended": "A",
        "reason": "Ends the loss.",
        "options": [_picture_option(), _same_as_today_option()],
        **changes,
    }


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


@pytest.mark.parametrize("ruling", [None, "A", "B"], ids=["open", "ruled-A", "ruled-B"])
def test_an_option_line_is_listed_with_its_card_in_the_wire_order(
    repository: FakeAcoRepository, board: BoardClient, ruling: str | None
) -> None:
    stored = option_line(ruling=ruling)
    repository.set_rulings(row(12, "Song jump", stored))

    [listed] = _listed_lines(board)

    assert list(listed) == _OPTION_LINE_KEYS
    assert isinstance(listed.pop("fingerprint"), str)
    assert listed == {key: stored[key] for key in listed}
    stored_options = cast(list[dict[str, object]], stored["options"])
    assert [list(option) for option in listed["options"]] == [
        list(option) for option in stored_options
    ]


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
        ({"provenance": "x"}, 12, False),
        ({"text": "Another wording."}, 12, False),
    ],
    ids=[
        "card-hash",
        "item",
        "index",
        "stored-card-hash",
        "default",
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
        option_line(options=[_picture_option("B"), _same_as_today_option("A")]),
        option_line(options=[_picture_option("A"), _same_as_today_option("C")]),
        option_line(options=[]),
        option_line(options=[_picture_option(letter) for letter in "ABCDE"]),
        option_line(options="none"),
        option_line(options=["A"]),
        option_line(options=[_picture_option(), _same_as_today_option(cost=5)]),
        option_line(options=[_picture_option(), _same_as_today_option(same_as_today=False)]),
        option_line(problem=5),
        option_line(picture=5),
        option_line(options=[_picture_option(picture=5), _same_as_today_option()]),
        option_line(ruling="A", ruled_on="tomorrow"),
        option_line(form="cards"),
        option_line(form=None),
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
    ],
)
def test_a_malformed_option_line_makes_only_its_repository_unreadable(
    two_repositories: tuple[FakeAcoRepository, FakeAcoRepository], malformed: dict[str, object]
) -> None:
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


def _card_hash_of(stored: dict[str, object]) -> str:
    return cast(str, stored["card_hash"])


def test_an_option_on_an_open_option_line_is_ruled_through_acos_option_write(
    repository: FakeAcoRepository, board: BoardClient
) -> None:
    """ABRD-39, E-ABRD-12."""
    stored = option_line()
    repository.set_rulings(row(12, "Song jump", stored))
    [listed] = _listed_lines(board)

    answer = board.decide_option_through_api(listed, 12, "A")

    assert answer.status == 200
    assert answer.json() == {"status": "ruled", "message": None}
    assert repository.calls() == [
        ["rulings", "--json"],
        ["rulings", "--json"],
        [
            "rule",
            "12",
            "--line",
            "1",
            "--option",
            "A",
            "--via",
            "board",
            f"--card-hash={_card_hash_of(stored)}",
            "--json",
        ],
    ]
    [ruled] = _listed_lines(board)
    assert ruled["ruling"] == "A"


@pytest.mark.parametrize("note", [None, "  "], ids=["null-note", "blank-note"])
def test_an_option_post_without_a_real_note_is_accepted(
    repository: FakeAcoRepository, board: BoardClient, note: str | None
) -> None:
    """ABRD-39, ABRD-42."""
    repository.set_rulings(row(12, "Song jump", option_line()))
    [listed] = _listed_lines(board)

    answer = board.post_rule(
        {
            "repo": board.repo,
            "item": 12,
            "line": 1,
            "fingerprint": listed["fingerprint"],
            "option": "B",
            "note": note,
        }
    )

    assert answer.json() == {"status": "ruled", "message": None}


def test_an_option_post_after_the_card_changed_is_refused_without_a_write(
    repository: FakeAcoRepository, board: BoardClient
) -> None:
    """ABRD-41."""
    repository.set_rulings(row(12, "Song jump", option_line()))
    [listed] = _listed_lines(board)
    repository.set_rulings(row(12, "Song jump", option_line(card_hash="sha256:other")))

    answer = board.decide_option_through_api(listed, 12, "A")

    assert answer.json() == {"status": "failed", "message": LINE_CHANGED}
    assert repository.rule_calls() == []


def test_an_option_post_acos_write_refuses_as_changed_is_refused_as_changed(
    repository: FakeAcoRepository, board: BoardClient
) -> None:
    """ABRD-41."""
    repository.set_rulings(row(12, "Song jump", option_line()))
    repository.refuse_rule("card_changed", _RULE_17_SENTENCE)
    before = repository.rulings_state()
    [listed] = _listed_lines(board)

    answer = board.decide_option_through_api(listed, 12, "A")

    assert answer.json() == {"status": "failed", "message": LINE_CHANGED}
    assert repository.rulings_state() == before


@pytest.mark.parametrize(
    ("rows", "item", "index"),
    [
        (
            [row(42, "Share page", line(1, "Guests?", default="yes"))],
            42,
            1,
        ),
        (
            [row(12, "Song jump", option_line())],
            12,
            2,
        ),
    ],
    ids=["yes-no-line", "no-such-line"],
)
def test_an_option_post_for_a_line_that_is_no_option_line_is_refused_without_a_write(
    repository: FakeAcoRepository,
    board: BoardClient,
    rows: list[dict[str, object]],
    item: int,
    index: int,
) -> None:
    """ABRD-40."""
    repository.set_rulings(*rows)
    [listed] = _listed_lines(board)

    answer = board.post_rule(
        {
            "repo": board.repo,
            "item": item,
            "line": index,
            "fingerprint": listed["fingerprint"],
            "option": "A",
        }
    )

    assert answer.json() == {"status": "failed", "message": LINE_CHANGED}
    assert repository.rule_calls() == []


def test_an_option_post_on_a_ruled_option_line_answers_already_ruled_with_its_card_hash(
    repository: FakeAcoRepository, board: BoardClient
) -> None:
    """ABRD-41."""
    stored = option_line(ruling="A")
    repository.set_rulings(row(12, "Song jump", stored))
    repository.refuse_rule("already_ruled", _RULE_04_SENTENCE)
    [listed] = _listed_lines(board)

    answer = board.decide_option_through_api(listed, 12, "B")

    assert answer.json() == {"status": "already_ruled", "message": _RULE_04_SENTENCE}
    [rule_call] = repository.rule_calls()
    assert f"--card-hash={_card_hash_of(stored)}" in rule_call


def test_a_letter_not_on_the_card_answers_acos_refusal_as_a_failure(
    repository: FakeAcoRepository, board: BoardClient
) -> None:
    """ABRD-41."""
    repository.set_rulings(row(12, "Song jump", option_line()))
    repository.refuse_rule("invalid_usage", _RULE_18_SENTENCE)
    before = repository.rulings_state()
    [listed] = _listed_lines(board)

    answer = board.decide_option_through_api(listed, 12, "C")

    assert answer.json() == {"status": "failed", "message": f"aco rule failed: {_RULE_18_SENTENCE}"}
    assert repository.rulings_state() == before


def test_an_option_lines_fingerprint_never_satisfies_another_repos_option_check(
    two_repositories: tuple[FakeAcoRepository, FakeAcoRepository],
) -> None:
    """ABRD-39."""
    repository_a, repository_b = two_repositories
    for repository in two_repositories:
        repository.set_rulings(row(12, "Song jump", option_line()))

    with serving_two(two_repositories) as board:
        [listed_in_a] = [
            entry
            for repo in cast(list[dict[str, Any]], board.get_board_json().json()["repos"])
            if repo["name"] == "a"
            for item in repo["items"]
            for entry in item["lines"]
        ]
        answer = board.decide_option_through_api(listed_in_a, 12, "A", repo="b")

    assert answer.json() == {"status": "failed", "message": LINE_CHANGED}
    assert repository_a.rule_calls() == []
    assert repository_b.rule_calls() == []


@pytest.mark.parametrize(
    "decision",
    [
        {"outcome": "yes", "option": "A"},
        {},
        {"outcome": None, "option": None},
        {"outcome": None, "option": "A"},
        {"outcome": "yes", "option": None},
        {"option": "a"},
        {"option": "E"},
        {"option": ""},
        {"option": 1},
        {"option": ["A"]},
        {"option": "A", "note": "x"},
        {"option": "A", "note": 5},
    ],
    ids=[
        "both",
        "neither",
        "both-null",
        "outcome-null-with-option",
        "option-null-with-outcome",
        "lowercase-letter",
        "letter-past-the-options",
        "empty-letter",
        "number",
        "list",
        "note",
        "note-not-text",
    ],
)
def test_a_malformed_option_post_is_refused_before_any_aco_call(
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
