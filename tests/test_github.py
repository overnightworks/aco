"""Behavior of the GitHub adapter (`aco.github`): `GitHubForge`'s
reader/writer methods, repository discovery, and the `gh` process boundary it
wraps. CLI wiring that merely drives a forge through `cli.py` -- including
tests that build a `GitHubForge` only to hand it to `board_read.build_board`/
`issue_claim.main` -- stays in `tests/test_cli.py`."""

import base64
import dataclasses
import json
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from board_fixtures import REPOSITORY
from github_fixtures import LANDING_BRANCH, MERGE_COMMIT_SHA
from github_pages import (
    api_head,
    api_pull_request,
    board_issue_page_client,
    listing_answer,
    listing_runner,
    paged_listing,
    raw_board_issue,
)
from process_fixtures import UnstoppableProcess, reap

from aco import forge, github, process, workboard
from aco.body import ItemKind
from aco.protocol import ClaimError

GitHubForge = github.GitHubForge


def test_only_the_github_adapters_speak_gh_argv() -> None:
    """Source check, not a runtime guarantee: import-linter's module contract
    cannot see an argv string, so "only the adapters speak `gh`" is proven by
    grepping every other module of the package, enumerated so that a new module
    is covered the day it is added, for the literal command name instead."""
    package = Path(__file__).parent.parent / "src" / "aco"
    adapters = {"github", "github_search", "github_probe"}
    others = sorted(p for p in package.glob("*.py") if p.stem not in adapters)
    assert len(others) >= 7
    for module in others:
        assert '"gh"' not in module.read_text(), f"{module.name} must not construct a gh argv"


def test_github_adapter_reads_the_native_issue_type_and_sub_issue_counts() -> None:
    client = board_issue_page_client(
        raw_board_issue(kind="Container", childrenClosed=1, childrenTotal=2)
    )

    issues = client.list_open_board_issues()

    assert issues[0].kind is ItemKind.CONTAINER
    assert issues[0].children_closed == 1
    assert issues[0].children_total == 2


def test_github_adapter_reads_an_unrecognized_issue_type_as_no_kind() -> None:
    client = board_issue_page_client(raw_board_issue(kind="Epic"))

    issues = client.list_open_board_issues()

    assert issues[0].kind is None


def test_github_adapter_reads_a_container_with_zero_children_as_a_real_state() -> None:
    """`0/0` must survive as a real container state, never as the forge
    saying nothing (the malformed-mixed-presence check would otherwise be
    indistinguishable from a genuinely empty container)."""
    client = board_issue_page_client(
        raw_board_issue(kind="Container", childrenClosed=0, childrenTotal=0)
    )

    issues = client.list_open_board_issues()

    assert issues[0].children_closed == 0
    assert issues[0].children_total == 0


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"childrenClosed": 1}, id="total-missing"),
        pytest.param({"childrenTotal": 2}, id="closed-missing"),
        pytest.param({"childrenClosed": -1, "childrenTotal": 2}, id="closed-negative"),
        pytest.param({"childrenClosed": 3, "childrenTotal": 2}, id="closed-exceeds-total"),
        pytest.param({"childrenClosed": True, "childrenTotal": 2}, id="closed-is-a-bool"),
        pytest.param({"kind": 5}, id="kind-not-a-string"),
        pytest.param({"childrenClosed": 2, "childrenTotal": True}, id="total-is-a-bool"),
        pytest.param({"childrenClosed": 2, "childrenTotal": -1}, id="total-negative"),
    ],
)
def test_github_adapter_fails_loud_on_a_malformed_board_issue(
    overrides: dict[str, object],
) -> None:
    client = board_issue_page_client(raw_board_issue(**overrides))

    with pytest.raises(ClaimError, match="malformed board issue"):
        client.list_open_board_issues()


def test_github_adapter_fails_loud_when_a_board_issue_is_not_an_object() -> None:
    client = GitHubForge(
        github.repository_id(REPOSITORY),
        run=listing_runner(lambda arguments, input_data=None: '"not an object"'),
    )

    with pytest.raises(ClaimError, match="malformed board issue"):
        client.list_open_board_issues()


def test_github_adapter_reads_every_board_page_the_link_header_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(github, "ISSUES_PER_PAGE", 2)
    client = board_issue_page_client(*(raw_board_issue(number=number) for number in (1, 2, 3)))

    assert [issue.number for issue in client.list_open_board_issues()] == [1, 2, 3]


def test_github_adapter_accepts_pretty_and_ansi_colored_json() -> None:
    """`gh` pretty-prints and colorizes when it believes it writes to a TTY;
    the adapter reads that back as the same values as compact NDJSON."""
    pretty = (
        json.dumps(raw_board_issue(number=1), indent=2)
        + "\n"
        + json.dumps(raw_board_issue(number=2), indent=2)
    )
    client = GitHubForge(
        github.repository_id(REPOSITORY),
        run=listing_runner(lambda arguments, input_data=None: f"\x1b[32m{pretty}\x1b[0m"),
    )

    assert [issue.number for issue in client.list_open_board_issues()] == [1, 2]


def test_github_adapter_accepts_concatenated_pretty_json_objects() -> None:
    """Pretty-printed objects can arrive with no separator at all between
    them, which is neither NDJSON nor a JSON array."""
    raw = json.dumps(raw_board_issue(number=1), indent=2) + json.dumps(
        raw_board_issue(number=2), indent=2
    )
    client = GitHubForge(
        github.repository_id(REPOSITORY), run=listing_runner(lambda arguments, input_data=None: raw)
    )

    assert [issue.number for issue in client.list_open_board_issues()] == [1, 2]


def test_github_adapter_retypes_an_issue_by_its_type_name() -> None:
    """`set_item_kind` PATCHes the organization's type by name,
    the field `create_issue` writes, and reads the type GitHub kept back."""
    observed: list[tuple[list[str], bytes | None]] = []

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        observed.append((arguments, input_data))
        return "Container\n"

    client = GitHubForge(github.repository_id(REPOSITORY), run=fake_run)

    client.set_item_kind(484, ItemKind.CONTAINER)

    assert observed == [
        (
            [
                "api",
                "--method",
                "PATCH",
                f"repos/{REPOSITORY}/issues/484",
                "--input",
                "-",
                "--jq",
                ".type.name",
            ],
            json.dumps({"type": "Container"}).encode("utf-8"),
        )
    ]


def test_github_adapter_fails_loud_when_github_drops_the_new_type() -> None:
    """GitHub drops the type silently without push access: the read-back
    type still says Task, so the retype raises by name instead of passing."""
    client = GitHubForge(github.repository_id(REPOSITORY), run=lambda *_a, **_k: "Task\n")

    with pytest.raises(ClaimError, match=r"GitHub did not set #484's type Container"):
        client.set_item_kind(484, ItemKind.CONTAINER)


def test_github_adapter_creates_a_child_and_links_it_as_a_sub_issue() -> None:
    """Composed from `create_issue` and `link_child`: the create POST,
    the id read `link_child` needs for an issue it did not just create
    itself, and the sub-issue POST."""
    observed: list[tuple[list[str], bytes | None]] = []

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        observed.append((arguments, input_data))
        if arguments[2] == "POST" and arguments[3].endswith("/issues"):
            return json.dumps({"id": 555444, "number": 101, "type": {"name": "Task"}})
        if arguments[1] == f"repos/{REPOSITORY}/issues/101":
            return "555444"
        return ""

    client = GitHubForge(github.repository_id(REPOSITORY), run=fake_run)

    issue_body = "Parent: #79\n"

    child = client.create_child(parent=79, title="Scheibe 4", body=issue_body, kind=ItemKind.TASK)

    assert child == 101
    assert observed == [
        (
            ["api", "--method", "POST", f"repos/{REPOSITORY}/issues", "--input", "-"],
            json.dumps({"title": "Scheibe 4", "body": issue_body, "type": "Task"}).encode("utf-8"),
        ),
        (["api", f"repos/{REPOSITORY}/issues/101", "--jq", ".id"], None),
        (
            ["api", "--method", "POST", f"repos/{REPOSITORY}/issues/79/sub_issues", "--input", "-"],
            json.dumps({"sub_issue_id": 555444}).encode("utf-8"),
        ),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("not json", id="invalid-json"),
        pytest.param(json.dumps({"id": 1}), id="missing-number"),
        pytest.param(json.dumps({"id": 1, "number": True}), id="number-is-a-bool"),
    ],
)
def test_github_adapter_fails_loud_on_a_malformed_created_child(payload: str) -> None:
    client = GitHubForge(github.repository_id(REPOSITORY), run=lambda *_a, **_k: payload)

    with pytest.raises(ClaimError, match=r"created.issue"):
        client.create_child(parent=79, title="Scheibe 4", body="", kind=ItemKind.TASK)


def test_github_adapter_names_the_created_child_when_the_relation_post_fails() -> None:
    """The issue exists once `create_child`'s first write returns; a second
    write failing after that must name the surviving child,
    never just surface the raw relation-POST error."""

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        if arguments[2] == "POST" and arguments[3].endswith("/issues"):
            return json.dumps({"id": 555444, "number": 101, "type": {"name": "Task"}})
        raise forge.ForgeError("HTTP 422 could not create sub-issue relation")

    client = GitHubForge(github.repository_id(REPOSITORY), run=fake_run)

    with pytest.raises(forge.ForgePartialChildCreationError) as excinfo:
        client.create_child(parent=79, title="Scheibe 4", body="", kind=ItemKind.TASK)

    assert excinfo.value.created == 101
    assert excinfo.value.parent == 79


@pytest.mark.parametrize("returned_type_name", ["Task", "task"], ids=["github-case", "org-case"])
def test_github_adapter_creates_an_issue_without_linking_it_as_a_child(
    returned_type_name: str,
) -> None:
    """`create_issue` is `item new`'s own write without `--parent` and
    `create_child`'s first write: one POST carrying the issue type by
    name, no sub-issue relation. The returned type is read as the board
    reads it, so an org's own casing of the name still counts as set."""
    observed: list[tuple[list[str], bytes | None]] = []

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        observed.append((arguments, input_data))
        return json.dumps({"id": 555444, "number": 101, "type": {"name": returned_type_name}})

    client = GitHubForge(github.repository_id(REPOSITORY), run=fake_run)

    issue_body = "Ship slice four.\n"

    number = client.create_issue(title="Scheibe 4", body=issue_body, kind=ItemKind.TASK)

    assert number == 101
    assert observed == [
        (
            ["api", "--method", "POST", f"repos/{REPOSITORY}/issues", "--input", "-"],
            json.dumps({"title": "Scheibe 4", "body": issue_body, "type": "Task"}).encode("utf-8"),
        )
    ]


