"""The reset step's bundle export of the state ref: one private ref, one
temporary file, one published bundle, and the cleanup of both.

Sibling of `store`, which owns the state ref's transport; `cmd_reset` is this
module's only production caller.
"""

import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

from .protocol import ClaimError, ObjectId
from .store import STATE_REF, git_failure_detail, git_failure_detail_from_stderr, run_git

# `export_state_bundle` points this at the leased tip and bundles it:
# Using the shared `STATE_REF` would let a concurrent reset in another
# linked worktree repoint or delete it between the bundle write and the
# lease-guarded remote delete that follows, and a failed
# export could leave it mutated with no restore of its previous value. This name
# lives in the same worktree-private `refs/worktree/*` namespace
# `_FETCH_ANCHOR_REF` already relies on, so no linked worktree ever
# observes, races, or clobbers it, and nothing shared is written by an
# export at all. `export_state_bundle` deletes it again before returning or
# raising, in every case, so restoring a bundle reads this name back on the
# bundle side of the fetch, not `STATE_REF`'s
# (`cmd_reset._reset_restore_command` builds the exact command).
EXPORT_BUNDLE_REF = "refs/worktree/aco/reset-export"


def _export_failure(tip: ObjectId, destination: Path, detail: str) -> ClaimError:
    return ClaimError(f"cannot export {STATE_REF} at {tip} to {destination}: {detail}")


def _write_bundle_to_descriptor(
    *, worktree: Path, tip: ObjectId, destination: Path, descriptor: int
) -> None:
    """Point `EXPORT_BUNDLE_REF` at `tip` and stream `git bundle create` for
    it into the already-claimed file descriptor `descriptor`: the git
    plumbing half of `export_state_bundle`'s write, kept separate so that
    function's own body stays about claiming and publishing a file, not
    about running git. Pointing `EXPORT_BUNDLE_REF` at `tip` is also this
    step's own validation that `tip`'s objects actually reached this
    worktree: `update-ref` itself refuses a `tip` git has never seen.

    `descriptor` is always closed by the time this returns or raises --
    successfully, via the `with os.fdopen(...)` below, or, on any earlier
    failure, by the `except` clause here.
    """
    try:
        update = run_git(worktree, ["update-ref", EXPORT_BUNDLE_REF, str(tip)])
        if update.exit_status != 0:
            detail = git_failure_detail_from_stderr(update)
            raise _export_failure(tip, destination, detail)
        result = run_git(worktree, ["bundle", "create", "-", EXPORT_BUNDLE_REF])
        if result.exit_status != 0:
            raise _export_failure(tip, destination, git_failure_detail(result))
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(result.stdout)
    except BaseException:
        with suppress(OSError):
            os.close(descriptor)
        raise


def _write_and_publish_bundle(
    *, worktree: Path, tip: ObjectId, destination: Path, descriptor: int, temporary: Path
) -> None:
    """Write `tip`'s bundle into the already-claimed temporary file, then
    publish it into `destination`, the write half of
    `export_state_bundle`'s step 1 of 5.

    Publishes atomically: the bundle is written in full to `temporary` first
    (`tempfile.mkstemp`, the same idiom `lineage_stamp` uses), then
    linked into place with `os.link`, whose no-clobber semantics are this
    function's `destination`-already-exists check -- a reader can never
    observe a half-written or empty `destination`, because nothing is ever
    written at that path directly. Removing `temporary` again, whether this
    succeeds or raises, is the caller's job (`export_state_bundle`'s
    unconditional cleanup), not this function's -- so every path out of here
    leaves `temporary` exactly where it found it.
    """
    _write_bundle_to_descriptor(
        worktree=worktree, tip=tip, destination=destination, descriptor=descriptor
    )
    try:
        os.link(temporary, destination)
    except FileExistsError:
        raise ClaimError(f"{destination} already exists; refusing to overwrite an export") from None
    except OSError as error:
        raise _export_failure(tip, destination, str(error)) from error


