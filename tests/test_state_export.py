"""`state_export` behaviour: the bundle export `aco reset` saves the state ref with.

Every test here drives real git subprocesses against a local bare repository,
the thin git-transport integration layer.
"""

import errno
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import NamedTuple

import pytest
from cli_fixtures import real_git, set_git_identity
from store_fixtures import fail_git_subprocesses_carrying, push_custom_tree

from aco import process, protocol, state_export, store

_PLACEHOLDER_TIP = protocol.ObjectId("1" * 40)


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """A commit identity for every git subprocess this test file spawns -- this
    machine may carry no git `user.name`/`user.email` at all."""
    set_git_identity(monkeypatch)


@pytest.mark.parametrize(
    "shared_state_ref_before_export",
    ["absent", "pointed-at-a-different-tip"],
)
def test_export_state_bundle_writes_a_verifiable_bundle_and_never_touches_the_shared_ref(
    bare_remote: Path, worktree: Path, tmp_path: Path, shared_state_ref_before_export: str
) -> None:
    """Bundles the private `EXPORT_BUNDLE_REF`, never the shared
    `STATE_REF`. The previous
    implementation pointed `STATE_REF` at `tip` to give the bundle a name --
    `refs/aco/state` is visible from every linked worktree of a repository,
    so a concurrent reset elsewhere could repoint or delete it between that
    write and the lease-guarded remote delete that follows, racing the
    bundle onto whatever tip it found rather than the one the caller
    leased, and a failed export left it mutated with no restore of its
    previous value. Whatever `STATE_REF` holds locally beforehand --
    nothing, or a foreign tip set by something else entirely -- must
    survive byte-for-byte, and the bundle must still carry exactly the
    leased `tip` regardless."""
    tip = store.bootstrap(worktree=worktree, remote=str(bare_remote))
    store.fetch_state(worktree=worktree, remote=str(bare_remote))
    foreign_tip = None
    if shared_state_ref_before_export == "pointed-at-a-different-tip":
        foreign_tip = push_custom_tree(
            bare_remote,
            worktree,
            parent=tip,
            files={store.SCHEMA_TOML_FILENAME: protocol.serialize_empty_schema_toml().encode()},
        )
        real_git(worktree, "update-ref", store.STATE_REF, foreign_tip)
    destination = tmp_path / "export" / "state.bundle"
    destination.parent.mkdir()

    returned = state_export.export_state_bundle(worktree=worktree, tip=tip, destination=destination)

    assert returned == destination
    real_git(worktree, "bundle", "verify", str(destination))
    heads = real_git(worktree, "bundle", "list-heads", str(destination)).stdout
    assert heads.strip() == f"{tip} {state_export.EXPORT_BUNDLE_REF}"
    if foreign_tip is None:
        assert not store.local_state_ref_exists(worktree)
    else:
        assert real_git(worktree, "rev-parse", store.STATE_REF).stdout.strip() == foreign_tip
    assert (
        store._run_git(
            worktree, ["show-ref", "--verify", "--quiet", state_export.EXPORT_BUNDLE_REF]
        ).exit_status
        != 0
    )
    assert not list(destination.parent.glob(f".{destination.name}.*"))


def test_export_state_bundle_refuses_to_overwrite_an_existing_destination(
    bare_remote: Path, worktree: Path, tmp_path: Path
) -> None:
    tip = store.bootstrap(worktree=worktree, remote=str(bare_remote))
    destination = tmp_path / "state.bundle"
    destination.write_bytes(b"an earlier export")

    with pytest.raises(protocol.ClaimError, match="already exists"):
        state_export.export_state_bundle(worktree=worktree, tip=tip, destination=destination)

    assert destination.read_bytes() == b"an earlier export"
    # The temporary file the bundle was written to must not survive a refused publish either.
    assert not list(destination.parent.glob(f".{destination.name}.*"))


def _break_export_via_an_unwritable_destination_directory(
    monkeypatch: pytest.MonkeyPatch, bare_remote: Path, worktree: Path, tmp_path: Path
) -> tuple[protocol.ObjectId, Path, Callable[[], None]]:
    tip = store.fetch_state(worktree=worktree, remote=str(bare_remote)).tip
    assert tip is not None
    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o500)
    return tip, readonly_dir / "state.bundle", lambda: readonly_dir.chmod(0o700)


