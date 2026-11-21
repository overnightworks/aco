"""A GitHub listing is read one page at a time, exactly the pages the `Link` header of each
answer names, and a page that fails is classified from `gh`'s own closing message behind the
head block `-i` prints."""

import json
import math
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from github_pages import listing_answer, paged_listing
from rate_limit_fixtures import REST_REFUSAL

from aco import forge, github, github_paging

REPOSITORY = github.repository_id("example/agent-coordination")
LISTING = f"repos/{REPOSITORY}/issues?per_page=100"
JQ = ".[]"

# Answers the n-th call with the n-th step `FAKE_GH_STEPS` lists (its output, then its exit
# status) and logs every call's arguments in `FAKE_GH_LOG`; a read of REST's `rate_limit` is
# answered with `FAKE_GH_RESET` and counts as no step.
FAKE_GH = """#!{python}
import json, os, sys

arguments = sys.argv[1:]
log = os.environ["FAKE_GH_LOG"]
with open(log, "a") as handle:
    handle.write(json.dumps(arguments) + "\\n")
if "rate_limit" in arguments:
    print(os.environ["FAKE_GH_RESET"])
    sys.exit(0)
with open(log) as handle:
    calls = [line for line in handle if "rate_limit" not in line]
output, status = json.loads(os.environ["FAKE_GH_STEPS"])[len(calls) - 1]
sys.stdout.write(output)
sys.exit(status)
"""


def gh_listing(
    steps: list[tuple[str, int]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reset: str = ""
) -> Path:
    """A `gh` on `PATH` answering as `FAKE_GH`; returns the file logging its calls."""
    shims = tmp_path / "gh-bin"
    shims.mkdir()
    fake_gh = shims / "gh"
    fake_gh.write_text(FAKE_GH.format(python=sys.executable))
    fake_gh.chmod(0o755)
    log = tmp_path / "gh-calls.log"
    monkeypatch.setenv("PATH", f"{shims}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    monkeypatch.setenv("FAKE_GH_STEPS", json.dumps(steps))
    monkeypatch.setenv("FAKE_GH_RESET", reset)
    return log


def calls_of(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text().splitlines()]


def paths_of(log: Path) -> list[str]:
    return [call[1] for call in calls_of(log) if "rate_limit" not in call]


def head(status: str, *headers: str) -> str:
    return "\r\n".join([f"HTTP/2.0 {status}", *headers]) + "\r\n\r\n"


def failed_page(status: str, body: str, closing: str) -> str:
    """What `gh api -i` prints for a refused page: the head, the body, then its own message."""
    return head(status, "Content-Type: application/json") + body + "\n" + closing


SUB_ISSUE = json.dumps(
    {
        "number": 5,
        "repository": f"https://api.github.com/repos/{REPOSITORY}",
        "state": "open",
        "title": "T",
    }
)
NEXT_PAGE_LINK = 'Link: <https://api.github.com/repositories/1/issues?page=2>; rel="next"'
FIRST_PAGE = head("200 OK", NEXT_PAGE_LINK) + SUB_ISSUE
LAST_PAGE = head("200 OK") + SUB_ISSUE


def run_of(answers: list[str], calls: list[list[str]]) -> Callable[[list[str]], str]:
    pending = iter(answers)

    def run(arguments: list[str]) -> str:
        calls.append(arguments)
        return next(pending)

    return run


def test_a_listing_follows_the_next_link_and_stops_at_the_answer_naming_none() -> None:
    calls: list[list[str]] = []
    run = run_of(
        [
            listing_answer(["-i"], "1\n2", next_path="repositories/1/issues?page=2"),
            listing_answer(["-i"], "3", next_path="repositories/1/issues?page=3"),
            listing_answer(["-i"], "4"),
        ],
        calls,
    )

    text = github_paging.read_pages(run, LISTING, JQ)

    assert text.split() == ["1", "2", "3", "4"]
    assert calls == [
        ["api", LISTING, "-i", "--jq", JQ],
        ["api", "repositories/1/issues?page=2", "-i", "--jq", JQ],
        ["api", "repositories/1/issues?page=3", "-i", "--jq", JQ],
    ]


@pytest.mark.parametrize("rows", [0, 1, 99, 100, 101, 250])
def test_a_listing_of_n_rows_costs_one_call_per_hundred_rows(rows: int) -> None:
    calls: list[list[str]] = []
    body = [{"number": number} for number in range(rows)]

    def run(arguments: list[str]) -> str:
        calls.append(arguments)
        return paged_listing(arguments, body)

    text = github_paging.read_pages(run, LISTING, JQ)

    assert len(text.splitlines()) == rows
    assert len(calls) == max(1, math.ceil(rows / 100))


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        pytest.param(
            head("200 OK", 'Link: <https://example.org/issues?page=2>; rel="next"') + "1",
            "outside its API",
            id="next-link-outside-the-api",
        ),
        pytest.param(
            head("200 OK", 'Link: <http://api.github.com/issues?page=2>; rel="next"') + "1",
            "outside its API",
            id="next-link-without-tls",
        ),
        pytest.param(
            head("200 OK", "Link: https://api.github.com/issues?page=2") + "1",
            "malformed Link",
            id="link-without-angle-brackets",
        ),
        pytest.param(
            head("200 OK", 'Link: <https://api.github.com/issues?page=2>; rel="next", junk') + "1",
            "malformed Link",
            id="link-with-a-trailing-fragment",
        ),
        pytest.param("1\n2", "without a header", id="body-without-a-head"),
        pytest.param("", "without a header", id="empty-answer"),
    ],
)
def test_a_listing_fails_loud_on_a_foreign_or_malformed_link_or_a_missing_head(
    answer: str, message: str
) -> None:
    run = run_of([answer], [])

    with pytest.raises(forge.ForgeMalformedResponseError, match=message):
        github_paging.read_pages(run, LISTING, JQ)


