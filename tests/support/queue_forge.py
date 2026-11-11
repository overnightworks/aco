"""A fake forge that expresses the merge queue: the rule on a branch, the three states of a
pull request and the enqueue call pinned to a head."""

from dataclasses import dataclass, field

from github_fixtures import FakeForge

from aco import forge


@dataclass
class QueueForge(FakeForge):
    """A `FakeForge` with a merge queue. `queue_branches` are the branches under a
    `merge_queue` rule, `queue_states` each pull request's state (a pull request
    nobody scripted is open and unqueued with no removal recorded) and
    `heads` the head each pull request has now: `enqueue_pull_request` queues it
    only when the head is the one pinned."""

    queue_branches: set[str] = field(default_factory=set)
    queue_states: dict[int, forge.MergeQueueState] = field(default_factory=dict)
    heads: dict[int, str] = field(default_factory=dict)
    enqueue_error: forge.ForgeError | None = None
    enqueued: list[tuple[int, str]] = field(default_factory=list)

    def requires_merge_queue(self, branch: str) -> bool:
        """This fake's mirror of `GitHubForge.requires_merge_queue`."""
        self._run()
        return branch in self.queue_branches

    def merge_queue_state(self, number: int) -> forge.MergeQueueState:
        """This fake's mirror of `GitHubForge.merge_queue_state`."""
        self._run()
        return self.queue_states.get(number, forge.UnqueuedPullRequest(None))

    def enqueue_pull_request(self, number: int, *, expected_head: str) -> None:
        """This fake's mirror of `GitHubForge.enqueue_pull_request`: records the call,
        raises `enqueue_error` when scripted, refuses a moved head, and otherwise
        queues the pull request."""
        self._run()
        if self.enqueue_error is not None:
            raise self.enqueue_error
        if self.heads.get(number, expected_head) != expected_head:
            raise forge.ForgeEnqueueHeadMovedError(f"pull request #{number} head moved")
        self.enqueued.append((number, expected_head))
        self.queue_states[number] = forge.QueuedPullRequest()