@pytest.mark.parametrize(
    "created",
    [
        pytest.param({"id": 555444, "number": 101, "type": None}, id="type-null"),
        pytest.param({"id": 555444, "number": 101, "type": {"name": "Bug"}}, id="another-type"),
        pytest.param({"number": 101}, id="number-only"),
    ],
)
def test_github_adapter_names_the_created_issue_github_left_without_its_type(
    created: dict[str, object],
) -> None:
    """GitHub's REST create drops `type` silently without push access:
    the issue exists anyway, so the refusal names it and the type
    still to set, never a plain success -- nor a generic malformed-response
    error once the response has named the created issue."""
    payload = json.dumps(created)
    client = GitHubForge(github.repository_id(REPOSITORY), run=lambda *_a, **_k: payload)

    with pytest.raises(forge.ForgeIssueTypeNotSetError) as excinfo:
        client.create_issue(title="Scheibe 4", body="", kind=ItemKind.CONTAINER)

    assert (excinfo.value.created, str(excinfo.value)) == (
        101,
        "created #101 but GitHub did not set its type Container",
    )


def closed_issue_row(
    number: int, closed_at: str, *, is_pull_request: bool = False
) -> dict[str, object]:
    return {
        "number": number,
        "title": f"Issue {number}",
        "closedAt": closed_at,
        "isPullRequest": is_pull_request,
    }


def test_github_adapter_lists_only_issues_closed_since_the_cutoff() -> None:
    """The twin search's closed half: GitHub's `since` filters by the
    last update, so an issue closed before the cutoff but touched after it
    is dropped here, and a pull request never counts as an issue."""
    observed: list[list[str]] = []
    rows = (
        closed_issue_row(7, "2026-09-20T10:00:00Z"),
        closed_issue_row(8, "2026-08-01T10:00:00Z"),
        closed_issue_row(9, "2026-09-21T10:00:00Z", is_pull_request=True),
    )

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        observed.append(arguments)
        return "\n".join(json.dumps(row) for row in rows)

    client = GitHubForge(github.repository_id(REPOSITORY), run=listing_runner(fake_run))
    since = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)

    closed = client.list_recently_closed_issues(since)

    assert closed == (forge.ClosedIssue(7, "Issue 7"),)
    assert observed == [
        [
            "api",
            f"repos/{REPOSITORY}/issues?state=closed&since=2026-08-27T10:00:00Z&per_page=100",
            "-i",
            "--jq",
            '.[] | {number,title,closedAt:.closed_at,isPullRequest:has("pull_request")}',
        ]
    ]


@pytest.mark.parametrize(
    "row",
    [
        pytest.param([], id="not-an-object"),
        pytest.param({**closed_issue_row(7, "2026-09-20T10:00:00Z"), "number": 0}, id="number"),
        pytest.param({**closed_issue_row(7, "2026-09-20T10:00:00Z"), "title": None}, id="title"),
        pytest.param(closed_issue_row(7, "20.09.2026"), id="closed-at"),
        pytest.param(
            {**closed_issue_row(7, "2026-09-20T10:00:00Z"), "isPullRequest": None},
            id="pull-request-flag",
        ),
    ],
)
def test_github_adapter_fails_loud_on_a_malformed_closed_issue(row: object) -> None:
    client = GitHubForge(
        github.repository_id(REPOSITORY),
        run=listing_runner(lambda *_arguments, **_options: json.dumps(row)),
    )
    since = datetime(2026, 8, 27, tzinfo=UTC)

    with pytest.raises(forge.ForgeMalformedResponseError, match="malformed closed issue"):
        client.list_recently_closed_issues(since)


def test_github_adapter_links_an_existing_child_by_reading_its_internal_id() -> None:
    """`link_child` records an already-existing issue as a sub-issue --
    the write a repeat `cut` uses to adopt an orphan `create_child` left
    behind. GitHub's sub-issue POST wants the child's internal id, not its
    issue number, so this reads it first."""
    observed: list[tuple[list[str], bytes | None]] = []

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        observed.append((arguments, input_data))
        return "555444" if arguments[1].endswith("/issues/101") else ""

    client = GitHubForge(github.repository_id(REPOSITORY), run=fake_run)

    client.link_child(79, 101)

    assert observed == [
        (["api", f"repos/{REPOSITORY}/issues/101", "--jq", ".id"], None),
        (
            ["api", "--method", "POST", f"repos/{REPOSITORY}/issues/79/sub_issues", "--input", "-"],
            json.dumps({"sub_issue_id": 555444}).encode("utf-8"),
        ),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("not a number", id="not-numeric"),
        pytest.param("0", id="zero"),
    ],
)
def test_github_adapter_fails_loud_on_a_malformed_child_identifier(payload: str) -> None:
    client = GitHubForge(github.repository_id(REPOSITORY), run=lambda *_a, **_k: payload)

    with pytest.raises(ClaimError, match="malformed issue id"):
        client.link_child(79, 101)


_LANDING_COMMENTS_PATH = f"repos/{REPOSITORY}/issues/79/comments"
_LANDING_COMMENTS_READ = [
    "api",
    f"{_LANDING_COMMENTS_PATH}?per_page=100",
    "-i",
    "--jq",
    ".[] | {body}",
]
_LANDING_COMMENTS_SECOND_READ = [
    "api",
    f"{_LANDING_COMMENTS_PATH}?per_page=100&page=2",
    "-i",
    "--jq",
    ".[] | {body}",
]


def test_github_adapter_closes_a_landed_item_with_a_comment_first() -> None:
    """`close_landed_item` reads its own past comments first (a repeat-safety check that finds
    none here), then posts the comment, then closes -- exactly the order
    its own docstring promises."""
    observed: list[tuple[list[str], bytes | None]] = []

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        observed.append((arguments, input_data))
        return ""

    client = GitHubForge(github.repository_id(REPOSITORY), run=listing_runner(fake_run))

    client.close_landed_item(79, pull_request=101)

    assert observed == [
        (_LANDING_COMMENTS_READ, None),
        (
            ["api", _LANDING_COMMENTS_PATH, "--input", "-"],
            json.dumps({"body": github.landing_comment(101)}).encode("utf-8"),
        ),
        (
            ["api", "--method", "PATCH", f"repos/{REPOSITORY}/issues/79", "--input", "-"],
            json.dumps({"state": "closed"}).encode("utf-8"),
        ),
    ]


def test_github_adapter_closing_a_landed_item_never_reaches_close_when_the_comment_fails() -> None:
    """The comment lands first: a transient failure
    there must never reach the close call, leaving the issue open with no
    record of why it is about to close -- worse than leaving it open with
    the comment already explaining the pending landing."""
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        calls.append(arguments)
        if input_data is None:
            return ""
        raise forge.ForgeError("HTTP 500 comment failed")

    client = GitHubForge(github.repository_id(REPOSITORY), run=listing_runner(fake_run))

    with pytest.raises(forge.ForgeError, match="comment failed"):
        client.close_landed_item(79, pull_request=101)

    assert calls == [
        _LANDING_COMMENTS_READ,
        ["api", _LANDING_COMMENTS_PATH, "--input", "-"],
    ]


def test_github_adapter_closing_a_landed_item_skips_a_repeated_comment() -> None:
    """A rerun that finds its own `landed by PR #<n>` comment
    already posted -- the comment landed but a prior run crashed before the
    close -- skips straight to the close instead of posting it twice."""
    calls: list[list[str]] = []
    already_posted = json.dumps({"body": github.landing_comment(101)})

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        calls.append(arguments)
        return already_posted if input_data is None else ""

    client = GitHubForge(github.repository_id(REPOSITORY), run=listing_runner(fake_run))

    client.close_landed_item(79, pull_request=101)

    assert calls == [
        _LANDING_COMMENTS_READ,
        ["api", "--method", "PATCH", f"repos/{REPOSITORY}/issues/79", "--input", "-"],
    ]


def test_github_adapter_finds_a_landing_comment_past_the_first_page() -> None:
    """With 100 unrelated comments filling the first page ahead of this run's own landing
    comment -- posted by a run whose close then failed -- a rerun must follow the listing to the
    second page, find it and skip straight to closing, never posting it a second time."""
    comments = [
        *({"body": f"unrelated comment {index}"} for index in range(100)),
        {"body": github.landing_comment(101)},
    ]
    calls: list[list[str]] = []
    close_should_fail = True

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        calls.append(arguments)
        nonlocal close_should_fail
        if input_data is None:
            return paged_listing(arguments, comments)
        if close_should_fail:
            close_should_fail = False
            raise forge.ForgeError("HTTP 500 close failed")
        return ""

    client = GitHubForge(github.repository_id(REPOSITORY), run=fake_run)

    with pytest.raises(forge.ForgeError, match="close failed"):
        client.close_landed_item(79, pull_request=101)
    client.close_landed_item(79, pull_request=101)

    close = ["api", "--method", "PATCH", f"repos/{REPOSITORY}/issues/79", "--input", "-"]
    assert calls == [
        _LANDING_COMMENTS_READ,
        _LANDING_COMMENTS_SECOND_READ,
        close,
        _LANDING_COMMENTS_READ,
        _LANDING_COMMENTS_SECOND_READ,
        close,
    ]


def test_github_adapter_fails_loud_on_a_malformed_issue_comment() -> None:
    client = GitHubForge(
        github.repository_id(REPOSITORY),
        run=listing_runner(lambda arguments, input_data=None: json.dumps({"body": 5})),
    )

    with pytest.raises(ClaimError, match="malformed issue comment"):
        client.close_landed_item(79, pull_request=101)


_READINESS_PULL_REQUEST_PATH = f"repos/{REPOSITORY}/pulls/57"
_READINESS_CHECK_RUNS_PATH = f"repos/{REPOSITORY}/commits/{MERGE_COMMIT_SHA}/check-runs"
_READINESS_STATUS_PATH = f"repos/{REPOSITORY}/commits/{MERGE_COMMIT_SHA}/status"


def _pull_request(**fields: object) -> dict[str, object]:
    return (
        dict(state="open", draft=False, headSha=MERGE_COMMIT_SHA, mergeableState="clean") | fields
    )


