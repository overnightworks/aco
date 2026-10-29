"""A forge serving one raw issue page: the `gh api` rows `GitHubForge` parses."""

from __future__ import annotations

import json

from board_fixtures import REPOSITORY

from aco import github


def board_issue_page_client(*rows: dict[str, object]) -> github.GitHubForge:
    return github.GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: "\n".join(json.dumps(row) for row in rows),
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
    }
    base.update(overrides)
    return base
