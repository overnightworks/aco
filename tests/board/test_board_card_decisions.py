"""The board decides a whole option card with one `aco rule` (ABRD-09, ABRD-39, ABRD-40,
ABRD-64, ABRD-70, ABRD-77 to ABRD-81):
the post's shape, the refusals before any `aco rule`, aco's own refusals relayed once for the
card, and that real `aco rule` stores what the board sent in one write."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from aco_board_fixtures import (
    BoardClient,
    FakeAcoRepository,
    Lister,
    line,
    option_line,
    row,
    serving_two,
)
from cli_fixtures import run_cli
from option_cards import check_defects, group_body, serve_item, shown_hash

from aco import body
from aco.board.aco_cli import AcoCli
from aco.board.board import LINE_CHANGED, SHUTTING_DOWN, Board, Boards
from aco.board.ports import PostedCard, PostedLine

_BAD_REQUEST = "bad request: decision"
_ITEM = 7
_ANSWER = "Nur auf dem Desktop offen lassen."
_ALREADY_RULED = "line 3 is already ruled; a changed ruling is a new line"
_WITH_HEAD = "line 2 is already with its head; it comes back once revised"
_Shown = dict[int, dict[str, Any]]
_Show = Callable[..., _Shown]
_Payload = dict[str, Any]


def _hash(index: int) -> str:
    return f"sha256:{index:064x}"


def _item(
    indexes: Sequence[int], *, rehashed: Sequence[int] = (), ruled: Sequence[int] = ()
) -> dict[str, object]:
    """Item 7: a ruled yes/no line 1 and an option line per index."""
    options = [
        option_line(
            index=index,
            card_hash=_hash(index + 100 if index in rehashed else index),
            ruling="A" if index in ruled else None,
        )
        for index in indexes
    ]
    return row(_ITEM, "Karte", line(1, "Alt", ruling="yes"), *options)


@pytest.fixture
def show(repository: FakeAcoRepository, board: BoardClient, listed_items: Lister) -> _Show:
    """Lists item 7 with an option line per index; its lines as listed, by line index."""

    def listed(*indexes: int) -> _Shown:
        repository.set_rulings(_item(indexes))
        return {entry["index"]: entry for entry in listed_items(board)[0]["lines"]}

    return listed


def _expected_line(index: int, letter: str) -> list[str]:
    picked = ["--option", letter] if letter else []
    return ["--line", str(index), *picked, f"--card-hash={_hash(index)}"]


def _expected_call(
    indexes: Sequence[int], options: Sequence[str], tail: Sequence[str]
) -> list[str]:
    lines = [_expected_line(index, letter) for index, letter in zip(indexes, options, strict=True)]
    return ["rule", str(_ITEM), *(part for entry in lines for part in entry), *tail, "--json"]


@pytest.mark.parametrize(
    ("indexes", "options", "answer", "tail", "status", "stored"),
    [
        ((2, 3), ("A", "B"), {}, ("--via", "board"), "ruled", ("A", "B")),
        (
            (2, 3, 4, 5),
            ("B", "A", "B", "A"),
            {},
            ("--via", "board"),
            "ruled",
            ("B", "A", "B", "A"),
        ),
        ((2, 3, 4, 5), ("A",) * 4, {}, ("--via", "board"), "ruled", ("A",) * 4),
        ((2,), ("B",), {}, ("--via", "board"), "ruled", ("B",)),
        (
            (2, 3),
            ("", ""),
            {"other": f"  {_ANSWER}\n"},
            (f"--other={_ANSWER}", "--via", "board"),
            "ruled",
            ("other", "other"),
        ),
        (
            (2, 3),
            ("", ""),
            {"other": " -n starts like an option "},
            ("--other=-n starts like an option", "--via", "board"),
            "ruled",
            ("other", "other"),
        ),
        (
            (2, 3),
            ("", ""),
            {"other": 'a\n"b" ä'},
            ('--other=a\n"b" ä', "--via", "board"),
            "ruled",
            ("other", "other"),
        ),
        (
            (2, 3),
            ("", ""),
            {"other": f" {'x' * 280} "},
            (f"--other={'x' * 280}", "--via", "board"),
            "ruled",
            ("other", "other"),
        ),
        ((2, 3), ("", ""), {"unclear": True}, ("--unclear",), "returned", (None, None)),
        (
            (2, 3),
            ("", ""),
            {"unclear": True, "note": " Was kostet B? "},
            ("--unclear", "--note=Was kostet B?"),
            "returned",
            (None, None),
        ),
        (
            (2, 3),
            ("", ""),
            {"unclear": True, "note": "  \n"},
            ("--unclear",),
            "returned",
            (None, None),
        ),
        (
            (2, 3),
            ("", ""),
            {"unclear": True, "note": "a\nb"},
            ("--unclear", "--note=a\nb"),
            "returned",
            (None, None),
        ),
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
def test_a_card_post_runs_one_aco_rule_naming_every_line_and_stores_them_all(
    repository: FakeAcoRepository,
    board: BoardClient,
    indexes: tuple[int, ...],
    options: tuple[str, ...],
    answer: dict[str, object],
    tail: tuple[str, ...],
    status: str,
    stored: tuple[str | None, ...],
    show: _Show,
) -> None:
    """ABRD-77, ABRD-78."""
    shown = show(*indexes)
    posted_options = None if answer else options

    answered = board.decide_card_through_api(
        _ITEM, [shown[index] for index in indexes], posted_options, answer
    )

    assert answered.json() == {"status": status, "message": None}
    assert repository.rule_calls() == [_expected_call(indexes, options, tail)]
    assert [repository.stored_line(_ITEM, index)["ruling"] for index in indexes] == list(stored)


@pytest.mark.parametrize(
    ("options", "answer", "stored"),
    [
        (["A", "B"], {}, ("A", "B")),
        (None, {"other": _ANSWER}, ("other", "other")),
    ],
    ids=["picks", "other"],
)
def test_a_card_with_a_line_held_by_its_head_is_stored_without_the_return(
    repository: FakeAcoRepository,
    board: BoardClient,
    options: list[str] | None,
    answer: dict[str, object],
    stored: tuple[str, str],
    listed_items: Lister,
) -> None:
    """ABRD-77, ABRD-78, RULE-25."""
    repository.set_rulings(
        row(
            _ITEM,
            "Karte",
            option_line(index=2, card_hash=_hash(2), returned_on="2026-10-01", returned_note="?"),
            option_line(index=3, card_hash=_hash(3)),
        )
    )
    shown = listed_items(board)[0]["lines"]

    board.decide_card_through_api(_ITEM, shown, options, answer)

    after = [repository.stored_line(_ITEM, index) for index in (2, 3)]
    assert [(entry["ruling"], entry["via"], entry["returned_on"]) for entry in after] == [
        (ruling, "board", None) for ruling in stored
    ]


def _added_after_reading(repository: FakeAcoRepository) -> None:
    repository.set_rulings(_item((2, 3, 4)))


def _rehashed_after_reading(repository: FakeAcoRepository) -> None:
    repository.set_rulings(_item((2, 3), rehashed=(3,)))


@pytest.mark.parametrize(
    ("shown", "later", "posted"),
    [
        ((2, 3, 4), None, (2, 3)),
        ((2, 3), _added_after_reading, (2, 3)),
        ((2, 3), _rehashed_after_reading, (2, 3)),
        ((2, 3), None, (2, 3, 9)),
        ((2, 3), None, (1, 2, 3)),
    ],
    ids=["point-missing", "point-added", "card-changed", "line-not-listed", "yes-no-line"],
)
def test_a_card_post_missing_a_point_or_naming_a_changed_line_runs_no_aco_rule(
    repository: FakeAcoRepository,
    board: BoardClient,
    shown: tuple[int, ...],
    later: Callable[[FakeAcoRepository], None] | None,
    posted: tuple[int, ...],
    show: _Show,
) -> None:
    """ABRD-79."""
    listed = show(*shown)
    listed[9] = {**listed[2], "index": 9}
    if later is not None:
        later(repository)
    options = ["A"] * len(posted)

    answered = board.decide_card_through_api(_ITEM, [listed[index] for index in posted], options)

    assert answered.json() == {"status": "failed", "message": LINE_CHANGED}
    assert repository.rule_calls() == []


def test_a_card_post_names_a_line_ruled_meanwhile_and_aco_refuses_the_whole_card(
    repository: FakeAcoRepository, board: BoardClient, show: _Show
) -> None:
    """ABRD-80, RULE-04."""
    listed = show(2, 3)
    repository.set_rulings(_item((2, 3), ruled=(3,)))
    before = repository.rulings_state()

    answered = board.decide_card_through_api(_ITEM, [listed[2], listed[3]], ["A", "B"])

    assert answered.json() == {"status": "already_ruled", "message": _ALREADY_RULED}
    assert repository.rulings_state() == before


@pytest.mark.parametrize(
    ("refusal", "status", "message"),
    [
        (("card_changed", "card changed"), "failed", LINE_CHANGED),
        (
            ("invalid_usage", "letter C is not on the card"),
            "failed",
            "aco rule failed: letter C is not on the card",
        ),
    ],
    ids=["card-changed-at-the-write", "letter-not-on-the-card"],
)
def test_aco_refusing_the_card_write_is_relayed_once_and_stores_nothing(
    repository: FakeAcoRepository,
    board: BoardClient,
    refusal: tuple[str, str],
    status: str,
    message: str,
    show: _Show,
) -> None:
    """ABRD-41, ABRD-80."""
    listed = show(2, 3)
    repository.refuse_rule(*refusal)
    before = repository.rulings_state()

    answered = board.decide_card_through_api(_ITEM, [listed[2], listed[3]], ["A", "C"])

    assert answered.json() == {"status": status, "message": message}
    assert repository.rulings_state() == before


def test_an_unclear_card_with_a_line_already_with_its_head_is_failed_with_acos_sentence(
    repository: FakeAcoRepository, board: BoardClient, show: _Show
) -> None:
    """ABRD-80, RULE-24."""
    listed = show(2, 3)
    repository.set_rulings(
        row(
            _ITEM,
            "Karte",
            option_line(index=2, card_hash=_hash(2), returned_on="2026-10-01", returned_note="x"),
            option_line(index=3, card_hash=_hash(3)),
        )
    )
    before = repository.rulings_state()

    answered = board.decide_card_through_api(_ITEM, [listed[2], listed[3]], None, {"unclear": True})

    assert answered.json() == {"status": "failed", "message": f"aco rule failed: {_WITH_HEAD}"}
    assert repository.rulings_state() == before


def test_a_card_post_when_aco_cannot_be_read_is_failed_without_an_aco_rule(
    repository: FakeAcoRepository, board: BoardClient, show: _Show
) -> None:
    """ABRD-79."""
    listed = show(2, 3)
    repository.fail_rulings("boom")

    answered = board.decide_card_through_api(_ITEM, [listed[2], listed[3]], ["A", "B"])

    assert answered.json()["status"] == "failed"
    assert repository.rule_calls() == []


def test_a_fingerprint_read_under_another_repo_never_satisfies_a_card_post(
    two_repositories: tuple[FakeAcoRepository, FakeAcoRepository], listed_items: Lister
) -> None:
    """ABRD-21, ABRD-79."""
    for repository in two_repositories:
        repository.set_rulings(_item((2, 3)))

    with serving_two(two_repositories) as board:
        listed_in_a = listed_items(board, "a")[0]["lines"]
        answered = board.decide_card_through_api(_ITEM, listed_in_a[1:], ["A", "B"], repo="b")

    assert answered.json() == {"status": "failed", "message": LINE_CHANGED}
    assert [repository.rule_calls() for repository in two_repositories] == [[], []]


def test_a_card_post_for_an_unknown_repo_is_a_bad_request(
    repository: FakeAcoRepository, board: BoardClient, show: _Show
) -> None:
    """ABRD-09, ABRD-81."""
    listed = show(2, 3)
    calls_before = repository.calls()

    answered = board.decide_card_through_api(_ITEM, [listed[2], listed[3]], ["A", "B"], repo="x")

    assert (answered.status, answered.json()) == (400, {"error": _BAD_REQUEST})
    assert repository.calls() == calls_before


def test_a_card_post_without_the_token_is_forbidden(
    repository: FakeAcoRepository, board: BoardClient, show: _Show
) -> None:
    """ABRD-09."""
    listed = show(2, 3)
    payload = {
        "repo": board.repo,
        "item": _ITEM,
        "lines": [{"line": 2, "fingerprint": listed[2]["fingerprint"]}],
    }

    answered = board.call_api("POST", "/api/rule", json.dumps(payload), presented=None)

    assert answered.status == 403
    assert repository.rule_calls() == []


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
    repository: FakeAcoRepository,
    board: BoardClient,
    change: Callable[[_Payload], _Payload],
    show: _Show,
) -> None:
    """ABRD-81."""
    listed = show(2, 3)
    valid = {
        "repo": board.repo,
        "item": _ITEM,
        "lines": [
            {"line": 2, "fingerprint": listed[2]["fingerprint"], "option": "A"},
            {"line": 3, "fingerprint": listed[3]["fingerprint"], "option": "B"},
        ],
    }
    calls_before = repository.calls()

    answered = board.post_rule(change(valid))

    assert (answered.status, answered.json()) == (400, {"error": _BAD_REQUEST})
    assert repository.calls() == calls_before


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
    repository: FakeAcoRepository, board: BoardClient, answer: dict[str, object], show: _Show
) -> None:
    """ABRD-40."""
    listed = show(2)
    payload = {
        "repo": board.repo,
        "item": _ITEM,
        "line": 2,
        "fingerprint": listed[2]["fingerprint"],
        **answer,
    }
    calls_before = repository.calls()

    answered = board.post_rule(payload)

    assert (answered.status, answered.json()) == (400, {"error": _BAD_REQUEST})
    assert repository.calls() == calls_before


@pytest.mark.parametrize(
    "top_level",
    [{"other": None}, {"unclear": None}, {"note": None}, {"other": None, "unclear": None}],
)
def test_a_null_answer_key_beside_picks_names_nothing(
    repository: FakeAcoRepository, board: BoardClient, top_level: dict[str, object], show: _Show
) -> None:
    """ABRD-81."""
    listed = show(2, 3)

    answered = board.decide_card_through_api(_ITEM, [listed[2], listed[3]], ["A", "B"], top_level)

    assert answered.json() == {"status": "ruled", "message": None}


def test_two_card_posts_for_one_item_store_it_once_and_refuse_the_other_as_already_ruled(
    repository: FakeAcoRepository, board: BoardClient, show: _Show
) -> None:
    """ABRD-80, ABRD-17."""
    listed = show(2, 3)
    shown = [listed[2], listed[3]]

    with ThreadPoolExecutor(max_workers=2) as threads:
        answers = [
            threads.submit(board.decide_card_through_api, _ITEM, shown, ["A", "B"])
            for _ in range(2)
        ]
        statuses = sorted(str(answer.result().json()["status"]) for answer in answers)

    assert statuses == ["already_ruled", "ruled"]
    assert [repository.stored_line(_ITEM, index)["ruling"] for index in (2, 3)] == ["A", "B"]


def test_a_card_post_after_stopping_began_is_refused_and_runs_no_aco_rule(
    repository: FakeAcoRepository, board: BoardClient, show: _Show
) -> None:
    """ABRD-17, ABRD-18."""
    listed = show(2, 3)
    boards = Boards({"repo": Board(AcoCli(directory=repository.directory))})
    boards.close_writes()
    posted = PostedCard(_ITEM, (PostedLine(2, listed[2]["fingerprint"], "A"),), None)

    answered = boards.decide_card("repo", posted)

    assert answered.message == SHUTTING_DOWN
    assert repository.rule_calls() == []


def _group_body_with_ruled_yes_no() -> str:
    """Issue #7 with its yes/no neighbour ruled, so only the option lines are open."""
    return group_body(
        yes_no_line='[[expectation]]\ntext = "Alt"\nruling = "yes"\nruled_on = 2026-10-28\n'
    )


