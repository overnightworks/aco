"""The per-repository read over the GitHub adapter's listing
(specs/serve.spec.md, ABRD-06): a card reaches the operator only from an item
a member of the repository wrote."""

import threading
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, cast, get_type_hints

import pytest
from aco_board_fixtures import board_checkout, land_item
from board_fixtures import board_issue, complete_contract
from board_forge import (
    BoardForge,
    ForgeOperation,
    ReleasedItem,
    StoredChild,
    child_list,
    item_body,
    run_context,
    seed_lane_records,
)
from cli_fixtures import real_git
from github_pages import (
    board_issue_page_client,
    raw_board_issue,
    rest_board_issue_page_client,
)
from option_cards import card, card_body, open_option_entry

from aco import body, forge, inbox, lane_measure, progress, repositories, rulings, workboard
from aco.board import board
from aco.body import ItemKind
from aco.lane_record import LaneOutcome, LaneRecord
from aco.routing_line import RoutingLine

_CARD = card_body(card())
_REPOSITORY = forge.RepositoryId("github.com", ("owner",), "repo")
_NO_CARD = {
    **dict.fromkeys(("purpose", "paste", "paste_kind", "expected", "actions", "answer")),
    "form": "old",
    "since": "2026-11-01",
    "url": "https://github.com/owner/repo/issues/9",
}


@pytest.mark.parametrize(
    ("association", "listed"),
    [
        pytest.param("OWNER", True, id="owner"),
        pytest.param("MEMBER", True, id="member"),
        pytest.param("COLLABORATOR", True, id="collaborator"),
        pytest.param("CONTRIBUTOR", False, id="contributor"),
        pytest.param("FIRST_TIME_CONTRIBUTOR", False, id="first-time-contributor"),
        pytest.param("FIRST_TIMER", False, id="first-timer"),
        pytest.param("MANNEQUIN", False, id="mannequin"),
        pytest.param("NONE", False, id="none"),
        pytest.param(None, False, id="null"),
        pytest.param(7, False, id="not-a-string"),
    ],
)
def test_an_item_is_listed_only_when_a_member_wrote_it(association: object, listed: bool) -> None:
    client = board_issue_page_client(
        raw_board_issue(number=5, body=_CARD, authorAssociation=association)
    )

    rows = inbox.rows(client.list_open_board_issues(), storage=body.Storage.GITHUB)

    assert [row.number for row in rows] == ([5] if listed else [])


def test_an_item_whose_listing_lacks_the_association_is_not_listed() -> None:
    without_association = raw_board_issue(number=5, body=_CARD)
    del without_association["authorAssociation"]
    client = board_issue_page_client(without_association)

    rows = inbox.rows(client.list_open_board_issues(), storage=body.Storage.GITHUB)

    assert rows == ()


@pytest.mark.parametrize(
    ("rest_association", "listed"),
    [
        pytest.param("OWNER", True, id="owner"),
        pytest.param("CONTRIBUTOR", False, id="contributor"),
        pytest.param(None, False, id="null"),
    ],
)
def test_a_rest_issue_is_listed_by_its_author_association(
    rest_association: str | None, listed: bool
) -> None:
    rest_issue = {
        "number": 5,
        "title": "Title",
        "labels": [],
        "body": _CARD,
        "created_at": "2026-08-20T00:00:00Z",
        "updated_at": "2026-08-20T00:00:00Z",
        "author_association": rest_association,
    }
    client = rest_board_issue_page_client(rest_issue)

    rows = inbox.rows(client.list_open_board_issues(), storage=body.Storage.GITHUB)

    assert [row.number for row in rows] == ([5] if listed else [])


def _read_rows(*entries: dict[str, object]) -> tuple[rulings.Row, ...]:
    issue = board_issue(5, "Item", item_body(*entries))
    return inbox.rows((issue,), storage=body.Storage.GITHUB)


_RULED = {**open_option_entry(), "ruling": "A", "ruled_on": date(2026, 10, 28), "via": "board"}
_RETURNED = {**open_option_entry(), "returned_on": date(2026, 10, 1)}
_WITHDRAWN = {"text": "Taken back.", "withdrawn_on": date(2026, 10, 2)}
_YES_NO = {"text": "A plain expectation."}


