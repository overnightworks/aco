"""What `aco land` says about the default branch's checks at the merge's first parent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from cli_fixtures import real_git, run_cli
from github_fixtures import FakeForge, arrange_follow_up_failures, landed_world

from aco import forge

RELEASED = "RELEASED issue #72: landing\nfreed: none\nnext: none\nworktree: removed\n"
FAILED = forge.CheckRun("quality / verdict", "failure")
PASSED = forge.CheckRun("lint", forge.CHECK_CONCLUSION_SUCCESS)
RUNNING = forge.CheckRun("build", None)


@dataclass(frozen=True)
class TrunkCase:
    checks: tuple[forge.CheckRun, ...] | forge.ForgeError
    trunk_line: str = ""


class TestLandTrunkState:
    @pytest.mark.parametrize(
        "case",
        [
            pytest.param(
                TrunkCase((PASSED, FAILED), "trunk: red at {sha7}: quality / verdict (failure)\n"),
                id="a-failed-check-is-named",
            ),
            pytest.param(TrunkCase((PASSED,)), id="all-succeeded-prints-nothing"),
            pytest.param(TrunkCase((PASSED, RUNNING)), id="pending-prints-nothing"),
            pytest.param(TrunkCase(()), id="no-checks-print-nothing"),
            pytest.param(
                TrunkCase(
                    forge.ForgeError("forge unreachable"),
                    "trunk: unreadable at {sha7}: forge unreachable\n",
                ),
                id="an-unreadable-trunk-keeps-exit-zero",
            ),
        ],
    )
    def test_reports_the_trunk_before_the_merge(
        self,
        case: TrunkCase,
        github_clone: Path,
        bare_remote: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Spec: LANDCMD-54, LANDCMD-55."""
        first_parent = real_git(github_clone, "rev-parse", "main").stdout.strip()

        def arrange(client: FakeForge, _head: str) -> None:
            client.commit_checks_by_sha[first_parent] = case.checks

        landed_world(github_clone, bare_remote, monkeypatch, extra_arrange=arrange)
        capsys.readouterr()
        result = run_cli(["land", "12"], capsys)
        observed = (result.status, result.stdout, result.stderr)
        expected = (0, RELEASED + case.trunk_line.format(sha7=first_parent[:7]), "")
        assert observed == expected

    def test_a_rerun_reports_the_trunk_too(
        self,
        github_clone: Path,
        bare_remote: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Spec: LANDCMD-54, LANDCMD-18."""
        first_parent = real_git(github_clone, "rev-parse", "main").stdout.strip()

        def arrange(client: FakeForge, _head: str) -> None:
            client.commit_checks_by_sha[first_parent] = (FAILED,)
            arrange_follow_up_failures(client, "forge unreachable", None)

        landed = landed_world(github_clone, bare_remote, monkeypatch, extra_arrange=arrange)
        capsys.readouterr()
        first = run_cli(["land", "12"], capsys)
        landed.landing.forge.close_error = None
        rerun = run_cli(["land", "12"], capsys)
        observed = (first.status, first.stdout, rerun.status, rerun.stdout, rerun.stderr)
        expected = (
            2,
            "",
            0,
            RELEASED + f"trunk: red at {first_parent[:7]}: quality / verdict (failure)\n",
            "",
        )
        assert observed == expected
