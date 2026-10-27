"""The board sends an option card back to its head (ABRD-09, ABRD-42, ABRD-70): the
post's shape, its `returned` answer (ABRD-71) and refusals, and the exact
`aco rule --unclear` it runs."""

from __future__ import annotations

from typing import Any

import pytest
from aco_board_fixtures import BoardClient, FakeAcoRepository, option_line

_NOTE = "Please show the jump on mobile too."


def test_an_unclear_post_leaves_the_line_open_with_its_head_and_the_trimmed_note(
    repository: FakeAcoRepository, board: BoardClient, listed: dict[str, Any]
) -> None:
    """ABRD-70, ABRD-71."""
    answer = board.post_rule({**listed, "unclear": True, "note": f"  {_NOTE}\n"})

    assert answer.json() == {"status": "returned", "message": None}
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