def _break_export_via_a_failed_bundle_create(
    monkeypatch: pytest.MonkeyPatch, bare_remote: Path, worktree: Path, tmp_path: Path
) -> tuple[protocol.ObjectId, Path, Callable[[], None]]:
    """The subprocess step between the claimed temporary file and its
    publish -- `git bundle create - EXPORT_BUNDLE_REF` -- can fail on its
    own even though the preceding `update-ref` already proved `tip`
    reachable; the claimed temporary file must be removed rather than left
    behind empty, and `destination` itself must never come to exist at all."""
    tip = store.fetch_state(worktree=worktree, remote=str(bare_remote)).tip
    assert tip is not None
    fail_git_subprocesses_carrying(
        monkeypatch, "bundle", "create", stderr=b"simulated bundle create failure"
    )
    return tip, tmp_path / "state.bundle", lambda: None


def _break_export_via_a_tip_this_worktree_never_received(
    monkeypatch: pytest.MonkeyPatch, bare_remote: Path, worktree: Path, tmp_path: Path
) -> tuple[protocol.ObjectId, Path, Callable[[], None]]:
    """Pointing `EXPORT_BUNDLE_REF` at `tip` is `export_state_bundle`'s own
    validation that `tip`'s objects actually reached this worktree --
    `update-ref` itself refuses a tip git has never seen, so a caller
    cannot silently bundle the wrong state."""
    return _PLACEHOLDER_TIP, tmp_path / "state.bundle", lambda: None


def _break_export_via_a_cross_device_link_failure(
    monkeypatch: pytest.MonkeyPatch, bare_remote: Path, worktree: Path, tmp_path: Path
) -> tuple[protocol.ObjectId, Path, Callable[[], None]]:
    """`os.link`'s no-clobber semantics (`FileExistsError`) are not its only
    failure mode: publishing across a filesystem boundary raises
    `OSError(errno.EXDEV, ...)` instead, a path CI's 100 % line-coverage
    gate found unexercised.
    Patched at `state_export.os.link`, the module boundary `_write_and_publish_bundle`
    calls through, rather than reimplementing a real cross-device mount."""
    tip = store.fetch_state(worktree=worktree, remote=str(bare_remote)).tip
    assert tip is not None

    def fake_link(source: Path, link_name: Path) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(state_export.os, "link", fake_link)
    return tip, tmp_path / "state.bundle", lambda: None


class _ExportFailureCase(NamedTuple):
    """One row of `test_export_state_bundle_fails_loud_and_leaves_no_trace`.

    `cause_fragment` is `None` for a row whose break point raises loud
    without a `from` chain of its own (the write/publish path never chains,
    only `export_state_bundle`'s own pre-write steps do) -- `None` skips
    the `__cause__` assertion rather than asserting it is unset, since this
    family does not otherwise pin that fact for rows it was not asked to."""

    id: str
    arrange: Callable[
        [pytest.MonkeyPatch, Path, Path, Path], tuple[protocol.ObjectId, Path, Callable[[], None]]
    ]
    cause_fragment: str | None


@pytest.mark.parametrize(
    "case",
    [
        _ExportFailureCase(
            "unwritable-directory", _break_export_via_an_unwritable_destination_directory, None
        ),
        _ExportFailureCase("bundle-create-fails", _break_export_via_a_failed_bundle_create, None),
        _ExportFailureCase(
            "unreachable-tip", _break_export_via_a_tip_this_worktree_never_received, None
        ),
        _ExportFailureCase(
            "cross-device-link",
            _break_export_via_a_cross_device_link_failure,
            "Invalid cross-device link",
        ),
    ],
    ids=lambda case: case.id,
)
def test_export_state_bundle_fails_loud_and_leaves_no_trace(
    monkeypatch: pytest.MonkeyPatch,
    bare_remote: Path,
    worktree: Path,
    tmp_path: Path,
    case: _ExportFailureCase,
) -> None:
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    tip, destination, restore = case.arrange(monkeypatch, bare_remote, worktree, tmp_path)

    try:
        with pytest.raises(protocol.ClaimError, match="cannot export") as excinfo:
            state_export.export_state_bundle(worktree=worktree, tip=tip, destination=destination)
    finally:
        restore()

    message = str(excinfo.value)
    assert str(tip) in message
    assert str(destination) in message
    if case.cause_fragment is not None:
        assert excinfo.value.__cause__ is not None
        assert case.cause_fragment in str(excinfo.value.__cause__)

    assert not destination.exists()
    assert not list(destination.parent.glob(f".{destination.name}.*"))


