"""A forge serving one raw issue page: the `gh api` rows `GitHubForge` parses."""

import json
import subprocess

from board_fixtures import REPOSITORY
from github_fixtures import LANDING_BRANCH, MERGE_COMMIT_SHA

from aco import github


def board_issue_page_client(*rows: dict[str, object]) -> github.GitHubForge:
    return github.GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: "\n".join(json.dumps(row) for row in rows),
    )


def gh_api_prints(arguments: list[str], answer: object) -> str:
    """What `gh api` prints for REST's `answer`: the answer itself, or what the request's own
    `--jq` filter selects from it."""
    if "--jq" not in arguments:
        return json.dumps(answer)
    return subprocess.run(
        ["jq", "-cr", arguments[arguments.index("--jq") + 1]],
        input=json.dumps(answer),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def rest_board_issue_page_client(*rest_rows: dict[str, object]) -> github.GitHubForge:
    """A forge whose `gh api` answers each request by running the request's own `--jq`
    filter over the given REST issue rows, as `gh` does."""
    return github.GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: gh_api_prints(arguments, list(rest_rows)),
    )


def raw_board_issue(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "number": 1,
        "title": "Title",
        "labels": [],
        "body": "",
        "createdAt": "2026-08-20T00:00:00Z",
        "updatedAt": "2026-08-20T00:00:00Z",
        "isPullRequest": False,
        "kind": None,
        "childrenClosed": None,
        "childrenTotal": None,
        "blockedByCount": 0,
        "authorAssociation": "MEMBER",
    }
    base.update(overrides)
    return base


def api_head(**overrides: object) -> dict[str, object]:
    """The head of a pull request as REST carries it: a branch of this repository."""
    owner, _, name = REPOSITORY.partition("/")
    return {
        "ref": LANDING_BRANCH,
        "sha": "a" * 40,
        "repo": {"name": name, "owner": {"login": owner}},
    } | overrides


def api_pull_request(**overrides: object) -> dict[str, object]:
    """One pull request as REST's single-pull-request answer carries it."""
    return {
        "number": 12,
        "title": "feat: land the lane",
        "body": "Work-Item: #72",
        "base": {"ref": "main"},
        "head": api_head(),
        "user": {"login": "ada", "type": "User"},
        "merged_at": "2026-09-05T10:00:00Z",
        "merge_commit_sha": MERGE_COMMIT_SHA,
    } | overrides
