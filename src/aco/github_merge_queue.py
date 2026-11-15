"""The GitHub merge queue and the branch rules that name it: whether a branch requires the
queue, where a pull request stands in it, and enqueueing a pull request pinned to its head.

Nothing here merges, retries or waits: every call is one decision for the caller.
The module never runs `gh`: the adapter hands in the callable that performs and
parses one round trip, so every round trip stays counted where the adapter counts them.
"""

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from enum import StrEnum

from . import forge, protocol, workboard

MERGE_QUEUE_RULE = "merge_queue"

_TYPE_KEY = "type"
_RULE_SUBJECT = "branch merge rule"
_REMOVAL_SUBJECT = "queue removal"
_QUEUE_STATE_SUBJECT = "pull request queue state"
_LOOKUP_SUBJECT = "pull request lookup"
_ENQUEUE_SUBJECT = "enqueue result"

# GraphQL reference: `PullRequest.mergeQueueEntry` is null outside the queue,
# `RemovedFromMergeQueueEvent.reason` is the removal's own reason. `last: 1` is the
# latest event of its type on the timeline.
_STATE_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: %d) {
      state
      mergeCommit { oid }
      mergeQueueEntry { id }
      removals: timelineItems(last: 1, itemTypes: [REMOVED_FROM_MERGE_QUEUE_EVENT]) {
        nodes { ... on RemovedFromMergeQueueEvent { createdAt reason } }
      }
      additions: timelineItems(last: 1, itemTypes: [ADDED_TO_MERGE_QUEUE_EVENT]) {
        nodes { ... on AddedToMergeQueueEvent { createdAt } }
      }
    }
  }
}
"""
_LOOKUP_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: %d) { id headRefOid }
  }
}
"""
_ENQUEUE_MUTATION = """
mutation($pullRequestId: ID!, $expectedHeadOid: GitObjectID) {
  enqueuePullRequest(input: {pullRequestId: $pullRequestId, expectedHeadOid: $expectedHeadOid}) {
    mergeQueueEntry { id }
  }
}
"""


class _PullRequestState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    MERGED = "MERGED"


# The adapter's one GraphQL round trip (`GitHubForge._graphql`): query, variables, the `jq`
# selecting from the answer, and what the answer is called in a refusal.
Graphql = Callable[[str, Mapping[str, str], str, str], tuple[object, ...]]


def _malformed(subject: str) -> forge.ForgeMalformedResponseError:
    return forge.ForgeMalformedResponseError(f"GitHub returned a malformed {subject}")


def _rule(rule: object) -> Mapping[str, object]:
    return _object(rule, _RULE_SUBJECT)


def has_merge_queue_rule(rules: Iterable[object]) -> bool:
    """Whether one of the branch's rules is a `merge_queue` rule."""
    return MERGE_QUEUE_RULE in [_rule(rule).get(_TYPE_KEY) for rule in rules]


def rule_merge_methods(rule: object) -> frozenset[workboard.MergeMethod] | None:
    """The methods one branch rule allows, or None where it restricts none."""
    values = _rule(rule)
    if values.get(_TYPE_KEY) == "required_linear_history":
        return frozenset(workboard.MergeMethod) - {workboard.MergeMethod.MERGE}
    if values.get(_TYPE_KEY) != "pull_request":
        return None
    parameters = values.get("parameters")
    if parameters is None:
        return None
    methods = _object(parameters, _RULE_SUBJECT).get("allowed_merge_methods")
    if methods is None:
        return None
    known = {method.value for method in workboard.MergeMethod}
    if not isinstance(methods, list) or not all(
        isinstance(method, str) and method in known for method in methods
    ):
        raise _malformed(_RULE_SUBJECT)
    return frozenset(workboard.MergeMethod(method) for method in methods)


def _commit(value: object, subject: str) -> str:
    if not isinstance(value, str) or protocol.COMMIT_PATTERN.fullmatch(value) is None:
        raise _malformed(subject)
    return value


