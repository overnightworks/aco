"""`aco cut` never adopts a sub-issue recorded in another repository."""

from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, container_issue
from cli_fixtures import freeze_cli_now, run_cli, track_board_config
from github_fixtures import FakeForge, serve_forge

from aco import forge, workboard

CONTAINER = 79
FOREIGN_NUMBER = 950
SLICE_TITLE = "Slice A"


def test_cut_creates_the_child_beside_a_foreign_sub_issue_with_the_same_title(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_world: Path,
) -> None:
    """Spec: CUT-44"""
    track_board_config(github_world, 'idea_label = "idea"\n')
    freeze_cli_now(monkeypatch)
    row = f'[[slice]]\nindex = 1\ntitle = "{SLICE_TITLE}"\ndone_when = "D"\n'
    foreign = workboard.ForeignChild(
        workboard.IssueReference("other/repo", FOREIGN_NUMBER), workboard.ChildState.OPEN
    )
    same_title = forge.ItemReference(forge.ItemState.OPEN, SLICE_TITLE, "", False)
    served = serve_forge(
        monkeypatch,
        FakeForge(
            board_issues=(container_issue(CONTAINER, MINIMAL_BLOCK_TOML + row),),
            children={CONTAINER: (foreign,)},
            issue_references={FOREIGN_NUMBER: same_title},
        ),
    )

    result = run_cli(["cut", str(CONTAINER), "--title", SLICE_TITLE, "--not-a-twin"], capsys)

    created_titles = [title for _, title, _, _ in served.created_children]
    assert (result.status, result.stdout.split()[0], created_titles) == (0, "CUT", [SLICE_TITLE])
