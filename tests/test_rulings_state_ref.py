"""`aco rulings` under `storage = "state-ref"` against a real bare remote."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from board_fixtures import block_body, write_repository_config
from cli_fixtures import real_git, run_cli, set_git_identity, stub_board_config_tracked
from option_cards import open_option_entry
from store_fixtures import blob, push_raw_state_tree, raw_tree

from aco import items, protocol
from aco.body import render_block

LISTED_ID = "aco-000004"
EXISTING_BLOCKER_ID = "aco-000005"
MISSING_ID = "aco-ffffff"


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    set_git_identity(monkeypatch)


def _item_file(item_id: str, *, expectations: bool, **links: object) -> tuple[str, bytes]:
    data: dict[str, object] = {
        "version": 1,
        "now": "Now.",
        "next": "Next.",
        "done_when": "Done.",
        "record": {
            "title": f"Item {item_id}",
            "state": "open",
            "kind": "task",
            "labels": [],
            "blocked_by": [],
            "parent": None,
            "created_at": "2026-09-10T00:00:00Z",
            "updated_at": "2026-09-15T00:00:00Z",
            **links,
        },
    }
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
    entries = [
        ("100644", "blob", blob(worktree, content), name) for name, content in item_files.items()
    ]
    schema = blob(worktree, protocol.serialize_empty_schema_toml().encode())
    push_raw_state_tree(
        bare_remote,
        worktree,
        [
            ("100644", "blob", schema, "schema.toml"),
            ("040000", "tree", raw_tree(worktree, entries), "items"),
        ],
    )
    real_git(worktree, "remote", "add", "origin", f"file://{bare_remote}")
    real_git(worktree, "push", "origin", "main")
    real_git(worktree, "remote", "set-head", "origin", "main")
    write_repository_config(worktree, 'storage = "state-ref"\ncanonical_remote = "origin"\n')
    stub_board_config_tracked(monkeypatch)
    monkeypatch.chdir(worktree)
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    for tool in ("git", "bash"):
        executable = shutil.which(tool)
        assert executable is not None
        (bin_directory / tool).symlink_to(executable)
    monkeypatch.setenv("PATH", str(bin_directory))


@pytest.mark.parametrize("as_json", [pytest.param(False, id="text"), pytest.param(True, id="json")])
@pytest.mark.parametrize(
    "links",
    [
        pytest.param({"parent": MISSING_ID}, id="parent-names-a-missing-id"),
        pytest.param({"blocked_by": [MISSING_ID]}, id="blocker-names-a-missing-id"),
        pytest.param(
            {"blocked_by": [EXISTING_BLOCKER_ID, EXISTING_BLOCKER_ID]}, id="blocker-named-twice"
        ),
    ],
)
def test_rulings_lists_an_item_whose_record_links_do_not_resolve(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    bare_remote: Path,
    worktree: Path,
    links: dict[str, object],
    as_json: bool,
) -> None:
    """Spec: RUL-21 --
    A broken `record.parent` or `record.blocked_by` does not keep the item out of `aco rulings`."""
    files = dict(
        [
            _item_file(LISTED_ID, expectations=True, **links),
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
