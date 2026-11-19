"""The batched GraphQL read: one aliased answer per block, refusing what it cannot read as a
value or as "nothing to report". The edit-history read stands for every batched read."""

import json

import pytest

from aco import forge, github_graphql

READ = github_graphql.EDIT_HISTORY_READ
ALIAS_FIELD = "issueOrPullRequest("


def history_node(*edited_at: object) -> dict[str, object]:
    return {"userContentEdits": {"nodes": [{"editedAt": value} for value in edited_at]}}


class Answering:
    """A round trip answering `repository` and recording each query."""

    def __init__(self, repository: object) -> None:
        self.repository = repository
        self.queries: list[str] = []

    def __call__(self, query: str, description: str) -> tuple[object, ...]:
        self.queries.append(query)
        return (self.repository,)


def read(
    numbers: tuple[int, ...], fetch: github_graphql.FetchBlock
) -> dict[int, tuple[github_graphql.BodyRevision, ...]]:
    return github_graphql.read_batched(READ, numbers, fetch=fetch, concurrency=2)


def test_each_number_is_read_from_one_round_trip() -> None:
    fetch = Answering({"n0": history_node(), "n1": history_node("2026-10-28T00:50:28Z")})

    revisions = read((323, 340), fetch)

    assert [len(revisions[number]) for number in (323, 340)] == [0, 1]
    assert len(fetch.queries) == 1
    assert f"{ALIAS_FIELD}number: 323)" in fetch.queries[0]


def test_nothing_requested_costs_no_round_trip() -> None:
    fetch = Answering({})

    revisions = read((), fetch)

    assert (revisions, fetch.queries) == ({}, [])


@pytest.mark.parametrize(
    "repository",
    [
        pytest.param({"n0": None}, id="item-gone"),
        pytest.param({}, id="alias-omitted"),
        pytest.param({"n0": history_node("yesterday")}, id="time-not-rfc3339"),
        pytest.param({"n0": history_node(5)}, id="time-not-text"),
        pytest.param({"n0": {"userContentEdits": {"nodes": "none"}}}, id="nodes-not-a-list"),
        pytest.param({"n0": {"userContentEdits": {"nodes": [{}]}}}, id="edit-without-time"),
        pytest.param(None, id="no-repository"),
    ],
)
def test_an_answer_it_cannot_read_is_refused(repository: object) -> None:
    fetch = Answering(repository)

    with pytest.raises(forge.ForgeMalformedResponseError, match="malformed batched edit history"):
        read((323,), fetch)


def test_a_null_item_gh_reports_as_not_found_is_refused() -> None:
    def fetch(_query: str, _description: str) -> tuple[object, ...]:
        raise forge.ForgeError(
            json.dumps(
                {
                    "data": {"repository": {"n0": None}},
                    "errors": [{"type": "NOT_FOUND", "path": ["repository", "n0"]}],
                }
            )
        )

    with pytest.raises(forge.ForgeMalformedResponseError, match="malformed batched edit history"):
        read((323,), fetch)


def test_more_numbers_than_one_block_are_split_over_several_round_trips() -> None:
    numbers = tuple(range(1, 251))
    queries: list[str] = []

    def fetch(query: str, _description: str) -> tuple[object, ...]:
        queries.append(query)
        return ({f"n{index}": history_node() for index in range(query.count(ALIAS_FIELD))},)

    revisions = read(numbers, fetch)

    assert set(revisions) == set(numbers)
    assert len(queries) > 1
    assert all(query.count(ALIAS_FIELD) <= github_graphql.GRAPHQL_BATCH_SIZE for query in queries)


@pytest.mark.parametrize(
    "message",
    [
        pytest.param("not json", id="unparseable"),
        pytest.param(
            json.dumps(
                {
                    "data": {"repository": {"n0": None}},
                    "errors": [{"type": "FORBIDDEN", "path": ["repository", "n0"]}],
                }
            ),
            id="error-not-not-found",
        ),
        pytest.param(
            json.dumps(
                {
                    "data": {"repository": {"n0": None}},
                    "errors": [{"type": "NOT_FOUND", "path": ["repository", "n9"]}],
                }
            ),
            id="error-on-an-alias-not-asked-for",
        ),
        pytest.param(json.dumps(["unexpected"]), id="response-not-an-object"),
        pytest.param(
            json.dumps(
                {
                    "data": {"repository": None},
                    "errors": [{"type": "NOT_FOUND", "path": ["repository", "n0"]}],
                }
            ),
            id="repository-not-a-mapping",
        ),
        pytest.param(
            json.dumps({"data": {"repository": {"n0": None}}, "errors": []}),
            id="no-errors",
        ),
        pytest.param(
            json.dumps(
                {
                    "data": {"repository": {}},
                    "errors": [{"type": "NOT_FOUND", "path": ["repository", "n0"]}],
                }
            ),
            id="alias-missing-from-repository",
        ),
        pytest.param(
            json.dumps(
                {
                    "data": {"repository": {"n0": None}},
                    "errors": [{"type": "NOT_FOUND", "path": ["repository"]}],
                }
            ),
            id="error-path-wrong-length",
        ),
        pytest.param(
            json.dumps(
                {
                    "data": {"repository": {"n0": None}},
                    "errors": [{"type": "NOT_FOUND", "path": ["repository", []]}],
                }
            ),
            id="error-path-alias-not-a-string",
        ),
    ],
)
def test_a_graphql_error_it_cannot_recover_is_reraised(message: str) -> None:
    def fetch(_query: str, _description: str) -> tuple[object, ...]:
        raise forge.ForgeError(message)

    with pytest.raises(forge.ForgeError) as raised:
        read((323,), fetch)

    assert str(raised.value) == message
