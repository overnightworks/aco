"""The GitHub adapter reads pull requests over REST: the merged and the open lists, one pull
request's landing facts and the time an item was reopened. The GitHub CLI is the only fake."""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from board_fixtures import REPOSITORY
from github_fixtures import MERGE_COMMIT_SHA
from github_pages import api_head, api_pull_request

from aco import forge, github, workboard

FLOOR = datetime(2026, 11, 1, tzinfo=UTC)
MERGED = "2026-11-10T10:00:00Z"
TEST_MERGE_COMMIT_SHA = "b" * 40
ISSUES = f"repos/{REPOSITORY}/issues"
PULLS = f"repos/{REPOSITORY}/pulls"
EVENTS = f"{ISSUES}/323/events"


def scripted_rest(
    routes: Mapping[str, Sequence[Sequence[object]]],
) -> tuple[github.GitHubForge, list[str]]:
    """An adapter whose `gh` answers each REST list `routes` names, page by page (a page past
    the last is empty), one row per line as `--jq '.[]'` prints it, and records every path asked."""
    asked: list[str] = []

    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        path = next(argument for argument in arguments if argument.startswith("repos/"))
        asked.append(path)
        location = urlsplit(path)
        pages = routes[location.path]
        page = int(parse_qs(location.query)["page"][0])
        return "\n".join(json.dumps(row) for row in (pages[page - 1] if page <= len(pages) else ()))

    return github.GitHubForge(github.repository_id(REPOSITORY), run=run), asked


def merged_row(number: object, merged_at: object = MERGED, **fields: object) -> dict[str, object]:
    """A pull request as REST's issue list carries it."""
    return {
        "number": number,
        "title": f"Change {number}",
        "body": f"Work-Item: #{number}",
        "pull_request": {"merged_at": merged_at},
        **fields,
    }


def open_row(number: int = 62, **fields: object) -> dict[str, object]:
    return {
        "number": number,
        "title": "Fixes #10",
        "body": "Ship it.",
        "head": {"ref": "codex/issue-10"},
        "merged_at": None,
        **fields,
    }


def event_row(event: object, created_at: object = MERGED) -> dict[str, object]:
    return {"event": event, "created_at": created_at}


def full_page(row: dict[str, object]) -> list[dict[str, object]]:
    return [{**row, "number": number} for number in range(1, github.ISSUES_PER_PAGE + 1)]


def merged_numbers(client: github.GitHubForge) -> list[int]:
    return [row.number for row in client.list_recent_merged_board_pull_requests(FLOOR)]


def test_the_merged_list_keeps_what_merged_at_or_after_the_floor() -> None:
    client, asked = scripted_rest(
        {
            ISSUES: [
                [
                    merged_row(1, "2026-11-20T00:00:00Z"),
                    merged_row(2, "2026-11-01T00:00:00Z"),
                    merged_row(3, "2026-10-31T23:59:59Z"),
                    merged_row(4, None),
                    {"number": 5, "title": "A plain issue", "body": "Fixes nothing."},
                ]
            ]
        }
    )

    merged = client.list_recent_merged_board_pull_requests(FLOOR)

    assert [(row.number, row.title, row.body, row.merged_at) for row in merged] == [
        (1, "Change 1", "Work-Item: #1", "2026-11-20T00:00:00Z"),
        (2, "Change 2", "Work-Item: #2", "2026-11-01T00:00:00Z"),
    ]
    assert "state=closed" in asked[0]
    assert "since=2026-11-01T00:00:00Z" in asked[0]


def test_a_merged_pull_request_with_no_body_reads_as_an_empty_body() -> None:
    client, _ = scripted_rest({ISSUES: [[merged_row(1, body=None)]]})

    merged = client.list_recent_merged_board_pull_requests(FLOOR)

    assert [row.body for row in merged] == [""]


def test_a_merged_pull_request_seen_twice_counts_once() -> None:
    client, _ = scripted_rest({ISSUES: [[merged_row(1), merged_row(2), merged_row(1)]]})

    assert merged_numbers(client) == [1, 2]


def test_the_merged_list_walks_every_page_and_counts_a_row_on_two_pages_once() -> None:
    first = full_page(merged_row(0))
    client, asked = scripted_rest({ISSUES: [first, [merged_row(100), merged_row(101)]]})

    assert merged_numbers(client) == list(range(1, 102))
    assert any("page=2" in path for path in asked)