@pytest.mark.parametrize(
    ("entries", "waiting_indexes"),
    [
        pytest.param([open_option_entry()], [1], id="open"),
        pytest.param([_RULED], [], id="ruled"),
        pytest.param([_RETURNED], [], id="returned"),
        pytest.param([_WITHDRAWN], [], id="withdrawn"),
        pytest.param([_YES_NO], [], id="yes-no"),
        pytest.param(
            [_RULED, open_option_entry(), _RETURNED, _WITHDRAWN, open_option_entry()],
            [2, 5],
            id="mixed-keeps-only-the-open-lines",
        ),
    ],
)
def test_only_an_open_option_line_waits_on_the_operator(
    entries: list[dict[str, object]], waiting_indexes: list[int]
) -> None:
    waiting = inbox.waiting_rows(_read_rows(*entries))

    assert [line.index for row in waiting for line in row.lines] == waiting_indexes
    assert [row.number for row in waiting] == ([5] if waiting_indexes else [])


def _repository(label: str, directory: Path) -> repositories.Repository:
    return repositories.Repository(label, directory)


def test_the_read_lists_each_repository_in_discovery_order_and_names_the_failed_ones(
    tmp_path: Path,
) -> None:
    good = _repository("a/good", tmp_path / "good")
    broken = _repository("b/broken", tmp_path / "broken")
    unreadable = _repository("c/unreadable", tmp_path / "unreadable")
    unscanned = repositories.UnavailableCheckout(tmp_path / "locked", "Permission denied")
    discovery = repositories.Discovery(tmp_path, (good, broken, unreadable), (unscanned,))

    def read_issues(repository: repositories.Repository) -> inbox.Reading:
        if repository is broken:
            raise forge.ForgeError("listing failed")
        if repository is unreadable:
            raise PermissionError("no access")
        return inbox.Reading(_read_rows(open_option_entry(), _RULED), ())

    answer = inbox.inbox_json(inbox.read(discovery, read_issues))

    repositories_read = cast("list[dict[str, Any]]", answer["repositories"])
    assert answer["root"] == str(tmp_path)
    assert [entry["repository"] for entry in repositories_read] == [
        "a/good",
        "b/broken",
        "c/unreadable",
    ]
    assert [line["index"] for line in repositories_read[0]["items"][0]["lines"]] == [1]
    assert repositories_read[0]["steps"] == []
    assert repositories_read[1] == {"repository": "b/broken", "unavailable": "listing failed"}
    assert repositories_read[2] == {"repository": "c/unreadable", "unavailable": "no access"}
    assert answer["unreadable"] == [
        {"directory": str(tmp_path / "locked"), "reason": "Permission denied"}
    ]


def _discovery_with_unavailable(
    tmp_path: Path, *unavailable: repositories.UnavailableCheckout
) -> repositories.Discovery:
    return repositories.Discovery(
        tmp_path, (_repository("owner/kept", tmp_path / "kept"),), tuple(unavailable)
    )


@pytest.mark.parametrize(
    "unavailable",
    [
        pytest.param(
            repositories.UnavailableCheckout(Path("broken"), "cannot be read", "owner/other"),
            id="another-label",
        ),
        pytest.param(repositories.UnavailableCheckout(Path("broken"), "no remote"), id="no-label"),
    ],
)
def test_a_label_no_unavailable_checkout_carries_keeps_the_not_found_refusal(
    tmp_path: Path, unavailable: repositories.UnavailableCheckout
) -> None:
    discovery = _discovery_with_unavailable(tmp_path, unavailable)

    with pytest.raises(inbox.RepositoryNotFoundError) as refusal:
        inbox.context_in_checkout_of(discovery, "owner/broken")

    assert str(refusal.value) == "no repository owner/broken found"


def test_the_repositories_are_read_concurrently_and_listed_in_discovery_order(
    tmp_path: Path,
) -> None:
    labels = ["a/first", "b/second", "c/third"]
    discovery = repositories.Discovery(
        tmp_path, tuple(_repository(label, tmp_path / label) for label in labels), ()
    )
    every_read_has_started = threading.Barrier(len(labels), timeout=10)

    def read_issues(_repository: repositories.Repository) -> inbox.Reading:
        every_read_has_started.wait()
        return inbox.Reading((), ())

    answer = inbox.inbox_json(inbox.read(discovery, read_issues))

    repositories_read = cast("list[dict[str, Any]]", answer["repositories"])
    assert [entry["repository"] for entry in repositories_read] == labels


