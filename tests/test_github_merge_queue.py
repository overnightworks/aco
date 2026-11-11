"""The GitHub adapter's merge queue: the rule on a branch, a pull request's queue state and
the enqueue call pinned to a head, against recorded `gh` answers.

Field names come from GitHub's GraphQL reference (`PullRequest.mergeQueueEntry`,
`RemovedFromMergeQueueEvent.reason`, the `enqueuePullRequest` mutation's
`pullRequestId` and `expectedHeadOid`) and from answers a read-only query recorded on a
scratch repository.
"""

import json
from collections.abc import Callable

import pytest
from board_fixtures import REPOSITORY
from queue_forge import QueueForge

from aco import forge, github

PULL_REQUEST_ID = "PR_kwDOVpnG6s8AAAABOKFfHA"
MERGE_COMMIT = "7342fa9c38b9dd29252ff81cb5e837cc6b0405a0"
HEAD = "5f46e82d36b5629a8bfee52902166528f06e0ca8"
MOVED_HEAD = "79e377c4d29252ff81cb5e837cc6b0405a0b79e3"
NUMBER = 3

MERGED = {
    "mergeCommit": {"oid": MERGE_COMMIT},
    "mergeQueueEntry": None,
    "state": "MERGED",
    "timelineItems": {"nodes": [{"reason": "merged"}]},
}
QUEUED = {
    "mergeCommit": None,
    "mergeQueueEntry": {"id": "MQE_kwDOVpnG6s4AAAAB"},
    "state": "OPEN",
    "timelineItems": {"nodes": []},
}
REMOVED_AFTER_RED_RUN = {
    "mergeCommit": None,
    "mergeQueueEntry": None,
    "state": "OPEN",
    "timelineItems": {"nodes": [{"reason": "failed_checks"}]},
}
NEVER_QUEUED_OR_DROPPED = {
    "mergeCommit": None,
    "mergeQueueEntry": None,
    "state": "OPEN",
    "timelineItems": {"nodes": []},
}
CLOSED = {
    "mergeCommit": None,
    "mergeQueueEntry": None,
    "state": "CLOSED",
    "timelineItems": {"nodes": [{"reason": "failed_checks"}]},
}
ENQUEUED = {"mergeQueueEntry": {"id": "MQE_kwDOVpnG6s4AAAAB"}}


def merged_commit_is(commit: object) -> dict[str, object]:
    return {**MERGED, "mergeCommit": {"oid": commit}}


def removal_is(nodes: object) -> dict[str, object]:
    return {**REMOVED_AFTER_RED_RUN, "timelineItems": {"nodes": nodes}}


def adapter_answering(
    answer: Callable[[list[str]], str],
) -> tuple[github.GitHubForge, list[list[str]]]:
    """An adapter whose every round trip goes to `answer` and is recorded."""
    observed: list[list[str]] = []

    def run(arguments: list[str]) -> str:
        observed.append(arguments)
        return answer(arguments)

    return github.GitHubForge(github.repository_id(REPOSITORY), run=run), observed


def adapter_answering_once(answer: object) -> github.GitHubForge:
    return adapter_answering(lambda _arguments: json.dumps(answer))[0]


def rules_answer(*rule_types: str) -> str:
    return "\n".join(json.dumps({"type": rule_type}) for rule_type in rule_types)


@pytest.mark.parametrize(
    ("rule_types", "required"),
    [
        pytest.param(("pull_request", "merge_queue", "deletion"), True, id="queue-among-rules"),
        pytest.param(("pull_request", "required_linear_history"), False, id="no-queue-rule"),
        pytest.param((), False, id="no-rule"),
    ],
)
def test_requires_merge_queue_reads_the_rule_on_the_branch(
    rule_types: tuple[str, ...], required: bool
) -> None:
    client, _ = adapter_answering(lambda _arguments: rules_answer(*rule_types))

    assert client.requires_merge_queue("main") is required


def test_requires_merge_queue_is_false_on_a_plan_without_rulesets() -> None:
    def refuse(_arguments: list[str]) -> str:
        raise forge.ForgePermissionDeniedError(
            "gh: Upgrade to GitHub Pro or make this repository public (HTTP 403)"
        )

    client, _ = adapter_answering(refuse)

    assert client.requires_merge_queue("main") is False


