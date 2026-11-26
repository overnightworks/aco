"""The `board` command (`specs/board.spec.md`)."""
# ruff: noqa: T201 - the board command writes its URL to stdout

import argparse
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

from . import board_link, board_read, protocol, recurring_audit, report, workboard
from .session import RepoMeaninglessUnderStateRefError, RunContext


class _BoardReason(StrEnum):
    """`aco board`'s own `--json` `reason` vocabulary
    (`specs/board.spec.md`): `projected` the only success. `invalid_usage`
    covers a bare `aco board` naming neither `--json` nor `--url` (BOARD-44) and `--repo`
    under `storage = state-ref` (PIN-04); every other refusal -- an
    unsupported forge host (BOARD-02), a state-ref checkout with no
    resolvable default branch (PIN-05) -- falls to `unavailable`, matching
    `ask`/`rule`/`brief`'s own catch-all."""

    PROJECTED = "projected"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


class _BoardNoModeUsageError(protocol.ClaimError):
    """A `board` call that names no mode, or mixes flags that belong to different
    modes (BOARD-44, BOARD-62): `board` has no default mode of its own."""


_BOARD_NO_MODE_MESSAGE = "aco board requires --json or --url"
_BOARD_BOTH_MODES_MESSAGE = "aco board takes --json or --url, not both"
_BOARD_LINK_ARGUMENTS_MESSAGE = "an item and --line belong to --url"
_BOARD_LINE_WITHOUT_ITEM_MESSAGE = "--line names a card of an item; give the item"

# The shape one decoded JSON object takes -- one alias so `cast` names a
# real type instead of repeating the `"dict[str, object]"` string literal
# (python:S1192). `board_payload`'s own JSON-projection concern, unrelated
# to `body.py`'s identically-shaped alias for its TOML rendering -- kept
# local rather than shared across that boundary for two unrelated readers.
_JsonObject = dict[str, object]

# The shape a decoded homogeneous array of tables, or an `asdict`'d list of
# dataclasses, takes -- one alias so `cast` names a real type instead of
# repeating the string.
_JsonRows = list[_JsonObject]


def _reference_label(reference: _JsonObject) -> str:
    return f"{reference['repository']}#{reference['number']}"


def _project_blocker_references(entry: dict[str, object], key: str, repository: str) -> None:
    """Rewrite `entry[key]` (a list of `asdict`'d `IssueReference`s) into the
    earlier local-int list plus a sibling `foreign_blockers` key (A2) -- the
    one projector `board_payload` uses for both `BoardItem.open_blockers`
    and each open child's `ChildItem.blocked_by`, never a mixed `int | str`
    list and never re-parsed from a label."""
    references = cast(_JsonRows, entry.pop(key))
    entry[key] = [
        reference["number"] for reference in references if reference["repository"] == repository
    ]
    entry["foreign_blockers"] = [
        _reference_label(reference)
        for reference in references
        if reference["repository"] != repository
    ]


def _project_foreign_children(container: dict[str, object]) -> None:
    """Rewrite `container["foreign_children"]` (a list of `asdict`'d
    `IssueReference`s) into `"<repository>#<n>"` strings (BOARD-59)."""
    references = cast(_JsonRows, container["foreign_children"])
    container["foreign_children"] = [_reference_label(reference) for reference in references]


def _project_uncut_row_scope(finding: dict[str, object]) -> None:
    """Drop a `None` `scope` from one uncut row's JSON dict rather than
    printing it: the public shape is
    `{"index", "title"}` with no third key, and `board --json` owes
    that to a row that names no scope of its own -- only a row that
    actually carries one gains the extra `"scope"` key, canonical and
    non-empty. A row's `done_when` is `cut`'s to read, never
    part of `board --json`'s row shape (BOARD-14)."""
    for row in cast(_JsonRows, finding["rows"]):
        del row["done_when"]
        if row["scope"] is None:
            del row["scope"]


def _project_landing_row(row: dict[str, object]) -> None:
    """One `LandingRow`'s JSON shape: `committed_at` turned to
    ISO text like every other board timestamp, and `evidence` -- a nested
    `TrunkLandingEvidence`/`PullRequestLandingEvidence` dict after `asdict`
    -- flattened into `sha`/`pull_request`, exactly one of which is ever
    non-`null`, so a consumer never has to branch on which evidence
    dataclass produced a row."""
    row["committed_at"] = cast(datetime, row["committed_at"]).astimezone(UTC).isoformat()
    evidence = cast(_JsonObject, row.pop("evidence"))
    row["sha"] = evidence.get("sha")
    row["pull_request"] = evidence.get("number")