def _readiness_client(
    *,
    check_run_pages: dict[int, list[dict[str, object]]],
    statuses: list[dict[str, object]],
    mergeable_state: str = "clean",
) -> tuple[GitHubForge, list[list[str]]]:
    """`statuses` names each combined-status context and its own
    `conclusion` (`None` for pending, else the state string) the way
    `landing_readiness`'s own result reads it; this fixture derives the
    endpoint's own aggregate `state`/`total_count` summary from that same
    list -- `pending` if any conclusion is still `None`, else `failure` if
    any is non-`success`, else `success` -- so a caller unions readiness
    exactly as before while the two real calls (summary, then a paginated
    names page only when the summary is not passing) stay faithful to
    `_combined_status_checks`'s own shape."""
    calls: list[list[str]] = []
    pull_request = json.dumps(_pull_request(mergeableState=mergeable_state))
    conclusions = [row.get("conclusion") for row in statuses]
    if not statuses:
        combined_state = "pending"  # GitHub's own default state for zero statuses.
    elif any(conclusion is None for conclusion in conclusions):
        combined_state = "pending"
    elif any(conclusion != "success" for conclusion in conclusions):
        combined_state = "failure"
    else:
        combined_state = "success"
    summary = json.dumps({"state": combined_state, "total": len(statuses)})
    name_page = [{"name": row["name"]} for row in statuses]

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        calls.append(arguments)
        path = arguments[1]
        if path == _READINESS_PULL_REQUEST_PATH:
            return pull_request
        if path.startswith(_READINESS_CHECK_RUNS_PATH):
            page = int(parse_qs(urlsplit(path).query).get("page", ["1"])[0])
            following = f"{_READINESS_CHECK_RUNS_PATH}?per_page=100&page={page + 1}"
            return listing_answer(
                arguments,
                "\n".join(json.dumps(row) for row in check_run_pages.get(page, [])),
                next_path=following if page + 1 in check_run_pages else None,
            )
        if path == _READINESS_STATUS_PATH:
            return summary
        assert path.startswith(_READINESS_STATUS_PATH)
        return listing_answer(arguments, "\n".join(json.dumps(row) for row in name_page))

    return GitHubForge(github.repository_id(REPOSITORY), run=fake_run), calls


def test_github_adapter_reads_landing_readiness_from_the_pull_request_and_its_checks() -> None:
    """`landing_readiness` reads the pull request itself (open state, head sha, mergeable
    state), the check-runs endpoint against that same head sha, and the combined commit
    status -- never `gh pr checks`, which reads the pull request's current head rather than
    the one this call pins."""
    client, calls = _readiness_client(
        check_run_pages={1: [{"id": 1, "name": "build", "conclusion": "success"}]},
        statuses=[],
    )

    readiness = client.landing_readiness(57)

    assert calls == [
        [
            "api",
            _READINESS_PULL_REQUEST_PATH,
            "--jq",
            "{state,draft:.draft,headSha:.head.sha,mergeableState:.mergeable_state}",
        ],
        [
            "api",
            f"{_READINESS_CHECK_RUNS_PATH}?per_page=100",
            "-i",
            "--jq",
            '.check_runs[] | {id,name,suite:(if .app.slug == "github-actions" '
            'then .check_suite.id else null end),conclusion:(if .status == "completed" '
            "then .conclusion else null end)}",
        ],
        [
            "api",
            _READINESS_STATUS_PATH,
            "--jq",
            "{state:.state,total:.total_count}",
        ],
    ]
    assert readiness == forge.LandingReadiness(
        57, True, False, MERGE_COMMIT_SHA, "clean", (forge.CheckRun("build", "success"),)
    )


def test_github_adapter_reads_a_check_run_reported_only_on_a_later_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A check run GitHub reports only on page
    two of `check-runs` still counts toward readiness -- a merge must not
    become possible just because a run sorted past the first page."""
    monkeypatch.setattr(github, "ISSUES_PER_PAGE", 1)
    client, _calls = _readiness_client(
        check_run_pages={
            1: [{"id": 1, "name": "build", "conclusion": "success"}],
            2: [{"id": 2, "name": "lint", "conclusion": None}],
        },
        statuses=[],
    )

    readiness = client.landing_readiness(57)

    assert readiness.checks == (
        forge.CheckRun("build", "success"),
        forge.CheckRun("lint", None),
    )


def test_github_adapter_reads_a_pending_status_context() -> None:
    """An external status context (SonarCloud,
    say) still `pending` reads as a not-yet-completed check, exactly as a
    check run with no conclusion does."""
    client, _calls = _readiness_client(
        check_run_pages={1: [{"id": 1, "name": "build", "conclusion": "success"}]},
        statuses=[{"name": "sonarcloud", "conclusion": None}],
    )

    readiness = client.landing_readiness(57)

    assert readiness.checks == (
        forge.CheckRun("build", "success"),
        forge.CheckRun("sonarcloud", None),
    )


def test_github_adapter_reads_a_failing_status_context() -> None:
    """An external status context that failed
    reads as a completed, non-successful check, so `aco land`'s preflight
    refuses on it exactly as it would a failed check run."""
    client, _calls = _readiness_client(
        check_run_pages={1: [{"id": 1, "name": "build", "conclusion": "success"}]},
        statuses=[{"name": "sonarcloud", "conclusion": "failure"}],
    )

    readiness = client.landing_readiness(57)

    assert readiness.checks == (
        forge.CheckRun("build", "success"),
        forge.CheckRun("sonarcloud", "failure"),
    )


def _raw_status_client(*, summary: str, names_page: str) -> GitHubForge:
    """A forge whose open pull request has no check runs and whose
    combined-status endpoint answers the raw `summary` text, then the raw
    `names_page` text for its paginated names read."""

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        path = arguments[1]
        if path == _READINESS_PULL_REQUEST_PATH:
            return json.dumps(_pull_request())
        if path.startswith(_READINESS_CHECK_RUNS_PATH):
            return ""
        if path == _READINESS_STATUS_PATH:
            return summary
        assert path.startswith(_READINESS_STATUS_PATH)
        return names_page

    return GitHubForge(github.repository_id(REPOSITORY), run=listing_runner(fake_run))


def test_github_adapter_reads_a_pending_combined_status_aggregate_with_an_empty_names_page() -> (
    None
):
    """The combined-status endpoint's own
    aggregate `state` decides the verdict, never a per-context
    reconstruction of it -- a `pending` aggregate with `total_count > 0`
    still blocks even when its own `statuses` page comes back empty (a
    context posted after this read, say), named under
    `EXTERNAL_STATUS_FALLBACK_NAME` rather than read as "no checks" and
    passed silently."""
    client = _raw_status_client(summary=json.dumps({"state": "pending", "total": 1}), names_page="")

    readiness = client.landing_readiness(57)

    assert readiness.checks == (forge.CheckRun(github.EXTERNAL_STATUS_FALLBACK_NAME, None),)


@pytest.mark.parametrize("aggregate", ["failure", "error"])
def test_github_adapter_reads_a_blocking_combined_status_aggregate(aggregate: str) -> None:
    """A `failure` or `error` aggregate from the combined-status endpoint blocks,
    named from whatever context its own paginated `statuses` does carry and
    read verbatim as the check's conclusion."""
    client = _raw_status_client(
        summary=json.dumps({"state": aggregate, "total": 1}),
        names_page=json.dumps({"name": "sonarcloud"}),
    )

    readiness = client.landing_readiness(57)

    assert readiness.checks == (forge.CheckRun("sonarcloud", aggregate),)


def test_github_adapter_reads_a_successful_combined_status_aggregate_as_a_named_check() -> None:
    """A `success` aggregate with statuses
    present is itself a named, successful check -- a pull request whose
    only CI is a combined status (no check runs at all) must still expose
    it, or `aco land`'s preflight misreads a green pull request as exposing
    no CI checks and refuses it."""
    client, _calls = _readiness_client(
        check_run_pages={},
        statuses=[{"name": "sonarcloud", "conclusion": "success"}],
    )

    readiness = client.landing_readiness(57)

    assert readiness.checks == (forge.CheckRun("sonarcloud", "success"),)


@pytest.mark.parametrize(
    ("summary", "names_page", "message"),
    [
        pytest.param(
            json.dumps({"state": "success", "total": 0}) * 2,
            "",
            "malformed commit status summary",
            id="summary-read-is-exactly-one-json-value",
        ),
        pytest.param(
            json.dumps({"state": "success", "total": -1}),
            "",
            "malformed commit status summary",
            id="summary-fields-fail-their-shape-check",
        ),
        pytest.param(
            json.dumps({"state": "failure", "total": 1}),
            json.dumps({"name": ""}),
            r"malformed commit status$",
            id="names-page-entry-has-no-usable-name",
        ),
    ],
)
def test_github_adapter_landing_rejects_a_malformed_combined_status_read(
    summary: str, names_page: str, message: str
) -> None:
    """A combined-status read that fails its shape check refuses loud, never
    read as a valid aggregate verdict or silently dropped from the refusal
    sentence it would otherwise name."""
    client = _raw_status_client(summary=summary, names_page=names_page)

    with pytest.raises(ClaimError, match=message):
        client.landing_readiness(57)


def test_github_adapter_accepts_a_mergeable_state_it_has_never_seen_before() -> None:
    """`mergeable_state` is GitHub's own open vocabulary --
    read verbatim, never a closed set this adapter could refuse a genuine,
    simply-not-yet-enumerated answer against."""

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        path = arguments[1]
        if "pulls" in path:
            return json.dumps(_pull_request(mergeableState="exploding"))
        if path.startswith(_READINESS_CHECK_RUNS_PATH):
            return ""
        if path == _READINESS_STATUS_PATH:
            return json.dumps({"state": "success", "total": 0})
        return ""

    client = GitHubForge(github.repository_id(REPOSITORY), run=listing_runner(fake_run))

    readiness = client.landing_readiness(57)

    assert readiness.mergeable_state == "exploding"


def test_github_adapter_fails_loud_on_an_empty_mergeable_state() -> None:
    client = GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: json.dumps(_pull_request(mergeableState="")),
    )

    with pytest.raises(ClaimError, match="malformed pull request"):
        client.landing_readiness(57)


