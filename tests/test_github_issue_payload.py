"""The member and dependency-bot flags of the GitHub adapter reads, decoded by
`aco.github_issue_payload`."""

import json

import pytest
from board_fixtures import REPOSITORY
from github_fixtures import api_pull_request

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


def _landing_client(login: str, body: object = "") -> github.GitHubForge:
    payload = api_pull_request(
        body=body,
        title="Bump ruff",
        headRefName="dependabot/uv/ruff",
        author={"login": login},
        mergedAt=None,
        mergeCommit=None,
    )
    return github.GitHubForge(
        github.repository_id(REPOSITORY), run=lambda _arguments: json.dumps(payload)
    )


@pytest.mark.parametrize(
    ("login", "is_dependency_bot"),
    [
        pytest.param("app/dependabot", True, id="dependabot-app"),
        pytest.param("dependabot", False, id="user-named-dependabot"),
        pytest.param("ada", False, id="member"),
    ],
)
def test_the_landing_read_flags_only_the_dependabot_app_as_a_dependency_bot(
    login: str, is_dependency_bot: bool
) -> None:
    assert _landing_client(login).landing(12).author_is_dependency_bot is is_dependency_bot


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
    client = _landing_client("app/dependabot", body)

    with pytest.raises(ForgeMalformedResponseError):
        client.landing(12)
