"""The `rulings` command (`specs/rulings.spec.md`)."""
# ruff: noqa: T201 - the rulings command writes its result lines to stdout

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from . import body, expectation_grammar, expectations, protocol, report, workboard
from .session import RepoMeaninglessUnderStateRefError, RunContext


@dataclass(frozen=True)
class _RulingsRow:
    """One `rulings` row: the item's number and title, its open/total counts,
    and every one of its `[[expectation]]` lines (open and already-ruled
    alike) in block order -- the detail `rulings` prints beneath the item's
    own summary."""

    number: int
    title: str
    progress: body.ExpectationProgress
    lines: tuple[expectations.ExpectationLine, ...]

    @property
    def newest_open_card_day(self) -> date | None:
        """The day the item's open card was last asked: the newest `asked_on`
        among its open option lines, `None` when none carries one."""
        return max(
            (
                line.asked_on
                for line in self.lines
                if isinstance(line, expectations.OptionLine)
                and line.ruling is None
                and line.asked_on is not None
            ),
            default=None,
        )


def _rulings_order(row: _RulingsRow) -> tuple[int, int, int]:
    """RUL-03: rows with a dated open card first, newest day first; then fully
    ruled rows; each group by descending number. Every open line is an option
    line asked on a day, so a row without one is fully ruled."""
    day = row.newest_open_card_day
    if day is not None:
        return (0, -day.toordinal(), -row.number)
    return (1, 0, -row.number)


def _rulings_rows(
    issues: Iterable[workboard.Issue], *, storage: body.Storage
) -> tuple[_RulingsRow, ...]:
    """Every readable open item that carries at least one `[[expectation]]`
    line, fully ruled ones included, in RUL-03's order. An unreadable item is
    skipped before any parse. `storage` is forwarded to `body.parse_body` and
    `expectations.expectation_lines` unchanged: a state-ref body's `[record]`
    table must read as a known key, not a malformed one."""
    rows = (
        _RulingsRow(
            issue.number,
            issue.title,
            body.parse_body(issue.body, storage=storage).expectation_progress,
            expectations.expectation_lines(issue.body, storage=storage),
        )
        for issue in issues
        if issue.unreadable is None
    )
    return tuple(sorted((row for row in rows if row.progress.total > 0), key=_rulings_order))


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
    """RUL-10, RUL-12..RUL-17, RUL-19: a yes/no line keeps its original keys; an option line
    adds `form`, `asked_on`, the current and the stored card hash, how it was decided,
    whether it is with its head, then its card."""
    shared = {
        "index": line.index,
        "text": line.text,
        "ruling": line.ruling,
        "ruled_on": line.ruled_on.isoformat() if line.ruled_on is not None else None,
    }
    if isinstance(line, expectations.YesNoLine):
        return {**shared, **_rulings_yes_no_card_json(line)}
    decision = line.decision
    return {
        "index": line.index,
        "form": line.form.value,
        "text": shared["text"],
        expectation_grammar.ASKED_ON: None if line.asked_on is None else line.asked_on.isoformat(),
        "ruling": shared["ruling"],
        "ruled_on": shared["ruled_on"],
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
    label = workboard.item_label(row.number, storage)
    title = protocol.terminal_text(row.title)
    header = f"{label} {row.progress.open}/{row.progress.total}: {title}"
    return "\n".join((header, *(_rulings_line_text(line) for line in row.lines)))


def _rulings(issues: Iterable[workboard.Issue], *, as_json: bool, storage: body.Storage) -> None:
    rows = _rulings_rows(issues, storage=storage)
    if as_json:
        report.emit_json(
            True,
            _RulingsReason.LISTED,
            rulings=[
                {
                    "number": row.number,
                    "title": row.title,
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
        storage = context.config.storage
    except RepoMeaninglessUnderStateRefError as error:
        return report.refuse(_RulingsReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_RulingsReason.UNAVAILABLE, error, as_json=as_json)
    _rulings(issues, as_json=as_json, storage=storage)
    return 0