@pytest.mark.usefixtures("github_world")
@pytest.mark.parametrize(
    ("answer", "options", "stored"),
    [
        ({}, ("A", "B"), {"ruling": ("A", "B"), "via": ("board", "board")}),
        (
            {"other": _ANSWER},
            None,
            {"ruling": ("other", "other"), "other": (_ANSWER, _ANSWER), "via": ("board", "board")},
        ),
        (
            {"unclear": True, "note": "Was kostet B?"},
            None,
            {"returned_note": ("Was kostet B?", "Was kostet B?")},
        ),
    ],
    ids=["picks", "other", "unclear-note"],
)
def test_the_real_aco_rule_stores_the_whole_card_in_one_body_write(
    repository: FakeAcoRepository,
    board: BoardClient,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    answer: dict[str, object],
    options: tuple[str, ...] | None,
    stored: dict[str, tuple[str, str]],
    listed_items: Lister,
) -> None:
    """ABRD-78, RULE-29: the argv is lawful for aco, and aco stores all lines at once."""
    repository.set_rulings(
        row(
            _ITEM,
            "Karte",
            line(1, "Alt", ruling="yes"),
            option_line(index=2, card_hash=shown_hash(_group_body_with_ruled_yes_no(), 2)),
            option_line(index=3, card_hash=shown_hash(_group_body_with_ruled_yes_no(), 3)),
        )
    )
    shown = listed_items(board)[0]["lines"][1:]
    posted = board.decide_card_through_api(_ITEM, shown, options, answer)
    [sent] = repository.rule_calls()
    forge = serve_item(monkeypatch, _group_body_with_ruled_yes_no())

    ruled = run_cli(sent, capsys)

    assert ruled.status == 0
    assert json.loads(ruled.stdout)["reason"] == posted.json()["status"]
    assert len(forge.body_writes) == 1
    entries = body.block_expectation_dicts(body.locate_block(forge.item_bodies[_ITEM]).data)
    for key, values in stored.items():
        assert tuple(entries[position].get(key) for position in (1, 2)) == values
    assert check_defects(capsys, forge.item_bodies[_ITEM]) == (0, [])
