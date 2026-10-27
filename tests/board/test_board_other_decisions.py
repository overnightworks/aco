"""The board answers an option card with the operator's own words, or sends it back
to its head (ABRD-09, ABRD-42, ABRD-63 to ABRD-66, ABRD-70): the post's shape and
refusals, the exact `aco rule --other` it runs, and that real `aco rule` accepts and
stores that call."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest
from aco_board_fixtures import (
    BoardClient,
    FakeAcoRepository,
    first_listed_line,
    line,
    option_line,
    row,
)
from cli_fixtures import run_cli
from option_cards import GOLDEN_CARD_HASH, card, item_body, serve_item

from aco import body
from aco.board.board import LINE_CHANGED

_BAD_REQUEST = "bad request: decision"
_ANSWER = "Nur auf dem Desktop offen lassen."


def test_an_other_post_rules_the_line_with_the_stripped_answer(
    repository: FakeAcoRepository, board: BoardClient, listed: dict[str, Any]
) -> None:
    """ABRD-63, ABRD-64."""
    answer = board.post_rule({**listed, "other": f"  {_ANSWER}\n"})

    assert answer.json() == {"status": "ruled", "message": None}
    stored = repository.stored_line(12, 1)
    assert (stored["ruling"], stored["other"], stored["via"]) == ("other", _ANSWER, "board")
    assert "note" not in stored


@pytest.mark.parametrize(
    "text", ["-n starts like an option", "two  spaces", "a\nb", 'quote " here', "Ärger ä"]
)
def test_an_other_post_runs_aco_rule_with_the_answer_as_one_argument(
    repository: FakeAcoRepository, board: BoardClient, listed: dict[str, Any], text: str
) -> None:
    """ABRD-64."""
    board.post_rule({**listed, "other": text})

    assert repository.rule_calls() == [
        [
            "rule",
            "12",
            "--line",
            "1",
            f"--other={text.strip()}",
            "--via",
            "board",
            f"--card-hash={listed_card_hash()}",
            "--json",
        ]
    ]


def listed_card_hash() -> str:
    return cast(str, option_line()["card_hash"])


@pytest.mark.parametrize(
    "fields",
    [
        {"other": ""},
        {"other": "   \n"},
        {"other": 5},
        {"other": ["x"]},
        {"other": "x" * 281},
        {"other": "a\0b"},
        {"other": "\ud800"},
        {"other": "x", "outcome": "yes"},
        {"other": "x", "option": "A"},
        {"other": "x", "note": "n"},
        {"other": "x", "note": ""},
        {"unclear": False},
        {"unclear": "true"},
        {"unclear": 1},
        {"unclear": True, "outcome": "yes"},
        {"unclear": True, "option": "A"},
        {"unclear": True, "other": "x"},
        {"unclear": True, "note": 5},
        {"unclear": True, "note": "x" * 281},
        {"unclear": True, "note": "a\0b"},
        {"unclear": True, "note": "\ud800"},
    ],
    ids=lambda fields: ",".join(f"{key}={str(value)[:12]!r}" for key, value in fields.items()),
)
def test_a_post_breaking_the_shape_or_the_bound_is_refused_before_any_aco_call(
    repository: FakeAcoRepository,
    board: BoardClient,
    listed: dict[str, Any],
    fields: dict[str, object],
) -> None:
    """ABRD-05, ABRD-42, ABRD-65, ABRD-70."""
    calls_before = repository.calls()

    answer = board.post_rule({**listed, **fields})

    assert (answer.status, answer.json()) == (400, {"error": _BAD_REQUEST})
    assert repository.calls() == calls_before


@pytest.mark.parametrize(
    "fields",
    [{"other": None}, {"unclear": None}, {"unclear": None, "other": None}],
    ids=["null-other", "null-unclear", "null-unclear-and-other"],
)
def test_a_null_other_or_unclear_names_nothing_so_the_option_beside_it_decides(
    repository: FakeAcoRepository,
    board: BoardClient,
    listed: dict[str, Any],
    fields: dict[str, object],
) -> None:
    """ABRD-42."""
    answer = board.post_rule({**listed, "option": "A", **fields})

    assert answer.json() == {"status": "ruled", "message": None}
    assert repository.stored_line(12, 1)["ruling"] == "A"


@pytest.mark.parametrize(
    ("answer", "stored_key"),
    [
        ({"other": f" {'x' * 280} "}, "other"),
        ({"unclear": True, "note": f" {'x' * 280} "}, "returned_note"),
    ],
    ids=["other", "unclear"],
)
def test_an_answer_of_exactly_the_bound_after_trimming_is_accepted(
    repository: FakeAcoRepository,
    board: BoardClient,
    listed: dict[str, Any],
    answer: dict[str, object],
    stored_key: str,
) -> None:
    """ABRD-05, ABRD-42, ABRD-65."""
    posted = board.post_rule({**listed, **answer})

    assert posted.json() == {"status": "ruled", "message": None}
    assert repository.stored_line(12, 1)[stored_key] == "x" * 280


_ANSWERS = pytest.mark.parametrize(
    "answer", [{"other": _ANSWER}, {"unclear": True}], ids=["other", "unclear"]
)


@_ANSWERS
def test_a_post_after_the_card_changed_is_refused_without_a_write(
    repository: FakeAcoRepository,
    board: BoardClient,
    listed: dict[str, Any],
    answer: dict[str, object],
) -> None:
    """ABRD-02, ABRD-64, ABRD-70."""
    repository.set_rulings(row(12, "Song jump", option_line(card_hash="sha256:other")))

    posted = board.post_rule({**listed, **answer})

    assert posted.json() == {"status": "failed", "message": LINE_CHANGED}
    assert repository.rule_calls() == []


@_ANSWERS
@pytest.mark.parametrize("index", [1, 9], ids=["yes-no-line", "missing-line"])
def test_a_post_for_no_option_line_is_refused_as_changed(
    repository: FakeAcoRepository, board: BoardClient, index: int, answer: dict[str, object]
) -> None:
    """ABRD-40, ABRD-64, ABRD-70."""
    repository.set_rulings(row(12, "Song jump", line(1, "Guests?", default="yes")))
    yes_no = first_listed_line(board)

    posted = board.post_rule(
        {
            "repo": board.repo,
            "item": 12,
            "line": index,
            "fingerprint": yes_no["fingerprint"],
            **answer,
        }
    )

    assert posted.json() == {"status": "failed", "message": LINE_CHANGED}
    assert repository.rule_calls() == []


@pytest.mark.usefixtures("github_world")
@pytest.mark.parametrize("text", ["-n first", "a\nb", 'say "hi" ä'])
@pytest.mark.parametrize(
    ("answer", "stored", "stamped"),
    [
        (
            lambda text: {"other": f" {text} "},
            lambda text: {"ruling": "other", "other": text, "via": "board", "note": None},
            set(),
        ),
        (
            lambda text: {"unclear": True, "note": f" {text} "},
            lambda text: {"ruling": None, "via": None, "returned_note": text},
            {"returned_on"},
        ),
    ],
    ids=["other", "unclear"],
)
def test_the_real_aco_rule_stores_what_the_board_sent(
    repository: FakeAcoRepository,
    board: BoardClient,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    text: str,
    answer: Callable[[str], dict[str, object]],
    stored: Callable[[str], dict[str, object]],
    stamped: set[str],
) -> None:
    """ABRD-64, ABRD-70, RULE-15, RULE-21, RULE-22, RULE-23: the argv is lawful for aco."""
    repository.set_rulings(
        row(7, "Karte", option_line(index=2, card_hash=GOLDEN_CARD_HASH, topic="Sprung"))
    )
    shown = first_listed_line(board)
    board.post_rule(
        {
            "repo": board.repo,
            "item": 7,
            "line": 2,
            "fingerprint": shown["fingerprint"],
            **answer(text),
        }
    )
    [sent] = repository.rule_calls()
    forge = serve_item(monkeypatch, item_body(card()))

    ruled = run_cli(sent, capsys)

    assert ruled.status == 0
    entry = body.block_expectation_dicts(body.locate_block(forge.item_bodies[7]).data)[1]
    assert {key: entry.get(key) for key in stored(text)} == stored(text)
    assert stamped <= set(entry)