def _delete_export_ref(worktree: Path) -> str | None:
    """Delete the temporary `EXPORT_BUNDLE_REF`, reporting failure as a
    description rather than raising: `_clear_export_artifacts` below must
    still attempt the temporary file's own removal even when this fails, so
    neither cleanup step can skip the other. Deleting an already-absent ref
    is a documented no-op (`git-update-ref`(1)), so a `tip` that never
    reached `update-ref` in the first place costs nothing here.

    Catches `(ClaimError, OSError, ValueError)` rather than only
    `ClaimError`:
    `run_git` only wraps `ExecutableMissingError`/`ProcessTimedOutError`
    into `ClaimError`, so a raw `OSError` from the git subprocess call inside `run_git`, its own
    `subprocess.run` (a descriptor exhausted) would otherwise escape before
    the temporary file's own cleanup below ever runs, and
    `git_failure_detail_from_stderr`'s own `stderr.decode()` on the
    nonzero-exit branch can raise `UnicodeDecodeError` -- a `ValueError`
    subclass -- on invalid UTF-8 in git's own stderr. This is the concrete
    failure family that can actually reach this call, not a stand-in for
    "anything": nothing here is swallowed, the caught error is carried
    verbatim into the leftover description `_clear_export_artifacts` returns
    and, from there, into the raised `ClaimError` and its `__cause__`."""
    try:
        result = run_git(worktree, ["update-ref", "-d", EXPORT_BUNDLE_REF])
        if result.exit_status != 0:
            return git_failure_detail_from_stderr(result)
    except (ClaimError, OSError, ValueError) as error:
        return str(error)
    return None


def _clear_export_artifacts(*, worktree: Path, temporary: Path) -> tuple[str, ...]:
    """Remove the temporary export ref and the temporary file, each
    attempted independently of whether the other fails: a broken `git`
    invocation while clearing `EXPORT_BUNDLE_REF` -- the
    `(ClaimError, OSError, ValueError)` family `_delete_export_ref`
    documents -- must never skip the temporary file's removal, and an
    `OSError` removing the temporary file must never skip clearing the
    ref. Returns a description of every artifact that could not be
    removed, or an empty tuple once both are confirmed gone."""
    leftovers: list[str] = []
    ref_failure = _delete_export_ref(worktree)
    if ref_failure is not None:
        leftovers.append(f"the temporary export ref {EXPORT_BUNDLE_REF} ({ref_failure})")
    try:
        temporary.unlink()
    except OSError as error:
        leftovers.append(f"the now-redundant temporary file {temporary} ({error})")
    return tuple(leftovers)


def _export_cleanup_failure(
    tip: ObjectId,
    destination: Path,
    leftovers: tuple[str, ...],
    primary_error: BaseException | None,
) -> ClaimError:
    artifacts = " and ".join(leftovers)
    if primary_error is None:
        return ClaimError(
            f"exported {STATE_REF} at {tip} to {destination} but could not remove {artifacts}"
        )
    return ClaimError(
        f"cannot export {STATE_REF} at {tip} to {destination}: {primary_error}; also could "
        f"not remove {artifacts}"
    )


def export_state_bundle(*, worktree: Path, tip: ObjectId, destination: Path) -> Path:
    """Bundle `tip` into `destination` (reset, step 1 of 5): the sole
    mandatory-unless-`--no-export` write a reset performs before anything is deleted.

    Bundles the private `EXPORT_BUNDLE_REF` (`_write_bundle_to_descriptor`'s own docstring has the
    full rationale), never the shared `STATE_REF`: nothing this function does is ever visible to
    another linked worktree's concurrent reset, and the bundled tip is always exactly the `tip`
    the caller leased -- never whatever a shared ref happens to hold when the subprocess actually
    runs. Restoring the bundle therefore reads `EXPORT_BUNDLE_REF`'s name on the bundle side of
    the fetch, not `STATE_REF`'s (`git bundle list-heads` names it,
    `cmd_reset._reset_restore_command` builds the command).

    Cleanup of the temporary export ref and the temporary file is unconditional and the two are
    independent of each other: whatever happened while writing or publishing the bundle --
    success, or a failure raised at any point -- both cleanups are always attempted, via
    `_clear_export_artifacts`, and a failure in one never skips the other. The previous version
    ran the ref cleanup as a plain statement ahead of the temporary file's own cleanup, so an
    exception from that one git invocation (not just a nonzero exit) skipped the temporary file's
    removal entirely, and both cleanups suppressed their own `OSError`/nonzero-exit without
    naming what was left behind. When a cleanup failure happens, the artifact it could not remove
    is named in the raised error, together with the write/publish failure that preceded it when
    there was one, carried as that error's cause (`raise ... from`); when cleanup succeeds but
    the write or publish itself failed, that original error is re-raised unchanged.
    """
    try:
        descriptor, temp_name = tempfile.mkstemp(
            dir=str(destination.parent), prefix=f".{destination.name}."
        )
    except OSError as error:
        raise _export_failure(tip, destination, str(error)) from error
    temporary = Path(temp_name)

    try:
        _write_and_publish_bundle(
            worktree=worktree,
            tip=tip,
            destination=destination,
            descriptor=descriptor,
            temporary=temporary,
        )
    finally:
        leftovers = _clear_export_artifacts(worktree=worktree, temporary=temporary)
        if leftovers:
            primary = sys.exc_info()[1]
            raise _export_cleanup_failure(tip, destination, leftovers, primary) from primary
    return destination
