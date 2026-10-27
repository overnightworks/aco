"""The board lists an open option line its head has been sent back as returned
(specs/serve.spec.md: ABRD-61, ABRD-62, ABRD-07), driven through the real server, wire form
and `aco` adapter against a fake `aco` on PATH."""

from __future__ import annotations

from typing import Any, cast

import pytest
from aco_board_fixtures import BoardClient, FakeAcoRepository, option_line, row


def _listed_line(board: BoardClient) -> dict[str, Any]:
    response = board.get_board_json()
    assert response.status == 200
    [repo] = cast(list[dict[str, Any]], response.json()["repos"])
    assert repo["error"] is None
    [item] = repo["items"]
    [listed] = item["lines"]
    return listed


@pytest.mark.parametrize(
    ("returned_on", "returned_note"),
    [("2026-10-27", None), ("2026-10-27", "Which jump do you mean?")],
    ids=["date-only", "date-and-note"],
)
def test_a_returned_open_line_is_listed_with_its_date_and_note(
    repository: FakeAcoRepository,
    board: BoardClient,
    returned_on: str,
    returned_note: str | None,
) -> None:
    repository.set_rulings(
        row(12, "Song jump", option_line(returned_on=returned_on, returned_note=returned_note))
    )

    listed = _listed_line(board)

    assert (listed["returned_on"], listed["returned_note"]) == (returned_on, returned_note)
    assert listed["ruling"] is None


def test_a_returned_line_keeps_the_fingerprint_it_had_before_it_was_sent_back(
    repository: FakeAcoRepository, board: BoardClient
) -> None:
    """ABRD-02, ABRD-35: the returned keys are outside the shown card."""
    repository.set_rulings(row(12, "Song jump", option_line()))
    before = _listed_line(board)["fingerprint"]
    repository.set_rulings(
        row(12, "Song jump", option_line(returned_on="2026-10-27", returned_note="Why?"))
    )

    assert _listed_line(board)["fingerprint"] == before


@pytest.mark.parametrize(
    "stored",
    [
        option_line(returned_note="Which jump?"),
        option_line(returned_on="2026-10-27", returned_note=""),
        option_line(returned_on="2026-10-27", returned_note="  "),
        option_line(returned_on="2026-10-27", returned_note=5),
        option_line(returned_on="27.10.2026"),
        option_line(returned_on=20261027),
        option_line(ruling="A", returned_on="2026-10-27"),
        option_line(ruling="A", returned_note="Which jump?"),
        {key: value for key, value in option_line().items() if key != "returned_on"},
        {key: value for key, value in option_line().items() if key != "returned_note"},
    ],
    ids=[
        "note-without-date",
        "note-empty",
        "note-blank",
        "note-not-text",
        "date-not-iso",
        "date-not-text",
        "ruled-and-returned",
        "ruled-with-a-note",
        "date-key-missing",
        "note-key-missing",
    ],
)
def test_a_returned_pair_aco_refuses_makes_the_repository_unreadable(
    repository: FakeAcoRepository, board: BoardClient, stored: dict[str, object]
) -> None:
    repository.set_rulings(row(12, "Song jump", stored))

    response = board.get_board_json()

    [repo] = cast(list[dict[str, Any]], response.json()["repos"])
    assert repo["error"].startswith("aco rulings --json is unreadable: ")
    assert repo["items"] == []
