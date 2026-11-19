"""`state_runs` behaviour: the bytes of a stored runs file, read from a real git object database."""

from pathlib import Path

import pytest
from cli_fixtures import set_git_identity

from aco import protocol, state_runs

# A syntactically valid but locally unresolvable object id.
_UNRESOLVABLE_OBJECT_ID = protocol.ObjectId("0" * 40)


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    set_git_identity(monkeypatch)


def test_a_runs_file_blob_git_cannot_read_refuses_naming_it(worktree: Path) -> None:
    with pytest.raises(
        protocol.ClaimError, match=f"cannot read the runs file {_UNRESOLVABLE_OBJECT_ID}"
    ):
        state_runs.read_runs_file(worktree, _UNRESOLVABLE_OBJECT_ID)
