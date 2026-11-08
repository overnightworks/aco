"""`aco item edit --size` and `--whole` write the item's body in the item's turn
(`specs/item.spec.md` ITEM-65), on the real checkout of a GitHub-hosted board. The
forge is the only fake."""

import json
from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import run_cli
from github_fixtures import serve_forge
from item_lock_witness import LockWitnessForge, run_second_writer_beside_the_first

from aco import body, cli, forge

pytestmark = pytest.mark.usefixtures("github_world")

ITEM = 72
SIZE_EDIT = ("--size", "L")
WHOLE_EDIT = ("--whole", "the adapters share one lock")
OTHER_SIZE_EDIT = ("--size", "M")
OTHER_WHOLE_EDIT = ("--whole", "the adapters share no lock")
FIELD_EDITS = [
    pytest.param(SIZE_EDIT, id="size"),
    pytest.param(WHOLE_EDIT, id="whole"),
]
TWO_DIFFERENT_EDITS = [
    pytest.param(SIZE_EDIT, OTHER_SIZE_EDIT, id="size"),
    pytest.param(WHOLE_EDIT, OTHER_WHOLE_EDIT, id="whole"),
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


def block_after(second: tuple[str, ...]) -> tuple[body.Size | None, str | None]:
    """The block's size and whole once `second` is the last edit to run."""
    flag, value = second
    return (body.Size(value), None) if flag == "--size" else (None, value)


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


@pytest.mark.parametrize(("edit", "other_edit"), TWO_DIFFERENT_EDITS)
def test_a_second_edit_says_it_waits_for_the_lock_and_writes_after_the_first(
    monkeypatch: pytest.MonkeyPatch,
    lock_directory: Path,
    edit: tuple[str, ...],
    other_edit: tuple[str, ...],
) -> None:
    """Spec: ITEM-65, RULE-42 -- the wait line, then the second run's own read and write."""
    client = served_witness(monkeypatch, lock_directory, pause_first_call=True)
    runs = iter([edit, other_edit])

    def writer() -> int:
        return cli.main(edit_arguments(next(runs)))

    contended = run_second_writer_beside_the_first(monkeypatch, client, writer)

    assert contended.statuses == (0, 0)
    assert contended.stderr == f"waiting for the item lock at {client.the_lock_file()}\n"
    assert contended.body_writes_when_the_second_waited == 0
    assert (client.lock_held_at_reads, client.lock_held_at_writes) == ([True, True], [True, True])
    final = body.parse_body(client.item_bodies[ITEM])
    assert (final.size, final.whole) == block_after(other_edit)


@pytest.mark.parametrize("edit", FIELD_EDITS)
def test_an_unwritable_lock_directory_refuses_precondition_failed_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    edit: tuple[str, ...],
) -> None:
    """Spec: ITEM-65, RULE-41 -- a lock the item cannot take names its path and writes nothing."""
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker))
    client = served_witness(monkeypatch, tmp_path / "unused")

    result = run_cli([*edit_arguments(edit), "--json"], capsys)

    assert (
        result.status,
        result.stderr.startswith(
            f"ERROR: cannot lock the item at {blocker / 'aco' / 'item-locks'}"
        ),
        json.loads(result.stdout)["reason"],
        client.body_writes,
    ) == (2, True, "precondition_failed", [])
