"""The GitHub adapter's reading of a container's sub-issues."""

import json

from board_fixtures import REPOSITORY

from aco import github, workboard
from aco.github import GitHubForge

FOREIGN_REPOSITORY = "other/repo"


def sub_issue_row(repository: str, number: int) -> str:
    return json.dumps(
        {
            "number": number,
            "repository": f"https://api.github.com/repos/{repository}",
            "state": "open",
        }
    )


def test_github_adapter_reports_a_sub_issue_of_another_repository_as_foreign() -> None:
    """Spec: BOARD-59"""
    listing = "\n".join((sub_issue_row(REPOSITORY, 72), sub_issue_row(FOREIGN_REPOSITORY, 954)))

    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        return REPOSITORY if arguments[-2:] == ["--jq", ".full_name"] else listing

    client = GitHubForge(github.repository_id(REPOSITORY), run=run)

    children = client.list_children(79)

    local = [child.number for child in workboard.local_children(children)]
    foreign = [
        str(child.reference) for child in children if isinstance(child, workboard.ForeignChild)
    ]
    assert (local, foreign) == ([72], [f"{FOREIGN_REPOSITORY}#954"])
