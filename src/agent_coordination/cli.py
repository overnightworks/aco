"""Coordinate coding-agent claims through this repository's own state ref."""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
import tomllib
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn, TypeVar, cast

from . import (
    __version__,
    board,
    board_read,
    body,
    checkout,
    cmd_board,
    cmd_bootstrap,
    cmd_check,
    cmd_land,
    cmd_protect,
    cmd_release,
    cmd_reset,
    cmd_rulings,
    cmd_workspace,
    forge,
    github,
    items,
    metrics,
    policy,
    protocol,
    providers,
    report,
    state_board,
    store,
)
from .session import (
    LaneSharedReading,
    LaneSharedUnavailable,
    RepoMeaninglessUnderStateRefError,
    RunContext,
    lane_shared_files,
    trunk_lane_shared_reading,
)

DEFAULT_CLAIM_ROLE = "builder"
NEXT_PULL_DESCRIPTION = (
    "Pulling is not dispatching: an item whose expectations are still unruled is "
    "named here with refining as its first step, while dispatching a builder onto "
    "it waits for the operator's ruling. An item labelled "
    f"{board.NEEDS_OPERATOR_LABEL} waits on the operator and is never pulled; set or "
    f"remove the label with gh issue edit <n> --add-label/--remove-label "
    f"{board.NEEDS_OPERATOR_LABEL}, or under storage = state-ref by piping a body whose "
    "[record] labels add or drop it to aco item edit <item-id>."
)
CLAIM_DESCRIPTION = (
    "Refuses before the first edit unless the checkout is a linked, isolated "
    "worktree on a non-main branch, the tree is clean, and every --scope value is "
    "a repository-relative path."
)
WHOLE_HELP = (
    "one sentence why this wide scope does not split; required for more than "
    "three paths, any directory, or, once the repository has at least twelve "
    "versioned files, more than a quarter of them"
)
ITEM_WHOLE_HELP = (
    "one sentence justifying this item's own wide scope, stored in its body; "
    "claim/start read it as --whole's own fallback when the call itself names none"
)
# `item new`'s own projection flags (issue #555), keyed by the block key
# each one writes.
ITEM_NEW_PROJECTION_FLAGS = (
    ("now", "the block's now: where the item stands"),
    ("next", "the block's next: the one concrete next step"),
    ("done_when", "the block's done_when: the checkable finish"),
)
NOT_A_TWIN_HELP = "create even though an open or recently closed issue carries a similar title"
START_DESCRIPTION = (
    "Creates the item's linked worktree and branch from the canonical remote's own trunk "
    "when neither exists yet, then claims it exactly as aco claim would; a second call "
    "against the same worktree only claims, or reports the live claim."
)
# Shared by `claim` and `start` (issue #322 review finding): CLM-09's own contract, spelled
# once so `start`'s pass-through help text can never drift from what `claim` itself does with
# the flag -- specs/claim.spec.md:62's "the reason is never stored" holds for both.
OUT_OF_ORDER_HELP = (
    "refuses a claim without a reason when a higher-priority actionable item is free or "
    "an open blocker remains; the reason is never stored, only downgrading the check"
)


def _scope_cost(versioned: tuple[str, ...], scope: tuple[str, ...]) -> tuple[int, int, float]:
    n = len(checkout.paths_under_scope(versioned, scope))
    total = len(versioned)
    share = 0.0 if total == 0 else n / total
    return n, total, share


def _optional_whole_reason(arguments: argparse.Namespace) -> str | None:
    raw = getattr(arguments, "whole", None)
    if raw is None:
        return None
    return protocol.outbound_text(raw, _WHOLE_REASON_LABEL, maximum=512)


def _wide_scope_condition(trip: protocol.WideScopeTrip) -> str:
    """The tripped condition in words, with the numbers it was judged
    against -- what the refusal names instead of restating the whole rule."""
    if trip.reason is protocol.WideScopeReason.PATH_COUNT:
        return f"{trip.path_count} paths exceeds three"
    if trip.reason is protocol.WideScopeReason.DIRECTORY:
        noun = "directory" if len(trip.directories) == 1 else "directories"
        return f"{len(trip.directories)} {noun} in scope ({', '.join(trip.directories)})"
    covered, total = trip.covered_file_count, trip.versioned_file_count
    percent = round(100 * covered / total)
    path_word = "path" if covered == 1 else "paths"
    return f"{covered} {path_word} of {total} versioned files ({percent} %) exceeds a quarter"


_WHOLE_REASON_LABEL = "whole reason"
"""`protocol.outbound_text`'s own field name for a `--whole`/body `whole` value
(issue #399), named once here beside the width-gate refusal it justifies --
`_optional_whole_reason`, `_cmd_item_edit_whole` and `_whole_from_item_body`
all bound the same reason text and must refuse by the same name."""


def _wide_scope_refusal(trip: protocol.WideScopeTrip, *, names_body_fallback: bool) -> str:
    suffix = " or set whole in the body" if names_body_fallback else ""
    return f"scope is wide: {_wide_scope_condition(trip)}; pass --whole REASON{suffix}"


def _reject_wide_scope(
    scope: tuple[str, ...],
    versioned: tuple[str, ...],
    whole_reason: str | None,
    *,
    directories: tuple[str, ...],
    whole_from_body: Callable[[], str | None] | None = None,
) -> tuple[int, int, float, str | None]:
    """`scope`'s own width gate (issue #326), `whole_reason`'s own text
    admitting a wide one exactly as before -- plus, for `claim`/`start`
    (issue #399), the effective reason actually used: `whole_reason` itself
    when given, else `whole_from_body()`, read only once the gate actually
    trips and the caller named none, so a narrow scope or an explicit
    `--whole` never costs the body read `whole_from_body` performs.
    `rescope` judges an issue claim by the same rule (issue #554), from the
    body it already read; a lane claim names no item, passes no
    `whole_from_body`, and keeps the plain refusal. `directories` are
    the scope entries that name a directory in the tree `versioned` lists
    (`checkout.scope_directories`)."""
    n, total, share = _scope_cost(versioned, scope)
    trip = _wide_scope_trip(scope, versioned, directories=directories)
    if trip is None:
        return n, total, share, whole_reason
    effective = whole_reason
    if effective is None and whole_from_body is not None:
        effective = whole_from_body()
    if effective is None:
        raise protocol.ClaimError(
            _wide_scope_refusal(trip, names_body_fallback=whole_from_body is not None)
        )
    return n, total, share, effective


def _wide_scope_trip(
    scope: tuple[str, ...], versioned: tuple[str, ...], *, directories: tuple[str, ...]
) -> protocol.WideScopeTrip | None:
    """`scope`'s width judged against the tree `versioned` lists, whose
    entries naming a directory are `directories` -- the one measure the
    width gate refuses by and `next`'s advice anticipates (issue #566)."""
    n, total, _share = _scope_cost(versioned, scope)
    return protocol.wide_scope_trip(
        scope, directories=directories, covered_file_count=n, versioned_file_count=total
    )


def _checkout_scope_is_wide(scope: tuple[str, ...], context: RunContext) -> bool:
    """Whether the width gate calls `scope` wide in `context`'s checkout,
    measured as `_scope_versioning` measures a claim there."""
    directories = checkout.scope_directories(
        scope, directory=context.directory, toplevel=lambda: context.toplevel
    )
    versioned = checkout.versioned_paths(directory=context.directory)
    return _wide_scope_trip(scope, versioned, directories=directories) is not None


def _reject_ungrounded_comma_scope(
    scope: tuple[str, ...], versioned: tuple[str, ...], *, flag: str
) -> None:
    """Refuse a scope entry that contains a comma and matches no versioned
    file -- the shape `{flag} a.py,b.py` takes when passed as one flag from
    habit instead of one path per flag (issue #207). Stored verbatim, that
    single entry names a path nothing tracks, so the claim protects nothing:
    the lane's real files stay uncovered and no overlap check can ever fire
    for them.

    Never call this over `--drop`: a value the live claim already holds is a
    fact about the claim, not a typo about the checkout, and dropping a value
    the claim does not hold is already refused by `combined_scope` with a
    truer sentence naming the claim rather than the checkout -- adding this
    check there would either block the very repair this refusal exists to
    leave open (dropping an already-claimed ungrounded value), or never fire
    at all (a not-yet-dropped value the claim lacks is refused first).

    Splitting on the comma would be the old, wrong fix (issue #201): it made
    a real comma-bearing filename unrepresentable. So a real comma-bearing
    path that names a versioned file, or a directory holding one, still
    passes here -- `paths_under_scope` matches either. So does a comma-free
    path that does not exist yet, since a lane routinely claims files it is
    about to create; only a comma with no match among versioned files is the
    signature this refuses.
    """
    for entry in scope:
        if "," in entry and not checkout.paths_under_scope(versioned, (entry,)):
            raise protocol.ClaimError(
                f"{entry!r} matches no versioned file; one {flag} path per flag, so its comma "
                f"is read literally -- repeat {flag} for a second path"
            )


def _touch_line(
    own_scope: tuple[str, ...], claim: protocol.ScopedClaim, storage: body.Storage
) -> str:
    """One overlapping claim, named with the paths where its scope meets
    `own_scope` -- the fact a claimant needs to know they hold both scopes
    at once, not only the other item's name (issue #206)."""
    meeting = protocol.scope_overlap_paths(own_scope, claim.scope)
    return f"{board.claim_subject(claim, storage)} on {protocol.named_with_overflow_count(meeting)}"


def _touch_summary(
    own_scope: tuple[str, ...], touches: tuple[protocol.ScopedClaim, ...], storage: body.Storage
) -> str:
    if not touches:
        return "overlaps no other open claims"
    return "overlaps " + ", ".join(_touch_line(own_scope, claim, storage) for claim in touches)


def _claim_cost_line(
    n: int,
    total: int,
    own_scope: tuple[str, ...],
    touches: tuple[protocol.ScopedClaim, ...],
    storage: body.Storage,
) -> str:
    percent = 0 if total == 0 else round(100 * n / total)
    return (
        f"{n} of {total} versioned files ({percent}%); "
        f"{_touch_summary(own_scope, touches, storage)}"
    )


def _resolved_claim_branch(arguments: argparse.Namespace, *, directory: Path | None = None) -> str:
    """`claim`'s own branch: `--branch` when given, else `directory`'s
    checked-out branch, read via `-C` when given (issue #322: `start`'s own
    resolved worktree, never a process-wide `os.chdir`) or the calling
    process's own cwd otherwise -- the one resolution `_request` and
    `_cmd_claim` (issue #337, which needs it before `_request` builds a full
    request) both bind to, so it stays a single owner rather than two copies
    of the same git call and validation."""
    branch = (
        checkout.attached_branch(checkout.current_branch(directory=directory))
        if arguments.branch is None
        else arguments.branch
    )
    return protocol.valid_branch({"branch": branch})


def _request(
    arguments: argparse.Namespace,
    *,
    default_branch: Callable[[], str | None],
    directory: Path | None = None,
) -> protocol.ClaimRequest:
    """`_claim_request`, checked against the checkout it is made in:
    `claim` stands in the worktree it claims, judged against the canonical
    remote's recorded default branch `default_branch` answers (issue
    #490)."""
    request = _claim_request(arguments, directory=directory)
    checkout.validate_checkout(request, default_branch=default_branch, directory=directory)
    return request


def _claim_request(
    arguments: argparse.Namespace, *, directory: Path | None = None
) -> protocol.ClaimRequest:
    """The `ClaimRequest` `claim` submits, `arguments.scope` bound as-is
    when given. Omitted -- issue mode only (issue #337); lane mode still
    refuses it, `_checked_claim`'s own first check -- it binds the empty
    tuple instead of raising: `_checked_claim` replaces it with the item's
    own body scope, or a live claim's stored scope on replay, before this
    request's scope ever reaches a wide-scope check or a write. With
    `--base` and `--branch` given it reads no checkout at all (issue #479:
    `start` checks its claim before the worktree exists)."""
    agent = protocol.outbound_text(checkout.resolved_agent(arguments.agent), "agent", maximum=128)
    role = protocol.outbound_text(arguments.role, "role", maximum=64)
    base = (
        checkout.git_output(["rev-parse", "HEAD"], directory=directory)
        if arguments.base is None
        else arguments.base
    )
    if protocol.COMMIT_PATTERN.fullmatch(base) is None:
        raise protocol.ClaimError("base must be a full lowercase commit SHA")
    branch = _resolved_claim_branch(arguments, directory=directory)
    issue = protocol.optional_issue_number(arguments.issue)
    identity = protocol.resolved_identity(issue, branch)
    claim_id = arguments.claim_id or uuid.uuid4().hex
    protocol.ClaimId(claim_id)
    whole_reason = _optional_whole_reason(arguments)
    resource = getattr(arguments, "resource", None)
    if resource is not None:
        resource = protocol.outbound_resource_name(resource)
    return protocol.ClaimRequest(
        identity=identity,
        agent=agent,
        role=role,
        base=base,
        branch=branch,
        scope=() if arguments.scope is None else protocol.valid_scope(arguments.scope),
        claim_id=claim_id,
        out_of_order_reason=arguments.out_of_order,
        whole_reason=whole_reason,
        resource=resource,
    )


LANE_ISSUE_HELP = "omit for lane mode, derived from a docs/ or fix/ checkout branch"
LONG_OPTION_PREFIX = "--"
JSON_HELP = "print the result as JSON instead of the human lines"
AGENT_HELP = (
    f"the acting agent's name; filled from a non-empty {checkout.IDENTITY_ENVIRONMENT_ORDER} "
    "when omitted"
)
EXPECTED_CLAIM_ID_HELP = (
    "assert which claim you are acting on; the issue number or lane branch selects it, and "
    "a differing id is refused rather than redirected"
)
ROLE_ON_LIVE_CLAIM_HELP = (
    "the acting role; the selected claim's own role when omitted, and required to be "
    "coordinator with --coordinator-override"
)
ITEM_REF_HELP = "an item, as aco-xxxxxx, #n, or the bare number n"


def _add_bootstrap_parser(commands: _Subcommands) -> None:
    commands.add_parser("bootstrap", help="create refs/aco/state if it does not exist yet")


def _add_reset_parser(commands: _Subcommands) -> None:
    reset = commands.add_parser(
        "reset",
        help="export refs/aco/state, delete it remotely and locally, and bootstrap fresh",
    )
    reset.add_argument(
        "--confirm", action="store_true", help="perform the reset; omit for a dry run"
    )
    reset.add_argument(
        "--no-export", action="store_true", help="skip the otherwise-mandatory bundle export"
    )
    reset.add_argument(
        "--export-dir",
        type=Path,
        metavar="DIR",
        help="directory for the export bundle (default: the repository's parent directory)",
    )
    reset.add_argument(
        "--force-unreadable",
        action="store_true",
        help="with --confirm, also reset a state whose schema this aco cannot read",
    )


def _add_json_flag(container: argparse.ArgumentParser) -> None:
    """The one place `--json` is declared (issue #432): a command that never
    calls this has no JSON mode at all, and `main` matches this same
    spelling when argparse refuses before any namespace is filled, so the
    flag needs a single owner."""
    container.add_argument(report.JSON_FLAG, action="store_true", help=JSON_HELP)


def _add_status_parser(commands: _Subcommands) -> None:
    status = commands.add_parser("status", help="show repository-wide build claims")
    status.add_argument(
        "issue",
        type=board.parse_item_reference,
        nargs="?",
        help="show only this issue's claims and the ones they overlap",
    )
    status.add_argument(
        "--path", metavar="PATH", help="list holders of this path instead of by issue"
    )
    _add_json_flag(status)


def _add_board_parser(commands: _Subcommands) -> None:
    board_command = commands.add_parser("board", help="project the open work board, read-only")
    _add_json_flag(board_command)
    board_command.add_argument(
        "--serve",
        action="store_true",
        help=argparse.SUPPRESS,
    )


def _add_rulings_parser(commands: _Subcommands) -> None:
    rulings_command = commands.add_parser(
        "rulings", help="list expectation lines, open and ruled, without writes"
    )
    _add_json_flag(rulings_command)


def _add_next_parser(commands: _Subcommands) -> None:
    next_command = commands.add_parser(
        "next",
        help="name the board's top-priority item to pull",
        description=NEXT_PULL_DESCRIPTION,
    )
    _add_json_flag(next_command)


def _add_start_parser(commands: _Subcommands) -> None:
    start = commands.add_parser(
        "start",
        help="create an item's linked worktree and branch, then claim it",
        description=START_DESCRIPTION,
    )
    start.add_argument("item", type=board.parse_item_reference, help=ITEM_REF_HELP)
    start.add_argument(
        "--scope",
        action="append",
        help=(
            "a repository-relative path; repeat --scope for more than one path; the item's "
            "own body scope when omitted"
        ),
    )
    start.add_argument(
        "--slug",
        help=(
            "the worktree/branch slug; derived from the item's title (lowercase, at most "
            "40 characters) when omitted"
        ),
    )
    start.add_argument("--whole", metavar="REASON", help=WHOLE_HELP)
    start.add_argument("--out-of-order", metavar="REASON", help=OUT_OF_ORDER_HELP)


def _add_claim_parser(commands: _Subcommands) -> None:
    claim = commands.add_parser(
        "claim",
        help="claim an issue and scope before editing",
        description=CLAIM_DESCRIPTION,
    )
    claim.add_argument(
        "issue",
        type=board.parse_item_reference,
        nargs="?",
        help=LANE_ISSUE_HELP,
    )
    claim.add_argument("--agent", help=AGENT_HELP)
    claim.add_argument(
        "--role",
        default=DEFAULT_CLAIM_ROLE,
        help=f"the claiming role; default {DEFAULT_CLAIM_ROLE}",
    )
    claim.add_argument(
        "--base",
        help="the full commit SHA this lane starts from; the current HEAD when omitted",
    )
    claim.add_argument(
        "--branch", help="the lane's branch; the current checkout branch when omitted"
    )
    claim.add_argument(
        "--scope",
        action="append",
        help=(
            "a repository-relative path; repeat --scope for more than one path; issue mode "
            "takes it from the item's own body when omitted, and refuses a value whose set "
            "differs from it; lane mode always requires it"
        ),
    )
    claim.add_argument(
        "--claim-id",
        help=(
            "this claim's own id; generated when omitted, and repeating an identical claim "
            "with it returns the active claim instead of writing a second one"
        ),
    )
    claim.add_argument("--out-of-order", metavar="REASON", help=OUT_OF_ORDER_HELP)
    claim.add_argument(
        "--whole",
        metavar="REASON",
        help=WHOLE_HELP,
    )
    claim.add_argument(
        "--resource",
        metavar="NAME",
        help="allocate the next free value of this named scarce resource and hold it",
    )
    _add_json_flag(claim)


def _add_release_parser(commands: _Subcommands) -> None:
    release = commands.add_parser("release", help="release a landed or abandoned claim")
    release.add_argument(
        "issue",
        type=board.parse_item_reference,
        nargs="?",
        help=LANE_ISSUE_HELP,
    )
    release.add_argument("--agent", help=AGENT_HELP)
    release.add_argument("--role", help=ROLE_ON_LIVE_CLAIM_HELP)
    release.add_argument(
        "--branch",
        help=(
            "the claim's lane branch; selects it without checking out that branch, unlike "
            "claim's --branch, and defaults to the current checkout branch when omitted "
            "together with --claim-id"
        ),
    )
    outcome = release.add_mutually_exclusive_group(required=True)
    outcome.add_argument(
        "--merged",
        nargs="?",
        const="",
        metavar="PULL_REQUEST_OR_SHA",
        help=(
            "the pull request that landed this claim's item on the default branch "
            "(storage = github), or the trunk commit that did (storage = state-ref; "
            "bare --merged picks the newest trunk commit naming this item)"
        ),
    )
    outcome.add_argument(
        "--abandoned",
        metavar="REASON",
        help="why this claim ends without a landing",
    )
    release.add_argument("--claim-id", help=EXPECTED_CLAIM_ID_HELP)
    release.add_argument(
        "--coordinator-override",
        action="store_true",
        help="release another agent's claim as the coordinator; requires --role coordinator",
    )
    release.add_argument(
        cmd_release.KEEP_WORKTREE_FLAG,
        action="store_true",
        help=(
            "keep the lane's local worktree and branch after a merged landing; by default a "
            "clean worktree whose branch is already merged is removed"
        ),
    )
    _add_json_flag(release)


def _add_land_parser(commands: _Subcommands) -> None:
    land = commands.add_parser(
        "land",
        help="merge a green pull request with its pinned head sha and run its release path",
    )
    land.add_argument("pull_request", type=int, help="the pull request number to land")
    land.add_argument(
        "--head",
        type=_reviewed_head,
        help=(
            "the head sha the reviewers saw, in full or as a prefix of at least 7 hex digits; "
            "land refuses before any write when the pull request's head is another commit"
        ),
    )
    land.add_argument("--agent", help=AGENT_HELP)
    land.add_argument("--role", help=ROLE_ON_LIVE_CLAIM_HELP)
    land.add_argument(
        "--coordinator-override",
        action="store_true",
        help="land another agent's claim as the coordinator; requires --role coordinator",
    )
    land.add_argument(
        cmd_release.KEEP_WORKTREE_FLAG,
        action="store_true",
        help=(
            "keep the lane's local worktree and branch after landing; by default a clean "
            "worktree whose branch is already merged is removed"
        ),
    )


REVIEWED_HEAD_PATTERN = re.compile(r"[0-9a-fA-F]{7,40}")


def _reviewed_head(value: str) -> str:
    """`land --head`'s argparse `type=` (issue #590): the sha its reviewers
    saw, lowercased as git prints it, refused before anything is read."""
    if REVIEWED_HEAD_PATTERN.fullmatch(value) is None:
        raise protocol.ClaimUnavailableError("--head must be 7 to 40 hex digits")
    return value.lower()


def _add_rescope_parser(commands: _Subcommands) -> None:
    rescope = commands.add_parser(
        "rescope", help="add or drop paths on a live claim without releasing"
    )
    rescope.add_argument(
        "issue",
        type=board.parse_item_reference,
        nargs="?",
        help=LANE_ISSUE_HELP,
    )
    rescope.add_argument("--agent", help=AGENT_HELP)
    rescope.add_argument(
        "--add",
        action="append",
        help=(
            "an absolute or repository-relative path to add; repeat --add for more than one path"
        ),
    )
    rescope.add_argument(
        "--drop",
        action="append",
        help=(
            "an absolute or repository-relative path to drop; repeat --drop for more than one path"
        ),
    )
    rescope.add_argument("--claim-id", help=EXPECTED_CLAIM_ID_HELP)
    rescope.add_argument(
        "--whole",
        metavar="REASON",
        help=WHOLE_HELP,
    )
    _add_json_flag(rescope)


def _add_cut_parser(commands: _Subcommands) -> None:
    cut = commands.add_parser("cut", help="create a container's next slice as a fresh child issue")
    cut.add_argument("issue", type=board.parse_item_reference, help="the container to cut")
    cut.add_argument(
        "--title",
        type=_nonblank_title,
        help=(
            "the fresh child issue's title; default is the linked slice row's own title, "
            "which a given --title must match; required when no row is linked"
        ),
    )
    cut.add_argument(
        "--row",
        type=int,
        metavar="N",
        help="the slice table's # column value to cut; default is the first cuttable row",
    )
    cut.add_argument(
        "--scope",
        action="append",
        help=(
            "a repository-relative path; repeat --scope for more than one path; fills the "
            "cut slice's own row scope when it has none, and becomes the child's scope"
        ),
    )
    cut.add_argument("--not-a-twin", action="store_true", help=NOT_A_TWIN_HELP)
    _add_json_flag(cut)


def _add_ask_parser(commands: _Subcommands) -> None:
    ask = commands.add_parser("ask", help="append one proposed expectation line to an item's block")
    ask.add_argument(
        "item", type=board.parse_item_reference, help="the item to append the expectation line to"
    )
    ask.add_argument("--text", required=True, help="the expectation line's prose")
    ask.add_argument(
        "--default",
        choices=sorted(body.BLOCK_EXPECTATION_DEFAULTS),
        default="yes",
        help="the proposer's suggested outcome; default yes",
    )
    ask.add_argument(
        "--question",
        help=(
            "one operator-language sentence the card shows as its heading "
            f"instead of --text; at most {body.EXPECTATION_QUESTION_MAXIMUM_CHARACTERS} characters"
        ),
    )
    ask.add_argument("--example", help="one operator-language sentence illustrating the question")
    ask.add_argument(
        "--picture",
        metavar="FILE.svg",
        help=(
            "a path to an inline-SVG file (root <svg>, no <script>, no external "
            f"href, at most {body.EXPECTATION_PICTURE_MAXIMUM_BYTES} bytes) the card shows"
        ),
    )
    _add_json_flag(ask)


def _add_rule_parser(commands: _Subcommands) -> None:
    rule = commands.add_parser(
        "rule", help="rule one proposed expectation line, transcribing the operator's word"
    )
    rule.add_argument(
        "item", type=board.parse_item_reference, help="the item whose expectation line is ruled"
    )
    rule.add_argument(
        "--line",
        type=int,
        required=True,
        metavar="N",
        help="the 1-based expectation line index, as rulings prints it",
    )
    outcome = rule.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--yes", action="store_const", dest="ruling", const="yes")
    outcome.add_argument("--no", action="store_const", dest="ruling", const="no")
    outcome.add_argument("--later", action="store_const", dest="ruling", const="later")
    rule.add_argument("--note", help="appended to the line's own text as ' Anmerkung: TEXT'")
    _add_json_flag(rule)


def _parse_check_subject(value: str) -> int | str:
    """`check`'s one positional: a pull/issue reference (`board.parse_item_reference`),
    or -- issue #359, LAND-48 -- a full 40-character commit id, read as a trunk
    commit instead. The two grammars never collide: an item reference
    (`aco-xxxxxx`, `#n`, or the bare `n`) is always far shorter than a full
    git object id."""
    if protocol.COMMIT_PATTERN.fullmatch(value) is not None:
        return value
    return board.parse_item_reference(value)


def _add_check_parser(commands: _Subcommands) -> None:
    check = commands.add_parser(
        "check",
        help=(
            "read one number or trunk commit -- a pull request's work-item "
            "classification, a trunk commit's (LAND-48), or an issue's body "
            "contract; claims, labels and writes nothing"
        ),
    )
    check.add_argument(
        "number",
        type=_parse_check_subject,
        help="the pull request, issue, or trunk commit to read",
    )
    _add_json_flag(check)


def _add_body_parser(commands: _Subcommands) -> None:
    body_parser = commands.add_parser(
        "body",
        help=(
            f"check a piped body's fenced {body.BLOCK_FENCE_INFO} block for defects "
            "before the forge"
        ),
    )
    body_parser.add_argument(
        "--check",
        action="store_true",
        required=True,
        help="read a body from stdin and report its defects",
    )
    _add_json_flag(body_parser)


def _add_brief_parser(commands: _Subcommands) -> None:
    brief = commands.add_parser(
        "brief",
        help="print one item's body, live claim, lane tip and touched files for a dispatch",
    )
    brief.add_argument("item", type=board.parse_item_reference, help="the work item to brief")
    brief.add_argument(
        "--step",
        choices=[step.value for step in board.BriefStep],
        default=None,
        help=f"also print this lane step's own rules and checks from {board.BRIEF_CONFIG_PATH}",
    )
    _add_json_flag(brief)


def _nonblank_title(value: str) -> str:
    """`item new`'s and `cut`'s `--title` argparse `type=` (issue #447):
    `value` unchanged unless `body.is_valid_title` -- the rule `record.title`
    is read by -- refuses it, before anything is read, created, or minted."""
    if not body.is_valid_title(value):
        raise protocol.ClaimUnavailableError("--title must be a non-empty string")
    return value


