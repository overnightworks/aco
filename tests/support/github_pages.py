"""A forge serving one raw issue page: the `gh api` rows `GitHubForge` parses."""

import json
import subprocess
from collections.abc import Callable, Sequence
from urllib.parse import parse_qs, urlencode, urlsplit

from board_fixtures import REPOSITORY
from github_fixtures import LANDING_BRANCH, MERGE_COMMIT_SHA

from aco import github, github_paging

DEFAULT_PER_PAGE = 30


LISTING_HEAD_LINES = ("HTTP/2.0 200 OK", "Content-Type: application/json; charset=utf-8")
HEAD_END = "\r\n\r\n"


def listing_answer(arguments: list[str], body: str, *, next_path: str | None = None) -> str:
    """What `gh api` prints for one listing page: with `-i`, the status line and headers (a
    `Link` to `next_path` among them) before `body`, else `body` alone."""
    if "-i" not in arguments:
        return body
    link = (
        [] if next_path is None else [f'Link: <{github_paging.API_ORIGIN}{next_path}>; rel="next"']
    )
    return "\r\n".join([*LISTING_HEAD_LINES, *link]) + HEAD_END + body


def page_of(arguments: list[str], rows: Sequence[object]) -> tuple[list[object], str | None]:
    """The rows of the page the listing request at `arguments[1]` selects with `per_page` and
    `page`, and the path of the next page while rows remain after it."""
    location = urlsplit(arguments[1])
    query = parse_qs(location.query)
    per_page = int(query.get("per_page", [DEFAULT_PER_PAGE])[0])
    page = int(query.get("page", [1])[0])
    selected = list(rows[(page - 1) * per_page : page * per_page])
    if page * per_page >= len(rows):
        return selected, None
    following = location._replace(query=urlencode({**query, "page": page + 1}, doseq=True))
    return selected, following.geturl()


def paged_listing(arguments: list[str], rows: Sequence[object]) -> str:
    """What `gh api` prints for the page of `rows` the request selects, one JSON row per line."""
    selected, next_path = page_of(arguments, rows)
    return listing_answer(
        arguments, "\n".join(json.dumps(row) for row in selected), next_path=next_path
    )


def listing_runner(
    run: Callable[..., str],
) -> Callable[..., str]:
    """`run` answering a listing read as `gh api -i` does: its answer behind a head block."""

    def with_head(arguments: list[str], *rest: object, **keywords: object) -> str:
        return listing_answer(arguments, run(arguments, *rest, **keywords))

    return with_head


def board_issue_page_client(*rows: dict[str, object]) -> github.GitHubForge:
    return github.GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: paged_listing(arguments, rows),
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
        run=lambda arguments, input_data=None: listing_answer(
            arguments, gh_api_prints(arguments, list(rest_rows))
        ),
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
        "openDependents": 0,
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
