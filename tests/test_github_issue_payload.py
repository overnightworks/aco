"""The member flag of the GitHub adapter's single-item read, decoded by
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
