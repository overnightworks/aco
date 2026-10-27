"""The `brief` command (`specs/brief.spec.md`)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast

from . import (
    checkout,
    cmd_status,
    protocol,
    report,
    store,
    workboard,
)
from .session import (
    LaneSharedReading,
    RepoMeaninglessUnderStateRefError,
    RunContext,
    trunk_lane_shared_reading,
)


def _brief_claim(
    claims: tuple[protocol.ActiveClaim, ...], item: int
) -> protocol.ActiveClaim | None:
    """This item's own live claim -- one exclusive build claim per issue
    before the first edit (README), so at most one is ever live; the first
    match is it. `None` when the item carries no live claim at all."""
    for claim in claims:
        if isinstance(claim.identity, protocol.IssueIdentity) and claim.identity.issue == item:
            return claim
    return None


@dataclass(frozen=True)
class _BriefClaim:
    """`brief`'s own live-claim reading: the claim paired with the one age it
    needs -- never every live claim's age like `board_read.claim_ages`, so a lineage
    break in an unrelated claim can never stop this item's brief."""

    claim: protocol.ActiveClaim
    opened_at: datetime


def _brief_live_claim(worktree: Path, state: protocol.ClaimState, item: int) -> _BriefClaim | None:
    claim = _brief_claim(tuple(state.claims.values()), item)
    if claim is None:
        return None
    # A live claim cannot exist without the ref it was read from.
    tip = cast(protocol.ObjectId, state.tip)
    opened_at = store.claim_ages(worktree=worktree, tip=tip, claims=(claim,))[claim.claim_id]
    return _BriefClaim(claim, opened_at)


def _lane_tip(branch: str) -> str | None:
    """`branch`'s current commit -- local first, then `origin/` -- or `None`
    when neither ref resolves (a deleted or not-yet-pushed lane branch). A
    git failure that keeps either read from answering
    raises instead of being read the same way as an absent ref."""
    for ref in (branch, f"origin/{branch}"):
        commit = checkout.resolved_commit(ref)
        if commit is not None:
            return commit
    return None


def _print_brief_claim(
    claim: protocol.ActiveClaim,
    opened_at: datetime,
    observed_at: datetime,
    lane_shared: LaneSharedReading,
) -> None:
    print(
        f"{cmd_status.claim_holder(claim)} branch={protocol.terminal_text(claim.branch)} "
        f"base={claim.base}"
        f"{workboard.claim_age_suffix(opened_at, observed_at)}"
    )
    for path in claim.scope:
        print(f"  {path}")
    if claim.whole_reason is not None:
        print(f"  whole: {protocol.terminal_text(claim.whole_reason)}")
    shared = cmd_status.lane_shared_line(lane_shared)
    if shared is not None:
        print(f"  {shared}")


def _print_brief_step_rules(step_rules: workboard.BriefStepRules) -> None:
    """`RULES` and `CHECKS`: two more sections after the four
    `_print_brief` always prints, only under `--step` -- the repository's own
    `.aco/brief.toml` entries for that lane step, one per line,
    each as `protocol.terminal_text` shows it so no entry can break into a forged
    line or section."""
    print()
    print("RULES")
    for rule in step_rules.rules:
        print(protocol.terminal_text(rule))
    print()
    print("CHECKS")
    for check in step_rules.checks:
        print(protocol.terminal_text(check))


@dataclass(frozen=True)
class _BriefComposition:
    """One `aco brief`'s full composed reads: the four sections
    `_print_brief` always prints, plus, only under `--step`, the repository's
    own rules and checks -- gathered once so the text and `--json` renderers
    print the same reads with no chance to drift apart."""

    body: str
    live: _BriefClaim | None
    observed_at: datetime
    tip: str | None
    touched: tuple[str, ...]
    step_rules: workboard.BriefStepRules | None
    lane_shared: LaneSharedReading


def _print_brief(composition: _BriefComposition) -> None:
    print(protocol.terminal_block(composition.body))
    print()
    print("CLAIM")
    if composition.live is None:
        print("no active claim")
    else:
        _print_brief_claim(
            composition.live.claim,
            composition.live.opened_at,
            composition.observed_at,
            composition.lane_shared,
        )
    print()
    print("TIP")
    if composition.live is not None:
        print(composition.tip if composition.tip is not None else "branch not found")
    print()
    print("TOUCHED")
    for path in composition.touched:
        print(path)
    if composition.step_rules is not None:
        _print_brief_step_rules(composition.step_rules)