def _fail_temporary_unlink(
    monkeypatch: pytest.MonkeyPatch, destination: Path, attempted: list[Path]
) -> None:
    """Fail `Path.unlink` for exactly the temporary file
    `_write_and_publish_bundle` claims for `destination` (the
    `tempfile.mkstemp` prefix its own docstring names), leaving every other
    `unlink` call -- including this test's own leftover cleanup once it has
    restored the real function -- untouched. Records the intercepted path in
    `attempted`: an observable stand-in for "the unlink was attempted" that
    counting fake calls would not be."""
    real_unlink = Path.unlink

    def fake_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name.startswith(f".{destination.name}."):
            attempted.append(self)
            raise OSError("simulated temporary-file cleanup failure")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fake_unlink)


class _RefDeletionFailure(Enum):
    """The three independent ways `_delete_export_ref`'s guard must survive an injected
    `update-ref -d EXPORT_BUNDLE_REF` failure: a nonzero exit matching a
    real `git update-ref` refusal, a raised `OSError` matching an
    invocation that never reached git at all, and a nonzero exit whose
    stderr is not valid UTF-8, matching a `.decode()` failure."""

    EXITS_NONZERO = "exits-nonzero"
    RAISES = "raises"
    RETURNS_INVALID_UTF8_STDERR = "returns-invalid-utf8-stderr"


def _fail_export_ref_deletion(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_bundle_create: bool,
    ref_deletion_failure: _RefDeletionFailure,
) -> None:
    """Patch `process.run_captured` so the bundle-create subprocess and the
    `EXPORT_BUNDLE_REF` cleanup fail the way each row of the parametrized
    cleanup-independence family below needs. Every other invocation,
    including the real `update-ref` that points `EXPORT_BUNDLE_REF` at
    `tip`, runs for real."""
    real_run_captured = process.run_captured

    def fake_run_captured(arguments: list[str]) -> process.CapturedResult:
        if fail_bundle_create and "bundle" in arguments and "create" in arguments:
            return process.CapturedResult(
                exit_status=1, stdout=b"", stderr=b"simulated bundle create failure"
            )
        if arguments[-3:] == ["update-ref", "-d", state_export.EXPORT_BUNDLE_REF]:
            if ref_deletion_failure is _RefDeletionFailure.RAISES:
                raise OSError("simulated ref-deletion invocation failure")
            if ref_deletion_failure is _RefDeletionFailure.RETURNS_INVALID_UTF8_STDERR:
                return process.CapturedResult(
                    exit_status=1, stdout=b"", stderr=b"\xff\xfe not valid utf-8"
                )
            return process.CapturedResult(
                exit_status=1, stdout=b"", stderr=b"simulated ref cleanup failure"
            )
        return real_run_captured(arguments)

    monkeypatch.setattr(store.process, "run_captured", fake_run_captured)


def _verify_and_remove_the_leftover_export_ref(worktree: Path) -> None:
    """`EXPORT_BUNDLE_REF` genuinely exists after a cleanup row whose ref
    deletion was made to fail: confirm that before removing it for real, so
    a future regression that quietly drops the real `update-ref` call
    cannot pass this test by accident."""
    assert (
        store._run_git(
            worktree, ["show-ref", "--verify", "--quiet", state_export.EXPORT_BUNDLE_REF]
        ).exit_status
        == 0
    )
    store._run_git(worktree, ["update-ref", "-d", state_export.EXPORT_BUNDLE_REF])


class _CleanupFailureCase(NamedTuple):
    """One row of the export-cleanup-independence test family below.

    `arrange` sets up `tip`/`destination` and whichever of the two cleanup
    steps (or the primary write/publish) this row breaks, returning the
    call's `tip` and `destination`. `error_match` filters the outer
    `pytest.raises`; `None` skips the filter for a row whose distinguishing
    text lives only in the body. `cause_fragment` is `None` for a row with
    no primary error (a successful publish whose cleanup still fails).
    `destination_exists_after` and `destination_bytes_after` say what should
    remain at `destination` -- `verify_bundle` additionally asks for a real
    `git bundle verify` where `destination` is a genuine publish rather than
    an untouched pre-existing file. `temp_leftover_expected` says whether the
    temporary file should remain; `postcheck` runs after the real
    `process.run_captured`/`Path.unlink` are restored, for a row that leaves
    a real git-level leftover of its own (a ref cleanup failure) rather than
    only a filesystem one.
    """

    id: str
    arrange: Callable[
        [pytest.MonkeyPatch, Path, Path, Path, list[Path]], tuple[protocol.ObjectId, Path]
    ]
    error_match: str | None
    message_fragments: tuple[str, ...]
    cause_fragment: str | None
    destination_exists_after: bool
    destination_bytes_after: bytes | None
    verify_bundle: bool
    temp_leftover_expected: bool
    postcheck: Callable[[Path], None]


