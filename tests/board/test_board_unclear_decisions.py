"""The board sends an option card back to its head (ABRD-09, ABRD-42, ABRD-70): the
post's shape and refusals, the exact `aco rule --unclear` it runs, and that real
`aco rule` accepts and stores that call."""

from __future__ import annotations

from typing import Any

import pytest
from aco_board_fixtures import BoardClient, FakeAcoRepository, first_listed_line, option_line, row
from cli_fixtures import run_cli
from option_cards import GOLDEN_CARD_HASH, card, item_body, serve_item

from aco import body

_NOTE = "Please show the jump on mobile too."


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
    shown = first_listed_line(board)
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