def test_requires_merge_queue_refuses_a_rule_it_cannot_read() -> None:
    client, _ = adapter_answering(lambda _arguments: json.dumps(["merge_queue"]))

    with pytest.raises(forge.ForgeMalformedResponseError, match="branch merge rule"):
        client.requires_merge_queue("main")


def test_a_merge_queue_rule_leaves_the_merge_method_read_unchanged() -> None:
    client, _ = adapter_answering(lambda _arguments: rules_answer("merge_queue", "pull_request"))

    assert client.branch_merge_rules("main") == ()


@pytest.mark.parametrize(
    ("answer", "state"),
    [
        pytest.param(MERGED, forge.MergedPullRequest(MERGE_COMMIT), id="merged"),
        pytest.param(QUEUED, forge.QueuedPullRequest(), id="queued"),
        pytest.param(
            REMOVED_AFTER_RED_RUN, forge.UnqueuedPullRequest("failed_checks"), id="removed"
        ),
        pytest.param(
            NEVER_QUEUED_OR_DROPPED, forge.UnqueuedPullRequest(None), id="no-removal-recorded"
        ),
        pytest.param(
            removal_is([{"reason": None}]), forge.UnqueuedPullRequest(None), id="removal-no-reason"
        ),
        pytest.param(CLOSED, forge.ClosedPullRequest("failed_checks"), id="closed-after-removal"),
        pytest.param(
            {**CLOSED, "timelineItems": {"nodes": []}},
            forge.ClosedPullRequest(None),
            id="closed-no-removal-recorded",
        ),
    ],
)
def test_merge_queue_state_names_exactly_one_state(
    answer: dict[str, object], state: forge.MergeQueueState
) -> None:
    client = adapter_answering_once(answer)

    assert client.merge_queue_state(NUMBER) == state


def test_merge_queue_state_asks_for_the_pull_request_by_number() -> None:
    client, observed = adapter_answering(lambda _arguments: json.dumps(MERGED))

    client.merge_queue_state(NUMBER)

    assert f"pullRequest(number: {NUMBER})" in "\n".join(observed[0])


def test_merge_queue_state_of_a_missing_pull_request_is_not_found() -> None:
    client = adapter_answering_once(None)

    with pytest.raises(forge.ForgeNotFoundError):
        client.merge_queue_state(NUMBER)


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param([MERGED], id="not-an-object"),
        pytest.param({**MERGED, "state": "DRAFT"}, id="unknown-state"),
        pytest.param(merged_commit_is("abc"), id="merge-commit-not-a-sha"),
        pytest.param({**MERGED, "mergeCommit": None}, id="merged-without-commit"),
        pytest.param({**QUEUED, "mergeQueueEntry": "queued"}, id="entry-not-an-object"),
        pytest.param(removal_is("none"), id="removals-not-a-list"),
        pytest.param(removal_is([{"reason": 5}]), id="reason-not-text"),
        pytest.param(removal_is(["failed_checks"]), id="removal-not-an-object"),
        pytest.param(removal_is([{"reason": "a"}, {"reason": "b"}]), id="two-removals"),
    ],
)
def test_merge_queue_state_refuses_an_answer_it_cannot_read(answer: object) -> None:
    client = adapter_answering_once(answer)

    with pytest.raises(forge.ForgeMalformedResponseError):
        client.merge_queue_state(NUMBER)


def enqueue_answers(
    mutation: Callable[[list[str]], str], *, head_now: str = HEAD
) -> Callable[[list[str]], str]:
    """Answers the identifier lookup with `head_now` as the head, the mutation with `mutation`."""

    def answer(arguments: list[str]) -> str:
        if "mutation" in "\n".join(arguments):
            return mutation(arguments)
        return json.dumps({"id": PULL_REQUEST_ID, "headRefOid": head_now})

    return answer


def test_enqueue_pins_the_pull_request_to_the_expected_head() -> None:
    client, observed = adapter_answering(enqueue_answers(lambda _arguments: json.dumps(ENQUEUED)))

    client.enqueue_pull_request(NUMBER, expected_head=HEAD)

    mutation = observed[-1]
    assert (len(observed), f"pullRequestId={PULL_REQUEST_ID}" in mutation) == (2, True)
    assert f"expectedHeadOid={HEAD}" in mutation


def test_enqueue_tells_a_moved_head_from_every_other_refusal() -> None:
    def refuse(_arguments: list[str]) -> str:
        raise forge.ForgeError("gh: refused")

    client, _ = adapter_answering(enqueue_answers(refuse, head_now=MOVED_HEAD))

    with pytest.raises(forge.ForgeEnqueueHeadMovedError):
        client.enqueue_pull_request(NUMBER, expected_head=HEAD)


