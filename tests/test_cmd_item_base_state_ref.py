"""A whole-body `aco item edit` names the body hash `aco item show --json` printed
(`specs/item.spec.md` ITEM-70..ITEM-77), on a real `storage = "state-ref"` checkout and a
bare `file://` remote. The GitHub twins live in `test_cmd_item_base.py`."""

import json
import tomllib
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import fresh_observation, run_cli, set_git_identity
from item_base import edit_item, edit_with_base, shown_body_hash
from store_fixtures import item_record, seed_state_ref_checkout

from aco import body, protocol, store
from aco.state_board import StateRefBoard

ITEM_ID = "aco-000001"
NOT_UTF8 = b"\xff\xfe not utf-8"
NO_BLOCK = b"prose, no block\n"

type SeedItem = Callable[[bytes], None]


def _item_body(prose: str) -> str:
    """A valid state-ref item body whose prose line is `prose`."""
    data = {
        **tomllib.loads(MINIMAL_BLOCK_TOML),
        "record": item_record(title="Karte", state="open", kind="task"),
    }
    return block_body(body.render_block(data).removesuffix("\n"), before=f"{prose}\n\n")


def _stored(remote: Path, worktree: Path) -> bytes:
    state = store.fetch_state(worktree=worktree, remote=f"file://{remote}")
    assert state.tip is not None
    return store.read_item_files(worktree, state.tip)[f"{ITEM_ID}.md"]


@pytest.fixture(autouse=True)
def commit_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    set_git_identity(monkeypatch)


@pytest.fixture
def seed_item(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bare_remote: Path, worktree: Path
) -> SeedItem:
    """Pins the checkout to `storage = "state-ref"` over `bare_remote`, with no `gh` on `PATH`,
    and seeds the state ref with item `ITEM_ID` holding the given bytes."""

    def seed(content: bytes) -> None:
        seed_state_ref_checkout(
            monkeypatch, tmp_path, bare_remote, worktree, {f"{ITEM_ID}.md": content}
        )

    return seed


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_an_edit_from_a_copy_read_before_another_edit_refuses_stale(
    seed_item: SeedItem,
    bare_remote: Path,
    worktree: Path,
    capsys: pytest.CaptureFixture[str],
    as_json: bool,
) -> None:
    """Spec: ITEM-72 -- a base that is no longer the stored body's hash refuses `stale`, and the
    state ref keeps the edit that came first."""
    seed_item(_item_body("Stored.").encode())
    stale = edit_with_base(ITEM_ID, capsys)
    first = edit_item(ITEM_ID, capsys, stdin=_item_body("First writer."))
    assert first.status == 0
    before = _stored(bare_remote, worktree)
    current = shown_body_hash(ITEM_ID, capsys)

    result = run_cli([*stale, *(["--json"] * as_json)], capsys, stdin=_item_body("Stale writer."))

    sentence = (
        f"{ITEM_ID} changed since it was read (base {stale[-1]}, now {current}); read it again "
        f"with aco item show {ITEM_ID} --json and apply your change to that body"
    )
    assert (result.status, result.stderr) == (2, f"ERROR: {sentence}\n")
    envelope = {"ok": False, "reason": "stale", "message": sentence}
    assert result.stdout == (json.dumps(envelope) + "\n" if as_json else "")
    assert _stored(bare_remote, worktree) == before


