"""The per-repository read over the GitHub adapter's listing
(specs/serve.spec.md, ABRD-06): a card reaches the operator only from an item
a member of the repository wrote."""

import pytest
from github_pages import (
    board_issue_page_client,
    raw_board_issue,
    rest_board_issue_page_client,
)
from option_cards import card, card_body

from aco import body, inbox

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