def test_enqueue_keeps_another_refusal_as_it_came() -> None:
    def refuse(_arguments: list[str]) -> str:
        raise forge.ForgeError("gh: Pull request is not mergeable")

    client, _ = adapter_answering(enqueue_answers(refuse))

    with pytest.raises(forge.ForgeError, match="not mergeable") as refused:
        client.enqueue_pull_request(NUMBER, expected_head=HEAD)

    assert type(refused.value) is forge.ForgeError


def test_enqueue_leaves_a_transient_failure_to_the_caller() -> None:
    def fail(_arguments: list[str]) -> str:
        raise forge.ForgeTransientError("gh: HTTP 502")

    client, observed = adapter_answering(enqueue_answers(fail))

    with pytest.raises(forge.ForgeTransientError):
        client.enqueue_pull_request(NUMBER, expected_head=HEAD)

    assert len(observed) == 2


def test_enqueue_of_a_missing_pull_request_is_not_found() -> None:
    client, observed = adapter_answering(lambda _arguments: "null")

    with pytest.raises(forge.ForgeNotFoundError):
        client.enqueue_pull_request(NUMBER, expected_head=HEAD)

    assert len(observed) == 1


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param({"id": ""}, id="identifier-empty"),
        pytest.param({"id": 7}, id="identifier-not-text"),
        pytest.param({"id": PULL_REQUEST_ID, "headRefOid": "abc"}, id="head-not-a-sha"),
    ],
)
def test_enqueue_refuses_a_lookup_it_cannot_read(answer: object) -> None:
    client = adapter_answering_once(answer)

    with pytest.raises(forge.ForgeMalformedResponseError):
        client.enqueue_pull_request(NUMBER, expected_head=HEAD)


@pytest.mark.parametrize(
    "mutation_answer",
    [
        pytest.param({"mergeQueueEntry": None}, id="no-entry"),
        pytest.param(None, id="no-payload"),
    ],
)
def test_enqueue_refuses_a_mutation_answer_with_no_entry(mutation_answer: object) -> None:
    client, _ = adapter_answering(
        enqueue_answers(lambda _arguments: json.dumps(mutation_answer)),
    )

    with pytest.raises(forge.ForgeMalformedResponseError):
        client.enqueue_pull_request(NUMBER, expected_head=HEAD)


@pytest.mark.parametrize(
    "state",
    [
        pytest.param(forge.MergedPullRequest(MERGE_COMMIT), id="merged"),
        pytest.param(forge.QueuedPullRequest(), id="queued"),
        pytest.param(forge.UnqueuedPullRequest("failed_checks"), id="removed"),
        pytest.param(forge.UnqueuedPullRequest(None), id="no-removal-recorded"),
        pytest.param(forge.ClosedPullRequest("failed_checks"), id="closed"),
    ],
)
def test_the_fake_forge_answers_each_queue_state(state: forge.MergeQueueState) -> None:
    fake = QueueForge(queue_branches={"main"}, queue_states={NUMBER: state})

    assert (fake.requires_merge_queue("main"), fake.merge_queue_state(NUMBER)) == (True, state)


def test_the_fake_forge_queues_a_pull_request_on_its_pinned_head_only() -> None:
    fake = QueueForge(heads={NUMBER: HEAD})

    fake.enqueue_pull_request(NUMBER, expected_head=HEAD)

    assert fake.merge_queue_state(NUMBER) == forge.QueuedPullRequest()
    with pytest.raises(forge.ForgeEnqueueHeadMovedError):
        fake.enqueue_pull_request(NUMBER, expected_head=MOVED_HEAD)


def test_the_fake_forge_refuses_an_enqueue_it_was_told_to_refuse() -> None:
    refusal = forge.ForgeTransientError("gh: HTTP 502")
    fake = QueueForge(enqueue_error=refusal)

    with pytest.raises(forge.ForgeTransientError):
        fake.enqueue_pull_request(NUMBER, expected_head=HEAD)

    assert fake.enqueued == []


def test_merge_queue_state_refuses_an_answer_of_two_values() -> None:
    client, _ = adapter_answering(lambda _arguments: f"{json.dumps(MERGED)}\n{json.dumps(QUEUED)}")

    with pytest.raises(forge.ForgeMalformedResponseError):
        client.merge_queue_state(NUMBER)
