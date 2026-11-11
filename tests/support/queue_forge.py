"""A fake forge that expresses the merge queue: the rule on a branch, the states of a
pull request and the enqueue call pinned to a head."""

import re
from dataclasses import dataclass, field, fields, replace

from github_fixtures import FakeForge, merge_on_the_forge

from aco import forge, workboard

# GitHub appends this paragraph to a squash whose commits another author wrote.
CO_AUTHOR_PARAGRAPH = "Co-authored-by: Ada <ada@example.com>"


@dataclass(frozen=True)
class LandsInQueue:
    """A scripted read at which the queue merges the pull request."""


LANDS = LandsInQueue()
QueueRead = forge.MergeQueueState | LandsInQueue | forge.ForgeError


@dataclass
class QueueForge(FakeForge):
    """A `FakeForge` with a merge queue. `queue_branches` are the branches under a
    `merge_queue` rule, `queue_states` each pull request's state (a pull request
    nobody scripted is open and unqueued with no removal recorded), `queue_reads`
    the states successive reads of a pull request answer (the last one repeats; `LANDS`
    merges it like GitHub's queue does, an error is raised) and `heads` the head each
    pull request has now: `enqueue_pull_request` queues it only when the head is the
    one pinned."""

    queue_branches: set[str] = field(default_factory=set)
    queue_states: dict[int, forge.MergeQueueState] = field(default_factory=dict)
    queue_reads: dict[int, list[QueueRead]] = field(default_factory=dict)
    heads: dict[int, str] = field(default_factory=dict)
    rules_error: forge.ForgeError | None = None
    enqueue_error: forge.ForgeError | None = None
    enqueue_attempts: list[tuple[int, str]] = field(default_factory=list)
    enqueued: list[tuple[int, str]] = field(default_factory=list)

    @classmethod
    def over(cls, base: FakeForge) -> QueueForge:
        """A queue forge holding `base`'s arrangement, its collections shared."""
        return cls(**{item.name: getattr(base, item.name) for item in fields(base) if item.init})

    def requires_merge_queue(self, branch: str) -> bool:
        """This fake's mirror of `GitHubForge.requires_merge_queue`."""
        self._run()
        if self.rules_error is not None:
            raise self.rules_error
        return branch in self.queue_branches

    def merge_queue_state(self, number: int) -> forge.MergeQueueState:
        """This fake's mirror of `GitHubForge.merge_queue_state`."""
        self._run()
        scripted = self.queue_reads.get(number)
        if not scripted:
            return self.queue_states.get(number, forge.UnqueuedPullRequest(None))
        read = scripted.pop(0) if len(scripted) > 1 else scripted[0]
        if isinstance(read, forge.ForgeError):
            raise read
        if isinstance(read, LandsInQueue):
            del self.queue_reads[number]
            read = self._merge_in_queue(number)
        self.queue_states[number] = read
        return read

    def _merge_in_queue(self, number: int) -> forge.MergedPullRequest:
        """The queue's squash of the pull request as its title and body stand now."""
        landing = self.landings[number]
        sha = self.merge_sha
        if self.closes_on_merge:
            self.closed_issues.update(
                int(closed) for closed in re.findall(r"Closes #(\d+)", landing.body)
            )
        if self.merge_remote is not None:
            body = landing.body.rstrip()
            message = f"{landing.title} (#{number})\n\n{body}\n\n{CO_AUTHOR_PARAGRAPH}\n"
            sha = merge_on_the_forge(
                self.merge_remote,
                self.default_branch_name,
                landing.source_branch,
                message,
                workboard.MergeMethod.SQUASH,
            )
        self.landings[number] = replace(landing, merged=True, merge_commit=sha)
        return forge.MergedPullRequest(sha)

    def enqueue_pull_request(self, number: int, *, expected_head: str) -> None:
        """This fake's mirror of `GitHubForge.enqueue_pull_request`: records the call,
        raises `enqueue_error` when scripted, refuses a moved head, and otherwise
        queues the pull request."""
        self._run()
        self.enqueue_attempts.append((number, expected_head))
        if self.enqueue_error is not None:
            raise self.enqueue_error
        if self.heads.get(number, expected_head) != expected_head:
            raise forge.ForgeEnqueueHeadMovedError(f"pull request #{number} head moved")
        self.enqueued.append((number, expected_head))
        self.queue_states[number] = forge.QueuedPullRequest()