def test_the_read_of_a_root_holding_only_unreadable_directories_lists_no_repository(
    tmp_path: Path,
) -> None:
    unscanned = repositories.UnavailableCheckout(tmp_path / "locked", "Permission denied")
    discovery = repositories.Discovery(tmp_path, (), (unscanned,))

    answer = inbox.inbox_json(inbox.read(discovery, lambda _repository: inbox.Reading((), ())))

    assert answer["repositories"] == []


def _step_issue(
    number: int,
    *,
    labels: tuple[str, ...] = (),
    body_text: str | None = None,
    wait: dict[str, object] | None = None,
    author_is_member: bool = True,
) -> workboard.Issue:
    operator_wait = (
        {"operator": "Do the thing.", "since": date(2026, 11, 1)} if wait is None else wait
    )
    text = complete_contract("Work.", wait=operator_wait) if body_text is None else body_text
    return board_issue(
        number, f"Item {number}", text, labels=labels, author_is_member=author_is_member
    )


def test_a_members_item_with_an_operator_wait_is_a_step_without_the_label() -> None:
    issues = (_step_issue(9, wait={"operator": "Rotate the key.", "since": date(2026, 11, 1)}),)

    found = inbox.steps(issues, repository=_REPOSITORY, storage=body.Storage.GITHUB)

    assert found == (
        inbox.Step(
            9,
            "Item 9",
            "Rotate the key.",
            date(2026, 11, 1),
            url="https://github.com/owner/repo/issues/9",
        ),
    )


def test_a_labelled_item_without_an_operator_wait_is_no_step() -> None:
    labelled = (workboard.NEEDS_OPERATOR_LABEL,)
    trigger = {"trigger": "A second machine.", "since": date(2026, 11, 1)}
    issues = (
        _step_issue(5, labels=labelled, body_text=complete_contract("Work.")),
        _step_issue(6, labels=labelled, wait=trigger),
        _step_issue(7, labels=labelled, body_text="Prose only, no block."),
    )

    found = inbox.steps(issues, repository=_REPOSITORY, storage=body.Storage.GITHUB)

    assert found == ()


def test_a_steps_text_is_its_operator_wait_not_the_blocks_next() -> None:
    wait = {"operator": "Rotate the key.", "since": date(2026, 11, 1)}
    issues = (_step_issue(9, body_text=complete_contract("Cut the slice.", wait=wait)),)

    [found] = inbox.steps(issues, repository=_REPOSITORY, storage=body.Storage.GITHUB)

    assert found.wait_text == "Rotate the key."


_PASTE = {"purpose": "Why.", "paste": "make rotate", "expected": "See that."}
_OLD_TABLE = {"purpose": "Why.", "actions": "Do\nthis.", "expected": "See that.", "answer": "Say."}
_LONG_STEP = " ".join(["word"] * 16)


def _listed(table: dict[str, object] | None, step: str = "Rotate.") -> dict[str, object]:
    """What `step_json` lists for an item whose operator `wait` is `step` and whose block
    holds `table`."""
    wait = {"operator": step, "since": date(2026, 11, 1)}
    fields: dict[str, Any] = {} if table is None else {"step": table}
    issues = (_step_issue(9, body_text=complete_contract("Work.", wait=wait, **fields)),)
    [found] = inbox.steps(issues, repository=_REPOSITORY, storage=body.Storage.GITHUB)
    return inbox.step_json(found)


