"""The progress each repo carries in `GET /api/board`, over the real `aco` read
and a fake forge (specs/serve.spec.md, ABRD-131 to ABRD-137)."""

from typing import Any, cast

from aco_board_fixtures import BoardClient
from board_fixtures import complete_contract, slice_entries
from board_forge import (
    BoardForge,
    ForgeOperation,
    ForgeRequest,
    ReleasedItem,
    StoredChild,
    child_list,
    seed_lane_records,
)

from aco import workboard
from aco.body import ItemKind
from aco.lane_record import LaneOutcome, LaneRecord
from aco.routing_line import RoutingLine


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
                "lanes_left": 4,
                "estimate": {"error": "lane records unreadable"},
                "closed_children": [
                    {
                        "number": 1,
                        "title": "Child 1",
                        "wall_seconds": None,
                        "fix_rounds": None,
                        "recorded": True,
                    }
                ],
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


def _finished(number: int, wall_seconds: int) -> ReleasedItem:
    record = LaneRecord(LaneOutcome.LANDED, wall_seconds=wall_seconds, item_size=None)
    return ReleasedItem(number, record, 1_700_000_000 + number)


def test_a_container_shows_its_lanes_left_and_the_range_in_seconds_with_its_samples(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-140, ABRD-141, ABRD-144."""
    repository.put_item(
        10,
        complete_contract("Build.", slice=slice_entries("S1")),
        kind=ItemKind.CONTAINER,
        children=child_list(closed=[1], open=[2, 3]),
    )
    repository.put_item(3, complete_contract("Decide."), labels=[workboard.NEEDS_OPERATOR_LABEL])
    seed_lane_records(repository, [_finished(n, 100 * n) for n in range(1, 7)])

    [container] = _repo(board)["progress"]["containers"]

    assert (container["lanes_left"], container["waiting"], container["estimate"]) == (
        2,
        1,
        {
            "error": None,
            "low_seconds": 700,
            "high_seconds": 1000,
            "samples": 6,
            "classes": [{"size": None, "lanes": 2, "basis": "pooled", "samples": 6}],
        },
    )


def test_a_container_with_no_lane_left_carries_no_estimate(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-140."""
    repository.put_item(
        10, complete_contract("Build."), kind=ItemKind.CONTAINER, children=child_list(closed=[1])
    )

    [container] = _repo(board)["progress"]["containers"]

    assert (container["lanes_left"], container["estimate"]) == (0, None)


def test_a_container_lists_its_closed_children_with_title_and_actuals_in_seconds(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-147, ABRD-148, ABRD-149."""
    repository.put_item(
        10,
        complete_contract("Build."),
        kind=ItemKind.CONTAINER,
        children=[StoredChild(2, True, "Second"), StoredChild(1, True, "First")],
    )
    routing = RoutingLine(stages={}, fix_rounds=3, blocking=None, experiment=None)
    record = LaneRecord(LaneOutcome.LANDED, wall_seconds=5400, routing=routing)
    seed_lane_records(repository, [ReleasedItem(1, record, 1_700_000_001)])

    [container] = _repo(board)["progress"]["containers"]

    assert container["closed_children"] == [
        {"number": 1, "title": "First", "wall_seconds": 5400, "fix_rounds": 3, "recorded": True},
        {
            "number": 2,
            "title": "Second",
            "wall_seconds": None,
            "fix_rounds": None,
            "recorded": False,
        },
    ]