@pytest.mark.parametrize(
    "row",
    [
        pytest.param(merged_row(1, pull_request={}), id="no-merged-at-key"),
        pytest.param(merged_row(1, pull_request="merged"), id="pull-request-not-an-object"),
        pytest.param(merged_row(1, pull_request=None), id="pull-request-null"),
        pytest.param(merged_row(None), id="no-number"),
        pytest.param(merged_row(True), id="number-is-a-bool"),
        pytest.param(merged_row(1, title=5), id="title-not-text"),
        pytest.param(merged_row(1, body=5), id="body-not-text"),
        pytest.param("a row of text", id="row-not-an-object"),
    ],
)
def test_the_merged_list_fails_loud_on_a_row_it_cannot_read(row: object) -> None:
    client, _ = scripted_rest({ISSUES: [[merged_row(2), row]]})

    with pytest.raises(forge.ForgeMalformedResponseError, match="malformed board pull request"):
        client.list_recent_merged_board_pull_requests(FLOOR)


@pytest.mark.parametrize(
    ("merged_at", "refusal"),
    [
        pytest.param("yesterday", "malformed board pull request", id="not-a-time"),
        pytest.param(5, "malformed board pull request", id="not-text"),
        pytest.param(
            "9999-99-99T00:00:00Z", "malformed merged board pull request", id="not-a-calendar-time"
        ),
    ],
)
def test_the_merged_list_fails_loud_on_a_merge_time_it_cannot_read(
    merged_at: object, refusal: str
) -> None:
    client, _ = scripted_rest({ISSUES: [[merged_row(1, merged_at)]]})

    with pytest.raises(forge.ForgeMalformedResponseError, match=refusal):
        client.list_recent_merged_board_pull_requests(FLOOR)


def test_the_open_list_reads_each_pull_request_with_its_branch() -> None:
    client, asked = scripted_rest({PULLS: [[open_row(), open_row(63, body=None)]]})

    opened = client.list_open_board_pull_requests()

    assert opened == (
        workboard.PullRequest(62, "Fixes #10", "Ship it.", "codex/issue-10", None),
        workboard.PullRequest(63, "Fixes #10", "", "codex/issue-10", None),
    )
    assert "state=open" in asked[0]


def test_the_open_list_walks_every_page() -> None:
    client, _ = scripted_rest({PULLS: [full_page(open_row()), [open_row(101)]]})

    assert [row.number for row in client.list_open_board_pull_requests()] == list(range(1, 102))


@pytest.mark.parametrize(
    "row",
    [
        pytest.param(open_row(True), id="number-is-a-bool"),
        pytest.param(open_row(0), id="number-not-positive"),
        pytest.param(open_row(title=5), id="title-not-text"),
        pytest.param(open_row(body=5), id="body-not-text"),
        pytest.param(open_row(head={"ref": None}), id="head-branch-missing"),
        pytest.param(open_row(head=None), id="head-missing"),
        pytest.param("a row of text", id="row-not-an-object"),
    ],
)
def test_the_open_list_fails_loud_on_a_row_it_cannot_read(row: object) -> None:
    client, _ = scripted_rest({PULLS: [[row]]})

    with pytest.raises(forge.ForgeMalformedResponseError, match="malformed board pull request"):
        client.list_open_board_pull_requests()


def landing_client(answer: object) -> github.GitHubForge:
    return github.GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: json.dumps(answer),
    )


@pytest.mark.parametrize(
    ("row", "facts"),
    [
        pytest.param(
            api_pull_request(),
            {"merged": True, "merge_commit": MERGE_COMMIT_SHA, "author": "ada"},
            id="merged",
        ),
        pytest.param(
            api_pull_request(merged_at=None, merge_commit_sha=TEST_MERGE_COMMIT_SHA),
            {"merged": False, "merge_commit": None},
            id="open-with-a-test-merge-commit",
        ),
        pytest.param(
            api_pull_request(user={"login": "dependabot[bot]", "type": "Bot"}),
            {"author": "app/dependabot", "author_is_dependency_bot": True},
            id="bot-author",
        ),
        pytest.param(
            api_pull_request(user={"login": "dependabot", "type": "User"}),
            {"author": "dependabot", "author_is_dependency_bot": False},
            id="user-named-like-the-bot",
        ),
        pytest.param(api_pull_request(body=None), {"body": ""}, id="no-body"),
        pytest.param(
            api_pull_request(base={"ref": "release"}),
            {"target_branch": "release"},
            id="target-branch",
        ),
    ],
)
def test_the_landing_maps_a_pull_request_as_rest_carries_it(
    row: dict[str, object], facts: dict[str, object]
) -> None:
    landing = landing_client(row).landing(12)

    assert {name: getattr(landing, name) for name in facts} == facts