@pytest.mark.parametrize(
    ("table", "step", "listed"),
    [
        pytest.param(
            _PASTE,
            "Rotate.",
            {**_NO_CARD, **_PASTE, "form": "paste", "paste_kind": "command"},
            id="command",
        ),
        pytest.param(
            {**_PASTE, "paste": "https://example.test/run"},
            "Rotate.",
            {**_NO_CARD, **_PASTE, "paste": "https://example.test/run", "form": "paste"}
            | {"paste_kind": "link"},
            id="link",
        ),
        pytest.param(
            {**_PASTE, "paste": "make a; make b"},
            "Rotate.",
            {**_NO_CARD, **_PASTE, "paste": "make a; make b", "form": "old"},
            id="stored-paste-breaking-a-rule",
        ),
        pytest.param(
            {**_PASTE, "paste": "javascript://x"},
            "Rotate.",
            {**_NO_CARD, **_PASTE, "paste": "javascript://x", "form": "old"},
            id="stored-paste-with-a-foreign-scheme",
        ),
        pytest.param(
            _PASTE,
            _LONG_STEP,
            {**_NO_CARD, **_PASTE, "form": "old"},
            id="stored-step-line-breaking-a-rule",
        ),
        pytest.param(
            _OLD_TABLE,
            "Rotate.",
            {**_NO_CARD, **_OLD_TABLE, "form": "old"},
            id="actions-with-answer",
        ),
        pytest.param(None, "Rotate.", {**_NO_CARD, "form": "old"}, id="no-table"),
    ],
)
def test_a_step_is_of_the_paste_form_only_when_its_card_keeps_the_rules(
    table: dict[str, object] | None, step: str, listed: dict[str, object]
) -> None:
    """Spec: MCP-39, MCP-68, MCP-89, MCP-94"""
    assert _listed(table, step) == {**listed, "number": 9, "title": "Item 9", "step": step}


def test_only_an_item_a_member_wrote_and_the_store_could_read_is_a_step() -> None:
    unreadable = replace(_step_issue(6), unreadable=body.ContractDefect("body", "unreadable"))
    issues = (
        _step_issue(3, author_is_member=False),
        unreadable,
        _step_issue(4, body_text=complete_contract("Work.")),
        _step_issue(7),
    )

    found = inbox.steps(issues, repository=_REPOSITORY, storage=body.Storage.GITHUB)

    assert [step.number for step in found] == [7]


@pytest.mark.parametrize(
    ("waiting_since", "ordered"),
    [
        pytest.param({2: 3, 11: 1, 5: 2}, [2, 5, 11], id="the-newer-since-comes-first"),
        pytest.param({2: 1, 11: 1, 5: 1}, [11, 5, 2], id="equal-since-falls-back-to-the-number"),
        pytest.param({2: 2, 11: 1, 5: 2}, [5, 2, 11], id="ties-break-by-the-higher-number"),
    ],
)
def test_steps_come_newest_since_first_then_by_descending_number(
    waiting_since: dict[int, int], ordered: list[int]
) -> None:
    """Spec: MCP-43"""
    issues = tuple(
        _step_issue(number, wait={"operator": "Rotate.", "since": date(2026, 11, day)})
        for number, day in waiting_since.items()
    )

    found = inbox.steps(issues, repository=_REPOSITORY, storage=body.Storage.GITHUB)

    assert [step.number for step in found] == ordered


@pytest.mark.parametrize(
    ("storage", "url"),
    [
        pytest.param(body.Storage.GITHUB, "https://github.com/owner/repo/issues/9", id="github"),
        pytest.param(body.Storage.STATE_REF, None, id="state-ref"),
    ],
)
def test_a_steps_url_is_its_items_page_and_none_without_item_pages(
    storage: body.Storage, url: str | None
) -> None:
    """Spec: MCP-94"""
    [found] = inbox.steps((_step_issue(9),), repository=_REPOSITORY, storage=storage)

    assert found.url == url


def test_an_item_with_an_operator_wait_and_a_waiting_line_is_in_both_lists() -> None:
    wait = {"operator": "Rotate.", "since": date(2026, 11, 1)}
    carded = _step_issue(
        5, body_text=complete_contract("Work.", wait=wait, expectation=[open_option_entry()])
    )

    reading = inbox.read_issues((carded,), repository=_REPOSITORY, storage=body.Storage.GITHUB)

    assert [row.number for row in reading.rows] == [5]
    assert [step.number for step in reading.steps] == [5]


