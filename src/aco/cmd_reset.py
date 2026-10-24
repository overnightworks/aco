"""The `reset` command (`specs/reset.spec.md`)."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path

from . import body, checkout, protocol, store, workboard
from .session import RunContext

# A short, still-practically-unique prefix of an `ObjectId`'s 40 hex
# characters (git's own `--short` abbreviation depends on the repository's
# object count, which the bundle filename has no reason to vary with).
_RESET_BUNDLE_SHA_LENGTH = 12


class _ResetStep(StrEnum):
    """The five lines `reset` prints, in the one order the dry run and the
    real run share (plan review, 19.09.2026): export, delete the remote
    ref, delete the local one if present, clear every worktree's lineage
    stamp and fetch anchor, bootstrap fresh."""

    EXPORT = "export"
    DELETE_REMOTE = "delete_remote"
    DELETE_LOCAL = "delete_local"
    CLEAR_STAMPS = "clear_stamps"
    BOOTSTRAP = "bootstrap"


_RESET_STEP_ORDER: tuple[_ResetStep, ...] = (
    _ResetStep.EXPORT,
    _ResetStep.DELETE_REMOTE,
    _ResetStep.DELETE_LOCAL,
    _ResetStep.CLEAR_STAMPS,
    _ResetStep.BOOTSTRAP,
)


@dataclass(frozen=True)
class _ResetExportTarget:
    tip: protocol.ObjectId
    destination: Path


@dataclass(frozen=True)
class _ResetPlan:
    """Every fact `reset`'s five lines are built from, read once before
    anything is exported or deleted (plan review, 19.09.2026). The dry run
    prints this verbatim with a `would: ` prefix; the real run prints the
    same per-step text as each action completes -- the two share the exact
    same line-building functions below, so they cannot say different things
    about the same reset."""

    remote: str
    remote_tip: protocol.ObjectId | None
    export_target: _ResetExportTarget | None
    local_ref_present: bool
    worktree_count: int
    unreadable_schema_version: int | None


def _reset_bundle_name(repository: str, today: date, tip: protocol.ObjectId) -> str:
    return f"aco-state-{repository}-{today.isoformat()}-{tip[:_RESET_BUNDLE_SHA_LENGTH]}.bundle"


def _reset_restore_command(destination: Path) -> str:
    """`store.export_state_bundle` bundles `store.EXPORT_BUNDLE_REF`, never the
    shared `store.STATE_REF` -- the bundle's own head therefore carries that name (`git bundle
    list-heads` shows it), and the fetch renames it to `STATE_REF` on the
    way in.
    """
    return f"git fetch {destination} {store.EXPORT_BUNDLE_REF}:{store.STATE_REF}"


@dataclass(frozen=True)
class _ResetExportConfig:
    """`--no-export`/`--export-dir`, resolved once: keeps
    `_build_reset_plan` under the five-argument ceiling without folding an
    unrelated pair of facts into `worktree` or `remote`."""

    enabled: bool
    directory: Path


def _resolved_reset_export_config(parsed: argparse.Namespace, toplevel: Path) -> _ResetExportConfig:
    directory = parsed.export_dir if parsed.export_dir is not None else toplevel.parent
    return _ResetExportConfig(enabled=not parsed.no_export, directory=directory)


def _build_reset_plan(
    *,
    worktree: Path,
    remote: str,
    state: protocol.ClaimState | protocol.UnreadableState,
    export: _ResetExportConfig,
    today: date,
) -> _ResetPlan:
    export_target = None
    if export.enabled and state.tip is not None:
        destination = export.directory / _reset_bundle_name(worktree.name, today, state.tip)
        export_target = _ResetExportTarget(tip=state.tip, destination=destination)
    return _ResetPlan(
        remote=remote,
        remote_tip=state.tip,
        export_target=export_target,
        local_ref_present=store.local_state_ref_exists(worktree),
        worktree_count=len(store.list_worktrees(worktree)),
        unreadable_schema_version=(
            state.schema_version if isinstance(state, protocol.UnreadableState) else None
        ),
    )


_ABANDONED_PLACEHOLDER = "--abandoned <reason>"


def _abandoned_release_command(
    claim: protocol.ActiveClaim, storage: body.Storage, running_agent: str | None
) -> str:
    """The `release --abandoned` advice that ends live `claim`:
    an item claim by its item and claim id (so no attached branch is
    needed, as reset needs none), a docs/ or fix/ lane claim by `--branch`;
    from a session that names no identity, as its holder by `--agent`,
    since `release` refuses without one and the holder is the only agent
    reset knows; otherwise, unless `running_agent` holds it, as the
    coordinator -- each the form `release` itself accepts, so the line runs
    as printed once `<reason>` is filled in."""
    target = (
        ("--branch", claim.branch)
        if isinstance(claim.identity, protocol.LaneIdentity)
        else (workboard.item_argument(claim.identity.issue, storage), "--claim-id", claim.claim_id)
    )
    if running_agent is None:
        releaser: tuple[str, ...] = ("--agent", claim.agent)
    elif running_agent == claim.agent:
        releaser = ()
    else:
        releaser = ("--role", protocol.COORDINATOR_ROLE, "--coordinator-override")
    return f"{workboard.advice_command('release', *target, *releaser)} {_ABANDONED_PLACEHOLDER}"


def _reset_live_claims_sentence(
    claims: Iterable[protocol.ActiveClaim], storage: body.Storage, running_agent: str | None
) -> str:
    named = [
        f"{workboard.claim_subject(claim, storage)} by {claim.agent} ({claim.role}) "
        f"branch={claim.branch} claim={claim.claim_id}, release: "
        + _abandoned_release_command(claim, storage, running_agent)
        for claim in claims
    ]
    return (
        f"{store.STATE_REF} holds {len(named)} live claim(s); release them first, "
        f"or reset after they are gone: {'; '.join(named)}"
    )


def _reset_unreadable_line(schema_version: int) -> str:
    return (
        f"schema {schema_version} not readable by this aco; live claims unknown "
        "(--confirm needs --force-unreadable)"
    )


def _reset_export_line(plan: _ResetPlan, *, done: bool) -> str:
    if plan.export_target is None:
        if plan.remote_tip is None:
            return f"nothing to export: {store.STATE_REF} does not exist on {plan.remote}"
        return f"skipped export (--no-export): {store.STATE_REF} at {plan.remote_tip} not saved"
    verb = "exported" if done else "export"
    restore = _reset_restore_command(plan.export_target.destination)
    return (
        f"{verb} {store.STATE_REF} at {plan.export_target.tip} to "
        f"{plan.export_target.destination} (restore with: {restore})"
    )


def _reset_delete_remote_line(plan: _ResetPlan, *, done: bool) -> str:
    if plan.remote_tip is None:
        return f"nothing to delete on {plan.remote}: {store.STATE_REF} does not exist"
    verb = "deleted" if done else "delete"
    return f"{verb} {store.STATE_REF} on {plan.remote} (lease {plan.remote_tip})"


def _reset_delete_local_line(*, present: bool, done: bool) -> str:
    if not present:
        return f"no local {store.STATE_REF} to delete"
    verb = "deleted" if done else "delete"
    return f"{verb} local {store.STATE_REF}"


def _reset_clear_stamps_line(*, worktree_count: int, done: bool) -> str:
    verb = "cleared" if done else "clear"
    plural = "" if worktree_count == 1 else "s"
    return f"{verb} lineage stamps and fetch anchors in {worktree_count} worktree{plural}"


def _reset_bootstrap_line(*, tip: protocol.ObjectId | None) -> str:
    if tip is None:
        return "bootstrap a fresh empty state"
    return f"bootstrapped a fresh empty state at {tip}"


def _print_reset_dry_run(plan: _ResetPlan) -> None:
    lines: dict[_ResetStep, str] = {
        _ResetStep.EXPORT: _reset_export_line(plan, done=False),
        _ResetStep.DELETE_REMOTE: _reset_delete_remote_line(plan, done=False),
        _ResetStep.DELETE_LOCAL: _reset_delete_local_line(
            present=plan.local_ref_present, done=False
        ),
        _ResetStep.CLEAR_STAMPS: _reset_clear_stamps_line(
            worktree_count=plan.worktree_count, done=False
        ),
        _ResetStep.BOOTSTRAP: _reset_bootstrap_line(tip=None),
    }
    if plan.unreadable_schema_version is not None:
        print(_reset_unreadable_line(plan.unreadable_schema_version))
    for step in _RESET_STEP_ORDER:
        print(f"would: {lines[step]}")


def _execute_reset(*, worktree: Path, remote: str, plan: _ResetPlan) -> None:
    """Export -> delete remote -> delete local -> clear stamps -> bootstrap, each step printed the
    moment it completes. An export
    failure raises before anything else runs; a remote-deletion failure
    (rejected, or the lease gone stale) raises with the local ref left
    exactly as it was, and whatever export ran left on disk."""
    if plan.export_target is not None:
        store.export_state_bundle(
            worktree=worktree,
            tip=plan.export_target.tip,
            destination=plan.export_target.destination,
        )
    print(_reset_export_line(plan, done=True))
    local_deleted = store.delete_state_ref(
        worktree=worktree, remote=remote, expected_remote_tip=plan.remote_tip
    )
    print(_reset_delete_remote_line(plan, done=True))
    print(_reset_delete_local_line(present=local_deleted, done=True))
    cleared_worktrees = store.clear_lineage_stamps(worktree=worktree)
    print(_reset_clear_stamps_line(worktree_count=len(cleared_worktrees), done=True))
    fresh_tip = store.bootstrap(worktree=worktree, remote=remote)
    print(_reset_bootstrap_line(tip=fresh_tip))


def _reset_observation(
    context: RunContext,
) -> tuple[Path, str, protocol.ClaimState | protocol.UnreadableState]:
    """`reset`'s own state read:
    `store.peek_state_for_reset` instead of `RunContext.observation`'s ordinary
    `store.fetch_state`, so a broken lineage -- exactly what `reset` exists to
    recover from -- never blocks it, and so a dry run, a live-claim
    refusal, or a failed export writes no per-worktree stamp or anchor.
    A canonical remote with no URL refuses before that read."""
    canonical_remote = context.configured_canonical_remote
    worktree = context.toplevel
    state = store.peek_state_for_reset(worktree=worktree, remote=canonical_remote)
    return worktree, canonical_remote, state


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`reset`: exports `STATE_REF`, deletes it on the remote
    with a lease and locally if present, clears every worktree's lineage
    stamp and fetch anchor, and bootstraps a fresh empty state. Forge-free,
    like `bootstrap`. A live claim always refuses -- `--confirm` or not --
    naming every live claim instead of touching anything: a reset over live
    work is data loss with no owner. A state whose schema this aco cannot
    read has unknown live claims, so executing over it additionally needs
    `--force-unreadable`; its bundle is still exported.
    """
    worktree, remote, state = _reset_observation(context)
    if isinstance(state, protocol.ClaimState) and state.claims:
        raise protocol.ClaimError(
            _reset_live_claims_sentence(
                state.claims.values(), context.config.storage, checkout.session_agent()
            )
        )
    export = _resolved_reset_export_config(parsed, context.toplevel)
    plan = _build_reset_plan(
        worktree=worktree,
        remote=remote,
        state=state,
        export=export,
        today=datetime.now(UTC).date(),
    )
    if not parsed.confirm:
        _print_reset_dry_run(plan)
        return 0
    if plan.unreadable_schema_version is not None and not parsed.force_unreadable:
        raise protocol.ClaimError(_reset_unreadable_line(plan.unreadable_schema_version))
    _execute_reset(worktree=worktree, remote=remote, plan=plan)
    return 0
