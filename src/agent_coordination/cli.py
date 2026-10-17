"""Coordinate coding-agent claims through this repository's own state ref."""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn, cast

from . import (
    __version__,
    board,
    board_read,
    body,
    checkout,
    cmd_board,
    cmd_bootstrap,
    cmd_check,
    cmd_claim,
    cmd_land,
    cmd_next,
    cmd_protect,
    cmd_release,
    cmd_rescope,
    cmd_reset,
    cmd_rulings,
    cmd_start,
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
        default=cmd_claim.DEFAULT_CLAIM_ROLE,
        help=f"the claiming role; default {cmd_claim.DEFAULT_CLAIM_ROLE}",
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
    body-shape decision `check <item>`'s own `cmd_check._CheckReason` reads."""

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
        board_read.require_update_item_body(client, command=ITEM_EDIT_SIZE_COMMAND)
        number = parsed.item
        storage = context.config.storage
        current_body = board_read.item_body_or_refuse(
            client, number, command=ITEM_EDIT_SIZE_COMMAND, storage=storage
        )
        located = board.located_block_or_refuse(
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
        board_read.require_update_item_body(client, command=ITEM_EDIT_WHOLE_COMMAND)
        number = parsed.item
        storage = context.config.storage
        current_body = board_read.item_body_or_refuse(
            client, number, command=ITEM_EDIT_WHOLE_COMMAND, storage=storage
        )
        located = board.located_block_or_refuse(
            number, current_body, command=ITEM_EDIT_WHOLE_COMMAND, storage=storage
        )
        reason = cast(str, policy.bounded_whole_reason(parsed.whole))
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
    (`policy.bounded_whole_reason`), so the two never drift on what a legal
    reason looks like."""
    return policy.bounded_whole_reason(raw)


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
        board.refuse_malformed_block(number, defect, "cut", storage)
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
    located = board.located_block_or_refuse(number, target.body, command="cut", storage=storage)
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
        board_read.require_update_item_body(client, command=command)
    except protocol.ClaimError as error:
        raise _TargetUnavailableError(str(error)) from error
    config = board_read.load_board_config(client, context)
    try:
        body = board_read.item_body_or_refuse(
            client, number, command=command, storage=config.storage
        )
        board.located_block_or_refuse(number, body, command=command, storage=config.storage)
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
    "next": _CommandEntry(_add_next_parser, cmd_next.run),
    "start": _CommandEntry(_add_start_parser, cmd_start.run),
    "claim": _CommandEntry(_add_claim_parser, cmd_claim.run),
    "release": _CommandEntry(_add_release_parser, cmd_release.run),
    "land": _CommandEntry(_add_land_parser, cmd_land.run),
    "rescope": _CommandEntry(_add_rescope_parser, cmd_rescope.run),
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
