"""A forge serving one raw issue page: the `gh api` rows `GitHubForge` parses."""

import json
import subprocess

from board_fixtures import REPOSITORY

from aco import github


def board_issue_page_client(*rows: dict[str, object]) -> github.GitHubForge:
    return github.GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: "\n".join(json.dumps(row) for row in rows),
    )


def rest_board_issue_page_client(*rest_rows: dict[str, object]) -> github.GitHubForge:
    """A forge whose `gh api` answers each request by running the request's own `--jq`
    filter over the given REST issue rows, as `gh` does."""

    def run(arguments: list[str], input_data: bytes | None = None) -> str:
        projection = arguments[arguments.index("--jq") + 1]
        return subprocess.run(
            ["jq", "-c", projection],
            input=json.dumps(list(rest_rows)),
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    return github.GitHubForge(github.repository_id(REPOSITORY), run=run)


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
