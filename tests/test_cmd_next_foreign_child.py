"""`aco next` reads a container whose sub-issues include one from another
repository, as GitHub reports them, and never offers that child (BOARD-60)."""

from dataclasses import dataclass

import pytest
from board_fixtures import REPOSITORY, board_issue, complete_contract, container_with_children
from cli_fixtures import freeze_cli_now, run_cli
from github_fixtures import FakeForge, scripted_gh, serve_forge, sub_issue_row
from github_pages import listing_runner

from aco import workboard
from aco.github import GitHubForge, repository_id

CONTAINER = 243
LOCAL_CHILD = 244
FOREIGN_REPOSITORY = "other/repo"
FOREIGN_NUMBER = 954
FOREIGN_LABEL = f"{FOREIGN_REPOSITORY}#{FOREIGN_NUMBER}"
FOREIGN_ROW = sub_issue_row(FOREIGN_REPOSITORY, FOREIGN_NUMBER, "open")
CLOSED_ROW = sub_issue_row(REPOSITORY, 1000, "closed")
LOCAL_ROW = sub_issue_row(REPOSITORY, LOCAL_CHILD, "open")


@dataclass
class ForgeListingSubIssuesFromGitHub(FakeForge):
    """The board's forge, except that a container's children are the `gh`
    sub-issue rows `GitHubForge` parses."""

    rows: tuple[str, ...] = ()

    def list_children(self, number: int) -> workboard.ChildList:
        return GitHubForge(
            repository_id(REPOSITORY), run=listing_runner(scripted_gh(*self.rows))
        ).list_children(number)


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
    forge = ForgeListingSubIssuesFromGitHub(
        board_issues=(container, local_child), rows=(LOCAL_ROW, FOREIGN_ROW, CLOSED_ROW)
    )
    serve_forge(monkeypatch, forge)

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


@pytest.mark.usefixtures("github_world")
def test_next_reads_a_container_whose_only_open_child_is_foreign_as_waiting_on_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: NEXT-60"""
    container, _ = container_with_children(CONTAINER, closed=1, body=complete_contract("Wait."))
    freeze_cli_now(monkeypatch)
    forge = ForgeListingSubIssuesFromGitHub(
        board_issues=(container,), rows=(FOREIGN_ROW, CLOSED_ROW)
    )
    serve_forge(monkeypatch, forge)

    result = run_cli(["next"], capsys)

    waiting_line = f"#{CONTAINER}: container; waiting on {FOREIGN_LABEL}"
    assert (result.status, waiting_line in result.stdout.splitlines()) == (3, True)