def _object(value: object, subject: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise _malformed(subject)
    return value


def _latest_event(pull_request: Mapping[str, object], alias: str) -> Mapping[str, object] | None:
    """The one event the timeline read `alias` answers, `None` where it records none."""
    nodes = _object(pull_request.get(alias), _REMOVAL_SUBJECT).get("nodes")
    if not isinstance(nodes, list) or len(nodes) > 1:
        raise _malformed(_REMOVAL_SUBJECT)
    return _object(nodes[0], _REMOVAL_SUBJECT) if nodes else None


def _created_at(event: Mapping[str, object]) -> datetime:
    created_at = event.get("createdAt")
    if not isinstance(created_at, str):
        raise _malformed(_REMOVAL_SUBJECT)
    try:
        return datetime.fromisoformat(created_at)
    except ValueError as error:
        raise _malformed(_REMOVAL_SUBJECT) from error


def _removal_reason(pull_request: Mapping[str, object]) -> str | None:
    """The reason of the latest queue removal, `None` where the timeline records none,
    the removal names no reason, or the pull request was added to the queue again after
    it: only a removal newer than the latest addition counts."""
    removal = _latest_event(pull_request, "removals")
    if removal is None:
        return None
    addition = _latest_event(pull_request, "additions")
    if addition is not None and _created_at(removal) <= _created_at(addition):
        return None
    reason = removal.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise _malformed(_REMOVAL_SUBJECT)
    return reason


def _queue_state(pull_request: object) -> forge.MergeQueueState:
    values = _object(pull_request, _QUEUE_STATE_SUBJECT)
    try:
        state = _PullRequestState(values.get("state"))
    except ValueError as error:
        raise _malformed(_QUEUE_STATE_SUBJECT) from error
    if state is _PullRequestState.MERGED:
        merge_commit = _object(values.get("mergeCommit"), "merge commit").get("oid")
        return forge.MergedPullRequest(_commit(merge_commit, "merge commit"))
    if state is _PullRequestState.CLOSED:
        return forge.ClosedPullRequest(_removal_reason(values))
    entry = values.get("mergeQueueEntry")
    if entry is None:
        return forge.UnqueuedPullRequest(_removal_reason(values))
    _object(entry, "merge queue entry")
    return forge.QueuedPullRequest()


class MergeQueue:
    """The merge queue of one repository's pull requests."""

    def __init__(self, repository: forge.RepositoryId, graphql: Graphql) -> None:
        self._repository = repository
        self._round_trip = graphql

    def _graphql(self, query: str, variables: Mapping[str, str], jq: str, subject: str) -> object:
        """The one JSON value `jq` selects from `query`'s answer."""
        values = self._round_trip(query, variables, jq, subject)
        if len(values) != 1:
            raise _malformed(subject)
        return values[0]

    def _pull_request(self, query: str, number: int, subject: str) -> object:
        pull_request = self._graphql(
            query % number,
            {"owner": self._repository.namespace[0], "name": self._repository.name},
            ".data.repository.pullRequest",
            subject,
        )
        if pull_request is None:
            raise forge.ForgeNotFoundError(f"GitHub has no pull request #{number}")
        return pull_request

    def state(self, number: int) -> forge.MergeQueueState:
        """Whether pull request `number` is merged, queued, open and not queued, or closed."""
        return _queue_state(self._pull_request(_STATE_QUERY, number, _QUEUE_STATE_SUBJECT))

    def _lookup(self, number: int) -> tuple[str, str]:
        """The pull request's node identifier and current head."""
        values = _object(
            self._pull_request(_LOOKUP_QUERY, number, _LOOKUP_SUBJECT),
            _LOOKUP_SUBJECT,
        )
        node_id = values.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise _malformed(_LOOKUP_SUBJECT)
        return node_id, _commit(values.get("headRefOid"), _LOOKUP_SUBJECT)

    def enqueue(self, number: int, expected_head: str) -> None:
        """Enqueue pull request `number` pinned to `expected_head`. A refusal while
        the head is another commit is `ForgeEnqueueHeadMovedError`: GitHub names
        that refusal only in prose, so the head is read again to tell it from any
        other refusal. A transient, permission or not-found failure stays as it is."""
        node_id, _ = self._lookup(number)
        try:
            payload = self._graphql(
                _ENQUEUE_MUTATION,
                {"pullRequestId": node_id, "expectedHeadOid": expected_head},
                ".data.enqueuePullRequest",
                _ENQUEUE_SUBJECT,
            )
        except (
            forge.ForgeTransientError,
            forge.ForgePermissionDeniedError,
            forge.ForgeNotFoundError,
        ):
            raise
        except forge.ForgeError as refusal:
            _, head = self._lookup(number)
            if head != expected_head:
                raise forge.ForgeEnqueueHeadMovedError(str(refusal)) from refusal
            raise
        if _object(payload, _ENQUEUE_SUBJECT).get("mergeQueueEntry") is None:
            raise _malformed(_ENQUEUE_SUBJECT)
