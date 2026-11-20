"""`aco next` and the repository's recurring audits under `storage = "state-ref"` (NEXT-62..68),
against a real bare remote: the anchor is read from the store's items with no forge request."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from board_fixtures import block_body
from cli_fixtures import (
    FROZEN_CLI_NOW,
    freeze_cli_now,
    head_sha,
    real_git,
    run_cli,
    set_git_identity,
    track_board_config,
)
from store_fixtures import item_record, path_without_gh, push_item_tree

from aco import items
from aco.body import render_block
from aco.recurring_audit import Reason

LABEL = "audit-scenario"
NAME = "scenario"
RUN = "Run the audit skill with its ownership lens."
CONFIG = (
    'storage = "state-ref"\ncanonical_remote = "origin"\n'
    f'[[audit]]\nname = "{NAME}"\nlabel = "{LABEL}"\nlandings = 3\ndays = 7\nrun = "{RUN}"\n'
)
OLDER_ID = items.format_item_id(10)
NEWEST_ID = items.format_item_id(11)
UNLABELLED_ID = items.format_item_id(12)
OLD_SHA = "c" * 40


@pytest.fixture(autouse=True)
def _frozen_run(monkeypatch: pytest.MonkeyPatch) -> None:
    set_git_identity(monkeypatch)
    freeze_cli_now(monkeypatch)


def item_file(
    item_id: str, *, created: str, anchor: str, state: str = "open", labelled: bool = True
) -> tuple[str, bytes]:
    record = {
        **item_record(
            title=f"Item {item_id}",
            state=state,
            kind="task",
            labels=(LABEL,) if labelled else (),
            closed_at=None if state == "open" else "2026-09-26T00:00:00Z",
        ),
        "created_at": created,
    }
    data = {"version": 1, "now": "Now.", "next": "Next.", "done_when": "Done.", "record": record}
    text = block_body(
        render_block(data).removesuffix("\n"), before=f"audited through {anchor}\n\n", after=""
    )
    return f"{item_id}.md", text.encode()


def land(worktree: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    moment = FROZEN_CLI_NOW.isoformat()
    monkeypatch.setenv("GIT_COMMITTER_DATE", moment)
    monkeypatch.setenv("GIT_AUTHOR_DATE", moment)
    real_git(worktree, "commit", "--allow-empty", "-q", "-m", "land")
    return head_sha(worktree)


def stand_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    bare_remote: Path,
    worktree: Path,
    *,
    commits_after_anchor: int,
    item_files: Callable[[str], dict[str, bytes]],
) -> str:
    """The state-ref world: a trunk whose commit `commits_after_anchor` back is the returned
    anchor, the items `item_files` makes of it, and no `gh` on the path."""
    real_git(worktree, "remote", "add", "origin", f"file://{bare_remote}")
    track_board_config(worktree, CONFIG)
    anchor = land(worktree, monkeypatch)
    for _ in range(commits_after_anchor):
        land(worktree, monkeypatch)
    real_git(worktree, "push", "-q", "origin", "main")
    real_git(worktree, "remote", "set-head", "origin", "main")
    push_item_tree(bare_remote, worktree, item_files(anchor))
    monkeypatch.chdir(worktree)
    monkeypatch.setenv("PATH", path_without_gh(tmp_path))
    return anchor


def test_the_newest_labelled_item_open_or_closed_is_the_anchor_and_costs_no_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    bare_remote: Path,
    worktree: Path,
) -> None:
    """Spec: NEXT-62, NEXT-63, NEXT-65."""
    anchor = stand_up(
        monkeypatch,
        tmp_path,
        bare_remote,
        worktree,
        commits_after_anchor=3,
        item_files=lambda sha: dict(
            [
                item_file(OLDER_ID, created="2026-09-01T00:00:00Z", anchor=OLD_SHA),
                item_file(NEWEST_ID, created="2026-09-20T00:00:00Z", anchor=sha, state="closed"),
                item_file(
                    UNLABELLED_ID, created="2026-09-25T00:00:00Z", anchor=OLD_SHA, labelled=False
                ),
            ]
        ),
    )

    printed = run_cli(["next"], capsys)
    payload = json.loads(run_cli(["next", "--json"], capsys).stdout)

    assert printed.stdout.startswith(
        f"audit_due {NAME}: 3 landings since {NEWEST_ID}, audited through {anchor[:7]}\n"
        f"Next: {RUN}\n\n"
    )
    assert payload["audits"] == [
        {
            "name": NAME,
            "reason": Reason.LANDINGS,
            "anchor": NEWEST_ID,
            "sha": anchor,
            "landings_since": 3,
            "days_since": 0,
            "run": RUN,
            "error": None,
        }
    ]


def test_no_labelled_item_is_no_anchor(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    bare_remote: Path,
    worktree: Path,
) -> None:
    """Spec: NEXT-63, NEXT-65."""
    stand_up(
        monkeypatch,
        tmp_path,
        bare_remote,
        worktree,
        commits_after_anchor=3,
        item_files=lambda _sha: dict(
            [
                item_file(
                    UNLABELLED_ID, created="2026-09-25T00:00:00Z", anchor=OLD_SHA, labelled=False
                )
            ]
        ),
    )

    printed = run_cli(["next"], capsys)

    assert printed.stdout.startswith(
        f"audit_due {NAME}: no item labelled {LABEL} holds an audited through line\nNext: {RUN}\n\n"
    )
