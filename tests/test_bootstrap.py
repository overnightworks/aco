"""`aco bootstrap`, driven through the CLI against real git (`specs/bootstrap.spec.md`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cli_fixtures import (
    count_context_reads,
    real_git,
    redirect_toplevel,
    run_cli,
    set_git_identity,
    stub_board_config_tracked,
)

from agent_coordination import protocol, store

BOOTSTRAP_REPOSITORY = "example/agent-coordination"


@pytest.fixture(autouse=True)
def _tracked_board_config_and_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    set_git_identity(monkeypatch)
    stub_board_config_tracked(monkeypatch)


@pytest.fixture
def clone(monkeypatch: pytest.MonkeyPatch, worktree: Path, bare_remote: Path) -> Path:
    """The `worktree` with its `origin` at the empty `bare_remote`, entered as the cwd."""
    real_git(worktree, "remote", "add", "origin", str(bare_remote))
    redirect_toplevel(monkeypatch, worktree)
    monkeypatch.chdir(worktree)
    return worktree


@pytest.mark.parametrize(
    "origin_url",
    [
        pytest.param("git@github.com:example/agent-coordination.git", id="github-remote"),
        pytest.param("git@gitlab.com:other/repo.git", id="non-github-remote"),
    ],
)
def test_bootstrap_with_a_repo_prints_the_ref_commit_id_as_without_one(
    clone: Path,
    bare_remote: Path,
    origin_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: BOOT-03 -- `--repo OWNER/REPO` against any canonical remote host."""
    real_git(clone, "config", f"url.{bare_remote}.insteadOf", origin_url)
    real_git(clone, "remote", "set-url", "origin", origin_url)

    with_repo = run_cli(["--repo", BOOTSTRAP_REPOSITORY, "bootstrap"], capsys)
    without_repo = run_cli(["bootstrap"], capsys)

    assert with_repo.stderr == ""
    assert without_repo.stderr == ""
    remote_state_commit = real_git(bare_remote, "rev-parse", store.STATE_REF).stdout.strip()
    assert with_repo.expect_success() == f"{remote_state_commit}\n"
    assert without_repo.expect_success() == with_repo.stdout


@pytest.mark.parametrize(
    "extra_arguments",
    [
        pytest.param(["--ledger", "5"], id="ledger-flag"),
        pytest.param(["--json"], id="json-flag"),
        pytest.param(["extra"], id="positional"),
    ],
)
def test_bootstrap_refuses_an_argument_it_does_not_define_before_any_read(
    clone: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: BOOT-02 -- an argument `bootstrap` does not define is refused."""
    reads = count_context_reads(monkeypatch)

    refused = run_cli(["bootstrap", *extra_arguments], capsys)

    assert refused.expect_refusal().endswith(
        f"aco: error: unrecognized arguments: {' '.join(extra_arguments)}\n"
    )
    assert reads.drain() == ({}, {}, {})


def test_bootstrap_refuses_an_unreachable_remote_on_stderr_alone(
    clone: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BOOT-01 -- a store-level refusal prints only `ERROR: <sentence>`."""
    real_git(clone, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

    with pytest.raises(protocol.ClaimError) as store_refusal:
        store.fetch_state(worktree=clone, remote="origin")

    refused = run_cli(["bootstrap"], capsys)

    assert refused.expect_refusal() == f"ERROR: {store_refusal.value}\n"
    assert refused.stdout == ""
