"""Reset against real state refs, bundles, leases, and worktree lineage."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

import pytest
from cli_fixtures import (
    FROZEN_CLI_NOW,
    arguments_bash_hands_aco,
    count_context_reads,
    freeze_cli_now,
    fresh_observation,
    init_bare_repository,
    push_repository_trunk,
    real_git,
    redirect_toplevel,
    run_cli,
    track_board_config,
)
from store_fixtures import (
    blob,
    claim_intent,
    lineage_observation,
    push_raw_state_tree,
    state_ref_tip,
)

from aco import checkout, process, protocol, session, store


def _bootstrap_output(stdout: str) -> tuple[tuple[str, ...], str | None]:
    lines = tuple(
        re.sub(r"(?<=bootstrapped a fresh empty state at )[0-9a-f]{40}$", "{fresh_tip}", line)
        for line in stdout.splitlines()
    )
    printed = re.search(
        r"^bootstrapped a fresh empty state at ([0-9a-f]{40})$", stdout, re.MULTILINE
    )
    return lines, printed.group(1) if printed is not None else None


def _expected_reset_bundle(export_dir: Path, clone: Path, tip: str) -> Path:
    return export_dir / (
        f"aco-state-{clone.name}-{FROZEN_CLI_NOW.date().isoformat()}-{tip[:12]}.bundle"
    )


def _readable_reset(clone: Path, bare_remote: Path) -> str:
    tip = store.bootstrap(worktree=clone, remote="origin")
    assert not store.local_state_ref_exists(clone)
    return tip


def _observed_reset(clone: Path, bare_remote: Path) -> str:
    tip = _readable_reset(clone, bare_remote)
    store.fetch_state(worktree=clone, remote="origin")
    assert all(lineage_observation(clone))
    return tip


def _schema1_reset(clone: Path, bare_remote: Path) -> str:
    tip = push_raw_state_tree(
        bare_remote, clone, [("100644", "blob", blob(clone, b"version = 1\n"), "schema.toml")]
    )
    assert lineage_observation(clone) == (None, None)
    assert not store.local_state_ref_exists(clone)
    return tip


def _never_reset(clone: Path, bare_remote: Path) -> None:
    assert state_ref_tip(bare_remote) is None
    assert not store.local_state_ref_exists(clone)
    assert lineage_observation(clone) == (None, None)


def _local_reset(clone: Path, bare_remote: Path) -> str:
    tip = _readable_reset(clone, bare_remote)
    real_git(clone, "update-ref", store.STATE_REF, tip)
    assert state_ref_tip(clone) == tip
    return tip


def _deleted_reset(clone: Path, bare_remote: Path) -> None:
    _observed_reset(clone, bare_remote)
    real_git(bare_remote, "update-ref", "-d", store.STATE_REF)
    with pytest.raises(protocol.StateLineageError):
        store.fetch_state(worktree=clone, remote="origin")
    assert state_ref_tip(bare_remote) is None
    assert not store.local_state_ref_exists(clone)


@dataclass(frozen=True)
class ResetPlan:
    arrange: Callable[[Path, Path], str | None]
    arguments: tuple[str, ...]
    executed: bool
    status: int
    lines: tuple[str, ...]
    error: str
    exports_bundle: bool
    explicit_directory: bool = True


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            ResetPlan(
                arrange=_observed_reset,
                arguments=(),
                executed=False,
                status=0,
                lines=(
                    "would: export {ref} at {tip} to {bundle} "
                    "(restore with: git fetch {bundle} {export_ref}:{ref})",
                    "would: delete {ref} on origin (lease {tip})",
                    "would: no local {ref} to delete",
                    "would: clear lineage stamps and fetch anchors in 1 worktree",
                    "would: bootstrap a fresh empty state",
                ),
                error="",
                exports_bundle=False,
                explicit_directory=True,
            ),
            id="claim-free-dry",
        ),
        pytest.param(
            ResetPlan(
                arrange=_readable_reset,
                arguments=("--confirm",),
                executed=True,
                status=0,
                lines=(
                    "exported {ref} at {tip} to {bundle} "
                    "(restore with: git fetch {bundle} {export_ref}:{ref})",
                    "deleted {ref} on origin (lease {tip})",
                    "no local {ref} to delete",
                    "cleared lineage stamps and fetch anchors in 1 worktree",
                    "bootstrapped a fresh empty state at {{fresh_tip}}",
                ),
                error="",
                exports_bundle=True,
                explicit_directory=True,
            ),
            id="plain",
        ),
        pytest.param(
            ResetPlan(
                arrange=_readable_reset,
                arguments=("--confirm", "--force-unreadable"),
                executed=True,
                status=0,
                lines=(
                    "exported {ref} at {tip} to {bundle} "
                    "(restore with: git fetch {bundle} {export_ref}:{ref})",
                    "deleted {ref} on origin (lease {tip})",
                    "no local {ref} to delete",
                    "cleared lineage stamps and fetch anchors in 1 worktree",
                    "bootstrapped a fresh empty state at {{fresh_tip}}",
                ),
                error="",
                exports_bundle=True,
                explicit_directory=True,
            ),
            id="forced",
        ),
        pytest.param(
            ResetPlan(
                arrange=_schema1_reset,
                arguments=(),
                executed=False,
                status=0,
                lines=(
                    "schema 1 not readable by this aco; live claims unknown "
                    "(--confirm needs --force-unreadable)",
                    "would: export {ref} at {tip} to {bundle} "
                    "(restore with: git fetch {bundle} {export_ref}:{ref})",
                    "would: delete {ref} on origin (lease {tip})",
                    "would: no local {ref} to delete",
                    "would: clear lineage stamps and fetch anchors in 1 worktree",
                    "would: bootstrap a fresh empty state",
                ),
                error="",
                exports_bundle=False,
                explicit_directory=True,
            ),
            id="schema1-dry",
        ),
        pytest.param(
            ResetPlan(
                arrange=_schema1_reset,
                arguments=("--confirm",),
                executed=False,
                status=2,
                lines=(),
                error=(
                    "ERROR: schema 1 not readable by this aco; live claims unknown "
                    "(--confirm needs --force-unreadable)\n"
                ),
                exports_bundle=False,
                explicit_directory=True,
            ),
            id="schema1-refused",
        ),
        pytest.param(
            ResetPlan(
                arrange=_schema1_reset,
                arguments=("--confirm", "--force-unreadable"),
                executed=True,
                status=0,
                lines=(
                    "exported {ref} at {tip} to {bundle} "
                    "(restore with: git fetch {bundle} {export_ref}:{ref})",
                    "deleted {ref} on origin (lease {tip})",
                    "no local {ref} to delete",
                    "cleared lineage stamps and fetch anchors in 1 worktree",
                    "bootstrapped a fresh empty state at {{fresh_tip}}",
                ),
                error="",
                exports_bundle=True,
                explicit_directory=True,
            ),
            id="schema1-forced",
        ),
        pytest.param(
            ResetPlan(
                arrange=_readable_reset,
                arguments=("--confirm", "--no-export"),
                executed=True,
                status=0,
                lines=(
                    "skipped export (--no-export): {ref} at {tip} not saved",
                    "deleted {ref} on origin (lease {tip})",
                    "no local {ref} to delete",
                    "cleared lineage stamps and fetch anchors in 1 worktree",
                    "bootstrapped a fresh empty state at {{fresh_tip}}",
                ),
                error="",
                exports_bundle=False,
                explicit_directory=True,
            ),
            id="no-export",
        ),
        pytest.param(
            ResetPlan(
                arrange=_never_reset,
                arguments=(),
                executed=False,
                status=0,
                lines=(
                    "would: nothing to export: {ref} does not exist on origin",
                    "would: nothing to delete on origin: {ref} does not exist",
                    "would: no local {ref} to delete",
                    "would: clear lineage stamps and fetch anchors in 1 worktree",
                    "would: bootstrap a fresh empty state",
                ),
                error="",
                exports_bundle=False,
                explicit_directory=True,
            ),
            id="never-dry",
        ),
        pytest.param(
            ResetPlan(
                arrange=_never_reset,
                arguments=("--confirm",),
                executed=True,
                status=0,
                lines=(
                    "nothing to export: {ref} does not exist on origin",
                    "nothing to delete on origin: {ref} does not exist",
                    "no local {ref} to delete",
                    "cleared lineage stamps and fetch anchors in 1 worktree",
                    "bootstrapped a fresh empty state at {{fresh_tip}}",
                ),
                error="",
                exports_bundle=False,
                explicit_directory=True,
            ),
            id="never-confirm",
        ),
        pytest.param(
            ResetPlan(
                arrange=_local_reset,
                arguments=("--confirm",),
                executed=True,
                status=0,
                lines=(
                    "exported {ref} at {tip} to {bundle} "
                    "(restore with: git fetch {bundle} {export_ref}:{ref})",
                    "deleted {ref} on origin (lease {tip})",
                    "deleted local {ref}",
                    "cleared lineage stamps and fetch anchors in 1 worktree",
                    "bootstrapped a fresh empty state at {{fresh_tip}}",
                ),
                error="",
                exports_bundle=True,
                explicit_directory=True,
            ),
            id="foreign-local",
        ),
        pytest.param(
            ResetPlan(
                arrange=_deleted_reset,
                arguments=("--confirm",),
                executed=True,
                status=0,
                lines=(
                    "nothing to export: {ref} does not exist on origin",
                    "nothing to delete on origin: {ref} does not exist",
                    "no local {ref} to delete",
                    "cleared lineage stamps and fetch anchors in 1 worktree",
                    "bootstrapped a fresh empty state at {{fresh_tip}}",
                ),
                error="",
                exports_bundle=False,
                explicit_directory=True,
            ),
            id="deleted-observed",
        ),
        pytest.param(
            ResetPlan(
                arrange=_readable_reset,
                arguments=("--confirm",),
                executed=True,
                status=0,
                lines=(
                    "exported {ref} at {tip} to {bundle} "
                    "(restore with: git fetch {bundle} {export_ref}:{ref})",
                    "deleted {ref} on origin (lease {tip})",
                    "no local {ref} to delete",
                    "cleared lineage stamps and fetch anchors in 1 worktree",
                    "bootstrapped a fresh empty state at {{fresh_tip}}",
                ),
                error="",
                exports_bundle=True,
                explicit_directory=False,
            ),
            id="default-directory",
        ),
    ],
)
def test_reset_plans_or_performs_each_state(
    monkeypatch: pytest.MonkeyPatch,
    clone: Path,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
    case: ResetPlan,
) -> None:
    """Spec: CAS-39, CAS-41, CAS-43, CAS-44, CAS-45, RESET-01, RESET-02,
    RESET-03, RESET-09, RESET-12, RESET-14, RESET-15, RESET-16, RESET-17.
    """
    freeze_cli_now(monkeypatch)
    tip = case.arrange(clone, bare_remote)
    lineage_before = lineage_observation(clone)
    export_dir = clone.parent / "export" if case.explicit_directory else clone.parent
    export_dir.mkdir(exist_ok=True)
    assert not list(export_dir.glob("*.bundle"))
    before = set(export_dir.iterdir())
    bundle = _expected_reset_bundle(export_dir, clone, tip) if tip is not None else None
    arguments = ["reset", *case.arguments]
    if case.explicit_directory:
        arguments += ["--export-dir", str(export_dir)]
    expected_lines = tuple(
        line.format(ref=store.STATE_REF, tip=tip, bundle=bundle, export_ref=store.EXPORT_BUNDLE_REF)
        for line in case.lines
    )
    capsys.readouterr()

    result = run_cli(arguments, capsys)
    remote = state_ref_tip(bare_remote)
    lines, printed = _bootstrap_output(result.stdout)
    actual: dict[str, object] = {
        "status": result.status,
        "lines": lines,
        "error": result.stderr,
        "local": store.local_state_ref_exists(clone),
        "export_changes": set(export_dir.iterdir()) - before,
    }
    expected: dict[str, object] = {
        "status": case.status,
        "lines": expected_lines,
        "error": case.error,
        "local": False,
        "export_changes": {bundle} if case.exports_bundle else set(),
    }
    if case.executed:
        reader_error, reader_tip, reader_claims = _read_reset_state(clone)
        actual.update(
            printed_tip=printed is not None and printed == remote,
            fresh_tip=bool(remote) and remote != tip,
            reader_error=reader_error,
            reader_tip=reader_tip is not None and reader_tip == remote,
            reader_claims=reader_claims,
        )
        expected.update(
            printed_tip=True, fresh_tip=True, reader_error=None, reader_tip=True, reader_claims=()
        )
    else:
        actual.update(remote=remote, lineage=lineage_observation(clone))
        expected.update(remote=tip, lineage=lineage_before)
    if case.exports_bundle:
        actual.update(
            bundle_verified=real_git(
                clone, "bundle", "verify", str(bundle), check=False
            ).returncode,
            bundle_heads=real_git(
                clone, "bundle", "list-heads", str(bundle), check=False
            ).stdout.strip(),
        )
        expected.update(bundle_verified=0, bundle_heads=f"{tip} {store.EXPORT_BUNDLE_REF}")
    assert actual == expected


@pytest.mark.parametrize(
    "mode, identified",
    [
        pytest.param([], True, id="dry-run"),
        pytest.param(["--confirm"], True, id="confirm"),
        pytest.param(["--confirm", "--force-unreadable"], True, id="forced"),
        pytest.param([], False, id="no-identity"),
    ],
)
def test_reset_refuses_live_claims_and_touches_nothing(
    clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: list[str],
    identified: bool,
) -> None:
    """Spec: CAS-40, CAS-62, CAS-63, CAS-64, RESET-17 -- release every live claim first."""
    store.bootstrap(worktree=clone, remote="origin")
    for identity, agent, branch, claim_id, operation in (
        (protocol.IssueIdentity(42), "Codex Sol", "codex/issue-42-reset", "claim-42", "op-42"),
        (protocol.IssueIdentity(43), "Grok Ada", "codex/issue-43-reset", "claim-43", "op-43"),
        (protocol.LaneIdentity(), "Grok Ada", "fix/reset-docs", "claim-lane", "op-lane"),
    ):
        store.commit_transition(
            observed=fresh_observation(clone, "origin"),
            subject=store.ClaimTransitionSubject("claim reset example", item=branch),
            intent=claim_intent(
                identity=identity,
                agent=agent,
                branch=branch,
                claim_id=claim_id,
                operation_id=operation,
            ),
        )
    if identified:
        monkeypatch.setenv(checkout.ACO_AGENT_ENV, "Codex Sol")
        releases = (
            "aco release 42 --claim-id claim-42 --abandoned <reason>",
            "aco release 43 --claim-id claim-43 --role coordinator --coordinator-override "
            "--abandoned <reason>",
            "aco release --branch fix/reset-docs --role coordinator --coordinator-override "
            "--abandoned <reason>",
        )
    else:
        monkeypatch.delenv(checkout.ACO_AGENT_ENV)
        releases = (
            "aco release 42 --claim-id claim-42 --agent 'Codex Sol' --abandoned <reason>",
            "aco release 43 --claim-id claim-43 --agent 'Grok Ada' --abandoned <reason>",
            "aco release --branch fix/reset-docs --agent 'Grok Ada' --abandoned <reason>",
        )
    tip = state_ref_tip(bare_remote)
    lineage_before = lineage_observation(clone)
    assert all(lineage_before)
    assert not store.local_state_ref_exists(clone)
    export_dir = clone.parent / "export"
    export_dir.mkdir()
    capsys.readouterr()

    result = run_cli(["reset", *mode, "--export-dir", str(export_dir)], capsys)
    remote = state_ref_tip(bare_remote)
    files = tuple(export_dir.iterdir())
    local = store.local_state_ref_exists(clone)
    lineage = lineage_observation(clone)
    real_git(clone, "checkout", "-q", "--detach")
    printed_releases = re.findall(r", release: ([^;\n]+)", result.stderr)
    advice_results = []
    for command in printed_releases:
        filled = command.replace("<reason>", shlex.quote("a stuck state ref"))
        shell_status, arguments = arguments_bash_hands_aco(filled, clone.parent)
        released = run_cli(arguments, capsys) if arguments else None
        advice_results.append((shell_status, arguments[:1], released.status if released else None))
    subsequent = run_cli(["reset"], capsys)
    expected_error = (
        "ERROR: refs/aco/state holds 3 live claim(s); release them first, "
        "or reset after they are gone: "
        "issue #42 by Codex Sol (builder) branch=codex/issue-42-reset claim=claim-42, "
        f"release: {releases[0]}; "
        "issue #43 by Grok Ada (builder) branch=codex/issue-43-reset claim=claim-43, "
        f"release: {releases[1]}; "
        "lane fix/reset-docs by Grok Ada (builder) branch=fix/reset-docs claim=claim-lane, "
        f"release: {releases[2]}\n"
    )
    assert (
        result.status,
        result.stdout,
        result.stderr,
        remote,
        files,
        local,
        lineage,
        advice_results,
        subsequent.status,
    ) == (
        2,
        "",
        expected_error,
        tip,
        (),
        False,
        lineage_before,
        [(0, ["release"], 0)] * 3,
        0,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param(["--bogus"], id="unknown-option"),
        pytest.param(["extra"], id="positional"),
        pytest.param(["--json"], id="json"),
        pytest.param(["--conf", "--f"], id="abbreviated"),
    ],
)
def test_reset_refuses_undefined_arguments_before_any_read(
    clone: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    """Spec: RESET-10, OUT-09 -- undefined arguments refuse before repository reads."""
    reads = count_context_reads(monkeypatch)
    capsys.readouterr()
    result = run_cli(["reset", *arguments], capsys)
    assert (result.status, result.stderr.splitlines()[-1:], reads.drain()) == (
        2,
        [f"aco: error: unrecognized arguments: {' '.join(arguments)}"],
        ({}, {}, {}),
    )


@pytest.mark.parametrize(
    "repo",
    [
        pytest.param([], id="without-repo"),
        pytest.param(["--repo", "example/agent-coordination"], id="with-repo"),
    ],
)
@pytest.mark.parametrize(
    "mode, expected_lines, executed",
    [
        pytest.param(
            [],
            (
                "would: nothing to export: {ref} does not exist on origin",
                "would: nothing to delete on origin: {ref} does not exist",
                "would: no local {ref} to delete",
                "would: clear lineage stamps and fetch anchors in 1 worktree",
                "would: bootstrap a fresh empty state",
            ),
            False,
            id="dry",
        ),
        pytest.param(
            ["--confirm"],
            (
                "nothing to export: {ref} does not exist on origin",
                "nothing to delete on origin: {ref} does not exist",
                "no local {ref} to delete",
                "cleared lineage stamps and fetch anchors in 1 worktree",
                "bootstrapped a fresh empty state at {{fresh_tip}}",
            ),
            True,
            id="confirm",
        ),
    ],
)
def test_reset_ignores_repo_without_resolving_a_forge(
    clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    repo: list[str],
    mode: list[str],
    expected_lines: tuple[str, ...],
    executed: bool,
) -> None:
    """Spec: RESET-11 -- repo does not affect a forge-free reset."""

    def forbidden(*args, **kwargs):
        pytest.fail("reset must not resolve a forge")

    monkeypatch.setattr(session, "_build_forge", forbidden)
    capsys.readouterr()
    result = run_cli([*repo, "reset", *mode], capsys)
    remote = state_ref_tip(bare_remote)
    lines, printed = _bootstrap_output(result.stdout)
    actual = {
        "status": result.status,
        "lines": lines,
        "remote": bool(remote),
        "printed_tip": printed is not None and printed == remote,
    }
    expected = {
        "status": 0,
        "lines": tuple(line.format(ref=store.STATE_REF) for line in expected_lines),
        "remote": executed,
        "printed_tip": executed,
    }
    assert actual == expected


def _reject_delete(
    monkeypatch: pytest.MonkeyPatch,
    clone: Path,
    tip: str,
    *,
    perform_delete: bool = False,
    fail_probe: bool = False,
) -> None:
    launch = process.run_captured
    deleted = False
    delete = [
        "git",
        "-C",
        str(clone),
        "push",
        "origin",
        f"--force-with-lease={store.STATE_REF}:{tip}",
        f":{store.STATE_REF}",
    ]
    probe = ["git", "-C", str(clone), "ls-remote", "--exit-code", "origin", store.STATE_REF]

    def captured(command: list[str], **kwargs) -> process.CapturedResult:
        nonlocal deleted
        if command == delete:
            deleted = True
            if perform_delete:
                launch(command, **kwargs)
            return process.CapturedResult(1, b"", b"simulated rejected delete")
        if deleted and command == probe and fail_probe:
            return process.CapturedResult(1, b"", b"simulated network failure")
        return launch(command, **kwargs)

    monkeypatch.setattr(process, "run_captured", captured)


class FreshTip(Enum):
    REQUIRED = auto()


@dataclass(frozen=True)
class ResetFailure:
    status: int
    error: str
    remote: str | FreshTip | None
    local_tip: str
    verification: bool
    lineage: tuple[protocol.ObjectId | None, str | None] | None = None
    manual_lease: bool | None = None


@contextmanager
def _denied_export(
    monkeypatch: pytest.MonkeyPatch, clone: Path, bare_remote: Path, tip: str, bundle: Path
) -> Iterator[ResetFailure]:
    assert not store.local_state_ref_exists(clone)
    lineage = lineage_observation(clone)
    bundle.parent.chmod(0o500)
    try:
        yield ResetFailure(
            status=2,
            error=re.escape(f"ERROR: cannot export {store.STATE_REF} at {tip} to {bundle}: ")
            + r".+\n",
            remote=tip,
            local_tip="",
            verification=False,
            lineage=lineage,
        )
    finally:
        bundle.parent.chmod(0o700)


@contextmanager
def _moved_remote(
    monkeypatch: pytest.MonkeyPatch, clone: Path, bare_remote: Path, tip: str, bundle: Path
) -> Iterator[ResetFailure]:
    assert not store.local_state_ref_exists(clone)
    tree = real_git(clone, "rev-parse", f"{tip}^{{tree}}").stdout.strip()
    moved_tip = real_git(clone, "commit-tree", tree, "-p", tip, "-m", "moved").stdout.strip()
    assert moved_tip != tip
    real_export = store.export_state_bundle

    def export_then_move_remote(
        *, worktree: Path, tip: protocol.ObjectId, destination: Path
    ) -> Path:
        result = real_export(worktree=worktree, tip=tip, destination=destination)
        real_git(clone, "push", "--force", str(bare_remote), f"{moved_tip}:{store.STATE_REF}")
        return result

    monkeypatch.setattr(store, "export_state_bundle", export_then_move_remote)
    yield ResetFailure(
        status=2,
        error=(
            re.escape(f"ERROR: cannot delete {store.STATE_REF} on origin (lease {tip}): ")
            + r".+"
            + re.escape(
                f"; the remote moved to {moved_tip} -- re-run `aco reset --confirm`, which "
                "re-observes origin, re-validates against every live claim, and re-exports "
                f"before deleting again; a manual lease against {moved_tip} "
                "would skip both checks\n"
            )
        ),
        remote=moved_tip,
        local_tip="",
        verification=True,
        manual_lease=False,
    )


def _retain_local_ref(clone: Path, tip: str) -> None:
    real_git(clone, "update-ref", store.STATE_REF, tip)
    assert state_ref_tip(clone) == tip


@contextmanager
def _unchanged_lease(
    monkeypatch: pytest.MonkeyPatch, clone: Path, bare_remote: Path, tip: str, bundle: Path
) -> Iterator[ResetFailure]:
    _retain_local_ref(clone, tip)
    _reject_delete(monkeypatch, clone, tip)
    yield ResetFailure(
        status=2,
        error=re.escape(
            f"ERROR: cannot delete {store.STATE_REF} on origin (lease {tip}): "
            f"simulated rejected delete; {store.STATE_REF} is still present at "
            f"{tip}, unchanged from the lease -- re-run "
            "`aco reset --confirm` once the cause is fixed\n"
        ),
        remote=tip,
        local_tip=tip,
        verification=True,
        manual_lease=False,
    )


@contextmanager
def _unknown_lease(
    monkeypatch: pytest.MonkeyPatch, clone: Path, bare_remote: Path, tip: str, bundle: Path
) -> Iterator[ResetFailure]:
    _retain_local_ref(clone, tip)
    _reject_delete(monkeypatch, clone, tip, fail_probe=True)
    yield ResetFailure(
        status=2,
        error=re.escape(
            f"ERROR: cannot delete {store.STATE_REF} on origin (lease {tip}): "
            "simulated rejected delete; outcome unknown -- verify with "
            f"`git ls-remote origin {store.STATE_REF}` "
            "before retrying `aco reset --confirm`\n"
        ),
        remote=tip,
        local_tip=tip,
        verification=True,
        manual_lease=False,
    )


@contextmanager
def _lost_response(
    monkeypatch: pytest.MonkeyPatch, clone: Path, bare_remote: Path, tip: str, bundle: Path
) -> Iterator[ResetFailure]:
    assert not store.local_state_ref_exists(clone)
    _reject_delete(monkeypatch, clone, tip, perform_delete=True)
    yield ResetFailure(
        status=0,
        error="",
        remote=FreshTip.REQUIRED,
        local_tip="",
        verification=True,
    )


@contextmanager
def _locked_local_ref(
    monkeypatch: pytest.MonkeyPatch, clone: Path, bare_remote: Path, tip: str, bundle: Path
) -> Iterator[ResetFailure]:
    _retain_local_ref(clone, tip)
    lock = clone / ".git" / f"{store.STATE_REF}.lock"
    lock.write_text("")
    assert lock.is_file()
    try:
        yield ResetFailure(
            status=2,
            error=re.escape(f"ERROR: cannot delete local {store.STATE_REF}: ") + r".+\n",
            remote=None,
            local_tip=tip,
            verification=True,
        )
    finally:
        lock.unlink(missing_ok=True)


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(_denied_export, id="export-denied"),
        pytest.param(_moved_remote, id="remote-moved"),
        pytest.param(_unchanged_lease, id="lease-unchanged"),
        pytest.param(_unknown_lease, id="lease-unknown"),
        pytest.param(_lost_response, id="lost-delete-response"),
        pytest.param(_locked_local_ref, id="local-delete-failed"),
    ],
)
def test_reset_failure_leaves_the_state_intact(
    clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[
        [pytest.MonkeyPatch, Path, Path, str, Path], AbstractContextManager[ResetFailure]
    ],
) -> None:
    """Spec: CAS-41, CAS-43, RESET-04, RESET-05, RESET-06, RESET-07, RESET-08, RESET-13.

    Stop at the failed step.
    """
    freeze_cli_now(monkeypatch)
    tip = _observed_reset(clone, bare_remote)
    export_dir = clone.parent / "export"
    export_dir.mkdir()
    assert not list(export_dir.glob("*.bundle"))
    bundle = _expected_reset_bundle(export_dir, clone, tip)
    with arrange(monkeypatch, clone, bare_remote, tip, bundle) as case:
        capsys.readouterr()
        result = run_cli(["reset", "--confirm", "--export-dir", str(export_dir)], capsys)
    remote = state_ref_tip(bare_remote)
    actual: dict[str, object] = {
        "status": result.status,
        "error": (
            bool(re.fullmatch(case.error, result.stderr, flags=re.DOTALL))
            if case.error
            else result.stderr
        ),
        "local_tip": real_git(
            clone, "rev-parse", "--verify", store.STATE_REF, check=False
        ).stdout.strip(),
        "verification": real_git(clone, "bundle", "verify", str(bundle), check=False).returncode
        == 0,
    }
    expected: dict[str, object] = {
        "status": case.status,
        "error": True if case.error else "",
        "local_tip": case.local_tip,
        "verification": case.verification,
    }
    if case.remote is FreshTip.REQUIRED:
        actual.update(fresh_tip=bool(remote) and remote != tip)
        expected.update(fresh_tip=True)
    else:
        actual.update(remote=remote)
        expected.update(remote=case.remote)
    if case.lineage is not None:
        actual.update(lineage=lineage_observation(clone))
        expected.update(lineage=case.lineage)
    if case.manual_lease is not None:
        actual.update(manual_lease="--force-with-lease" in result.stderr)
        expected.update(manual_lease=case.manual_lease)
    assert actual == expected, result.stderr


def test_reset_bundle_restores_the_released_history(
    clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: CAS-46, STAT-01 -- the printed restore command recovers released claim history."""
    claim_id = "claim-42"
    freeze_cli_now(monkeypatch)
    store.bootstrap(worktree=clone, remote="origin")
    store.commit_transition(
        observed=fresh_observation(clone, "origin"),
        subject=store.ClaimTransitionSubject("claim issue 42", item="42"),
        intent=claim_intent(claim_id=claim_id),
    )
    store.commit_transition(
        observed=fresh_observation(clone, "origin"),
        subject=store.ClaimTransitionSubject("release issue 42", item="42"),
        intent=protocol.ReleaseIntent(
            claim_id=protocol.ClaimId(claim_id),
            agent="Ada",
            role="builder",
            outcome=protocol.AbandonedRelease("test cleanup"),
            operation_id="op-42-release",
        ),
    )
    before = store.fetch_state(worktree=clone, remote="origin")
    assert not before.claims
    assert before.tip is not None
    assert protocol.ClaimId(claim_id) in before.consumed_ids
    real_git(clone, "rev-parse", f"{before.tip}~2")
    export_dir = clone.parent / "export"
    export_dir.mkdir()
    capsys.readouterr()
    reset = run_cli(["reset", "--confirm", "--export-dir", str(export_dir)], capsys)
    bundle = _expected_reset_bundle(export_dir, clone, before.tip)
    restored_remote = clone.parent / "restored-remote.git"
    init_bare_repository(restored_remote)
    restored = real_git(
        restored_remote,
        "fetch",
        "-q",
        str(bundle),
        f"{store.EXPORT_BUNDLE_REF}:{store.STATE_REF}",
        check=False,
    )
    assert restored.returncode == 0
    fresh_repository = clone.parent / "fresh"
    fresh_repository.mkdir()
    real_git(fresh_repository, "init", "-q", "-b", "main")
    real_git(fresh_repository, "remote", "add", "origin", str(restored_remote))
    track_board_config(fresh_repository, "")
    push_repository_trunk(fresh_repository, "origin")
    monkeypatch.chdir(fresh_repository)
    redirect_toplevel(monkeypatch, fresh_repository)
    status = run_cli(["status"], capsys)
    state = store.fetch_state(worktree=fresh_repository, remote="origin")
    assert (
        reset.status,
        state.tip,
        protocol.ClaimId(claim_id) in state.consumed_ids,
        status.status,
        "UNCLAIMED repository" in status.stdout,
    ) == (0, before.tip, True, 0, True)


def _read_reset_state(clone: Path) -> tuple[str | None, str | None, tuple[str, ...]]:
    try:
        fresh = store.fetch_state(worktree=clone, remote="origin")
        return None, fresh.tip, tuple(fresh.claims)
    except protocol.ClaimError as error:
        return type(error).__name__, None, ()
