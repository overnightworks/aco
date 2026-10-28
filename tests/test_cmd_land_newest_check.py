"""What `aco land` judges when one check name has several runs on the head."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from cli_fixtures import run_cli
from github_fixtures import MERGE_COMMIT_SHA, FakeForge, landed_world
from test_github_newest_check import check_run_forge, run_row

RELEASED = "RELEASED issue #72: landing\nfreed: none\nnext: none\nworktree: removed\n"
OLD_RED = run_row(122559589457, "pr-check", "failure")
OLD_GREEN = run_row(122559589457, "pr-check", "success")
NEW_GREEN = run_row(122580424334, "pr-check", "success")
NEW_RED = run_row(122580424334, "pr-check", "failure")
NEW_PENDING = run_row(122580424334, "pr-check", None)


@dataclass(frozen=True)
class RunsCase:
    runs: list[dict[str, object]]
    status: int
    stdout: str
    stderr: str = ""


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(RunsCase([OLD_RED, NEW_GREEN], 0, RELEASED), id="old-red-new-green-lands"),
        pytest.param(
            RunsCase(
                [OLD_GREEN, NEW_RED],
                2,
                "",
                "ERROR: pull request #12 has non-successful checks: pr-check (failure); land only "
                "after every check succeeds\n",
            ),
            id="old-green-new-red-refuses",
        ),
        pytest.param(
            RunsCase(
                [OLD_RED, NEW_PENDING],
                2,
                "",
                "ERROR: pull request #12 has checks still running: pr-check; wait for every check "
                "to succeed\n",
            ),
            id="old-red-new-pending-waits",
        ),
    ],
)
def test_land_judges_only_the_newest_run_of_a_check_name(
    case: RunsCase,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: LANDCMD-56, LANDCMD-06, LANDCMD-45."""
    adapter = check_run_forge(case.runs)

    def arrange(client: FakeForge, _head: str) -> None:
        readiness = client.readiness_by_number[12]
        checks = adapter.commit_checks(MERGE_COMMIT_SHA)
        client.readiness_by_number[12] = replace(readiness, checks=checks)

    landed_world(github_clone, bare_remote, monkeypatch, extra_arrange=arrange)
    capsys.readouterr()

    result = run_cli(["land", "12"], capsys)

    assert (result.status, result.stdout, result.stderr) == (case.status, case.stdout, case.stderr)
