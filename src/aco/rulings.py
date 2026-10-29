"""The rows `aco rulings` lists (`specs/rulings.spec.md`) and their two
renderings, free of output; `aco rulings` (`cmd_rulings`) emits them."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from . import body, expectation_grammar, expectations, protocol, workboard


@dataclass(frozen=True)
class Row:
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


def _order(row: Row) -> tuple[int, int, int]:
    """RUL-03: rows with a dated open card first, newest day first; then rows
    fully ruled or withdrawn; each group by descending number. Every open line
    is an option line asked on a day, so a row without one has none open."""
    day = row.newest_open_card_day
    if day is not None:
        return (0, -day.toordinal(), -row.number)
    return (1, 0, -row.number)


def rows(issues: Iterable[workboard.Issue], *, storage: body.Storage) -> tuple[Row, ...]:
    """Every readable open item that carries at least one `[[expectation]]`
    line, fully ruled ones included, in RUL-03's order. An unreadable item is
    skipped before any parse. `storage` is forwarded to `body.parse_body` and
    `expectations.expectation_lines` unchanged: a state-ref body's `[record]`
    table must read as a known key, not a malformed one."""
    found: list[Row] = []
    for issue in issues:
        if issue.unreadable is not None:
            continue
        progress = body.parse_body(issue.body, storage=storage).expectation_progress
        if progress.total > 0:
            lines = expectations.expectation_lines(issue.body, storage=storage)
            found.append(Row(issue.number, issue.title, progress, lines))
    return tuple(sorted(found, key=_order))


def _option_json(option: expectations.CardOption) -> dict[str, object]:
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


def _option_line_card_json(line: expectations.OptionLine) -> dict[str, object]:
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
        "options": [_option_json(option) for option in line.options],
    }


def _yes_no_card_json(line: expectations.YesNoLine) -> dict[str, object]:
    return {
        key: value
        for key, value in (
            ("question", line.question),
            ("example", line.example),
            ("picture", line.picture),
        )
        if value is not None
    }


def line_json(line: expectations.ExpectationLine) -> dict[str, object]:
    """RUL-10, RUL-12..RUL-17, RUL-19, RUL-23: a yes/no line keeps its original keys; an
    option line adds `form`, `asked_on`, the current and the stored card hash, how it was
    decided, whether it is with its head, then its card; a withdrawn line carries no
    `ruling` key, which would read as open."""
    if isinstance(line, expectations.WithdrawnLine):
        return {
            "index": line.index,
            "form": line.form.value,
            "text": line.text,
            expectation_grammar.WITHDRAWN_ON: line.withdrawn_on.isoformat(),
        }
    shared = {
        "index": line.index,
        "text": line.text,
        "ruling": line.ruling,
        "ruled_on": line.ruled_on.isoformat() if line.ruled_on is not None else None,
    }
    if isinstance(line, expectations.YesNoLine):
        return {**shared, **_yes_no_card_json(line)}
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
        **_option_line_card_json(line),
    }


def _line_text(line: expectations.ExpectationLine) -> str:
    state = expectations.expectation_line_state(line)
    summary = protocol.terminal_text(expectations.expectation_line_summary(line))
    return f"  {line.index} {state}: {summary}"


def row_json(row: Row) -> dict[str, object]:
    return {
        "number": row.number,
        "title": row.title,
        "open": row.progress.open,
        "total": row.progress.total,
        "lines": [line_json(line) for line in row.lines],
    }


def row_text(row: Row, storage: body.Storage) -> str:
    label = workboard.item_label(row.number, storage)
    title = protocol.terminal_text(row.title)
    header = f"{label} {row.progress.open}/{row.progress.total}: {title}"
    return "\n".join((header, *(_line_text(line) for line in row.lines)))
