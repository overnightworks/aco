"""The member and dependency-bot flags of the GitHub adapter reads, decoded by
`aco.github_issue_payload`."""

import json

import pytest
from board_fixtures import REPOSITORY
from github_pages import (
    api_head,
    api_pull_request,
    board_issue_page_client,
    raw_board_issue,
    rest_board_issue_page_client,
)

from aco import github
from aco.forge import ForgeMalformedResponseError


def _item_reference_client(**fields: object) -> github.GitHubForge:
    payload = {"state": "open", "title": "Work", "body": "", "is_landing": False, **fields}
    return github.GitHubForge(
        github.repository_id(REPOSITORY), run=lambda _arguments: json.dumps(payload)
    )


@pytest.mark.parametrize(
    ("fields", "is_member"),
    [
        pytest.param({"author_association": "OWNER"}, True, id="owner"),
        pytest.param({"author_association": "MEMBER"}, True, id="member"),
        pytest.param({"author_association": "COLLABORATOR"}, True, id="collaborator"),
        pytest.param({"author_association": "NONE"}, False, id="none"),
        pytest.param({"author_association": "CONTRIBUTOR"}, False, id="contributor"),
        pytest.param({}, False, id="missing"),
        pytest.param({"author_association": ["OWNER"]}, False, id="malformed"),
        pytest.param(
            {"author_association": "MEMBER", "is_landing": True}, True, id="member-pull-request"
        ),
        pytest.param(
            {"author_association": "NONE", "is_landing": True}, False, id="stranger-pull-request"
        ),
    ],
)
def test_the_single_item_read_says_whether_a_member_wrote_the_item(
    fields: dict[str, object], is_member: bool
) -> None:
    client = _item_reference_client(**fields)

    reference = client.item_reference(10)

    assert reference.author_is_member is is_member


def _landing_client(login: str, body: object = "", user_type: str = "Bot") -> github.GitHubForge:
    payload = api_pull_request(
        body=body,
        title="Bump ruff",
        head=api_head(ref="dependabot/uv/ruff"),
        user={"login": login, "type": user_type},
        merged_at=None,
    )
    return github.GitHubForge(
        github.repository_id(REPOSITORY), run=lambda _arguments: json.dumps(payload)
    )


@pytest.mark.parametrize(
    ("login", "user_type", "is_dependency_bot"),
    [
        pytest.param("dependabot[bot]", "Bot", True, id="dependabot-app"),
        pytest.param("renovate[bot]", "Bot", False, id="another-app"),
        pytest.param("dependabot", "User", False, id="user-named-dependabot"),
        pytest.param("ada", "User", False, id="member"),
    ],
)
def test_the_landing_read_flags_only_the_dependabot_app_as_a_dependency_bot(
    login: str, user_type: str, is_dependency_bot: bool
) -> None:
    landing = _landing_client(login, user_type=user_type).landing(12)

    assert landing.author_is_dependency_bot is is_dependency_bot


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(0, id="zero"),
        pytest.param(False, id="false"),
        pytest.param([], id="empty-list"),
        pytest.param({}, id="empty-object"),
    ],
)
def test_the_landing_read_refuses_a_falsy_body_that_is_not_text(body: object) -> None:
    client = _landing_client("dependabot[bot]", body)

    with pytest.raises(ForgeMalformedResponseError):
        client.landing(12)


def _rest_issue(**fields: object) -> dict[str, object]:
    return {
        "number": 5,
        "title": "Title",
        "labels": [],
        "body": "",
        "created_at": "2026-08-20T00:00:00Z",
        "updated_at": "2026-08-20T00:00:00Z",
        **fields,
    }


@pytest.mark.parametrize(
    ("fields", "open_dependents"),
    [
        pytest.param(
            {"issue_dependencies_summary": {"blocking": 2, "total_blocking": 3}},
            2,
            id="two-open-of-three",
        ),
        pytest.param(
            {"issue_dependencies_summary": {"blocking": 0, "total_blocking": 1}},
            0,
            id="its-only-dependent-closed",
        ),
        pytest.param({}, 0, id="no-summary"),
    ],
)
def test_the_board_listing_carries_the_open_dependents_github_counts(
    fields: dict[str, object], open_dependents: int
) -> None:
    client = rest_board_issue_page_client(_rest_issue(**fields))

    issues = client.list_open_board_issues()

    assert [issue.open_dependents for issue in issues] == [open_dependents]


@pytest.mark.parametrize("count", ["2", -1, True, None], ids=["text", "negative", "bool", "null"])
def test_the_board_listing_refuses_a_malformed_open_dependents_count(count: object) -> None:
    client = board_issue_page_client(raw_board_issue(openDependents=count))

    with pytest.raises(ForgeMalformedResponseError, match="malformed board issue"):
        client.list_open_board_issues()
