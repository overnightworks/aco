"""The pure fold that puts one asked card on an item body (`specs/mcp.spec.md`)."""

from datetime import date

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from option_cards import ask_card, card, open_option_entry

from aco import body, expectations

ASKED_ON = date(2026, 11, 8)


def item_with(*lines: str) -> str:
    return block_body(MINIMAL_BLOCK_TOML + "\n".join(lines))


def entries_of(raw: str) -> list[dict[str, object]]:
    return body.block_expectation_dicts(body.locate_block(raw).data)


def test_asking_appends_one_line_dated_by_the_caller_and_keeps_the_others() -> None:
    before = item_with(card())

    after = expectations.ask_line(before, ask_card(), ASKED_ON)

    kept, asked = entries_of(after)
    assert kept == entries_of(before)[0]
    assert asked == {**open_option_entry(), "asked_on": ASKED_ON}


def test_the_asked_body_is_rendered_canonically() -> None:
    after = expectations.ask_line(item_with(card()), ask_card(), ASKED_ON)
    located = body.locate_block(after)

    assert body.replace_block(after, located, located.data) == after


def test_the_fold_leaves_the_prose_around_the_block_alone() -> None:
    before = item_with(card())

    after = expectations.ask_line(before, ask_card(), ASKED_ON)

    outside = [
        (raw[: located.content_start], raw[located.content_end :])
        for raw, located in ((before, body.locate_block(before)), (after, body.locate_block(after)))
    ]
    assert outside[1] == outside[0]


@pytest.mark.parametrize(
    ("changes", "sentence"),
    [
        pytest.param({"text": ["a", "b"]}, "must be a non-empty string", id="text-a-list"),
        pytest.param({"question": 7}, "must be a non-empty string", id="question-an-integer"),
        pytest.param({"options": "A"}, "must be an array of tables", id="options-a-string"),
        pytest.param({"options": [3, 4]}, "must be a table", id="options-integers"),
    ],
)
def test_a_value_of_the_wrong_type_refuses_with_the_grammars_sentence(
    changes: dict[str, object], sentence: str
) -> None:
    before = item_with(card())
    asked = ask_card(**changes)

    with pytest.raises(expectations.ExpectationCardDefectError, match=sentence):
        expectations.ask_line(before, asked, ASKED_ON)


def test_a_same_as_today_that_is_not_true_refuses() -> None:
    options = open_option_entry()["option"]
    assert isinstance(options, list)
    wrong = [{**options[0], "same_as_today": "yes"}, options[1]]
    asked = ask_card(options=wrong)

    with pytest.raises(expectations.ExpectationCardDefectError, match="must be true"):
        expectations.ask_line(item_with(card()), asked, ASKED_ON)
