"""What `aco land` judges when one check name has several runs on the head."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY
from cli_fixtures import run_cli
from github_fixtures import MERGE_COMMIT_SHA, FakeForge, landed_world

from aco import forge, github
from aco.github import GitHubForge

RELEASED = "RELEASED issue #72: landing\nfreed: none\nnext: none\nworktree: removed\n"
OLD_RUN = 122559589457
NEW_RUN = 122580424334


def pr_check(run_id: int, conclusion: str | None) -> dict[str, object]:
    return {"id": run_id, "name": "pr-check", "conclusion": conclusion}


OLD_RED = pr_check(OLD_RUN, "failure")
OLD_GREEN = pr_check(OLD_RUN, "success")
NEW_GREEN = pr_check(NEW_RUN, "success")
NEW_RED = pr_check(NEW_RUN, "failure")
NEW_PENDING = pr_check(NEW_RUN, None)


@dataclass(frozen=True)
class RunsCase:
    runs: list[dict[str, object]]
    status: int
    stdout: str
    stderr: str = ""


def checks_read_from(runs: list[dict[str, object]]) -> tuple[forge.CheckRun, ...]:
    """What the adapter reads for the head when GitHub answers `check-runs` with `runs`."""

    def transport(arguments: list[str], *, input_data: bytes | None = None) -> str:
        if "check-runs" in arguments[1]:
            return "\n".join(json.dumps(row) for row in runs)
        return json.dumps({"state": "pending", "total": 0})

    client = GitHubForge(github.repository_id(REPOSITORY), run=transport)
    return client.commit_checks(MERGE_COMMIT_SHA)


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

    def arrange(client: FakeForge, _head: str) -> None:
        readiness = client.readiness_by_number[12]
        checks = checks_read_from(case.runs)
        client.readiness_by_number[12] = replace(readiness, checks=checks)

    landed_world(github_clone, bare_remote, monkeypatch, extra_arrange=arrange)
    capsys.readouterr()

    result = run_cli(["land", "12"], capsys)

    assert (result.status, result.stdout, result.stderr) == (case.status, case.stdout, case.stderr)