def test_the_answer_lists_steps_always_and_gives_an_unavailable_entry_none() -> None:
    discovery = repositories.Discovery(
        Path("/root"),
        (_repository("a/steps", Path("/a")), _repository("b/none", Path("/b"))),
        (),
    )
    step = inbox.Step(
        9,
        "Item 9",
        "Rotate the key.",
        date(2026, 11, 1),
        url="https://github.com/owner/repo/issues/9",
    )

    def read_issues(repository: repositories.Repository) -> inbox.Reading:
        return inbox.Reading((), (step,) if repository.label == "a/steps" else ())

    answer = inbox.inbox_json(inbox.read(discovery, read_issues))

    repositories_read = cast("list[dict[str, Any]]", answer["repositories"])
    assert repositories_read[0]["steps"] == [
        {**_NO_CARD, "number": 9, "title": "Item 9", "step": "Rotate the key."}
    ]
    assert repositories_read[1]["steps"] == []


def test_one_read_of_a_checkout_lists_its_open_items_once_for_its_rows_and_its_steps(
    tmp_path: Path, isolated_global_git_config: Path
) -> None:
    del isolated_global_git_config
    repository = board_checkout(tmp_path / "repository")
    wait = {"operator": "Rotate.", "since": date(2026, 11, 1)}
    waiting_body = complete_contract("Work.", wait=wait, expectation=[open_option_entry()])
    repository.put_item(5, waiting_body)
    context = run_context(None).for_directory(repository.directory)

    reading = inbox.read_context(context)

    assert ([row.number for row in reading.rows], [step.number for step in reading.steps]) == (
        [5],
        [5],
    )
    listings = [
        request
        for request in repository.request_log()
        if request.operation is ForgeOperation.LIST_OPEN_ISSUES
    ]
    assert len(listings) == 1


def _repository_with_a_container(tmp_path: Path) -> BoardForge:
    repository = board_checkout(tmp_path / "repository")
    repository.put_item(
        10,
        complete_contract("Build."),
        kind=ItemKind.CONTAINER,
        children=child_list(closed=[11, 12]),
    )
    return repository


def _progress_read(repository: BoardForge) -> inbox.Reading:
    context = run_context(None).for_directory(repository.directory)
    return inbox.read_context(context, with_progress=True)


def test_a_closed_child_a_trunk_commit_names_is_landed_in_the_progress_read(
    tmp_path: Path, isolated_global_git_config: Path
) -> None:
    del isolated_global_git_config
    repository = _repository_with_a_container(tmp_path)
    land_item(repository, 11)

    shown = _progress_read(repository).progress

    assert isinstance(shown, progress.Progress)
    assert (shown.closed, shown.landed) == (2, 1)


def test_an_unreadable_trunk_leaves_the_progress_unknown_and_the_items_listed(
    tmp_path: Path, isolated_global_git_config: Path
) -> None:
    del isolated_global_git_config
    repository = _repository_with_a_container(tmp_path)
    repository.put_item(5, item_body(open_option_entry()))
    real_git(repository.directory, "branch", "--move", "renamed")

    reading = _progress_read(repository)

    assert isinstance(reading.progress, progress.ProgressUnavailable)
    assert [row.number for row in reading.rows] == [5]


def _finished_items(*wall_seconds: int) -> list[ReleasedItem]:
    return [
        ReleasedItem(
            number, LaneRecord(LaneOutcome.LANDED, wall_seconds=seconds), 1_700_000_000 + number
        )
        for number, seconds in enumerate(wall_seconds, start=1)
    ]


def _container_estimate(repository: BoardForge) -> object:
    shown = _progress_read(repository).progress
    assert isinstance(shown, progress.Progress)
    [container] = shown.containers
    return container.estimate


def test_the_progress_read_prices_the_lanes_left_from_the_state_ref_lane_records(
    tmp_path: Path, isolated_global_git_config: Path
) -> None:
    """Spec: ABRD-141."""
    del isolated_global_git_config
    repository = board_checkout(tmp_path / "repository")
    repository.put_item(
        10,
        complete_contract("Build."),
        kind=ItemKind.CONTAINER,
        children=child_list(open=[7, 8]),
    )
    seed_lane_records(repository, _finished_items(100, 200, 300, 400, 500))

    estimate = _container_estimate(repository)

    assert estimate == lane_measure.RemainingWork(
        low_seconds=600,
        high_seconds=800,
        items=5,
        classes=(lane_measure.PricedClass(None, 2, lane_measure.Basis.POOLED, 5),),
    )


