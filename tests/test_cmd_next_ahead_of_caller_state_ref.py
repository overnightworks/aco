"""`aco next` and the list of code built ahead of its caller under
`storage = "state-ref"`, against a real bare remote."""

import json
from pathlib import Path

import pytest
from board_fixtures import block_body
from cli_fixtures import real_git, run_cli, set_git_identity, track_board_config
from store_fixtures import item_record, path_without_gh, push_item_tree

from aco import items
from aco.body import render_block

OPEN_ID = items.format_item_id(10)
CLOSED_ID = items.format_item_id(12)


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    set_git_identity(monkeypatch)


def item_file(item_id: str, *, state: str) -> tuple[str, bytes]:
    record = item_record(
        title=f"Item {item_id}",
        state=state,
        kind="task",
        closed_at=None if state == "open" else "2026-09-12T00:00:00Z",
    )
    data = {"version": 1, "now": "Now.", "next": "Next.", "done_when": "Done.", "record": record}
    text = block_body(render_block(data).removesuffix("\n"), before="Prose.\n\n", after="")
    return f"{item_id}.md", text.encode()


def test_a_closed_own_item_is_red_under_either_spelling_and_named_by_its_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    bare_remote: Path,
    worktree: Path,
) -> None:
    """Spec: AHEAD-10, NEXT-54 (matrix row 14)."""
    files = dict([item_file(OPEN_ID, state="open"), item_file(CLOSED_ID, state="closed")])
    push_item_tree(bare_remote, worktree, files)
    real_git(worktree, "remote", "add", "origin", f"file://{bare_remote}")
    track_board_config(worktree, 'storage = "state-ref"\ncanonical_remote = "origin"\n')
    (worktree / ".aco" / "ahead-of-caller.toml").write_text(
        f'[[code]]\npath = "a.py"\nitem = "{CLOSED_ID}"\nreason = "first"\n'
        '[[code]]\npath = "b.py"\nitem = "#12"\nreason = "second"\n'
    )
    real_git(worktree, "add", "-f", ".aco/ahead-of-caller.toml")
    real_git(worktree, "commit", "-q", "-m", "list code built ahead of its caller")
    real_git(worktree, "push", "origin", "main")
    real_git(worktree, "remote", "set-head", "origin", "main")
    monkeypatch.chdir(worktree)
    monkeypatch.setenv("PATH", path_without_gh(tmp_path))

    text = run_cli(["next"], capsys)
    payload = json.loads(run_cli(["next", "--json"], capsys).stdout)

    assert text.stdout.splitlines()[-2:] == [
        f"ahead of caller: a.py: item {CLOSED_ID} is closed (first)",
        f"ahead of caller: b.py: item {CLOSED_ID} is closed (second)",
    ]
    assert [(entry["item"], entry["state"]) for entry in payload["ahead_of_caller"]] == [
        (CLOSED_ID, "closed"),
        (CLOSED_ID, "closed"),
    ]