def test_a_write_landing_between_the_read_and_the_write_is_reported_stale(
    seed_item: SeedItem,
    monkeypatch: pytest.MonkeyPatch,
    bare_remote: Path,
    worktree: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: ITEM-72 -- the store's compare-and-swap refusal (CAS-20) reaches the caller as
    `stale`, the answer a changed body gets."""
    seed_item(_item_body("Stored.").encode())
    arguments = edit_with_base(ITEM_ID, capsys)
    hashed = StateRefBoard.stored_body_hash

    def hash_then_let_another_machine_write(board: StateRefBoard, number: int) -> str:
        stored = hashed(board, number)
        remote = f"file://{bare_remote}"
        store.commit_transition(
            observed=fresh_observation(worktree, remote),
            subject=store.TransitionSubject("another machine writes"),
            intent=protocol.ItemWriteIntent(
                item_id=ITEM_ID,
                expected=store.fetch_state(worktree=worktree, remote=remote).items[ITEM_ID],
                new_oid=store.hash_blob(worktree, _item_body("Other machine.").encode()),
                operation_id=uuid.uuid4().hex,
            ),
        )
        return stored

    monkeypatch.setattr(StateRefBoard, "stored_body_hash", hash_then_let_another_machine_write)

    result = run_cli([*arguments, "--json"], capsys, stdin=_item_body("Mine."))

    refusal = json.loads(result.stdout)
    assert (result.status, refusal["reason"]) == (2, "stale")
    assert _stored(bare_remote, worktree) == _item_body("Other machine.").encode()


@pytest.mark.parametrize("content", [NOT_UTF8, NO_BLOCK], ids=["not-utf8", "no-block"])
def test_a_malformed_item_is_repaired_with_the_hash_item_show_refused_with(
    seed_item: SeedItem, capsys: pytest.CaptureFixture[str], content: bytes
) -> None:
    """Spec: ITEM-77, ITEM-39 -- `item show --json` refuses a malformed item with the
    `body_hash` of its stored bytes ahead of `message`, and `item edit --base` takes it."""
    seed_item(content)

    shown = run_cli(["item", "show", ITEM_ID, "--json"], capsys)

    refusal = json.loads(shown.stdout)
    assert shown.status == 2
    assert list(refusal)[-2:] == ["body_hash", "message"]
    assert refusal["message"].endswith(f"aco item show {ITEM_ID} --json prints the body_hash")
    repaired = run_cli(
        ["item", "edit", ITEM_ID, "--base", refusal["body_hash"]],
        capsys,
        stdin=_item_body("Repaired."),
    )
    assert (repaired.status, repaired.stdout) == (0, f"EDITED {ITEM_ID}\n")
    assert run_cli(["item", "show", ITEM_ID, "--json"], capsys).status == 0


def test_the_hint_item_new_prints_for_a_missing_section_leads_to_a_working_edit(
    seed_item: SeedItem, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ITEM-61, ITEM-70 -- pasted, the `item show` the hint names prints the hash
    the `item edit` it names takes."""
    seed_item(_item_body("Seed.").encode())
    created = run_cli(["item", "new", "--title", "Importer", "--kind", "task"], capsys, stdin="")
    assert created.status == 0, created.stderr
    new_id = created.stdout.split()[-1]

    shown = run_cli(["item", "show", new_id, "--json"], capsys)
    edited = run_cli(
        ["item", "edit", new_id, "--base", json.loads(shown.stdout)["body_hash"]],
        capsys,
        stdin=_item_body("Filled."),
    )

    assert (edited.status, edited.stdout) == (0, f"EDITED {new_id}\n")


def test_an_edit_of_an_unknown_item_refuses(
    seed_item: SeedItem, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: PIN-23 -- the base cannot match an item no `items/` entry carries."""
    seed_item(_item_body("Stored.").encode())

    result = run_cli(
        ["item", "edit", "aco-abcdef", "--base", "sha256:" + "0" * 64],
        capsys,
        stdin=_item_body("Replacement."),
    )

    assert result.status == 2
    assert "does not exist" in result.stderr


def test_an_edit_with_a_body_holding_no_block_writes_nothing(
    seed_item: SeedItem,
    bare_remote: Path,
    worktree: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: ITEM-74, PIN-24 -- a piped body with no `aco` block refuses with `check -`'s own
    sentence and the state ref keeps its tip."""
    seed_item(_item_body("Stored.").encode())
    before = _stored(bare_remote, worktree)

    result = edit_item(ITEM_ID, capsys, stdin="no block\n")

    assert (result.status, result.stderr) == (2, "ERROR: body malformed: aco: no aco block\n")
    assert _stored(bare_remote, worktree) == before
