"""The steps waiting on the operator each repo carries in `GET /api/board`, over the
real `aco` read and a fake forge (specs/serve.spec.md, ABRD-157 to ABRD-159)."""

from datetime import date
from typing import Any, cast

import pytest
from aco_board_fixtures import BoardClient, serving_two
from board_fixtures import OPERATOR_WAIT, complete_contract
from board_forge import BoardForge

STEP_TABLE = {
    "purpose": "Release the build.",
    "paste": "make release",
    "expected": "The page shows green.",
}
OLD_STEP_TABLE = {
    "purpose": "Release the build.",
    "actions": "open https://example.test/run\nclick Run",
    "expected": "The page shows green.",
}


def _repo(board: BoardClient) -> dict[str, Any]:
    [repo] = cast(list[dict[str, Any]], board.get_board_json().json()["repos"])
    return repo


@pytest.mark.parametrize(
    ("table", "listed"),
    [
        pytest.param(
            STEP_TABLE,
            {**STEP_TABLE, "form": "paste", "paste_kind": "command", "actions": None},
            id="command",
        ),
        pytest.param(
            {**STEP_TABLE, "paste": "https://example.test/run"},
            {
                **STEP_TABLE,
                "paste": "https://example.test/run",
                "form": "paste",
                "paste_kind": "link",
                "actions": None,
            },
            id="link",
        ),
        pytest.param(
            {**STEP_TABLE, "paste": "make a; make b"},
            {
                **STEP_TABLE,
                "paste": "make a; make b",
                "form": "old",
                "paste_kind": None,
                "actions": None,
            },
            id="stored-paste-breaking-a-rule",
        ),
        pytest.param(
            OLD_STEP_TABLE,
            {**OLD_STEP_TABLE, "form": "old", "paste": None, "paste_kind": None},
            id="actions",
        ),
    ],
)
def test_a_step_with_its_table_lists_its_form_and_every_stored_field(
    repository: BoardForge, board: BoardClient, table: dict[str, str], listed: dict[str, object]
) -> None:
    """Spec: ABRD-157"""
    repository.put_item(
        7, complete_contract("Run it.", wait=OPERATOR_WAIT, step=table), title="Release"
    )

    (step,) = _repo(board)["steps"]

    del step["fingerprint"]
    assert step == {
        "number": 7,
        "title": "Release",
        "step": OPERATOR_WAIT["operator"],
        "answer": None,
        **listed,
    }


def test_a_step_lists_a_fingerprint_that_follows_its_text_and_every_field_of_its_card(
    repository: BoardForge, board: BoardClient
) -> None:
    """Spec: ABRD-163"""
    variants = [
        (OPERATOR_WAIT, STEP_TABLE),
        ({**OPERATOR_WAIT, "operator": "Another."}, STEP_TABLE),
        *((OPERATOR_WAIT, {**STEP_TABLE, key: "Other."}) for key in STEP_TABLE),
        (OPERATOR_WAIT, OLD_STEP_TABLE),
        (OPERATOR_WAIT, {**OLD_STEP_TABLE, "answer": "the report"}),
    ]
    fingerprints: list[str] = []
    for wait, table in variants:
        repository.put_item(7, complete_contract("Run it.", wait=wait, step=table))
        fingerprints.append(board.listed_step(7)["fingerprint"])

    assert len(set(fingerprints)) == len(variants)


def test_a_step_listed_again_unchanged_keeps_its_fingerprint(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-163."""
    repository.put_item(7, complete_contract("Run it.", wait=OPERATOR_WAIT, step=STEP_TABLE))

    first = board.listed_step(7)["fingerprint"]

    assert board.listed_step(7)["fingerprint"] == first


def test_a_step_with_an_answer_lists_it(repository: BoardForge, board: BoardClient) -> None:
    """ABRD-157."""
    repository.put_item(
        7,
        complete_contract(
            "Run it.", wait=OPERATOR_WAIT, step={**OLD_STEP_TABLE, "answer": "the report"}
        ),
    )

    (step,) = _repo(board)["steps"]

    assert (step["number"], step["answer"]) == (7, "the report")


def test_a_step_without_a_table_lists_null_purpose_and_actions_and_the_old_form(
    repository: BoardForge, board: BoardClient
) -> None:
    """Spec: ABRD-157"""
    repository.put_item(
        8, complete_contract("Run it.", wait={"operator": "Old.", "since": date(2026, 8, 31)})
    )

    (step,) = _repo(board)["steps"]

    assert (step["number"], step["step"], step["purpose"], step["actions"], step["form"]) == (
        8,
        "Old.",
        None,
        None,
        "old",
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


def test_a_step_identical_in_two_repos_lists_a_fingerprint_for_each(
    two_repositories: tuple[BoardForge, BoardForge],
) -> None:
    """ABRD-163."""
    for repository in two_repositories:
        repository.put_item(7, complete_contract("Run it.", wait=OPERATOR_WAIT, step=STEP_TABLE))

    with serving_two(two_repositories) as board:
        fingerprints = {board.listed_step(7, repo)["fingerprint"] for repo in ("a", "b")}

    assert len(fingerprints) == 2
