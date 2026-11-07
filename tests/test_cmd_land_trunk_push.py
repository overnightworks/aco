"""What `aco land` reports about a trunk whose commit also carries manual workflow runs."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY
from cli_fixtures import real_git, run_cli
from github_fixtures import FakeForge, landed_world

from aco import forge, github
from aco.github import GitHubForge

RELEASED = "RELEASED issue #72: landing\nfreed: none\nnext: none\nworktree: removed\n"
PUSH_SUITE = 501
MANUAL_SUITE = 502


def actions_check(run_id: int, name: str, conclusion: str, suite: int) -> dict[str, object]:
    return {"id": run_id, "name": name, "conclusion": conclusion, "suite": suite}


def other_app_check(run_id: int, name: str, conclusion: str) -> dict[str, object]:
    return {"id": run_id, "name": name, "conclusion": conclusion, "suite": None}


def workflow_run(event: str, suite: int) -> dict[str, object]:
    return {"event": event, "suite": suite}


@dataclass(frozen=True)
class TrunkRead:
    check_runs: list[dict[str, object]]
    workflow_runs: list[dict[str, object]] | forge.ForgeError | str
    trunk_line: str = ""


def checks_read_from(read: TrunkRead, sha: str) -> tuple[forge.CheckRun, ...] | forge.ForgeError:
    """What the adapter's trunk read answers when GitHub gives `read`'s rows."""

    def transport(arguments: list[str], *, input_data: bytes | None = None) -> str:
        path = arguments[-3] if "--paginate" in arguments else arguments[1]
        if "check-runs" in path:
            return "\n".join(json.dumps(row) for row in read.check_runs)
        if "actions/runs" in path:
            if isinstance(read.workflow_runs, forge.ForgeError):
                raise read.workflow_runs
            if isinstance(read.workflow_runs, str):
                return read.workflow_runs
            return "\n".join(json.dumps(row) for row in read.workflow_runs)
        return json.dumps({"state": "pending", "total": 0})

    client = GitHubForge(github.repository_id(REPOSITORY), run=transport)
    try:
        return client.commit_checks(sha, push_only=True)
    except forge.ForgeError as error:
        return error


@pytest.mark.parametrize(
    "read",
    [
        pytest.param(
            TrunkRead(
                [
                    actions_check(1, "Gate", "failure", MANUAL_SUITE),
                    actions_check(2, "CI", "success", PUSH_SUITE),
                ],
                [workflow_run("workflow_dispatch", MANUAL_SUITE), workflow_run("push", PUSH_SUITE)],
            ),
            id="a-manual-run-refusal-is-not-red",
        ),
        pytest.param(
            TrunkRead(
                [
                    actions_check(1, "Image", "success", PUSH_SUITE),
                    actions_check(2, "Image", "skipped", MANUAL_SUITE),
                ],
                [workflow_run("push", PUSH_SUITE), workflow_run("workflow_dispatch", MANUAL_SUITE)],
            ),
            id="a-manual-skipped-job-does-not-hide-the-push-job",
        ),
        pytest.param(
            TrunkRead(
                [actions_check(1, "Image", "failure", PUSH_SUITE)],
                [workflow_run("push", PUSH_SUITE)],
                "trunk: red at {sha7}: Image (failure)\n",
            ),
            id="a-failed-push-job-is-red",
        ),
        pytest.param(
            TrunkRead(
                [actions_check(1, "Gate", "failure", MANUAL_SUITE)],
                [],
            ),
            id="a-run-the-workflow-listing-lacks-is-not-judged",
        ),
        pytest.param(
            TrunkRead(
                [other_app_check(1, "CodeQL", "failure")],
                [],
                "trunk: red at {sha7}: CodeQL (failure)\n",
            ),
            id="another-apps-check-counts-without-a-workflow-run",
        ),
        pytest.param(
            TrunkRead(
                [actions_check(1, "CI", "success", PUSH_SUITE)],
                forge.ForgeError("rate limited"),
                "trunk: unreadable at {sha7}: rate limited\n",
            ),
            id="an-unreadable-workflow-run-read-is-never-fine",
        ),
        pytest.param(
            TrunkRead(
                [actions_check(1, "CI", "success", PUSH_SUITE)],
                "not json",
                "trunk: unreadable at {sha7}: GitHub returned a malformed workflow run\n",
            ),
            id="an-undecodable-workflow-run-is-unreadable",
        ),
        pytest.param(
            TrunkRead(
                [actions_check(1, "CI", "success", PUSH_SUITE)],
                '{"event": "push"}',
                "trunk: unreadable at {sha7}: GitHub returned a malformed workflow run\n",
            ),
            id="a-malformed-workflow-run-is-unreadable",
        ),
    ],
)
def test_land_judges_the_push_runs_of_the_trunk(
    read: TrunkRead,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: LANDCMD-58, LANDCMD-54, LANDCMD-55."""
    first_parent = real_git(github_clone, "rev-parse", "main").stdout.strip()

    def arrange(client: FakeForge, _head: str) -> None:
        client.commit_checks_by_sha[first_parent] = checks_read_from(read, first_parent)

    landed = landed_world(github_clone, bare_remote, monkeypatch, extra_arrange=arrange)
    capsys.readouterr()

    result = run_cli(["land", "12"], capsys)

    merged = f"merged: {landed.landing.forge.landings[12].merge_commit}\n"
    expected = RELEASED + merged + read.trunk_line.format(sha7=first_parent[:7])
    assert (result.status, result.stdout, result.stderr) == (0, expected, "")
