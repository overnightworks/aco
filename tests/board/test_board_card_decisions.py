"""The board decides a whole option card with one `aco rule` (ABRD-09, ABRD-39, ABRD-40,
ABRD-41, ABRD-64, ABRD-70, ABRD-77, ABRD-79 to ABRD-81): the post's shape, the refusals
before any port call, aco's own refusals relayed once for the card, and that the real
`aco rule` stores what the board sent in one body write."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

import pytest
from aco_board_fixtures import (
    BoardClient,
    Lister,
    RecordedPort,
    decision_port,
    serving_many,
)
from board_forge import BoardForge, item_body
from option_cards import SECOND_CARD, YES_NO_LINE, card, card_head, check_defects, group_body

from aco.board.board import LINE_CHANGED, SHUTTING_DOWN, Board, Boards
from aco.board.ports import PostedCard, PostedLine

_BAD_REQUEST = "bad request: decision"
_ITEM = 7
_ANSWER = "Nur auf dem Desktop offen lassen."
_ALREADY_RULED = "line 3 is already ruled; a changed ruling is a new line"
_WITH_HEAD = "line 2 is already with its head; it comes back once revised"
_YES_NO = tomllib.loads(YES_NO_LINE)["expectation"][0]
_CARDS = tuple(
    tomllib.loads(text)["expectation"][0]
    for text in (
        card(),
        SECOND_CARD,
        card(card_head(("Soll dein Song", "Soll dein Album"))),
        card(card_head(("Soll dein Song", "Soll dein Video"))),
    )
)
"""`group_body()`'s two option lines, then two more."""
_STORED_KEYS = ("ruling", "via", "other", "returned_note")
_Shown = dict[int, dict[str, Any]]
_Show = Callable[..., _Shown]
_Payload = dict[str, Any]


def _cards(*entries: dict[str, object]) -> str:
    """Issue #7: line 1 `group_body()`'s ruled yes/no line, then `entries`."""
    return item_body(_YES_NO, *entries)


def _ruled(entry: dict[str, object]) -> dict[str, object]:
    return {**entry, "ruling": "A", "ruled_on": date(2026, 10, 28), "via": "board"}


def _returned(entry: dict[str, object]) -> dict[str, object]:
    return {**entry, "returned_on": date(2026, 10, 1), "returned_note": "?"}


@pytest.fixture
def show(repository: BoardForge, board: BoardClient, listed_items: Lister) -> _Show:
    """Puts item 7 with `raw_body`, `group_body()` unless given; its lines as
    listed, by line index."""

    def listed(raw_body: str | None = None) -> _Shown:
        repository.put_item(_ITEM, group_body() if raw_body is None else raw_body)
        return {entry["index"]: entry for entry in listed_items(board)[0]["lines"]}

    return listed


def _stored(repository: BoardForge, indexes: tuple[int, ...]) -> list[tuple[object, ...]]:
    entries = repository.stored_entries(_ITEM)
    return [tuple(entries[index - 1].get(key) for key in _STORED_KEYS) for index in indexes]


def _assert_untouched(port: RecordedPort, repository: BoardForge) -> None:
    """No `rule_card` reached the port, and no item was read or written."""
    assert port.ruled_items() == []
    assert repository.item_requests() == ()


def _picked(*letters: str) -> list[tuple[object, ...]]:
    return [(letter, "board", None, None) for letter in letters]


def _other(answer: str) -> list[tuple[object, ...]]:
    return [("other", "board", answer, None)] * 2


def _sent_back(note: str | None) -> list[tuple[object, ...]]:
    return [(None, None, None, note)] * 2


