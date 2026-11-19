"""The runs files of the state ref: the bytes of one stored `runs/<claim-id>.json`.

Sibling of `store`, which owns the state ref's transport and names each runs file's blob in
`ClaimState.runs`; `cmd_lane_record` is this module's production caller.
"""

from pathlib import Path

from .protocol import ClaimError, ObjectId
from .store import git_failure_detail_from_stderr, run_git


def read_runs_file(worktree: Path, oid: ObjectId) -> bytes:
    """The raw bytes of the runs file blob `oid`, which `ClaimState.runs` names."""
    result = run_git(worktree, ["cat-file", "blob", str(oid)])
    if result.exit_status != 0:
        raise ClaimError(
            f"cannot read the runs file {oid}: {git_failure_detail_from_stderr(result)}"
        )
    return result.stdout