def _add_item_parser(commands: _Subcommands) -> None:
    item = commands.add_parser("item", help="create, show, edit, or close one work item")
    item_commands = _add_subcommands(item, "item_command")
    new = item_commands.add_parser(
        "new",
        help=(
            "create a fresh item and print its id; its body is read from stdin, a piped "
            f"body without an {body.BLOCK_FENCE_INFO} block getting one built from the flags"
        ),
    )
    for key, meaning in ITEM_NEW_PROJECTION_FLAGS:
        new.add_argument(f"--{key.replace('_', '-')}", dest=key, help=meaning)
    new.add_argument("--title", required=True, type=_nonblank_title, help="the fresh item's title")
    new.add_argument(
        "--kind",
        choices=BODY_TEMPLATE_KINDS,
        default=DEFAULT_BODY_TEMPLATE_KIND,
        help=f"the fresh item's kind; default {DEFAULT_BODY_TEMPLATE_KIND}",
    )
    new.add_argument(
        "--parent",
        type=board.parse_item_reference,
        metavar="ITEM",
        help=f"the fresh item's parent, {ITEM_REF_HELP}",
    )
    new.add_argument(
        "--origin",
        type=items.parse_origin,
        metavar="FORGE#N",
        help="bind this lane to a foreign forge issue, e.g. gitlab#42",
    )
    new.add_argument(
        "--scope",
        action="append",
        help="a repository-relative path; repeat --scope for more than one path",
    )
    new.add_argument(
        "--size",
        choices=tuple(metrics.Size),
        help="this item's size class, for the board's own measured estimate; default none",
    )
    new.add_argument("--whole", metavar="REASON", help=ITEM_WHOLE_HELP)
    new.add_argument("--not-a-twin", action="store_true", help=NOT_A_TWIN_HELP)
    _add_json_flag(new)
    show = item_commands.add_parser(
        "show",
        help="print one item's header and its stored body, display controls escaped"
        " (--json keeps the body as stored)",
    )
    show.add_argument(
        "item", type=board.parse_item_reference, help=f"the item to show, {ITEM_REF_HELP}"
    )
    _add_json_flag(show)
    edit = item_commands.add_parser(
        "edit", help="replace one item's body from stdin, aco keeping its own record fields"
    )
    edit.add_argument(
        "item", type=board.parse_item_reference, help=f"the item to edit, {ITEM_REF_HELP}"
    )
    one_field = edit.add_mutually_exclusive_group()
    refuses_stdin = "reads no stdin; a piped or redirected body is refused"
    one_field.add_argument(
        "--size",
        choices=tuple(metrics.Size),
        help=f"set only this item's size class (any storage); {refuses_stdin}",
    )
    one_field.add_argument(
        "--whole",
        metavar="REASON",
        help=f"set only this item's whole reason (any storage); {refuses_stdin}",
    )
    one_field.add_argument(
        "--kind",
        choices=ITEM_EDIT_KINDS,
        help=f"set only this item's kind (any storage); {refuses_stdin}",
    )
    _add_json_flag(edit)
    close = item_commands.add_parser(
        "close", help="close a state-ref item; the file stays, next and board let it go"
    )
    close.add_argument(
        "item", type=board.parse_item_reference, help=f"the item to close, {ITEM_REF_HELP}"
    )
    _add_json_flag(close)


def _add_protect_parser(commands: _Subcommands) -> None:
    commands.add_parser("protect", help="deny PreToolUse writes without this session's live claim")


def _add_register_parser(commands: _Subcommands) -> None:
    register = commands.add_parser(
        "register",
        help="record one stopped or validated live provider session for workspace recovery",
    )
    register.add_argument("project", metavar="PROJECT", help="a stable local project key")
    register.add_argument(
        "--path", required=True, type=Path, help="the project's canonical directory"
    )
    register.add_argument("--session-id", required=True, help="the exact provider session UUID")
    register.add_argument("--agent", required=True, help="the inherited logical claim identity")
    register.add_argument(
        "--provider",
        choices=tuple(provider.value for provider in providers.Provider),
        default=providers.Provider.CODEX.value,
        help="the conversation provider (default: codex)",
    )
    register.add_argument("--model", help="optional provider model override")
    handover = register.add_mutually_exclusive_group(required=True)
    handover.add_argument(
        "--stopped",
        action="store_true",
        help="acknowledge that the existing provider session was checkpointed and stopped",
    )
    handover.add_argument(
        "--live-pid", type=int, help="the exact running native Codex or Claude process ID"
    )


def _add_run_parser(commands: _Subcommands) -> None:
    run = commands.add_parser("run", help="open the registered provider workspace consoles")
    run.add_argument("project", metavar="PROJECT", nargs="?", help="one registered project")


def _add_login_parser(commands: _Subcommands) -> None:
    login = commands.add_parser(
        "login", help="manage configured workspace recovery at desktop login"
    )
    login_commands = _add_subcommands(login, "login_command")
    login_commands.add_parser("enable", help="install the owned desktop login launcher")
    login_commands.add_parser("disable", help="remove the owned desktop login launcher")
    login_commands.add_parser(
        "status", help="show launcher, configuration, and latest attempt state"
    )


def _add_run_at_login_parser(commands: _Subcommands) -> None:
    commands.add_parser("_run-at-login", help=argparse.SUPPRESS)


# `item`, `protect`, `register`, `run`, `login`, and `_run-at-login` never
# own a `_CommandEntry` (issue #372): `item` fans out to its own four
# subcommands ahead of `_COMMAND_TABLE`, `protect` and the workspace
# commands are forge-free and never reach `_dispatch` at all. `status` and
# `body` are the same story (`_read_status_body_or_dispatch`, ahead of
# `_dispatch`) but `aco --help` must still list all
# eight in their original places, so `_subparser_build_order` below weaves
# them back into position rather than appending them after every table
# entry.
_OTHER_SUBPARSER_BUILDERS: tuple[Callable[[_Subcommands], None], ...] = (
    _add_item_parser,
    _add_protect_parser,
    _add_register_parser,
    _add_run_parser,
    _add_login_parser,
    _add_run_at_login_parser,
)


def _subparser_build_order() -> tuple[Callable[[_Subcommands], None], ...]:
    """Every subcommand's parser builder, in the exact order `aco --help`
    has always listed them (issue #372 R3): read from `_COMMAND_TABLE` only
    here, at `_parser()`'s own call time, since that table is defined
    further below in the file."""
    table = _COMMAND_TABLE
    return (
        table["bootstrap"].add_parser,
        table["reset"].add_parser,
        _add_status_parser,
        table["board"].add_parser,
        table["rulings"].add_parser,
        table["next"].add_parser,
        table["start"].add_parser,
        table["claim"].add_parser,
        table["release"].add_parser,
        table["land"].add_parser,
        table["rescope"].add_parser,
        table["cut"].add_parser,
        table["ask"].add_parser,
        table["rule"].add_parser,
        table["check"].add_parser,
        _add_body_parser,
        table["brief"].add_parser,
        *_OTHER_SUBPARSER_BUILDERS,
    )


class _UsageError(protocol.ClaimError):
    """One refusal the argument parser itself raises -- an unknown flag, a
    missing required option, a mutually exclusive pair -- carried out of the
    parse instead of exiting inside it (issue #432), so a `--json` caller
    still gets the shared envelope. `parser` is the one that refused, a
    subcommand's own rather than the root's, because only it can print the
    usage block the plain-text path still prints byte for byte."""

    def __init__(self, parser: argparse.ArgumentParser, message: str) -> None:
        super().__init__(message)
        self.parser = parser