@pytest.mark.parametrize(
    ("count", "options", "answer", "status", "stored"),
    [
        (2, ("A", "B"), {}, "ruled", _picked("A", "B")),
        (4, ("B", "A", "B", "A"), {}, "ruled", _picked("B", "A", "B", "A")),
        (4, ("A",) * 4, {}, "ruled", _picked(*"AAAA")),
        (1, ("B",), {}, "ruled", _picked("B")),
        (2, None, {"other": f"  {_ANSWER}\n"}, "ruled", _other(_ANSWER)),
        (
            2,
            None,
            {"other": " -n starts like an option "},
            "ruled",
            _other("-n starts like an option"),
        ),
        (2, None, {"other": 'a\n"b" ä'}, "ruled", _other('a\n"b" ä')),
        (2, None, {"other": f" {'x' * 280} "}, "ruled", _other("x" * 280)),
        (2, None, {"unclear": True}, "returned", _sent_back(None)),
        (
            2,
            None,
            {"unclear": True, "note": " Was kostet B? "},
            "returned",
            _sent_back("Was kostet B?"),
        ),
        (2, None, {"unclear": True, "note": "  \n"}, "returned", _sent_back(None)),
        (2, None, {"unclear": True, "note": "a\nb"}, "returned", _sent_back("a\nb")),
    ],
    ids=[
        "picks",
        "four-picks",
        "accept-all",
        "one-line-card",
        "other",
        "other-like-an-option-flag",
        "other-with-a-newline-and-quote",
        "other-at-the-bound",
        "unclear",
        "unclear-note",
        "unclear-blank-note",
        "unclear-note-with-a-newline",
    ],
)
def test_a_card_post_stores_every_line_in_one_body_write(
    repository: BoardForge,
    board: BoardClient,
    count: int,
    options: tuple[str, ...] | None,
    answer: dict[str, object],
    status: str,
    stored: list[tuple[object, ...]],
    show: _Show,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ABRD-39, ABRD-64, ABRD-70, ABRD-77, RULE-29: a stored ruling also proves
    aco took the card hash the board sent, and the stored body passes `aco check`."""
    shown = show(_cards(*_CARDS[:count]))
    indexes = tuple(range(2, 2 + count))

    answered = board.decide_card_through_api(
        _ITEM, [shown[index] for index in indexes], options, answer
    )

    assert answered.json() == {"status": status, "message": None}
    assert _stored(repository, indexes) == stored
    assert repository.body_writes() == [_ITEM]
    monkeypatch.chdir(repository.directory)
    assert check_defects(capsys, repository.stored_body(_ITEM)) == (0, [])


@pytest.mark.parametrize(
    ("options", "answer", "stored"),
    [(["A", "B"], {}, ("A", "B")), (None, {"other": _ANSWER}, ("other", "other"))],
    ids=["picks", "other"],
)
def test_a_card_with_a_line_held_by_its_head_is_stored_without_the_return(
    repository: BoardForge,
    board: BoardClient,
    options: list[str] | None,
    answer: dict[str, object],
    stored: tuple[str, str],
    show: _Show,
) -> None:
    """ABRD-77, RULE-25."""
    shown = show(_cards(_returned(_CARDS[0]), _CARDS[1]))

    board.decide_card_through_api(_ITEM, [shown[2], shown[3]], options, answer)

    entries = repository.stored_entries(_ITEM)[1:]
    assert [(entry["ruling"], entry["via"], entry.get("returned_on")) for entry in entries] == [
        (ruling, "board", None) for ruling in stored
    ]


def _added_after_reading(repository: BoardForge) -> None:
    repository.put_item(_ITEM, _cards(*_CARDS[:3]))


def _rehashed_after_reading(repository: BoardForge) -> None:
    repository.put_item(_ITEM, _cards(_CARDS[0], _CARDS[2]))


@pytest.mark.parametrize(
    ("count", "later", "posted"),
    [
        (3, None, (2, 3)),
        (2, _added_after_reading, (2, 3)),
        (2, _rehashed_after_reading, (2, 3)),
        (2, None, (2, 3, 9)),
        (2, None, (1, 2, 3)),
    ],
    ids=["point-missing", "point-added", "card-changed", "line-not-listed", "yes-no-line"],
)
def test_a_card_post_missing_a_point_or_naming_a_changed_line_runs_no_aco_rule(
    repository: BoardForge,
    board: BoardClient,
    port: RecordedPort,
    count: int,
    later: Callable[[BoardForge], None] | None,
    posted: tuple[int, ...],
    show: _Show,
) -> None:
    """ABRD-79."""
    listed = show(_cards(*_CARDS[:count]))
    listed[9] = {**listed[2], "index": 9}
    if later is not None:
        later(repository)
    options = ["A"] * len(posted)

    answered = board.decide_card_through_api(_ITEM, [listed[index] for index in posted], options)

    assert answered.json() == {"status": "failed", "message": LINE_CHANGED}
    _assert_untouched(port, repository)


def test_a_card_post_names_a_line_ruled_meanwhile_and_aco_refuses_the_whole_card(
    repository: BoardForge, board: BoardClient, show: _Show
) -> None:
    """ABRD-80, RULE-04."""
    listed = show()
    repository.put_item(_ITEM, _cards(_CARDS[0], _ruled(_CARDS[1])))
    before = repository.stored_body(_ITEM)

    answered = board.decide_card_through_api(_ITEM, [listed[2], listed[3]], ["A", "B"])

    assert answered.json() == {"status": "already_ruled", "message": _ALREADY_RULED}
    assert repository.stored_body(_ITEM) == before
    assert repository.body_writes() == []


def _edited_before_acos_read(repository: BoardForge) -> None:
    repository.edit_before_next_read(_ITEM, _cards(_CARDS[0], _CARDS[2]))


@pytest.mark.parametrize(
    ("arrange", "letters", "message"),
    [
        (_edited_before_acos_read, ["A", "B"], LINE_CHANGED),
        (
            None,
            ["A", "C"],
            "aco rule failed: line 3 has no option C; its options are A, B",
        ),
    ],
    ids=["card-changed-at-the-write", "letter-not-on-the-card"],
)
def test_aco_refusing_the_card_write_is_relayed_once_and_stores_nothing(
    repository: BoardForge,
    board: BoardClient,
    arrange: Callable[[BoardForge], None] | None,
    letters: list[str],
    message: str,
    show: _Show,
) -> None:
    """ABRD-41, ABRD-80, RULE-17, RULE-18."""
    listed = show()
    if arrange is not None:
        arrange(repository)

    answered = board.decide_card_through_api(_ITEM, [listed[2], listed[3]], letters)

    assert answered.json() == {"status": "failed", "message": message}
    assert repository.body_writes() == []


def test_an_unclear_card_with_a_line_already_with_its_head_is_failed_with_acos_sentence(
    repository: BoardForge, board: BoardClient, show: _Show
) -> None:
    """ABRD-80, RULE-24."""
    listed = show()
    repository.put_item(_ITEM, _cards(_returned(_CARDS[0]), _CARDS[1]))
    before = repository.stored_body(_ITEM)

    answered = board.decide_card_through_api(_ITEM, [listed[2], listed[3]], None, {"unclear": True})

    assert answered.json() == {"status": "failed", "message": f"aco rule failed: {_WITH_HEAD}"}
    assert repository.stored_body(_ITEM) == before
    assert repository.body_writes() == []


def test_a_card_post_when_aco_cannot_be_read_is_failed_without_an_aco_rule(
    repository: BoardForge, board: BoardClient, port: RecordedPort, show: _Show
) -> None:
    """ABRD-79."""
    listed = show()
    repository.fail_listing("boom")

    answered = board.decide_card_through_api(_ITEM, [listed[2], listed[3]], ["A", "B"])

    assert answered.json() == {"status": "failed", "message": "aco rulings failed: boom"}
    _assert_untouched(port, repository)


def test_a_fingerprint_read_under_another_repo_never_satisfies_a_card_post(
    two_repositories: tuple[BoardForge, BoardForge], listed_items: Lister
) -> None:
    """ABRD-21, ABRD-79."""
    ports = [decision_port(repository) for repository in two_repositories]
    for repository in two_repositories:
        repository.put_item(_ITEM, group_body())

    with serving_many(dict(zip("ab", ports, strict=True))) as board:
        listed_in_a = listed_items(board, "a")[0]["lines"]
        answered = board.decide_card_through_api(_ITEM, listed_in_a[1:], ["A", "B"], repo="b")

    assert answered.json() == {"status": "failed", "message": LINE_CHANGED}
    for port, repository in zip(ports, two_repositories, strict=True):
        _assert_untouched(port, repository)


def _assert_nothing_after(
    port: RecordedPort, repository: BoardForge, arranged: tuple[int, int]
) -> None:
    """No port call and no forge request since `arranged` was counted."""
    assert (len(port.calls()), repository.requests) == arranged


def test_a_card_post_for_an_unknown_repo_is_a_bad_request(
    repository: BoardForge, board: BoardClient, port: RecordedPort, show: _Show
) -> None:
    """ABRD-09, ABRD-81."""
    listed = show()
    arranged = (len(port.calls()), repository.requests)

    answered = board.decide_card_through_api(_ITEM, [listed[2], listed[3]], ["A", "B"], repo="x")

    assert (answered.status, answered.json()) == (400, {"error": _BAD_REQUEST})
    _assert_nothing_after(port, repository, arranged)


def test_a_card_post_without_the_token_is_forbidden(
    repository: BoardForge, board: BoardClient, port: RecordedPort, show: _Show
) -> None:
    """ABRD-09."""
    listed = show()
    payload = {
        "repo": board.repo,
        "item": _ITEM,
        "lines": [{"line": 2, "fingerprint": listed[2]["fingerprint"]}],
    }
    arranged = (len(port.calls()), repository.requests)

    answered = board.call_api("POST", "/api/rule", json.dumps(payload), presented=None)

    assert answered.status == 403
    _assert_nothing_after(port, repository, arranged)


def _plain(payload: _Payload) -> _Payload:
    """The payload with no option on any entry, to carry one answer for all."""
    entries = [
        {key: value for key, value in entry.items() if key != "option"}
        for entry in payload["lines"]
    ]
    return {**payload, "lines": entries}


def _entry(payload: _Payload, index: int, **changes: object) -> _Payload:
    entries = [
        {**entry, **changes} if position == index else entry
        for position, entry in enumerate(payload["lines"])
    ]
    return {**payload, "lines": entries}


def _plain_second(payload: _Payload) -> _Payload:
    """Only the first entry carries an option."""
    return {**payload, "lines": [payload["lines"][0], _plain(payload)["lines"][1]]}


_MALFORMED_CARDS: dict[str, Callable[[_Payload], _Payload]] = {
    "empty-lines": lambda payload: {**payload, "lines": []},
    "lines-not-a-list": lambda payload: {**payload, "lines": 5},
    "entry-not-an-object": lambda payload: {**payload, "lines": [5]},
    "line-named-twice": lambda payload: {**payload, "lines": [payload["lines"][0]] * 2},
    "line-zero": lambda payload: _entry(payload, 0, line=0),
    "line-true": lambda payload: _entry(payload, 0, line=True),
    "line-text": lambda payload: _entry(payload, 0, line="2"),
    "fingerprint-number": lambda payload: _entry(payload, 0, fingerprint=5),
    "entry-note": lambda payload: _entry(payload, 0, note="x"),
    "entry-other": lambda payload: _entry(payload, 0, other="x"),
    "entry-unclear": lambda payload: _entry(payload, 0, unclear=True),
    "entry-outcome": lambda payload: _entry(payload, 0, outcome="yes"),
    "option-on-one-entry-only": _plain_second,
    "option-null": lambda payload: _entry(payload, 0, option=None),
    "option-lowercase": lambda payload: _entry(payload, 0, option="a"),
    "option-past-the-card": lambda payload: _entry(payload, 0, option="E"),
    "option-number": lambda payload: _entry(payload, 0, option=1),
    "top-level-line": lambda payload: {**payload, "line": 2},
    "top-level-line-null": lambda payload: {**payload, "line": None},
    "top-level-fingerprint-null": lambda payload: {**payload, "fingerprint": None},
    "top-level-option-null": lambda payload: {**payload, "option": None},
    "top-level-outcome-null": lambda payload: {**payload, "outcome": None},
    "picks-with-other": lambda payload: {**payload, "other": "x"},
    "picks-with-unclear": lambda payload: {**payload, "unclear": True},
    "picks-with-note": lambda payload: {**payload, "note": "x"},
    "no-answer": _plain,
    "other-and-unclear": lambda payload: {**_plain(payload), "other": "x", "unclear": True},
    "other-with-note": lambda payload: {**_plain(payload), "other": "x", "note": "n"},
    "other-blank": lambda payload: {**_plain(payload), "other": "  "},
    "other-too-long": lambda payload: {**_plain(payload), "other": "x" * 281},
    "other-number": lambda payload: {**_plain(payload), "other": 5},
    "unclear-false": lambda payload: {**_plain(payload), "unclear": False},
    "unclear-text": lambda payload: {**_plain(payload), "unclear": "true"},
    "unclear-note-too-long": lambda payload: {
        **_plain(payload),
        "unclear": True,
        "note": "x" * 281,
    },
    "unclear-note-nul": lambda payload: {**_plain(payload), "unclear": True, "note": "a\0b"},
    "item-zero": lambda payload: {**payload, "item": 0},
    "item-true": lambda payload: {**payload, "item": True},
    "unclear-note-number": lambda payload: {**_plain(payload), "unclear": True, "note": 7},
    "unclear-note-lone-surrogate": lambda payload: {
        **_plain(payload),
        "unclear": True,
        "note": "\ud800",
    },
}


@pytest.mark.parametrize("change", _MALFORMED_CARDS.values(), ids=list(_MALFORMED_CARDS))
def test_a_card_post_breaking_the_card_key_rules_is_refused_before_any_aco_call(
    repository: BoardForge,
    board: BoardClient,
    port: RecordedPort,
    change: Callable[[_Payload], _Payload],
    show: _Show,
) -> None:
    """ABRD-81."""
    listed = show()
    valid = {
        "repo": board.repo,
        "item": _ITEM,
        "lines": [
            {"line": 2, "fingerprint": listed[2]["fingerprint"], "option": "A"},
            {"line": 3, "fingerprint": listed[3]["fingerprint"], "option": "B"},
        ],
    }
    arranged = (len(port.calls()), repository.requests)

    answered = board.post_rule(change(valid))

    assert (answered.status, answered.json()) == (400, {"error": _BAD_REQUEST})
    _assert_nothing_after(port, repository, arranged)


@pytest.mark.parametrize(
    "answer",
    [
        {"option": "A"},
        {"other": _ANSWER},
        {"unclear": True},
        {"unclear": True, "note": "x"},
        {"outcome": "yes", "note": "x"},
        {},
    ],
    ids=["option", "other", "unclear", "unclear-note", "outcome", "nothing"],
)
def test_a_post_without_lines_is_refused_before_any_aco_call(
    repository: BoardForge,
    board: BoardClient,
    port: RecordedPort,
    answer: dict[str, object],
    show: _Show,
) -> None:
    """ABRD-40."""
    listed = show()
    payload = {
        "repo": board.repo,
        "item": _ITEM,
        "line": 2,
        "fingerprint": listed[2]["fingerprint"],
        **answer,
    }
    arranged = (len(port.calls()), repository.requests)

    answered = board.post_rule(payload)

    assert (answered.status, answered.json()) == (400, {"error": _BAD_REQUEST})
    _assert_nothing_after(port, repository, arranged)


@pytest.mark.parametrize(
    "top_level",
    [{"other": None}, {"unclear": None}, {"note": None}, {"other": None, "unclear": None}],
)
def test_a_null_answer_key_beside_picks_names_nothing(
    board: BoardClient, top_level: dict[str, object], show: _Show
) -> None:
    """ABRD-81."""
    listed = show()

    answered = board.decide_card_through_api(_ITEM, [listed[2], listed[3]], ["A", "B"], top_level)

    assert answered.json() == {"status": "ruled", "message": None}


def test_two_card_posts_for_one_item_store_it_once_and_refuse_the_other_as_already_ruled(
    repository: BoardForge, board: BoardClient, show: _Show
) -> None:
    """ABRD-80, ABRD-17."""
    listed = show()
    shown = [listed[2], listed[3]]

    with ThreadPoolExecutor(max_workers=2) as threads:
        answers = [
            threads.submit(board.decide_card_through_api, _ITEM, shown, ["A", "B"])
            for _ in range(2)
        ]
        statuses = sorted(str(answer.result().json()["status"]) for answer in answers)

    assert statuses == ["already_ruled", "ruled"]
    assert _stored(repository, (2, 3)) == _picked("A", "B")
    assert repository.body_writes() == [_ITEM]


def test_a_card_post_after_stopping_began_is_refused_and_runs_no_aco_rule(
    repository: BoardForge, port: RecordedPort, show: _Show
) -> None:
    """ABRD-17, ABRD-18."""
    listed = show()
    boards = Boards({"repo": Board(port)})
    boards.close_writes()
    posted = PostedCard(_ITEM, (PostedLine(2, listed[2]["fingerprint"], "A"),), None)

    answered = boards.decide_card("repo", posted)

    assert answered.message == SHUTTING_DOWN
    _assert_untouched(port, repository)
