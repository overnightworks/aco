"""The steps waiting on the operator each repo carries in `GET /api/board`, over the
real `aco` read and a fake forge (specs/serve.spec.md, ABRD-157 to ABRD-159)."""

from datetime import date
from typing import Any, cast

from aco_board_fixtures import BoardClient
from board_fixtures import OPERATOR_WAIT, complete_contract
from board_forge import BoardForge

STEP_TABLE = {
    "purpose": "Release the build.",
    "actions": "open https://example.test/run\nclick Run",
    "expected": "The page shows green.",
}


def _repo(board: BoardClient) -> dict[str, Any]:
    [repo] = cast(list[dict[str, Any]], board.get_board_json().json()["repos"])
    return repo


def test_a_step_with_its_table_lists_purpose_actions_expected_and_no_answer(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-157."""
    repository.put_item(
        7,
        complete_contract("Run it.", wait=OPERATOR_WAIT, step=STEP_TABLE),
        title="Release",
    )

    assert _repo(board)["steps"] == [
        {
            "number": 7,
            "title": "Release",
            "step": OPERATOR_WAIT["operator"],
            **STEP_TABLE,
            "answer": None,
        }
    ]


def test_a_step_with_an_answer_lists_it(repository: BoardForge, board: BoardClient) -> None:
    """ABRD-157."""
    repository.put_item(
        7,
        complete_contract(
            "Run it.", wait=OPERATOR_WAIT, step={**STEP_TABLE, "answer": "the report"}
        ),
    )

    (step,) = _repo(board)["steps"]

    assert (step["number"], step["answer"]) == (7, "the report")


def test_an_old_step_lists_null_purpose_and_actions(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-157."""
    repository.put_item(
        8, complete_contract("Run it.", wait={"operator": "Old.", "since": date(2026, 8, 31)})
    )

    (step,) = _repo(board)["steps"]

    assert (step["number"], step["step"], step["purpose"], step["actions"]) == (
        8,
        "Old.",
        None,
        None,
    )


def test_a_step_of_a_non_member_is_not_listed(repository: BoardForge, board: BoardClient) -> None:
    """ABRD-158."""
    repository.put_item(
        7,
        complete_contract("Run it.", wait=OPERATOR_WAIT, step=STEP_TABLE),
        author_is_member=False,
    )

    assert _repo(board)["steps"] == []


def test_an_item_that_waits_on_nobody_lists_no_step(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-158."""
    repository.put_item(7, complete_contract("Run it."))

    assert _repo(board)["steps"] == []
