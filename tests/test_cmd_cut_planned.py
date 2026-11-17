"""`aco cut` stamps a container's planned count on its first cut (CUT-45..47)."""

from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body, container_issue
from cli_fixtures import (
    freeze_cli_now,
    real_git,
    run_cli,
    set_git_identity,
    track_board_config,
)
from github_fixtures import FakeForge, serve_forge
from store_fixtures import item_record, path_without_gh, push_item_tree

from aco import body, forge, items, store, workboard

CONTAINER = 79
OLD_CHILD = 801
FOREIGN_CHILD = 950


def _rows(count: int) -> str:
    return "".join(
        f'[[slice]]\nindex = {index}\ntitle = "Slice {index}"\ndone_when = "D"\n'
        for index in range(1, count + 1)
    )


def _forge(
    block_toml: str, children: tuple[workboard.ChildItem | workboard.ForeignChild, ...]
) -> FakeForge:
    return FakeForge(
        board_issues=(container_issue(CONTAINER, block_toml),),
        children={CONTAINER: children} if children else {},
        issue_references={
            OLD_CHILD: forge.ItemReference(forge.ItemState.CLOSED, "Done earlier", "", False)
        },
    )


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    set_git_identity(monkeypatch)


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch, github_world: Path) -> ServedCut:
    track_board_config(github_world, 'idea_label = "idea"\n')
    freeze_cli_now(monkeypatch)
    return ServedCut(monkeypatch)


class ServedCut:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch

    def serve(self, fake: FakeForge) -> FakeForge:
        return serve_forge(self._monkeypatch, fake)


def _written_block(fake: FakeForge) -> dict[str, object]:
    [(_, written)] = fake.body_writes
    return body.locate_block(written).data


def _cut(capsys: pytest.CaptureFixture[str], *extra: str) -> int | str | None:
    return run_cli(["cut", str(CONTAINER), "--not-a-twin", *extra], capsys).status


def test_the_first_cut_stamps_the_children_plus_the_rows(
    served: ServedCut, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CUT-45"""
    fake = served.serve(_forge(MINIMAL_BLOCK_TOML + _rows(3), ()))

    status = _cut(capsys)

    block = _written_block(fake)
    assert (status, block["planned_at_first_cut"], len(block["slice"])) == (0, 3, 2)  # type: ignore[arg-type]


def test_a_later_cut_keeps_the_stamp(served: ServedCut, capsys: pytest.CaptureFixture[str]) -> None:
    """Spec: CUT-46"""
    toml = MINIMAL_BLOCK_TOML + "planned_at_first_cut = 3\n" + _rows(2)
    fake = served.serve(
        _forge(toml, (workboard.ChildItem(OLD_CHILD, workboard.ChildState.CLOSED, "Done earlier"),))
    )

    status = _cut(capsys)

    assert (status, _written_block(fake)["planned_at_first_cut"]) == (0, 3)


def test_a_cut_on_a_container_that_has_a_stamp_and_no_child_keeps_it(
    served: ServedCut, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CUT-46"""
    fake = served.serve(_forge(MINIMAL_BLOCK_TOML + "planned_at_first_cut = 9\n" + _rows(2), ()))

    status = _cut(capsys)

    assert (status, _written_block(fake)["planned_at_first_cut"]) == (0, 9)


@pytest.mark.parametrize(
    "existing",
    [
        pytest.param(
            workboard.ChildItem(OLD_CHILD, workboard.ChildState.CLOSED, "Done earlier"),
            id="closed-child",
        ),
        pytest.param(
            workboard.ChildItem(OLD_CHILD + 1, workboard.ChildState.OPEN, "Open earlier"),
            id="open-child",
        ),
        pytest.param(
            workboard.ForeignChild(
                workboard.IssueReference("other/repo", FOREIGN_CHILD), workboard.ChildState.OPEN
            ),
            id="foreign-child",
        ),
    ],
)
def test_a_container_with_another_child_gets_no_stamp(
    served: ServedCut,
    capsys: pytest.CaptureFixture[str],
    existing: workboard.ChildItem | workboard.ForeignChild,
) -> None:
    """Spec: CUT-46"""
    fake = served.serve(_forge(MINIMAL_BLOCK_TOML + _rows(2), (existing,)))

    status = _cut(capsys)

    assert (status, "planned_at_first_cut" in _written_block(fake)) == (0, False)


def test_a_cut_without_a_linked_row_writes_no_stamp_and_no_body(
    served: ServedCut, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CUT-47"""
    fake = served.serve(_forge(MINIMAL_BLOCK_TOML, ()))

    status = _cut(capsys, "--title", "Slice X")

    assert (status, fake.body_writes) == (0, [])


def test_a_rerun_after_a_failed_first_write_stamps_the_same_count_once(
    served: ServedCut, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CUT-18, CUT-46"""
    fake = served.serve(_forge(MINIMAL_BLOCK_TOML + _rows(3), ()))
    fake.fail_update_item_body = True
    failed = _cut(capsys)
    fake.fail_update_item_body = False

    fake.issue_references[900] = forge.ItemReference(forge.ItemState.OPEN, "Slice 1", "", False)
    status = _cut(capsys)

    assert (
        failed,
        status,
        len(fake.created_children),
        _written_block(fake)["planned_at_first_cut"],
    ) == (
        2,
        0,
        1,
        3,
    )


def test_an_adopted_orphan_is_not_counted_twice(
    served: ServedCut, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CUT-45"""
    orphan = 905
    fake = _forge(MINIMAL_BLOCK_TOML + _rows(3), ())
    parent_line = body.parent_line(workboard.item_label(CONTAINER, workboard.Storage.GITHUB))
    fake.board_issues = (
        *fake.board_issues,
        workboard.Issue(
            orphan,
            "Slice 1",
            (),
            parent_line + "\n",
            "2026-08-20T00:00:00Z",
            "2026-08-20T00:00:00Z",
            kind=body.ItemKind.TASK,
        ),
    )
    served.serve(fake)

    status = _cut(capsys)

    block = _written_block(fake)
    assert (status, fake.created_children, block["planned_at_first_cut"]) == (0, [], 3)


def test_the_first_cut_stamps_a_state_ref_container(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    bare_remote: Path,
    worktree: Path,
) -> None:
    """Spec: CUT-45"""
    container_id = items.format_item_id(10)
    data = {
        "version": 1,
        "now": "N",
        "next": "X",
        "done_when": "D",
        "slice": [{"index": n, "title": f"Slice {n}", "done_when": "D"} for n in (1, 2, 3)],
        "record": item_record(title="Epic", state="open", kind="container"),
    }
    text = block_body(body.render_block(data).removesuffix("\n"), after="")
    push_item_tree(bare_remote, worktree, {f"{container_id}.md": text.encode()})
    real_git(worktree, "remote", "add", "origin", f"file://{bare_remote}")
    track_board_config(worktree, 'storage = "state-ref"\ncanonical_remote = "origin"\n')
    real_git(worktree, "push", "origin", "main")
    real_git(worktree, "remote", "set-head", "origin", "main")
    monkeypatch.chdir(worktree)
    monkeypatch.setenv("PATH", path_without_gh(tmp_path))

    status = run_cli(["cut", str(items.item_number(container_id)), "--not-a-twin"], capsys).status

    tip = store.fetch_state(worktree=worktree, remote=f"file://{bare_remote}").tip
    assert tip is not None
    written = store.read_item_files(worktree, tip)[f"{container_id}.md"].decode()
    block = body.locate_block(written).data
    assert (status, block["planned_at_first_cut"], len(block["slice"])) == (0, 3, 2)  # type: ignore[arg-type]
