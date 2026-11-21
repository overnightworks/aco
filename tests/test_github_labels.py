"""`GitHubForge.add_label` (`specs/mcp.spec.md`): the request it sends and how it
reads GitHub's answer, through a `run` that answers as `gh` would."""

import json

import pytest
from board_fixtures import REPOSITORY

from aco import forge, github

_LABEL = "needs-operator"


@pytest.fixture
def requests() -> list[tuple[list[str], bytes | None]]:
    return []


def _forge_answering(
    answer: str, requests: list[tuple[list[str], bytes | None]]
) -> github.GitHubForge:
    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        requests.append((arguments, input_data))
        return answer

    return github.GitHubForge(github.repository_id(REPOSITORY), run=run)


def _labels(*names: str) -> str:
    return json.dumps([{"id": 1, "name": name, "color": "ededed"} for name in names])


def test_the_label_is_posted_to_the_issues_label_list(
    requests: list[tuple[list[str], bytes | None]],
) -> None:
    client = _forge_answering(_labels("bug", _LABEL), requests)

    client.add_label(484, _LABEL)

    assert requests == [
        (
            ["api", "--method", "POST", f"repos/{REPOSITORY}/issues/484/labels", "--input", "-"],
            json.dumps({"labels": [_LABEL]}).encode("utf-8"),
        )
    ]


def test_an_answer_holding_the_label_in_another_case_passes(
    requests: list[tuple[list[str], bytes | None]],
) -> None:
    client = _forge_answering(_labels("Needs-Operator"), requests)

    client.add_label(484, _LABEL)

    assert len(requests) == 1


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(_labels("bug"), id="label-missing"),
        pytest.param("[]", id="empty-list"),
        pytest.param("not json", id="invalid-json"),
        pytest.param('{"labels": []}', id="no-list"),
        pytest.param(json.dumps([_LABEL, None, 3]), id="entries-without-names"),
    ],
)
def test_an_answer_without_the_label_is_a_malformed_response(
    answer: str, requests: list[tuple[list[str], bytes | None]]
) -> None:
    client = _forge_answering(answer, requests)

    with pytest.raises(forge.ForgeMalformedResponseError):
        client.add_label(484, _LABEL)


def test_removing_the_label_deletes_it_from_the_issues_label_list(
    requests: list[tuple[list[str], bytes | None]],
) -> None:
    client = _forge_answering(_labels("bug"), requests)

    client.remove_label(484, _LABEL)

    assert requests == [
        (["api", "--method", "DELETE", f"repos/{REPOSITORY}/issues/484/labels/{_LABEL}"], None)
    ]


def test_a_label_the_issue_does_not_hold_counts_as_removed() -> None:
    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        raise forge.ForgeNotFoundError("gh: Label does not exist (HTTP 404)")

    client = github.GitHubForge(github.repository_id(REPOSITORY), run=run)

    client.remove_label(484, _LABEL)


def _issue_line(number: int, *, pull_request: bool = False) -> str:
    return json.dumps(
        {
            "number": number,
            "title": f"Issue {number}",
            "labels": [_LABEL],
            "body": f"audited through {'a' * 40}",
            "createdAt": "2026-11-01T00:00:00Z",
            "updatedAt": "2026-11-01T00:00:00Z",
            "isPullRequest": pull_request,
            "kind": None,
            "authorAssociation": "MEMBER",
            "childrenClosed": None,
            "childrenTotal": None,
            "blockedByCount": 0,
            "openDependents": 0,
        }
    )


def test_labelled_issues_come_from_one_request_for_the_quoted_label_in_any_state(
    requests: list[tuple[list[str], bytes | None]],
) -> None:
    client = _forge_answering(
        "\n".join([_issue_line(7), _issue_line(8, pull_request=True)]), requests
    )

    found = client.newest_labelled_issues("audit tests")

    assert ([issue.number for issue in found], [arguments[1] for arguments, _ in requests]) == (
        [7],
        [
            f"repos/{REPOSITORY}/issues?state=all&labels=audit%20tests"
            "&sort=created&direction=desc&per_page=100"
        ],
    )


def test_a_refused_label_removal_stays_a_failure() -> None:
    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        raise forge.ForgePermissionDeniedError("gh: Resource not accessible (HTTP 403)")

    client = github.GitHubForge(github.repository_id(REPOSITORY), run=run)

    with pytest.raises(forge.ForgePermissionDeniedError):
        client.remove_label(484, _LABEL)