@pytest.mark.parametrize(
    "row",
    [
        pytest.param({"number": 12, "body": "b"}, id="missing-refs"),
        pytest.param(api_pull_request(user=None), id="deleted-author"),
        pytest.param(api_pull_request(user={"type": "User"}), id="author-without-login"),
        pytest.param(api_pull_request(title=None), id="missing-title"),
        pytest.param(api_pull_request(base=None), id="missing-base"),
        pytest.param(api_pull_request(head=api_head(sha=None)), id="missing-head-sha"),
        pytest.param(api_pull_request(head=api_head(sha="not-a-sha")), id="malformed-head-sha"),
        pytest.param(api_pull_request(head=api_head(ref=None)), id="missing-head-branch"),
        pytest.param(api_pull_request(head=api_head(repo=None)), id="deleted-fork"),
        pytest.param(
            api_pull_request(
                head=api_head(repo={"name": "repo/extra", "owner": {"login": "owner"}})
            ),
            id="head-repository-invalid-shape",
        ),
        pytest.param(
            api_pull_request(head=api_head(repo={"name": "repo", "owner": None})),
            id="deleted-fork-owner",
        ),
        pytest.param(api_pull_request(merged_at="yesterday"), id="malformed-merge-time"),
        pytest.param(
            {key: value for key, value in api_pull_request().items() if key != "merged_at"},
            id="no-merged-at-key",
        ),
        pytest.param(api_pull_request(merge_commit_sha=None), id="merged-with-no-merge-commit"),
        pytest.param(api_pull_request(merge_commit_sha="not-a-sha"), id="malformed-merge-commit"),
        pytest.param(api_pull_request(merge_commit_sha=1234567), id="merge-commit-not-text"),
    ],
)
def test_the_landing_refuses_a_pull_request_it_cannot_read(row: dict[str, object]) -> None:
    client = landing_client(row)

    with pytest.raises(forge.ForgeMalformedResponseError) as refusal:
        client.landing(12)

    assert str(refusal.value) == github.MALFORMED_PULL_REQUEST


def test_a_number_that_is_no_pull_request_refuses_as_a_plain_forge_error() -> None:
    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        raise forge.ForgeNotFoundError("gh: Not Found (HTTP 404)")

    client = github.GitHubForge(github.repository_id(REPOSITORY), run=run)

    with pytest.raises(forge.ForgeError) as refusal:
        client.landing(12)

    assert (type(refusal.value), str(refusal.value)) == (
        forge.ForgeError,
        "gh: Not Found (HTTP 404)",
    )


def test_the_reopen_time_is_the_newest_reopened_event() -> None:
    client, asked = scripted_rest(
        {
            EVENTS: [
                [
                    event_row("reopened", "2026-11-12T00:00:00Z"),
                    event_row("closed", "2026-11-13T00:00:00Z"),
                    event_row("reopened", "2026-11-14T00:00:00Z"),
                    event_row("reopened", "2026-11-11T00:00:00Z"),
                ]
            ]
        }
    )

    reopened = client.reopened_at((323, 323))

    assert reopened == {323: datetime(2026, 11, 14, tzinfo=UTC)}
    assert len(asked) == 1


def test_an_item_never_reopened_has_no_reopen_time() -> None:
    client, _ = scripted_rest({EVENTS: [[event_row("closed"), event_row("labeled")]]})

    assert client.reopened_at((323,)) == {323: None}


def test_the_reopen_time_reads_every_page_of_the_events() -> None:
    client, _ = scripted_rest(
        {
            EVENTS: [
                full_page(event_row("labeled")),
                [event_row("reopened", "2026-11-15T00:00:00Z")],
            ]
        }
    )

    assert client.reopened_at((323,)) == {323: datetime(2026, 11, 15, tzinfo=UTC)}


def test_the_reopen_time_of_each_candidate_is_read_from_its_own_events() -> None:
    client, _ = scripted_rest(
        {
            EVENTS: [[event_row("reopened", "2026-11-12T00:00:00Z")]],
            f"{ISSUES}/340/events": [[event_row("closed")]],
        }
    )

    assert client.reopened_at((323, 340)) == {323: datetime(2026, 11, 12, tzinfo=UTC), 340: None}


def test_the_reopen_time_of_no_candidate_costs_no_round_trip() -> None:
    client, asked = scripted_rest({})

    assert (client.reopened_at(()), asked) == ({}, [])


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param([event_row(None)], id="event-not-text"),
        pytest.param([{"created_at": MERGED}], id="event-missing"),
        pytest.param([event_row("reopened", None)], id="reopened-without-time"),
        pytest.param([event_row("reopened", "yesterday")], id="reopened-time-not-rfc3339"),
        pytest.param(
            [event_row("reopened", "9999-99-99T00:00:00Z")], id="reopened-time-not-a-date"
        ),
        pytest.param([event_row("reopened", 5)], id="reopened-time-not-text"),
        pytest.param(["a row of text"], id="row-not-an-object"),
    ],
)
def test_the_reopen_time_fails_loud_on_an_event_it_cannot_read(rows: list[object]) -> None:
    client, _ = scripted_rest({EVENTS: [rows]})

    with pytest.raises(forge.ForgeMalformedResponseError, match="malformed issue event"):
        client.reopened_at((323,))