@pytest.mark.parametrize("method", sorted(workboard.LANDING_MERGE_METHODS))
def test_github_adapter_merges_a_pull_request_with_a_pinned_sha(
    method: workboard.MergeMethod,
) -> None:
    """`merge_landing` merges through `gh api --method PUT
    pulls/<n>/merge`, never `gh pr merge`, which re-reads the pull
    request's own current head instead of the sha this call pins; the
    method `land` chose, a merge commit or a squash, is sent along."""
    observed: list[tuple[list[str], bytes | None]] = []

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        observed.append((arguments, input_data))
        return json.dumps({"merged": True, "sha": MERGE_COMMIT_SHA})

    client = GitHubForge(github.repository_id(REPOSITORY), run=fake_run)

    sha = client.merge_landing(
        57,
        head_sha=MERGE_COMMIT_SHA,
        method=method,
        title="Merge pull request #57",
        body="Work-Item: #42\n",
    )

    assert sha == MERGE_COMMIT_SHA
    assert observed == [
        (
            ["api", "--method", "PUT", f"repos/{REPOSITORY}/pulls/57/merge", "--input", "-"],
            json.dumps(
                {
                    "sha": MERGE_COMMIT_SHA,
                    "merge_method": method.value,
                    "commit_title": "Merge pull request #57",
                    "commit_message": "Work-Item: #42\n",
                }
            ).encode("utf-8"),
        )
    ]


@pytest.mark.parametrize(
    ("settings", "allowed"),
    [
        pytest.param(
            {"merge": True, "squash": True, "rebase": True},
            frozenset(workboard.MergeMethod),
            id="all-three",
        ),
        pytest.param(
            {"merge": False, "squash": True, "rebase": False},
            frozenset({workboard.MergeMethod.SQUASH}),
            id="squash",
        ),
        pytest.param(
            {"merge": False, "squash": False, "rebase": True},
            frozenset({workboard.MergeMethod.REBASE}),
            id="rebase",
        ),
        pytest.param(
            {"merge": None, "squash": None, "rebase": None},
            None,
            id="withheld-without-push-rights",
        ),
    ],
)
def test_github_adapter_reads_the_repositorys_allowed_merge_methods(
    settings: dict[str, object], allowed: frozenset[workboard.MergeMethod] | None
) -> None:
    """`allowed_merge_methods` reads the repository's own
    `allow_merge_commit`/`allow_squash_merge`/`allow_rebase_merge`, and
    `None` where GitHub withholds them from a token without push rights."""
    observed: list[list[str]] = []

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        observed.append(arguments)
        return json.dumps(settings)

    client = GitHubForge(github.repository_id(REPOSITORY), run=fake_run)

    assert client.allowed_merge_methods() == allowed
    assert observed == [
        [
            "api",
            f"repos/{REPOSITORY}",
            "--jq",
            "{merge:.allow_merge_commit,squash:.allow_squash_merge,rebase:.allow_rebase_merge}",
        ]
    ]


def _read_merge_settings(client: GitHubForge) -> object:
    return client.allowed_merge_methods()


def _read_main_merge_rules(client: GitHubForge) -> object:
    return client.merge_rules("main").merge_methods


def _pull_request_rule(allowed_merge_methods: object) -> str:
    rule = {"type": "pull_request", "parameters": {"allowed_merge_methods": allowed_merge_methods}}
    return json.dumps(rule) + "\n"


_MALFORMED_SETTINGS = "malformed repository merge settings"
_MALFORMED_RULE = "malformed branch merge rule"


@pytest.mark.parametrize(
    ("read", "answer", "refusal"),
    [
        pytest.param(
            _read_merge_settings,
            json.dumps({"merge": True, "squash": True, "rebase": "yes"}),
            _MALFORMED_SETTINGS,
            id="settings-not-a-boolean",
        ),
        pytest.param(
            _read_merge_settings,
            json.dumps({"merge": False, "squash": True, "rebase": None}),
            _MALFORMED_SETTINGS,
            id="settings-half-withheld",
        ),
        pytest.param(
            _read_merge_settings,
            json.dumps([True, True]),
            _MALFORMED_SETTINGS,
            id="settings-not-an-object",
        ),
        pytest.param(
            _read_main_merge_rules,
            _pull_request_rule(["squash", "fast-forward"]),
            _MALFORMED_RULE,
            id="rule-unknown-method",
        ),
        pytest.param(
            _read_main_merge_rules,
            _pull_request_rule([["squash"]]),
            _MALFORMED_RULE,
            id="rule-not-a-method-name",
        ),
        pytest.param(
            _read_main_merge_rules,
            _pull_request_rule("squash"),
            _MALFORMED_RULE,
            id="rule-not-a-list",
        ),
        pytest.param(_read_main_merge_rules, '"squash"', _MALFORMED_RULE, id="rule-not-an-object"),
        pytest.param(
            _read_main_merge_rules,
            json.dumps({"type": "pull_request", "parameters": ["squash"]}),
            _MALFORMED_RULE,
            id="rule-parameters-not-an-object",
        ),
    ],
)
def test_github_adapter_fails_loud_on_malformed_merge_answers(
    read: Callable[[GitHubForge], object], answer: str, refusal: str
) -> None:
    """A merge-settings or branch-rule answer this
    adapter cannot read as merge methods fails loud rather than guessing."""
    client = GitHubForge(
        github.repository_id(REPOSITORY),
        run=listing_runner(lambda arguments, input_data=None: answer),
    )

    with pytest.raises(ClaimError, match=refusal):
        read(client)


_RULESETS_UPGRADE_MESSAGE = (
    "Upgrade to GitHub Pro or make this repository public to enable this feature."
)


def _branch_rules_refused_with(message: str, status: int = 403) -> GitHubForge:
    def refuse(arguments: list[str], *, input_data: bytes | None = None) -> str:
        raise forge.ForgePermissionDeniedError(f"gh: {message} (HTTP {status})")

    return GitHubForge(github.repository_id(REPOSITORY), run=refuse)


def test_github_adapter_reads_no_merge_rules_on_a_plan_without_rulesets() -> None:
    """A private repository on a plan without rulesets
    answers the branch-rules read with GitHub's own upgrade 403, which means
    no rule narrows the settings."""
    client = _branch_rules_refused_with(_RULESETS_UPGRADE_MESSAGE)

    assert client.merge_rules("main").merge_methods == ()


@pytest.mark.parametrize(
    ("message", "status"),
    [
        pytest.param("Resource not accessible by integration", 403, id="other-403"),
        pytest.param(_RULESETS_UPGRADE_MESSAGE, 401, id="upgrade-phrase-under-401"),
    ],
)
def test_github_adapter_fails_loud_on_any_other_branch_rules_refusal(
    message: str, status: int
) -> None:
    """Every other refusal of the branch-rules read fails
    loud rather than reading as no rules -- the upgrade phrase too, unless
    GitHub answered it with a 403."""
    client = _branch_rules_refused_with(message, status)

    with pytest.raises(forge.ForgePermissionDeniedError, match=f"HTTP {status}"):
        client.merge_rules("main")


@pytest.mark.parametrize(
    ("answer", "rules"),
    [
        pytest.param("", (), id="no-rule"),
        pytest.param(
            json.dumps({"type": "pull_request", "parameters": {}}),
            (),
            id="pull-request-rule-without-a-method-list",
        ),
        pytest.param(
            json.dumps({"type": "pull_request"}),
            (),
            id="pull-request-rule-without-parameters",
        ),
        pytest.param(json.dumps({"type": "deletion"}), (), id="rule-without-a-merge-restriction"),
        pytest.param(
            json.dumps({"type": "required_linear_history"}),
            (frozenset({workboard.MergeMethod.SQUASH, workboard.MergeMethod.REBASE}),),
            id="required-linear-history-drops-the-merge-commit",
        ),
        pytest.param(
            _pull_request_rule(["squash", "rebase"]) + _pull_request_rule(["squash"]),
            (
                frozenset({workboard.MergeMethod.SQUASH, workboard.MergeMethod.REBASE}),
                frozenset({workboard.MergeMethod.SQUASH}),
            ),
            id="two-rulesets",
        ),
    ],
)
def test_github_adapter_reads_the_default_branchs_merge_rules(
    answer: str, rules: tuple[frozenset[workboard.MergeMethod], ...]
) -> None:
    """`merge_rules` reads every rule on
    the branch through the branch-rules endpoint, one method set per
    `pull_request` rule carrying a method list and per
    `required_linear_history` rule, and an empty tuple where no rule
    restricts the methods."""
    observed: list[list[str]] = []

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        observed.append(arguments)
        return answer

    client = GitHubForge(github.repository_id(REPOSITORY), run=listing_runner(fake_run))

    assert client.merge_rules("main").merge_methods == rules
    assert observed == [
        [
            "api",
            f"repos/{REPOSITORY}/rules/branches/main?per_page=100",
            "-i",
            "--jq",
            ".[]",
        ]
    ]


def _file_contents_client(answer: str | forge.ForgeError) -> GitHubForge:
    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        if isinstance(answer, forge.ForgeError):
            raise answer
        return answer

    return GitHubForge(github.repository_id(REPOSITORY), run=run)


def test_github_adapter_reads_a_file_at_a_commit_from_its_base64_contents() -> None:
    """The contents API answers one base64 object --
    line-wrapped the way GitHub sends it -- and the adapter hands back the
    file's own text."""
    calls: list[list[str]] = []
    encoded = base64.encodebytes(b'storage = "github"\n').decode("ascii")

    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        calls.append(arguments)
        return json.dumps({"encoding": "base64", "content": encoded})

    client = GitHubForge(github.repository_id(REPOSITORY), run=run)

    text = client.file_at_commit(workboard.CONFIG_PATH, MERGE_COMMIT_SHA)

    assert text == 'storage = "github"\n'
    assert calls[0][1] == (
        f"repos/{REPOSITORY}/contents/{workboard.CONFIG_PATH.as_posix()}?ref={MERGE_COMMIT_SHA}"
    )


def test_github_adapter_reads_a_file_absent_at_a_commit_as_none() -> None:
    client = _file_contents_client(forge.ForgeNotFoundError("gh: Not Found (HTTP 404)"))

    assert client.file_at_commit(workboard.CONFIG_PATH, MERGE_COMMIT_SHA) is None


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(json.dumps([]), id="not-one-object"),
        pytest.param(json.dumps({"encoding": "none", "content": ""}), id="not-base64"),
        pytest.param(json.dumps({"encoding": "base64", "content": 5}), id="content-not-text"),
        pytest.param(json.dumps({"encoding": "base64", "content": "abc"}), id="bad-padding"),
        pytest.param(json.dumps({"encoding": "base64", "content": "/w=="}), id="not-utf-8"),
        pytest.param(json.dumps({"encoding": "base64", "content": "!!!!"}), id="not-alphabet"),
        pytest.param(json.dumps({"encoding": "base64", "content": "ä==="}), id="not-ascii"),
        pytest.param(json.dumps({"encoding": "base64", "content": "YW JjZA=="}), id="space"),
        pytest.param(json.dumps({"encoding": "base64", "content": "YW\tJjZA=="}), id="tab"),
        pytest.param(
            json.dumps({"encoding": "base64", "content": "YQ==\u00a0"}), id="not-ascii-whitespace"
        ),
    ],
)
def test_github_adapter_fails_loud_on_malformed_file_contents(answer: str) -> None:
    client = _file_contents_client(answer)
    path = workboard.CONFIG_PATH

    with pytest.raises(forge.ForgeMalformedResponseError, match="malformed file contents"):
        client.file_at_commit(path, MERGE_COMMIT_SHA)


