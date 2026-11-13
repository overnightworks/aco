"""The answers of the direct-merge path of the `land` command (`specs/land.spec.md`) to a merge
call that may still be running. `cmd_land` decides when it merges and what follows a merge."""

from . import forge, github, protocol, report

_PENDING_REFUSAL = (
    "pull request #{number} may still be merging ({foreign}); re-run aco land {number}"
)


def pending_refusal(number: int, error: forge.ForgeError) -> protocol.ClaimUnavailableError:
    """The refusal of a merge call after which the pull request may still be merging: a
    re-run finds it merged and finishes the landing, or merges it."""
    return protocol.ClaimUnavailableError(
        report.refusal_around_foreign_text(_PENDING_REFUSAL, str(error), number=number)
    )


def merge_commit_after_server_error(
    client: github.GitHubForge,
    number: int,
    pinned_head: str,
    error: forge.ForgeMergeUnansweredError,
) -> str:
    """The merge commit of a pull request GitHub merged at `pinned_head` although the merge
    call failed with a server error, found by one read of it; a pull request still open, or
    a read that fails, refuses as a merge that may still be pending."""
    try:
        read = client.landing(number)
    except forge.ForgeError:
        raise pending_refusal(number, error) from error
    if read.merge_commit is None or read.head_sha != pinned_head:
        raise pending_refusal(number, error) from error
    return read.merge_commit