def _arrange_successful_publish_with_a_failed_temp_unlink(
    monkeypatch: pytest.MonkeyPatch,
    bare_remote: Path,
    worktree: Path,
    tmp_path: Path,
    attempted_unlinks: list[Path],
) -> tuple[protocol.ObjectId, Path]:
    tip = store.bootstrap(worktree=worktree, remote=str(bare_remote))
    store.fetch_state(worktree=worktree, remote=str(bare_remote))
    destination = tmp_path / "export" / "state.bundle"
    destination.parent.mkdir()
    _fail_temporary_unlink(monkeypatch, destination, attempted_unlinks)
    return tip, destination


def _arrange_a_failed_bundle_create_with_a_failed_ref_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    bare_remote: Path,
    worktree: Path,
    tmp_path: Path,
    attempted_unlinks: list[Path],
) -> tuple[protocol.ObjectId, Path]:
    tip = store.bootstrap(worktree=worktree, remote=str(bare_remote))
    store.fetch_state(worktree=worktree, remote=str(bare_remote))
    destination = tmp_path / "export" / "state.bundle"
    destination.parent.mkdir()
    _fail_export_ref_deletion(
        monkeypatch,
        fail_bundle_create=True,
        ref_deletion_failure=_RefDeletionFailure.EXITS_NONZERO,
    )
    return tip, destination


def _arrange_a_successful_publish_with_invalid_utf8_ref_cleanup_stderr(
    monkeypatch: pytest.MonkeyPatch,
    bare_remote: Path,
    worktree: Path,
    tmp_path: Path,
    attempted_unlinks: list[Path],
) -> tuple[protocol.ObjectId, Path]:
    tip = store.bootstrap(worktree=worktree, remote=str(bare_remote))
    store.fetch_state(worktree=worktree, remote=str(bare_remote))
    destination = tmp_path / "export" / "state.bundle"
    destination.parent.mkdir()
    _fail_export_ref_deletion(
        monkeypatch,
        fail_bundle_create=False,
        ref_deletion_failure=_RefDeletionFailure.RETURNS_INVALID_UTF8_STDERR,
    )
    return tip, destination


def _arrange_a_refused_publish_with_a_failed_temp_unlink(
    monkeypatch: pytest.MonkeyPatch,
    bare_remote: Path,
    worktree: Path,
    tmp_path: Path,
    attempted_unlinks: list[Path],
) -> tuple[protocol.ObjectId, Path]:
    tip = store.bootstrap(worktree=worktree, remote=str(bare_remote))
    destination = tmp_path / "state.bundle"
    destination.write_bytes(b"an earlier export")
    _fail_temporary_unlink(monkeypatch, destination, attempted_unlinks)
    return tip, destination


def _arrange_a_failed_bundle_create_with_both_cleanup_steps_failing(
    monkeypatch: pytest.MonkeyPatch,
    bare_remote: Path,
    worktree: Path,
    tmp_path: Path,
    attempted_unlinks: list[Path],
) -> tuple[protocol.ObjectId, Path]:
    tip = store.bootstrap(worktree=worktree, remote=str(bare_remote))
    store.fetch_state(worktree=worktree, remote=str(bare_remote))
    destination = tmp_path / "export" / "state.bundle"
    destination.parent.mkdir()
    _fail_export_ref_deletion(
        monkeypatch, fail_bundle_create=True, ref_deletion_failure=_RefDeletionFailure.RAISES
    )
    _fail_temporary_unlink(monkeypatch, destination, attempted_unlinks)
    return tip, destination


