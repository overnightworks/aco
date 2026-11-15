"""`checkout.trunk_landings` reading a landing's trailers through git's own configuration."""

from pathlib import Path

import pytest
from cli_fixtures import push_repository_trunk, real_git, real_repository_with_bare_remote

from aco import checkout, workboard


def test_trunk_landings_read_an_appended_coauthor_commit_with_the_walked_repository_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: LAND-83"""
    walked = tmp_path / "walked"
    walked.mkdir()
    repo, _remote = real_repository_with_bare_remote(walked, remote_name="hub")
    (repo / "base.txt").write_text("base\n")
    real_git(repo, "add", "base.txt")
    real_git(
        repo,
        "commit",
        "-q",
        "-m",
        "Landing (#4)",
        "-m",
        "Work-Item: #4",
        "-m",
        "Co-authored-by: A <a@example.invalid>",
    )
    push_repository_trunk(repo, "hub")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    real_git(elsewhere, "init", "-q")
    real_git(elsewhere, "config", "trailer.work-item.key", "Renamed-Item: ")
    real_git(elsewhere, "config", "trailer.work-item.ifexists", "replace")
    monkeypatch.chdir(elsewhere)

    [landing] = checkout.trunk_landings("refs/remotes/hub/main", 1, directory=repo)

    assert landing.classification == workboard.TrunkWorkItemClassification((4,))
