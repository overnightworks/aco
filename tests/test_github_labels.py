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
