"""Which submodule repositories a worktree holds and whether deleting them loses a commit."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from cli_fixtures import real_git, set_git_identity
from release_cleanup_world import one_commit_repository

from aco import protocol, submodule_stores

BRANCH = "codex/issue-1-widget"


@pytest.fixture(autouse=True)
def _commit_identity(monkeypatch: pytest.MonkeyPatch, isolated_global_git_config: Path) -> None:
    set_git_identity(monkeypatch)


@pytest.fixture
def lane(worktree: Path, tmp_path: Path) -> Path:
    """A linked worktree, which has a git directory of its own beside its working directory."""
    linked = tmp_path / "lane"
    real_git(worktree, "worktree", "add", "-q", str(linked), "-b", BRANCH)
    return linked


@pytest.fixture
def upstream(tmp_path: Path) -> Path:
    return one_commit_repository(tmp_path / "upstream")


def lane_git_directory(lane: Path) -> Path:
    return Path(real_git(lane, "rev-parse", "--absolute-git-dir").stdout.strip())


def clone_store(upstream: Path, store: Path, working_directory: Path) -> Path:
    """`upstream` cloned with its git directory at `store`, as a populated submodule is."""
    store.parent.mkdir(parents=True, exist_ok=True)
    real_git(
        upstream,
        "clone",
        "-q",
        f"--separate-git-dir={store}",
        str(upstream),
        str(working_directory),
    )
    return store


def hold_unique_commit(store: Path) -> None:
    tree = real_git(store, "--git-dir=.", "rev-parse", "HEAD^{tree}").stdout.strip()
    commit = real_git(
        store, "--git-dir=.", "commit-tree", tree, "-p", "HEAD", "-m", "only here"
    ).stdout.strip()
    real_git(store, "--git-dir=.", "update-ref", "refs/heads/work", commit)


def proof_of(lane: Path) -> submodule_stores.RemovalProof:
    return submodule_stores.removal_proof(lane, branch=BRANCH)


def test_a_worktree_without_submodule_repositories_needs_no_force(lane: Path) -> None:
    """Spec: REL-70 -- the removal runs as before."""
    assert proof_of(lane) == (False, None)


def test_a_repository_inside_the_worktree_is_proven_like_any_other(
    lane: Path, upstream: Path
) -> None:
    """Spec: REL-70, REL-71 -- a git directory physically inside the worktree is deleted too."""
    clone_store(upstream, lane / "vendor" / ".git-store", lane / "vendor")
    store = lane / "vendor" / ".git-store"

    assert proof_of(lane) == (True, None)

    hold_unique_commit(store)
    kept_reason = proof_of(lane).kept_reason
    assert kept_reason is not None
    assert f"submodule repository {store} holds refs/heads/work" in kept_reason


def test_a_git_directory_the_worktree_only_points_to_needs_no_proof(
    lane: Path, upstream: Path, tmp_path: Path
) -> None:
    """Spec: REL-70 -- a gitfile pointing outside the worktree is not deleted with it."""
    outside = clone_store(upstream, tmp_path / "outside.git", lane / "vendor")
    hold_unique_commit(outside)

    assert proof_of(lane) == (False, None)


def test_a_nested_repository_is_found_and_named(lane: Path, upstream: Path) -> None:
    """Spec: REL-70, REL-72 -- every depth under `modules` counts."""
    modules = lane_git_directory(lane) / "modules"
    outer = clone_store(upstream, modules / "outer", lane / "outer")
    inner = clone_store(upstream, outer / "modules" / "inner", lane / "inner")
    hold_unique_commit(inner)

    kept_reason = proof_of(lane).kept_reason

    assert kept_reason is not None
    assert kept_reason.startswith(f"submodule repository {inner} holds")


def test_a_repository_below_a_repositorys_object_store_is_proven_too(
    lane: Path, upstream: Path
) -> None:
    """Spec: REL-70 -- every depth counts, an object store's directories included."""
    outer = clone_store(upstream, lane_git_directory(lane) / "modules" / "sub", lane / "sub")
    backup = clone_store(upstream, outer / "objects" / "backup.git", lane / "backup")
    hold_unique_commit(backup)

    kept_reason = proof_of(lane).kept_reason

    assert kept_reason is not None
    assert kept_reason.startswith(f"submodule repository {backup} holds")


def test_a_tag_that_names_no_commit_is_held(lane: Path, upstream: Path) -> None:
    """Spec: REL-71 -- a ref whose commit cannot be reached is never proven."""
    store = clone_store(upstream, lane_git_directory(lane) / "modules" / "sub", lane / "sub")
    blob = real_git(lane / "sub", "hash-object", "-w", "submodule.txt").stdout.strip()
    real_git(lane / "sub", "tag", "blob-tag", blob)

    kept_reason = proof_of(lane).kept_reason

    assert kept_reason is not None
    assert f"submodule repository {store} holds refs/tags/blob-tag" in kept_reason


def test_a_missing_object_is_a_read_failure_never_a_fetch(lane: Path, upstream: Path) -> None:
    """Spec: REL-74 -- a partial clone's missing object is not fetched from its promisor."""
    store = clone_store(upstream, lane_git_directory(lane) / "modules" / "sub", lane / "sub")
    real_git(store, "--git-dir=.", "config", "core.repositoryformatversion", "1")
    real_git(store, "--git-dir=.", "config", "extensions.partialClone", "origin")
    real_git(store, "--git-dir=.", "config", "remote.origin.promisor", "true")
    (upstream / "later.txt").write_text("later\n")
    real_git(upstream, "add", "later.txt")
    real_git(upstream, "commit", "-q", "-m", "later")
    later = real_git(upstream, "rev-parse", "HEAD").stdout.strip()
    (store / "refs" / "heads" / "later").write_text(later + "\n")

    with pytest.raises(protocol.ClaimError, match=later):
        proof_of(lane)

    absent = real_git(store, "--no-lazy-fetch", "--git-dir=.", "cat-file", "-e", later, check=False)
    assert absent.returncode != 0


@pytest.fixture
def unreadable(lane: Path) -> Iterator[Path]:
    directory = lane_git_directory(lane) / "modules" / "locked"
    directory.mkdir(parents=True)
    directory.chmod(0)
    yield directory
    directory.chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any directory")
def test_a_directory_that_cannot_be_read_is_a_read_failure(lane: Path, unreadable: Path) -> None:
    """Spec: REL-74 -- a repository that may sit in it is never skipped."""
    with pytest.raises(protocol.ClaimError, match=str(unreadable)):
        proof_of(lane)
