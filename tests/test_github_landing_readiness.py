"""The draft flag of the pull request that `aco land`'s readiness read returns."""

import json

import pytest
from board_fixtures import REPOSITORY
from github_fixtures import MERGE_COMMIT_SHA

from aco import github
from aco.github import GitHubForge
from aco.protocol import ClaimError

_PULL_REQUEST_PATH = f"repos/{REPOSITORY}/pulls/57"


def _client(**fields: object) -> GitHubForge:
    pull_request = (
        dict(state="open", draft=False, headSha=MERGE_COMMIT_SHA, mergeableState="clean") | fields
    )

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        if arguments[1] == _PULL_REQUEST_PATH:
            return json.dumps(pull_request)
        if arguments[1].endswith("/status"):
            return json.dumps({"state": "success", "total": 0})
        return ""

    return GitHubForge(github.repository_id(REPOSITORY), run=fake_run)


@pytest.mark.parametrize("draft", [True, False])
def test_landing_readiness_reads_whether_the_pull_request_is_a_draft(draft: bool) -> None:
    client = _client(draft=draft)

    readiness = client.landing_readiness(57)

    assert readiness.draft is draft


@pytest.mark.parametrize(
    "draft",
    [pytest.param(None, id="missing"), pytest.param("false", id="not-boolean")],
)
def test_landing_readiness_fails_loud_on_a_malformed_draft_flag(draft: object) -> None:
    client = _client(draft=draft)

    with pytest.raises(ClaimError, match="malformed pull request"):
        client.landing_readiness(57)
