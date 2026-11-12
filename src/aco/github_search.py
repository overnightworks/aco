"""GitHub's search for ruling items (`forge.RulingSearch`), over the REST search
endpoint: one query, every page of its answer."""

import json
from collections.abc import Callable

from . import forge, github_issue_payload
from .protocol import REPOSITORY_PATTERN

type CommandRunner = Callable[..., str]
"""Runs the `gh` command line it is given for the stated `purpose` and answers
its output; raises a typed forge failure when the command fails."""

_PAGE_SIZE = 100
_RESULT_CAP = 1000
"""The most hits the forge's search hands out for one query."""
_PURPOSE = "GitHub search of ruling items"
_MALFORMED = "GitHub returned a malformed search result"
_REPOSITORIES_PATH = "/repos/"


def _malformed() -> forge.ForgeMalformedResponseError:
    return forge.ForgeMalformedResponseError(_MALFORMED)


def _repository(url: object) -> str:
    """The `OWNER/REPO` a hit's `repository_url` names."""
    path = url.partition(_REPOSITORIES_PATH)[2] if isinstance(url, str) else ""
    if REPOSITORY_PATTERN.fullmatch(path) is None:
        raise _malformed()
    return path


def _body(value: object) -> str:
    if value is not None and not isinstance(value, str):
        raise _malformed()
    return value or ""


def _ruling_item(hit: object) -> forge.RulingItem:
    if not isinstance(hit, dict):
        raise _malformed()
    number, title = hit.get("number"), hit.get("title")
    if not isinstance(number, int) or isinstance(number, bool) or not isinstance(title, str):
        raise _malformed()
    return forge.RulingItem(
        _repository(hit.get("repository_url")),
        number,
        title,
        _body(hit.get("body")),
        github_issue_payload.is_member(hit.get("author_association")),
    )


class _Page:
    """One page of the search endpoint's answer."""

    def __init__(self, text: str) -> None:
        try:
            answer = json.loads(text)
        except json.JSONDecodeError as error:
            raise _malformed() from error
        if not isinstance(answer, dict):
            raise _malformed()
        total, incomplete, hits = (
            answer.get("total_count"),
            answer.get("incomplete_results"),
            answer.get("items"),
        )
        if (
            not isinstance(total, int)
            or not isinstance(incomplete, bool)
            or not isinstance(hits, list)
        ):
            raise _malformed()
        self.total = total
        self.incomplete = incomplete
        self.items = tuple(_ruling_item(hit) for hit in hits)


class GitHubRulingSearch:
    """`forge.RulingSearch` over `run`, the command runner of the GitHub adapter."""

    def __init__(self, run: CommandRunner) -> None:
        self._run = run

    def _page(self, query: str, number: int) -> _Page:
        command = [
            "gh",
            "api",
            "--method",
            "GET",
            "search/issues",
            "-f",
            f"q={query}",
            "-f",
            f"per_page={_PAGE_SIZE}",
            "-f",
            f"page={number}",
        ]
        return _Page(self._run(command, purpose=_PURPOSE))

    def search(self, query: str) -> forge.RulingSearchResult:
        """Every page of `query`'s answer. The result is incomplete when the
        forge marks it so, when it holds more hits than the forge hands out, or
        when the pages end before the total."""
        page = self._page(query, 1)
        items = list(page.items)
        complete = not page.incomplete and page.total <= _RESULT_CAP
        number = 1
        while complete and len(items) < page.total:
            number += 1
            following = self._page(query, number)
            items.extend(following.items)
            complete = bool(following.items) and not following.incomplete
        return forge.RulingSearchResult(tuple(items), complete)
