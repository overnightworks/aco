"""The commit history of the state ref: the age of each live claim.

Sibling of `store`, which owns the state ref's transport; `board_read` and `cmd_brief` are this
module's production callers.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .protocol import ActiveClaim, ClaimError, ObjectId, StateLineageError
from .store import git_failure_detail_from_stderr, run_git

# Field separator for the batched `git log` read below: %x09 is git's own
# escape for a literal tab, unambiguous inside a `--format` string.
_LOG_FORMAT = "%H%x09%cI"


def _first_parent_commit_dates(worktree: Path, tip: ObjectId) -> dict[ObjectId, datetime]:
    """Every commit reachable from `tip` by first-parent descent, mapped to
    its committer date, in one `git log` call.

    `refs/aco/state`'s own history is always linear by construction --
    `commit_transition` never writes a merge, every retry parents its new
    commit onto a freshly observed tip ("never a merge") -- so a
    first-parent walk from `tip` reaches every commit the ref has ever held.
    """
    result = run_git(worktree, ["log", "--first-parent", f"--format={_LOG_FORMAT}", str(tip)])
    if result.exit_status != 0:
        raise ClaimError(
            f"cannot read the commit history of {tip}: {git_failure_detail_from_stderr(result)}"
        )
    dates: dict[ObjectId, datetime] = {}
    for line in result.stdout.decode().splitlines():
        commit_hex, _, raw_date = line.partition("\t")
        try:
            parsed = datetime.fromisoformat(raw_date)
        except ValueError as error:
            raise ClaimError(f"git returned a malformed committer date for {commit_hex}") from error
        dates[ObjectId(commit_hex)] = parsed.astimezone(UTC)
    return dates


def claim_ages(
    *, worktree: Path, tip: ObjectId, claims: Iterable[ActiveClaim]
) -> dict[str, datetime]:
    """Each `claim`'s age -- its `opened_commit`'s committer date -- from one
    walk of `tip`'s history, replacing a `merge-base` plus `log`
    pair per claim.

    Refuses with `StateLineageError` for a claim whose `opened_commit` the
    walk never reaches (claim-record.spec.md, CLAIM-50): a claim's age display reads
    real history, it never guesses across a lineage break.
    """
    claim_list = tuple(claims)
    if not claim_list:
        return {}
    dates = _first_parent_commit_dates(worktree, tip)
    ages: dict[str, datetime] = {}
    for claim in claim_list:
        try:
            ages[claim.claim_id] = dates[claim.opened_commit]
        except KeyError:
            raise StateLineageError(
                f"{claim.opened_commit} is not an ancestor of {tip}; the ref may "
                "have been rewritten"
            ) from None
    return ages
