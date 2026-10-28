"""The GitHub adapter's reopen read: one aliased GraphQL answer per block, refusing
what it cannot read as a time or as "never reopened"."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from board_fixtures import REPOSITORY

from aco import forge, github, protocol


def reopen_node(*created_at: object) -> dict[str, object]:
    return {"timelineItems": {"nodes": [{"createdAt": value} for value in created_at]}}


def forge_answering(repository: object) -> tuple[github.GitHubForge, list[list[str]]]:
    """An adapter whose every round trip answers `repository` and records its arguments."""
    observed: list[list[str]] = []

    def run(arguments: list[str]) -> str:
        observed.append(arguments)
        return json.dumps(repository)

    return github.GitHubForge(github.repository_id(REPOSITORY), run=run), observed


def test_reopened_at_reads_each_number_from_one_round_trip() -> None:
    client, observed = forge_answering(
        {"n0": reopen_node("2026-10-28T00:50:28Z"), "n1": reopen_node()}
    )

    reopened = client.reopened_at((323, 340))

    assert reopened == {323: datetime(2026, 10, 28, 0, 50, 28, tzinfo=UTC), 340: None}
    assert len(observed) == 1
    assert "issue(number: 323)" in observed[0][3]


def test_reopened_at_of_nothing_costs_no_round_trip() -> None:
    client, observed = forge_answering({})

    reopened = client.reopened_at(())

    assert (reopened, observed) == ({}, [])


@pytest.mark.parametrize(
    "repository",
    [
        pytest.param({"n0": None}, id="issue-gone"),
        pytest.param({}, id="alias-omitted"),
        pytest.param({"n0": reopen_node("yesterday")}, id="time-not-rfc3339"),
        pytest.param({"n0": reopen_node(5)}, id="time-not-text"),
        pytest.param({"n0": reopen_node("2026-10-28T00:50:28Z", "2026-10-29T00:50:28Z")}, id="two"),
        pytest.param({"n0": {"timelineItems": {"nodes": "none"}}}, id="nodes-not-a-list"),
        pytest.param({"n0": {"timelineItems": {"nodes": [{}]}}}, id="event-without-time"),
    ],
)
def test_reopened_at_refuses_an_answer_it_cannot_read(repository: object) -> None:
    client, _ = forge_answering(repository)

    with pytest.raises(forge.ForgeMalformedResponseError, match="malformed batched reopen time"):
        client.reopened_at((323,))


def test_reopened_at_refuses_a_null_issue_gh_reports_as_not_found() -> None:
    def run(_arguments: list[str]) -> str:
        raise forge.ForgeError(
            json.dumps(
                {
                    "data": {"repository": {"n0": None}},
                    "errors": [{"type": "NOT_FOUND", "path": ["repository", "n0"]}],
                }
            )
        )

    client = github.GitHubForge(github.repository_id(REPOSITORY), run=run)

    with pytest.raises(protocol.ClaimError, match="malformed batched reopen time"):
        client.reopened_at((323,))