def test_github_adapter_deletes_a_merged_branch() -> None:
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        calls.append(arguments)
        return ""

    client = GitHubForge(github.repository_id(REPOSITORY), run=fake_run)

    client.delete_branch(LANDING_BRANCH)

    assert calls == [
        ["api", "--method", "DELETE", f"repos/{REPOSITORY}/git/refs/heads/{LANDING_BRANCH}"]
    ]


@pytest.mark.parametrize(
    "decoded",
    [
        "HTTP 404 Not Found",
        "gh: Reference does not exist (HTTP 422)",
        "HTTP 422 Reference does not exist",
    ],
)
def test_github_adapter_deleting_an_already_absent_branch_is_idempotent(decoded: str) -> None:
    """Spec: LANDCMD-16. `gh api`'s real error text puts the message before the
    code (`gh: Reference does not exist (HTTP 422)`);
    the reversed order is covered alongside it so neither order regresses."""

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        raise forge.ForgeNotFoundError(decoded) if "404" in decoded else forge.ForgeError(decoded)

    client = GitHubForge(github.repository_id(REPOSITORY), run=fake_run)

    client.delete_branch(LANDING_BRANCH)


def test_github_adapter_delete_branch_reraises_an_unrelated_422() -> None:
    """Only GitHub's own "reference does not
    exist" 422 is idempotent absence; any other 422 -- a protected branch
    refusing the delete, say -- is a real failure `delete_branch` must
    still surface, not silently treat as already gone."""
    client = GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: (_ for _ in ()).throw(
            forge.ForgeError("HTTP 422 Validation Failed: branch is protected")
        ),
    )

    with pytest.raises(forge.ForgeError, match="branch is protected"):
        client.delete_branch(LANDING_BRANCH)


@pytest.mark.parametrize(
    "action",
    [
        pytest.param(lambda client: client.delete_branch(LANDING_BRANCH), id="delete-branch"),
        pytest.param(
            lambda client: client.merge_landing(
                57,
                head_sha=MERGE_COMMIT_SHA,
                method=workboard.MergeMethod.MERGE,
                title="t",
                body="Work-Item: #42\n",
            ),
            id="merge-landing",
        ),
    ],
)
def test_github_adapter_reraises_a_failure_unrelated_to_its_own_classification(
    action: Callable[[GitHubForge], object],
) -> None:
    """Both `delete_branch`'s idempotent-absence handling and
    `merge_landing`'s conflict translation only ever intercept their own
    named case; any other `ForgeError` -- a forbidden request, say -- passes
    through unchanged."""
    client = GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: (_ for _ in ()).throw(forge.ForgeError("HTTP 403")),
    )

    with pytest.raises(forge.ForgeError, match="403") as raised:
        action(client)

    assert type(raised.value) is forge.ForgeError


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("not a dict", id="not-a-dict"),
        pytest.param({"name": "", "conclusion": "success"}, id="empty-name"),
        pytest.param({"name": "build", "conclusion": ""}, id="empty-conclusion"),
        pytest.param({"name": "build", "conclusion": 5}, id="non-string-conclusion"),
    ],
)
def test_github_adapter_fails_loud_on_a_malformed_check_run(value: object) -> None:
    client = GitHubForge(
        github.repository_id(REPOSITORY), run=lambda arguments, input_data=None: ""
    )

    with pytest.raises(ClaimError, match="malformed check run"):
        client._check_run(value)


def test_github_adapter_fails_loud_on_a_malformed_readiness_response() -> None:
    """`landing_readiness` reads its pull request's own `--jq` filter as
    exactly one JSON value; more than one -- `gh`'s own paginated-array
    shape, say -- is a malformed pull request, not a valid readiness."""
    two_values = json.dumps({"state": "open"}) + json.dumps({"state": "closed"})
    client = GitHubForge(
        github.repository_id(REPOSITORY), run=lambda arguments, input_data=None: two_values
    )

    with pytest.raises(ClaimError, match="malformed pull request"):
        client.landing_readiness(57)


@pytest.mark.parametrize(
    "result",
    [
        pytest.param({"merged": False, "sha": MERGE_COMMIT_SHA}, id="not-merged"),
        pytest.param({"merged": True, "sha": "not-a-sha"}, id="malformed-sha"),
        pytest.param({"merged": True}, id="missing-sha"),
    ],
)
def test_github_adapter_fails_loud_on_a_malformed_merge_result(result: dict[str, object]) -> None:
    client = GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: json.dumps(result),
    )

    with pytest.raises(ClaimError, match="malformed merge result"):
        client.merge_landing(
            57,
            head_sha=MERGE_COMMIT_SHA,
            method=workboard.MergeMethod.MERGE,
            title="t",
            body="Work-Item: #42\n",
        )


def test_github_adapter_fails_loud_on_a_merge_result_with_more_than_one_value() -> None:
    two_values = json.dumps({"merged": True}) + json.dumps({"merged": True})
    client = GitHubForge(
        github.repository_id(REPOSITORY), run=lambda arguments, input_data=None: two_values
    )

    with pytest.raises(ClaimError, match="malformed merge result"):
        client.merge_landing(
            57,
            head_sha=MERGE_COMMIT_SHA,
            method=workboard.MergeMethod.MERGE,
            title="t",
            body="Work-Item: #42\n",
        )


def test_github_adapter_runs_gh_when_no_fake_run_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every other adapter test injects `run=` to avoid a real subprocess;
    this proves the adapter's own default (`_gh`, via `bounded_command`)
    actually builds a `gh` command and runs it through the real bounded-I/O
    machinery -- substituting the child process itself so the test needs no
    real `gh` executable."""
    observed: list[list[str]] = []
    original_popen = subprocess.Popen

    def start(
        command: list[str],
        *,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen[bytes]:
        observed.append(command)
        substituted = [sys.executable, "-c", "print('main')"]
        return original_popen(substituted, stdin=stdin, stdout=stdout, stderr=stderr, env=env)

    monkeypatch.setattr(subprocess, "Popen", start)
    client = GitHubForge(github.repository_id("example/agent-coordination"))

    assert client.default_branch() == "main"
    assert observed == [
        ["gh", "api", "repos/example/agent-coordination", "--jq", ".default_branch"]
    ]


def test_github_adapter_item_reference_reads_state_title_and_body() -> None:
    client = GitHubForge(
        github.repository_id("example/agent-coordination"),
        run=lambda _arguments: json.dumps(
            {"state": "open", "title": "Work", "body": "Do it.", "is_landing": False}
        ),
    )

    assert client.item_reference(10) == forge.ItemReference(forge.ItemState.OPEN, "Work", "Do it.")


def test_github_adapter_item_reference_reports_a_pull_request_as_a_landing() -> None:
    """The one read `check` distributes on: GitHub answers for a pull request
    at the issues endpoint too, and only this flag tells the two apart."""
    client = GitHubForge(
        github.repository_id("example/agent-coordination"),
        run=lambda _arguments: json.dumps(
            {"state": "open", "title": "Land it", "body": "Work-Item: #7", "is_landing": True}
        ),
    )

    assert client.item_reference(12) == forge.ItemReference(
        forge.ItemState.OPEN, "Land it", "Work-Item: #7", True
    )


def test_github_adapter_item_reference_reads_a_closed_issue_with_no_body() -> None:
    client = GitHubForge(
        github.repository_id("example/agent-coordination"),
        run=lambda _arguments: json.dumps(
            {"state": "closed", "title": "Work", "body": None, "is_landing": False}
        ),
    )

    assert client.item_reference(10) == forge.ItemReference(forge.ItemState.CLOSED, "Work", "")


def test_github_adapter_item_reference_is_missing_after_a_404() -> None:
    client = GitHubForge(
        github.repository_id("example/agent-coordination"),
        run=lambda _arguments: (_ for _ in ()).throw(
            forge.ForgeNotFoundError("GitHub API failed: HTTP 404")
        ),
    )

    assert client.item_reference(10) == forge.ItemReference(forge.ItemState.MISSING)


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        pytest.param("not-json", "invalid issue reference JSON", id="not-json"),
        pytest.param("", "malformed issue reference", id="no-values"),
        pytest.param('{"a": 1}\n{"b": 2}', "malformed issue reference", id="two-values"),
        pytest.param(json.dumps([]), "malformed issue reference", id="empty-list"),
        pytest.param(json.dumps(["not-a-dict"]), "malformed issue reference", id="not-a-dict"),
        pytest.param(
            json.dumps({"state": "unknown", "title": "x", "body": None}),
            "malformed issue reference",
            id="unknown-state",
        ),
        pytest.param(
            json.dumps({"state": "open", "title": 5, "body": None}),
            "malformed issue reference",
            id="title-not-text",
        ),
        pytest.param(
            json.dumps({"state": "open", "title": "x", "body": 5}),
            "malformed issue reference",
            id="body-not-text",
        ),
    ],
)
def test_github_adapter_item_reference_fails_loud_on_a_malformed_response(
    raw: str, match: str
) -> None:
    client = GitHubForge(
        github.repository_id("example/agent-coordination"), run=lambda _arguments: raw
    )

    with pytest.raises(ClaimError, match=match):
        client.item_reference(10)


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(json.dumps(["not-a-dict"]), id="not-a-dict"),
        pytest.param(
            json.dumps(
                {
                    "number": 151,
                    "state": "open",
                    "closedAt": None,
                    "repository": "not a repo",
                    "isPullRequest": False,
                }
            ),
            id="malformed-repository",
        ),
        pytest.param(
            json.dumps(
                {
                    "number": 151,
                    "state": "closed",
                    "closedAt": None,
                    "repository": "example/agent-coordination",
                    "isPullRequest": False,
                }
            ),
            id="closed-without-timestamp",
        ),
    ],
)
def test_github_board_dependency_fails_loud_on_a_malformed_shape(raw: str) -> None:
    client = GitHubForge(
        github.repository_id("example/agent-coordination"),
        run=listing_runner(lambda _arguments: raw),
    )

    with pytest.raises(ClaimError, match="malformed board blocked-by dependency"):
        client.list_board_dependencies(150)


def test_github_board_dependency_reads_a_closed_timestamp_as_an_aware_instant() -> None:
    client = GitHubForge(
        github.repository_id("example/agent-coordination"),
        run=listing_runner(
            lambda _arguments: json.dumps(
                {
                    "number": 151,
                    "state": "closed",
                    "closedAt": "2026-09-05T00:00:00Z",
                    "repository": "example/agent-coordination",
                    "isPullRequest": False,
                }
            )
        ),
    )

    dependencies = client.list_board_dependencies(150)

    assert dependencies[0].closed_at == datetime(2026, 9, 5, tzinfo=UTC)


def test_github_board_dependency_fails_loud_on_an_uncalendared_closed_timestamp() -> None:
    """`closedAt` can pass the timestamp-shape check (digits in the right
    places) while still naming no real calendar date; `datetime.fromisoformat`
    itself is the second, calendar-aware check that catches that."""
    client = GitHubForge(
        github.repository_id("example/agent-coordination"),
        run=listing_runner(
            lambda _arguments: json.dumps(
                {
                    "number": 151,
                    "state": "closed",
                    "closedAt": "9999-99-99T00:00:00Z",
                    "repository": "example/agent-coordination",
                    "isPullRequest": False,
                }
            )
        ),
    )

    with pytest.raises(ClaimError, match="malformed board blocked-by dependency"):
        client.list_board_dependencies(150)


def test_bounded_command_sets_github_quiet_environment() -> None:
    observed = github.bounded_command(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ['NO_COLOR']); print(os.environ['GH_NO_UPDATE_NOTIFIER'])",
        ],
        purpose="env probe",
    )

    assert observed.splitlines() == ["1", "1"]


@pytest.fixture
def non_github_remote_url() -> str:
    """A remote URL `discover_repository` reads first and finds
    no repository in, so it falls through to asking `gh` -- every test using
    this in place of a matching GitHub remote is exercising that fallback,
    never the cheap local-URL read."""
    return "https://example.com/owner/repo"


def test_repository_resolution_uses_github_quiet_environment(
    monkeypatch: pytest.MonkeyPatch, non_github_remote_url: str
) -> None:
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed["command"] = command
        observed["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(command, 0, b"\x1b[32mowner/repository\x1b[0m\n", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    resolved = github.discover_repository(remote_url=non_github_remote_url)

    assert resolved == forge.RepositoryId(github.GITHUB_HOST, ("owner",), "repository")
    command = observed["command"]
    assert isinstance(command, list)
    assert command[0] == "gh"
    env = observed["env"]
    assert isinstance(env, dict)
    assert env["NO_COLOR"] == "1"
    assert env["GH_NO_UPDATE_NOTIFIER"] == "1"


def test_repository_resolution_asks_gh_about_the_named_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, non_github_remote_url: str
) -> None:
    """The `gh repo view` fallback resolves the checkout the
    caller named, never whatever this process's own cwd happens to be."""
    asked_in: list[Path | None] = []

    def spy_run_captured(
        command: list[str], *, cwd: Path | None = None, **_kwargs: object
    ) -> process.CapturedResult:
        asked_in.append(cwd)
        return process.CapturedResult(exit_status=0, stdout=b"owner/repository\n", stderr=b"")

    monkeypatch.setattr(process, "run_captured", spy_run_captured)

    github.discover_repository(remote_url=non_github_remote_url, directory=tmp_path)

    assert asked_in == [tmp_path]


