"""The progress each repo carries in `GET /api/board`, over the real `aco` read
and a fake forge (specs/serve.spec.md, ABRD-131 to ABRD-137)."""

from typing import Any, cast

from aco_board_fixtures import BoardClient, land_item
from board_fixtures import complete_contract, slice_entries
from board_forge import BoardForge, ForgeOperation, ForgeRequest, child_list

from aco import workboard
from aco.body import ItemKind


def _repo(board: BoardClient) -> dict[str, Any]:
    [repo] = cast(list[dict[str, Any]], board.get_board_json().json()["repos"])
    return repo


def test_a_repo_lists_closed_and_planned_per_top_level_container_and_for_itself(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-131, ABRD-132, E-ABRD-20."""
    repository.put_item(
        10,
        complete_contract("Build.", slice=slice_entries("S1", "S2")),
        title="Epic",
        kind=ItemKind.CONTAINER,
        children=child_list(closed=[1], open=[2, 3]),
    )
    repository.put_item(
        11,
        complete_contract("Build."),
        title="Nested",
        kind=ItemKind.CONTAINER,
        children=child_list(closed=[5, 6]),
        parent=10,
    )

    progress = _repo(board)["progress"]

    assert progress == {
        "error": None,
        "closed": 1,
        "landed": 0,
        "planned": 5,
        "open": 2,
        "uncut": 2,
        "percent": 20,
        "waiting": 0,
        "containers": [
            {
                "number": 10,
                "title": "Epic",
                "closed": 1,
                "landed": 0,
                "planned": 5,
                "open": 2,
                "uncut": 2,
                "percent": 20,
                "waiting": 0,
            }
        ],
    }


def test_a_repo_counts_the_items_that_wait_on_the_operator(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-133."""
    repository.put_item(7, complete_contract("Decide."), labels=[workboard.NEEDS_OPERATOR_LABEL])

    progress = _repo(board)["progress"]

    assert progress["waiting"] == 1


def test_a_failed_parent_read_shows_its_sentence_and_no_counts(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-134, E-ABRD-21."""
    repository.put_item(
        10, complete_contract("Build."), kind=ItemKind.CONTAINER, children=child_list(closed=[1])
    )
    repository.fail_parent_reads("GitHub is down")

    repo = _repo(board)

    assert (repo["error"], repo["progress"]) == (None, {"error": "GitHub is down"})


def test_a_failed_child_read_shows_its_sentence_and_no_counts(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-134."""
    repository.put_item(
        10, complete_contract("Build."), kind=ItemKind.CONTAINER, children=child_list(closed=[1])
    )
    repository.fail_child_reads("GitHub is down")

    repo = _repo(board)

    assert (repo["error"], repo["progress"]) == (None, {"error": "GitHub is down"})


def test_a_closed_child_a_trunk_commit_names_is_landed_apart_from_other_closes(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-136."""
    repository.put_item(
        10,
        complete_contract("Build."),
        kind=ItemKind.CONTAINER,
        children=child_list(closed=[1, 2, 3]),
    )
    land_item(repository, 1)
    land_item(repository, 2)

    progress = _repo(board)["progress"]

    assert (progress["closed"], progress["landed"]) == (3, 2)
    assert [(c["closed"], c["landed"]) for c in progress["containers"]] == [(3, 2)]


def test_a_container_lists_the_open_children_that_wait_on_the_operator(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-137."""
    repository.put_item(
        10, complete_contract("Build."), kind=ItemKind.CONTAINER, children=child_list(open=[7, 8])
    )
    repository.put_item(7, complete_contract("Decide."), labels=[workboard.NEEDS_OPERATOR_LABEL])
    repository.put_item(9, complete_contract("Decide."), labels=[workboard.NEEDS_OPERATOR_LABEL])

    progress = _repo(board)["progress"]

    assert progress["waiting"] == 2
    assert [c["waiting"] for c in progress["containers"]] == [1]


def test_a_read_asks_the_forge_for_the_listing_then_each_top_level_container_once(
    repository: BoardForge, board: BoardClient
) -> None:
    """E-ABRD-20."""
    repository.put_item(
        10, complete_contract("Build."), kind=ItemKind.CONTAINER, children=child_list(closed=[1])
    )
    repository.put_item(
        11,
        complete_contract("Build."),
        kind=ItemKind.CONTAINER,
        children=child_list(closed=[2]),
        parent=10,
    )

    _repo(board)

    assert sorted(
        repository.request_log(), key=lambda request: (request.operation.value, request.item or 0)
    ) == [
        ForgeRequest(ForgeOperation.LIST_CHILDREN, 10),
        ForgeRequest(ForgeOperation.LIST_OPEN_ISSUES),
        ForgeRequest(ForgeOperation.READ_PARENT, 10),
        ForgeRequest(ForgeOperation.READ_PARENT, 11),
    ]


def test_a_repo_without_containers_shows_no_planned_work(
    repository: BoardForge, board: BoardClient
) -> None:
    repository.put_item(7, complete_contract("Build."))

    progress = _repo(board)["progress"]

    assert (progress["planned"], progress["percent"], progress["containers"]) == (0, None, [])
