"""Pure dependency listing and path decisions (LAND-71, LAND-73..76)."""

from __future__ import annotations

import pytest
from github_fixtures import MERGE_COMMIT_SHA
from agent_coordination import board, forge, policy


@pytest.mark.parametrize(
    "after_count, expected",
    [
        pytest.param(4, "changed while aco listed its files; run the command again", id="P1"),
        pytest.param(3, frozenset({"uv.lock", "old.lock", "pyproject.toml"}), id="P3"),
    ],
)
def test_listed_paths_judge_only_a_complete_listing(
    after_count: int, expected: str | frozenset[str]
) -> None:
    changes = forge.PullRequestChanges(
        forge.ListingReading(MERGE_COMMIT_SHA, 3),
        forge.ListingReading(MERGE_COMMIT_SHA, after_count),
        (
            forge.ChangedFile("uv.lock", "old.lock"),
            forge.ChangedFile("old.lock", None),
            forge.ChangedFile("pyproject.toml", None),
        ),
    )
    result = policy.listed_paths(changes, MERGE_COMMIT_SHA)
    assert (result.reason if isinstance(result, policy.ListingDefect) else result) == expected


def test_dependency_paths_cover_only_up_to_a_slash() -> None:
    config = board.BoardConfig(dependency_paths=("uv.lock",))
    defect = policy.dependency_rule_defect(config, lambda: frozenset({"uv.lock", "uv.lock.bak"}))
    assert defect == board.ClassificationDefect(
        "changes uv.lock.bak, which dependency_paths in .aco/board.toml does not name"
    )
