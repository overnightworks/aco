"""The merge commit `aco land` names after a RELEASED ending."""

from pathlib import Path

import pytest
from cli_fixtures import run_cli
from github_fixtures import arrange_follow_up_failures, landed_world


class TestLandMergedLine:
    def test_a_first_landing_names_the_merge_commit(
        self,
        github_clone: Path,
        bare_remote: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Spec: LANDCMD-57."""
        landed = landed_world(github_clone, bare_remote, monkeypatch)
        capsys.readouterr()
        result = run_cli(["land", "12"], capsys)
        merge_commit = landed.landing.forge.landings[12].merge_commit
        assert merge_commit is not None
        assert result.stdout.splitlines()[3:5] == ["worktree: removed", f"merged: {merge_commit}"]

    def test_a_resumed_rerun_names_the_same_merge_commit(
        self,
        github_clone: Path,
        bare_remote: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Spec: LANDCMD-57, LANDCMD-18."""
        landed = landed_world(
            github_clone,
            bare_remote,
            monkeypatch,
            extra_arrange=lambda client, _head: arrange_follow_up_failures(
                client, "forge unreachable", None
            ),
        )
        capsys.readouterr()
        first = run_cli(["land", "12"], capsys)
        landed.landing.forge.close_error = None
        rerun = run_cli(["land", "12"], capsys)
        merge_commit = landed.landing.forge.landings[12].merge_commit
        assert (first.status, rerun.status) == (2, 0)
        assert rerun.stdout.splitlines()[-1] == f"merged: {merge_commit}"
