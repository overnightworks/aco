"""A board read and `aco check <pull request>` need no GraphQL point: with every GraphQL call
refused, both still answer. The GitHub CLI is the only fake."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from board_fixtures import REPOSITORY, complete_contract
from check_pull_request_fixtures import LANE_BRANCH, LANE_CLAIM
from cli_fixtures import freeze_cli_now, run_cli
from github_fixtures import serve_forge
from github_pages import api_head, api_pull_request, gh_api_prints
from store_fixtures import publish_claims_from_a_second_clone

from aco import forge, github

RATE_LIMIT_REFUSAL = "GraphQL: API rate limit already exceeded for user ID 1."
ITEM = 90
ISSUES = f"repos/{REPOSITORY}/issues"
PULLS = f"repos/{REPOSITORY}/pulls"
DECLARING_MERGE = {
    "number": 140,
    "title": "Lands it",
    "body": f"Work-Item: #{ITEM}\n\nCloses #{ITEM}",
    "pull_request": {"merged_at": "2026-08-20T12:00:00Z"},
}
OPEN_ITEM = {
    "number": ITEM,
    "title": "Landed but open",
    "body": complete_contract("Close it."),
    "labels": [],
    "created_at": "2026-08-01T00:00:00Z",
    "updated_at": "2026-08-20T00:00:00Z",
    "author_association": "MEMBER",
}
LANE_BODY = "No-Item: docs\n\nTidy the README."
CHECKED_PULL_REQUEST = api_pull_request(
    body=LANE_BODY,
    head=api_head(ref=LANE_BRANCH),
    merged_at=None,
    merge_commit_sha="b" * 40,
    changed_files=1,
)


def route_of(path: str) -> str:
    """The path a request names, with the issue state it filters on."""
    location = urlsplit(path)
    states = parse_qs(location.query).get("state")
    return location.path if states is None else f"{location.path}?state={states[0]}"


@dataclass
class GraphqlRefusingGitHub:
    """A `gh` that answers each REST route of `rest` and refuses every GraphQL and `pr` call with
    the recorded rate-limit text, recording what it refused."""

    rest: dict[str, object]
    refused: list[list[str]] = field(default_factory=list)

    def __call__(self, arguments: list[str], *, input_data: bytes | None = None) -> str:
        if arguments[:2] == ["api", "graphql"] or arguments[0] == "pr":
            self.refused.append(arguments)
            raise forge.ForgeError(RATE_LIMIT_REFUSAL)
        path = next(argument for argument in arguments if argument.startswith("repos/"))
        if (route := route_of(path)) not in self.rest:
            pytest.fail(f"unexpected request: {arguments}")
        return gh_api_prints(arguments, self.rest[route])


def serve_rest(monkeypatch: pytest.MonkeyPatch, rest: dict[str, object]) -> GraphqlRefusingGitHub:
    """The adapter over a `gh` answering `rest`, installed as GitHub's."""
    gh = GraphqlRefusingGitHub(rest)
    serve_forge(monkeypatch, github.GitHubForge(github.repository_id(REPOSITORY), run=gh))
    return gh


@pytest.fixture(autouse=True)
def _freeze_clock(monkeypatch: pytest.MonkeyPatch, github_world: Path) -> None:
    freeze_cli_now(monkeypatch)


def test_a_board_read_with_a_recovery_candidate_succeeds_while_graphql_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = serve_rest(
        monkeypatch,
        {
            f"{ISSUES}?state=open": [OPEN_ITEM],
            f"{ISSUES}?state=closed": [DECLARING_MERGE],
            f"{PULLS}?state=open": [],
            f"{ISSUES}/{ITEM}/events": [{"event": "closed", "created_at": "2026-08-20T12:00:01Z"}],
        },
    )

    result = run_cli(["board", "--json"], capsys)

    payload = json.loads(result.stdout)
    assert (result.status, [row["number"] for row in payload["recovery"]], gh.refused) == (
        0,
        [ITEM],
        [],
    )


def test_a_pull_request_check_succeeds_while_graphql_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    publish_claims_from_a_second_clone(github_clone, bare_remote, (LANE_CLAIM,))
    landing_issue = {"state": "open", "title": "Tidy", "body": LANE_BODY, "pull_request": {}}
    gh = serve_rest(
        monkeypatch,
        {
            f"repos/{REPOSITORY}": {"default_branch": "main"},
            f"{ISSUES}/12": landing_issue,
            f"{PULLS}/12": CHECKED_PULL_REQUEST,
            f"{PULLS}/12/files": [{"filename": "README.md", "status": "modified"}],
        },
    )

    result = run_cli(["check", "12"], capsys)

    assert (result.status, result.stdout, gh.refused) == (
        0,
        "PR #12 by ada declares No-Item: docs\n",
        [],
    )
