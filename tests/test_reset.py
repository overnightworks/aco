"""Reset against real state refs, bundles, leases, and worktree lineage."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
from cli_fixtures import (
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

from agent_coordination import checkout, process, protocol, session, store


@pytest.mark.parametrize(
    "state, flags, explicit_directory",
    [
        pytest.param("observed", [], True, id="claim-free-dry"),
        pytest.param("readable", ["--confirm"], True, id="plain"),
        pytest.param("readable", ["--confirm", "--force-unreadable"], True, id="forced"),
        pytest.param("schema1", [], True, id="schema1-dry"),
        pytest.param("schema1", ["--confirm"], True, id="schema1-refused"),
        pytest.param("schema1", ["--confirm", "--force-unreadable"], True, id="schema1-forced"),
        pytest.param("readable", ["--confirm", "--no-export"], True, id="no-export"),
        pytest.param("never", [], True, id="never-dry"),
        pytest.param("never", ["--confirm"], True, id="never-confirm"),
        pytest.param("local", ["--confirm"], True, id="foreign-local"),
        pytest.param("deleted", ["--confirm"], True, id="deleted-observed"),
        pytest.param("readable", ["--confirm"], False, id="default-directory"),
    ],
)
def test_reset_plans_or_performs_each_state(
    monkeypatch: pytest.MonkeyPatch,
    clone: Path,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
    state: str,
    flags: list[str],
    explicit_directory: bool,
) -> None:
    """Spec: RESET-01, RESET-02, RESET-03, RESET-09, RESET-12, RESET-14,
    RESET-15, RESET-16, RESET-17 -- plan, refusal, export and fresh state.
    """
    freeze_cli_now(monkeypatch)
    tip = None
    if state == "schema1":
        tip = push_raw_state_tree(
            bare_remote, clone, [("100644", "blob", blob(clone, b"version = 1\n"), "schema.toml")]
        )
    elif state != "never":
        tip = store.bootstrap(worktree=clone, remote="origin")
    if state in {"observed", "deleted"}:
        store.fetch_state(worktree=clone, remote="origin")
        assert all(lineage_observation(clone))
    if state == "deleted":
        real_git(bare_remote, "update-ref", "-d", store.STATE_REF)
        with pytest.raises(protocol.StateLineageError):
            store.fetch_state(worktree=clone, remote="origin")
        tip = None
    if state == "local":
        real_git(clone, "update-ref", store.STATE_REF, str(tip))
    assert store.local_state_ref_exists(clone) == (state == "local")
    lineage_before = lineage_observation(clone)
    export_dir = clone.parent / "export" if explicit_directory else clone.parent
    if explicit_directory:
        export_dir.mkdir()
        assert list(export_dir.iterdir()) == []
    bundle = export_dir / f"aco-state-{clone.name}-2026-08-21-{str(tip)[:12]}.bundle"
    arguments = ["reset", *flags]
    if explicit_directory:
        arguments += ["--export-dir", str(export_dir)]
    confirmed = "--confirm" in flags
    refused = state == "schema1" and confirmed and "--force-unreadable" not in flags
    executed = confirmed and not refused
    saves_bundle = executed and tip is not None and "--no-export" not in flags
    capsys.readouterr()

    result = run_cli(arguments, capsys)
    remote = state_ref_tip(bare_remote)
    local = store.local_state_ref_exists(clone)
    lineage_after = lineage_observation(clone)
    exists = bundle.exists()
    verified = (
        real_git(clone, "bundle", "verify", str(bundle), check=False).returncode
        if saves_bundle
        else None
    )
    heads = (
        real_git(clone, "bundle", "list-heads", str(bundle), check=False).stdout.strip()
        if saves_bundle
        else None
    )
    reader_error, reader_tip, reader_claims = (
        _read_reset_state(clone) if executed else (None, None, ())
    )

    actual = {
        "status": result.status,
        "lines": tuple(result.stdout.splitlines()),
        "error": result.stderr,
        "remote": remote,
        "local": local,
        "lineage": None if executed else lineage_after,
        "bundle_exists": exists,
        "bundle_verified": verified,
        "bundle_heads": heads,
        "reader_error": reader_error,
        "reader_tip": reader_tip,
        "reader_claims": reader_claims,
        "fresh_tip": bool(remote) and remote != tip if executed else False,
    }
    expected = {
        "status": 2 if refused else 0,
        "lines": _plan_lines(state, flags, tip, bundle, remote),
        "error": (
            "ERROR: schema 1 not readable by this aco; live claims unknown "
            "(--confirm needs --force-unreadable)\n"
        )
        if refused
        else "",
        "remote": remote if executed else tip,
        "local": False,
        "lineage": None if executed else lineage_before,
        "bundle_exists": saves_bundle,
        "bundle_verified": 0 if saves_bundle else None,
        "bundle_heads": f"{tip} {store.EXPORT_BUNDLE_REF}" if saves_bundle else None,
        "reader_error": None,
        "reader_tip": remote if executed else None,
        "reader_claims": (),
        "fresh_tip": executed,
    }
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
    "mode", [pytest.param([], id="dry"), pytest.param(["--confirm"], id="confirm")]
)
def test_reset_ignores_repo_without_resolving_a_forge(
    clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    repo: list[str],
    mode: list[str],
) -> None:
    """Spec: RESET-11 -- repo does not affect a forge-free reset."""

    def forbidden(*args, **kwargs):
        pytest.fail("reset must not resolve a forge")

    monkeypatch.setattr(session, "_build_forge", forbidden)
    capsys.readouterr()
    result = run_cli([*repo, "reset", *mode], capsys)
    remote = state_ref_tip(bare_remote)
    expected = (
        f"nothing to export: {store.STATE_REF} does not exist on origin",
        f"nothing to delete on origin: {store.STATE_REF} does not exist",
        f"no local {store.STATE_REF} to delete",
        "cleared lineage stamps and fetch anchors in 1 worktree"
        if mode
        else "clear lineage stamps and fetch anchors in 1 worktree",
        f"bootstrapped a fresh empty state at {remote}"
        if mode
        else "bootstrap a fresh empty state",
    )
    if not mode:
        expected = tuple(f"would: {line}" for line in expected)
    assert (result.status, tuple(result.stdout.splitlines()), bool(remote)) == (
        0,
        expected,
        bool(mode),
    )


def _reject_delete(monkeypatch: pytest.MonkeyPatch, clone: Path, tip: str, mode: str) -> None:
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
            if mode == "lost-delete-response":
                launch(command, **kwargs)
            return process.CapturedResult(1, b"", b"simulated rejected delete")
        if deleted and command == probe and mode == "lease-unknown":
            return process.CapturedResult(1, b"", b"simulated network failure")
        return launch(command, **kwargs)

    monkeypatch.setattr(process, "run_captured", captured)


@pytest.mark.parametrize(
    "failure",
    [
        "export-denied",
        "remote-moved",
        "lease-unchanged",
        "lease-unknown",
        "lost-delete-response",
        "local-delete-failed",
    ],
)
def test_reset_failure_leaves_the_state_intact(
    clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    """Spec: RESET-04, RESET-05, RESET-06, RESET-07, RESET-08, RESET-13.

    Stop at the failed step.
    """
    freeze_cli_now(monkeypatch)
    tip = store.bootstrap(worktree=clone, remote="origin")
    store.fetch_state(worktree=clone, remote="origin")
    lineage_before = lineage_observation(clone)
    assert all(lineage_before)
    local_before = failure in {"lease-unchanged", "lease-unknown", "local-delete-failed"}
    if local_before:
        real_git(clone, "update-ref", store.STATE_REF, tip)
    assert store.local_state_ref_exists(clone) == local_before
    export_dir = clone.parent / "export"
    export_dir.mkdir()
    lock = clone / ".git" / f"{store.STATE_REF}.lock"
    moved_tip = ""
    real_export = store.export_state_bundle

    def export_then_move_remote(
        *, worktree: Path, tip: protocol.ObjectId, destination: Path
    ) -> Path:
        nonlocal moved_tip
        result = real_export(worktree=worktree, tip=tip, destination=destination)
        tree = real_git(clone, "rev-parse", f"{tip}^{{tree}}").stdout.strip()
        moved_tip = real_git(clone, "commit-tree", tree, "-p", tip, "-m", "moved").stdout.strip()
        real_git(clone, "push", "--force", str(bare_remote), f"{moved_tip}:{store.STATE_REF}")
        return result

    if failure == "remote-moved":
        monkeypatch.setattr(store, "export_state_bundle", export_then_move_remote)
    if failure in {"lease-unchanged", "lease-unknown", "lost-delete-response"}:
        _reject_delete(monkeypatch, clone, tip, failure)
    if failure == "export-denied":
        export_dir.chmod(0o500)
    if failure == "local-delete-failed":
        lock.write_text("")
    capsys.readouterr()
    try:
        result = run_cli(["reset", "--confirm", "--export-dir", str(export_dir)], capsys)
    finally:
        export_dir.chmod(0o700)
        lock.unlink(missing_ok=True)
    remote = state_ref_tip(bare_remote)
    local_tip = real_git(
        clone, "rev-parse", "--verify", store.STATE_REF, check=False
    ).stdout.strip()
    bundle = export_dir / f"aco-state-{clone.name}-2026-08-21-{tip[:12]}.bundle"
    verification = real_git(clone, "bundle", "verify", str(bundle), check=False).returncode
    expected_error = _failure_sentence(failure, tip, moved_tip, bundle)
    assert (
        result.status,
        bool(re.fullmatch(expected_error, result.stderr, flags=re.DOTALL)),
        remote,
        local_tip,
        lineage_observation(clone) if failure == "export-denied" else None,
        verification == 0,
    ) == (
        0 if failure == "lost-delete-response" else 2,
        True,
        _failure_remote(failure, tip, moved_tip, remote),
        tip if local_before else "",
        lineage_before if failure == "export-denied" else None,
        failure != "export-denied",
    ), result.stderr


def _failure_remote(failure: str, tip: str, moved_tip: str, remote: str | None) -> str | None:
    if failure == "remote-moved":
        return moved_tip
    if failure == "local-delete-failed":
        return None
    if failure == "lost-delete-response":
        return remote if remote and remote != tip else "missing fresh state"
    return tip


def _failure_sentence(failure: str, tip: str, moved_tip: str, bundle: Path) -> str:
    prefix = f"ERROR: cannot delete {store.STATE_REF} on origin (lease {tip}): "
    if failure == "export-denied":
        return re.escape(f"ERROR: cannot export {store.STATE_REF} at {tip} to {bundle}: ") + r".+\n"
    if failure == "local-delete-failed":
        return re.escape(f"ERROR: cannot delete local {store.STATE_REF}: ") + r".+\n"
    if failure == "remote-moved":
        return (
            re.escape(prefix)
            + r".+"
            + re.escape(
                f"; the remote moved to {moved_tip} -- re-run `aco reset --confirm`, which "
                "re-observes origin, re-validates against every live claim, and re-exports "
                f"before deleting again; a manual lease against {moved_tip} "
                "would skip both checks\n"
            )
        )
    if failure == "lease-unknown":
        return re.escape(
            prefix + "simulated rejected delete; outcome unknown -- verify with "
            f"`git ls-remote origin {store.STATE_REF}` "
            "before retrying `aco reset --confirm`\n"
        )
    if failure == "lease-unchanged":
        return re.escape(
            prefix + f"simulated rejected delete; {store.STATE_REF} is still present at "
            f"{tip}, unchanged from the lease -- re-run "
            "`aco reset --confirm` once the cause is fixed\n"
        )
    return ""


@pytest.mark.parametrize("claim_id", [pytest.param("claim-42", id="released-history")])
def test_reset_bundle_restores_the_released_history(
    clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    claim_id: str,
) -> None:
    """Spec: RESET-03 -- the printed restore command recovers released claim history."""
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
    assert not before.claims and protocol.ClaimId(claim_id) in before.consumed_ids
    real_git(clone, "rev-parse", f"{before.tip}~2")
    export_dir = clone.parent / "export"
    export_dir.mkdir()
    capsys.readouterr()
    reset = run_cli(["reset", "--confirm", "--export-dir", str(export_dir)], capsys)
    bundle = export_dir / f"aco-state-{clone.name}-2026-08-21-{str(before.tip)[:12]}.bundle"
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
        restored.returncode,
        state.tip,
        protocol.ClaimId(claim_id) in state.consumed_ids,
        status.status,
        "UNCLAIMED repository" in status.stdout,
    ) == (0, 0, before.tip, True, 0, True)


def _plan_lines(
    state: str, flags: list[str], tip: str | None, bundle: Path, remote: str | None
) -> tuple[str, ...]:
    confirmed = "--confirm" in flags
    refused = state == "schema1" and confirmed and "--force-unreadable" not in flags
    executed = confirmed and not refused
    warning = (
        "schema 1 not readable by this aco; live claims unknown "
        "(--confirm needs --force-unreadable)"
    )
    if tip is None:
        export_line = f"nothing to export: {store.STATE_REF} does not exist on origin"
        delete_line = f"nothing to delete on origin: {store.STATE_REF} does not exist"
    else:
        verb = "exported" if executed else "export"
        export_line = (
            f"{verb} {store.STATE_REF} at {tip} to {bundle} "
            f"(restore with: git fetch {bundle} {store.EXPORT_BUNDLE_REF}:{store.STATE_REF})"
        )
        if "--no-export" in flags:
            export_line = f"skipped export (--no-export): {store.STATE_REF} at {tip} not saved"
        delete_verb = "deleted" if executed else "delete"
        delete_line = f"{delete_verb} {store.STATE_REF} on origin (lease {tip})"
    local_line = (
        f"deleted local {store.STATE_REF}"
        if state == "local"
        else f"no local {store.STATE_REF} to delete"
    )
    clear_line = (
        "cleared lineage stamps and fetch anchors in 1 worktree"
        if executed
        else "clear lineage stamps and fetch anchors in 1 worktree"
    )
    bootstrap_line = (
        f"bootstrapped a fresh empty state at {remote}"
        if executed
        else "bootstrap a fresh empty state"
    )
    expected_lines = (export_line, delete_line, local_line, clear_line, bootstrap_line)
    if not confirmed:
        expected_lines = tuple(f"would: {line}" for line in expected_lines)
        if state == "schema1":
            expected_lines = (warning, *expected_lines)
    if refused:
        expected_lines = ()
    return expected_lines


def _read_reset_state(clone: Path) -> tuple[str | None, str | None, tuple[str, ...]]:
    try:
        fresh = store.fetch_state(worktree=clone, remote="origin")
        return None, fresh.tip, tuple(fresh.claims)
    except protocol.ClaimError as error:
        return type(error).__name__, None, ()