def test_the_progress_read_gives_each_closed_child_its_title_and_lane_actuals(
    tmp_path: Path, isolated_global_git_config: Path
) -> None:
    """Spec: ABRD-147, ABRD-148, ABRD-149."""
    del isolated_global_git_config
    repository = board_checkout(tmp_path / "repository")
    repository.put_item(
        10,
        complete_contract("Build."),
        kind=ItemKind.CONTAINER,
        children=[StoredChild(1, True, "Recorded"), StoredChild(2, True, "Unrecorded")],
    )
    routing = RoutingLine(stages={}, fix_rounds=2, blocking=None, experiment=None)
    record = LaneRecord(LaneOutcome.LANDED, wall_seconds=90, routing=routing)
    seed_lane_records(repository, [ReleasedItem(1, record, 1_700_000_001)])

    shown = _progress_read(repository).progress

    assert isinstance(shown, progress.Progress)
    [container] = shown.containers
    assert container.closed_children == (
        progress.ClosedChild(1, "Recorded", lane_measure.ItemActuals(90, 2)),
        progress.ClosedChild(2, "Unrecorded", None),
    )


def test_an_unreadable_state_ref_leaves_the_closed_children_actuals_unknown(
    tmp_path: Path, isolated_global_git_config: Path
) -> None:
    """Spec: ABRD-150."""
    del isolated_global_git_config
    repository = board_checkout(tmp_path / "repository")
    repository.put_item(
        10, complete_contract("Build."), kind=ItemKind.CONTAINER, children=child_list(closed=[1])
    )

    shown = _progress_read(repository).progress

    assert isinstance(shown, progress.Progress)
    [container] = shown.containers
    assert [child.actuals for child in container.closed_children] == [
        lane_measure.ItemActuals(None, None)
    ]


def test_a_state_ref_without_lane_records_leaves_the_range_unknown_by_name(
    tmp_path: Path, isolated_global_git_config: Path
) -> None:
    """Spec: ABRD-144."""
    del isolated_global_git_config
    repository = board_checkout(tmp_path / "repository")
    repository.put_item(
        10, complete_contract("Build."), kind=ItemKind.CONTAINER, children=child_list(open=[7])
    )
    seed_lane_records(repository, [])

    estimate = _container_estimate(repository)

    assert estimate is lane_measure.NoRange.NO_RECORDS


def test_an_unreadable_state_ref_leaves_only_the_range_unknown_and_the_counts_shown(
    tmp_path: Path, isolated_global_git_config: Path
) -> None:
    """Spec: ABRD-144."""
    del isolated_global_git_config
    repository = board_checkout(tmp_path / "repository")
    repository.put_item(
        10,
        complete_contract("Build."),
        kind=ItemKind.CONTAINER,
        children=child_list(closed=[1], open=[7]),
    )

    shown = _progress_read(repository).progress

    assert isinstance(shown, progress.Progress)
    assert [(c.estimate, c.closed, c.open) for c in shown.containers] == [
        (lane_measure.NoRange.UNREADABLE, 1, 1)
    ]


def test_a_read_without_progress_reads_neither_the_sub_issues_nor_the_trunk(
    tmp_path: Path, isolated_global_git_config: Path
) -> None:
    del isolated_global_git_config
    repository = _repository_with_a_container(tmp_path)
    real_git(repository.directory, "branch", "--move", "renamed")
    context = run_context(None).for_directory(repository.directory)

    reading = inbox.read_context(context)

    assert reading.progress is None
    assert ForgeOperation.LIST_CHILDREN not in {
        request.operation for request in repository.request_log()
    }


@pytest.mark.parametrize("record", [inbox.Reading, board.RepoSnapshot])
def test_record_annotations_resolve_at_runtime(record: type) -> None:
    assert "progress" in get_type_hints(record)


def test_a_nested_container_is_no_top_level_container_in_the_progress_read(
    tmp_path: Path, isolated_global_git_config: Path
) -> None:
    """ABRD-194."""
    del isolated_global_git_config
    repository = _repository_with_a_container(tmp_path)
    repository.put_item(
        20,
        complete_contract("Build."),
        kind=ItemKind.CONTAINER,
        children=child_list(closed=[21]),
        parent=10,
    )

    shown = _progress_read(repository).progress

    assert isinstance(shown, progress.Progress)
    assert [container.number for container in shown.containers] == [10]
