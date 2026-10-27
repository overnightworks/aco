"""The board sends an option card back to its head (ABRD-09, ABRD-42, ABRD-70): the
post's shape and refusals, the exact `aco rule --unclear` it runs, and that real
`aco rule` accepts and stores that call."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from aco_board_fixtures import (
    BoardClient,
    FakeAcoRepository,
    line,
    option_line,
    row,
)
from cli_fixtures import run_cli
from github_fixtures import assert_github_world
from option_cards import GOLDEN_CARD_HASH, card, item_body, serve_item

from aco import body
from aco.board.board import LINE_CHANGED

_NOTE = "Please show the jump on mobile too."


@pytest.fixture
def listed(repository: FakeAcoRepository, board: BoardClient) -> dict[str, Any]:
    """The post payload naming item 12's first listed line, without a decision."""
    repository.set_rulings(row(12, "Song jump", option_line()))
    shown = _first_listed_line(board)
    return {
        "repo": board.repo,
        "item": 12,
        "line": shown["index"],
        "fingerprint": shown["fingerprint"],
    }


def _first_listed_line(board: BoardClient) -> dict[str, Any]:
    return board.get_board_json().json()["repos"][0]["items"][0]["lines"][0]


def test_an_unclear_post_leaves_the_line_open_with_its_head_and_the_trimmed_note(
    repository: FakeAcoRepository, board: BoardClient, listed: dict[str, Any]
) -> None:
    """ABRD-70."""
    answer = board.post_rule({**listed, "unclear": True, "note": f"  {_NOTE}\n"})

    assert answer.json() == {"status": "ruled", "message": None}
    stored = repository.stored_line(12, 1)
    assert (stored["ruling"], stored["via"], stored["returned_note"]) == (None, None, _NOTE)
    assert stored["returned_on"] is not None


@pytest.mark.parametrize(
    "note",
    [None, "", "  \n", "-n starts like an option", "two  spaces", "a\nb", 'quote " here', "ä"],
)
def test_an_unclear_post_runs_aco_rule_with_the_note_as_one_argument_and_no_via(
    repository: FakeAcoRepository, board: BoardClient, listed: dict[str, Any], note: str | None
) -> None:
    """ABRD-70."""
    fields: dict[str, object] = {} if note is None else {"note": note}
    board.post_rule({**listed, "unclear": True, **fields})

    sent_note = [] if note is None or not note.strip() else [f"--note={note.strip()}"]
    assert repository.rule_calls() == [
        [
            "rule",
            "12",
            "--line",
            "1",
            "--unclear",
            *sent_note,
            f"--card-hash={option_line()['card_hash']}",
            "--json",
        ]
    ]


def test_an_unclear_note_of_exactly_the_bound_after_trimming_is_accepted(
    repository: FakeAcoRepository, board: BoardClient, listed: dict[str, Any]
) -> None:
    """ABRD-05, ABRD-42."""
    answer = board.post_rule({**listed, "unclear": True, "note": f" {'x' * 280} "})

    assert answer.json() == {"status": "ruled", "message": None}
    assert repository.stored_line(12, 1)["returned_note"] == "x" * 280


@pytest.mark.parametrize(
    "fields",
    [
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
def test_an_unclear_post_breaking_the_shape_or_the_bound_is_refused_before_any_aco_call(
    repository: FakeAcoRepository,
    board: BoardClient,
    listed: dict[str, Any],
    fields: dict[str, object],
) -> None:
    """ABRD-05, ABRD-42, ABRD-70."""
    calls_before = repository.calls()

    answer = board.post_rule({**listed, **fields})

    assert (answer.status, answer.json()) == (400, {"error": "bad request: decision"})
    assert repository.calls() == calls_before


@pytest.mark.parametrize(
    "fields",
    [{"unclear": None}, {"unclear": None, "other": None}],
    ids=["null-unclear", "null-unclear-and-other"],
)
def test_a_null_unclear_names_nothing_so_the_option_beside_it_decides(
    repository: FakeAcoRepository,
    board: BoardClient,
    listed: dict[str, Any],
    fields: dict[str, object],
) -> None:
    """ABRD-42."""
    answer = board.post_rule({**listed, "option": "A", **fields})

    assert answer.json() == {"status": "ruled", "message": None}
    assert repository.stored_line(12, 1)["ruling"] == "A"


def test_an_unclear_post_after_the_card_changed_is_refused_without_a_write(
    repository: FakeAcoRepository, board: BoardClient, listed: dict[str, Any]
) -> None:
    """ABRD-02, ABRD-70."""
    repository.set_rulings(row(12, "Song jump", option_line(card_hash="sha256:other")))

    answer = board.post_rule({**listed, "unclear": True})

    assert answer.json() == {"status": "failed", "message": LINE_CHANGED}
    assert repository.rule_calls() == []


@pytest.mark.parametrize("index", [1, 9], ids=["yes-no-line", "missing-line"])
def test_an_unclear_post_for_no_option_line_is_refused_as_changed(
    repository: FakeAcoRepository, board: BoardClient, index: int
) -> None:
    """ABRD-40."""
    repository.set_rulings(row(12, "Song jump", line(1, "Guests?", default="yes")))
    yes_no = _first_listed_line(board)

    answer = board.post_rule(
        {
            "repo": board.repo,
            "item": 12,
            "line": index,
            "fingerprint": yes_no["fingerprint"],
            "unclear": True,
        }
    )

    assert answer.json() == {"status": "failed", "message": LINE_CHANGED}
    assert repository.rule_calls() == []


def test_a_second_unclear_is_answered_failed_with_the_sentence_aco_gave(
    board: BoardClient, listed: dict[str, Any]
) -> None:
    """ABRD-70, E-ABRD-14."""
    board.post_rule({**listed, "unclear": True})
    again = board.post_rule({**listed, "unclear": True})

    assert (again.json()["status"], str(again.json()["message"])) == (
        "failed",
        "aco rule failed: line 1 is already with its head; it comes back once revised",
    )


@pytest.fixture
def github_world(github_clone: Path, bare_remote: Path) -> None:
    assert_github_world(github_clone, bare_remote)


@pytest.mark.usefixtures("github_world")
@pytest.mark.parametrize("note", ["-n first", "a\nb", 'say "hi" ä'])
def test_the_real_aco_rule_stores_what_the_board_sent(
    repository: FakeAcoRepository,
    board: BoardClient,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    note: str,
) -> None:
    """ABRD-70, RULE-22, RULE-23: the board's argv is lawful for the real command."""
    repository.set_rulings(
        row(7, "Karte", option_line(index=2, card_hash=GOLDEN_CARD_HASH, topic="Sprung"))
    )
    shown = _first_listed_line(board)
    board.post_rule(
        {
            "repo": board.repo,
            "item": 7,
            "line": 2,
            "fingerprint": shown["fingerprint"],
            "unclear": True,
            "note": f" {note} ",
        }
    )
    [sent] = repository.rule_calls()
    forge = serve_item(monkeypatch, item_body(card()))

    returned = run_cli(sent, capsys)

    assert returned.status == 0
    entry = body.block_expectation_dicts(body.locate_block(forge.item_bodies[7]).data)[1]
    assert (entry.get("ruling"), entry.get("via"), entry["returned_note"]) == (None, None, note)
    assert "returned_on" in entry
