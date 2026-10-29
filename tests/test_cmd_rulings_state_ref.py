"""`aco rulings` under `storage = "state-ref"` against a real bare remote."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from board_fixtures import block_body, slice_entries
from cli_fixtures import real_git, run_cli, set_git_identity, track_board_config
from option_cards import open_option_entry
from store_fixtures import item_record, path_without_gh, push_item_tree

from aco import items
from aco.body import render_block

LISTED_ID = "aco-000004"
EXISTING_BLOCKER_ID = "aco-000005"
MISSING_ID = "aco-ffffff"


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    set_git_identity(monkeypatch)


def _item_file(
    item_id: str, *, expectations: bool, kind: str = "task", **links: object
) -> tuple[str, bytes]:
    """A container carries one uncut `[[slice]]`: the shape whose parent `aco board` looks up."""
    record = item_record(title=f"Item {item_id}", state="open", kind=kind)
    data: dict[str, object] = {
        "version": 1,
        "now": "Now.",
        "next": "Next.",
        "done_when": "Done.",
        "record": {**record, **links},
    }
    if kind == "container":
        data["slice"] = slice_entries("First slice")
    if expectations:
        data["expectation"] = [open_option_entry()]
    text = block_body(render_block(data).removesuffix("\n"), before="Prose.\n\n", after="")
    return f"{item_id}.md", text.encode()


def _checkout_listing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    bare_remote: Path,
    worktree: Path,
    item_files: dict[str, bytes],
) -> None:
    """A real checkout pinned to `storage = "state-ref"` whose `origin` carries `item_files`."""
    push_item_tree(bare_remote, worktree, item_files)
    real_git(worktree, "remote", "add", "origin", f"file://{bare_remote}")
    real_git(worktree, "push", "origin", "main")
    real_git(worktree, "remote", "set-head", "origin", "main")
    track_board_config(worktree, 'storage = "state-ref"\ncanonical_remote = "origin"\n')
    monkeypatch.chdir(worktree)
    monkeypatch.setenv("PATH", path_without_gh(tmp_path))


@pytest.mark.parametrize("as_json", [pytest.param(False, id="text"), pytest.param(True, id="json")])
@pytest.mark.parametrize(
    "kind, links",
    [
        pytest.param(
            "container",
            {"parent": MISSING_ID},
            id="childless-container-with-uncut-slice-names-a-missing-parent",
        ),
        pytest.param("task", {"blocked_by": [MISSING_ID]}, id="blocker-names-a-missing-id"),
        pytest.param(
            "task",
            {"blocked_by": [EXISTING_BLOCKER_ID, EXISTING_BLOCKER_ID]},
            id="blocker-named-twice",
        ),
    ],
)
def test_rulings_lists_an_item_whose_record_links_do_not_resolve(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    bare_remote: Path,
    worktree: Path,
    kind: str,
    links: dict[str, object],
    as_json: bool,
) -> None:
    """Spec: RUL-21 --
    A broken `record.parent` or `record.blocked_by` does not keep the item out of `aco rulings`."""
    files = dict(
        [
            _item_file(LISTED_ID, expectations=True, kind=kind, **links),
            _item_file(EXISTING_BLOCKER_ID, expectations=False),
        ]
    )
    _checkout_listing(monkeypatch, tmp_path, bare_remote, worktree, files)
    capsys.readouterr()
    result = run_cli(["rulings", *(["--json"] if as_json else [])], capsys)
    assert result.status == 0
    if as_json:
        assert [row["number"] for row in json.loads(result.stdout)["rulings"]] == [
            items.item_number(LISTED_ID)
        ]
    else:
        assert result.stdout.splitlines()[0].startswith(f"{LISTED_ID} ")
