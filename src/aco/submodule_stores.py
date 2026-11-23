"""The submodule repositories a landed lane's worktree holds, and the proof that deleting them loses
nothing: the proof that lets `git worktree remove --force` run on a worktree git itself refuses
to remove."""

import os
import shlex
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from . import checkout, protocol

_REMOTE_TRACKING_PREFIX = "refs/remotes/"
_STASH_REF = "refs/stash"
_REF_FIELD_SEPARATOR = "\t"
# `%(*...)` is the peeled object of an annotated tag, empty for any other ref.
_REF_FORMAT = _REF_FIELD_SEPARATOR.join(
    ("%(refname)", "%(objecttype)", "%(objectname)", "%(*objecttype)", "%(*objectname)")
)
_COMMIT_TYPE = "commit"


class RemovalProof(NamedTuple):
    """What a worktree's submodule repositories allow: `forced` when it holds some and each is
    proven to hold nothing unique, so the removal needs git's `--force`; `kept_reason` when one
    holds more, so the worktree and branch stay."""

    forced: bool
    kept_reason: str | None


class _Ref(NamedTuple):
    name: str
    tip_type: str
    tip: str


def removal_proof(worktree: Path, *, branch: str) -> RemovalProof:
    """The proof for removing `worktree`, the lane on `branch`: every repository
    `git worktree remove --force` would delete with it holds nothing outside its remote-tracking
    refs, and no populated submodule's working directory is dirty. A git failure reading one
    raises `ClaimError`; nothing here fetches."""
    stores = _stores(worktree)
    if stores and _submodules_are_dirty(worktree):
        return RemovalProof(False, checkout.WORKTREE_KEPT_DIRTY_REASON)
    for store in stores:
        holding = _holding(store)
        if holding is not None:
            return RemovalProof(False, _kept_reason(store, holding, worktree, branch))
    return RemovalProof(bool(stores), None)


def _submodules_are_dirty(worktree: Path) -> bool:
    """Whether any populated submodule, at any depth, has changed or untracked files. Each one is
    asked with the status the worktree itself is asked, whose flags override the configuration of
    its own repository, which the status of the repository above does not reach. The no-fetch
    option reaches every child git process: a missing object is a read failure."""
    status = shlex.join(["git", *checkout.DIRTY_STATUS])
    return bool(
        checkout.git_output(
            ["--no-lazy-fetch", "submodule", "--quiet", "foreach", "--recursive", status],
            directory=worktree,
        )
    )


def _kept_reason(store: Path, holding: str, worktree: Path, branch: str) -> str:
    removal = f"git worktree remove --force {shlex.quote(str(worktree))}"
    deletion = f"git branch -D {shlex.quote(branch)}"
    return (
        f"submodule repository {store} {holding}; after checking it, run: {removal} && {deletion}"
    )


def _stores(worktree: Path) -> tuple[Path, ...]:
    """Every git directory the force deletes: those under the worktree's own git directory's
    `modules` and those physically inside the worktree."""
    git_directory = Path(
        checkout.git_output(["rev-parse", "--absolute-git-dir"], directory=worktree)
    )
    return tuple(
        sorted({*_git_directories(git_directory / "modules"), *_git_directories(worktree)})
    )


def _git_directories(root: Path) -> Iterator[Path]:
    if not root.is_dir():
        return
    for directory, _subdirectories, _files in os.walk(root, onerror=_refuse_unreadable):
        path = Path(directory)
        if checkout.has_plain_git_directory_layout(path):
            yield path


def _refuse_unreadable(error: OSError) -> None:
    raise protocol.ClaimError(f"cannot read {error.filename}: {error.strerror}")


def _holding(store: Path) -> str | None:
    """What `store` holds that its remote-tracking refs do not, as a phrase, or none."""
    if _has_linked_worktree(store):
        return "has a linked worktree of its own"
    refs = _refs(store)
    if not any(ref.name.startswith(_REMOTE_TRACKING_PREFIX) for ref in refs):
        return "has no remote-tracking ref"
    local = [ref for ref in refs if not ref.name.startswith(_REMOTE_TRACKING_PREFIX)]
    if any(ref.name == _STASH_REF for ref in local):
        return "holds a stash entry"
    unique = _commits_outside_remote_tracking_refs(store)
    holding = sorted(ref.name for ref in local if ref.tip_type != _COMMIT_TYPE or ref.tip in unique)
    if not holding and unique:
        holding = ["HEAD"]
    if holding:
        return f"holds {', '.join(holding)} outside its remote-tracking refs"
    return None


def _has_linked_worktree(store: Path) -> bool:
    return any((store / "worktrees").glob("*"))


def _refs(store: Path) -> list[_Ref]:
    listing = checkout.git_output(
        [*_read_only(store), "for-each-ref", f"--format={_REF_FORMAT}"], lossy=True
    )
    rows = (line.split(_REF_FIELD_SEPARATOR) for line in listing.splitlines())
    return [
        _Ref(name, peeled_type or tip_type, peeled_tip or tip)
        for name, tip_type, tip, peeled_type, peeled_tip in rows
    ]


def _commits_outside_remote_tracking_refs(store: Path) -> frozenset[str]:
    """The commits `HEAD` and every ref outside `refs/remotes/` reach that no remote-tracking ref
    does."""
    listing = checkout.git_output(
        [
            *_read_only(store),
            "rev-list",
            f"--exclude={_REMOTE_TRACKING_PREFIX}*",
            "--all",
            "--not",
            "--remotes",
        ]
    )
    return frozenset(listing.split())


def _read_only(store: Path) -> list[str]:
    """The global options of every read: the store itself, with its own directory as the working
    tree because git changes into the directory `core.worktree` names, which a deinitialised
    parent's nested store names though it is gone, and no lazy fetch of an object a partial
    clone lacks."""
    return ["--no-lazy-fetch", f"--git-dir={store}", f"--work-tree={store}"]
