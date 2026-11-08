"""`aco cut` holds the item's lock from before its first forge use through its
container write (`specs/cut.spec.md` CUT-41), on the real checkout of a GitHub-hosted
board. The forge is the only fake."""

import json
from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, container_issue
from cli_fixtures import run_cli
from github_fixtures import serve_forge
from item_lock_witness import LockWitnessForge, run_second_writer_beside_the_first

from aco import cli, forge

pytestmark = pytest.mark.usefixtures("github_world")

CONTAINER = 79
CUT_ARGUMENTS = ["cut", str(CONTAINER), "--title", "Slice A", "--not-a-twin"]
ONE_ROW = MINIMAL_BLOCK_TOML + '[[slice]]\nindex = 1\ntitle = "Slice A"\ndone_when = "D"\n'


@pytest.fixture
def lock_directory(tmp_path: Path) -> Path:
    return tmp_path / "state" / "aco" / "item-locks"


def served_witness(
    monkeypatch: pytest.MonkeyPatch, lock_directory: Path, *, pause_first_call: bool = False
) -> LockWitnessForge:
    container = container_issue(CONTAINER, ONE_ROW)
    return serve_forge(
        monkeypatch,
        LockWitnessForge(
            lock_directory,
            issue_references={
                CONTAINER: forge.ItemReference(forge.ItemState.OPEN, "Epic", container.body)
            },
            board_issues=(container,),
            pause_first_call=pause_first_call,
        ),
    )


def test_the_board_is_listed_and_the_container_written_while_its_lock_is_held(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    lock_directory: Path,
) -> None:
    """Spec: CUT-41 -- the first forge use and the container write are under the lock."""
    client = served_witness(monkeypatch, lock_directory)

    result = run_cli(CUT_ARGUMENTS, capsys)

    assert (result.status, result.stderr) == (0, "")
    assert (client.lock_held_at_listings, client.lock_held_at_writes) == ([True], [True])


def test_a_second_cut_says_it_waits_for_the_lock_and_lists_the_board_after_the_first(
    monkeypatch: pytest.MonkeyPatch, lock_directory: Path
) -> None:
    """Spec: CUT-41, RULE-42 -- the wait line, then the second run lists the board the
    first one wrote: its row is gone, so it writes no body and only creates its child."""
    client = served_witness(monkeypatch, lock_directory, pause_first_call=True)

    def writer() -> int:
        return cli.main(CUT_ARGUMENTS)

    contended = run_second_writer_beside_the_first(monkeypatch, client, writer)

    assert contended.statuses == (0, 0)
    assert contended.stderr == f"waiting for the item lock at {client.the_lock_file()}\n"
    assert contended.body_writes_when_the_second_waited == 0
    assert (client.lock_held_at_listings, client.lock_held_at_writes) == ([True, True], [True])
    assert len(client.created_issues) == 2


def test_an_unwritable_lock_directory_refuses_precondition_failed_and_reads_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    lock_directory: Path,
) -> None:
    """Spec: CUT-41, RULE-41 -- a lock the item cannot take names its path; nothing is
    read or written."""
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker))
    client = served_witness(monkeypatch, lock_directory)

    result = run_cli([*CUT_ARGUMENTS, "--json"], capsys)

    assert (
        result.status,
        result.stderr.startswith(
            f"ERROR: cannot lock the item at {blocker / 'aco' / 'item-locks'}"
        ),
        json.loads(result.stdout)["reason"],
        client.body_writes,
        client.created_issues,
        client.lock_held_at_listings,
    ) == (2, True, "precondition_failed", [], [], [])
