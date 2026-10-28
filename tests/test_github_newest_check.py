"""The GitHub adapter's check-run read keeps the newest run of each check name."""

from __future__ import annotations

import json

import pytest
from board_fixtures import REPOSITORY
from github_fixtures import MERGE_COMMIT_SHA

from aco import forge, github
from aco.github import GitHubForge

CHECK_RUNS_PATH = f"repos/{REPOSITORY}/commits/{MERGE_COMMIT_SHA}/check-runs"
STATUS_PATH = f"repos/{REPOSITORY}/commits/{MERGE_COMMIT_SHA}/status"


def check_run_forge(runs: list[dict[str, object]], *, page_size: int | None = None) -> GitHubForge:
    """A real adapter whose transport answers `check-runs` with `runs` (split into pages of
    `page_size`) and reports no combined-status context."""
    pages = (
        [runs]
        if page_size is None
        else [runs[i : i + page_size] for i in range(0, len(runs), page_size)]
    )

    def fake_run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        path = arguments[1]
        if path.startswith(CHECK_RUNS_PATH):
            page = int(path.rsplit("page=", 1)[1])
            rows = pages[page - 1] if page <= len(pages) else []
            return "\n".join(json.dumps(row) for row in rows)
        assert path == STATUS_PATH
        return json.dumps({"state": "pending", "total": 0})

    return GitHubForge(github.repository_id(REPOSITORY), run=fake_run)


def run_row(run_id: int, name: str, conclusion: str | None) -> dict[str, object]:
    return {"id": run_id, "name": name, "conclusion": conclusion}


def names_and_conclusions(checks: tuple[forge.CheckRun, ...]) -> list[tuple[str, str | None]]:
    return [(check.name, check.conclusion) for check in checks]


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        pytest.param(
            [
                run_row(122559589457, "pr-check", "failure"),
                run_row(122580424334, "pr-check", "success"),
            ],
            [("pr-check", "success")],
            id="newer-after-older",
        ),
        pytest.param(
            [
                run_row(122580424334, "pr-check", "success"),
                run_row(122559589457, "pr-check", "failure"),
            ],
            [("pr-check", "success")],
            id="newer-before-older",
        ),
        pytest.param(
            [run_row(7, "pr-check", "success"), run_row(9, "pr-check", None)],
            [("pr-check", None)],
            id="newest-still-running",
        ),
        pytest.param(
            [
                run_row(3, "build", "failure"),
                run_row(4, "lint", "success"),
                run_row(5, "build", "success"),
            ],
            [("build", "success"), ("lint", "success")],
            id="other-names-stay",
        ),
    ],
)
def test_check_read_keeps_the_newest_run_of_each_name(
    runs: list[dict[str, object]], expected: list[tuple[str, str | None]]
) -> None:
    """Spec: LANDCMD-56."""
    client = check_run_forge(runs)

    checks = client.commit_checks(MERGE_COMMIT_SHA)

    assert names_and_conclusions(checks) == expected


def test_check_read_compares_runs_across_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec: LANDCMD-56."""
    monkeypatch.setattr(github, "ISSUES_PER_PAGE", 1)
    client = check_run_forge(
        [run_row(1, "pr-check", "failure"), run_row(2, "pr-check", "success")], page_size=1
    )

    checks = client.commit_checks(MERGE_COMMIT_SHA)

    assert names_and_conclusions(checks) == [("pr-check", "success")]


@pytest.mark.parametrize("run_id", [None, "7"])
def test_check_read_refuses_a_run_without_an_integer_id(run_id: object) -> None:
    """Spec: LANDCMD-56."""
    client = check_run_forge([{"id": run_id, "name": "build", "conclusion": "success"}])

    with pytest.raises(forge.ForgeMalformedResponseError, match="malformed check run"):
        client.commit_checks(MERGE_COMMIT_SHA)
