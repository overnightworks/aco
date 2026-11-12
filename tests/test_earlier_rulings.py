"""The earlier rulings of a card's area (`specs/mcp.spec.md`, MCP-57..MCP-64), free
of any search: the query a card's area becomes, and the lines kept from what the
forge found."""

from collections.abc import Callable
from datetime import date

import pytest
from board_forge import item_body
from option_cards import open_option_entry

from aco import earlier_rulings, forge

AREA = "Song-Seite"
TRACKED = ("owner/a", "owner/b")
ASKED = earlier_rulings.LineKey("owner/a", 1, 1)


def _ruled_entry(**changes: object) -> dict[str, object]:
    ruled = {"ruling": "A", "ruled_on": date(2026, 10, 28), "via": "board"}
    return {**open_option_entry(), **ruled, **changes}


def _item(
    repository: str,
    number: int,
    *entries: dict[str, object],
    member: bool = True,
    title: str = "Titel",
) -> forge.RulingItem:
    return forge.RulingItem(repository, number, title, item_body(*entries), member)


def _recall(
    *items: forge.RulingItem, area: str = AREA, complete: bool = True
) -> earlier_rulings.Recall:
    result = forge.RulingSearchResult(items, complete)
    return earlier_rulings.recall(result, area=area, tracked=TRACKED, asked=ASKED)


def _shown(recall: earlier_rulings.Recall) -> list[tuple[str, int, int]]:
    return [(line.repository, line.item, line.index) for line in recall.lines]


@pytest.mark.parametrize(
    ("area", "owners", "query"),
    [
        pytest.param(
            "Song-Seite", ("owner",), '"area song seite" in:body is:issue user:owner', id="hyphen"
        ),
        pytest.param(
            'Say "hi" (x)', ("owner",), '"area say hi x" in:body is:issue user:owner', id="quotes"
        ),
        pytest.param(
            "Backup OR Sicherung NOT x",
            ("owner",),
            '"area backup or sicherung not x" in:body is:issue user:owner',
            id="operators",
        ),
        pytest.param(
            "Größe & Übung",
            ("owner",),
            '"area größe übung" in:body is:issue user:owner',
            id="umlauts",
        ),
        pytest.param(
            "[Beta] v2.1 _x",
            ("owner",),
            '"area beta v2 1 x" in:body is:issue user:owner',
            id="brackets-digits-underscore",
        ),
        pytest.param(
            "Song-Seite",
            ("b-org", "a-org", "b-org"),
            '"area song seite" in:body is:issue user:a-org user:b-org',
            id="one-qualifier-per-owner",
        ),
    ],
)
def test_the_query_is_one_phrase_of_the_areas_words_limited_to_issue_bodies_of_the_owners(
    area: str, owners: tuple[str, ...], query: str
) -> None:
    assert earlier_rulings.search_query(area, owners) == query


@pytest.mark.parametrize(
    ("area", "owners"),
    [
        pytest.param("", ("owner",), id="empty"),
        pytest.param("--- «»", ("owner",), id="no-letter-or-digit"),
        pytest.param("x" * 300, ("owner",), id="over-the-length-limit"),
        pytest.param(AREA, (), id="no-owner"),
    ],
)
def test_an_area_the_forge_cannot_search_is_unavailable(area: str, owners: tuple[str, ...]) -> None:
    with pytest.raises(earlier_rulings.RecallUnavailableError):
        earlier_rulings.search_query(area, owners)


def test_the_owners_come_from_the_labels_that_pass_the_repository_name_pattern() -> None:
    labels = ("b-org/x", "a-org/y", "a-org/z", "no-slash", "-lead/x", "a/b/c")

    assert earlier_rulings.owners_of(labels) == ("a-org", "b-org")


def test_a_ruled_line_of_the_same_area_is_kept_with_its_question_answer_day_and_way() -> None:
    entry = _ruled_entry(ruled_on=date(2026, 10, 29), via="chat")
    recall = _recall(_item("owner/b", 4, entry, title="Der Song"))

    [line] = recall.lines
    assert (line.repository, line.item, line.title, line.index) == ("owner/b", 4, "Der Song", 1)
    assert (line.question, line.answer) == (entry["question"], "Song bleibt offen")
    assert (line.ruled_on, line.via) == (date(2026, 10, 29), "chat")