class _UsageErrorParser(argparse.ArgumentParser):
    """Every `aco` parser and subparser -- argparse hands this class down to
    each subparser it builds. Its own refusal path prints usage and exits
    inside the parse, before `--json` was ever read off a namespace, so this
    raises instead and lets one place decide the refusal's shape.

    No parser reads an abbreviated long option (issue #502, OUT-09): a
    prefix unique today targets another option once one is added, and
    `reset --conf --f` must never stand for a destructive flag pair.

    It also remembers what a refused parse would otherwise lose (issue #432):
    Python parses a subcommand into a throwaway namespace and copies the
    values back only once that parse succeeds, yet `--json` is exactly the
    flag the refusal's own shape depends on. So each parser keeps the tokens
    it was handed and the arguments declared on it, and `subcommands` names
    the parsers one level down."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.declared_actions: list[argparse.Action] = []
        self.received_tokens: tuple[str, ...] | None = None
        self.subcommands: _Subcommands | None = None
        super().__init__(*args, allow_abbrev=False, **kwargs)

    def add_argument(self, *args: Any, **kwargs: Any) -> argparse.Action:
        action = super().add_argument(*args, **kwargs)
        self.declared_actions.append(action)
        return action

    def parse_known_args(
        self, args: Iterable[str] | None = None, *rest: Any, **keywords: Any
    ) -> tuple[Any, list[str]]:
        if self.subcommands:
            self.subcommands.forget_received_tokens()
        self.received_tokens = tuple(sys.argv[1:] if args is None else args)
        return super().parse_known_args(self.received_tokens, *rest, **keywords)

    def error(self, message: str) -> NoReturn:
        raise _UsageError(self, message)


class _Subcommands:
    """The subcommand level of one `aco` parser: builders add their command
    through it, and a refused parse can ask which command was chosen (the
    one that was handed tokens)."""

    def __init__(self, parent: _UsageErrorParser, dest: str) -> None:
        self._action = parent.add_subparsers(dest=dest, required=True)

    def add_parser(self, name: str, **kwargs: Any) -> _UsageErrorParser:
        return self._action.add_parser(name, **kwargs)

    def chosen(self) -> tuple[_UsageErrorParser, tuple[str, ...]] | None:
        return next(
            (
                (parser, parser.received_tokens)
                for parser in self._action.choices.values()
                if parser.received_tokens is not None
            ),
            None,
        )

    def forget_received_tokens(self) -> None:
        """A reused parser must not report the command an earlier parse chose."""
        for parser in self._action.choices.values():
            parser.received_tokens = None
            if parser.subcommands:
                parser.subcommands.forget_received_tokens()


def _add_subcommands(parser: _UsageErrorParser, dest: str) -> _Subcommands:
    parser.subcommands = _Subcommands(parser, dest)
    return parser.subcommands


def _parser() -> _UsageErrorParser:
    parser = _UsageErrorParser(prog="aco", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--repo", help="GitHub repository as OWNER/REPO")
    commands = _add_subcommands(parser, "command")
    for add_subparser in _subparser_build_order():
        add_subparser(commands)
    return parser


def _status_claims(
    claims: tuple[protocol.ActiveClaim, ...], issue: int | None
) -> tuple[tuple[protocol.ActiveClaim, ...], protocol.ClaimConflictIndex]:
    selected = tuple(
        claim
        for claim in claims
        if issue is None
        or (isinstance(claim.identity, protocol.IssueIdentity) and claim.identity.issue == issue)
    )
    index = protocol.claim_conflict_index(claims)
    if not selected:
        return (), index
    related_ids = (
        {claim.claim_id for claim in claims}
        if issue is None
        else protocol.related_claim_ids(index, selected)
    )
    related = tuple(claim for claim in claims if claim.claim_id in related_ids)
    return related, index


def _overlap_subjects(
    claims_by_id: Mapping[str, protocol.ActiveClaim], peer_ids: set[str]
) -> list[dict[str, object]]:
    return [
        {
            **protocol.identity_json(peer.identity),
            "claim_id": peer.claim_id,
            "agent": peer.agent,
        }
        for claim_id in sorted(peer_ids)
        if (peer := claims_by_id.get(claim_id)) is not None
    ]


def _overlap_note(
    claims_by_id: Mapping[str, protocol.ActiveClaim], peer_ids: set[str], storage: body.Storage
) -> str | None:
    peers = [claims_by_id[claim_id] for claim_id in sorted(peer_ids) if claim_id in claims_by_id]
    if not peers:
        return None
    return "overlaps " + ", ".join(
        f"{board.claim_subject(claim, storage)} ({claim.claim_id})" for claim in peers
    )


@dataclass(frozen=True)
class _ClaimReportContext:
    """`index` and `storage` together (issue #292): the two facts every
    claim in one `status` read shares -- bundled so adding `storage`
    beside the pre-existing `index` never pushes a caller past PLR0913's
    five-argument ceiling."""

    index: protocol.ClaimConflictIndex
    storage: body.Storage


def _print_claim_status_lines(
    claim: protocol.ActiveClaim,
    claims_by_id: Mapping[str, protocol.ActiveClaim],
    context: _ClaimReportContext,
    opened_at: datetime,
    observed_at: datetime,
) -> None:
    state = "CONFLICT" if claim.claim_id in context.index.conflict_ids else "CLAIMED"
    print(
        f"{state} {board.claim_subject(claim, context.storage)}: {claim.agent} ({claim.role}) "
        f"base={claim.base} branch={claim.branch} claim={claim.claim_id}"
        f"{board.claim_age_suffix(opened_at, observed_at)}"
    )
    for path in claim.scope:
        print(f"  {path}")
    if claim.resource is not None:
        print(f"  resource {claim.resource.name}={claim.resource.value}")
    if claim.whole_reason is not None:
        print(f"  whole: {claim.whole_reason}")
    note = _overlap_note(
        claims_by_id, protocol.overlap_peer_ids(context.index, claim), context.storage
    )
    if note is not None:
        print(f"  {note}")


def _print_related_claims(
    claims: tuple[protocol.ActiveClaim, ...],
    related: tuple[protocol.ActiveClaim, ...],
    context: _ClaimReportContext,
    ages: Mapping[str, datetime],
    observed_at: datetime,
) -> int:
    claims_by_id: dict[str, protocol.ActiveClaim] = {claim.claim_id: claim for claim in claims}
    for claim in related:
        _print_claim_status_lines(claim, claims_by_id, context, ages[claim.claim_id], observed_at)
    return 2 if any(claim.claim_id in context.index.conflict_ids for claim in related) else 0


def _status(
    claims: tuple[protocol.ActiveClaim, ...],
    issue: int | None,
    ages: Mapping[str, datetime],
    storage: body.Storage,
    lane_shared: LaneSharedReading = (),
) -> int:
    """Every related claim's block, then the lane-shared files once (issue
    #575), named only beside a claim that may write them."""
    observed_at = datetime.now(UTC)
    related, index = _status_claims(claims, issue)
    if related:
        context = _ClaimReportContext(index, storage)
        exit_code = _print_related_claims(claims, related, context, ages, observed_at)
        shared = _lane_shared_line(lane_shared)
        if shared is not None:
            print(shared)
        return exit_code
    subject = "repository" if issue is None else f"issue {board.item_label(issue, storage)}"
    print(f"UNCLAIMED {subject}")
    return 0


class StatusReason(StrEnum):
    """`aco status`'s own `--json` `reason` vocabulary (issue #406,
    `specs/status.spec.md` STAT-03/STAT-05): `claimed`, `unclaimed`, and
    `conflict` are its own three read states. `status` is forge-free
    (STAT-16) and never resolves a repository target, so it names no
    `invalid_usage` of its own -- only `unavailable`, reached when
    `store.fetch_state` refuses a rewritten or malformed state ref."""

    CLAIMED = "claimed"
    UNCLAIMED = "unclaimed"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


def _status_claim_json(
    claim: protocol.ActiveClaim,
    claims_by_id: Mapping[str, protocol.ActiveClaim],
    index: protocol.ClaimConflictIndex,
    ages: Mapping[str, datetime],
    observed_at: datetime,
) -> dict[str, object]:
    age, old = board.claim_age_fields(ages[claim.claim_id], observed_at)
    return {
        **protocol.claim_identity_fields(claim),
        **protocol.resource_fields(claim.resource),
        **({"whole": claim.whole_reason} if claim.whole_reason is not None else {}),
        "overlaps": _overlap_subjects(claims_by_id, protocol.overlap_peer_ids(index, claim)),
        "state": "CONFLICT" if claim.claim_id in index.conflict_ids else "CLAIMED",
        "age": age,
        "old": old,
    }


def _status_json(
    claims: tuple[protocol.ActiveClaim, ...],
    issue: int | None,
    ages: Mapping[str, datetime],
    tip: protocol.ObjectId | None,
    lane_shared: LaneSharedReading = (),
) -> int:
    observed_at = datetime.now(UTC)
    related, index = _status_claims(claims, issue)
    if not related:
        reason = StatusReason.UNCLAIMED
    elif any(claim.claim_id in index.conflict_ids for claim in related):
        reason = StatusReason.CONFLICT
    else:
        reason = StatusReason.CLAIMED
    claims_by_id: dict[str, protocol.ActiveClaim] = {claim.claim_id: claim for claim in claims}
    claims_payload = [
        _status_claim_json(claim, claims_by_id, index, ages, observed_at) for claim in related
    ]
    report.emit_json(
        reason is not StatusReason.CONFLICT,
        reason,
        issue=issue,
        tip=tip,
        claims=claims_payload,
        **_lane_shared_json(lane_shared),
    )
    return 2 if reason is StatusReason.CONFLICT else 0


def _status_path(
    claims: tuple[protocol.ActiveClaim, ...],
    path: str,
    storage: body.Storage,
    lane_shared: LaneSharedReading,
) -> None:
    """`path`'s holders; with none, `LANE-SHARED` for a file the trunk's
    `lane_shared` names, which any claim may write (issue #586), else
    `UNCLAIMED`. A defective trunk configuration adds its own line."""
    holders = protocol.claims_holding_path(claims, path)
    if holders:
        _print_path_holders(holders, path, storage)
    elif path in lane_shared_files(lane_shared):
        print(f"LANE-SHARED {path}")
    else:
        print(f"UNCLAIMED {path}")
    if isinstance(lane_shared, LaneSharedUnavailable):
        print(_lane_shared_unavailable_line(lane_shared))


def _print_path_holders(
    holders: tuple[protocol.ActiveClaim, ...], path: str, storage: body.Storage
) -> None:
    for claim in holders:
        print(
            f"CLAIMED {path} {board.claim_subject(claim, storage)}: {claim.agent} ({claim.role}) "
            f"claim={claim.claim_id}"
        )
        if claim.whole_reason is not None:
            print(f"  whole: {claim.whole_reason}")
    if len(holders) > 1:
        print(
            "overlap: "
            + ", ".join(
                f"{board.claim_subject(claim, storage)} ({claim.claim_id})" for claim in holders
            )
        )


def _lane_shared_unavailable_line(unavailable: LaneSharedUnavailable) -> str:
    return f"lane-shared: unavailable ({unavailable.defect})"


def _lane_shared_line(lane_shared: LaneSharedReading) -> str | None:
    """The one line `status` and `brief` name the repository's lane-shared
    registry files with (issue #575), so a builder comparing its changes
    with its claim scope counts them as allowed: an entry naming no file the
    trunk tracks is marked so, never shown as a grant, and a defective trunk
    configuration names its defect (issue #586); `None` when none is
    configured."""
    if isinstance(lane_shared, LaneSharedUnavailable):
        return _lane_shared_unavailable_line(lane_shared)
    if not lane_shared:
        return None
    return "lane-shared: " + ", ".join(
        entry.path if entry.names_a_file else f"{entry.path} (names no file)"
        for entry in lane_shared
    )


def _lane_shared_json(lane_shared: LaneSharedReading) -> dict[str, object]:
    """`lane_shared` and `lane_shared_unavailable`, the `--json` form of
    `_lane_shared_line` (issue #586): the entries with whether each names a
    trunk-tracked file, or `null` beside the defect that hides them."""
    if isinstance(lane_shared, LaneSharedUnavailable):
        return {"lane_shared": None, "lane_shared_unavailable": lane_shared.defect}
    return {
        "lane_shared": [
            {"path": entry.path, "names_a_file": entry.names_a_file} for entry in lane_shared
        ],
        "lane_shared_unavailable": None,
    }


def _status_path_json(
    claims: tuple[protocol.ActiveClaim, ...], path: str, lane_shared: LaneSharedReading
) -> int:
    holders = protocol.claims_holding_path(claims, path)
    reason = StatusReason.UNCLAIMED if not holders else StatusReason.CLAIMED
    claims_payload = [
        {
            **protocol.claim_identity_fields(claim),
            **protocol.resource_fields(claim.resource),
            **({"whole": claim.whole_reason} if claim.whole_reason is not None else {}),
            "state": "CLAIMED",
        }
        for claim in holders
    ]
    report.emit_json(
        True, reason, path=path, claims=claims_payload, **_lane_shared_json(lane_shared)
    )
    return 0


class RescopeReason(StrEnum):
    """`aco rescope`'s own `--json` `reason` vocabulary (issue #406,
    `specs/rescope.spec.md`): `rescoped` the only success. `invalid_usage`
    covers a malformed `--add`/`--drop` value (a relative entry, one outside
    the checkout, a comma-bearing entry matching no versioned file, or a
    combination `protocol.combined_scope` refuses); `precondition_failed`
    covers this claim's own current state disallowing the rescope (no live
    claim on the target identity/branch, a different agent than the
    claimant, or a scope too wide for the width gate without `--whole`).
    Every other refusal -- an unresolved checkout, a missing state ref, a
    corrupted claim record -- falls to `unavailable`, matching `ask`/`rule`/
    `brief`'s own catch-all."""

    RESCOPED = "rescoped"
    PRECONDITION_FAILED = "precondition_failed"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


def _rescope_json(claimed: protocol.ActiveClaim) -> None:
    report.emit_json(True, RescopeReason.RESCOPED, **protocol.claim_identity_fields(claimed))


@dataclass(frozen=True)
class ScopeVersioning:
    """How much of the claimed scope's Git history the checkout already has,
    for the `--json` claim payload's `versioned_files`/`share` fields."""

    versioned_files: int
    versioned_files_total: int
    share: float


class ClaimReason(StrEnum):
    """`aco claim`'s own `--json` `reason` vocabulary (issue #406,
    `specs/claim.spec.md`): `claimed` the only success. `precondition_failed`
    covers the shared `checks` array `_refuse_claim` reports (out-of-order,
    blocked, container, closed/missing, body-incomplete, missing-parent --
    CLM-08..14). `target_invalid` and `body_invalid` are the two failures a
    scope actually being *derived* from an item's own body can hit before
    those checks ever run: the item itself is unusable (missing, a pull
    request), or its body cannot supply or confirm a scope (a malformed
    `aco` block, no `scope` field, or one differing from an explicit
    `--scope`). `claim_conflict` is `apply()`'s own single failure surface
    for a claim write -- identity already claimed, claim id already
    consumed, or a resource conflict or format issue -- never split further
    here. Every other refusal -- a checkout precondition, scope grammar, an
    unsafe branch or claim id -- falls to `unavailable`, matching `ask`/
    `rule`/`brief`'s own catch-all."""

    CLAIMED = "claimed"
    PRECONDITION_FAILED = "precondition_failed"
    TARGET_INVALID = "target_invalid"
    BODY_INVALID = "body_invalid"
    CLAIM_CONFLICT = "claim_conflict"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


def _claim_json(
    claimed: protocol.ActiveClaim,
    *,
    versioning: ScopeVersioning,
    touches: tuple[protocol.ActiveClaim, ...],
    checks: tuple[SliceCheck, ...],
) -> int:
    report.emit_json(
        True,
        ClaimReason.CLAIMED,
        **protocol.claim_identity_fields(claimed),
        **protocol.resource_fields(claimed.resource),
        versioned_files=versioning.versioned_files,
        versioned_files_total=versioning.versioned_files_total,
        share=versioning.share,
        touches=[protocol.touch_json(claim) for claim in touches],
        checks=[check.as_json() for check in checks],
    )
    return 0


def _ruling_pull_hint(item: board.BoardItem) -> str | None:
    if item.expectation_state is body.ExpectationState.PROPOSED:
        return "expectations unruled: refine before the pull"
    if not item.ruling_old:
        return None
    return f"ruled {item.ruling_landings} landings ago: refine again at the pull"


def _next_action_command(
    action: board.WorkItemAction | board.CutSliceAction,
    storage: body.Storage,
    *,
    site: _PullSite,
) -> str:
    """The exact `aco` invocation `_next` prints and `_next --json` carries
    as `command` -- one owner so text and JSON never name a different
    command for the same action. `close_container` has none: there is no
    command to run, and neither grammar invents one.

    A `WorkItemAction` is `claim` where `next` runs in a checkout `claim`
    accepts (`site.claims_in_place`), else `start` with the slug `start` itself
    derives from the title (issue #562), so the advice runs as printed from
    the default branch's checkout too. Either drops `--scope` entirely for
    an item carrying its own top-level `scope` (issue #348, #337's own
    derivation); an item whose one `[[slice]]` row names paths claims
    exactly those; only an item naming neither still prints the
    placeholder, alongside `SCOPE_UNKNOWN_NOTE`. A scope the width gate
    calls wide in this checkout, with no `whole` in the body, adds
    `--whole <reason>` (issue #566). All render through `board.advice_command`, so the line runs as
    printed (issue #510).
    """
    if isinstance(action, board.CutSliceAction):
        return board.cut_command(action.container.number, storage)
    item = action.item
    pull = board.PullScope(item.scope, action.scope, item.whole, site.scope_is_wide)
    if site.claims_in_place:
        return board.work_item_claim_command(item.number, storage, pull)
    slug = _advised_slug(item.number, item.title, storage)
    return board.work_item_start_command(item.number, storage, slug, pull)


def _advised_slug(number: int, title: str, storage: body.Storage) -> str:
    """The slug `start` derives from `title`, else, for a title with no
    usable slug (issue #566), the one item `number`'s own id yields -- a
    value `start --slug` accepts, so the advice runs as printed."""
    try:
        return checkout.slug_from_title(title)
    except protocol.ClaimError:
        return checkout.slug_from_title(board.item_argument(number, storage))


@dataclass(frozen=True)
class _PullSite:
    """What the checkout `next` runs in says about pulling its action:
    whether `claim` accepts it in place, and whether the width gate calls
    the action's scope wide there (issue #566)."""

    claims_in_place: bool
    scope_is_wide: bool


def _pull_site(action: board.NextAction | None, context: RunContext) -> _PullSite:
    scope = action.scope if isinstance(action, board.WorkItemAction) else None
    return _PullSite(
        claims_in_place=_claims_in_place(context),
        scope_is_wide=scope is not None and _checkout_scope_is_wide(scope, context),
    )


def _claims_in_place(context: RunContext) -> bool:
    """Whether `claim` accepts a build claim in this run's checkout: a
    linked worktree on an attached branch other than the default one, the
    isolation `claim` itself requires (CLAIM_DESCRIPTION)."""
    here = checkout.resolve_path_checkout(context.toplevel)
    return (
        here is not None
        and here.kind is checkout.CheckoutKind.LINKED_WORKTREE
        and not checkout.is_detached_head(here.branch)
        and not checkout.is_default_branch(here.branch, context.recorded_default_branch)
    )


class NextReason(StrEnum):
    """`aco next`'s own `--json` `reason` vocabulary (issue #412,
    `specs/next.spec.md`): the action type -- `work_item`, `cut_slice`,
    `check_container`, `close_container` -- names a success (`ok: true`) exactly as it did
    when carried under the dropped `"action"` key; `nothing_actionable`
    is the one `ok: false` outcome that exits `3` in text (NEXT-01) and
    under `--json` alike, the sole reason exit `3` is ever used.
    `invalid_usage` covers `--repo` under `storage = state-ref`
    (PIN-04); every other refusal -- an unsupported forge host (BOARD-02),
    a state-ref checkout with no resolvable default branch (PIN-05) --
    falls to `unavailable`, matching `ask`/`rule`/`brief`'s own catch-all."""

    WORK_ITEM = "work_item"
    CUT_SLICE = "cut_slice"
    CHECK_CONTAINER = "check_container"
    CLOSE_CONTAINER = "close_container"
    NOTHING_ACTIONABLE = "nothing_actionable"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


def _next_action_reason(action: board.NextAction) -> NextReason:
    if isinstance(action, board.WorkItemAction):
        return NextReason.WORK_ITEM
    if isinstance(action, board.CutSliceAction):
        return NextReason.CUT_SLICE
    if isinstance(action, board.CheckContainerAction):
        return NextReason.CHECK_CONTAINER
    return NextReason.CLOSE_CONTAINER


def _next_action_payload(
    action: board.NextAction, storage: body.Storage, *, site: _PullSite
) -> dict[str, object]:
    """The action-specific fields `_next_json` adds beyond `recovery`/`skipped`
    -- `_next_action_reason` now carries what an `"action"` key used to."""
    number = board.item_json_reference(board.next_action_item(action).number, storage)
    if isinstance(action, board.WorkItemAction):
        item = action.item
        payload: dict[str, object] = {
            "number": number,
            "score": item.score,
            "title": item.title,
            "next": item.next_step,
            "command": _next_action_command(action, storage, site=site),
            "ruling_landings": item.ruling_landings,
            "ruling_old": item.ruling_old,
        }
        hint = _ruling_pull_hint(item)
        if hint is not None:
            payload["ruling_hint"] = hint
        return payload
    if isinstance(action, board.CutSliceAction):
        return {
            "number": number,
            "title": action.container.title,
            "slice": action.next_step,
            "cut_title": action.cut_title,
            "command": _next_action_command(action, storage, site=site),
        }
    return {
        "number": number,
        "closed": action.container_progress.closed,
        "total": action.container_progress.total,
        "next_step": (action.next_step if isinstance(action, board.CheckContainerAction) else None),
    }


# The three sentences issue #348 adds to `next`'s own text form, each named
# once so text and JSON (`_parallel_json`) never restate them (Sonar S1192).
SCOPE_UNKNOWN_NOTE = "scope unknown"
PARALLEL_UNKNOWN_LINE = "parallel: unknown (first action names no scope)"
# "Text zeigt höchstens drei Kandidaten plus 'and N more'" (issue #348 Form):
# a stable display cap, not something an operator tunes.
PARALLEL_TEXT_LIMIT = 3


def _parallel_candidate_label(candidate: board.ParallelCandidate, storage: body.Storage) -> str:
    label = board.item_label(candidate.number, storage)
    count = len(candidate.scope)
    unit = "path" if count == 1 else "paths"
    return f"{label} ({count} {unit})"


def _parallel_line(parallel: board.ParallelSet, storage: body.Storage) -> str:
    """`next`'s own `parallel:` line: the unknown sentence when the first
    action itself names no scope, `none` when the walk placed nothing,
    otherwise every placed candidate capped at `PARALLEL_TEXT_LIMIT` --
    reusing `protocol.named_with_overflow_count`, the one "and N more"
    owner, rather than a second overflow renderer here."""
    if parallel.first_scope_unknown:
        return PARALLEL_UNKNOWN_LINE
    if not parallel.candidates:
        return "parallel: none"
    labels = tuple(
        _parallel_candidate_label(candidate, storage) for candidate in parallel.candidates
    )
    return f"parallel: {protocol.named_with_overflow_count(labels, limit=PARALLEL_TEXT_LIMIT)}"


def _scope_unknown_line(parallel: board.ParallelSet, storage: body.Storage) -> str:
    if not parallel.scope_unknown:
        return "scope unknown: none"
    named = ", ".join(board.item_label(number, storage) for number in parallel.scope_unknown)
    return f"scope unknown: {named}"


def _close_line(close: tuple[int, ...], storage: body.Storage) -> str:
    if not close:
        return "close: none"
    return "close: " + ", ".join(board.item_label(number, storage) for number in close)


def _next_json_numbers(numbers: Iterable[int], storage: body.Storage) -> list[int | str]:
    return [board.item_json_reference(number, storage) for number in numbers]


def _parallel_json(parallel: board.ParallelSet, storage: body.Storage) -> dict[str, object]:
    return {
        "first_scope_unknown": parallel.first_scope_unknown,
        "candidates": [
            {
                "number": board.item_json_reference(candidate.number, storage),
                "scope": list(candidate.scope),
            }
            for candidate in parallel.candidates
        ],
        "scope_unknown": _next_json_numbers(parallel.scope_unknown, storage),
    }


@dataclass(frozen=True)
class _NextReport:
    """Everything `_next`/`_next_json` print for one `next` run, bundled so
    each printer takes one argument instead of PLR0913's five-scalar
    ceiling (issue #348): the board's own first action (`None` when nothing
    qualifies), the unworkable rows `SKIPPED` names, the landed-but-open
    `RECOVERY` rows, the parallel-capacity projection, the zero-cost
    `close:` list, the items waiting on the operator (issue #553), and
    whether `claim` accepts this checkout, which picks `claim` or `start`
    as the advice (issue #562)."""

    action: board.NextAction | None
    skipped: tuple[board.BoardItem, ...]
    recovery: tuple[board.BoardItem, ...]
    parallel: board.ParallelSet
    close: tuple[int, ...]
    waiting: tuple[int, ...]
    site: _PullSite


def _next_json(next_report: _NextReport, storage: body.Storage) -> None:
    reason = (
        _next_action_reason(next_report.action)
        if next_report.action is not None
        else NextReason.NOTHING_ACTIONABLE
    )
    payload: dict[str, object] = {
        "recovery": [
            {
                "number": board.item_json_reference(recovery_item.number, storage),
                "title": recovery_item.title,
                "step": board.RECOVERY_STEP,
            }
            for recovery_item in next_report.recovery
        ],
        "skipped": [
            {
                "number": board.item_json_reference(skipped_item.number, storage),
                "reason": skipped_item.actionable_reason,
            }
            for skipped_item in next_report.skipped
        ],
        "parallel": _parallel_json(next_report.parallel, storage),
        "close": _next_json_numbers(next_report.close, storage),
        "waiting_on_operator": _next_json_numbers(next_report.waiting, storage),
    }
    if next_report.action is not None:
        payload.update(_next_action_payload(next_report.action, storage, site=next_report.site))
    report.emit_json(next_report.action is not None, reason, **payload)


def _next_action_lines(
    action: board.NextAction, storage: body.Storage, *, site: _PullSite
) -> list[str]:
    """The action-specific lines `_next` prints before `parallel:`/`close:`."""
    if isinstance(action, board.WorkItemAction):
        item = action.item
        label = board.item_label(item.number, storage)
        lines = [
            f"{label} score {item.score}: {board.terminal_text(item.title)}",
            f"Next: {board.terminal_text(str(item.next_step))}",
            f"Run: {_next_action_command(action, storage, site=site)}",
        ]
        if action.scope is None:
            lines.append(SCOPE_UNKNOWN_NOTE)
        hint = _ruling_pull_hint(item)
        if hint is not None:
            lines.append(hint)
        return lines
    container_label = board.item_label(action.container.number, storage)
    if isinstance(action, board.CutSliceAction):
        return [
            f"cut_slice {container_label}: {board.terminal_text(action.next_step)}",
            f"Next: {_next_action_command(action, storage, site=site)}",
        ]
    if isinstance(action, board.CheckContainerAction):
        return [
            f"check_container {container_label}: {board.CHECK_DONE_WHEN}",
            f"Next: {board.terminal_text(action.next_step)}",
        ]
    progress = action.container_progress
    return [
        f"close_container {container_label}: "
        f"{progress.closed}/{progress.total} children closed, no Next work"
    ]


def _next(report: _NextReport, storage: body.Storage) -> None:
    """A landed-but-open item is named before anything new is pulled; the
    parallel set and the zero-cost `close:` list are named right after the
    first action, unconditionally (issue #348) -- regardless of that
    action's own rank, so a closable container or a recovery item never goes
    unmentioned merely because something else pulled ahead of it."""
    lines: list[str] = []
    if report.recovery:
        lines.append("RECOVERY")
        lines.extend(
            f"{board.item_label(recovery_item.number, storage)}: {board.RECOVERY_STEP}"
            for recovery_item in report.recovery
        )
        lines.append("")
    lines.extend(
        _next_action_lines(report.action, storage, site=report.site)
        if report.action is not None
        else ["No actionable item."]
    )
    lines.append(_parallel_line(report.parallel, storage))
    if not report.parallel.first_scope_unknown:
        lines.append(_scope_unknown_line(report.parallel, storage))
    lines.append(_close_line(report.close, storage))
    if report.waiting:
        named = ", ".join(board.item_label(number, storage) for number in report.waiting)
        lines.append(f"{board.WAITING_ON_OPERATOR}: {named}")
    if report.skipped:
        skipped_lines = (
            f"{board.item_label(skipped_item.number, storage)}: "
            f"{skipped_item.terminal_actionable_reason}"
            for skipped_item in report.skipped
        )
        lines.extend(("", "SKIPPED", *skipped_lines))
    print("\n".join(lines))


def _unworkable(projected: board.Board) -> tuple[board.BoardItem, ...]:
    return tuple(item for item in projected.items if not item.actionable)


@dataclass(frozen=True)
class SliceCheck:
    """One slice-rule finding — the `check` table `#79` rules.

    `slice`/`issue` carry whichever numbers the message names, so a `--json`
    caller can act on the finding without re-parsing `text`; either is
    `None` when the check has nothing of that kind to name.
    """

    level: str
    check: str
    text: str
    slice: int | None = None
    issue: int | None = None

    def render(self) -> str:
        prefix = "ERROR" if self.level == "error" else "WARNING"
        return f"{prefix}: {board.terminal_text(self.text)}"

    def as_json(self) -> dict[str, object]:
        return {
            "level": self.level,
            "check": self.check,
            "text": self.text,
            "slice": self.slice,
            "issue": self.issue,
        }


def _issue_reference_state(
    client: forge.ForgeReader,
    open_by_number: dict[int, board.Issue],
    number: int,
) -> tuple[forge.ItemState, str | None, str | None]:
    open_issue = open_by_number.get(number)
    if open_issue is not None:
        return forge.ItemState.OPEN, open_issue.title, open_issue.body
    reference = board_read.fetch_issue_reference(client, number)
    return reference.state, reference.title, reference.body


def _out_of_order_check(
    projected: board.Board,
    issue: int | None,
    out_of_order_reason: str | None,
    storage: body.Storage,
) -> SliceCheck | None:
    highest = board.highest_scored_actionable(projected)
    if highest is None or issue is None:
        return None
    claimed_item = next((item for item in projected.items if item.number == issue), None)
    if claimed_item is None or board.board_rank(highest) >= board.board_rank(claimed_item):
        return None
    return SliceCheck(
        "warning" if out_of_order_reason is not None else "error",
        "out-of-order",
        f"higher-priority actionable item {board.item_label(highest.number, storage)} "
        f"(score {highest.score}) is free: {highest.title}; "
        "use --out-of-order REASON to proceed",
        issue=highest.number,
    )


def _blocked_check(
    item: board.BoardItem | None,
    out_of_order_reason: str | None,
    repository: str,
    storage: body.Storage,
) -> SliceCheck | None:
    if item is None or not item.open_blockers:
        return None
    blockers = ", ".join(
        board.open_blocker_label(reference, repository, storage) for reference in item.open_blockers
    )
    return SliceCheck(
        "warning" if out_of_order_reason is not None else "error",
        "blocked",
        f"{board.item_label(item.number, storage)} is blocked by {blockers} (open); "
        "pass --out-of-order REASON to claim it anyway",
        issue=item.number,
    )


def _parent_checks(
    client: forge.ForgeReader, repository: str, issue: int, title: str, storage: body.Storage
) -> SliceCheck | None:
    """Warn when a slice-shaped title names a parent GitHub does not record as one."""
    match = board.slice_title_match(title)
    if match is None:
        return None
    slice_number, parent_issue = match
    if board.names_no_item(parent_issue, storage):
        return None
    parent = client.parent_issue(issue)
    if parent is not None and parent.reference == board.IssueReference(repository, parent_issue):
        return None
    parent_label = board.item_label(parent_issue, storage)
    return SliceCheck(
        "warning",
        "missing-parent",
        f"looks like slice {slice_number} of {parent_label} but is no sub-issue "
        f"of {parent_label}; the parent inherits nothing",
        slice=slice_number,
        issue=parent_issue,
    )


def _malformed_checks(item: board.BoardItem) -> tuple[SliceCheck, ...] | None:
    """The one refusal a malformed block body gets (#150) -- every other
    body-contract check (blocker state, completeness) never runs, since
    neither the parsed projections nor the blocker set can be trusted once
    the body itself failed to read."""
    if item.read_state is body.BodyReadState.MALFORMED:
        return tuple(
            SliceCheck("error", "body-contract", body.body_defect_text(defect))
            for defect in item.contract.defects
        )
    return None


def _body_contract_checks(item: board.BoardItem, storage: body.Storage) -> tuple[SliceCheck, ...]:
    malformed = _malformed_checks(item)
    if malformed is not None:
        return malformed
    contract = item.contract
    checks = [SliceCheck("error", "body-contract", defect.message) for defect in contract.defects]
    # Read the two atomic facts directly rather than `item.actionable_reason`:
    # that reason is the *first* one `_actionable_reason` finds (frozen,
    # claimed, blocked, then incomplete), so an item that is both blocked and
    # incomplete would report only "blocked" there -- masking the incomplete
    # body this check exists to name. A freshly `cut` child (an incomplete
    # but defect-free skeleton) is refused here exactly as it is invisible to
    # `next`, regardless of what else may also be true of it.
    if not item.contract_complete and not item.projectionless_idea:
        missing = ", ".join(body.missing_or_empty_sections(contract))
        checks.append(
            SliceCheck(
                "error",
                "body-incomplete",
                f"{board.item_label(item.number, storage)} body incomplete: {missing}",
                issue=item.number,
            )
        )
    return tuple(checks)


@dataclass(frozen=True)
class BoardReferenceLookup:
    """The board client, its repository, and the currently open issues it can
    resolve `#reference`s against — what every cross-issue slice/parent check
    below needs to look a referenced issue up."""

    client: forge.ForgeReader
    repository: str
    open_by_number: dict[int, board.Issue]


def _slice_rule_checks(
    lookup: BoardReferenceLookup,
    issue: int,
    projected: board.Board,
    out_of_order_reason: str | None,
    storage: body.Storage,
) -> tuple[SliceCheck, ...]:
    checks: list[SliceCheck] = []
    out_of_order = _out_of_order_check(projected, issue, out_of_order_reason, storage)
    if out_of_order is not None:
        checks.append(out_of_order)
    label = board.item_label(issue, storage)
    item = next((item for item in projected.items if item.number == issue), None)
    if item is not None and item.kind is body.ItemKind.CONTAINER:
        checks.append(
            SliceCheck("error", "container", f"{label} is a container; claim a child", issue=issue)
        )
    blocked = _blocked_check(item, out_of_order_reason, lookup.repository, storage)
    if blocked is not None:
        checks.append(blocked)
    state, title, _body = _issue_reference_state(lookup.client, lookup.open_by_number, issue)
    if state is forge.ItemState.CLOSED:
        checks.append(SliceCheck("error", "closed-issue", f"issue {label} is closed", issue=issue))
    elif state is forge.ItemState.MISSING:
        checks.append(
            SliceCheck("error", "missing-issue", f"issue {label} does not exist here", issue=issue)
        )
    if item is not None:
        checks.extend(_body_contract_checks(item, storage))
    if title is not None:
        parent_check = _parent_checks(lookup.client, lookup.repository, issue, title, storage)
        if parent_check is not None:
            checks.append(parent_check)
    return tuple(checks)


def _refuse_claim(as_json: bool, issue: int | None, checks: tuple[SliceCheck, ...]) -> None:
    if as_json:
        report.emit_json(
            False,
            ClaimReason.PRECONDITION_FAILED,
            issue=issue,
            checks=[c.as_json() for c in checks],
        )
        return
    for check in checks:
        print(check.render(), file=sys.stderr)


def _body_shape_defects(
    raw_body: str, *, storage: body.Storage = body.Storage.GITHUB
) -> tuple[str, ...]:
    """`item edit`'s own accessor (issue #287) onto `body.body_shape_check`
    (issue #404): only the defect sentences, never the verdict `check
    <item>` and `body --check` read for their own `--json` `reason`."""
    return body.body_shape_check(raw_body, storage=storage).defects


BODY_TEMPLATE_KINDS = ("task", "feature", "container")
# `item edit --kind`'s targets: an item turns container with its first
# child and back to task once none is open (issue #503).
ITEM_EDIT_KINDS = (body.ItemKind.TASK.value, body.ItemKind.CONTAINER.value)
DEFAULT_BODY_TEMPLATE_KIND = "task"


def _read_body_check_input() -> str:
    """`body --check`'s body text, read from stdin only (issue #262 Sonar
    S8707): an agent pipes the file in (`aco body --check < body.md`)
    rather than naming a path the CLI would have to trust."""
    try:
        return sys.stdin.read()
    except UnicodeDecodeError as error:
        raise protocol.ClaimError(
            f"stdin is not valid UTF-8: {error}; pipe the body as UTF-8 text"
        ) from error


def _stdin_file_mode() -> int | None:
    """The type bits of the descriptor on stdin, told without reading, since
    an idle pipe or socket a harness holds open would block a read forever;
    `None` for a closed stdin."""
    try:
        return os.fstat(sys.stdin.fileno()).st_mode
    except (AttributeError, OSError, ValueError):
        return None


def _stdin_carries_a_body() -> bool:
    """Whether stdin carries a body a command reads (head ruling of
    01.10.2026 on issue #555): a redirected file (`< body.md`) or a pipe
    (`printf ... |`). A socket -- what Claude Code's Bash tool hands a
    command -- a terminal, `/dev/null` or a closed stdin carry none, so the
    command never waits on an idle harness stdin."""
    mode = _stdin_file_mode()
    return mode is not None and (stat.S_ISREG(mode) or stat.S_ISFIFO(mode))


def _refuse_a_body_on_stdin(command: str) -> None:
    """Refuses, before any write, a body `command` would otherwise drop
    unread (issue #567): it reads no stdin, so a file or pipe there carrying
    one (`_stdin_carries_a_body`) is a mistake the person must see."""
    if _stdin_carries_a_body():
        raise protocol.ClaimUnavailableError(f"{command} reads no stdin; drop the redirect")


class BodyCheckReason(StrEnum):
    """`aco body --check`'s own `--json` `reason` vocabulary
    (`specs/body.spec.md`, issue #404): `valid`/`malformed`/`incomplete`
    mirror `body.BodyShapeVerdict`'s own three values -- the same
    body-shape decision `check <item>`'s own `cmd_check.CheckReason` reads."""

    VALID = body.BodyShapeVerdict.VALID.value
    MALFORMED = body.BodyShapeVerdict.MALFORMED.value
    INCOMPLETE = body.BodyShapeVerdict.INCOMPLETE.value
    UNAVAILABLE = "unavailable"


def _body_check_report(check: body.BodyShapeCheck, *, as_json: bool) -> int:
    """The one rendering of a `body --check` answer: `body.body_shape_check`'s
    own sentences, never truncated to the first, since there is no live
    item here to refuse a single verdict about."""
    ok = check.verdict is body.BodyShapeVerdict.VALID
    if as_json:
        report.emit_json(ok, BodyCheckReason(check.verdict.value), defects=list(check.defects))
    elif check.defects:
        for defect in check.defects:
            print(defect, file=sys.stderr)
    else:
        print("body ok")
    return 0 if ok else 2


def _cmd_body(parsed: argparse.Namespace, context: RunContext) -> int:
    """`body --check` is forge-free (issue #262), the same way `status` and
    `bootstrap` are (issue #245): it reads stdin only, never an issue, a
    live claim, a filesystem path, or the forge's own `blocked_by`
    relation, so it never asks the `RunContext` for its forge (`main` dispatches
    it outside `_dispatch`, exactly like `status`). It still reads the
    repository's own storage pin (issue #287): `[record]` is a known key
    under `storage = "state-ref"` and an unknown one under
    `storage = "github"`, the same gate `_state_ref_forge`'s own items
    already read through `_decode_item`."""
    as_json = parsed.json
    try:
        config = context.config
        raw_body = _read_body_check_input()
    except protocol.ClaimError as error:
        return report.refuse(BodyCheckReason.UNAVAILABLE, error, as_json=as_json)
    check = body.body_shape_check(raw_body, storage=config.storage)
    return _body_check_report(check, as_json=as_json)


@dataclass(frozen=True)
class _StoreItemWriter:
    """`state_board.ItemWriter`, implemented over `store` (issue #283): the
    one place this tool hashes an item's finished bytes into a blob and
    writes it through one CAS transition -- an `ItemWriteIntent` (issue
    #279), or for a close an `ItemCloseIntent` (issue #459).
    `state_board.py` itself may not import `store` (Layers contract), so
    this class owns both git steps of a state-ref item write: `_item_write`
    hashes the blob, `_commit` publishes it through the CAS transition.
    """

    context: RunContext

    def write_item(
        self,
        item_id: str,
        *,
        expected: protocol.ObjectId | None,
        content: bytes,
        store_expected: Mapping[str, protocol.ObjectId] | None,
    ) -> protocol.ObjectId:
        return self._commit(self._item_write(item_id, expected, content, store_expected))

    def close_item(
        self,
        item_id: str,
        *,
        number: int,
        expected: protocol.ObjectId,
        content: bytes,
        store_expected: Mapping[str, protocol.ObjectId] | None,
    ) -> protocol.ObjectId:
        write = self._item_write(item_id, expected, content, store_expected)
        return self._commit(protocol.ItemCloseIntent(write, protocol.IssueIdentity(number)))

    def _item_write(
        self,
        item_id: str,
        expected: protocol.ObjectId | None,
        content: bytes,
        store_expected: Mapping[str, protocol.ObjectId] | None,
    ) -> protocol.ItemWriteIntent:
        return protocol.ItemWriteIntent(
            item_id=item_id,
            expected=expected,
            new_oid=store.hash_blob(self.context.toplevel, content),
            operation_id=uuid.uuid4().hex,
            store_expected=store_expected,
        )

    def _commit(
        self, intent: protocol.ItemWriteIntent | protocol.ItemCloseIntent
    ) -> protocol.ObjectId:
        new_state = self.context.transition(
            store.TransitionSubject(f"write item {intent.item_id}"), intent
        )
        return new_state.items[intent.item_id]


def _state_ref_forge(context: RunContext) -> state_board.StateRefBoard:
    """The `state-ref` storage pin's forge (issues #248, #283): repository
    identity and default branch from `context` (host-neutral, the canonical
    remote's recorded `HEAD`),
    item content and blob oids read once through
    `store.read_item_files`/`ClaimState.items` of `context.observation` --
    the very snapshot the command's own checks read (issue #477) -- and a
    write port over that same `store` (`_StoreItemWriter`) -- this is the
    one place `state_board.StateRefBoard` is ever handed live data or a way
    to write it, since the Layers contract keeps that module from reaching
    `store` itself. It reads and writes through `context`'s own worktree:
    `start` (issue #322 review finding 2) hands it a context for the freshly
    created worktree, so the worktree-scoped claim never reads a
    caller-checkout snapshot observed before that worktree existed."""
    repository = context.repository_id
    default_branch = context.default_branch
    state = context.observation
    item_files = {} if state.tip is None else store.read_item_files(context.toplevel, state.tip)
    return state_board.StateRefBoard(
        repository=repository,
        default_branch=default_branch,
        item_files=item_files,
        item_oids=state.items,
        writer=_StoreItemWriter(context),
    )


def _build_forge(context: RunContext) -> forge.ForgeReader:
    """The forge adapter for `context`'s own `storage` pin (issue #248),
    never chosen by the canonical remote's host: `github` (the default)
    builds `github.GitHubForge`; `state-ref` builds
    `state_board.StateRefBoard` from the state ref's own `items/` tree."""
    if context.config.storage is body.Storage.STATE_REF:
        return _state_ref_forge(context)
    return github.GitHubForge(context.repository_id)


def _state_ref_board(context: RunContext) -> state_board.StateRefBoard:
    """`context`'s own forge as the state-ref board, for an item command
    that has already refused every other storage pin: under `state-ref`
    `_build_forge` builds exactly `_state_ref_forge`'s board, so the cast is
    honest, not a suppression -- the same narrowing `RunContext.forge_writer`
    performs for the generic writing surface."""
    return cast(state_board.StateRefBoard, context.forge)


def _run_context(repo: forge.RepositoryId | None) -> RunContext:
    """This run's root context, built once the command is known to need a
    repository at all (after the workspace and `protect` dispatch)."""
    return RunContext(repo, build_forge=_build_forge)


ITEM_NEW_ORIGIN_ON_GITHUB_REFUSAL = '--origin needs storage = "state-ref"'


class ItemReason(StrEnum):
    """`aco item`'s own `--json` `reason` vocabulary, shared across its four
    subcommands (issue #425, `specs/item.spec.md`): `created`/`edited`/
    `closed`/`shown` name each subcommand's own success; `unchanged`, an
    `item edit --size/--whole/--kind` whose value is already set, which
    writes nothing (issue #572). `body_invalid`
    covers only `item new`'s and `item edit`'s own piped-body shape check
    (`_body_shape_defects`, the same check `body --check` runs), carrying
    `defects` the same way (`BodyCheckReason`, issue #404); `partial_write`
    only a GitHub issue `item new` created but could not type or record under
    its `--parent` (issue #444), `cut`'s own shape. Every other refusal -- a
    `storage = "github"` command, a missing item or parent, a possible twin,
    a pull request target, a forge write capability, or a live claim still
    on the item -- is `precondition_failed`, this command family's single
    generic bucket."""

    CREATED = "created"
    EDITED = "edited"
    UNCHANGED = "unchanged"
    CLOSED = "closed"
    SHOWN = "shown"
    PRECONDITION_FAILED = "precondition_failed"
    BODY_INVALID = "body_invalid"
    PARTIAL_WRITE = "partial_write"


def _refuse_item_body_invalid(defects: tuple[str, ...], *, as_json: bool) -> int:
    print(f"{report.CLI_ERROR_PREFIX}{defects[0]}", file=sys.stderr)
    if as_json:
        report.emit_json(False, ItemReason.BODY_INVALID, defects=list(defects), message=defects[0])
    return 2


def _cmd_item_new(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item new` (issues #285, #316, #444): one fresh item under
    either storage pin, each through its own adapter's write
    (`_item_new_on_github`, `_item_new_on_state_ref`), both behind the same
    twin search `cut` runs (`_refuse_possible_twin`). Every refusal but a
    malformed piped body or a partial GitHub write reports through the
    shared envelope as `precondition_failed` (issue #425)."""
    as_json = parsed.json
    try:
        if context.config.storage is body.Storage.GITHUB:
            return _item_new_on_github(parsed, context)
        return _item_new_on_state_ref(parsed, context)
    except _ItemBodyInvalidError as error:
        return _refuse_item_body_invalid(error.defects, as_json=as_json)
    except _PartialWriteError as error:
        return _refuse_partial_write(error, ItemReason.PARTIAL_WRITE, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


class _ItemBodyInvalidError(protocol.ClaimError):
    """`item new`'s piped body refused before anything is created, carrying
    every defect sentence for `body_invalid`'s own `defects` list."""

    def __init__(self, defects: tuple[str, ...]) -> None:
        self.defects = defects
        super().__init__(defects[0])


def _read_item_new_input() -> str:
    """`item new`'s piped body under either storage, or `""` when stdin
    carries none (`_stdin_carries_a_body`)."""
    return _read_body_check_input() if _stdin_carries_a_body() else ""


def _item_new_block_fields(parsed: argparse.Namespace) -> dict[str, object]:
    """Every block field `item new`'s own flags name, keyed as the block
    writes it -- only the flags given."""
    scope = _requested_body_scope(parsed.scope)
    requested: dict[str, object | None] = {
        **{key: getattr(parsed, key) for key, _meaning in ITEM_NEW_PROJECTION_FLAGS},
        "scope": None if scope is None else list(scope),
        "size": parsed.size,
        "whole": _requested_whole_reason(parsed.whole),
    }
    return {key: value for key, value in requested.items() if value is not None}


def _item_new_body(parsed: argparse.Namespace, storage: body.Storage) -> str:
    """The body `item new` stores under either storage (issue #555): the
    piped one, its block given each flag it lacks and refused when a flag
    contradicts it; or, piped without a block, the prose above a block the
    flags build -- a container's own skeleton prose when nothing was piped."""
    piped = _read_item_new_input()
    fields = _item_new_block_fields(parsed)
    if not body.carries_block(piped):
        default_prose = (
            body.CONTAINER_SKELETON_PROSE if parsed.kind == body.ItemKind.CONTAINER else ""
        )
        return body.prose_above_fresh_block(piped if piped.strip() else default_prose, fields)
    shape = body.body_shape_check(piped, storage=storage)
    if shape.verdict is body.BodyShapeVerdict.MALFORMED:
        raise _ItemBodyInvalidError(shape.defects)
    conflicts = body.block_field_conflicts(piped, fields)
    if conflicts:
        raise _ItemBodyInvalidError(conflicts)
    return body.body_with_block_fields(piped, fields)


def _item_new_on_github(parsed: argparse.Namespace, context: RunContext) -> int:
    """`item new` under `storage = "github"` (issue #444): the body it
    stores (`_item_new_body`) passes the same shape check `aco check <n>`
    applies before
    anything else is read or written, so an invalid body creates nothing;
    `--parent` must name an open container or Task (a Task is retyped once
    the twin search passes, `_retype_task_parent`); then the twin search, the only
    guard against a second run: the issue an earlier run created carries
    the same title, so the search names it. Then one issue of the
    organization's type for `--kind`, recorded under `--parent` when given
    (`create_child`, else `create_issue`); a type or relation write that
    fails after the create refuses naming the issue and what is left to do
    by hand, never a re-run. `--origin` binds a state-ref item only: a
    GitHub issue binds to no foreign one."""
    if parsed.origin is not None:
        raise protocol.ClaimUnavailableError(ITEM_NEW_ORIGIN_ON_GITHUB_REFUSAL)
    new_body = _item_new_body(parsed, body.Storage.GITHUB)
    defects = _body_shape_defects(new_body)
    if defects:
        raise _ItemBodyInvalidError(defects)
    client = context.forge_writer
    open_issues = client.list_open_board_issues()
    storage = context.config.storage
    parent = (
        None
        if parsed.parent is None
        else _open_container(open_issues, parsed.parent, storage, ITEM_PARENT_KINDS)
    )
    if not parsed.not_a_twin:
        _refuse_possible_twin(
            client,
            parsed.title,
            _numbered_titles(open_issues),
            parent=parsed.parent,
            storage=storage,
        )
    _retype_task_parent(client, parent, storage)
    kind = body.ItemKind(parsed.kind)
    try:
        number = (
            client.create_issue(title=parsed.title, body=new_body, kind=kind)
            if parsed.parent is None
            else client.create_child(
                parent=parsed.parent, title=parsed.title, body=new_body, kind=kind
            )
        )
    except forge.ForgeIssueTypeNotSetError as error:
        relation = "" if parsed.parent is None else f" and record it under #{parsed.parent}"
        raise _PartialWriteError(
            error, recovery=f"set that type{relation} on the forge by hand"
        ) from error
    except forge.ForgePartialChildCreationError as error:
        raise _PartialWriteError(
            error, recovery="record that sub-issue relation on the forge by hand"
        ) from error
    _print_item_new_result(
        board.item_label(number, body.Storage.GITHUB), number, as_json=parsed.json
    )
    return 0


def _retype_task_parent(
    client: forge.ForgeWriter, parent: board.Issue | None, storage: body.Storage
) -> None:
    """Retype an open Task `--parent` to Container before it gets its first
    child (issue #503), under either storage, and say so on stderr, leaving
    stdout and `--json` the created item's alone; any other parent keeps
    its kind."""
    if parent is None or parent.kind is not body.ItemKind.TASK:
        return
    client.set_item_kind(parent.number, body.ItemKind.CONTAINER)
    label = board.item_label(parent.number, storage)
    print(f"retyped {label} to Container for its first child", file=sys.stderr)


def _item_new_on_state_ref(parsed: argparse.Namespace, context: RunContext) -> int:
    """`item new` under `storage = "state-ref"` (issues #285, #316): the one
    write path for a fresh state-ref item -- `StateRefBoard.compose_item`
    then `create_item`, the same CAS write `cut`'s own `create_child`
    performs, generalized to an optional parent and origin -- so this
    module never grows a second way to create one. `--origin` binds the
    fresh item to a foreign forge issue (`items.parse_origin`'s own grammar,
    refused by `argparse` before this ever runs) without aco governing that
    forge at all. An open Task parent turns Container
    (`_retype_task_parent`) once the item is composed and before it is
    written, so an item the read would refuse retypes nothing. Narrows the
    context's forge to the state-ref board (`_state_ref_board`), since
    `create_item` is not part of the generic `ForgeWriter` port every other
    write command narrows to. The body is `_item_new_body`'s, the piped one
    stored as under github; one left incomplete is still written, each
    missing section named on stderr (issue #555)."""
    client = _state_ref_board(context)
    parent = parsed.parent
    storage = context.config.storage
    new_body = _item_new_body(parsed, storage)
    if parent is not None and client.item_reference(parent).state is forge.ItemState.MISSING:
        raise protocol.ClaimUnavailableError(f"{board.item_label(parent, storage)} does not exist")
    if not parsed.not_a_twin:
        _refuse_possible_twin(
            client, parsed.title, client.open_item_titles(), parent=parsed.parent, storage=storage
        )
    new_item = client.compose_item(
        title=parsed.title,
        body=new_body,
        kind=body.ItemKind(parsed.kind),
        parent=parsed.parent,
        origin=parsed.origin,
    )
    if parent is not None:
        _retype_task_parent(client, client.open_issue(parent), storage)
    item_id = client.create_item(new_item)
    _print_item_new_result(item_id, items.item_number(item_id), as_json=parsed.json)
    for section in body.missing_or_empty_sections(body.parse_body(new_body).contract):
        print(f"{item_id} misses {section}; aco item edit {item_id} fills it", file=sys.stderr)
    return 0


def _print_item_new_result(item_id: str, number: int, *, as_json: bool) -> None:
    if as_json:
        report.emit_json(True, ItemReason.CREATED, item=item_id, number=number)
    else:
        print(item_id)


ITEM_EDIT_GITHUB_REFUSAL = "forge issues are edited on the forge; aco never governs them"


def _cmd_item_edit(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item edit ITEM` (issue #287; `--size`, issue #357; `--whole`,
    issue #399; `--kind`, issue #503): with `--size`, `--whole`, or `--kind`,
    a narrow write of only that one field (`_cmd_item_edit_size`/
    `_cmd_item_edit_whole`/`_cmd_item_edit_kind`, both storages); with none,
    the state-ref item's own body, replaced from
    stdin only -- refused before any write when the piped body carries no
    valid `aco` block (`body --check`'s own sentences,
    `_body_shape_defects`). The CAS `expected` oid is this process's own
    already-read snapshot (`StateRefBoard.update_item_body`'s
    `current.oid`, set once at `_state_ref_forge` construction): a second
    process writing from that same snapshot refuses with issue #279's own
    sentence, never merged, never silently overwritten. `parent`, `state`,
    `origin`, `created_at`, and `closed_at` stay this item's own stored
    values regardless of what the piped body's `[record]` names for them --
    `update_item_body`'s own owner rule; `updated_at` always moves to now;
    `title`, `labels`, `blocked_by` come from the piped record when it
    carries one -- except a malformed item (ITEM-39), which takes the piped
    record whole and refuses a body without one; a delivered `blocked_by`
    naming one blocker twice, or a blocker the item does not already carry
    that names no item, a malformed item or the item itself, refuses before
    any write (ITEM-43, ITEM-44). Refuses under
    `storage = "github"`: forge issues are edited on the forge, never
    governed by aco. Narrows the context's forge to the state-ref board,
    as `item new`'s state-ref path does. A malformed piped body reports through
    the shared envelope as `body_invalid`, with `body --check`'s own
    `defects`; every other refusal is `precondition_failed` (issue #425)."""
    if parsed.size is not None:
        return _cmd_item_edit_size(parsed, context)
    if parsed.whole is not None:
        return _cmd_item_edit_whole(parsed, context)
    if parsed.kind is not None:
        return _cmd_item_edit_kind(parsed, context)
    as_json = parsed.json
    try:
        if context.config.storage is not body.Storage.STATE_REF:
            raise protocol.ClaimUnavailableError(ITEM_EDIT_GITHUB_REFUSAL)
        new_body = _read_item_edit_body(parsed.item)
        defects = _body_shape_defects(new_body, storage=body.Storage.STATE_REF)
        if defects:
            return _refuse_item_body_invalid(defects, as_json=as_json)
        client = _state_ref_board(context)
        number = parsed.item
        if not client.holds(number):
            raise protocol.ClaimUnavailableError(
                board_read.missing_item_refusal(number, client, context.config.storage)
            )
        client.update_item_body(number, new_body)
        _print_item_edit_result(
            items.format_item_id(number), number, client.item_oid(number), as_json=as_json
        )
        return 0
    except protocol.ClaimError as error:
        return report.refuse(ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _read_item_edit_body(number: int) -> str:
    """`item edit`'s new body, read only when stdin carries one
    (`_stdin_carries_a_body`, issue #572): an idle socket, a terminal,
    `/dev/null` or a closed stdin refuses at once, naming the redirect,
    rather than hanging on a read or replacing the body with nothing."""
    if not _stdin_carries_a_body():
        item_id = items.format_item_id(number)
        raise protocol.ClaimUnavailableError(
            f"item edit {item_id} needs the new body on stdin: aco item edit {item_id} < body.md"
        )
    return _read_body_check_input()


ITEM_EDIT_SIZE_COMMAND = "item edit --size"


def _cmd_item_edit_size(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item edit ITEM --size S|M|L` (issue #357): the one item-size
    write, over the generic `ForgeWriter.update_item_body` both `github`
    and `state-ref` already implement -- unlike the whole-body `item edit`
    above, this works under `storage = "github"` too, since it patches only
    the block's own top-level `size` key (never `[record]`, a
    `state-ref`-only table BODY-15 refuses under `github`) and leaves every
    other byte untouched. Every refusal reports through the shared envelope
    as `precondition_failed` (issue #425)."""
    as_json = parsed.json
    try:
        _refuse_a_body_on_stdin(ITEM_EDIT_SIZE_COMMAND)
        client = context.forge_writer
        _require_update_item_body(client, command=ITEM_EDIT_SIZE_COMMAND)
        number = parsed.item
        storage = context.config.storage
        current_body = _item_body_or_refuse(
            client, number, command=ITEM_EDIT_SIZE_COMMAND, storage=storage
        )
        located = _located_block_or_refuse(
            number, current_body, command=ITEM_EDIT_SIZE_COMMAND, storage=storage
        )
        new_data = {**located.data, "size": parsed.size}
        outcome = _write_block_data(client, number, current_body, located, new_data)
        _print_item_edit_size_result(number, parsed.size, storage, outcome, as_json=as_json)
        return 0
    except protocol.ClaimError as error:
        return report.refuse(ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _write_block_data(
    client: forge.ForgeWriter,
    number: int,
    current_body: str,
    located: body.LocatedBlock,
    new_data: dict[str, object],
) -> ItemReason:
    """Writes `new_data` as item `number`'s block, every other byte
    untouched, or nothing at all when the block already carries it (issue
    #572), so a repeated narrow edit leaves no empty write behind."""
    if new_data == located.data:
        return ItemReason.UNCHANGED
    client.update_item_body(number, body.replace_block(current_body, located, new_data))
    return ItemReason.EDITED


def _narrow_edit_word(outcome: ItemReason) -> str:
    """The first word a narrow `item edit` prints: `EDITED` or `UNCHANGED`."""
    return outcome.value.upper()


def _print_item_edit_size_result(
    number: int, size: str, storage: body.Storage, outcome: ItemReason, *, as_json: bool
) -> None:
    if as_json:
        report.emit_json(True, outcome, item=number, size=size)
    else:
        print(f"{_narrow_edit_word(outcome)} {board.item_label(number, storage)} size={size}")


ITEM_EDIT_WHOLE_COMMAND = "item edit --whole"


def _cmd_item_edit_whole(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item edit ITEM --whole REASON` (issue #399): the one item-whole
    write, mirroring `_cmd_item_edit_size` over the same generic
    `ForgeWriter.update_item_body` -- works under `storage = "github"` too,
    since it patches only the block's own top-level `whole` key and leaves
    every other byte untouched. Every refusal reports through the shared
    envelope as `precondition_failed` (issue #425)."""
    as_json = parsed.json
    try:
        _refuse_a_body_on_stdin(ITEM_EDIT_WHOLE_COMMAND)
        client = context.forge_writer
        _require_update_item_body(client, command=ITEM_EDIT_WHOLE_COMMAND)
        number = parsed.item
        storage = context.config.storage
        current_body = _item_body_or_refuse(
            client, number, command=ITEM_EDIT_WHOLE_COMMAND, storage=storage
        )
        located = _located_block_or_refuse(
            number, current_body, command=ITEM_EDIT_WHOLE_COMMAND, storage=storage
        )
        reason = protocol.outbound_text(parsed.whole, _WHOLE_REASON_LABEL, maximum=512)
        new_data = {**located.data, "whole": reason}
        outcome = _write_block_data(client, number, current_body, located, new_data)
        _print_item_edit_whole_result(number, reason, storage, outcome, as_json=as_json)
        return 0
    except protocol.ClaimError as error:
        return report.refuse(ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _print_item_edit_whole_result(
    number: int, reason: str, storage: body.Storage, outcome: ItemReason, *, as_json: bool
) -> None:
    if as_json:
        report.emit_json(True, outcome, item=number, whole=reason)
    else:
        print(f"{_narrow_edit_word(outcome)} {board.item_label(number, storage)} whole={reason}")


ITEM_EDIT_KIND_COMMAND = "item edit --kind"


def _cmd_item_edit_kind(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item edit ITEM --kind task|container` (issue #503): the one
    retype a person runs, over the `ForgeWriter.set_item_kind` both storages
    implement -- the repair `next` names for a nested container with one
    uncut row. Reads no stdin, and refuses a body piped or redirected there
    before any write, so it is never silently dropped.
    A container with an open child stays one, since a Task never has
    children to claim through. Every refusal reports through the shared
    envelope as `precondition_failed`."""
    as_json = parsed.json
    try:
        _refuse_a_body_on_stdin(ITEM_EDIT_KIND_COMMAND)
        client = context.forge_writer
        storage = context.config.storage
        number = parsed.item
        kind = body.ItemKind(parsed.kind)
        # Under state-ref the retype reads its item alone (ITEM-37/38, issue
        # #536); the forge answers only through its open-issue list.
        if isinstance(client, state_board.StateRefBoard):
            target = client.open_issue(number)
        else:
            target = next(
                (issue for issue in client.list_open_board_issues() if issue.number == number),
                None,
            )
        label = board.item_label(number, storage)
        if target is None:
            raise protocol.ClaimUnavailableError(f"{label} is not an open item")
        # The retype decides with the item and its children alone (issue
        # #536), and holds the store it read through its write, so a child
        # written since refuses it rather than being guessed past (#447).
        if isinstance(client, state_board.StateRefBoard):
            _refuse_an_unreadable_relative(client, number, with_parent=False)
            client.hold_items()
        if kind is body.ItemKind.TASK and target.has_open_child:
            raise protocol.ClaimUnavailableError(
                f"{label} has an open child; a container with open children stays a container"
            )
        outcome = ItemReason.UNCHANGED if target.kind is kind else ItemReason.EDITED
        if outcome is ItemReason.EDITED:
            client.set_item_kind(number, kind)
        _print_item_edit_kind_result(number, kind, storage, outcome, as_json=as_json)
        return 0
    except protocol.ClaimError as error:
        return report.refuse(ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _print_item_edit_kind_result(
    number: int, kind: body.ItemKind, storage: body.Storage, outcome: ItemReason, *, as_json: bool
) -> None:
    label = board.item_label(number, storage)
    if as_json:
        report.emit_json(True, outcome, item=label, number=number, kind=kind.value)
    else:
        print(f"{_narrow_edit_word(outcome)} {label} kind={kind.value}")


def _print_item_edit_result(
    item_id: str, number: int, oid: protocol.ObjectId, *, as_json: bool
) -> None:
    if as_json:
        report.emit_json(True, ItemReason.EDITED, item=item_id, number=number, oid=oid)
    else:
        print(f"EDITED {item_id}")


ITEM_CLOSE_GITHUB_REFUSAL = "the forge closes its issues; aco never governs them"


def _cmd_item_close(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item close ITEM` (issue #289): the state-ref item's own record,
    closed -- `state` to `CLOSED`, `closed_at`/`updated_at` to now, the item
    file and every other byte untouched (`StateRefBoard.close_item`'s one
    CAS write over this process's own already-read oid, extending #287's
    record-owner rule by one field rather than composing a record here).
    Refuses under `storage = "github"` by name -- the forge closes its own
    issues, aco never governs them -- and, once the state ref is readable,
    refuses a live claim on the item before every item-state refusal
    (missing, malformed, already closed), then again on every write
    attempt, retries included (`protocol.ItemCloseIntent`, issue #459), so
    a concurrent claim cannot slip past the first check.
    Existence is checked through the ordinary
    `item_reference` read before `close_item` is ever called, so an unknown
    id gets this command's own "does not exist" sentence rather than
    `close_item`'s internal `_by_number` lookup failing with the wrong
    shape; `close_item` itself refuses a second close on an already-closed
    item, naming its date. An unreadable item refuses at its own read; an
    unreadable parent or child, or a parent `items/` lacks, refuses before
    the write (`_refuse_an_unreadable_relative`); any other malformed item only goes
    unfreed, and one failing the `freed:` read after the write turns that line
    into a hint (issue #541). Prints one line, `CLOSED aco-xxxxxx` (`--json`:
    `{"item", "number", "closed_at", "parent_closable"}`), then `release
    --merged`'s own `freed:` line -- open items whose only open local
    blocker was this one (`board.freed_item_numbers`, issue #256; nothing new) --
    and, when this close was its parent's last open child, `release
    --merged`'s own parent hint (issue #348). Every refusal reports through
    the shared envelope as `precondition_failed` (issue #425)."""
    as_json = parsed.json
    try:
        if context.config.storage is not body.Storage.STATE_REF:
            raise protocol.ClaimUnavailableError(ITEM_CLOSE_GITHUB_REFUSAL)
        number = parsed.item
        observed = context.observation
        protocol.require_state_ref(observed)
        protocol.require_no_live_claim(observed, protocol.IssueIdentity(number))
        client = _state_ref_board(context)
        if client.item_reference(number).state is forge.ItemState.MISSING:
            raise protocol.ClaimUnavailableError(
                board_read.missing_item_refusal(number, client, context.config.storage)
            )
        _refuse_an_unreadable_relative(client, number, with_parent=True)
        closed_at = client.close_item(number)
        result = _ItemCloseResult(
            item_id=items.format_item_id(number),
            number=number,
            closed_at=closed_at,
            freed=board_read.board_read_after_write(lambda: _item_close_freed(client, number)),
            parent_closable=_closable_parent_of_a_closed_item(client, number),
        )
        _print_item_close_result(result, as_json=as_json)
        return 0
    except protocol.ClaimError as error:
        named = board.named_refusal(error, body.Storage.STATE_REF)
        return report.refuse(ItemReason.PRECONDITION_FAILED, named, as_json=as_json)


def _refuse_an_unreadable_relative(
    client: state_board.StateRefBoard, number: int, *, with_parent: bool
) -> None:
    """Refuses by the lowest id while one of `number`'s children -- the same
    children the board counts, an unreadable item that may be one included
    (issue #550, ITEM-54) -- or, `with_parent`, its parent does not read
    (issue #536, ITEM-53): a single-item write decides with those alone, so
    each is read through the one narrow `item_references` read, and an
    unrelated malformed item never blocks the write. `parent_number` refuses
    a parent `items/` lacks (PIN-16) here too, before the write rather than
    after it."""
    relatives = {child.number for child in client.list_children(number)}
    parent = client.parent_number(number) if with_parent else None
    if parent is not None:
        relatives.add(parent)
    client.item_references(sorted(relatives))


def _closable_parent_of_a_closed_item(
    client: state_board.StateRefBoard, closed_item: int
) -> int | None:
    """`board_read.parent_closable_number`'s parent hint, withheld while the parent's
    own `item close` would refuse by an unreadable relative (issue #536,
    ITEM-54): the hint recommends that close, so it asks the very check
    that close runs rather than contradicting it."""
    closable = board_read.parent_closable_number(client, closed_item, body.Storage.STATE_REF)
    if closable is None:
        return None
    try:
        _refuse_an_unreadable_relative(client, closable, with_parent=True)
    except protocol.MalformedStateTreeError:
        return None
    return closable


def _item_close_freed(client: forge.ForgeReader, number: int) -> tuple[int, ...]:
    """Every open item `number`'s own close just freed -- issue #256's own
    derivation, reused rather than reinvented, the same base-issues-plus-
    dependency-fetch wave `cmd_release._release_landing` runs for a merged release, read
    fresh off `client`'s own already-closed view so `number` itself never
    appears among its own candidates."""
    issues = client.list_open_board_issues()
    candidates = tuple(issue.number for issue in issues if issue.blocked_by_count > 0)
    dependencies = board_read.validated_dependencies(
        issues, board_read.fetch_dependencies(client, candidates)
    )
    landed = board.IssueReference(client.repository.path, number)
    return board.freed_item_numbers(dependencies, landed)


@dataclass(frozen=True)
class _ItemCloseResult:
    """Everything `_print_item_close_result` needs for one `item close`
    (issue #348), bundled so the printer itself takes one argument instead
    of PLR0913's five-scalar ceiling. `freed` is the freed numbers, or
    the hint that replaced them when that read refused (issue #541)."""

    item_id: str
    number: int
    closed_at: str
    freed: tuple[int, ...] | str
    parent_closable: int | None


def _print_item_close_result(result: _ItemCloseResult, *, as_json: bool) -> None:
    if as_json:
        report.emit_json(
            True,
            ItemReason.CLOSED,
            item=result.item_id,
            number=result.number,
            closed_at=result.closed_at,
            parent_closable=result.parent_closable,
        )
        if isinstance(result.freed, str):
            board_read.print_board_read_hint(result.freed, as_json=True)
        return
    print(f"CLOSED {result.item_id}")
    if isinstance(result.freed, str):
        board_read.print_board_read_hint(result.freed, as_json=False)
    else:
        # `item close` only ever runs under `storage = "state-ref"`
        # (`_cmd_item_close`'s own refusal otherwise), so `freed:`'s own id
        # chooser is fixed here rather than threaded as a further field.
        print(board.release_freed_line(result.freed, body.Storage.STATE_REF))
    parent_line = board.parent_closable_line(result.parent_closable, body.Storage.STATE_REF)
    if parent_line is not None:
        print(parent_line)


def _item_state_text(state: forge.ItemState) -> str:
    return "open" if state is forge.ItemState.OPEN else "closed"


def _item_parent_id(parent: int | None) -> str | None:
    return None if parent is None else items.format_item_id(parent)


def _item_header(number: int, reference: forge.ItemReference, parent: int | None) -> str:
    """`item show`'s one header line: id, number, state, parent, and origin
    -- the same shape regardless of which forge answered the reads, since an
    id (`items.format_item_id`) is a pure encoding of `number`, never a
    per-adapter fact. `reference.origin` (issue #316) stays `None` for a
    GitHub-stored item, so this prints `origin none` there exactly like an
    unset parent prints `parent none`."""
    return (
        f"{items.format_item_id(number)} · #{number} · "
        f"{_item_state_text(reference.state)} · parent {_item_parent_id(parent) or 'none'} · "
        f"origin {reference.origin or 'none'}"
    )


def _cmd_item_show(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item show` (issue #285): the stored body behind one header
    line, its display controls escaped in text (issue #544), byte-exact
    under `--json` -- read through the ordinary forge port, so it works
    identically under `storage = "github"` (the forge's own issue body) and
    `storage = "state-ref"` (the item file's own body); closing an item
    never deletes it, so a closed item is shown exactly like an open one.
    A missing id -- or a forge that fails either read this header needs --
    reports through the shared envelope as `precondition_failed` (issue
    #425)."""
    as_json = parsed.json
    try:
        client = context.forge
        number = parsed.item
        reference = client.item_reference(number)
        if reference.state is forge.ItemState.MISSING:
            storage = context.config.storage
            raise protocol.ClaimUnavailableError(
                board_read.missing_item_refusal(number, client, storage)
            )
        parent = client.parent_number(number)
    except protocol.ClaimError as error:
        return report.refuse(ItemReason.PRECONDITION_FAILED, error, as_json=as_json)
    body = reference.body or ""
    if as_json:
        report.emit_json(
            True,
            ItemReason.SHOWN,
            item=items.format_item_id(number),
            number=number,
            state=_item_state_text(reference.state),
            parent=_item_parent_id(parent),
            origin=reference.origin,
            body=body,
        )
        return 0
    print(_item_header(number, reference, parent))
    print(board.terminal_block(body), end="")
    return 0


def _claim_intent_from_request(
    request: protocol.ClaimRequest, operation_id: str, item_pin: protocol.ItemPin | None
) -> protocol.ClaimIntent:
    """`_request`'s validated `ClaimRequest`, converted to the store's own
    intent (issue #176, §1: `ClaimRequest` stays the CLI-facing input,
    `ClaimIntent` is what `apply` actually consumes), pinned to `item_pin`
    when the claim's checks judged a state-ref item open (issue #496)."""
    resource_name = None
    resource_value = None
    if request.resource is not None:
        resource_name = request.resource
        resource_value = request.resource_value
    return protocol.ClaimIntent(
        identity=request.identity,
        agent=request.agent,
        role=request.role,
        base=protocol.ObjectId(request.base),
        branch=request.branch,
        scope=request.scope,
        claim_id=protocol.ClaimId(request.claim_id),
        operation_id=operation_id,
        whole_reason=request.whole_reason,
        resource_name=resource_name,
        resource_value=resource_value,
        item_pin=item_pin,
    )


def _claimed_item_pin(
    identity: protocol.ClaimIdentity, observed: protocol.ClaimState, storage: body.Storage
) -> protocol.ItemPin | None:
    """The state-ref item a claim's checks judged open, pinned to its blob in
    `observed`, the observation those checks read (issue #496). `None` for a
    lane, and under `github`, whose forge holds the item's state while the
    ledger holds no fact of it; `None` too for an item `observed` lacks,
    which the checks already refuse as missing."""
    if storage is not body.Storage.STATE_REF or not isinstance(identity, protocol.IssueIdentity):
        return None
    item_id = items.format_item_id(identity.issue)
    oid = observed.items.get(item_id)
    return None if oid is None else protocol.ItemPin(item_id, oid)


def _matching_store_claim(
    observed: protocol.ClaimState, request: protocol.ClaimRequest
) -> protocol.ActiveClaim | None:
    """The live store claim an interrupted, replayed `claim` invocation may
    reuse (criterion 2): same identity, agent, role, branch, scope, *and*
    claim id -- `apply` itself only replays on an exact claim-id match
    (§1 "Retry of an interrupted identical request"), so a CLI-level replay
    check that skips this slice's dispatch rules must use the same test, not
    the ledger's looser field-only match. Issueless lanes keep today's
    one-claim-per-branch contract; only a numbered item gets replay
    detection at all.
    """
    if not isinstance(request.identity, protocol.IssueIdentity):
        return None
    existing = observed.claims.get(protocol.claim_key(request.identity, request.branch))
    if (
        existing is not None
        and existing.claim_id == request.claim_id
        and existing.agent == request.agent
        and existing.role == request.role
        and existing.branch == request.branch
        and existing.scope == request.scope
    ):
        return existing
    return None


@dataclass(frozen=True)
class _RescopePaths:
    """`rescope`'s own `--add`/`--drop` entries, each made absolute (issue
    #554): an absolute entry as given, a relative one joined to the toplevel
    of the checkout the command runs in -- the repository-relative form an
    item body's own `scope` list prints, so an entry copied from it works as
    typed from anywhere inside that checkout."""

    add: tuple[str, ...]
    drop: tuple[str, ...]

    def named(self) -> tuple[tuple[str, str], ...]:
        """Every entry beside the flag that named it, `--add` first."""
        return (
            *(("--add", path) for path in self.add),
            *(("--drop", path) for path in self.drop),
        )


def _rescope_paths(add: list[str] | None, drop: list[str] | None) -> _RescopePaths:
    return _RescopePaths(
        add=_absolute_rescope_entries(add, flag="--add"),
        drop=_absolute_rescope_entries(drop, flag="--drop"),
    )


def _absolute_rescope_entries(raw_paths: list[str] | None, *, flag: str) -> tuple[str, ...]:
    return tuple(
        raw_path if Path(raw_path).is_absolute() else _joined_to_run_checkout(raw_path, flag=flag)
        for raw_path in raw_paths or ()
    )


def _joined_to_run_checkout(raw_path: str, *, flag: str) -> str:
    """A relative entry joined to the run checkout's toplevel. One that
    climbs out of that checkout refuses here (RESC-05), naming the entry as
    typed: the joined path would otherwise locate whichever checkout it
    lands in and be judged there instead."""
    toplevel = _run_checkout_toplevel(raw_path, flag=flag)
    joined = toplevel / raw_path
    if checkout.checkout_relative(joined, toplevel=toplevel) is None:
        raise _RescopeInvalidUsageError(_outside_checkout_reason(flag, raw_path, toplevel))
    return str(joined)


def _run_checkout_toplevel(raw_path: str, *, flag: str) -> Path:
    """The toplevel a relative `raw_path` is read against: the checkout the
    command runs in. Outside every repository there is none, and the
    refusal names the entry and how to give it instead."""
    cwd = Path.cwd()
    run_checkout = checkout.resolve_named_path_checkout(cwd)
    if run_checkout is None:
        raise _RescopeInvalidUsageError(
            f"{flag} path {raw_path!r} is relative and {cwd} is "
            f"{checkout.NOT_IN_A_REPOSITORY_REASON}; pass it as an absolute path"
        )
    return run_checkout.toplevel


def _rescope_scope_entries(
    absolute_paths: tuple[str, ...], *, toplevel: Path, flag: str
) -> tuple[str, ...]:
    """One `--add`/`--drop` list, already absolute (`_RescopePaths`),
    canonicalized to repository-relative scope entries against `toplevel`.
    A path no claim could ever cover refuses with the sentence `protect`
    denies it with (issue #483)."""
    if not absolute_paths:
        return ()
    canonical: list[str] = []
    for raw_path in absolute_paths:
        unscopable = checkout.unscopable_path_reason(raw_path, toplevel=toplevel)
        if unscopable is not None:
            raise _RescopeInvalidUsageError(unscopable)
        relative = checkout.relative_scope_entry(raw_path, toplevel=toplevel)
        if relative is None:
            raise _RescopeInvalidUsageError(_outside_checkout_reason(flag, raw_path, toplevel))
        canonical.append(relative)
    return protocol.valid_scope(canonical)


def _outside_checkout_reason(flag: str, path: str, toplevel: Path) -> str:
    return f"{flag} path {path!r} is outside the resolved checkout {toplevel}"


def _rescope_checkout(paths: _RescopePaths) -> checkout.PathCheckout:
    """`rescope`'s checkout, resolved from its first entry whenever one
    names a location (issue #314), else from the process's own cwd, read
    through the same path-based resolver `protect` uses. A checkout with no
    commit yet denies here too (gate G3), the same precondition `protect`
    enforces on its own resolved checkout. The path resolves exactly as
    `protect` resolves a payload path -- a checkout root as its own
    checkout, a file in a directory not created yet from its nearest
    existing ancestor (issues #474, #483)."""
    named = paths.named()
    location = Path(named[0][1]) if named else Path.cwd()
    path_checkout = checkout.resolve_named_path_checkout(location)
    if path_checkout is None:
        raise protocol.ClaimUnavailableError(_outside_every_repository_reason(named))
    if not path_checkout.has_commit:
        raise protocol.ClaimUnavailableError(checkout.NO_COMMIT_CHECKOUT_REASON)
    return path_checkout


def _outside_every_repository_reason(named: tuple[tuple[str, str], ...]) -> str:
    """PROT-10's own sentence, naming the entry that located no checkout
    whenever an entry did the locating (issue #554)."""
    if not named:
        return checkout.NOT_IN_A_REPOSITORY_REASON
    flag, path = named[0]
    return f"{flag} path {path!r} is {checkout.NOT_IN_A_REPOSITORY_REASON}"


def _rescope_command(
    parsed: argparse.Namespace,
    paths: _RescopePaths,
    path_checkout: checkout.PathCheckout,
    checkout_context: RunContext,
) -> protocol.RescopeRequest:
    """The rescope `parsed` asks for in `path_checkout`, judged against the
    resolved checkout's own recorded default branch (issue #490)."""
    branch = path_checkout.branch
    if not branch:
        raise protocol.ClaimUnavailableError(
            "rescope requires a non-empty current branch; "
            "check out the claim branch, or pass an issue number"
        )
    checkout.refuse_shared_checkout(
        path_checkout,
        default_branch=checkout_context.recorded_default_branch,
        canonical_remote=checkout_context.canonical_remote,
        repair=checkout.WorktreeRepair.RETURN_TO_CLAIM,
    )
    identity = protocol.resolved_identity(protocol.optional_issue_number(parsed.issue), branch)
    return protocol.RescopeRequest(
        identity=identity,
        agent=parsed.agent,
        add=_rescope_scope_entries(paths.add, toplevel=path_checkout.toplevel, flag="--add"),
        drop=_rescope_scope_entries(paths.drop, toplevel=path_checkout.toplevel, flag="--drop"),
        claim_id=parsed.claim_id,
        branch=branch,
        whole_reason=_optional_whole_reason(parsed),
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
    git failure that keeps either read from answering (issue #390 finding
    9b) raises instead of being read the same way as an absent ref."""
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
        f"{claim.agent} ({claim.role}) branch={claim.branch} base={claim.base}"
        f"{board.claim_age_suffix(opened_at, observed_at)}"
    )
    for path in claim.scope:
        print(f"  {path}")
    if claim.whole_reason is not None:
        print(f"  whole: {claim.whole_reason}")
    shared = _lane_shared_line(lane_shared)
    if shared is not None:
        print(f"  {shared}")


def _print_brief_step_rules(step_rules: board.BriefStepRules) -> None:
    """`RULES` and `CHECKS` (issue #324): two more sections after the four
    `_print_brief` always prints, only under `--step` -- the repository's own
    `.aco/brief.toml` entries for that lane step, one per line,
    each as `terminal_text` shows it so no entry can break into a forged
    line or section (issue #548)."""
    print()
    print("RULES")
    for rule in step_rules.rules:
        print(board.terminal_text(rule))
    print()
    print("CHECKS")
    for check in step_rules.checks:
        print(board.terminal_text(check))


@dataclass(frozen=True)
class _BriefComposition:
    """One `aco brief`'s full composed reads (issue #324): the four sections
    `_print_brief` always prints, plus, only under `--step`, the repository's
    own rules and checks -- gathered once so the text and `--json` renderers
    print the same reads with no chance to drift apart."""

    body: str
    live: _BriefClaim | None
    observed_at: datetime
    tip: str | None
    touched: tuple[str, ...]
    step_rules: board.BriefStepRules | None
    lane_shared: LaneSharedReading


def _print_brief(composition: _BriefComposition) -> None:
    print(board.terminal_block(composition.body))
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


STATE_REF_ITEM_PAST_THE_ID_SPACE = "{number} " + board.NAMES_NO_ITEM


class PreDispatchReason(StrEnum):
    """The one `reason` every refusal raised before the chosen command starts
    reports under `--json` (issue #425): agent identity resolution, and
    `release`'s own branch and override checks, refuse before any command
    runs, so `_dispatch` owns their envelope here instead of each command
    carrying a second `precondition_failed` member for a refusal it never
    sees itself. `invalid_usage` is the parser's own refusal (issue #432),
    raised before any command is even chosen, and PIN-31's state-ref item
    number past the id space (issue #467), an argument no command can use."""

    INVALID_USAGE = "invalid_usage"
    PRECONDITION_FAILED = "precondition_failed"


def _refuse_usage(error: _UsageError, *, as_json: bool) -> int:
    """The argument parser's own refusal, in the shape this invocation asked
    for (issue #432): without `--json` argparse's own usage block and
    sentence, printed by the implementation `_UsageErrorParser` overrode, so
    the bytes stay exactly what they were; with `--json` the shared envelope
    instead, `invalid_usage`, argparse's own sentence as `message`."""
    if not as_json:
        argparse.ArgumentParser.error(error.parser, str(error))
    return report.refuse(PreDispatchReason.INVALID_USAGE, error, as_json=True)


class BriefReason(StrEnum):
    """`aco brief`'s own `--json` `reason` vocabulary (`specs/brief.spec.md`,
    issue #396): `composed` the only success. `invalid_item` names no
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
        "age": board.claim_age_fields(live.opened_at, observed_at)[0],
        **_lane_shared_json(lane_shared),
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
    report.emit_json(True, BriefReason.COMPOSED, **payload)
    return 0


def _brief_config(toplevel: Path) -> board.BriefConfig | None:
    """`.aco/brief.toml`'s own content, read only when the file is
    actually tracked by git (issue #324) -- the same tracked-file
    requirement `board_config` enforces for `board.toml`'s storage pin, so
    an ignored or not-yet-added file never quietly answers for the
    repository. `None` either when it is untracked or when `load_brief_config`
    finds no such file at all."""
    if not checkout.path_is_tracked(board.BRIEF_CONFIG_PATH.as_posix(), directory=toplevel):
        return None
    return board.load_brief_config(toplevel / board.BRIEF_CONFIG_PATH)


def _brief_step_rules_or_refusal(
    step: str | None, context: RunContext
) -> board.BriefStepRules | None:
    """`--step`'s own rules and checks, or `None` when the brief carries no
    `--step` at all -- the one branch that must stay untouched by
    `.aco/brief.toml`'s presence or content (BRIEF-16)."""
    if step is None:
        return None
    config = _brief_config(context.toplevel)
    if config is None:
        raise protocol.ClaimError(f"no {board.BRIEF_CONFIG_PATH} in the repository")
    return config.for_step(board.BriefStep(step))


def _cmd_brief(parsed: argparse.Namespace, context: RunContext) -> int:
    """Compose one item's own reads into the one dispatch brief a lane step's
    body otherwise gets assembled from by hand (AGENTS.md "the next brief
    names the body, the lane tip ... and the commands"): the item's body from
    the forge, its live claim from the store, the claim branch's current tip,
    and the files the lane itself changes since its merge base with trunk.
    Never a new data source, and never a write. Every refusal on this path --
    BRIEF-07, BRIEF-09's PIN-04/PIN-05, BRIEF-15, BRIEF-18's lane-tip read and
    trunk diff, BRIEF-20's trunk read, and the item read itself, which is a
    forge call like any other (issue #432) -- reports through `report.refuse` under
    this command's own vocabulary."""
    as_json = parsed.json
    try:
        return _brief_report(parsed, context)
    except RepoMeaninglessUnderStateRefError as error:
        return report.refuse(BriefReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(BriefReason.UNAVAILABLE, error, as_json=as_json)


def _brief_report(parsed: argparse.Namespace, context: RunContext) -> int:
    """`brief`'s own composition and printing, every refusal raised by name
    for `_cmd_brief` to report."""
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


def _cmd_status(parsed: argparse.Namespace, context: RunContext) -> int:
    """`status` reads live claims from the store directly (issue #176),
    dispatched straight from `main` -- it never needs `_dispatch`'s ledger
    resolution (a cut-over repository may have no ledger issue left at all).
    It is forge-free (issue #245): `--repo` is meaningless here and unused.
    Every `protocol.ClaimError` `_status_read` can raise -- a rewritten or
    malformed state ref -- reports through `report.refuse` as `unavailable` (issue
    #406): `status` names no `invalid_usage` of its own (see `StatusReason`).
    """
    try:
        return _status_read(parsed, context)
    except protocol.ClaimError as error:
        return report.refuse(StatusReason.UNAVAILABLE, error, as_json=parsed.json)


def _status_read(parsed: argparse.Namespace, context: RunContext) -> int:
    worktree = context.toplevel
    state = context.observation
    claims = tuple(state.claims.values())
    lane_shared = trunk_lane_shared_reading(context.configured_canonical_remote, context.toplevel)
    if parsed.path is not None:
        # `--path` prints no age, so it never reads a claim's ancestry: a
        # lineage break in one unrelated claim must not stop this answer
        # (README "status --path").
        if parsed.json:
            return _status_path_json(claims, parsed.path, lane_shared)
        _status_path(claims, parsed.path, context.config.storage, lane_shared)
        return 0
    ages = board_read.claim_ages(worktree, state)
    issue = protocol.optional_issue_number(parsed.issue)
    if parsed.json:
        return _status_json(claims, issue, ages, state.tip, lane_shared)
    return _status(claims, issue, ages, context.config.storage, lane_shared)


def _next_action_container_number(action: board.NextAction | None) -> int | None:
    """The container `action` targets, when it targets one -- excluded from
    `SKIPPED` below since a container is always non-actionable itself."""
    if action is None or isinstance(action, board.WorkItemAction):
        return None
    return action.container.number


def _cmd_next(parsed: argparse.Namespace, context: RunContext) -> int:
    as_json = parsed.json
    try:
        observed = board_read.observed_board(context)
        storage = context.config.storage
        projected = observed.board
        action = board.next_action(projected)
        site = _pull_site(action, context)
    except RepoMeaninglessUnderStateRefError as error:
        return report.refuse(NextReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(NextReason.UNAVAILABLE, error, as_json=as_json)
    close = board.zero_cost_closes(projected)
    waiting = board.waiting_on_operator(projected)
    already_named = {_next_action_container_number(action), *close, *waiting}
    skipped = tuple(item for item in _unworkable(projected) if item.number not in already_named)
    next_report = _NextReport(
        action=action,
        skipped=skipped,
        recovery=projected.recovery,
        parallel=board.parallel_set(projected, observed.live_claims, action),
        close=close,
        waiting=waiting,
        site=site,
    )
    if as_json:
        _next_json(next_report, storage)
    else:
        _next(next_report, storage)
    return 0 if action is not None else 3


class _RescopeInvalidUsageError(protocol.ClaimError):
    """A rescope `--add`/`--drop` value itself is malformed or contradictory
    -- relative, outside the checkout, a comma-bearing entry matching no
    versioned file, or a combination `protocol.combined_scope` refuses
    (issue #406) -- named so `--json` can choose `invalid_usage` over the
    broad `unavailable` every checkout- or store-level refusal falls to."""


class _RescopePreconditionError(protocol.ClaimError):
    """The rescope cannot proceed given this claim's own current state: no
    live claim on the target identity/branch, a different agent than the
    one holding it, or a scope too wide for the width gate without
    `--whole` (issue #406) -- named so `--json` can choose
    `precondition_failed`."""


RESCOPE_COMMAND = "rescope"


@dataclass(frozen=True)
class _RescopedItemBody:
    """The item body a rescope keeps in step with its claim (issue #554):
    the body as read, its located `aco` block, and the `whole`
    reason the block names."""

    number: int
    text: str
    located: body.LocatedBlock
    whole: str | None


def _rescoped_item_body(
    context: RunContext, identity: protocol.ClaimIdentity
) -> _RescopedItemBody | None:
    """The claimed item's own body, read before any write so an item whose
    body cannot take the new scope refuses with nothing changed; `None` for
    a lane claim, which names no item."""
    if not isinstance(identity, protocol.IssueIdentity):
        return None
    client = context.forge_writer
    storage = context.config.storage
    number = identity.issue
    try:
        _require_update_item_body(client, command=RESCOPE_COMMAND)
        text = _item_body_or_refuse(client, number, command=RESCOPE_COMMAND, storage=storage)
        located = _located_block_or_refuse(number, text, command=RESCOPE_COMMAND, storage=storage)
    except protocol.ClaimError as error:
        raise _RescopePreconditionError(str(error)) from error
    whole = body.parse_body(text, storage=storage).whole
    return _RescopedItemBody(number=number, text=text, located=located, whole=whole)


def _write_rescoped_body(
    context: RunContext, item: _RescopedItemBody, scope: tuple[str, ...], whole: str | None
) -> None:
    """The body's own `scope` set to the claim's new one, and `--whole`
    written beside it when the call names one."""
    new_data: dict[str, object] = {**item.located.data, "scope": list(scope)}
    if whole is not None:
        new_data["whole"] = whole
    context.forge_writer.update_item_body(
        item.number, body.replace_block(item.text, item.located, new_data)
    )


def _rescope_item_and_claim(
    context: RunContext,
    subject: store.ClaimTransitionSubject,
    intent: protocol.RescopeIntent,
    item: _RescopedItemBody,
    whole: str | None,
) -> protocol.ClaimState:
    """The body first, then the claim's own transition (issue #554): a
    refused body write leaves the claim as it stood, and a claim write that
    fails after it says the body already names the new scope and how to
    bring the claim in step -- the body write is not undone, and the same
    rescope again writes the same body and the claim."""
    _write_rescoped_body(context, item, intent.scope, whole)
    try:
        return context.transition(subject, intent)
    except protocol.ClaimError as error:
        label = board.item_label(item.number, context.config.storage)
        raise protocol.ClaimUnavailableError(
            f"{label} body scope now reads {list(intent.scope)}, but the claim was not "
            f"rescoped: {error}; run the same rescope again"
        ) from error


def _rescope_write(parsed: argparse.Namespace, run_context: RunContext) -> int:
    paths = _rescope_paths(parsed.add, parsed.drop)
    path_checkout = _rescope_checkout(paths)
    checkout_context = run_context.for_directory(path_checkout.toplevel, is_toplevel=True)
    requested = _rescope_command(parsed, paths, path_checkout, checkout_context)
    worktree = checkout_context.toplevel
    observed = checkout_context.observation
    protocol.require_state_ref(observed)
    try:
        selected = board.selected_store_claim(
            observed,
            requested.identity,
            requested.branch,
            requested.claim_id,
            checkout_context.config.storage,
        )
    except protocol.ClaimError as error:
        raise _RescopePreconditionError(str(error)) from error
    if requested.agent != selected.agent:
        raise _RescopePreconditionError(
            "only the original claimant may rescope "
            f"(holder={protocol.claimant_text(selected.agent, selected.role)!r}, "
            f"this session={protocol.claimant_text(requested.agent, selected.role)!r})"
        )
    versioned = checkout.versioned_paths(directory=worktree)
    try:
        _reject_ungrounded_comma_scope(requested.add, versioned, flag="--add")
        combined = protocol.combined_scope(selected.scope, requested.add, requested.drop)
    except protocol.ClaimError as error:
        raise _RescopeInvalidUsageError(str(error)) from error
    item = _rescoped_item_body(checkout_context, selected.identity)
    try:
        _n, _total, _share, whole_reason = _reject_wide_scope(
            combined,
            versioned,
            requested.whole_reason or selected.whole_reason,
            directories=checkout.scope_directories(
                combined,
                directory=checkout_context.directory,
                toplevel=lambda: checkout_context.toplevel,
            ),
            whole_from_body=None if item is None else lambda: item.whole,
        )
    except protocol.ClaimError as error:
        raise _RescopePreconditionError(str(error)) from error
    intent = protocol.RescopeIntent(
        claim_id=selected.claim_id,
        agent=requested.agent,
        role=selected.role,
        scope=combined,
        operation_id=uuid.uuid4().hex,
        whole_reason=whole_reason,
    )
    subject = store.transition_subject(RESCOPE_COMMAND, selected.identity, selected.branch)
    new_state = (
        checkout_context.transition(subject, intent)
        if item is None
        else _rescope_item_and_claim(
            checkout_context, subject, intent, item, requested.whole_reason
        )
    )
    rescoped = new_state.claims[protocol.claim_key(selected.identity, selected.branch)]
    if parsed.json:
        _rescope_json(rescoped)
        return 0
    subject = board.claim_subject(rescoped, checkout_context.config.storage)
    print(f"RESCOPED {subject}: {rescoped.claim_id}")
    return 0


def _cmd_rescope(parsed: argparse.Namespace, context: RunContext) -> int:
    """`rescope`'s own `--json` refusals (issue #406, `RescopeReason`):
    `_rescope_write`'s two typed exceptions choose `invalid_usage`/
    `precondition_failed`; every other `protocol.ClaimError` -- an
    unresolved checkout, a missing state ref, a corrupted claim record --
    falls to `unavailable`, matching `ask`/`rule`/`brief`'s own catch-all."""
    as_json = parsed.json
    try:
        return _rescope_write(parsed, context)
    except _RescopeInvalidUsageError as error:
        return report.refuse(RescopeReason.INVALID_USAGE, error, as_json=as_json)
    except _RescopePreconditionError as error:
        return report.refuse(RescopeReason.PRECONDITION_FAILED, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(RescopeReason.UNAVAILABLE, error, as_json=as_json)


LANE_CLAIM_SCOPE_REQUIRED = "lane claim requires --scope; a lane names no item to derive it from"
CLAIM_SCOPE_MISSING = "item names no scope; pass --scope"
CLAIM_SCOPE_MISMATCH = "claim scope differs from the item's scope; correct the item first"


class _ClaimTargetInvalidError(protocol.ClaimError):
    """The item a claim's scope is being *derived* from is unusable --
    missing, or a pull request -- discovered while reading its body, before
    any slice-rule check ever runs (issue #406). Named so `--json` can
    choose `target_invalid` over the broad `unavailable` every other claim
    refusal falls to."""


class _ClaimBodyInvalidError(protocol.ClaimError):
    """The item a claim's scope is being *derived* from has a body that
    cannot supply or confirm one -- a malformed `aco` block (issue
    #310 finding 43: named *before* "item names no scope", reusing the same
    block-defect reader `body --check` uses), no `scope` field at all, or
    one differing from an explicit `--scope` (issue #406). Named so
    `--json` can choose `body_invalid`."""


def _item_target_body(
    client: forge.ForgeReader,
    open_by_number: Mapping[int, board.Issue],
    number: int,
    storage: body.Storage,
) -> str:
    """The item's own body for `_item_scope`/`_item_whole` (issue #337):
    from `open_by_number` -- the open-board listing `claim` needs anyway
    for its slice-rule checks -- when the target is open, so a derived
    scope costs no separate body read; a closed, missing, or pull-request
    target never appears there, and falls back to the one single-item
    lookup `_issue_reference_state` uses for the same reason (issue #245).
    `_item_body_or_refuse`'s own `ClaimUnavailableError` -- missing or a
    pull request, CLM-24's own two conditions -- becomes
    `_ClaimTargetInvalidError` by name (issue #406); a forge outage or
    malformed response (`forge.ForgeError`, raised by `client.item_reference`
    itself) is a different failure and passes through unwrapped to
    `_cmd_claim`'s `unavailable` catch-all (CLM-27)."""
    issue = open_by_number.get(number)
    if issue is not None:
        return issue.body
    try:
        return _item_body_or_refuse(client, number, command="claim", storage=storage)
    except protocol.ClaimUnavailableError as error:
        raise _ClaimTargetInvalidError(str(error)) from error


def _item_scope(
    client: forge.ForgeReader,
    open_by_number: Mapping[int, board.Issue],
    number: int,
    *,
    storage: body.Storage,
) -> tuple[str, ...] | None:
    """The item's own top-level `scope = [...]` (issue #337). A malformed
    block refuses `_ClaimBodyInvalidError` here (issue #310 finding 43) --
    before this function's caller ever gets to name the less specific "item
    names no scope" -- reading `read_state`/`contract.defects` the same way
    `body --check` and `_located_block_or_refuse` already do, the one
    block-defect reader every by-name body refusal in this file shares.
    `_item_whole`'s own read stays tolerant of a malformed body instead: its
    caller is only ever an optional width-gate fallback, never a hard
    requirement the way a claim's own scope is."""
    raw_body = _item_target_body(client, open_by_number, number, storage)
    parsed = body.parse_body(raw_body, storage=storage)
    if parsed.read_state is body.BodyReadState.MALFORMED:
        defect = parsed.contract.defects[0]
        raise _ClaimBodyInvalidError(
            f"{board.item_label(number, storage)} {body.body_defect_text(defect)}"
        )
    return parsed.scope


def _item_whole(
    client: forge.ForgeReader,
    open_by_number: Mapping[int, board.Issue],
    number: int,
    *,
    storage: body.Storage,
) -> str | None:
    """The item's own top-level `whole = "<reason>"` (issue #399), read the
    same way `_item_scope` reads `scope` -- except a malformed body is never
    a hard refusal here (see `_item_scope`'s own docstring): `parse_body`
    simply carries no `whole` for one, exactly as it did before issue #406,
    so the width gate's own refusal still fires instead of an unrelated
    defect message."""
    raw_body = _item_target_body(client, open_by_number, number, storage)
    return body.parse_body(raw_body, storage=storage).whole


def _whole_from_item_body(
    context: RunContext,
    identity: protocol.ClaimIdentity,
    *,
    open_by_number: Mapping[int, board.Issue] | None,
) -> Callable[[], str | None] | None:
    """The wide-scope gate's own fallback for `claim`/`start` (issue #399):
    `None` for a lane claim, which names no item to read one from; otherwise
    a lazy resolver `_reject_wide_scope` calls only once the scope actually
    trips the gate and neither call names `--whole` -- so a narrow scope, or
    an explicit `--whole`, never costs this read. Reuses `open_by_number`
    when the caller already fetched it (a derived scope); otherwise reads
    the one target item alone, never the whole board, so a replay (CLM-15)
    or a live-claim resume (START-06) never reads past its own item (issue
    #447). Resolves the repository's own storage pin
    itself, since a trip's resolver runs before `_cmd_claim`'s own branch
    has necessarily done so."""
    if not isinstance(identity, protocol.IssueIdentity):
        return None
    number = identity.issue

    def resolve() -> str | None:
        client = context.forge
        storage = context.config.storage
        return _item_whole(client, open_by_number or {}, number, storage=storage)

    return resolve


def _resolved_claim_request(
    requested: protocol.ClaimRequest,
    observed: protocol.ClaimState,
    context: RunContext,
    storage: body.Storage,
) -> tuple[protocol.ClaimRequest, dict[int, board.Issue] | None]:
    """`requested` with its scope filled in for an issue-mode claim that
    omitted `--scope` (issue #337), paired with the open-board listing that
    filling it cost -- `None` when it cost nothing, so `_cmd_claim` never
    fetches that board a second time for its own slice-rule checks.

    A live claim already on this identity and branch is a replayed,
    interrupted request even when the retry drops `--scope`: its own stored
    scope is taken outright, with no forge call and no body read at all, so
    a retry never refuses merely because the body changed, or lost its
    scope, since the original claim was opened -- and `_matching_store_claim`
    is guaranteed `None` for an identity with no live claim at all, so this
    is the only place that needs to look. Otherwise the item's own body
    `scope = [...]` is the source of truth, fetched from the same open board
    `_cmd_claim` needs anyway for its slice-rule checks, so the caller reuses
    it rather than asking again."""
    identity = requested.identity
    assert isinstance(identity, protocol.IssueIdentity)
    live = observed.claims.get(protocol.claim_key(identity, requested.branch))
    if live is not None:
        return replace(requested, scope=live.scope), None
    client = context.forge
    open_by_number = {issue.number: issue for issue in client.list_open_board_issues()}
    item_scope = _item_scope(client, open_by_number, identity.issue, storage=storage)
    if item_scope is None:
        raise _ClaimBodyInvalidError(CLAIM_SCOPE_MISSING)
    return replace(requested, scope=item_scope), open_by_number


def _reject_scope_mismatch(
    open_by_number: Mapping[int, board.Issue],
    target_issue: int,
    scope: tuple[str, ...],
    storage: body.Storage,
) -> None:
    """Refuses an explicit `--scope` whose canonical set differs from the
    target item's own body scope (issue #337) -- reusing the open board
    `_cmd_claim` fetches once, whether for a derived scope or for its
    slice-rule checks, so this costs no second forge read. A target item
    outside the fetched open list, or one with no `scope` field of its own,
    has nothing to differ from and is silently accepted, exactly as before
    this field existed. A derived scope always came from this same body, so
    the comparison here is trivially satisfied -- never an extra read, just
    an inexpensive no-op check."""
    issue = open_by_number.get(target_issue)
    if issue is None:
        return
    item_scope = body.parse_body(issue.body, storage=storage).scope
    if item_scope is not None and item_scope != scope:
        raise _ClaimBodyInvalidError(CLAIM_SCOPE_MISMATCH)


def _scope_versioning(
    scope: tuple[str, ...],
    whole_reason: str | None,
    *,
    context: RunContext,
    whole_from_body: Callable[[], str | None] | None = None,
    revision: str | None = None,
) -> tuple[ScopeVersioning, str | None]:
    """`claim`'s local, forge-free scope checks (issue #207's comma guard,
    the wide-scope width gate) against the real checkout, run once the
    requested scope is final -- whether it came from `--scope` or was
    derived from the item's own body. Read from `context`'s directory via
    `-C` when it names one (issue #322: `start`'s own resolved worktree,
    never a process-wide `os.chdir`) or the calling process's own cwd
    otherwise. The second element is the effective `whole_reason` the width
    gate actually admitted the scope with (issue #399): `whole_reason`
    itself, or `whole_from_body()`'s own result when the gate tripped and
    needed it -- the caller's own claim persists this, not the raw
    `whole_reason` it passed in. Given `revision`, the scope is measured
    against that commit's tree instead of the checkout (issue #479:
    `start`'s fetched trunk, before any worktree of it exists)."""
    versioned = checkout.versioned_paths(directory=context.directory, revision=revision)
    _reject_ungrounded_comma_scope(scope, versioned, flag="--scope")
    directories = checkout.scope_directories(
        scope, directory=context.directory, toplevel=lambda: context.toplevel, revision=revision
    )
    n, total, share, effective_whole_reason = _reject_wide_scope(
        scope, versioned, whole_reason, directories=directories, whole_from_body=whole_from_body
    )
    return ScopeVersioning(n, total, share), effective_whole_reason


@dataclass(frozen=True)
class _ClaimTargetContext:
    """The board-environment scalars `_claim_target_checks` needs beyond
    the claim request itself, bundled once instead of PLR0913's
    five-scalar ceiling (issue #337): `storage` and `worktree` `_cmd_claim`
    already resolved before this point, and `open_by_number` -- the open
    board, when deriving the scope already fetched it, `None` otherwise --
    so a fresh issue claim that did not derive its scope still fetches the
    board exactly once, inside `_claim_target_checks` itself."""

    storage: body.Storage
    worktree: Path
    open_by_number: dict[int, board.Issue] | None


def _claim_target_checks(
    context: RunContext,
    requested: protocol.ClaimRequest,
    observed: protocol.ClaimState,
    target: _ClaimTargetContext,
) -> tuple[tuple[SliceCheck, ...], int | None, protocol.ActiveClaim | None]:
    """`_cmd_claim`'s slice-rule checks against its own target issue,
    `()`/`None`/`None` for a lane claim -- there is no target issue to
    check against. A replayed claim (`_matching_store_claim`) skips the
    forge and the checks entirely, since an interrupted retry was already
    accepted once. A fresh issue claim reuses `target.open_by_number` when
    deriving the scope already fetched it (issue #337), so this never
    re-fetches the open board a second time, then runs the mismatch and
    slice-rule gates against it. `context.forge` -- built and
    Erwartung-6-checked on this first call (issue #245) -- runs only on
    this fresh-claim path, never for a lane claim or a replay."""
    if not isinstance(requested.identity, protocol.IssueIdentity):
        return (), None, None
    target_issue = requested.identity.issue
    replayed = _matching_store_claim(observed, requested)
    if replayed is not None:
        return (), target_issue, replayed
    client = context.forge
    open_by_number = target.open_by_number
    if open_by_number is None:
        open_by_number = {issue.number: issue for issue in client.list_open_board_issues()}
    _reject_scope_mismatch(open_by_number, target_issue, requested.scope, target.storage)
    projected = board_read.build_board(
        context,
        tuple(observed.claims.values()),
        issues=tuple(open_by_number.values()),
        history=board_read.ClaimHistory(ages=board_read.claim_ages(target.worktree, observed)),
    )
    checks = _slice_rule_checks(
        BoardReferenceLookup(client, client.repository.path, open_by_number),
        target_issue,
        projected,
        requested.out_of_order_reason,
        target.storage,
    )
    return checks, target_issue, replayed


def _cmd_claim(parsed: argparse.Namespace, context: RunContext) -> int:
    try:
        return _claim_write(parsed, context)
    except protocol.ClaimError as error:
        return _refuse_claim_error(error, context, as_json=parsed.json)


def _refuse_claim_error(error: protocol.ClaimError, context: RunContext, *, as_json: bool) -> int:
    """`claim`'s own `--json` refusals (issue #406, `ClaimReason`):
    `_claim_write`'s typed exceptions choose `target_invalid`/
    `body_invalid`/`claim_conflict`; `RepoMeaninglessUnderStateRefError`
    chooses `invalid_usage`; every other `protocol.ClaimError` -- a checkout
    precondition, scope grammar, an unsafe branch or claim id -- falls to
    `unavailable`, matching `ask`/`rule`/`brief`'s own catch-all. Only a
    conflict reads `context`'s board configuration, to name its item."""
    match error:
        case RepoMeaninglessUnderStateRefError():
            reason = ClaimReason.INVALID_USAGE
        case _ClaimTargetInvalidError():
            reason = ClaimReason.TARGET_INVALID
        case _ClaimBodyInvalidError():
            reason = ClaimReason.BODY_INVALID
        case protocol.ClaimConflictError():
            # `apply()`'s own conflict, met on the observed state or by the
            # claim's write (CLM-25), whether or not its push was sent; a
            # transport, git, lineage, or retry-exhaustion failure is another
            # `ClaimError` and falls to `unavailable` below (CLM-27).
            return report.refuse(
                ClaimReason.CLAIM_CONFLICT,
                board.named_refusal(error, context.config.storage),
                as_json=as_json,
            )
        case _:
            reason = ClaimReason.UNAVAILABLE
    return report.refuse(reason, error, as_json=as_json)


def _claim_write(
    parsed: argparse.Namespace, context: RunContext, *, worktree: Path | None = None
) -> int:
    """`claim` made in the session's own checkout, or in `worktree` when
    given (`start` claiming in a lane worktree that already stands, issue
    #479): then the request is read and checked in `worktree` and the scope
    measured against its HEAD, while the claim's checks read the session's
    own board configuration -- the main checkout's."""

    def default_branch() -> str | None:
        # A remote this checkout does not configure records no default
        # branch, so the `main`/`master` guess would judge the checkout
        # against a trunk nobody named (issue #512): name the remote first.
        context.refuse_unconfigured_canonical_remote()
        return context.recorded_default_branch

    if worktree is None:
        requested = _request(parsed, default_branch=default_branch, directory=context.directory)
        plan = _checked_claim(requested, context)
        writer = context
    else:
        requested = _request(parsed, default_branch=default_branch, directory=worktree)
        plan = _checked_claim(requested, context, revision=requested.base)
        writer = context.for_lane_worktree(worktree)
    if plan.refused:
        _refuse_claim(parsed.json, plan.target_issue, plan.checks)
        return 2
    _print_claim_checks(plan, as_json=parsed.json)
    claimed, live = _committed_claim(plan, writer)
    return _report_claim(plan, claimed, live, as_json=parsed.json)


@dataclass(frozen=True)
class _ClaimPlan:
    """What `claim`'s check phase accepted, and everything its commit phase
    writes and reports (issue #479): `start` runs the two phases around the
    worktree it builds, so a refusal comes before the build."""

    requested: protocol.ClaimRequest
    observed: protocol.ClaimState
    storage: body.Storage
    versioning: ScopeVersioning
    checks: tuple[SliceCheck, ...]
    target_issue: int | None
    replayed: protocol.ActiveClaim | None
    intent: protocol.ClaimIntent

    @property
    def refused(self) -> bool:
        return any(check.level == "error" for check in self.checks)


def _checked_claim(
    requested: protocol.ClaimRequest, context: RunContext, *, revision: str | None = None
) -> _ClaimPlan:
    """`claim`'s check phase: every refusal a claim meets before its one
    ledger write -- the scope's shape and width, the store, the target's
    slice rules, and the ledger's own conflict, `protocol.apply` run on the
    observed state (issue #479). Refusing slice rules come back in the plan
    for the caller to report in its own shape; every other refusal raises.
    `revision` names the commit the scope is measured against when the
    session's own checkout is not the one claimed in (`start`'s fetched
    trunk before its worktree exists, or the HEAD of a lane worktree that
    already stands); the session's own checkout otherwise."""
    if isinstance(requested.identity, protocol.LaneIdentity) and not requested.scope:
        raise protocol.ClaimUnavailableError(LANE_CLAIM_SCOPE_REQUIRED)
    open_by_number: dict[int, board.Issue] | None = None
    if requested.scope or not isinstance(requested.identity, protocol.IssueIdentity):
        # Scope already final (given, or a lane's own required value): the
        # local shape checks run first, exactly as before this field
        # existed, so a comma or width refusal never touches the store or
        # resolves the repository toplevel -- unless the scope is actually
        # wide and names no `--whole` of its own, in which case the width
        # gate's own lazy fallback (issue #399) resolves the toplevel itself
        # to read the item's body, never this branch.
        versioning, effective_whole = _scope_versioning(
            requested.scope,
            requested.whole_reason,
            context=context,
            whole_from_body=_whole_from_item_body(context, requested.identity, open_by_number=None),
            revision=revision,
        )
        requested = replace(requested, whole_reason=effective_whole)
        observed = context.observation
        protocol.require_state_ref(observed)
        storage = context.config.storage
    else:
        # `--scope` was omitted in issue mode: the item's own scope has to
        # come from the store, and usually the forge, before it can even be
        # shape-checked -- both observed exactly once, here, so an omitted-
        # scope claim never fetches either a second time (issue #337).
        observed = context.observation
        protocol.require_state_ref(observed)
        storage = context.config.storage
        requested, open_by_number = _resolved_claim_request(requested, observed, context, storage)
        versioning, effective_whole = _scope_versioning(
            requested.scope,
            requested.whole_reason,
            context=context,
            whole_from_body=_whole_from_item_body(
                context, requested.identity, open_by_number=open_by_number
            ),
            revision=revision,
        )
        requested = replace(requested, whole_reason=effective_whole)
    worktree = context.toplevel
    checks, target_issue, replayed = _claim_target_checks(
        context, requested, observed, _ClaimTargetContext(storage, worktree, open_by_number)
    )
    plan = _ClaimPlan(
        requested=requested,
        observed=observed,
        storage=storage,
        versioning=versioning,
        checks=checks,
        target_issue=target_issue,
        replayed=replayed,
        intent=_claim_intent_from_request(
            requested,
            uuid.uuid4().hex,
            _claimed_item_pin(requested.identity, observed, storage),
        ),
    )
    if replayed is None and not plan.refused:
        protocol.apply(observed, plan.intent)
    return plan


def _print_claim_checks(plan: _ClaimPlan, *, as_json: bool) -> None:
    for check in plan.checks:
        print(check.render(), file=sys.stderr if as_json else sys.stdout)


def _committed_claim(
    plan: _ClaimPlan, writer: RunContext
) -> tuple[protocol.ActiveClaim, tuple[protocol.ActiveClaim, ...]]:
    """`claim`'s commit phase: the plan's one ledger write, made from the
    checkout `writer` stands for, or the replayed claim it already names,
    with every live claim after it."""
    if plan.replayed is not None:
        return plan.replayed, tuple(plan.observed.claims.values())
    requested = plan.requested
    new_state = writer.transition(
        store.transition_subject("claim", requested.identity, requested.branch), plan.intent
    )
    claimed = new_state.claims[protocol.claim_key(requested.identity, requested.branch)]
    return claimed, tuple(new_state.claims.values())


def _report_claim(
    plan: _ClaimPlan,
    claimed: protocol.ActiveClaim,
    live: tuple[protocol.ActiveClaim, ...],
    *,
    as_json: bool,
) -> int:
    touches = protocol.conflicting_claims(live, claimed)
    if as_json:
        return _claim_json(claimed, versioning=plan.versioning, touches=touches, checks=plan.checks)
    print(f"CLAIMED {board.claim_subject(claimed, plan.storage)}: {claimed.claim_id}")
    print(
        _claim_cost_line(
            plan.versioning.versioned_files,
            plan.versioning.versioned_files_total,
            plan.requested.scope,
            touches,
            plan.storage,
        )
    )
    return 0


def _start_worktree_path(main_checkout: Path, *, number: int, slug: str) -> Path:
    return main_checkout.parent / f"{main_checkout.name}-worktrees" / f"issue-{number}-{slug}"


@dataclass(frozen=True)
class _StartTarget:
    """The worktree `start` claims in and the branch it stands on."""

    path: Path
    branch: str


def _runs_in_lane_worktree(context: RunContext, lane_branch: str) -> bool:
    """Whether `start` runs inside a linked worktree checked out on
    `lane_branch` -- the live claim's own lane (issue #479), whatever slug
    its path carries."""
    caller = checkout.resolve_path_checkout(context.toplevel)
    return (
        caller is not None
        and caller.kind is checkout.CheckoutKind.LINKED_WORKTREE
        and caller.branch == lane_branch
    )


def _resumable_start_claim(
    live: protocol.ActiveClaim | None, branch: str
) -> protocol.ActiveClaim | None:
    """`live`, when `start` resumes it rather than claiming afresh.
    `claim_key` alone is an issue-only key for an `IssueIdentity` (it never
    folds `branch` into the key at all): a live record found under it may
    belong to a different agent, a different role, or a different branch
    entirely, so resume requires this session's own agent, `start`'s own
    claiming role, and the expected lane branch too -- the same facts
    `release`'s own claimant/branch checks require, plus the role a
    reviewer claim on the same item must never satisfy (review/gate
    finding). A mismatch falls through to the fresh claim, which refuses
    with the store's own "is claimed by ..." conflict."""
    if (
        live is not None
        and live.agent == checkout.resolved_agent(None)
        and live.role == DEFAULT_CLAIM_ROLE
        and live.branch == branch
    ):
        return live
    return None


def _print_start_target(target: _StartTarget) -> None:
    print(f"worktree: {target.path}")
    print(f"branch: {target.branch}")


def _remove_refused_start_worktree(target: _StartTarget) -> None:
    """Undo the build of a `start` whose claim was refused after the check
    phase passed (issue #479), saying so: a refusal must leave no worktree
    or branch behind. When git will not remove the worktree, that is said
    too, beside the refusal rather than in its place."""
    try:
        outcome = checkout.remove_linked_worktree(target.path, branch=target.branch)
    except protocol.ClaimError as error:
        print(
            f"worktree {target.path} and branch '{target.branch}' this start created "
            f"kept: git failure: {error}",
            file=sys.stderr,
        )
        return
    if outcome.branch.fate is checkout.BranchFate.REMOVED:
        print(
            f"removed worktree {target.path} and branch '{target.branch}' this start created",
            file=sys.stderr,
        )
        return
    print(
        f"removed worktree {target.path} this start created; "
        f"branch '{target.branch}' {outcome.branch.fate}: {outcome.branch.reason}",
        file=sys.stderr,
    )


RESUME_SCOPE_MISMATCH = "live claim scope differs; release it first"


def _refuse_resume_scope_mismatch(live: protocol.ActiveClaim, parsed: argparse.Namespace) -> None:
    if parsed.scope is not None and protocol.valid_scope(parsed.scope) != live.scope:
        raise protocol.ClaimUnavailableError(RESUME_SCOPE_MISMATCH)


def _checked_start_resume(
    live: protocol.ActiveClaim,
    parsed: argparse.Namespace,
    *,
    context: RunContext,
    revision: str | None = None,
) -> ScopeVersioning:
    """Every refusal `start`'s resume of `live` can meet, run before anything
    is printed or built (issue #479): an explicit `--scope` that disagrees
    with the live claim's own stored scope (review/gate finding: resume must
    not silently ignore it), then the stored scope's own shape and width
    against `context`'s checkout -- or `revision`, the fetched trunk a gone
    worktree is rebuilt from. `--whole` is never required here even when the
    live scope is wide, since the stored claim's own `whole_reason` already
    justified it once."""
    _refuse_resume_scope_mismatch(live, parsed)
    versioning, _effective_whole = _scope_versioning(
        live.scope,
        parsed.whole if parsed.whole is not None else live.whole_reason,
        context=context,
        revision=revision,
    )
    return versioning


def _print_start_resume(
    live: protocol.ActiveClaim,
    observed: protocol.ClaimState,
    storage: body.Storage,
    versioning: ScopeVersioning,
) -> None:
    """`start`'s own resume path (issue #322 review finding 1): prints the
    same `CLAIMED ...`/cost-line grammar a fresh claim prints, for the live
    claim `_cmd_start` already found in the store -- the same
    `observed.claims` lookup `status`/`release` use -- rather than minting a
    second, fresh id for an item that already has one."""
    print(f"CLAIMED {board.claim_subject(live, storage)}: {live.claim_id}")
    touches = protocol.conflicting_claims(tuple(observed.claims.values()), live)
    print(
        _claim_cost_line(
            versioning.versioned_files,
            versioning.versioned_files_total,
            live.scope,
            touches,
            storage,
        )
    )


def _start_branch_and_slug(parsed: argparse.Namespace, context: RunContext) -> tuple[str, str]:
    """The lane branch and slug `start` builds for an open item, refusing a
    missing or closed one, an unusable slug, and an unsafe prefix before any
    git write."""
    number = parsed.item
    item = context.forge.item_reference(number)
    label = board.item_label(number, context.config.storage)
    if item.state is forge.ItemState.MISSING:
        raise protocol.ClaimUnavailableError(f"issue {label} does not exist here")
    if item.state is forge.ItemState.CLOSED:
        raise protocol.ClaimUnavailableError(f"issue {label} is closed")
    slug = (
        checkout.validate_slug(parsed.slug)
        if parsed.slug is not None
        else checkout.slug_from_title(item.title or "")
    )
    prefix = checkout.branch_prefix_for_identity()
    branch = f"{prefix}/issue-{number}-{slug}"
    checkout.refuse_unsafe_start_branch(branch, prefix=prefix)
    return branch, slug


def _cmd_start(parsed: argparse.Namespace, context: RunContext) -> int:
    """Checks, then builds (issue #479): a worktree already standing -- the
    caller's own lane, or a prior `start`'s at the computed path -- is
    claimed in place; otherwise the claim is checked against the freshly
    fetched trunk before the worktree is built, so a refusal leaves
    nothing behind. The item, the store, and every check the claim makes
    read the main checkout's own board configuration, never a lane
    worktree's the caller stands in or claims in: a lane may be changing
    its `board.toml`."""
    caller = context
    main_context = caller.for_directory(
        checkout.main_checkout_root(toplevel=caller.toplevel), is_toplevel=True
    )
    branch, slug = _start_branch_and_slug(parsed, main_context)
    observed = main_context.observation
    protocol.require_state_ref(observed)
    live = observed.claims.get(
        protocol.claim_key(protocol.resolved_identity(parsed.item, branch), branch)
    )
    if live is not None and _runs_in_lane_worktree(caller, live.branch):
        own_lane = _StartTarget(caller.toplevel, live.branch)
        return _claim_in_start_worktree(parsed, main_context, own_lane, observed, live)
    target = _StartTarget(
        _start_worktree_path(main_context.toplevel, number=parsed.item, slug=slug), branch
    )
    if checkout.existing_start_worktree(target.path, branch):
        return _claim_in_start_worktree(parsed, main_context, target, observed, live)
    resumed = _resumable_start_claim(live, branch)
    if resumed is not None:
        return _rebuild_and_resume(parsed, main_context, target, observed, resumed)
    return _check_build_and_claim(parsed, main_context, target)


def _start_claim_arguments(
    parsed: argparse.Namespace,
    *,
    base: str | None = None,
    branch: str | None = None,
    claim_id: str | None = None,
) -> argparse.Namespace:
    """The `aco claim` arguments `start` claims with: this session's own
    agent as the builder, and a fresh id, exactly as a bare `aco claim`
    mints one (issue #322 review finding 1) -- `start` resumes a live claim
    by name before it ever claims, so CLAIM-15's own replay-by-claim-id
    logic never needs to recognize a `start`-minted id as special. A
    resume passes its live claim's own `claim_id`, so it never computes a
    second one."""
    return argparse.Namespace(
        issue=parsed.item,
        agent=None,
        role=DEFAULT_CLAIM_ROLE,
        base=base,
        branch=branch,
        scope=parsed.scope,
        claim_id=claim_id,
        out_of_order=parsed.out_of_order,
        whole=parsed.whole,
        resource=None,
        json=False,
    )


def _claim_in_start_worktree(
    parsed: argparse.Namespace,
    context: RunContext,
    target: _StartTarget,
    observed: protocol.ClaimState,
    live: protocol.ActiveClaim | None,
) -> int:
    """Claim, or resume, in a worktree that already stands: nothing is
    built, so a refusal has nothing to undo, and a claim whose outcome the
    store cannot tell says the worktree stays as a fresh build's would
    (START-25). `context` is the main checkout's; only the scope is
    measured in the worktree itself."""
    resumed = _resumable_start_claim(live, target.branch)
    if resumed is not None:
        versioning = _checked_start_resume(
            resumed, parsed, context=context.for_directory(target.path)
        )
        _print_start_target(target)
        _print_start_resume(resumed, observed, context.config.storage, versioning)
        return 0
    _print_start_target(target)
    # The main checkout's one observation, the same snapshot the lookup above
    # read (CAS-53): nothing fetched since.
    try:
        return _claim_write(_start_claim_arguments(parsed), context, worktree=target.path)
    except protocol.UncertainWriteError as error:
        named = board.named_refusal(error, context.config.storage)
        return _report_uncertain_start_claim(named, target)
    except protocol.ClaimError as error:
        return _refuse_claim_error(error, context, as_json=False)


def _rebuild_and_resume(
    parsed: argparse.Namespace,
    context: RunContext,
    target: _StartTarget,
    observed: protocol.ClaimState,
    resumed: protocol.ActiveClaim,
) -> int:
    """A live claim of this session's whose worktree is gone: its scope is
    checked against the fetched trunk first, then the worktree is built
    again from that trunk and the claim reprinted, never a second one
    minted. A worktree that stands on another commit -- another fetch moved
    the trunk after the checks -- is removed again, as a fresh build's is
    (START-18)."""
    trunk_ref = context.fetched_trunk_ref()
    trunk = checkout.trunk_commit(trunk_ref, directory=context.toplevel)
    versioning = _checked_start_resume(resumed, parsed, context=context, revision=trunk)
    checked = _claim_request(
        _start_claim_arguments(parsed, base=trunk, branch=target.branch, claim_id=resumed.claim_id)
    )
    checkout.create_linked_worktree(
        target.path, branch=target.branch, trunk=trunk_ref, directory=context.toplevel
    )
    _print_start_target(target)
    try:
        _validate_built_worktree(checked, target, context)
    except protocol.ClaimError as error:
        return _refuse_built_start(error, target)
    _print_start_resume(resumed, observed, context.config.storage, versioning)
    return 0


def _check_build_and_claim(
    parsed: argparse.Namespace, context: RunContext, target: _StartTarget
) -> int:
    """Fetch the trunk, run `claim`'s check phase against that one commit,
    then build the worktree from the trunk and run the commit phase (issue
    #479). A refusal after the build removes it again (START-18): the trunk
    moved under another fetch meanwhile, the new worktree failing `claim`'s
    own checkout preconditions, or the ledger refusing the write -- a claim
    or close that landed after the checks, a store it cannot reach -- also
    once a sent push was rejected and the store re-read nothing of it
    written (issue #498). Only a sent write whose outcome the store cannot
    tell keeps the worktree and says so (START-25). An interrupt or an
    unexpected error is no refusal."""
    trunk_ref = context.fetched_trunk_ref()
    trunk = checkout.trunk_commit(trunk_ref, directory=context.toplevel)
    # The main checkout observed afresh, never the observation the
    # item-existence read already holds: the fetch above may take a while,
    # and the claim must read the item as it stands once the fetch is done,
    # not the snapshot that read took (issue #322 review finding 2, CAS-55).
    check_context = context.observed_afresh()
    requested = _claim_request(_start_claim_arguments(parsed, base=trunk, branch=target.branch))
    storage = check_context.config.storage
    try:
        plan = _checked_claim(requested, check_context, revision=trunk)
    except protocol.ClaimConflictError as error:
        raise board.named_refusal(error, storage) from error
    if plan.refused:
        _refuse_claim(False, plan.target_issue, plan.checks)
        return 2
    checkout.create_linked_worktree(
        target.path, branch=target.branch, trunk=trunk_ref, directory=context.toplevel
    )
    _print_start_target(target)
    _print_claim_checks(plan, as_json=False)
    try:
        _validate_built_worktree(requested, target, check_context)
        # Written from the built worktree, so the lane's own lineage stamp
        # and fetch anchor start at its claim (CAS-09).
        claimed, claims = _committed_claim(plan, check_context.for_lane_worktree(target.path))
    except protocol.UncertainWriteError as error:
        return _report_uncertain_start_claim(board.named_refusal(error, storage), target)
    except protocol.ClaimError as error:
        return _refuse_built_start(board.named_refusal(error, storage), target)
    return _report_claim(plan, claimed, claims, as_json=False)


def _validate_built_worktree(
    request: protocol.ClaimRequest, target: _StartTarget, context: RunContext
) -> None:
    """`claim`'s own checkout preconditions against the worktree `start`
    built, judged against the main checkout `context`'s recorded default
    branch. Its base is the trunk `start` checked, so a base mismatch means
    another fetch moved the trunk between the checks and the build, and
    rerunning `start` checks the trunk as it stands now (START-26)."""
    try:
        checkout.validate_checkout(
            request,
            default_branch=lambda: context.recorded_default_branch,
            directory=target.path,
        )
    except checkout.CheckoutBaseMismatchError as error:
        raise protocol.ClaimUnavailableError(
            "the trunk moved after start checked it; run start again"
        ) from error


def _report_uncertain_start_claim(error: protocol.ClaimError, target: _StartTarget) -> int:
    """A claim write whose outcome the store cannot tell after its push was
    sent: the claim may have landed, so the worktree it may name stays, and
    the next `start` resumes whichever it finds (START-25)."""
    status = report.refuse(ClaimReason.UNAVAILABLE, error, as_json=False)
    print(
        f"the claim's push was sent, its outcome unknown; worktree {target.path} and "
        f"branch '{target.branch}' kept; run start again to resume it",
        file=sys.stderr,
    )
    return status


def _refuse_built_start(error: protocol.ClaimError, target: _StartTarget) -> int:
    try:
        return report.refuse(ClaimReason.UNAVAILABLE, error, as_json=False)
    finally:
        # A refusal that cannot be written (a closed stderr) must still
        # leave nothing behind (START-18).
        _remove_refused_start_worktree(target)


LAND_GITHUB_ONLY_REFUSAL = (
    "aco land is a github command; storage = state-ref has no pull requests to land"
)
LAND_SELF_PACKAGE_NAME = "agent-coordination"
LAND_REINSTALL_LINE = "reinstall: uv tool install --force --from . agent-coordination"


def _land_trunk_trailer(classification: board.Classification) -> str:
    """`classification` rendered as a trunk commit's own trailer grammar
    (`board.trunk_commit_classification`'s counterpart), never the pull
    request body's qualified `owner/repo#n` form `WorkItemClassification.__str__`
    prints: a git trailer is always local to the repository whose history
    it lands on (issue #405; see `board.parse_item_reference`'s own
    docstring)."""
    if isinstance(classification, board.WorkItemClassification):
        return f"Work-Item: #{classification.item.number}"
    return f"No-Item: {classification.kind.value}"


# Git's own blank line (`is_blank_line`): whitespace only. One run of them
# separates two paragraphs, captured so a kept paragraph keeps its own.
_BLANK_LINE_RUN = re.compile(r"(\n(?:[ \t]*\n)+)")


def _without_classification_lines(paragraph: str) -> str:
    return "\n".join(
        line
        for line in paragraph.split("\n")
        if not board.CLASSIFICATION_LINE_PATTERN.fullmatch(line)
    )


def _narrower_separator(dropped: str | None, following: str) -> str:
    """The fewer-line of the two separators around a dropped paragraph,
    `following` on a tie; `following` alone when nothing was dropped."""
    if dropped is None:
        return following
    return min(following, dropped, key=lambda separator: separator.count("\n"))


def _body_without_classification(body: str) -> str:
    """`body` with its classification line removed; a paragraph the removal
    leaves blank goes, and its neighbours keep the narrower of the two
    separators around it, so no blank-line run stays where it stood
    (issue #594 line 5)."""
    pieces = _BLANK_LINE_RUN.split(body.replace("\r\n", "\n"))
    composed = ""
    dropped_separator: str | None = None
    for separator, paragraph in zip(["", *pieces[1::2]], pieces[0::2], strict=True):
        remaining = _without_classification_lines(paragraph)
        if not remaining.strip():
            dropped_separator = _narrower_separator(dropped_separator, separator)
            continue
        if composed:
            composed += _narrower_separator(dropped_separator, separator)
        composed += remaining
        dropped_separator = None
    return composed.strip()


def _land_merge_body(title: str, body: str, classification: board.Classification) -> str:
    """The merge commit message `aco land` composes itself (issue #405,
    Befund 42 on #310): the pull request's own body with its classification
    line removed, then that classification, in the trunk's own trailer
    grammar, as the message's own last line -- so the trailer a later trunk
    walk reads through git's own trailer parsing is never wherever the pull
    request body happened to put it. Git reads trailers from the last
    paragraph only, so a body already ending in a trailer block (a
    `Co-Authored-By:` line) takes the classification into that block
    rather than behind a blank line that would orphan it -- but only where
    git then reads that block's trailers and the classification both, a
    question asked of the composed message itself: git reading the body
    alone skips a trailing comment line and still finds the trailer block
    above it, but once joined that comment line no longer ends the message,
    and git reads it with the classification as the last paragraph instead
    (issue #594)."""
    without_classification = _body_without_classification(body)
    trailer = _land_trunk_trailer(classification)
    if not without_classification:
        return f"{trailer}\n"
    joined = f"{without_classification}\n{trailer}"
    body_trailers = checkout.message_trailers(f"{title}\n\n{without_classification}\n")
    # Read as git reads it: a configured `trailer.<token>.key` renames it.
    classification_trailers = checkout.message_trailers(f"{title}\n\n{trailer}\n")
    joined_keeps_every_trailer = bool(body_trailers) and checkout.message_trailers(
        f"{title}\n\n{joined}\n"
    ) == (*body_trailers, *classification_trailers)
    if joined_keeps_every_trailer:
        return f"{joined}\n"
    return f"{without_classification}\n\n{trailer}\n"


def _land_merge_method(
    pinned: board.MergeMethod | None, client: github.GitHubForge, number: int, branch: str
) -> board.MergeMethod:
    """The method `aco land` merges pull request `number` into `branch` with
    (issues #578, #615): the board configuration's own pin, refused where
    the forge's allowed methods exclude it; otherwise a merge commit wherever
    the forge allows one, and a squash where it allows a squash but no merge
    commit -- never a rebase, so a forge allowing no method at all, or only a
    rebase to an unpinned land, refuses."""
    allowed = _forge_allowed_merge_methods(client, number, branch)
    if pinned is not None and allowed:
        if pinned not in allowed:
            allowed_list = ", ".join(
                method.value for method in board.MergeMethod if method in allowed
            )
            raise protocol.ClaimUnavailableError(
                f"board.toml merge_method {pinned.value} is not allowed on {branch}: "
                f"GitHub allows {allowed_list}"
            )
        return pinned
    for method in (board.MergeMethod.MERGE, board.MergeMethod.SQUASH):
        if method in allowed:
            return method
    raise protocol.ClaimUnavailableError(f"GitHub allows no merge method aco can use on {branch}")


def _forge_allowed_merge_methods(
    client: github.GitHubForge, number: int, branch: str
) -> frozenset[board.MergeMethod]:
    """Every method the forge allows on `branch`: the repository's own
    settings -- every method where it withholds them from a token without
    push rights, refused before any write unless they allow one `aco land`
    can use -- narrowed by each rule on `branch` (LANDCMD-42), since GitHub
    refuses a method any one of them excludes."""
    settings = client.allowed_merge_methods()
    allowed = frozenset(board.MergeMethod) if settings is None else settings
    if not allowed & board.LANDING_MERGE_METHODS:
        raise protocol.ClaimUnavailableError(
            f"pull request #{number} cannot land: this repository allows neither a merge commit "
            "nor a squash merge"
        )
    for rule in client.branch_merge_rules(branch):
        allowed &= rule
    return allowed


def _land_merge_title(method: board.MergeMethod, detail: forge.Landing) -> str:
    """A merge commit's own title, or a squash commit's: the pull request
    title plus `(#<n>)`, the convention a squash-only history reads."""
    if method is board.MergeMethod.SQUASH:
        return f"{detail.title} (#{detail.number})"
    return f"Merge pull request #{detail.number}"


def _land_merge(
    client: github.GitHubForge,
    detail: forge.Landing,
    readiness: forge.LandingReadiness,
    classification: board.Classification,
    method: board.MergeMethod,
) -> str:
    title = _land_merge_title(method, detail)
    try:
        return client.merge_landing(
            detail.number,
            head_sha=readiness.head_sha,
            method=method,
            title=title,
            body=_land_merge_body(title, detail.body, classification),
        )
    except forge.ForgeMergeConflictError as error:
        raise protocol.ClaimUnavailableError(
            f"pull request #{detail.number} changed while it was checked; re-run land"
        ) from error
    except forge.ForgeMergeRefusedError as error:
        raise protocol.ClaimUnavailableError(
            f"GitHub refused the merge of pull request #{detail.number}: "
            f"{board.terminal_text(str(error))}"
        ) from error


_LandStepResult = TypeVar("_LandStepResult")


def _land_step(
    number: int, sha: str, step: str, action: Callable[[], _LandStepResult]
) -> _LandStepResult:
    """Every step `aco land` runs once its merge already landed (issue
    #405): a failure here never means "not merged" -- the merge already
    happened -- so it reports the one ruled recovery line instead of the
    generic refusal an earlier precondition would print. A rerun starts
    `_cmd_land` over from the top, finds the pull request already merged,
    and resumes here without a second merge. The failure is Git's or the
    forge's own text, so its display controls print escaped and the
    recovery stays one line."""
    try:
        return action()
    except protocol.ClaimError as error:
        raise protocol.ClaimUnavailableError(
            f"MERGED pull request #{number} as {sha}; follow-up incomplete: {step} "
            f"({board.terminal_text(str(error))}); re-run aco land {number}"
        ) from error


def _land_release_routing(
    classification: board.Classification | None, merge_sha: str, context: RunContext
) -> int | None:
    """The issue `aco land`'s own delegated `release --merged` call routes
    to (issue #405 point 4): a fresh merge reuses the classification this
    same run's own preflight already verified, never a re-read of the pull
    request's own mutable body. `classification` is `None` only for a rerun
    against a pull request `_cmd_land` found already merged -- preflight
    never ran this time -- so this reads the merge commit's own trailer
    instead, exactly as `cmd_release._verify_merged_release` does (issue #397, Befund
    41): the same authority a lane release itself checks, never the pull
    request's `body`, which stays mutable long after the merge. Runs inside
    the `release` step's own `_land_step` (issue #405 review finding), so a
    defect here -- an edited body's classification long gone from the merge
    commit's own history -- prints the ruled `MERGED ... follow-up
    incomplete: release; re-run aco land <n>` line, never a bare refusal."""
    if classification is not None:
        if isinstance(classification, board.WorkItemClassification):
            return classification.item.number
        return None
    landings = checkout.trunk_landings(
        context.fetched_default_branch_ref(),
        board_read.TRUNK_LANDING_DEPTH,
        directory=context.toplevel,
    )
    landing = next((entry for entry in landings if entry.sha == merge_sha), None)
    trunk_classification = None if landing is None else landing.classification
    if isinstance(trunk_classification, board.TrunkWorkItemClassification):
        return trunk_classification.numbers[0]
    if isinstance(trunk_classification, board.NoItemClassification):
        return None
    raise protocol.ClaimUnavailableError(
        f"merge commit {merge_sha} carries no `Work-Item:` or `No-Item:` trailer"
    )


def _land_release(
    parsed: argparse.Namespace,
    context: RunContext,
    issue: int | None,
    branch: str,
) -> cmd_release.ReleaseEnding:
    """`aco land`'s own delegated call into the existing `release --merged`
    path (issue #405): never a second copy of its close/release/report/
    cleanup -- `--branch` selects the lane by name without requiring this
    checkout to be on it (`cmd_release.release_branch_for`'s own documented case: "the
    release may run from the coordinator's primary checkout"), exactly
    where `land` runs from. Calls `cmd_release.release_transition` directly, never
    `cmd_release.run` (issue #425): `land` needs a raised `ClaimError` here so
    `_land_step` can convert it into its own ruled `MERGED ... follow-up
    incomplete: release` line, not `cmd_release.run`'s own caught-and-printed
    `--json` refusal, which `land` never uses (`json=False` above) and
    would otherwise print its sentence a second time. The release reads
    through a fresh `context` (issue #457 proof 6): the fast-forward just
    wrote the landed trunk into this very checkout, so the configuration
    and forge read before it no longer answer for it."""
    release_parsed = argparse.Namespace(
        issue=issue,
        agent=parsed.agent,
        role=parsed.role,
        branch=branch,
        merged=str(parsed.pull_request),
        abandoned=None,
        claim_id=None,
        coordinator_override=parsed.coordinator_override,
        keep_worktree=parsed.keep_worktree,
        # `land` has no `--json` mode of its own (specs/land.spec.md): the
        # delegated release path always reports in text, exactly as every
        # other line `land` itself prints does.
        json=False,
        repo=parsed.repo,
    )
    return cmd_release.release_transition(release_parsed, context.fresh(), branch)


def _land_is_own_repository(toplevel: Path) -> bool:
    """Whether `toplevel` is this very package's own repository (issue
    #405): `land`'s own reinstall reminder applies only there -- landing in
    any other repository this tool coordinates leaves nothing to
    reinstall."""
    try:
        with (toplevel / "pyproject.toml").open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        return False
    project = data.get("project")
    return isinstance(project, dict) and project.get("name") == LAND_SELF_PACKAGE_NAME


def _cmd_land(parsed: argparse.Namespace, context: RunContext) -> None:
    """`aco land <pr>` (issue #405): preflight every ruled precondition
    read-only, merge with a pinned head sha and a commit message this tool
    composes itself, delete the merged branch, fast-forward this checkout's
    own default branch, then run the existing `release --merged` path
    unchanged. A pull request `landing` already finds merged -- a resumed
    run after an earlier step failed -- skips preflight and the merge
    itself entirely: `merge_landing` never runs twice for the same pull
    request. `--coordinator-override`'s own role is validated here, at
    entry, before that fresh/rerun split and before any read (issue #405
    round-4 finding 1): a rerun skips `cmd_land.land_preflight` entirely, so a
    check placed only there left a rerun free to delete the branch and
    fast-forward -- and `cmd_release.run` free to close the item -- on a bare
    `--coordinator-override` with no coordinator role behind it."""
    toplevel = context.toplevel
    config = context.config
    if config.storage is not body.Storage.GITHUB:
        raise protocol.ClaimUnavailableError(LAND_GITHUB_ONLY_REFUSAL)
    if parsed.coordinator_override:
        protocol.require_coordinator_override(parsed.role)
    client = cast(github.GitHubForge, context.forge)
    number = parsed.pull_request
    repository = client.repository.path
    detail = client.landing(number)
    classification: board.Classification | None
    if detail.merged:
        assert detail.merge_commit is not None  # `merged` is true; github.py guarantees this.
        merge_sha = detail.merge_commit
        checkout.refuse_unlandable_checkout(context.default_branch, directory=toplevel)
        # A rerun: this run's own preflight never ran, so it never verified a
        # classification -- `_land_release_routing` reads the merge commit's
        # own trailer instead (issue #405 point 4).
        classification = None
    else:

        def claims_provider() -> protocol.ClaimState:
            # `store.peek_state`, never `RunContext.observation`'s
            # `fetch_state` (issue #405 review/gate finding): a pull
            # request this preflight goes on to refuse must anchor no ref
            # and stamp no lineage -- the same read-only requirement
            # `cmd_reset._reset_observation` already carries for `reset`.
            observed = store.peek_state(worktree=context.toplevel, remote=context.canonical_remote)
            protocol.require_state_ref(observed)
            return observed

        check_context = policy.LandingCheckContext(context, repository, config.storage)
        detail, classification, readiness = cmd_land.land_preflight(
            client, claims_provider, check_context, number, parsed
        )
        checkout.refuse_unlandable_checkout(context.default_branch, directory=toplevel)
        method = _land_merge_method(config.merge_method, client, number, context.default_branch)
        merge_sha = _land_merge(client, detail, readiness, classification, method)
    _land_step(
        number, merge_sha, "delete-branch", lambda: client.delete_branch(detail.source_branch)
    )
    _land_step(
        number,
        merge_sha,
        "fast-forward",
        lambda: checkout.fast_forward_default_branch(
            context.fetched_default_branch_ref(), directory=toplevel
        ),
    )
    ending = _land_step(
        number,
        merge_sha,
        "release",
        lambda: _land_release(
            parsed,
            context,
            _land_release_routing(classification, merge_sha, context),
            detail.source_branch,
        ),
    )
    # The run whose release succeeded already printed it (LANDCMD-38).
    if ending is cmd_release.ReleaseEnding.RELEASED and _land_is_own_repository(toplevel):
        print(LAND_REINSTALL_LINE)


CONTAINER_KINDS = frozenset({body.ItemKind.CONTAINER})
# `item new --parent` also takes a Task: an item becomes a container exactly
# when it gets its first child, so that write retypes it (issue #503).
ITEM_PARENT_KINDS = frozenset({body.ItemKind.CONTAINER, body.ItemKind.TASK})


def _open_container(
    open_issues: Iterable[board.Issue],
    number: int,
    storage: body.Storage,
    accepted_kinds: frozenset[body.ItemKind] = CONTAINER_KINDS,
) -> board.Issue:
    """`number`'s open issue when its type is one of `accepted_kinds` --
    `cut`'s own target and `item new --parent` (issue #444) -- or why it is
    not."""
    target = next((issue for issue in open_issues if issue.number == number), None)
    if target is None:
        raise protocol.ClaimUnavailableError(
            f"{board.item_label(number, storage)} is not an open container"
        )
    if target.unreadable is not None:
        raise protocol.ClaimUnavailableError(body.body_defect_text(target.unreadable))
    if target.kind not in accepted_kinds:
        raise protocol.ClaimUnavailableError(
            f"{board.item_label(number, storage)} is not a container"
        )
    return target


def _cut_target(
    client: forge.ForgeWriter,
    open_issues: Iterable[board.Issue],
    number: int,
    storage: body.Storage,
) -> board.Issue:
    """The open container `cut` targets, or why it refuses before any write."""
    target = _open_container(open_issues, number, storage)
    parent = client.parent_issue(number)
    if parent is not None:
        parent_label = board.relation_label(parent.reference, storage)
        raise protocol.ClaimUnavailableError(
            f"{board.item_label(number, storage)} is itself a child of {parent_label}; "
            "nested containers are not supported"
        )
    return target


@dataclass(frozen=True)
class _SliceRowRemoval:
    """`container`'s rewritten body, the cut row already removed from its
    `aco` block, and `step`, the words naming that write."""

    container: int
    new_body: str
    step: str


def _link_created_child(
    client: forge.ForgeWriter, removal: _SliceRowRemoval, child: int, storage: body.Storage
) -> None:
    """Write `removal.new_body` back to `removal.container`.

    Not atomic with `create_child` -- GitHub has no transaction across the
    two writes. A failure here still leaves the created child behind, so it
    raises the same `forge.ForgePartialChildCreationError` a failed relation
    write inside `create_child` itself would -- one type, so `_cmd_cut`
    renders one recovery message for either, `step` naming what an
    identical re-run finishes.
    """
    try:
        client.update_item_body(removal.container, removal.new_body)
    except protocol.ClaimError as error:
        raise forge.ForgePartialChildCreationError(
            child=child,
            parent=removal.container,
            step=removal.step,
            cause=error,
            storage=storage,
        ) from error


class CutReason(StrEnum):
    """`aco cut`'s own `--json` `reason` vocabulary (issue #425,
    `specs/cut.spec.md`): `cut`/`adopted` mirror the text form's own
    `CUT`/`ADOPTED` verb -- whether `child` was freshly created or an
    already-open child GitHub already recorded (#260). Every refusal
    before any write is `precondition_failed`; a write that created the
    child but failed to finish recording it
    (`forge.ForgePartialChildCreationError`) is `partial_write` instead,
    carrying `written`/`failed` as structured siblings rather than only
    the prose sentence stderr already printed."""

    CUT = "cut"
    ADOPTED = "adopted"
    PRECONDITION_FAILED = "precondition_failed"
    PARTIAL_WRITE = "partial_write"


@dataclass(frozen=True)
class _CutOutcome:
    """What one `cut` did: the container, the row it linked (if any), the
    child it created or adopted, and whether it adopted."""

    container: int
    row_index: int | None
    child: int
    adopted: bool


def _print_cut_result(outcome: _CutOutcome, storage: body.Storage, *, as_json: bool) -> None:
    """Print `cut`'s result: the text form's `CUT`/`ADOPTED` verb becomes
    `--json`'s own `reason` (issue #425) -- `adopted` no longer needs its
    own boolean sibling once the envelope's `reason` already names it."""
    if as_json:
        report.emit_json(
            True,
            CutReason.ADOPTED if outcome.adopted else CutReason.CUT,
            container=outcome.container,
            row=outcome.row_index,
            child=outcome.child,
        )
        return
    suffix = "" if outcome.row_index is None else f" row {outcome.row_index}"
    verb = "ADOPTED" if outcome.adopted else "CUT"
    container_label = board.item_label(outcome.container, storage)
    print(f"{verb} {container_label}{suffix} -> {board.item_label(outcome.child, storage)}")


class _PartialWriteError(protocol.ClaimError):
    """Wraps `forge.ForgePartialCreationError` so `cut` and `item new`
    can choose `partial_write`'s own structured `--json` shape (`written`,
    `failed`) without parsing the wrapped error's prose (mirrors `ask`/
    `rule`'s own `_TargetUnavailableError`/`_InvalidTargetError`, issue
    #396); `recovery` is the caller's own way to finish the write."""

    def __init__(self, error: forge.ForgePartialCreationError, *, recovery: str) -> None:
        self.written = error.created
        self.failed = error.step
        super().__init__(f"{error}; {recovery}")


def _parent_line(container: int, storage: body.Storage) -> str:
    """The `Parent: <label>` line `cut` writes as a fresh child's first line
    -- the same wording issue bodies already use for this fact, naming
    `container` as `board.item_label` prints it (issue #467) -- and reads
    back to recognise its own orphan."""
    return f"Parent: {board.item_label(container, storage)}"


def _requested_body_scope(raw: list[str] | None) -> tuple[str, ...] | None:
    """A repeated `--scope` flag's canonical value, or `None` when it was
    never given -- `item new` and `cut` (issue #337) both take an optional
    `--scope`, so this is the one place either turns the raw flag list into
    the same canonical form `protocol.valid_scope` produces for `claim`."""
    return None if raw is None else protocol.valid_scope(raw)


def _requested_whole_reason(raw: str | None) -> str | None:
    """A `--whole` flag's own bounded text (issue #399), or `None` when it
    was never given -- `item new`'s own entry point into the same
    `protocol.outbound_text` bound `claim`'s own `--whole` already enforces
    (`_optional_whole_reason`), so the two never drift on what a legal
    reason looks like."""
    return None if raw is None else protocol.outbound_text(raw, _WHOLE_REASON_LABEL, maximum=512)


# Fixed text naming no child number (issue #606 line 2), so the child is
# written once, in the same create call that mints its number.
CUT_CHILD_NEXT = f"Build this slice; claim it with {board.advice_command('start')}."


def _cut_child_body(
    container: int,
    storage: body.Storage,
    scope: tuple[str, ...] | None = None,
    done_when: str | None = None,
) -> str:
    """The body `cut` writes for a fresh child: `_parent_line` above a fresh
    block whose `now` names the container it was cut from, whose `next` is
    `CUT_CHILD_NEXT`, and whose `done_when` is the linked row's own (issue
    #606), plus the cut slice's own top-level `scope = [...]` (issue #337)
    when the cut carries one -- the linked row's own scope, or a filled
    `--scope`. With no row `done_when` to take -- the row carries none, or
    the cut is untied -- that key stays empty, never a refusal. A repeat
    `cut` after a partial failure reads the parent line back
    (`_orphan_names_container`) to tell `container`'s own orphan apart from
    an unrelated open issue that merely shares the row's title (#260)."""
    fields: dict[str, object] = {
        "now": f"Cut from {board.item_label(container, storage)}",
        "next": CUT_CHILD_NEXT,
    }
    if done_when is not None:
        fields["done_when"] = done_when
    if scope is not None:
        fields["scope"] = list(scope)
    return body.prose_above_fresh_block(_parent_line(container, storage), fields)


def _orphan_names_container(raw_body: str, container: int, storage: body.Storage) -> bool:
    """Whether `raw_body`'s first line is the `_parent_line`
    `_cut_child_body` writes -- the one signal that tells `container`'s own
    orphan apart from another open issue, another container's own failed
    cut, or a human-filed issue that happens to share the row's title."""
    return body.first_line(raw_body) == _parent_line(container, storage)


def _adoptable_child(
    client: forge.ForgeWriter,
    container: int,
    title: str,
    config: board.BoardConfig,
    open_issues: Iterable[board.Issue],
) -> board.ChildItem | None:
    """`container`'s already-open child titled exactly `title`, so a repeat
    `cut` after a partial failure (`forge.ForgePartialChildCreationError`)
    adopts the child GitHub already recorded instead of risking a second one
    (#260). Two sources can carry that child: already linked under
    `container` (`list_children`), or an orphan -- one of the caller's own
    `open_issues` snapshot with no recorded parent at all, exactly the shape
    a failed `link_child` POST leaves behind. A title match alone is too
    weak to adopt an orphan: any unrelated open issue anywhere in the
    repository -- including one a human filed -- could share it. An orphan
    is adoptable only when it is also a `TASK` (never the container itself,
    never an idea-labelled item) and its body still names `container` as the
    parent `_cut_child_body` wrote for it; a recovery orphan is always
    exactly that shape, and nothing else can fake it. An untyped orphan
    (`forge.ForgeIssueTypeNotSetError`, issue #444) is never adopted: the
    twin search names it instead. An orphan match is linked under
    `container` right here before it is returned, so the caller's remaining steps treat it exactly
    like an already-linked child; the container's own issue is never created
    twice for it. More than one open match refuses by name rather than guess
    which one the failed cut actually created. A closed linked child with
    that title refuses too -- adoption finishes an interrupted cut, it does
    not reopen a closed one. `None` when nothing matches, so the caller
    falls through to `create_child`.
    """
    linked = [
        child
        for child in client.list_children(container)
        if client.item_reference(child.number).title == title
    ]
    open_linked = [child.number for child in linked if child.state is board.ChildState.OPEN]
    orphans = [
        issue.number
        for issue in open_issues
        if issue.title == title
        and issue.number != container
        and issue.kind is body.ItemKind.TASK
        and not board.has_label(issue.labels, config.idea_label)
        and _orphan_names_container(issue.body, container, config.storage)
        and client.parent_issue(issue.number) is None
    ]
    open_matches = open_linked + orphans
    container_label = board.item_label(container, config.storage)
    if len(open_matches) > 1:
        named = ", ".join(board.item_label(number, config.storage) for number in open_matches)
        raise protocol.ClaimUnavailableError(
            f"{container_label}'s row {title!r} matches more than one open issue ({named}); "
            "adopt the right one by hand and remove the row"
        )
    if open_matches:
        [number] = open_matches
        if number in orphans:
            client.link_child(container, number)
        return board.ChildItem(number, board.ChildState.OPEN)
    closed = next((child for child in linked if child.state is board.ChildState.CLOSED), None)
    if closed is None:
        return None
    raise protocol.ClaimUnavailableError(
        f"{container_label} already has a closed child "
        f"{board.item_label(closed.number, config.storage)} titled {title!r}; "
        "reopen it or remove the row by hand"
    )


# How far back a closed issue still counts for the twin search (issue #444):
# a duplicate usually repeats an item closed weeks, not months, ago.
TWIN_SEARCH_CLOSED_WINDOW = timedelta(days=30)
# Two titles are possible twins when at least this share of their combined
# distinct casefolded words appears in both (issue #444).
TWIN_TITLE_WORD_OVERLAP = 0.6
_TITLE_WORD = re.compile(r"\w+")


def _title_words(title: str) -> frozenset[str]:
    return frozenset(_TITLE_WORD.findall(title.casefold()))


def _title_overlap(title: str, other: str) -> float:
    """The share of both titles' combined distinct words they have in
    common; an identical title overlaps fully even without a single word,
    so a re-run is always named as its own earlier run's twin."""
    if other == title:
        return 1.0
    first, second = _title_words(title), _title_words(other)
    combined = first | second
    return len(first & second) / len(combined) if combined else 0.0


def _numbered_titles(issues: Iterable[board.Issue]) -> tuple[tuple[int, str], ...]:
    return tuple((issue.number, issue.title) for issue in issues)


def _possible_twin(title: str, candidates: Iterable[tuple[int, str]]) -> int | None:
    """The candidate whose title overlaps `title` most, at least
    `TWIN_TITLE_WORD_OVERLAP`, the lower number on a tie; `None` when no
    candidate reaches it."""
    hits = [
        (overlap, number)
        for number, other in candidates
        if (overlap := _title_overlap(title, other)) >= TWIN_TITLE_WORD_OVERLAP
    ]
    return min(hits, key=lambda hit: (-hit[0], hit[1]))[1] if hits else None


def _refuse_possible_twin(
    client: forge.ForgeReader,
    title: str,
    open_titles: Iterable[tuple[int, str]],
    *,
    parent: int | None,
    storage: body.Storage,
) -> None:
    """The one twin search `item new` and `cut` run before they create an
    issue (issue #444): `open_titles` -- every open issue's number and title
    -- and the titles of every issue closed within `TWIN_SEARCH_CLOSED_WINDOW`,
    never the new issue's own `parent`. A hit refuses by number;
    `--not-a-twin` is the caller's way past it."""
    since = datetime.now(UTC) - TWIN_SEARCH_CLOSED_WINDOW
    candidates = [
        *open_titles,
        *((issue.number, issue.title) for issue in client.list_recently_closed_issues(since)),
    ]
    twin = _possible_twin(title, (entry for entry in candidates if entry[0] != parent))
    if twin is not None:
        raise protocol.ClaimUnavailableError(
            f"possible twin {board.item_label(twin, storage)}; pass --not-a-twin"
        )


def _block_slice_entries(data: Mapping[str, object]) -> list[dict[str, object]]:
    value = data.get("slice")
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


def _cut_link(
    label: str, data: Mapping[str, object], row_number: int | None
) -> body.SliceRow | None:
    """Which `[[slice]]` entry `cut` links its fresh child to (#150 §7):
    without `--row`, the first entry when the block carries one; with `--row
    N`, the entry `N` names, refusing by name when the block has no `slice`
    key at all or no such row left (every remaining entry is cuttable: a
    linked entry is removed from `data["slice"]` at the moment it is cut)."""
    entries = _block_slice_entries(data)
    if row_number is None:
        return body.slice_row(entries[0]) if entries else None
    if "slice" not in data:
        raise protocol.ClaimUnavailableError(
            f"{label} has no slice table; --row needs one to select a row from"
        )
    match = next((entry for entry in entries if entry["index"] == row_number), None)
    if match is None:
        cuttable = ", ".join(str(entry["index"]) for entry in entries) or "none"
        raise protocol.ClaimUnavailableError(
            f"{label} has no row {row_number}; cuttable rows: {cuttable}"
        )
    return body.slice_row(match)


def _child_title(label: str, link: body.SliceRow | None, title: str | None) -> str:
    """The title `cut`'s child gets (issue #604): the linked row's own title,
    which a given `--title` must match exactly; with no linked row, `--title`
    itself, which is then required."""
    if link is None:
        if title is None:
            raise protocol.ClaimUnavailableError(f"{label} has no slice row; pass --title")
        return title
    if title is not None and title != link.title:
        raise protocol.ClaimUnavailableError(
            f"{label}'s slice {link.index} is titled {link.title!r}; --title must match it exactly"
        )
    return link.title


def _located_block_or_refuse(
    number: int, raw_body: str, *, command: str, storage: body.Storage = body.Storage.GITHUB
) -> body.LocatedBlock:
    """`raw_body`'s located `aco` block, or a by-name refusal before
    any write: `cut`, `rescope`, `rule`, `ask`, and `item edit --size` /
    `--whole` need a body `parse_body` reads as VALID before they rewrite
    its block, and share this one gate so their refusal has one shape.
    `storage` is forwarded to `parse_body` unchanged (issue #283): a state-ref item's own `[record]`
    table must read as a known key, not a malformed one."""
    parsed = body.parse_body(raw_body, storage=storage)
    if parsed.read_state is body.BodyReadState.MALFORMED:
        _refuse_malformed_block(
            number, body.body_defect_text(parsed.contract.defects[0]), command, storage
        )
    return body.locate_block(raw_body)


def _refuse_malformed_block(
    number: int, defect_text: str, command: str, storage: body.Storage
) -> NoReturn:
    raise protocol.ClaimUnavailableError(
        f"{board.item_label(number, storage)} {defect_text}; "
        f"{command} needs a valid {body.BLOCK_FENCE_INFO} block"
    )


CUT_ROW_SCOPE_ALREADY_SET = "slice {index} already names a scope; edit the container instead"


def _cut_row_scope(
    link: body.SliceRow | None, requested: tuple[str, ...] | None
) -> tuple[str, ...] | None:
    """The scope `cut`'s fresh child inherits (issue #337): the linked
    row's own scope when it already has one -- `--scope` then refuses by
    name, since the row is the one place to change it -- else `--scope`
    fills the (still empty) row and becomes the child's scope; with no
    linked row at all, `--scope` becomes the child's scope directly."""
    if link is not None and link.scope is not None:
        if requested is not None:
            raise protocol.ClaimUnavailableError(CUT_ROW_SCOPE_ALREADY_SET.format(index=link.index))
        return link.scope
    return requested


def _cut_row_done_when(
    number: int, located: body.LocatedBlock, link: body.SliceRow | None, storage: body.Storage
) -> str | None:
    """The `done_when` `cut`'s fresh child inherits (issue #606 line 2):
    the linked row's own, refused in CUT-05's form before any write when it
    breaks BODY-66 (CUT-39)."""
    if link is None:
        return None
    defect = body.slice_done_when_defect(located, link)
    if defect is not None:
        _refuse_malformed_block(number, defect, "cut", storage)
    return link.done_when


CUT_RERUN_RECOVERY = "re-run the same cut -- it adopts the child"
CUT_TYPE_RECOVERY = f"set that type on the forge by hand, then {CUT_RERUN_RECOVERY}"


def _cut_slice(
    client: forge.ForgeWriter,
    target: board.Issue,
    open_issues: Iterable[board.Issue],
    parsed: argparse.Namespace,
    config: board.BoardConfig,
) -> int:
    number = target.number
    storage = config.storage
    label = board.item_label(number, storage)
    located = _located_block_or_refuse(number, target.body, command="cut", storage=storage)
    link = _cut_link(label, located.data, parsed.row)
    title = _child_title(label, link, parsed.title)
    child_scope = _cut_row_scope(link, _requested_body_scope(parsed.scope))
    child_done_when = _cut_row_done_when(number, located, link, storage)
    adopted = _adoptable_child(client, number, title, config, open_issues)
    if adopted is None and not parsed.not_a_twin:
        _refuse_possible_twin(
            client, title, _numbered_titles(open_issues), parent=number, storage=storage
        )
    try:
        child = (
            adopted.number
            if adopted is not None
            else client.create_child(
                parent=number,
                title=title,
                body=_cut_child_body(number, storage, child_scope, child_done_when),
                kind=body.ItemKind.TASK,
            )
        )
        if link is not None:
            remaining = [
                entry
                for entry in _block_slice_entries(located.data)
                if entry["index"] != link.index
            ]
            new_data = {**located.data, "slice": remaining}
            removal = _SliceRowRemoval(
                container=number,
                new_body=body.replace_block(target.body, located, new_data),
                step=f"remove row {link.index} from {label}'s {body.BLOCK_FENCE_INFO} block",
            )
            _link_created_child(client, removal, child, storage)
    except forge.ForgeIssueTypeNotSetError as error:
        raise _PartialWriteError(error, recovery=CUT_TYPE_RECOVERY) from error
    except forge.ForgePartialChildCreationError as error:
        raise _PartialWriteError(error, recovery=CUT_RERUN_RECOVERY) from error
    outcome = _CutOutcome(
        container=number,
        row_index=None if link is None else link.index,
        child=child,
        adopted=adopted is not None,
    )
    _print_cut_result(outcome, storage, as_json=parsed.json)
    return 0


def _refuse_partial_write(
    error: _PartialWriteError, reason: CutReason | ItemReason, *, as_json: bool
) -> int:
    print(f"{report.CLI_ERROR_PREFIX}{error}", file=sys.stderr)
    if as_json:
        report.emit_json(
            False,
            reason,
            written=error.written,
            failed=error.failed,
            message=str(error),
        )
    return 2


def _cmd_cut(parsed: argparse.Namespace, context: RunContext) -> int:
    """`cut`'s own `--json` envelope (issue #425): a partial write reports
    through `_refuse_partial_write`'s own structured shape; every other
    refusal past the parser is `precondition_failed`, matching this
    command's single generic refusal bucket."""
    as_json = parsed.json
    try:
        client = context.forge_writer
        number = int(parsed.issue)
        for operation in (
            forge.ForgeOperation.CREATE_CHILD,
            forge.ForgeOperation.LINK_CHILD,
            forge.ForgeOperation.UPDATE_ITEM_BODY,
        ):
            if client.capability(operation) is not forge.Capability.READ_WRITE:
                raise protocol.ClaimUnavailableError(
                    f"this forge cannot {operation.value}; cut the slice by hand"
                )
        config = board_read.load_board_config(client, context)
        open_issues = client.list_open_board_issues()
        target = _cut_target(client, open_issues, number, config.storage)
        return _cut_slice(client, target, open_issues, parsed, config)
    except _PartialWriteError as error:
        return _refuse_partial_write(error, CutReason.PARTIAL_WRITE, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(CutReason.PRECONDITION_FAILED, error, as_json=as_json)


def _item_body_or_refuse(
    client: forge.ForgeReader, number: int, *, command: str, storage: body.Storage
) -> str:
    """The live body of issue `number`, or a by-name refusal before any
    write: `rule` and `ask` both target one existing issue, never a pull
    request -- a pull request exists only on a forge, so that refusal
    keeps the forge's own `#n`."""
    reference = client.item_reference(number)
    if reference.state is forge.ItemState.MISSING:
        raise protocol.ClaimUnavailableError(f"{board.item_label(number, storage)} does not exist")
    if reference.is_landing:
        raise protocol.ClaimUnavailableError(
            f"#{number} is a pull request, not an issue; {command} needs an issue"
        )
    return reference.body or ""


def _require_update_item_body(client: forge.ForgeWriter, *, command: str) -> None:
    if client.capability(forge.ForgeOperation.UPDATE_ITEM_BODY) is not forge.Capability.READ_WRITE:
        raise protocol.ClaimUnavailableError(
            f"this forge cannot update_item_body; {command} by hand"
        )


class _TargetUnavailableError(protocol.ClaimError):
    """`_require_writable_target`'s own "forge cannot write" refusal (issue
    #396) -- a distinct type from `_InvalidTargetError` so `ask`/`rule` can
    each choose their own `unavailable` without parsing prose."""


class _InvalidTargetError(protocol.ClaimError):
    """`_require_writable_target`'s own "no such writable item" refusal
    (issue #396) -- missing, a pull request, or a malformed body -- so
    `ask`/`rule` can each choose their own `invalid_item` without parsing
    prose."""


def _require_writable_target(
    client: forge.ForgeWriter, context: RunContext, number: int, *, command: str
) -> tuple[str, board.BoardConfig]:
    """`ask` and `rule`'s shared target gate (RULE-06..08, cited verbatim by
    `specs/ask.spec.md`): the forge must accept a body write, the item must
    exist and not be a pull request, and its body must parse -- in that
    order, unchanged from before issue #396 factored it out of both
    commands. Returns the live body and the board configuration `ask`/
    `rule` still need for their own write."""
    try:
        _require_update_item_body(client, command=command)
    except protocol.ClaimError as error:
        raise _TargetUnavailableError(str(error)) from error
    config = board_read.load_board_config(client, context)
    try:
        body = _item_body_or_refuse(client, number, command=command, storage=config.storage)
        _located_block_or_refuse(number, body, command=command, storage=config.storage)
    except protocol.ClaimError as error:
        raise _InvalidTargetError(str(error)) from error
    return body, config


def _rule_remaining_open(new_body: str, *, storage: body.Storage) -> int:
    return sum(
        1 for line in body.expectation_lines(new_body, storage=storage) if line.ruling is None
    )


class RuleReason(StrEnum):
    """`aco rule`'s own `--json` `reason` vocabulary (`specs/rule.spec.md`,
    issue #396): `ruled` the only success."""

    RULED = "ruled"
    ALREADY_RULED = "already_ruled"
    LINE_OUT_OF_RANGE = "line_out_of_range"
    INVALID_ITEM = "invalid_item"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


def _emit_rule_result(
    number: int,
    line: body.ExpectationLine,
    open_remaining: int,
    storage: body.Storage,
    *,
    as_json: bool,
) -> None:
    ruling = cast(str, line.ruling)
    ruled_on = cast(date, line.ruled_on)
    if as_json:
        report.emit_json(
            True,
            RuleReason.RULED,
            item=number,
            index=line.index,
            ruling=ruling,
            ruled_on=ruled_on.isoformat(),
            open=open_remaining,
        )
        return
    print(
        f"RULED {board.item_label(number, storage)} line {line.index} {ruling}; "
        f"{open_remaining} line(s) still open"
    )


def rule_item(
    context: RunContext, number: int, line: int, ruling: str, note: str | None
) -> tuple[body.ExpectationLine, int]:
    """`_cmd_rule`'s own write (issue #280): returns the newly ruled line and
    how many the item still has open; raises `protocol.ClaimError` by name
    for every refusal (already ruled, out of range, a bad outcome, a
    malformed or missing item), which `_cmd_rule` turns into its own
    by-name response."""
    client = context.forge_writer
    current_body, config = _require_writable_target(client, context, number, command="rule")
    ruled_on = datetime.now(UTC).date()
    new_body = body.rule_expectation(current_body, line, ruling, ruled_on, note=note)
    client.update_item_body(number, new_body)
    ruled_line = body.expectation_lines(new_body, storage=config.storage)[line - 1]
    return ruled_line, _rule_remaining_open(new_body, storage=config.storage)


_RuleItemError = (
    _TargetUnavailableError
    | _InvalidTargetError
    | body.ExpectationAlreadyRuledError
    | body.ExpectationOutOfRangeError
)


def _rule_item_reason(error: _RuleItemError) -> RuleReason:
    """`_cmd_rule`'s own mapping from `rule_item`'s four refusals to their
    `--json` `reason` (issue #396): a bad target names `unavailable`
    (forge cannot write) or `invalid_item` (missing item, pull request);
    a bad line names `already_ruled` or `line_out_of_range`."""
    if isinstance(error, _TargetUnavailableError):
        return RuleReason.UNAVAILABLE
    if isinstance(error, _InvalidTargetError):
        return RuleReason.INVALID_ITEM
    if isinstance(error, body.ExpectationAlreadyRuledError):
        return RuleReason.ALREADY_RULED
    return RuleReason.LINE_OUT_OF_RANGE


def _rule_expectation_line(parsed: argparse.Namespace, context: RunContext) -> int:
    """`rule`'s own work, every refusal raised by name for `_cmd_rule` to
    report."""
    number = int(parsed.item)
    ruled_line, open_remaining = rule_item(context, number, parsed.line, parsed.ruling, parsed.note)
    storage = context.config.storage
    _emit_rule_result(number, ruled_line, open_remaining, storage, as_json=parsed.json)
    return 0


def _cmd_rule(parsed: argparse.Namespace, context: RunContext) -> int:
    """`rule`'s own `--json` refusals (issue #396), for the whole command and
    not only its first steps (issue #432): the body write inside the shared
    ruling path can fail like any other forge call, and a failure there names
    this command's own `unavailable` rather than escaping the envelope."""
    as_json = parsed.json
    try:
        return _rule_expectation_line(parsed, context)
    except (
        _TargetUnavailableError,
        _InvalidTargetError,
        body.ExpectationAlreadyRuledError,
        body.ExpectationOutOfRangeError,
    ) as error:
        return report.refuse(_rule_item_reason(error), error, as_json=as_json)
    except RepoMeaninglessUnderStateRefError as error:
        return report.refuse(RuleReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(RuleReason.UNAVAILABLE, error, as_json=as_json)


@dataclass(frozen=True)
class _AskedLine:
    """One `aco ask` write's result (issue #295): the item, the fresh
    line's 1-based index, its `text`/`default`, and whichever card fields
    were given -- bundled so `_print_ask_result` takes one value instead of
    five loose ones."""

    item: int
    index: int
    text: str
    default: str
    card: body.ExpectationCardFields


class AskReason(StrEnum):
    """`aco ask`'s own `--json` `reason` vocabulary (`specs/ask.spec.md`,
    issue #396): `asked` the only success."""

    ASKED = "asked"
    INVALID_ITEM = "invalid_item"
    INVALID_EXPECTATION = "invalid_expectation"
    INVALID_PICTURE = "invalid_picture"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


def _emit_ask_result(asked: _AskedLine, storage: body.Storage, *, as_json: bool) -> None:
    if as_json:
        card_fields = {key: value for key, value in asdict(asked.card).items() if value is not None}
        report.emit_json(
            True,
            AskReason.ASKED,
            item=asked.item,
            index=asked.index,
            text=asked.text,
            default=asked.default,
            **card_fields,
        )
        return
    print(f"ASKED {board.item_label(asked.item, storage)} line {asked.index}: {asked.text}")


class _PictureFileError(protocol.ClaimError):
    """`_read_picture_file`'s own unreadable-file refusal (issue #396),
    typed so `aco ask`'s `--json` can choose `invalid_picture` without
    parsing prose."""


def _read_picture_file(path: str) -> str:
    """`--picture FILE.svg`'s own filesystem boundary (issue #295): read
    before any forge call, so a missing file refuses before the item body
    is even fetched. Content validation (size, `<svg>` root, no `<script>`,
    no external `href`) is `body.append_expectation`'s -- one owner, shared
    with the body parser's own defects."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise _PictureFileError(f"--picture {path} could not be read: {error}") from error


def _ask_target_reason(error: _TargetUnavailableError | _InvalidTargetError) -> AskReason:
    """`_cmd_ask`'s own mapping from `_require_writable_target`'s two
    target refusals to their `--json` `reason` (issue #396)."""
    if isinstance(error, _TargetUnavailableError):
        return AskReason.UNAVAILABLE
    return AskReason.INVALID_ITEM


def _ask_expectation_reason(
    error: body.ExpectationTextError | body.ExpectationFieldError,
) -> AskReason:
    """`_cmd_ask`'s own mapping from `append_expectation`'s two card-content
    refusals (issue #396) to their `--json` `reason`: a blank `--text`
    (`ExpectationTextError`) and a `--question`/`--example` failing its own
    rule both name `invalid_expectation`; only a refused `--picture`
    (`ExpectationFieldError` whose `field` is `picture`) names
    `invalid_picture`, per `specs/ask.spec.md`'s ASK-07/ASK-10 split."""
    if isinstance(error, body.ExpectationFieldError) and error.field == "picture":
        return AskReason.INVALID_PICTURE
    return AskReason.INVALID_EXPECTATION


def _append_expectation_card(parsed: argparse.Namespace, context: RunContext) -> int:
    """`ask`'s own work, every refusal raised by name for `_cmd_ask` to
    report: the picture file is read before the forge is ever resolved, so a
    missing one refuses before the item body is fetched."""
    picture = _read_picture_file(parsed.picture) if parsed.picture else None
    card = body.ExpectationCardFields(
        question=parsed.question, example=parsed.example, picture=picture
    )
    client = context.forge_writer
    number = int(parsed.item)
    current_body, config = _require_writable_target(client, context, number, command="ask")
    new_body = body.append_expectation(current_body, parsed.text, parsed.default, card=card)
    index = len(body.expectation_lines(new_body, storage=config.storage))
    client.update_item_body(number, new_body)
    asked = _AskedLine(
        item=number, index=index, text=parsed.text, default=parsed.default, card=card
    )
    _emit_ask_result(asked, config.storage, as_json=parsed.json)
    return 0


def _cmd_ask(parsed: argparse.Namespace, context: RunContext) -> int:
    """`ask`'s own `--json` refusals (issue #396), for the whole command and
    not only its first steps (issue #432): the body write this command ends
    with can fail like any other forge call, and a failure there names this
    command's own `unavailable` rather than escaping the envelope."""
    as_json = parsed.json
    try:
        return _append_expectation_card(parsed, context)
    except _PictureFileError as error:
        return report.refuse(AskReason.INVALID_PICTURE, error, as_json=as_json)
    except (_TargetUnavailableError, _InvalidTargetError) as error:
        return report.refuse(_ask_target_reason(error), error, as_json=as_json)
    except (body.ExpectationTextError, body.ExpectationFieldError) as error:
        return report.refuse(_ask_expectation_reason(error), error, as_json=as_json)
    except RepoMeaninglessUnderStateRefError as error:
        return report.refuse(AskReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(AskReason.UNAVAILABLE, error, as_json=as_json)


@dataclass(frozen=True)
class _CommandEntry:
    """One command's parser builder and handler (issue #372: one table
    instead of a `_SUBPARSER_BUILDERS`/`_READ_HANDLERS`/`_WRITE_HANDLERS`/
    `_FORGE_FREE_COMMANDS` quartet keyed by the same names). Every handler
    takes the parsed arguments and the run's `RunContext`; `release` also
    takes the branch `_dispatch` read before it started."""

    add_parser: Callable[[_Subcommands], None]
    handler: Callable[..., int | None]


_COMMAND_TABLE: dict[str, _CommandEntry] = {
    "bootstrap": _CommandEntry(
        _add_bootstrap_parser, lambda _parsed, context: cmd_bootstrap.run(context)
    ),
    "reset": _CommandEntry(_add_reset_parser, cmd_reset.run),
    "board": _CommandEntry(_add_board_parser, cmd_board.run),
    "rulings": _CommandEntry(_add_rulings_parser, cmd_rulings.run),
    "next": _CommandEntry(_add_next_parser, _cmd_next),
    "start": _CommandEntry(_add_start_parser, _cmd_start),
    "claim": _CommandEntry(_add_claim_parser, _cmd_claim),
    "release": _CommandEntry(_add_release_parser, cmd_release.run),
    "land": _CommandEntry(_add_land_parser, _cmd_land),
    "rescope": _CommandEntry(_add_rescope_parser, _cmd_rescope),
    "cut": _CommandEntry(_add_cut_parser, _cmd_cut),
    "ask": _CommandEntry(_add_ask_parser, _cmd_ask),
    "rule": _CommandEntry(_add_rule_parser, _cmd_rule),
    "check": _CommandEntry(_add_check_parser, cmd_check.run),
    "brief": _CommandEntry(_add_brief_parser, _cmd_brief),
}


def _dispatch_item(parsed: argparse.Namespace, context: RunContext) -> int:
    """`item`'s own four subcommands, pulled out of `_dispatch` (issue #372
    S1) so their nesting stops counting against every other command's
    cognitive complexity."""
    if parsed.item_command == "new":
        return _cmd_item_new(parsed, context)
    if parsed.item_command == "edit":
        return _cmd_item_edit(parsed, context)
    if parsed.item_command == "close":
        return _cmd_item_close(parsed, context)
    return _cmd_item_show(parsed, context)


def _resolved_before_the_command_starts(parsed: argparse.Namespace) -> str | None:
    """Everything a writer needs settled before its own command starts
    (issue #425): the agent identity it claims under, and `release`'s own
    branch and override checks, which read the checkout rather than the
    claim record. Returns `release`'s branch, `None` for every other
    command."""
    if parsed.command in {"claim", "release", "rescope", "land"}:
        parsed.agent = checkout.resolved_agent(parsed.agent)
    return cmd_release.release_branch_for(parsed) if parsed.command == "release" else None


def _dispatch(parsed: argparse.Namespace, context: RunContext) -> int:
    # Only the pre-start checks report through the shared envelope (issue
    # #425); a refusal a command raises itself owns its own `reason`, so the
    # dispatch below stays outside this boundary.
    try:
        release_branch = _resolved_before_the_command_starts(parsed)
    except protocol.ClaimError as error:
        return report.refuse(
            PreDispatchReason.PRECONDITION_FAILED,
            error,
            as_json=bool(getattr(parsed, "json", False)),
        )
    if parsed.command == "item":
        return _dispatch_item(parsed, context)
    entry = _COMMAND_TABLE[parsed.command]
    if parsed.command == "release":
        # The release branch is dispatch data, read before the command
        # starts, never a repository fact the context would hold (#418).
        result = entry.handler(parsed, context, release_branch)
    else:
        result = entry.handler(parsed, context)
    return 0 if result is None else result


def _read_status_body_or_dispatch(parsed: argparse.Namespace, context: RunContext) -> int:
    """`status` and `body` are forge-free (issue #245, #262): both are
    resolved here, ahead of `_dispatch`, and neither ever asks the
    `RunContext` for its forge."""
    if parsed.command == "status":
        return _cmd_status(parsed, context)
    if parsed.command == "body":
        return _cmd_body(parsed, context)
    return _dispatch(parsed, context)


def _spells_json_flag(token: str, parser: _UsageErrorParser) -> bool:
    """Whether `parser` itself would read `token` as its own `--json`: the
    exact spelling on a parser that declares it, never an abbreviation, since
    no `aco` parser reads one (OUT-09)."""
    spelling = token.split("=", 1)[0]
    return spelling == report.JSON_FLAG and any(
        report.JSON_FLAG in action.option_strings for action in parser.declared_actions
    )


def _level_options(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """The tokens one parser level still reads as options. A bare `--` ends
    that level's options and nothing else's: argparse marks the rest of this
    level's tokens as non-options, then hands what follows the command name
    down untouched, and the next level scans it for a `--` of its own."""
    return tokens[: tokens.index(LONG_OPTION_PREFIX)] if LONG_OPTION_PREFIX in tokens else tokens


def _asked_for_json(root: _UsageErrorParser, given: list[str]) -> bool:
    """Whether this invocation asked for JSON, answered by the parsers it
    reached rather than by the raw tokens alone (issue #432): only a command
    declaring `--json` can answer in the envelope, so `aco bootstrap --json`
    stays argparse's own text, and so does `aco release --jso`, an
    abbreviation no parser reads (OUT-09). Each level is asked about its own tokens,
    the ones argparse handed it, so a `--` cuts that level alone."""
    return any(
        _spells_json_flag(token, parser)
        for parser, tokens in _reached_levels(root, given)
        for token in _level_options(tokens)
    )


def _reached_levels(
    root: _UsageErrorParser, given: list[str]
) -> Iterator[tuple[_UsageErrorParser, tuple[str, ...]]]:
    """Each parser this invocation's parse reached, root first, with the
    tokens argparse handed that level (issue #432)."""
    parser, tokens = root, tuple(given)
    while True:
        yield parser, tokens
        level = parser.subcommands.chosen() if parser.subcommands else None
        if level is None:
            return
        parser, tokens = level


# Every argparse `type=` that reads an item reference. `check`'s subject also
# reads a trunk commit id, which parses to a string and so names no item.
_ITEM_ARGUMENT_TYPES = frozenset({board.parse_item_reference, _parse_check_subject})


def _item_arguments(
    root: _UsageErrorParser, given: list[str], parsed: argparse.Namespace
) -> Iterator[int]:
    """Every item number this invocation named: the parsed integer of each
    argument an `_ITEM_ARGUMENT_TYPES` parser types, on every parser the
    parse reached."""
    for parser, _tokens in _reached_levels(root, given):
        for action in parser.declared_actions:
            value = getattr(parsed, action.dest, None)
            if action.type in _ITEM_ARGUMENT_TYPES and isinstance(value, int):
                yield value


def _refuse_item_past_the_id_space(
    root: _UsageErrorParser,
    given: list[str],
    parsed: argparse.Namespace,
    context: RunContext,
) -> int | None:
    """PIN-31 (issue #467, #469 review): under `storage = "state-ref"` a
    number past `aco-ffffff` names no item, and `items.format_item_id` would
    print it as an id `board.parse_item_reference` refuses back -- so it
    refuses here, before any command looks it up or names it. The storage
    pin is read only for such a number; a pin that cannot be read is left to
    the command, which meets the same refusal and reports it in its own
    envelope."""
    past = next(
        (
            number
            for number in _item_arguments(root, given, parsed)
            if board.names_no_item(number, body.Storage.STATE_REF)
        ),
        None,
    )
    if past is None or not _pins_state_ref(context):
        return None
    error = protocol.ClaimUnavailableError(STATE_REF_ITEM_PAST_THE_ID_SPACE.format(number=past))
    return report.refuse(
        PreDispatchReason.INVALID_USAGE, error, as_json=_asked_for_json(root, given)
    )


def _pins_state_ref(context: RunContext) -> bool:
    """Whether this checkout's readable storage pin says `state-ref`; an
    unreadable pin says nothing here, so its refusal stays the command's."""
    try:
        return context.config.storage is body.Storage.STATE_REF
    except protocol.ClaimError:
        return False


def main(arguments: list[str] | None = None) -> int:
    # Every refusal the parse itself raises -- argparse's own usage errors,
    # and `board.parse_item_reference`, an argparse `type=` whose refusal is
    # a `ClaimError` -- fires before any namespace carries `--json`, so the
    # mode is read back off the parsers this parse reached (issue #432).
    # Both report `invalid_usage` through the one envelope. Past the parse
    # the plain sentence alone still stands: a refusal a command raises
    # outside its own reported vocabulary must not be dressed as one
    # (issue #425).
    given = sys.argv[1:] if arguments is None else arguments
    parser = _parser()
    try:
        parsed = parser.parse_args(given)
        # Judged after the parse, not as an argparse `type=`: `--repo`
        # precedes the subcommand, so a refusal raised while argparse reads
        # it would fire before the parse reached the command that decides
        # whether this run asked for JSON (issue #465).
        parsed.repo = None if parsed.repo is None else github.repository_id(parsed.repo)
    except _UsageError as error:
        return _refuse_usage(error, as_json=_asked_for_json(parser, given))
    except protocol.ClaimError as error:
        return report.refuse(
            PreDispatchReason.INVALID_USAGE, error, as_json=_asked_for_json(parser, given)
        )
    try:
        if parsed.command in {"_run-at-login", "register", "run", "login"}:
            return cmd_workspace.run(parsed)
        if parsed.command == "protect":
            return cmd_protect.run()
        context = _run_context(parsed.repo)
        refusal = _refuse_item_past_the_id_space(parser, given, parsed, context)
        return refusal if refusal is not None else _read_status_body_or_dispatch(parsed, context)
    except protocol.ClaimError as error:
        print(f"{report.CLI_ERROR_PREFIX}{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
