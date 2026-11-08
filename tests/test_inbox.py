"""The per-repository read over the GitHub adapter's listing
(specs/serve.spec.md, ABRD-06): a card reaches the operator only from an item
a member of the repository wrote."""

import threading
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
from aco_board_fixtures import board_checkout
from board_fixtures import board_issue, complete_contract
from board_forge import ForgeOperation, item_body, run_context
from github_pages import (
    board_issue_page_client,
    raw_board_issue,
    rest_board_issue_page_client,
)
from option_cards import card, card_body, open_option_entry

from aco import body, forge, inbox, repositories, rulings, workboard

_CARD = card_body(card())


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
    labels: tuple[str, ...] = (workboard.NEEDS_OPERATOR_LABEL,),
    body_text: str | None = None,
    next_step: str = "Do the thing.",
    author_is_member: bool = True,
) -> workboard.Issue:
    text = complete_contract(next_step) if body_text is None else body_text
    return board_issue(
        number, f"Item {number}", text, labels=labels, author_is_member=author_is_member
    )


def test_a_labelled_member_item_is_a_step_with_its_number_title_and_next() -> None:
    issues = (_step_issue(9, next_step="Rotate the key."),)

    found = inbox.steps(issues, storage=body.Storage.GITHUB)

    assert found == (inbox.Step(9, "Item 9", "Rotate the key."),)


def test_the_label_matches_in_any_case() -> None:
    issues = (_step_issue(9, labels=("Needs-Operator",)),)

    found = inbox.steps(issues, storage=body.Storage.GITHUB)

    assert [step.number for step in found] == [9]


@pytest.mark.parametrize(
    "body_text",
    [
        pytest.param("Prose only, no block.", id="no-block"),
        pytest.param("```aco\nversion = \n```\n", id="malformed-block"),
    ],
)
def test_a_labelled_item_without_a_readable_block_is_a_step_with_no_text(body_text: str) -> None:
    issues = (_step_issue(9, body_text=body_text), _step_issue(8, next_step="Fine."))

    found = inbox.steps(issues, storage=body.Storage.GITHUB)

    assert [(step.number, step.next_step) for step in found] == [(9, None), (8, "Fine.")]


def test_only_a_labelled_item_a_member_wrote_and_the_store_could_read_is_a_step() -> None:
    unreadable = replace(_step_issue(6), unreadable=body.ContractDefect("body", "unreadable"))
    issues = (
        _step_issue(3, author_is_member=False),
        unreadable,
        _step_issue(4, labels=()),
        _step_issue(5, labels=("bug",)),
        _step_issue(7),
    )

    found = inbox.steps(issues, storage=body.Storage.GITHUB)

    assert [step.number for step in found] == [7]


def test_steps_come_by_descending_number() -> None:
    issues = (_step_issue(2), _step_issue(11), _step_issue(5))

    found = inbox.steps(issues, storage=body.Storage.GITHUB)

    assert [step.number for step in found] == [11, 5, 2]


def test_a_labelled_item_with_a_waiting_line_is_in_both_lists() -> None:
    carded = _step_issue(5, body_text=item_body(open_option_entry()))

    reading = inbox.read_issues((carded,), storage=body.Storage.GITHUB)

    assert [row.number for row in reading.rows] == [5]
    assert [step.number for step in reading.steps] == [5]


def test_the_answer_lists_steps_always_and_gives_an_unavailable_entry_none() -> None:
    discovery = repositories.Discovery(
        Path("/root"),
        (_repository("a/steps", Path("/a")), _repository("b/none", Path("/b"))),
        (),
    )
    step = inbox.Step(9, "Item 9", "Rotate the key.")

    def read_issues(repository: repositories.Repository) -> inbox.Reading:
        return inbox.Reading((), (step,) if repository.label == "a/steps" else ())

    answer = inbox.inbox_json(inbox.read(discovery, read_issues))

    repositories_read = cast("list[dict[str, Any]]", answer["repositories"])
    assert repositories_read[0]["steps"] == [
        {"number": 9, "title": "Item 9", "step": "Rotate the key."}
    ]
    assert repositories_read[1]["steps"] == []


def test_a_step_with_no_text_prints_as_null() -> None:
    step = inbox.Step(9, "Item 9", None)

    assert inbox.step_json(step) == {"number": 9, "title": "Item 9", "step": None}


def test_one_read_of_a_checkout_lists_its_open_items_once_for_its_rows_and_its_steps(
    tmp_path: Path, isolated_global_git_config: Path
) -> None:
    del isolated_global_git_config
    repository = board_checkout(tmp_path / "repository")
    repository.put_item(5, item_body(open_option_entry()), labels=[workboard.NEEDS_OPERATOR_LABEL])
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
