"""The per-repository read over the GitHub adapter's listing
(specs/serve.spec.md, ABRD-06): a card reaches the operator only from an item
a member of the repository wrote."""

from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
from board_fixtures import board_issue
from board_forge import item_body
from github_pages import (
    board_issue_page_client,
    raw_board_issue,
    rest_board_issue_page_client,
)
from option_cards import card, card_body, open_option_entry

from aco import body, forge, inbox, repositories, rulings

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

    def read_rows(repository: repositories.Repository) -> tuple[rulings.Row, ...]:
        if repository is broken:
            raise forge.ForgeError("listing failed")
        if repository is unreadable:
            raise PermissionError("no access")
        return _read_rows(open_option_entry(), _RULED)

    answer = inbox.inbox_json(inbox.read(discovery, read_rows))

    repositories_read = cast("list[dict[str, Any]]", answer["repositories"])
    assert answer["root"] == str(tmp_path)
    assert [entry["repository"] for entry in repositories_read] == [
        "a/good",
        "b/broken",
        "c/unreadable",
    ]
    assert [line["index"] for line in repositories_read[0]["items"][0]["lines"]] == [1]
    assert repositories_read[1]["unavailable"] == "listing failed"
    assert repositories_read[2]["unavailable"] == "no access"
    assert answer["unreadable"] == [
        {"directory": str(tmp_path / "locked"), "reason": "Permission denied"}
    ]


def test_the_read_of_a_root_holding_only_unreadable_directories_lists_no_repository(
    tmp_path: Path,
) -> None:
    unscanned = repositories.UnavailableCheckout(tmp_path / "locked", "Permission denied")
    discovery = repositories.Discovery(tmp_path, (), (unscanned,))

    answer = inbox.inbox_json(inbox.read(discovery, lambda _repository: ()))

    assert answer["repositories"] == []