def test_a_listing_with_a_link_naming_no_next_page_ends_there() -> None:
    last = head("200 OK", 'Link: <https://api.github.com/repositories/1/issues?page=1>; rel="prev"')
    calls: list[list[str]] = []

    text = github_paging.read_pages(run_of([last + "7"], calls), LISTING, JQ)

    assert (text, len(calls)) == ("7", 1)


def sub_issues_of(client: github.GitHubForge) -> object:
    return client.list_children(79)


@pytest.mark.parametrize(
    ("closing", "status", "error"),
    [
        pytest.param(
            "gh: Not Found (HTTP 404)", "404 Not Found", forge.ForgeNotFoundError, id="not-found"
        ),
        pytest.param(
            "gh: Resource not accessible by integration (HTTP 403)",
            "403 Forbidden",
            forge.ForgePermissionDeniedError,
            id="permission-refused",
        ),
        pytest.param(
            "gh: Server Error (HTTP 502)",
            "502 Bad Gateway",
            forge.ForgeTransientError,
            id="server-error",
        ),
    ],
)
def test_a_failed_page_is_classified_from_the_closing_message_behind_the_head_block(
    closing: str,
    status: str,
    error: type[forge.ForgeError],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    gh_listing(
        [(FIRST_PAGE, 0), (failed_page(status, '{"message":"x"}', closing), 1)],
        monkeypatch,
        tmp_path,
    )
    client = github.GitHubForge(REPOSITORY)

    with pytest.raises(error):
        sub_issues_of(client)


def test_a_rate_limit_on_the_second_page_is_transient_and_names_its_reset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reset = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=30)
    refused = head("403 Forbidden", "Content-Type: application/json") + REST_REFUSAL
    log = gh_listing(
        [(FIRST_PAGE, 0), (refused, 1)], monkeypatch, tmp_path, str(int(reset.timestamp()))
    )
    client = github.GitHubForge(REPOSITORY)

    with pytest.raises(forge.ForgeRateLimitedError) as refusal:
        sub_issues_of(client)

    assert refusal.value.resets_at == reset
    assert (len(paths_of(log)), client.requests) == (2, 3)


def test_an_empty_listing_costs_one_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log = gh_listing([(head("200 OK"), 0)], monkeypatch, tmp_path)
    client = github.GitHubForge(REPOSITORY)

    children = client.list_children(79)

    assert (children, len(calls_of(log))) == ((), 1)


def test_every_page_of_a_listing_counts_as_one_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = gh_listing([(FIRST_PAGE, 0), (LAST_PAGE, 0)], monkeypatch, tmp_path)
    client = github.GitHubForge(REPOSITORY)

    children = client.list_children(79)

    assert (len(children), client.requests, len(calls_of(log))) == (2, 2, 2)


def test_the_branch_rules_read_still_reads_a_plan_without_rulesets_as_no_rule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    message = "Upgrade to GitHub Pro or make this repository public to enable this feature."
    refusal = failed_page(
        "403 Forbidden", json.dumps({"message": message}), f"gh: {message} (HTTP 403)"
    )
    gh_listing([(refusal, 1)], monkeypatch, tmp_path)
    client = github.GitHubForge(REPOSITORY)

    rules = client.merge_rules("main")

    assert rules.merge_methods == ()
