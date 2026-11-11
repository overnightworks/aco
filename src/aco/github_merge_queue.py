"""The GitHub merge queue and the branch rules that name it: whether a branch requires the
queue, where a pull request stands in it, and enqueueing a pull request pinned to its head.

Nothing here merges, retries or waits: every call is one decision for the caller.
The module never runs `gh`: the adapter hands in the callables that perform and
parse one round trip, so every round trip stays counted where the adapter counts them.
"""

from collections.abc import Callable, Iterable, Mapping
from enum import StrEnum

from . import forge, protocol, workboard

MERGE_QUEUE_RULE = "merge_queue"

# GraphQL reference: `PullRequest.mergeQueueEntry` is null outside the queue,
# `RemovedFromMergeQueueEvent.reason` is the removal's own reason. `last: 1` is the
# latest removal on the timeline.
_STATE_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: %d) {
      state
      mergeCommit { oid }
      mergeQueueEntry { id }
      timelineItems(last: 1, itemTypes: [REMOVED_FROM_MERGE_QUEUE_EVENT]) {
        nodes { ... on RemovedFromMergeQueueEvent { reason } }
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


# The adapter's one round trip (`GitHubForge._run`) and its tolerant JSON reader
# (`GitHubForge._json_lines`).
Run = Callable[[list[str]], str]
JsonLines = Callable[[str, str], tuple[object, ...]]


def _malformed(subject: str) -> forge.ForgeMalformedResponseError:
    return forge.ForgeMalformedResponseError(f"GitHub returned a malformed {subject}")


def _rule(rule: object) -> Mapping[str, object]:
    return _object(rule, "branch merge rule")


def has_merge_queue_rule(rules: Iterable[object]) -> bool:
    """Whether one of the branch's rules is a `merge_queue` rule."""
    return MERGE_QUEUE_RULE in [_rule(rule).get("type") for rule in rules]


def rule_merge_methods(rule: object) -> frozenset[workboard.MergeMethod] | None:
    """The methods one branch rule allows, or None where it restricts none."""
    values = _rule(rule)
    if values.get("type") == "required_linear_history":
        return frozenset(workboard.MergeMethod) - {workboard.MergeMethod.MERGE}
    if values.get("type") != "pull_request":
        return None
    parameters = values.get("parameters")
    if parameters is None:
        return None
    methods = _object(parameters, "branch merge rule").get("allowed_merge_methods")
    if methods is None:
        return None
    known = {method.value for method in workboard.MergeMethod}
    if not isinstance(methods, list) or not all(
        isinstance(method, str) and method in known for method in methods
    ):
        raise _malformed("branch merge rule")
    return frozenset(workboard.MergeMethod(method) for method in methods)


def _commit(value: object, subject: str) -> str:
    if not isinstance(value, str) or protocol.COMMIT_PATTERN.fullmatch(value) is None:
        raise _malformed(subject)
    return value


def _object(value: object, subject: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise _malformed(subject)
    return value


def _removal_reason(pull_request: Mapping[str, object]) -> str | None:
    """The reason of the latest queue removal, `None` where the timeline records none
    or the removal names no reason."""
    nodes = _object(pull_request.get("timelineItems"), "queue removal").get("nodes")
    if not isinstance(nodes, list) or len(nodes) > 1:
        raise _malformed("queue removal")
    if not nodes:
        return None
    reason = _object(nodes[0], "queue removal").get("reason")
    if reason is not None and not isinstance(reason, str):
        raise _malformed("queue removal")
    return reason


def _queue_state(pull_request: object, number: int) -> forge.MergeQueueState:
    values = _object(pull_request, "pull request queue state")
    try:
        state = _PullRequestState(values.get("state"))
    except ValueError as error:
        raise _malformed("pull request queue state") from error
    if state is _PullRequestState.MERGED:
        merge_commit = _object(values.get("mergeCommit"), "merge commit").get("oid")
        return forge.MergedPullRequest(_commit(merge_commit, "merge commit"))
    if state is _PullRequestState.CLOSED:
        raise forge.ForgeError(f"pull request #{number} is closed without a merge")
    entry = values.get("mergeQueueEntry")
    if entry is None:
        return forge.UnqueuedPullRequest(_removal_reason(values))
    _object(entry, "merge queue entry")
    return forge.QueuedPullRequest()


class MergeQueue:
    """The merge queue of one repository's pull requests."""

    def __init__(self, repository: forge.RepositoryId, run: Run, json_lines: JsonLines) -> None:
        self._repository = repository
        self._run = run
        self._json_lines = json_lines

    def _graphql(self, query: str, variables: Mapping[str, str], jq: str, subject: str) -> object:
        """The one JSON value `jq` selects from `query`'s answer."""
        arguments = ["api", "graphql", "-f", f"query={query}"]
        for name, value in variables.items():
            arguments += ["-f", f"{name}={value}"]
        values = self._json_lines(self._run([*arguments, "--jq", jq]), subject)
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
        """Whether pull request `number` is merged, queued or open and not queued."""
        return _queue_state(
            self._pull_request(_STATE_QUERY, number, "pull request queue state"), number
        )

    def _lookup(self, number: int) -> tuple[str, str]:
        """The pull request's node identifier and current head."""
        values = _object(
            self._pull_request(_LOOKUP_QUERY, number, "pull request lookup"),
            "pull request lookup",
        )
        node_id = values.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise _malformed("pull request lookup")
        return node_id, _commit(values.get("headRefOid"), "pull request lookup")

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
                "enqueue result",
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
        if _object(payload, "enqueue result").get("mergeQueueEntry") is None:
            raise _malformed("enqueue result")
