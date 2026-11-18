"""The member and dependency-bot flags of the GitHub adapter reads, decoded by
`aco.github_issue_payload`."""

import json

import pytest
from board_fixtures import REPOSITORY

from aco import github


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
    owner, _, name = REPOSITORY.partition("/")
    payload = {
        "number": 12,
        "title": "Bump ruff",
        "body": "",
        "baseRefName": "main",
        "headRefName": "dependabot/uv/ruff",
        "headRefOid": "a" * 40,
        "headRepository": {"name": name},
        "headRepositoryOwner": {"login": owner},
        "author": {"login": login},
        "mergedAt": None,
        "mergeCommit": None,
    }
    client = github.GitHubForge(
        github.repository_id(REPOSITORY), run=lambda _arguments: json.dumps(payload)
    )

    assert client.landing(12).author_is_dependency_bot is is_dependency_bot
