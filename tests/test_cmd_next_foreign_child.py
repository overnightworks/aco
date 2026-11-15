"""`aco next` reads a container whose sub-issues include one from another
repository, as GitHub reports them, and never offers that child (BOARD-60)."""

import json

import pytest
from board_fixtures import REPOSITORY, board_issue, complete_contract, container_with_children
from cli_fixtures import freeze_cli_now, run_cli
from github_fixtures import FakeForge, serve_forge

from aco import workboard
from aco.github import GitHubForge, repository_id

CONTAINER = 243
LOCAL_CHILD = 244
FOREIGN_REPOSITORY = "other/repo"
FOREIGN_NUMBER = 954


def sub_issue_row(repository: str, number: int, state: str) -> str:
    return json.dumps(
        {
            "number": number,
            "repository": f"https://api.github.com/repos/{repository}",
            "state": state,
        }
    )


SUB_ISSUES = "\n".join(
    (
        sub_issue_row(REPOSITORY, LOCAL_CHILD, "open"),
        sub_issue_row(FOREIGN_REPOSITORY, FOREIGN_NUMBER, "open"),
        sub_issue_row(REPOSITORY, 1000, "closed"),
    )
)


def scripted_gh(arguments: list[str], *, input_data: bytes | None = None) -> str:
    """`gh` answering the repository lookup and the one sub-issue listing."""
    return REPOSITORY if arguments[-2:] == ["--jq", ".full_name"] else SUB_ISSUES


class ForgeListingSubIssuesFromGitHub(FakeForge):
    """The board's forge, except that a container's children are the `gh`
    sub-issue rows `GitHubForge` parses."""

    def list_children(self, number: int) -> workboard.ChildList:
        return GitHubForge(repository_id(REPOSITORY), run=scripted_gh).list_children(number)


@pytest.mark.usefixtures("github_world")
def test_next_offers_the_local_child_of_a_container_that_also_has_a_foreign_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BOARD-60"""
    container, _ = container_with_children(
        CONTAINER,
        closed=1,
        open_children=(LOCAL_CHILD,),
        foreign_open=(workboard.IssueReference(FOREIGN_REPOSITORY, FOREIGN_NUMBER),),
        body=complete_contract("Cut the next slice."),
    )
    local_child = board_issue(LOCAL_CHILD, "Local child", complete_contract("Ship it."))
    freeze_cli_now(monkeypatch)
    serve_forge(monkeypatch, ForgeListingSubIssuesFromGitHub(board_issues=(container, local_child)))

    result = run_cli(["next"], capsys)

    assert (
        result.status,
        f"#{LOCAL_CHILD}" in result.stdout,
        str(FOREIGN_NUMBER) in result.stdout,
    ) == (
        0,
        True,
        False,
    )
