"""`aco item show` under `storage = "state-ref"`: the parent in its header (specs/item.spec.md)."""

import tomllib
from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import run_cli, set_git_identity
from store_fixtures import item_record, seed_state_ref_checkout

from aco import body

PARENT_ID = "aco-000001"
CHILD_ID = "aco-000002"
MISSING_ID = "aco-ffffff"


@pytest.fixture(autouse=True)
def commit_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    set_git_identity(monkeypatch)


def _item_file(parent: str | None) -> bytes:
    data = {
        **tomllib.loads(MINIMAL_BLOCK_TOML),
        "record": item_record(title="Karte", state="open", kind="task", parent=parent),
    }
    return block_body(body.render_block(data).removesuffix("\n"), before="Prose.\n\n").encode()


@pytest.mark.parametrize(
    ("parent", "refusal"),
    [
        pytest.param(PARENT_ID, None, id="a-parent-items-holds"),
        pytest.param(
            MISSING_ID,
            f"ERROR: item {MISSING_ID} is referenced as a parent but does not exist\n",
            id="a-parent-items-lacks",
        ),
    ],
)
def test_show_names_the_recorded_parent_or_refuses_one_items_lacks(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    bare_remote: Path,
    worktree: Path,
    parent: str,
    refusal: str | None,
) -> None:
    """ITEM-82."""
    files = {f"{PARENT_ID}.md": _item_file(None), f"{CHILD_ID}.md": _item_file(parent)}
    seed_state_ref_checkout(monkeypatch, tmp_path, bare_remote, worktree, files)

    shown = run_cli(["item", "show", CHILD_ID], capsys)

    header = shown.stdout.split(" · ")[3:4]
    assert (shown.status, shown.stderr, header) == (
        (0, "", [f"parent {PARENT_ID}"]) if refusal is None else (2, refusal, [])
    )
