"""The GitHub adapter of the search for ruling items (`specs/mcp.spec.md`,
MCP-57..MCP-64), driven with a fake command runner."""

import json
from collections.abc import Sequence

import pytest

from aco import forge, github_search

QUERY = '"area song seite" in:body is:issue user:owner'


class _Runner:
    """A command runner that answers the given pages in order, or raises an answer
    that is an exception, and keeps every command it was given."""

    def __init__(self, *answers: str | Exception) -> None:
        self._answers = list(answers)
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], *, purpose: str) -> str:
        assert purpose
        self.commands.append(command)
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def fields(self, call: int) -> dict[str, str]:
        """The `-f key=value` fields of the `call`-th command."""
        command = self.commands[call]
        pairs = (command[index + 1] for index, word in enumerate(command) if word == "-f")
        return {pair.partition("=")[0]: pair.partition("=")[2] for pair in pairs}


def _hit(
    number: int, *, association: str = "MEMBER", repository: str = "owner/a"
) -> dict[str, object]:
    return {
        "number": number,
        "title": f"Titel {number}",
        "body": f"Body {number}",
        "author_association": association,
        "repository_url": f"https://api.github.com/repos/{repository}",
    }


def _page(hits: Sequence[object], *, total: int | None = None, incomplete: bool = False) -> str:
    total_count = len(hits) if total is None else total
    return json.dumps({"total_count": total_count, "incomplete_results": incomplete, "items": hits})


def _search(runner: _Runner) -> forge.RulingSearchResult:
    return github_search.GitHubRulingSearch(runner).search(QUERY)


def _numbers(result: forge.RulingSearchResult) -> list[int]:
    return [item.number for item in result.items]


def test_the_query_is_sent_unchanged_as_one_field_of_the_search_endpoint() -> None:
    runner = _Runner(_page([_hit(1)]))

    _search(runner)

    [command] = runner.commands
    assert command[:5] == ["gh", "api", "--method", "GET", "search/issues"]
    assert runner.fields(0) == {"q": QUERY, "per_page": "100", "page": "1"}


@pytest.mark.parametrize(
    ("association", "member"),
    [
        ("OWNER", True),
        ("MEMBER", True),
        ("COLLABORATOR", True),
        ("CONTRIBUTOR", False),
        ("NONE", False),
    ],
)
def test_an_item_counts_as_a_members_by_the_author_association(
    association: str, member: bool
) -> None:
    runner = _Runner(_page([_hit(1, association=association)]))

    [item] = _search(runner).items

    assert item == forge.RulingItem("owner/a", 1, "Titel 1", "Body 1", member)


def test_an_item_without_a_body_has_an_empty_one() -> None:
    runner = _Runner(_page([{**_hit(1), "body": None}]))

    [item] = _search(runner).items

    assert item.body == ""


def test_every_page_is_read_until_all_hits_are_in() -> None:
    first = [_hit(number) for number in range(1, 101)]
    second = [_hit(number) for number in range(101, 201)]
    third = [_hit(number) for number in range(201, 251)]
    runner = _Runner(_page(first, total=250), _page(second, total=250), _page(third, total=250))

    result = _search(runner)

    assert (len(result.items), result.complete) == (250, True)
    assert [runner.fields(call)["page"] for call in range(3)] == ["1", "2", "3"]


def test_a_result_the_forge_marks_incomplete_is_answered_incomplete() -> None:
    runner = _Runner(_page([_hit(1)], incomplete=True))

    result = _search(runner)

    assert (_numbers(result), result.complete) == ([1], False)


def test_a_result_above_the_forges_cap_is_answered_incomplete_without_paging_on() -> None:
    runner = _Runner(_page([_hit(1)], total=1001))

    result = _search(runner)

    assert (_numbers(result), result.complete, len(runner.commands)) == ([1], False, 1)


def test_a_page_that_ends_short_of_the_total_is_answered_incomplete() -> None:
    runner = _Runner(_page([_hit(1)], total=3), _page([], total=3))

    result = _search(runner)

    assert (_numbers(result), result.complete) == ([1], False)


def test_a_failing_runner_fails_the_search_with_its_error() -> None:
    failing = forge.ForgeTransientError("HTTP 502")
    runner = _Runner(failing)
    search = github_search.GitHubRulingSearch(runner)

    with pytest.raises(forge.ForgeTransientError, match="HTTP 502"):
        search.search(QUERY)


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param("not json", id="not-json"),
        pytest.param("[]", id="not-an-object"),
        pytest.param(json.dumps({"incomplete_results": False, "items": []}), id="no-total"),
        pytest.param(json.dumps({"total_count": 1, "incomplete_results": False}), id="no-items"),
        pytest.param(
            json.dumps({"total_count": 1, "incomplete_results": "no", "items": [_hit(1)]}),
            id="incomplete-not-a-bool",
        ),
        pytest.param(_page([{**_hit(1), "number": "1"}]), id="number-not-an-integer"),
        pytest.param(_page([{**_hit(1), "body": 5}]), id="body-not-text"),
        pytest.param(
            _page([{**_hit(1), "repository_url": "https://api.github.com/x"}]), id="no-repository"
        ),
        pytest.param(_page(["x"]), id="item-not-an-object"),
    ],
)
def test_an_answer_that_is_no_search_result_is_malformed(answer: str) -> None:
    search = github_search.GitHubRulingSearch(_Runner(answer))

    with pytest.raises(forge.ForgeMalformedResponseError):
        search.search(QUERY)