def test_the_operators_own_words_are_the_answer_of_a_line_ruled_other() -> None:
    entry = _ruled_entry(ruling="other", other="Lieber Kopie", via="chat")

    [line] = _recall(_item("owner/b", 4, entry)).lines

    assert line.answer == "Lieber Kopie"


@pytest.mark.parametrize(
    "line",
    [
        pytest.param(_ruled_entry(area="song-seite"), id="case-differs"),
        pytest.param(_ruled_entry(via="default"), id="ruled-by-default"),
    ],
)
def test_lines_whose_area_equals_the_cards_without_case_are_kept(line: dict[str, object]) -> None:
    assert _shown(_recall(_item("owner/b", 4, line))) == [("owner/b", 4, 1)]


@pytest.mark.parametrize(
    "left_out",
    [
        pytest.param(lambda: _item("owner/b", 5, open_option_entry()), id="open-line"),
        pytest.param(lambda: _item("owner/b", 5, _ruled_entry(area="Song Seite")), id="word-form"),
        pytest.param(lambda: _item("owner/b", 5, _ruled_entry(area="Andere")), id="other-area"),
        pytest.param(lambda: _item("owner/b", 5, _ruled_entry(), member=False), id="non-member"),
        pytest.param(lambda: _item("owner/x", 5, _ruled_entry()), id="untracked-repository"),
        pytest.param(
            lambda: _item("owner/b", 5, {"text": "Weg", "withdrawn_on": date(2026, 10, 2)}),
            id="withdrawn",
        ),
        pytest.param(lambda: _item("owner/a", 1, _ruled_entry()), id="the-asked-line-itself"),
    ],
)
def test_a_line_that_is_open_withdrawn_of_another_area_or_not_a_members_is_left_out(
    left_out: Callable[[], forge.RulingItem],
) -> None:
    kept = _item("owner/b", 4, _ruled_entry())

    assert _shown(_recall(left_out(), kept)) == [("owner/b", 4, 1)]


def test_another_ruled_line_of_the_asked_item_is_kept() -> None:
    asked_item = _item("owner/a", 1, _ruled_entry(), _ruled_entry())

    assert _shown(_recall(asked_item)) == [("owner/a", 1, 2)]


def test_an_item_found_twice_counts_once() -> None:
    twice = _item("owner/b", 4, _ruled_entry())

    assert _shown(_recall(twice, twice)) == [("owner/b", 4, 1)]


def test_lines_come_newest_day_first_then_by_repository_item_descending_and_line_index() -> None:
    newest = _ruled_entry(ruled_on=date(2026, 11, 1))
    older = _ruled_entry(ruled_on=date(2026, 10, 1))
    items = (
        _item("owner/b", 9, older),
        _item("owner/a", 3, older, older),
        _item("owner/a", 7, older),
        _item("owner/b", 2, newest),
    )

    assert _shown(_recall(*items)) == [
        ("owner/b", 2, 1),
        ("owner/a", 7, 1),
        ("owner/a", 3, 1),
        ("owner/a", 3, 2),
        ("owner/b", 9, 1),
    ]


@pytest.mark.parametrize(("lines", "more"), [(5, 0), (7, 2)])
def test_at_most_five_lines_are_kept_and_the_rest_is_counted(lines: int, more: int) -> None:
    items = [_item("owner/b", number, _ruled_entry()) for number in range(1, lines + 1)]

    recall = _recall(*items)

    assert (len(recall.lines), recall.more) == (5, more)


def test_the_lines_of_an_area_without_a_ruling_are_none() -> None:
    recall = _recall(_item("owner/b", 4, _ruled_entry(area="Andere")))

    assert (recall.lines, recall.more) == ((), 0)


def test_a_result_the_forge_marks_incomplete_is_unavailable() -> None:
    with pytest.raises(earlier_rulings.RecallUnavailableError):
        _recall(_item("owner/b", 4, _ruled_entry()), complete=False)


def test_the_recall_is_answered_as_the_keys_earlier_and_earlier_more() -> None:
    entry = _ruled_entry(ruled_on=date(2026, 10, 29), via="chat")
    recall = _recall(_item("owner/b", 4, entry, title="Der Song"))

    assert earlier_rulings.earlier_json(recall) == {
        "earlier": [
            {
                "repository": "owner/b",
                "item": 4,
                "title": "Der Song",
                "question": entry["question"],
                "answer": "Song bleibt offen",
                "ruled_on": "2026-10-29",
                "via": "chat",
            }
        ],
        "earlier_more": 0,
    }
