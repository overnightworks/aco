"""Batched GraphQL reads of numbered repository items: one aliased query per block.

The module never runs `gh`: the adapter hands in a callable that performs one
round trip, so every round trip stays counted where the adapter counts them.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

from . import forge, protocol

# GraphQL aliases every number into one query field, so a block this size
# stays one round trip; GitHub's own guidance keeps a query's alias count in
# the 50-100 range rather than one huge query per repository.
GRAPHQL_ITEM_REFERENCE_BATCH_SIZE = 100

_Value = TypeVar("_Value")

# One round trip: the query and what the response is called in a refusal, answering
# `data.repository` as the values `gh` printed.
FetchBlock = Callable[[str, str], tuple[object, ...]]


@dataclass(frozen=True)
class BatchedRead(Generic[_Value]):
    """One read of every requested number through a single top-level field."""

    field: str
    selection: str
    subject: str
    parse_node: Callable[[object], _Value]


def malformed_response(subject: str) -> forge.ForgeMalformedResponseError:
    return forge.ForgeMalformedResponseError(f"GitHub returned a malformed batched {subject}")


def _query(read: BatchedRead[_Value], numbers: Sequence[int]) -> str:
    aliases = "\n".join(
        f"n{index}: {read.field}(number: {number}) {{ {read.selection} }}"
        for index, number in enumerate(numbers)
    )
    return (
        "query($owner: String!, $name: String!) { "
        f"repository(owner: $owner, name: $name) {{ {aliases} }} }}"
    )


def _values_from_nodes(
    read: BatchedRead[_Value], nodes: Mapping[str, object], numbers: Sequence[int]
) -> dict[int, _Value]:
    """Every requested number's parsed value. An omitted alias is a malformed
    response, never read as the explicit `null` GitHub answers for a number it
    cannot resolve."""
    values: dict[int, _Value] = {}
    for index, number in enumerate(numbers):
        alias = f"n{index}"
        if alias not in nodes:
            raise malformed_response(read.subject)
        values[number] = read.parse_node(nodes[alias])
    return values


# A NOT_FOUND error's own `path`: `["repository", "nN"]`,
# the field GraphQL walked to reach the alias it could not resolve.
_ERROR_PATH_LENGTH = 2


def _is_recovered_not_found_error(
    error: object, aliases: frozenset[str], repository: Mapping[str, object]
) -> bool:
    """Whether `error` is `NOT_FOUND` on one of this call's own aliases, at the
    alias `repository` already answers `null` for."""
    if not isinstance(error, dict) or error.get("type") != "NOT_FOUND":
        return False
    path = error.get("path")
    if not isinstance(path, list) or len(path) != _ERROR_PATH_LENGTH:
        return False
    section, alias = path
    if not isinstance(section, str) or not isinstance(alias, str):
        return False
    return section == "repository" and alias in aliases and repository.get(alias) is None


def not_found_batch_nodes(message: str, numbers: Sequence[int]) -> Mapping[str, object] | None:
    """`gh api graphql` exits nonzero whenever any alias resolved to nothing,
    even though GraphQL's response already answers `null` for it in `data`;
    the process layer folds that exit into an unclassified `ForgeError`, and
    this reads `message` back as the response it carries.

    Returns the batch's nodes -- `null` exactly at every not-found alias --
    only when `message` parses as JSON of that shape, every one of `errors` is
    a `NOT_FOUND` on one of this call's own aliases, and `data.repository`
    holds every alias asked for. Any other shape returns `None` so the caller
    re-raises its original error instead of guessing at recovery.
    """
    try:
        decoded, _ = json.JSONDecoder().raw_decode(message)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    data = decoded.get("data")
    repository = data.get("repository") if isinstance(data, dict) else None
    errors = decoded.get("errors")
    if not isinstance(repository, dict) or not isinstance(errors, list) or not errors:
        return None
    aliases = frozenset(f"n{index}" for index in range(len(numbers)))
    if not aliases.issubset(repository):
        return None
    recovered = all(_is_recovered_not_found_error(error, aliases, repository) for error in errors)
    return repository if recovered else None


def _read_block(
    read: BatchedRead[_Value], numbers: tuple[int, ...], fetch: FetchBlock
) -> dict[int, _Value]:
    """One round trip for at most `GRAPHQL_ITEM_REFERENCE_BATCH_SIZE` numbers."""
    try:
        values = fetch(_query(read, numbers), f"batched {read.subject}")
    except forge.ForgeError as error:
        nodes = not_found_batch_nodes(str(error), numbers)
        if nodes is None:
            raise
        return _values_from_nodes(read, nodes, numbers)
    if len(values) != 1 or not isinstance(values[0], dict):
        raise malformed_response(read.subject)
    return _values_from_nodes(read, values[0], numbers)


def read_batched(
    read: BatchedRead[_Value], numbers: Iterable[int], *, fetch: FetchBlock, concurrency: int
) -> dict[int, _Value]:
    """Every one of `numbers`, in blocks of `GRAPHQL_ITEM_REFERENCE_BATCH_SIZE`
    fetched concurrently, at most `concurrency` at once. Nothing requested costs
    no round trip."""
    ordered = tuple(dict.fromkeys(numbers))
    if not ordered:
        return {}
    blocks = tuple(
        ordered[start : start + GRAPHQL_ITEM_REFERENCE_BATCH_SIZE]
        for start in range(0, len(ordered), GRAPHQL_ITEM_REFERENCE_BATCH_SIZE)
    )
    with ThreadPoolExecutor(max_workers=min(len(blocks), concurrency)) as pool:
        results = list(pool.map(lambda block: _read_block(read, block, fetch), blocks))
    merged: dict[int, _Value] = {}
    for result in results:
        merged.update(result)
    return merged


# `Repository.issueOrPullRequest`'s own `state` enum spans both `Issue`
# (`OPEN`/`CLOSED`) and `PullRequest` (`OPEN`/`CLOSED`/`MERGED`); `forge.
# ItemReference.state` only ever distinguishes open from not, matching the
# REST issues endpoint `item_reference` reads a single number through, so a
# merged pull request reads exactly like a closed one here too. GraphQL's own
# schema has `MERGED` solely on `PullRequestState`, so an `Issue` node
# claiming it is impossible on the wire and a malformed response, never a
# state to normalize.
_ITEM_STATES_BY_TYPENAME: dict[str, dict[str, forge.ItemState]] = {
    "Issue": {"OPEN": forge.ItemState.OPEN, "CLOSED": forge.ItemState.CLOSED},
    "PullRequest": {
        "OPEN": forge.ItemState.OPEN,
        "CLOSED": forge.ItemState.CLOSED,
        "MERGED": forge.ItemState.CLOSED,
    },
}


def _parsed_item_reference_node(node: object) -> forge.ItemReference:
    """One alias's value: `MISSING` for a number that is neither an issue nor a
    pull request, a malformed shape raised loud."""
    if node is None:
        return forge.ItemReference(forge.ItemState.MISSING)
    if not isinstance(node, dict):
        raise malformed_response(_ITEM_REFERENCE_SUBJECT)
    typename = node.get("__typename")
    state = node.get("state")
    title = node.get("title")
    body = node.get("body")
    if (
        not isinstance(typename, str)
        or not isinstance(state, str)
        or state not in _ITEM_STATES_BY_TYPENAME.get(typename, {})
        or not isinstance(title, str)
        or (body is not None and not isinstance(body, str))
    ):
        raise malformed_response(_ITEM_REFERENCE_SUBJECT)
    return forge.ItemReference(
        _ITEM_STATES_BY_TYPENAME[typename][state],
        title,
        body or "",
        typename == "PullRequest",
    )


def _parsed_reopened_node(node: object) -> datetime | None:
    """One issue's last reopen: `None` when it was never reopened. A missing
    issue or a time that is no RFC 3339 instant raises loud, never read as
    "not reopened"."""
    timeline = node.get("timelineItems") if isinstance(node, dict) else None
    events = timeline.get("nodes") if isinstance(timeline, dict) else None
    if not isinstance(events, list) or len(events) > 1:
        raise malformed_response(_REOPENED_SUBJECT)
    if not events:
        return None
    created_at = events[0].get("createdAt") if isinstance(events[0], dict) else None
    if (
        not isinstance(created_at, str)
        or protocol.RFC3339_TIMESTAMP_PATTERN.fullmatch(created_at) is None
    ):
        raise malformed_response(_REOPENED_SUBJECT)
    return datetime.fromisoformat(created_at)


_ITEM_REFERENCE_SUBJECT = "item reference"
_REOPENED_SUBJECT = "reopen time"
ITEM_REFERENCE_READ = BatchedRead(
    "issueOrPullRequest",
    "__typename ... on Issue { state title body } ... on PullRequest { state title body }",
    _ITEM_REFERENCE_SUBJECT,
    _parsed_item_reference_node,
)
REOPENED_AT_READ = BatchedRead(
    "issue",
    "timelineItems(itemTypes: [REOPENED_EVENT], last: 1) "
    "{ nodes { ... on ReopenedEvent { createdAt } } }",
    _REOPENED_SUBJECT,
    _parsed_reopened_node,
)