def test_missing_gh_repository_resolution_is_a_controlled_error(
    monkeypatch: pytest.MonkeyPatch, non_github_remote_url: str
) -> None:
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)

    with pytest.raises(ClaimError, match="gh is required"):
        github.discover_repository(remote_url=non_github_remote_url)


def test_repository_resolution_times_out(
    monkeypatch: pytest.MonkeyPatch, non_github_remote_url: str
) -> None:
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(["gh"], process.DEFAULT_TIMEOUT_SECONDS)

    monkeypatch.setattr(subprocess, "run", timed_out)

    with pytest.raises(ClaimError, match="gh timed out while resolving the repository"):
        github.discover_repository(remote_url=non_github_remote_url)


def test_repository_resolution_refuses_when_no_remote_matches(
    monkeypatch: pytest.MonkeyPatch, non_github_remote_url: str
) -> None:
    def failed_gh(*arguments, **kwargs):
        return subprocess.CompletedProcess(arguments[0], 1, b"", b"not a gh repo")

    monkeypatch.setattr(subprocess, "run", failed_gh)

    with pytest.raises(ClaimError, match="cannot resolve GitHub repository"):
        github.discover_repository(remote_url=non_github_remote_url)


@pytest.mark.parametrize(
    "remote",
    [
        "https://github.com/owner/repository.git",
        "git@github.com:owner/repository.git",
    ],
)
def test_repository_resolves_from_a_standard_github_remote_without_asking_gh(
    monkeypatch: pytest.MonkeyPatch, remote: str
) -> None:
    """The git remote is `discover_repository`'s first read: a
    remote that already names a GitHub repository resolves from it alone,
    with `gh` never invoked at all."""

    def unused(*args, **kwargs):
        pytest.fail("a matching GitHub remote must resolve without ever asking gh")

    monkeypatch.setattr(subprocess, "run", unused)

    resolved = github.discover_repository(remote_url=remote)

    assert resolved == forge.RepositoryId(github.GITHUB_HOST, ("owner",), "repository")


def test_bounded_command_stops_before_unbounded_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(process, "MAX_COMMAND_OUTPUT_BYTES", 32)

    with pytest.raises(ClaimError, match="output limit"):
        github.bounded_command(
            [sys.executable, "-c", "print('x' * 1000)"],
            purpose="test command",
        )


def test_bounded_command_disables_github_update_notifications() -> None:
    observed = github.bounded_command(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ['GH_NO_UPDATE_NOTIFIER'])",
        ],
        purpose="update notifier probe",
    )

    assert observed == "1"


def test_bounded_command_streams_stdin_without_putting_it_in_argv() -> None:
    observed = github.bounded_command(
        [sys.executable, "-c", "import sys; print(sys.stdin.buffer.read().decode())"],
        purpose="stdin probe",
        input_data=b"bounded body",
    )

    assert observed == "bounded body"


def test_bounded_command_wraps_process_argument_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cannot_start(*args, **kwargs):
        raise OSError(7, "Argument list too long")

    monkeypatch.setattr(subprocess, "Popen", cannot_start)

    with pytest.raises(ClaimError, match="cannot start test command"):
        github.bounded_command(["gh", "issue"], purpose="test command")


def test_bounded_command_wraps_stdin_write_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cannot_write(*args, **kwargs):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(github.os, "write", cannot_write)

    with pytest.raises(ClaimError, match="failed while sending bounded input"):
        github.bounded_command(
            [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
            purpose="stdin write probe",
            input_data=b"body",
        )


@pytest.fixture
def launched_children(monkeypatch: pytest.MonkeyPatch) -> list[subprocess.Popen[Any]]:
    """Every child `subprocess.Popen` starts, so a test can observe its cleanup."""
    children: list[subprocess.Popen[Any]] = []
    original_popen = cast(Callable[..., subprocess.Popen[Any]], subprocess.Popen)

    def start(command: list[str], **options: object) -> subprocess.Popen[Any]:
        children.append(original_popen(command, **options))
        return children[-1]

    monkeypatch.setattr(subprocess, "Popen", start)
    return children


def _assert_child_reaped_with_its_output_closed(child: subprocess.Popen[Any]) -> None:
    assert child.poll() is not None
    assert child.stdout is not None
    assert child.stdout.closed


def test_bounded_command_reaps_child_when_selector_setup_fails(
    monkeypatch: pytest.MonkeyPatch, launched_children: list[subprocess.Popen[Any]]
) -> None:
    def cannot_select():
        raise OSError(5, "selector failed")

    monkeypatch.setattr(process.selectors, "DefaultSelector", cannot_select)

    with pytest.raises(ClaimError, match="failed while coordinating I/O"):
        github.bounded_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            purpose="selector setup probe",
        )

    _assert_child_reaped_with_its_output_closed(launched_children[0])


def test_bounded_command_reaps_child_when_select_fails(
    monkeypatch: pytest.MonkeyPatch, launched_children: list[subprocess.Popen[Any]]
) -> None:
    class FailingSelector:
        instance: FailingSelector | None = None

        def __init__(self) -> None:
            self.closed = False
            FailingSelector.instance = self

        def register(self, fileobj, events, data) -> None:
            pass

        def get_map(self):
            return {"stdout": object()}

        def select(self, timeout):
            raise OSError(5, "select failed")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(process.selectors, "DefaultSelector", FailingSelector)

    with pytest.raises(ClaimError, match="failed while waiting for I/O"):
        github.bounded_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            purpose="select probe",
        )

    _assert_child_reaped_with_its_output_closed(launched_children[0])
    assert FailingSelector.instance is not None
    assert FailingSelector.instance.closed


def test_bounded_command_reaps_child_when_output_read_fails(
    monkeypatch: pytest.MonkeyPatch, launched_children: list[subprocess.Popen[Any]]
) -> None:
    original_read = github.os.read

    def cannot_read(file_descriptor: int, count: int) -> bytes:
        output = launched_children[0].stdout if launched_children else None
        if output is not None and file_descriptor == output.fileno():
            raise OSError(5, "read failed")
        return original_read(file_descriptor, count)

    monkeypatch.setattr(github.os, "read", cannot_read)

    with pytest.raises(ClaimError, match="failed while reading output"):
        github.bounded_command(
            [sys.executable, "-u", "-c", "import time; print('ready'); time.sleep(30)"],
            purpose="read probe",
        )

    _assert_child_reaped_with_its_output_closed(launched_children[0])


def test_bounded_command_reaps_child_on_cancellation(
    monkeypatch: pytest.MonkeyPatch, launched_children: list[subprocess.Popen[Any]]
) -> None:
    class CancellationSentinel(BaseException):
        pass

    class CancellingSelector:
        def register(self, fileobj, events, data) -> None:
            pass

        def get_map(self):
            return {"stdout": object()}

        def select(self, timeout):
            raise CancellationSentinel

        def close(self) -> None:
            pass

    monkeypatch.setattr(process.selectors, "DefaultSelector", CancellingSelector)

    with pytest.raises(CancellationSentinel):
        github.bounded_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            purpose="cancellation probe",
        )

    _assert_child_reaped_with_its_output_closed(launched_children[0])


