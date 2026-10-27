"""The decision board skips a withdrawn line and keeps reading the rest
(specs/serve.spec.md: ABRD-07, ABRD-60), driven through the real server, wire
form and `aco` adapter against a fake `aco` on PATH."""

from __future__ import annotations

from typing import Any, cast

import pytest
from aco_board_fixtures import BoardClient, FakeAcoRepository, line, row


def _withdrawn(index: int, **keys: object) -> dict[str, object]:
    return {"index": index, "form": "withdrawn", "ruling": None, **keys}


def _board_repo(board: BoardClient) -> dict[str, Any]:
    response = board.get_board_json()
    assert response.status == 200
    [repo] = cast(list[dict[str, Any]], response.json()["repos"])
    return repo


def test_a_withdrawn_line_is_skipped_and_its_neighbours_keep_their_indexes(
    repository: FakeAcoRepository, board: BoardClient
) -> None:
    repository.set_rulings(
        row(
            12,
            "Song jump",
            line(1, "Guests?", default="yes"),
            _withdrawn(2, text=7, unknown={"nested": True}),
            line(3, "Share page?", ruling="yes"),
        )
    )

    repo = _board_repo(board)

    assert repo["error"] is None
    [item] = repo["items"]
    assert [(entry["index"], entry["text"]) for entry in item["lines"]] == [
        (1, "Guests?"),
        (3, "Share page?"),
    ]


def test_an_item_with_only_withdrawn_lines_is_absent(
    repository: FakeAcoRepository, board: BoardClient
) -> None:
    repository.set_rulings(
        row(12, "Song jump", _withdrawn(1)),
        row(42, "Share page", line(1, "Guests?", default="yes")),
    )

    repo = _board_repo(board)

    assert repo["error"] is None
    assert [item["number"] for item in repo["items"]] == [42]


@pytest.mark.parametrize("form", ["Withdrawn", "cards", None], ids=["case", "other", "null"])
def test_any_other_unknown_form_still_makes_the_repository_unreadable(
    repository: FakeAcoRepository, board: BoardClient, form: object
) -> None:
    """ABRD-07."""
    repository.set_rulings(row(12, "Song jump", _withdrawn(1, form=form)))

    response = board.get_board_json()

    [repo] = cast(list[dict[str, Any]], response.json()["repos"])
    assert response.status == 502
    assert repo["error"] == "aco rulings --json is unreadable: #12 line has an unknown form"
    assert repo["items"] == []
