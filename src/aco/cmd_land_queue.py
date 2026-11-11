"""The merge-queue path of the `land` command (`specs/land.spec.md`): the landing message
written into the pull request, one enqueue pinned to the preflight head, and the wait for
the queue's verdict. `cmd_land` decides when this path runs and what follows a merge."""

import time
from collections.abc import Callable

from . import forge, github, protocol, report

# The queue merges after its checks ran, which takes minutes: a read every minute is plenty.
QUEUE_READ_PAUSE_SECONDS = 60.0
# Looked up at each call, so a test replaces it and never really waits.
pause_between_queue_reads = time.sleep

# GitHub drops an entry without an event when a ruleset changes under it, and may answer
# a read just after an enqueue without the entry: only a second read in a row settles that
# the pull request left the queue.
_UNQUEUED_READS_THAT_SETTLE_REMOVAL = 2
_NO_REMOVAL_REASON = "no reason recorded"

_WRITING_MESSAGE = "writing its landing message"
_ENQUEUEING = "enqueueing it"
_NOT_QUEUED = (
    "pull request #{number} was not queued: {step} failed ({foreign}); re-run aco land {number}"
)
_QUEUE_READ_FAILED = (
    "reading the merge queue state of pull request #{number} failed ({foreign}); "
    "re-run aco land {number}"
)
_REMOVED = (
    "pull request #{number} was removed from the merge queue ({foreign}); re-run aco land {number}"
)
_REMOVED_AND_CLOSED = (
    "pull request #{number} was removed from the merge queue and closed ({foreign})"
)


def head_moved_refusal(number: int) -> protocol.ClaimUnavailableError:
    """The refusal of a pinned merge or enqueue whose pull request changed since the
    preflight read its head."""
    return protocol.ClaimUnavailableError(
        f"pull request #{number} changed while it was checked; re-run land"
    )


def _not_queued(
    number: int, step: str, error: protocol.ClaimError
) -> protocol.ClaimUnavailableError:
    return protocol.ClaimUnavailableError(
        report.refusal_around_foreign_text(_NOT_QUEUED, str(error), number=number, step=step)
    )


def enqueue(client: github.GitHubForge, detail: forge.Landing, head_sha: str, message: str) -> None:
    """Queue the pull request pinned to `head_sha`, once: its body first holds `message`,
    which the queue's squash takes as its own, unless it already does. A failure leaves
    the pull request as it was and the claim standing; a re-run reads the queue first."""
    number = detail.number
    if detail.body != message:
        try:
            client.update_item_body(number, message, replacing=detail.body)
        except protocol.ClaimError as error:
            raise _not_queued(number, _WRITING_MESSAGE, error) from error
    try:
        client.enqueue_pull_request(number, expected_head=head_sha)
    except forge.ForgeEnqueueHeadMovedError as error:
        raise head_moved_refusal(number) from error
    except forge.ForgeError as error:
        raise _not_queued(number, _ENQUEUEING, error) from error


def _read_state(client: github.GitHubForge, number: int) -> forge.MergeQueueState:
    try:
        return client.merge_queue_state(number)
    except forge.ForgeError as error:
        raise protocol.ClaimUnavailableError(
            report.refusal_around_foreign_text(_QUEUE_READ_FAILED, str(error), number=number)
        ) from error


def _shown_reason(removal_reason: str | None) -> str:
    return _NO_REMOVAL_REASON if removal_reason is None else removal_reason


def _refuse_removal(number: int, state: forge.MergeQueueState, unqueued_reads: int) -> None:
    """Refuse where `state` shows the pull request left the queue without merging: closed,
    or open with a recorded reason, or open without an entry in `unqueued_reads` reads in a row."""
    if isinstance(state, forge.ClosedPullRequest):
        raise protocol.ClaimUnavailableError(
            report.refusal_around_foreign_text(
                _REMOVED_AND_CLOSED, _shown_reason(state.removal_reason), number=number
            )
        )
    if isinstance(state, forge.UnqueuedPullRequest) and (
        state.removal_reason is not None or unqueued_reads >= _UNQUEUED_READS_THAT_SETTLE_REMOVAL
    ):
        raise protocol.ClaimUnavailableError(
            report.refusal_around_foreign_text(
                _REMOVED, _shown_reason(state.removal_reason), number=number
            )
        )


def await_merge(
    client: github.GitHubForge,
    number: int,
    state: forge.MergeQueueState,
    pause: Callable[[float], None],
) -> str:
    """The merge commit once the queue merged the pull request. `state` is the latest
    read, judged at once; every read after it follows `pause`. A pull request that left
    the queue refuses and the claim stays."""
    unqueued_reads = 0
    while not isinstance(state, forge.MergedPullRequest):
        unqueued_reads = unqueued_reads + 1 if isinstance(state, forge.UnqueuedPullRequest) else 0
        _refuse_removal(number, state, unqueued_reads)
        pause(QUEUE_READ_PAUSE_SECONDS)
        state = _read_state(client, number)
    return state.merge_commit
