"""`aco item edit --size` and `--whole` write the item's body in the item's turn
(`specs/item.spec.md` ITEM-65), on the real checkout of a GitHub-hosted board. The
forge is the only fake."""

from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import run_cli
from github_fixtures import serve_forge
from item_lock_witness import LockWitnessForge, run_second_writer_beside_the_first

from aco import cli, forge

pytestmark = pytest.mark.usefixtures("github_world")

ITEM = 72
SIZE_EDIT = ("--size", "L")
WHOLE_EDIT = ("--whole", "the adapters share one lock")
FIELD_EDITS = [
    pytest.param(SIZE_EDIT, id="size"),
    pytest.param(WHOLE_EDIT, id="whole"),
]


@pytest.fixture
def lock_directory(tmp_path: Path) -> Path:
    return tmp_path / "state" / "aco" / "item-locks"


def served_witness(
    monkeypatch: pytest.MonkeyPatch, lock_directory: Path, *, pause_first_call: bool = False
) -> LockWitnessForge:
    reference = forge.ItemReference(forge.ItemState.OPEN, "Claims", block_body(MINIMAL_BLOCK_TOML))
    return serve_forge(
        monkeypatch,
        LockWitnessForge(
            lock_directory,
            issue_references={ITEM: reference},
            pause_first_call=pause_first_call,
        ),
    )


def edit_arguments(edit: tuple[str, ...]) -> list[str]:
    return ["item", "edit", str(ITEM), *edit]


@pytest.mark.parametrize("edit", FIELD_EDITS)
def test_the_item_is_read_and_written_while_its_lock_is_held(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    lock_directory: Path,
    edit: tuple[str, ...],
) -> None:
    """Spec: ITEM-65 -- the read and the write both happen under the item's lock."""
    client = served_witness(monkeypatch, lock_directory)

    result = run_cli(edit_arguments(edit), capsys)

    assert (result.status, result.stderr) == (0, "")
    assert (client.lock_held_at_reads, client.lock_held_at_writes) == ([True], [True])


@pytest.mark.parametrize("edit", FIELD_EDITS)
def test_a_second_edit_says_it_waits_for_the_lock_and_writes_after_the_first(
    monkeypatch: pytest.MonkeyPatch, lock_directory: Path, edit: tuple[str, ...]
) -> None:
    """Spec: ITEM-65, RULE-42 -- the wait line, then the second run's read and write."""
    client = served_witness(monkeypatch, lock_directory, pause_first_call=True)

    def writer() -> int:
        return cli.main(edit_arguments(edit))

    contended = run_second_writer_beside_the_first(monkeypatch, client, writer)

    assert contended.statuses == (0, 0)
    assert contended.stderr == f"waiting for the item lock at {client.the_lock_file()}\n"
    assert contended.body_writes_when_the_second_waited == 0
    assert (client.lock_held_at_reads, client.lock_held_at_writes) == ([True, True], [True])