class _BriefReason(StrEnum):
    """`aco brief`'s own `--json` `reason` vocabulary (`specs/brief.spec.md`):
    `composed` the only success. `invalid_item` names no
    reachable refusal today -- brief never refuses for an item nothing
    carries (BRIEF-08's own Never clause) -- so it stays out until a future
    slice gives it a caller."""

    COMPOSED = "composed"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


def _brief_claim_json(
    live: _BriefClaim, observed_at: datetime, lane_shared: LaneSharedReading
) -> dict[str, object]:
    claim = live.claim
    return {
        "agent": claim.agent,
        "role": claim.role,
        "branch": claim.branch,
        "base": claim.base,
        "scope": list(claim.scope),
        "whole": claim.whole_reason,
        "age": workboard.claim_age_fields(live.opened_at, observed_at)[0],
        **cmd_status.lane_shared_json(lane_shared),
    }


def _brief_json(composition: _BriefComposition) -> int:
    live = composition.live
    payload: dict[str, object] = {
        "body": composition.body,
        "claim": None
        if live is None
        else _brief_claim_json(live, composition.observed_at, composition.lane_shared),
        "tip": composition.tip,
        "touched": list(composition.touched),
        "outside_claim": None
        if live is None
        else [
            path
            for path in composition.touched
            if not protocol.scopes_overlap(live.claim.scope, (path,))
        ],
    }
    step_rules = composition.step_rules
    if step_rules is not None:
        payload["rules"] = list(step_rules.rules)
        payload["checks"] = list(step_rules.checks)
    report.emit_json(True, _BriefReason.COMPOSED, **payload)
    return 0


def _brief_config(toplevel: Path) -> workboard.BriefConfig | None:
    """`.aco/brief.toml`'s own content, read only when the file is
    actually tracked by git -- the same tracked-file
    requirement `session.board_config` enforces for `board.toml`'s storage pin, so
    an ignored or not-yet-added file never quietly answers for the
    repository. `None` either when it is untracked or when `workboard.load_brief_config`
    finds no such file at all."""
    if not checkout.path_is_tracked(workboard.BRIEF_CONFIG_PATH.as_posix(), directory=toplevel):
        return None
    return workboard.load_brief_config(toplevel / workboard.BRIEF_CONFIG_PATH)


def _brief_step_rules_or_refusal(
    step: str | None, context: RunContext
) -> workboard.BriefStepRules | None:
    """`--step`'s own rules and checks, or `None` when the brief carries no
    `--step` at all -- the one branch that must stay untouched by
    `.aco/brief.toml`'s presence or content (BRIEF-16)."""
    if step is None:
        return None
    config = _brief_config(context.toplevel)
    if config is None:
        raise protocol.ClaimError(f"no {workboard.BRIEF_CONFIG_PATH} in the repository")
    return config.for_step(workboard.BriefStep(step))


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """Compose one item's own reads into the one dispatch brief a lane step's
    body otherwise gets assembled from by hand (AGENTS.md "the next brief
    names the body, the lane tip ... and the commands"): the item's body from
    the forge, its live claim from the store, the claim branch's current tip,
    and the files the lane itself changes since its merge base with trunk.
    Never a new data source, and never a write. Every refusal on this path --
    BRIEF-07, BRIEF-09's PIN-04/PIN-05, BRIEF-15, BRIEF-18's lane-tip read and
    trunk diff, BRIEF-20's trunk read, and the item read itself, which is a
    forge call like any other -- reports through `report.refuse` under
    this command's own vocabulary."""
    as_json = parsed.json
    try:
        return _brief_report(parsed, context)
    except RepoMeaninglessUnderStateRefError as error:
        return report.refuse(_BriefReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_BriefReason.UNAVAILABLE, error, as_json=as_json)


def _brief_report(parsed: argparse.Namespace, context: RunContext) -> int:
    """`brief`'s own composition and printing, every refusal raised by name
    for `run` to report."""
    step_rules = _brief_step_rules_or_refusal(parsed.step, context)
    item = int(parsed.item)
    client = context.forge
    item_body = client.item_reference(item).body or ""
    live = _brief_live_claim(context.toplevel, context.observation, item)
    if live is None:
        tip: str | None = None
        touched: tuple[str, ...] = ()
    else:
        tip = _lane_tip(live.claim.branch)
        touched = (
            checkout.lane_changed_paths(tip, trunk=context.trunk_ref, directory=context.toplevel)
            if tip is not None
            else ()
        )
    observed_at = datetime.now(UTC)
    composition = _BriefComposition(
        item_body,
        live,
        observed_at,
        tip,
        touched,
        step_rules,
        trunk_lane_shared_reading(context.configured_canonical_remote, context.toplevel),
    )
    if parsed.json:
        return _brief_json(composition)
    _print_brief(composition)
    return 0
