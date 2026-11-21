"""The lane branch `aco start` builds tracks its own remote branch (START-31)."""

from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, board_issue, complete_contract, write_repository_config
from cli_fixtures import (
    push_repository_trunk,
    real_git,
    real_repository_with_bare_remote,
    set_agent_identity_env,
)
from github_fixtures import FakeForge

from aco import checkout, forge, github, protocol, store, workboard
from aco import cli as issue_claim

_BRANCH = "codex/issue-314-fresh-slug-title"


def _start_scenario(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    """A real repository over a bare `origin` with a bootstrapped state ref
    and item #314 open on a fake forge; returns the repository and its remote."""
    repo, remote = real_repository_with_bare_remote(tmp_path)
    (repo / "base.txt").write_text("base\n")
    write_repository_config(repo)
    real_git(repo, "add", "base.txt", workboard.CONFIG_PATH.as_posix())
    real_git(repo, "commit", "-q", "-m", "initial")
    push_repository_trunk(repo, "origin")
    store.bootstrap(worktree=repo, remote=str(remote))
    item = board_issue(314, "Fresh Slug Title", complete_contract("Build it.", scope=["src/x.py"]))
    client = FakeForge(board_issues=(item,))
    client.issue_references[314] = forge.ItemReference(forge.ItemState.OPEN, item.title, item.body)
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    monkeypatch.setattr(
        checkout, "remote_url", lambda _remote, **_kwargs: f"git@github.com:{REPOSITORY}.git"
    )
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
    monkeypatch.chdir(repo)
    return repo, remote


def _start() -> int:
    return issue_claim.main(["--repo", REPOSITORY, "start", "314"])


def _lane_config(repo: Path, key: str) -> str:
    return real_git(repo, "config", "--get", f"branch.{_BRANCH}.{key}").stdout.strip()


def _lane_worktree(repo: Path) -> Path:
    return repo.parent / f"{repo.name}-worktrees" / "issue-314-fresh-slug-title"


def test_start_leaves_the_lane_tracking_its_own_branch_so_a_bare_push_publishes_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo, remote = _start_scenario(monkeypatch, tmp_path)
    trunk_before = real_git(remote, "rev-parse", "refs/heads/main").stdout

    assert _start() == 0

    lane = _lane_worktree(repo)
    assert _lane_config(repo, "remote") == "origin"
    assert _lane_config(repo, "merge") == f"refs/heads/{_BRANCH}"
    (lane / "lane.txt").write_text("lane\n")
    real_git(lane, "add", "lane.txt")
    real_git(lane, "commit", "-q", "-m", "lane work")
    real_git(lane, "push")
    assert (
        real_git(remote, "rev-parse", f"refs/heads/{_BRANCH}").stdout
        == real_git(lane, "rev-parse", "HEAD").stdout
    )
    assert real_git(remote, "rev-parse", "refs/heads/main").stdout == trunk_before


def test_start_rebuilding_a_gone_worktree_leaves_the_same_upstream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo, _remote = _start_scenario(monkeypatch, tmp_path)
    assert _start() == 0
    real_git(repo, "worktree", "remove", str(_lane_worktree(repo)))
    real_git(repo, "branch", "-D", _BRANCH)

    assert _start() == 0

    assert _lane_worktree(repo).is_dir()
    assert _lane_config(repo, "remote") == "origin"
    assert _lane_config(repo, "merge") == f"refs/heads/{_BRANCH}"


def test_a_refusal_after_the_build_removes_the_lane_while_the_main_checkout_stands_behind_the_trunk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo, remote = _start_scenario(monkeypatch, tmp_path)
    other = tmp_path / "other"
    real_git(tmp_path, "clone", "-q", str(remote), str(other))
    real_git(other, "config", "user.name", "Test")
    real_git(other, "config", "user.email", "test@example.com")
    real_git(other, "commit", "-q", "--allow-empty", "-m", "the trunk moves on")
    real_git(other, "push", "-q", "origin", "HEAD:main")

    def refuse_the_write(**_arguments: object) -> protocol.ClaimState:
        raise protocol.ClaimUnavailableError("the store refuses")

    monkeypatch.setattr(store, "commit_transition", refuse_the_write)

    assert _start() == 2

    assert not _lane_worktree(repo).exists()
    assert _BRANCH not in real_git(repo, "branch", "--list").stdout
