"""The `rulings` command (`specs/rulings.spec.md`)."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from . import board_read, body, protocol, report, workboard
from .session import RepoMeaninglessUnderStateRefError, RunContext


@dataclass(frozen=True)
class _RulingsRow:
    """One `rulings` row: the item, its open/total counts, and every one of
    its `[[expectation]]` lines (open and already-ruled alike) in block
    order -- the detail `rulings` prints beneath the item's own summary."""

    item: workboard.BoardItem
    progress: body.ExpectationProgress
    lines: tuple[body.ExpectationLine, ...]


def _rulings_rows(
    projected: workboard.Board, bodies: Mapping[int, str], *, storage: body.Storage
) -> tuple[_RulingsRow, ...]:
    """Every open board item that carries at least one `[[expectation]]`
    line, fully ruled ones included (issue #379) -- items with an open line
    first, board-ranked then by fewer open lines then issue number
    (unchanged from before #240), then the fully ruled items in that same
    order. Each row is paired with its lines read fresh from `bodies` --
    `projected.items` itself carries only the open/total counters. `storage`
    is forwarded to `body.expectation_lines` unchanged (issue #248): a state-ref
    body's `[record]` table must read as a known key, not a malformed one."""
    ranked = sorted(
        (
            (item, item.expectation_progress)
            for item in projected.items
            if item.expectation_progress.total > 0
        ),
        key=lambda entry: (
            0 if entry[1].open > 0 else 1,
            *workboard.board_rank(entry[0])[:2],
            entry[1].open,
            entry[0].number,
        ),
    )
    return tuple(
        _RulingsRow(
            item, progress, body.expectation_lines(bodies.get(item.number, ""), storage=storage)
        )
        for item, progress in ranked
    )


def _rulings_line_json(line: body.ExpectationLine) -> dict[str, object]:
    payload: dict[str, object] = {
        "index": line.index,
        "text": line.text,
        "ruling": line.ruling,
        "ruled_on": line.ruled_on.isoformat() if line.ruled_on is not None else None,
        "default": line.default,
    }
    payload.update(
        (key, value)
        for key, value in (
            ("question", line.question),
            ("example", line.example),
            ("picture", line.picture),
        )
        if value is not None
    )
    return payload


def _rulings_line_text(line: body.ExpectationLine) -> str:
    state = body.expectation_line_state(line)
    summary = protocol.terminal_text(body.expectation_line_summary(line))
    return f"  {line.index} {state}: {summary}"


def _rulings_row_text(row: _RulingsRow, storage: body.Storage) -> str:
    label = workboard.item_label(row.item.number, storage)
    title = protocol.terminal_text(row.item.title)
    header = f"{label} {row.progress.open}/{row.progress.total}: {title}"
    return "\n".join((header, *(_rulings_line_text(line) for line in row.lines)))


def _rulings(
    projected: workboard.Board, bodies: Mapping[int, str], *, as_json: bool, storage: body.Storage
) -> None:
    rows = _rulings_rows(projected, bodies, storage=storage)
    if as_json:
        report.emit_json(
            True,
            _RulingsReason.LISTED,
            rulings=[
                {
                    "number": row.item.number,
                    "title": row.item.title,
                    "open": row.progress.open,
                    "total": row.progress.total,
                    "lines": [_rulings_line_json(line) for line in row.lines],
                }
                for row in rows
            ],
        )
        return
    if not rows:
        print("No expectation lines.")
        return
    print("\n".join(_rulings_row_text(row, storage) for row in rows))


class _RulingsReason(StrEnum):
    """`aco rulings`' own `--json` `reason` vocabulary (issue #412,
    `specs/rulings.spec.md`): `listed` the only success. `invalid_usage`
    covers `--repo` under `storage = state-ref` (PIN-04); every other
    refusal -- an unsupported forge host (BOARD-02), a state-ref checkout
    with no resolvable default branch (PIN-05) -- falls to `unavailable`,
    matching `ask`/`rule`/`brief`'s own catch-all."""

    LISTED = "listed"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    as_json = parsed.json
    try:
        issues = context.forge.list_open_board_issues()
        projected = board_read.observed_board(context, issues=issues).board
        bodies = {issue.number: issue.body for issue in issues}
        storage = context.config.storage
    except RepoMeaninglessUnderStateRefError as error:
        return report.refuse(_RulingsReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_RulingsReason.UNAVAILABLE, error, as_json=as_json)
    _rulings(projected, bodies, as_json=as_json, storage=storage)
    return 0