def test_bounded_command_requires_the_named_executable() -> None:
    with pytest.raises(ClaimError) as excinfo:
        github.bounded_command(
            ["missing-claim-command"],
            purpose="missing executable probe",
        )
    assert str(excinfo.value) == "missing-claim-command is required for issue claims"


def test_bounded_command_times_out(
    monkeypatch: pytest.MonkeyPatch, launched_children: list[subprocess.Popen[Any]]
) -> None:
    monkeypatch.setattr(github, "GH_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(ClaimError) as excinfo:
        github.bounded_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            purpose="timeout probe",
        )
    assert str(excinfo.value) == "timeout probe timed out"
    assert launched_children[0].poll() is not None


def test_bounded_command_stops_a_child_that_hangs_after_closing_output(
    launched_children: list[subprocess.Popen[Any]],
) -> None:
    with pytest.raises(ClaimError) as excinfo:
        github.bounded_command(
            [
                sys.executable,
                "-c",
                (
                    "import os, sys, time\n"
                    "for stream in (sys.stdout, sys.stderr):\n"
                    "    try:\n"
                    "        stream.close()\n"
                    "    except OSError:\n"
                    "        pass\n"
                    "for fd in (1, 2):\n"
                    "    try:\n"
                    "        os.close(fd)\n"
                    "    except OSError:\n"
                    "        pass\n"
                    "time.sleep(30)"
                ),
            ],
            purpose="hang probe",
        )
    assert str(excinfo.value) == "hang probe did not exit"
    assert launched_children[0].poll() is not None


def test_bounded_command_reports_a_child_that_cannot_be_stopped_as_not_exiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same sentence holds when the child is still running while its output is open."""
    real_popen = subprocess.Popen
    started: list[subprocess.Popen[Any]] = []

    def start(
        command: list[str],
        *,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
        env: dict[str, str] | None = None,
    ) -> UnstoppableProcess:
        started.append(real_popen(command, stdin=stdin, stdout=stdout, stderr=stderr, env=env))
        return UnstoppableProcess(started[-1])

    monkeypatch.setattr(subprocess, "Popen", start)
    monkeypatch.setattr(github, "GH_TIMEOUT_SECONDS", 0.05)
    try:
        with pytest.raises(ClaimError) as excinfo:
            github.bounded_command(
                [sys.executable, "-c", "import time; time.sleep(30)"], purpose="hang probe"
            )
    finally:
        reap(started)
    assert str(excinfo.value) == "hang probe did not exit"


def test_bounded_command_uses_combined_output_as_nonzero_exit_message() -> None:
    with pytest.raises(ClaimError) as excinfo:
        github.bounded_command(
            [sys.executable, "-c", "raise SystemExit('boom')"],
            purpose="exit probe",
        )
    assert str(excinfo.value) == "boom"


def test_bounded_command_names_the_exit_code_when_nonzero_output_is_empty() -> None:
    with pytest.raises(ClaimError) as excinfo:
        github.bounded_command(
            [sys.executable, "-c", "raise SystemExit(7)"],
            purpose="empty exit probe",
        )
    assert str(excinfo.value) == "empty exit probe failed with exit 7"


def test_bounded_command_rejects_non_utf8_output() -> None:
    with pytest.raises(ClaimError) as excinfo:
        github.bounded_command(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(bytes((255,))); sys.stdout.buffer.flush()",
            ],
            purpose="decode probe",
        )
    assert str(excinfo.value) == "decode probe returned non-UTF-8 output"


@pytest.mark.parametrize(
    ("outcome", "expected_type", "expected_message"),
    [
        pytest.param(
            process.BoundedResult(0, bytes((255,))),
            forge.ForgeMalformedResponseError,
            "GitHub issue coordination returned non-UTF-8 output",
            id="malformed-non-utf8-output",
        ),
        pytest.param(
            process.BoundedResult(1, b"HTTP 404 Not Found"),
            forge.ForgeNotFoundError,
            "HTTP 404 Not Found",
            id="http-404",
        ),
        pytest.param(
            process.BoundedResult(1, b"HTTP 401 Unauthorized"),
            forge.ForgePermissionDeniedError,
            "HTTP 401 Unauthorized",
            id="http-401",
        ),
        pytest.param(
            process.BoundedResult(1, b"HTTP 403 Forbidden"),
            forge.ForgePermissionDeniedError,
            "HTTP 403 Forbidden",
            id="http-403",
        ),
        pytest.param(
            process.BoundedResult(1, b"HTTP 502 Bad Gateway"),
            forge.ForgeTransientError,
            "HTTP 502 Bad Gateway",
            id="http-5xx",
        ),
        pytest.param(
            process.BoundedResult(1, b"connection reset by peer"),
            forge.ForgeTransientError,
            "connection reset by peer",
            id="connection-reset-signal",
        ),
        pytest.param(
            process.BoundedResult(1, b"request timeout"),
            forge.ForgeTransientError,
            "request timeout",
            id="decoded-timeout-signal",
        ),
        pytest.param(
            process.BoundedResult(1, b""),
            forge.ForgeError,
            "GitHub issue coordination failed with exit 1",
            id="unclassified-empty-exit",
        ),
        pytest.param(
            process.BoundedResult(1, b"some other prose"),
            forge.ForgeError,
            "some other prose",
            id="unclassified-nonzero-exit",
        ),
        pytest.param(
            process.ProcessIoFailedError(process.IoStage.WAITING, "boom"),
            forge.ForgeTransientError,
            "GitHub issue coordination failed while waiting for I/O: boom",
            id="io-stage-waiting",
        ),
        pytest.param(
            process.ProcessIoFailedError(process.IoStage.SENDING, "boom"),
            forge.ForgeTransientError,
            "GitHub issue coordination failed while sending bounded input: boom",
            id="io-stage-sending",
        ),
        pytest.param(
            process.ProcessIoFailedError(process.IoStage.READING, "boom"),
            forge.ForgeTransientError,
            "GitHub issue coordination failed while reading output: boom",
            id="io-stage-reading",
        ),
        pytest.param(
            process.ProcessIoFailedError(process.IoStage.COORDINATING, "boom"),
            forge.ForgeTransientError,
            "GitHub issue coordination failed while coordinating I/O: boom",
            id="io-stage-coordinating",
        ),
        pytest.param(
            process.ProcessDidNotExitError(),
            forge.ForgeTransientError,
            "GitHub issue coordination did not exit",
            id="did-not-exit",
        ),
        pytest.param(
            process.ProcessTimedOutError(),
            forge.ForgeTransientError,
            "GitHub issue coordination timed out",
            id="process-timed-out",
        ),
        pytest.param(
            process.ProcessOutputTooLargeError(),
            forge.ForgeMalformedResponseError,
            "GitHub issue coordination exceeded its output limit",
            id="output-too-large",
        ),
        pytest.param(
            process.ExecutableMissingError("gh"),
            ClaimError,
            "gh is required for issue claims",
            id="gh-missing",
        ),
    ],
)
def test_bounded_command_classifies_every_forge_failure_signal(
    monkeypatch: pytest.MonkeyPatch,
    outcome: process.BoundedResult | process.ProcessError,
    expected_type: type[Exception],
    expected_message: str,
) -> None:
    """Driven through `GitHubForge.default_branch` with `process.run_bounded`
    faked: every failure signal becomes the exact typed error and message."""

    def fake_run_bounded(*args, **kwargs):
        if isinstance(outcome, process.ProcessError):
            raise outcome
        return outcome

    monkeypatch.setattr(process, "run_bounded", fake_run_bounded)
    client = GitHubForge(github.repository_id("example/agent-coordination"))

    with pytest.raises(expected_type) as excinfo:
        client.default_branch()

    assert type(excinfo.value) is expected_type
    assert str(excinfo.value) == expected_message


def test_bounded_command_refuses_a_process_error_type_it_does_not_classify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `process.ProcessError` subclass the failure classifier does not name
    fails loud as a defect instead of becoming a generic `ForgeError`."""

    class _UnknownProcessError(process.ProcessError):
        pass

    def fake_run_bounded(*args, **kwargs):
        raise _UnknownProcessError

    monkeypatch.setattr(process, "run_bounded", fake_run_bounded)
    client = GitHubForge(github.repository_id("example/agent-coordination"))

    with pytest.raises(AssertionError, match="unhandled process failure type"):
        client.default_branch()


def test_github_adapter_reads_a_pull_request_and_the_default_branch() -> None:
    head_sha = "b" * 40
    pull_request = api_pull_request(head=api_head(sha=head_sha))

    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        if f"repos/{REPOSITORY}/pulls/12" in arguments:
            return json.dumps(pull_request)
        return "main"

    client = GitHubForge(github.repository_id(REPOSITORY), run=run)
    expected = forge.Landing(
        12,
        "ada",
        "Work-Item: #72",
        github.repository_id(REPOSITORY),
        LANDING_BRANCH,
        "main",
        True,
        MERGE_COMMIT_SHA,
        "feat: land the lane",
        head_sha,
        False,
    )
    assert dataclasses.astuple(client.landing(12)) == dataclasses.astuple(expected)
    assert client.default_branch() == "main"


def test_github_adapter_fails_loud_when_github_answers_for_another_pull_request() -> None:
    client = GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: json.dumps(api_pull_request(number=13)),
    )

    with pytest.raises(ClaimError, match="answered for pull request #13, not #12"):
        client.landing(12)


def test_github_adapter_fails_loud_when_the_pull_request_payload_is_not_a_dict() -> None:
    client = GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: json.dumps("not a pull request"),
    )

    with pytest.raises(ClaimError) as excinfo:
        client.landing(12)

    assert str(excinfo.value) == github.MALFORMED_PULL_REQUEST


def test_github_adapter_fails_loud_when_github_answers_with_more_than_one_pull_request() -> None:
    client = GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: (
            f"{json.dumps(api_pull_request())}\n{json.dumps(api_pull_request())}"
        ),
    )

    with pytest.raises(ClaimError) as excinfo:
        client.landing(12)

    assert str(excinfo.value) == github.MALFORMED_PULL_REQUEST


def test_github_adapter_fails_loud_when_github_answers_with_no_pull_request() -> None:
    client = GitHubForge(
        github.repository_id(REPOSITORY), run=lambda arguments, input_data=None: ""
    )

    with pytest.raises(ClaimError) as excinfo:
        client.landing(12)

    assert str(excinfo.value) == github.MALFORMED_PULL_REQUEST


