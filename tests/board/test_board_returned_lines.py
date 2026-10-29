"""The board lists an open option line its head has been sent back as returned
(specs/serve.spec.md: ABRD-61, ABRD-62), driven through the real server, wire form and
`aco` adapter against the real `aco` over a fake forge."""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest
from aco_board_fixtures import BoardClient
from board_forge import BoardForge, item_body
from option_cards import open_option_entry

_RETURNED_ON = date(2026, 10, 27)


def _listed_line(board: BoardClient) -> dict[str, Any]:
    response = board.get_board_json()
    assert response.status == 200
    [repo] = cast(list[dict[str, Any]], response.json()["repos"])
    assert repo["error"] is None
    [item] = repo["items"]
    [listed] = item["lines"]
    return listed


def _returned_entry(note: str | None) -> dict[str, object]:
    note_key = {} if note is None else {"returned_note": note}
    return {**open_option_entry(), "returned_on": _RETURNED_ON, **note_key}


@pytest.mark.parametrize(
    "returned_note", [None, "Which jump do you mean?"], ids=["date-only", "date-and-note"]
)
def test_a_returned_open_line_is_listed_with_its_date_and_note(
    repository: BoardForge, board: BoardClient, returned_note: str | None
) -> None:
    repository.put_item(12, item_body(_returned_entry(returned_note)), title="Song jump")

    listed = _listed_line(board)

    assert (listed["returned_on"], listed["returned_note"]) == (
        _RETURNED_ON.isoformat(),
        returned_note,
    )
    assert listed["ruling"] is None


def test_a_returned_line_keeps_the_fingerprint_it_had_before_it_was_sent_back(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-02, ABRD-35: the returned keys are outside the shown card."""
    repository.put_item(12, item_body(open_option_entry()), title="Song jump")
    before = _listed_line(board)["fingerprint"]
    repository.put_item(12, item_body(_returned_entry("Why?")), title="Song jump")

    assert _listed_line(board)["fingerprint"] == before