@pytest.mark.parametrize(
    "case",
    [
        _CleanupFailureCase(
            id="successful-publish-temp-unlink-fails",
            arrange=_arrange_successful_publish_with_a_failed_temp_unlink,
            error_match="could not remove the now-redundant temporary",
            message_fragments=(),
            cause_fragment=None,
            destination_exists_after=True,
            destination_bytes_after=None,
            verify_bundle=True,
            temp_leftover_expected=True,
            postcheck=lambda worktree: None,
        ),
        _CleanupFailureCase(
            id="bundle-create-fails-and-ref-cleanup-exits-nonzero",
            arrange=_arrange_a_failed_bundle_create_with_a_failed_ref_cleanup,
            error_match=None,
            message_fragments=(
                "simulated bundle create failure",
                state_export.EXPORT_BUNDLE_REF,
                "simulated ref cleanup failure",
            ),
            cause_fragment="simulated bundle create failure",
            destination_exists_after=False,
            destination_bytes_after=None,
            verify_bundle=False,
            temp_leftover_expected=False,
            postcheck=_verify_and_remove_the_leftover_export_ref,
        ),
        _CleanupFailureCase(
            id="successful-publish-ref-cleanup-stderr-is-invalid-utf8",
            arrange=_arrange_a_successful_publish_with_invalid_utf8_ref_cleanup_stderr,
            error_match="could not remove the temporary export ref",
            message_fragments=(state_export.EXPORT_BUNDLE_REF, "can't decode"),
            cause_fragment=None,
            destination_exists_after=True,
            destination_bytes_after=None,
            verify_bundle=True,
            temp_leftover_expected=False,
            postcheck=_verify_and_remove_the_leftover_export_ref,
        ),
        _CleanupFailureCase(
            id="refused-publish-temp-unlink-fails",
            arrange=_arrange_a_refused_publish_with_a_failed_temp_unlink,
            error_match="already exists",
            message_fragments=("simulated temporary-file cleanup failure",),
            cause_fragment="already exists",
            destination_exists_after=True,
            destination_bytes_after=b"an earlier export",
            verify_bundle=False,
            temp_leftover_expected=True,
            postcheck=lambda worktree: None,
        ),
        _CleanupFailureCase(
            id="bundle-create-fails-and-both-cleanup-steps-fail",
            arrange=_arrange_a_failed_bundle_create_with_both_cleanup_steps_failing,
            error_match=None,
            message_fragments=(
                "simulated bundle create failure",
                state_export.EXPORT_BUNDLE_REF,
                "simulated ref-deletion invocation failure",
                "simulated temporary-file cleanup failure",
            ),
            cause_fragment="simulated bundle create failure",
            destination_exists_after=False,
            destination_bytes_after=None,
            verify_bundle=False,
            temp_leftover_expected=True,
            postcheck=_verify_and_remove_the_leftover_export_ref,
        ),
    ],
    ids=lambda case: case.id,
)
def test_export_state_bundle_names_every_uncleaned_leftover_and_preserves_the_original_cause(
    monkeypatch: pytest.MonkeyPatch,
    bare_remote: Path,
    worktree: Path,
    tmp_path: Path,
    case: _CleanupFailureCase,
) -> None:
    """The two cleanup steps `_clear_export_artifacts` runs -- clearing
    `EXPORT_BUNDLE_REF` and removing the temporary file -- are independent
    of each other and of whatever exception type each raises: whichever one fails,
    the other is still attempted, the raised error names every artifact
    that is actually left behind together with its own failure, and it is
    chained to the write/publish failure that preceded it when there was
    one -- never silently dropped in favour of a cleanup failure, and never
    silently dropping a cleanup failure in favour of it."""
    attempted_unlinks: list[Path] = []
    tip, destination = case.arrange(monkeypatch, bare_remote, worktree, tmp_path, attempted_unlinks)

    with pytest.raises(protocol.ClaimError, match=case.error_match) as excinfo:
        state_export.export_state_bundle(worktree=worktree, tip=tip, destination=destination)

    message = str(excinfo.value)
    for fragment in case.message_fragments:
        assert fragment in message
    if case.cause_fragment is None:
        assert excinfo.value.__cause__ is None
    else:
        assert excinfo.value.__cause__ is not None
        assert case.cause_fragment in str(excinfo.value.__cause__)
    assert destination.exists() == case.destination_exists_after
    if case.destination_bytes_after is not None:
        assert destination.read_bytes() == case.destination_bytes_after

    monkeypatch.undo()  # restore the real process.run_captured/Path.unlink before cleanup below

    if case.temp_leftover_expected:
        assert attempted_unlinks, "the temporary file's own unlink must still be attempted"
        assert str(attempted_unlinks[0]) in message
        leftover = list(destination.parent.glob(f".{destination.name}.*"))
        assert leftover
        for stray in leftover:
            stray.unlink()
    else:
        assert not list(destination.parent.glob(f".{destination.name}.*"))
    if case.verify_bundle:
        real_git(worktree, "bundle", "verify", str(destination))

    case.postcheck(worktree)