def test_github_adapter_fails_loud_on_a_malformed_default_branch() -> None:
    client = GitHubForge(
        github.repository_id(REPOSITORY), run=lambda arguments, input_data=None: "not a branch"
    )

    with pytest.raises(ClaimError, match="malformed default branch"):
        client.default_branch()


def test_github_adapter_refuses_a_default_branch_over_the_length_bound() -> None:
    overlong = "a" * 300
    client = GitHubForge(
        github.repository_id(REPOSITORY), run=lambda arguments, input_data=None: overlong
    )

    with pytest.raises(ClaimError, match="malformed default branch"):
        client.default_branch()


API_REPOSITORY_URL = f"https://api.github.com/repos/{REPOSITORY}"


def api_sub_issue(number: int, state: str, title: object = "T") -> dict[str, object]:
    return {"number": number, "repository": API_REPOSITORY_URL, "state": state, "title": title}


def sub_issue_client(*children: dict[str, object]) -> GitHubForge:
    return GitHubForge(
        github.repository_id(REPOSITORY),
        run=listing_runner(
            lambda arguments, input_data=None: "\n".join(json.dumps(child) for child in children)
        ),
    )


def test_github_adapter_reads_a_recorded_parent_and_its_children() -> None:
    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        if arguments[1].endswith("/parent"):
            return json.dumps(
                {"number": 79, "repository": API_REPOSITORY_URL, "body": "## Next\nCut."}
            )
        return "\n".join(json.dumps(api_sub_issue(number, "open")) for number in (72, 73))

    client = GitHubForge(github.repository_id(REPOSITORY), run=listing_runner(run))

    assert client.parent_issue(72) == workboard.ParentIssue(
        workboard.IssueReference(REPOSITORY, 79), "## Next\nCut."
    )
    assert client.parent_number(72) == 79
    assert client.list_children(79) == (
        workboard.ChildItem(72, workboard.ChildState.OPEN, "T"),
        workboard.ChildItem(73, workboard.ChildState.OPEN, "T"),
    )


def test_github_adapter_reports_a_closed_child_alongside_open_ones() -> None:
    client = sub_issue_client(api_sub_issue(72, "closed"), api_sub_issue(73, "open"))

    assert client.list_children(79) == (
        workboard.ChildItem(72, workboard.ChildState.CLOSED, "T"),
        workboard.ChildItem(73, workboard.ChildState.OPEN, "T"),
    )


@pytest.mark.parametrize(
    "child",
    [
        pytest.param({"number": 72, "repository": API_REPOSITORY_URL}, id="state-missing"),
        pytest.param(api_sub_issue(72, "archived"), id="state-unknown"),
        pytest.param(api_sub_issue(72, "open", title=5), id="title-not-text"),
    ],
)
def test_github_adapter_fails_loud_on_an_unreadable_sub_issue(child: dict[str, object]) -> None:
    client = sub_issue_client(child)

    with pytest.raises(ClaimError, match="malformed sub-issue"):
        client.list_children(79)


def test_github_adapter_fails_loud_when_a_sub_issue_is_not_an_object() -> None:
    client = GitHubForge(
        github.repository_id(REPOSITORY), run=listing_runner(lambda arguments, input_data=None: "5")
    )

    with pytest.raises(ClaimError, match="malformed sub-issue"):
        client.list_children(79)


def test_github_adapter_reads_an_issue_without_a_parent_as_parentless() -> None:
    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        raise forge.ForgeNotFoundError("gh: No parent issue found (HTTP 404)")

    client = GitHubForge(github.repository_id(REPOSITORY), run=run)

    assert (client.parent_issue(72), client.parent_number(72)) == (None, None)


def test_github_adapter_reads_the_parents_native_kind() -> None:
    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        return json.dumps(
            {
                "number": 79,
                "repository": API_REPOSITORY_URL,
                "body": "## Next\nCut.",
                "kind": "Container",
            }
        )

    client = GitHubForge(github.repository_id(REPOSITORY), run=run)

    assert client.parent_issue(72) == workboard.ParentIssue(
        workboard.IssueReference(REPOSITORY, 79), "## Next\nCut.", ItemKind.CONTAINER
    )


def test_github_adapter_fails_loud_on_a_malformed_parent_kind() -> None:
    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        return json.dumps(
            {"number": 79, "repository": API_REPOSITORY_URL, "body": "## Next\nCut.", "kind": 5}
        )

    client = GitHubForge(github.repository_id(REPOSITORY), run=run)

    with pytest.raises(ClaimError, match="malformed parent issue"):
        client.parent_issue(72)


def test_github_adapter_fails_loud_when_the_parent_issue_response_is_not_one_object() -> None:
    client = GitHubForge(
        github.repository_id(REPOSITORY), run=lambda arguments, input_data=None: json.dumps([])
    )

    with pytest.raises(ClaimError, match="malformed parent issue"):
        client.parent_issue(72)


def test_github_adapter_fails_loud_when_the_parent_issue_body_is_not_text() -> None:
    client = GitHubForge(
        github.repository_id(REPOSITORY),
        run=lambda arguments, input_data=None: json.dumps(
            {"number": 79, "repository": API_REPOSITORY_URL, "body": 5}
        ),
    )

    with pytest.raises(ClaimError, match="malformed parent issue"):
        client.parent_issue(72)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"number": True}, id="number-is-a-bool"),
        pytest.param({"repository": "not-a-repository-url"}, id="repository-unparsable"),
    ],
)
def test_github_adapter_fails_loud_on_a_malformed_parent_reference(
    overrides: dict[str, object],
) -> None:
    value = {"number": 79, "repository": API_REPOSITORY_URL, "body": "## Next\nCut.", **overrides}
    client = GitHubForge(
        github.repository_id(REPOSITORY), run=lambda arguments, input_data=None: json.dumps(value)
    )

    with pytest.raises(ClaimError, match="malformed parent issue"):
        client.parent_issue(72)


@pytest.mark.parametrize(
    ("rows", "reading", "valid"),
    [
        pytest.param([{"filename": "uv.lock"}], {}, True, id="G1"),
        pytest.param([{"filename": f"file-{i}"} for i in range(150)], {}, True, id="G2"),
        pytest.param([False], {}, False, id="G3"),
        pytest.param([{"filename": ""}], {}, False, id="G4"),
        pytest.param([{"filename": "uv.lock", "status": "renamed"}], {}, False, id="G5"),
        pytest.param([{"filename": "uv.lock"}] * 2, {}, False, id="G6"),
        pytest.param([], {"changedFiles": -1}, False, id="G7"),
        pytest.param([], {"headSha": "short"}, False, id="G8"),
        pytest.param([{}], {}, False, id="missing-filename"),
        pytest.param([{"filename": 1}], {}, False, id="non-string-filename"),
        pytest.param(
            [{"filename": "uv.lock", "previous_filename": ""}], {}, False, id="empty-previous"
        ),
        pytest.param(
            [{"filename": "uv.lock", "previous_filename": 1}], {}, False, id="non-string-previous"
        ),
        pytest.param(
            [{"filename": "uv.lock", "previous_filename": "old.lock", "status": "renamed"}],
            {},
            True,
            id="rename",
        ),
        pytest.param([], {"changedFiles": True}, False, id="boolean-count"),
        pytest.param([], {"changedFiles": "1"}, False, id="string-count"),
        pytest.param([], {"headSha": None}, False, id="non-string-head"),
        pytest.param([], None, False, id="non-object-reading"),
        pytest.param([], {}, True, id="empty-listing"),
    ],
)
def test_pull_request_changes_brackets_every_page_and_refuses_a_malformed_listing(
    rows: list[object],
    reading: dict[str, object] | None,
    valid: bool,
) -> None:
    head = (
        {"headSha": MERGE_COMMIT_SHA, "changedFiles": len(rows)} | reading
        if reading is not None
        else None
    )
    calls: list[list[str]] = []
    after = {"headSha": "b" * 40, "changedFiles": len(rows) + 1}
    readings = iter([json.dumps(head), json.dumps(after)])

    def run(arguments: list[str], input_data: bytes | None = None) -> str:
        calls.append(arguments)
        if arguments[1].split("?")[0].endswith("/files"):
            return paged_listing(arguments, rows)
        return next(readings)

    client = GitHubForge(github.repository_id(REPOSITORY), run=run)
    if not valid:
        with pytest.raises(forge.ForgeMalformedResponseError):
            client.pull_request_changes(12)
        return
    changes = client.pull_request_changes(12)
    assert changes.before == forge.ListingReading(MERGE_COMMIT_SHA, len(rows))
    assert changes.after == forge.ListingReading("b" * 40, len(rows) + 1)
    assert len(changes.files) == len(rows)
    if rows:
        assert (
            changes.files[0].path == "uv.lock"
            if len(rows) == 1
            else changes.files[-1].path == "file-149"
        )
    if len(rows) == 1:
        assert isinstance(rows[0], dict)
        assert changes.files[0].previous_path == (
            "old.lock" if "previous_filename" in rows[0] else None
        )
    endpoint = f"repos/{REPOSITORY}/pulls/12"
    bracket = ["api", endpoint, "--jq", "{headSha:.head.sha,changedFiles:.changed_files}"]
    files = ["-i", "--jq", ".[] | {filename,previous_filename,status}"]
    second_page = (
        [["api", endpoint + "/files?per_page=100&page=2", *files]] if len(rows) > 100 else []
    )
    assert calls == [
        bracket,
        ["api", endpoint + "/files?per_page=100", *files],
        *second_page,
        bracket,
    ]


@pytest.mark.parametrize(
    ("value", "number"),
    [
        pytest.param("12", 12, id="plain"),
        pytest.param("007", 7, id="leading-zeros-stay-readable"),
        pytest.param("7" * 18, int("7" * 18), id="at-the-bound"),
    ],
)
def test_pull_request_number_reads_a_bare_ascii_decimal_number(value: str, number: int) -> None:
    """Spec: REL-60."""
    assert github.pull_request_number(value) == number


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty"),
        pytest.param("sha123", id="sha"),
        pytest.param("²", id="superscript-digit"),
        pytest.param("٧٢", id="non-ascii-digits"),
        pytest.param("7" * 19, id="past-the-bound"),
        pytest.param("7" * 5000, id="past-the-int-digit-limit"),
    ],
)
def test_pull_request_number_refuses_anything_but_a_bounded_ascii_number(value: str) -> None:
    """Spec: REL-60."""
    with pytest.raises(ClaimError, match="--merged requires a pull request number"):
        github.pull_request_number(value)
