"""The `rulings` command (`specs/rulings.spec.md`)."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from . import board_read, body, expectation_grammar, expectations, protocol, report, workboard
from .session import RepoMeaninglessUnderStateRefError, RunContext


@dataclass(frozen=True)
class _RulingsRow:
    """One `rulings` row: the item, its open/total counts, and every one of
    its `[[expectation]]` lines (open and already-ruled alike) in block
    order -- the detail `rulings` prints beneath the item's own summary."""

    item: workboard.BoardItem
    progress: body.ExpectationProgress
    lines: tuple[expectations.ExpectationLine, ...]


def _rulings_rows(
    projected: workboard.Board, bodies: Mapping[int, str], *, storage: body.Storage
) -> tuple[_RulingsRow, ...]:
    """Every open board item that carries at least one `[[expectation]]`
    line, fully ruled ones included -- items with an open line
    first, board-ranked then by fewer open lines then issue number,
    then the fully ruled items in that same
    order. Each row is paired with its lines read fresh from `bodies` --
    `projected.items` itself carries only the open/total counters. `storage`
    is forwarded to `expectations.expectation_lines` unchanged: a state-ref
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
            item,
            progress,
            expectations.expectation_lines(bodies.get(item.number, ""), storage=storage),
        )
        for item, progress in ranked
    )


def _rulings_option_json(option: expectations.CardOption) -> dict[str, object]:
    result: dict[str, object] = {"same_as_today": True}
    if option.result is not None:
        result = {"picture": option.result.picture}
        if option.result.caption is not None:
            result["caption"] = option.result.caption
    return {
        "letter": option.letter,
        "name": option.name,
        "effect": option.effect,
        **result,
        "notice": option.notice,
        "cost": option.cost,
        "undo": option.undo.value,
        "undo_how": option.undo_how,
        "contract": option.contract,
    }


def _rulings_option_line_card_json(line: expectations.OptionLine) -> dict[str, object]:
    return {
        "question": line.question,
        "problem": line.problem,
        "picture": line.picture,
        "caption": line.caption,
        "decision_kind": line.decision_kind.value,
        "area": line.area,
        "topic": line.topic,
        "recommended": line.recommended,
        "reason": line.reason,
        "options": [_rulings_option_json(option) for option in line.options],
    }


def _rulings_yes_no_card_json(line: expectations.YesNoLine) -> dict[str, object]:
    return {
        key: value
        for key, value in (
            ("question", line.question),
            ("example", line.example),
            ("picture", line.picture),
        )
        if value is not None
    }


def _rulings_line_json(line: expectations.ExpectationLine) -> dict[str, object]:
    """RUL-10, RUL-12..RUL-17: a yes/no line keeps its original keys; an option line
    adds `form`, the current and the stored card hash, how it was decided,
    whether it is with its head, then its card."""
    shared = {
        "index": line.index,
        "text": line.text,
        "ruling": line.ruling,
        "ruled_on": line.ruled_on.isoformat() if line.ruled_on is not None else None,
    }
    if isinstance(line, expectations.YesNoLine):
        return {**shared, "default": line.default, **_rulings_yes_no_card_json(line)}
    decision = line.decision
    return {
        "index": line.index,
        "form": line.form.value,
        **{key: shared[key] for key in ("text", "ruling", "ruled_on")},
        "default": None,
        "card_hash": line.card_hash,
        "stored_card_hash": None if decision is None else decision.card_hash,
        "via": None if decision is None else decision.via.value,
        expectation_grammar.OTHER: line.other_answer,
        expectation_grammar.RETURNED_ON: (
            None if line.returned is None else line.returned.returned_on.isoformat()
        ),
        expectation_grammar.RETURNED_NOTE: None if line.returned is None else line.returned.note,
        **_rulings_option_line_card_json(line),
    }


def _rulings_line_text(line: expectations.ExpectationLine) -> str:
    state = expectations.expectation_line_state(line)
    summary = protocol.terminal_text(expectations.expectation_line_summary(line))
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
    """`aco rulings`' own `--json` `reason` vocabulary
    (`specs/rulings.spec.md`): `listed` the only success. `invalid_usage`
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