def _tuples_to_lists(value: object) -> object:
    """`asdict(board)` preserves every tuple-typed dataclass field as a
    tuple; a JSON array carries no such distinction, so `board_payload`
    walks the finished payload once more here and turns every tuple into a
    list -- the one place this module guarantees its own return is
    genuinely JSON-shaped, the same way every other command's hand-built
    `--json` payload in the `cmd_*` modules already is."""
    if isinstance(value, dict):
        return {key: _tuples_to_lists(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_tuples_to_lists(item) for item in value]
    return value


def board_payload(board: workboard.Board) -> dict[str, object]:
    """`board`'s own `--json`/envelope payload: every value
    already JSON-primitive -- dates and datetimes turned to ISO text,
    blocker references split and re-keyed, every tuple turned into a list
    -- so `report.emit_json` can serialize it with a plain `json.dumps`,
    with no `default=` fallback of its own. The one owner both `board
    --json` and a future embedded read share."""
    payload = asdict(board)
    repository = payload.pop("repository")
    for group in ("items", "ready_now", "stale", "recovery"):
        for item in payload[group]:
            freed_on = item["freed_on"]
            item["freed_on"] = (
                None if freed_on is None else freed_on.astimezone(UTC).date().isoformat()
            )
            item.pop("terminal_actionable_reason")
            item.pop("read_state")
            item.pop("childless_verdict")
            # `whole` feeds `next`'s advice only; board.spec
            # names no such `--json` key.
            item.pop("whole")
            # `waiting_on_operator` is `next`'s own projection;
            # board.spec names no such per-item `--json` key.
            item.pop("waits_on_operator")
            _project_blocker_references(item, "open_blockers", repository)
            container = item["container"]
            if container is not None:
                _project_foreign_children(container)
                for child in container["open_children"]:
                    child.pop("title")  # the row's public shape carries no title
                    _project_blocker_references(child, "blocked_by", repository)
    for row in cast(_JsonRows, payload["landings"]):
        _project_landing_row(row)
    for finding in cast(_JsonRows, payload["uncut"]):
        _project_uncut_row_scope(finding)
    return cast(_JsonObject, _tuples_to_lists(payload))


def startable_payload(
    board: workboard.Board, audits: Iterable[recurring_audit.Finding]
) -> dict[str, object]:
    """What can start on `board`, the embedded read `aco mcp` serves: every item of
    `ready_now` in rank order, every container with an uncut slice, and the names of
    the due recurring `audits`."""
    return {
        "startable": [
            {
                "number": item.number,
                "title": item.title,
                "kind": item.kind,
                "size": item.size,
                "priority_bucket": item.priority_bucket,
                "next": item.contract.next,
            }
            for item in board.ready_now
        ],
        "uncut": [
            {
                "item": uncut.item,
                "index": uncut.rows[0].index,
                "title": uncut.rows[0].title,
                "rows": len(uncut.rows),
            }
            for uncut in board.uncut
        ],
        "audits_due": [finding.entry.name for finding in audits if finding.is_due],
    }


def startable_reading(context: RunContext) -> dict[str, object]:
    """`startable_payload` of the board `context` is bound to; raises
    `protocol.ClaimError` when that board cannot be read."""
    observed = board_read.observed_board(context)
    return startable_payload(
        observed.board, board_read.recurring_audit_reading(context, observed.trunk_landings)
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """`board`'s flags: `--json`, or `--url` with the item and `--line` it takes."""
    report.add_json_flag(parser, "JSON only")
    parser.add_argument(
        "--url",
        action="store_true",
        help="print the board's address; with an item its step's link, with --line its card's",
    )
    parser.add_argument(
        "item",
        nargs="?",
        type=workboard.parse_item_reference,
        help="with --url, an item, as aco-xxxxxx, #n, or the bare number n",
    )
    parser.add_argument(
        "--line", type=int, metavar="K", help="with --url and an item, the card's line"
    )


def _usage_refusal(parsed: argparse.Namespace) -> str | None:
    """The sentence naming what the flags got wrong, or `None` when they name
    exactly one mode with arguments that belong to it."""
    if parsed.json and parsed.url:
        return _BOARD_BOTH_MODES_MESSAGE
    if not parsed.json and not parsed.url:
        return _BOARD_NO_MODE_MESSAGE
    if not parsed.url and (parsed.item is not None or parsed.line is not None):
        return _BOARD_LINK_ARGUMENTS_MESSAGE
    if parsed.line is not None and parsed.item is None:
        return _BOARD_LINE_WITHOUT_ITEM_MESSAGE
    return None


def _selection(
    parsed: argparse.Namespace, context: RunContext
) -> board_link.CardLink | board_link.StepLink | None:
    """The card (`--line`) or step the URL opens, `None` for the board itself."""
    if parsed.item is None:
        return None
    repository = context.repository_id.path
    if parsed.line is None:
        return board_link.StepLink(repository, parsed.item)
    return board_link.CardLink(repository, parsed.item, parsed.line)


def _print_url(parsed: argparse.Namespace, context: RunContext) -> int:
    """The board's address, or the card's or step's link: the URL and a newline."""
    url = board_link.configured_board_url(_selection(parsed, context))
    # The URL is this command's whole output: a head pastes it as it is.
    print(url)
    return 0


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    as_json = parsed.json
    try:
        usage_refusal = _usage_refusal(parsed)
        if usage_refusal is not None:
            raise _BoardNoModeUsageError(usage_refusal)
        if parsed.url:
            return _print_url(parsed, context)
        projected = board_read.observed_board(context).board
    except _BoardNoModeUsageError as error:
        return report.refuse(_BoardReason.INVALID_USAGE, error, as_json=as_json)
    except RepoMeaninglessUnderStateRefError as error:
        return report.refuse(_BoardReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_BoardReason.UNAVAILABLE, error, as_json=as_json)
    report.emit_json(True, _BoardReason.PROJECTED, **board_payload(projected))
    return 0
