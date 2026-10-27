"""`DecisionPort` over the installed `aco` command line.

Reads with `aco rulings --json` (specs/rulings.spec.md) and writes with
`aco rule ITEM --line N --yes|--no|--later [--note TEXT] --json` or
`aco rule ITEM --line N --option X --via board --card-hash=HASH --json`
(specs/rule.spec.md).
Every call runs in the directory the board was started in, so the board only
ever sees that repository, and passes its arguments as a list, never through
a shell.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

from .ports import (
    OPTION_LETTERS,
    OPTIONS_FORM,
    OTHER,
    WITHDRAWN_FORM,
    CardChanged,
    CardOption,
    Decision,
    DecisionResult,
    DecisionSourceUnavailableError,
    DecisionStatus,
    ExpectationLine,
    OptionDecision,
    OptionLetter,
    OptionLine,
    OtherAnswer,
    Outcome,
    RulingVia,
    YesNoLine,
)

ACO_EXECUTABLE = "aco"
DEFAULT_TIMEOUT_SECONDS = 120.0
"""`aco rulings` builds the whole board projection, which can take tens of
seconds against a forge; a call still running after this is treated as hung."""
_ALREADY_RULED_REASON = "already_ruled"
_CARD_CHANGED_REASON = "card_changed"

_Field = TypeVar("_Field")
_Member = TypeVar("_Member", bound=StrEnum)


@dataclass(frozen=True)
class _Completed:
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class _RuleAnswer:
    result: DecisionResult
    card_changed: bool


@dataclass(frozen=True)
class AcoCli:
    directory: Path
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def expectation_lines(self) -> tuple[ExpectationLine, ...]:
        completed = self._run(["rulings", "--json"])
        envelope = _envelope(completed)
        if completed.exit_code != 0 or envelope.get("ok") is not True:
            raise DecisionSourceUnavailableError(
                _failure_sentence("aco rulings", completed, envelope)
            )
        return _lines_from_rulings(envelope.get("rulings"))

    def rule(self, decision: Decision) -> DecisionResult:
        arguments = [
            "rule",
            str(decision.item),
            "--line",
            str(decision.index),
            f"--{decision.outcome.value}",
        ]
        if decision.note is not None:
            # One argument: a note starting with "-" would otherwise read as an option.
            arguments.append(f"--note={decision.note}")
        return self._write(arguments).result

    def rule_option(self, decision: OptionDecision, card_hash: str) -> DecisionResult | CardChanged:
        answer = self._write(
            [
                "rule",
                str(decision.item),
                "--line",
                str(decision.index),
                "--option",
                decision.letter,
                "--via",
                # The only `--via` the board writes: the cooperative path, never
                # `chat` or `default`, which belong to the operator's other writers.
                RulingVia.BOARD,
                # One argument: a hash from aco's output can never read as an option.
                f"--card-hash={card_hash}",
            ]
        )
        return CardChanged() if answer.card_changed else answer.result

    def _write(self, arguments: list[str]) -> _RuleAnswer:
        try:
            completed = self._run([*arguments, "--json"])
        except DecisionSourceUnavailableError as error:
            return _RuleAnswer(DecisionResult(DecisionStatus.FAILED, str(error)), False)
        envelope = _envelope(completed)
        if completed.exit_code == 0 and envelope.get("ok") is True:
            return _RuleAnswer(DecisionResult(DecisionStatus.RULED), False)
        reason = envelope.get("reason")
        if reason == _ALREADY_RULED_REASON:
            return _RuleAnswer(
                DecisionResult(DecisionStatus.ALREADY_RULED, _message(envelope)), False
            )
        failed = DecisionResult(
            DecisionStatus.FAILED, _failure_sentence("aco rule", completed, envelope)
        )
        return _RuleAnswer(failed, reason == _CARD_CHANGED_REASON)

    def _run(self, arguments: list[str]) -> _Completed:
        try:
            completed = subprocess.run(
                [ACO_EXECUTABLE, *arguments],
                cwd=self.directory,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as error:
            raise DecisionSourceUnavailableError("aco is not installed on PATH") from error
        except subprocess.TimeoutExpired as error:
            raise DecisionSourceUnavailableError(
                f"aco {arguments[0]} did not answer within {self.timeout_seconds:g} seconds"
            ) from error
        except OSError as error:
            raise DecisionSourceUnavailableError(
                f"aco {arguments[0]} could not be run: {error.strerror}"
            ) from error
        except UnicodeDecodeError as error:
            raise DecisionSourceUnavailableError(
                f"aco {arguments[0]} answered output that is not UTF-8"
            ) from error
        return _Completed(completed.returncode, completed.stdout, completed.stderr)


def _envelope(completed: _Completed) -> dict[str, object]:
    """aco's `--json` object, or an empty one when stdout carries none."""
    try:
        parsed: object = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {}
    return _as_object(parsed) or {}


def _message(envelope: dict[str, object]) -> str | None:
    message = envelope.get("message")
    return message if isinstance(message, str) else None


def _failure_sentence(command: str, completed: _Completed, envelope: dict[str, object]) -> str:
    explanation = _message(envelope) or completed.stderr.strip()
    if not explanation:
        explanation = f"exit {completed.exit_code} without a message"
    return f"{command} failed: {explanation}"


def _lines_from_rulings(rows: object) -> tuple[ExpectationLine, ...]:
    if not isinstance(rows, list):
        raise _unreadable("rulings is not a list")
    return tuple(line for row in rows for line in _lines_from_row(row))


def _lines_from_row(row: object) -> tuple[ExpectationLine, ...]:
    fields = _as_object(row)
    if fields is None:
        raise _unreadable("a rulings row is not an object")
    item = _required(fields, "number", int)
    title = _required(fields, "title", str)
    lines = fields.get("lines")
    if not isinstance(lines, list):
        raise _unreadable(f"#{item} lines is not a list")
    return tuple(_line(item, title, line) for line in lines if not _is_withdrawn(line))


def _is_withdrawn(line: object) -> bool:
    fields = _as_object(line)
    return fields is not None and fields.get("form") == WITHDRAWN_FORM


def _line(item: int, title: str, line: object) -> ExpectationLine:
    fields = _as_object(line)
    if fields is None:
        raise _unreadable(f"#{item} has a line that is not an object")
    if "form" not in fields:
        return _yes_no_line(item, title, fields)
    if fields["form"] != OPTIONS_FORM:
        raise _unreadable(f"#{item} line has an unknown form")
    return _option_line(item, title, fields)


def _require_keys(item: int, fields: dict[str, object], keys: tuple[str, ...]) -> None:
    for key in keys:
        if key not in fields:
            raise _unreadable(f"#{item} line has no {key}")


def _yes_no_line(item: int, title: str, fields: dict[str, object]) -> YesNoLine:
    # RUL-10 always names a line's default, ruling and ruling date, null while
    # absent; a missing key is a broken shape, never an open line.
    _require_keys(item, fields, ("default", "ruling", "ruled_on"))
    return YesNoLine(
        item=item,
        item_title=title,
        index=_required(fields, "index", int),
        text=_required(fields, "text", str),
        question=_optional_text(fields, "question"),
        example=_optional_text(fields, "example"),
        picture=_optional_text(fields, "picture"),
        default=_optional_member(fields, "default", Outcome, "an outcome"),
        ruling=_optional_member(fields, "ruling", Outcome, "an outcome"),
        ruled_on=_optional_date(fields, "ruled_on"),
    )


def _option_line(item: int, title: str, fields: dict[str, object]) -> OptionLine:
    """RUL-13 and RUL-14's card with RUL-15's `via`; the always-null `default`
    and `stored_card_hash` are not read."""
    _require_keys(item, fields, ("ruling", "ruled_on", "via"))
    options = _card_options(fields.get("options"))
    letters: tuple[OptionLetter, ...] = tuple(option.letter for option in options)
    recommended = _letter(fields, "recommended", letters)
    return OptionLine(
        item=item,
        item_title=title,
        index=_required(fields, "index", int),
        text=_required(fields, "text", str),
        question=_required(fields, "question", str),
        problem=_required(fields, "problem", str),
        picture=_required(fields, "picture", str),
        caption=_required(fields, "caption", str),
        decision_kind=_required(fields, "decision_kind", str),
        area=_required(fields, "area", str),
        topic=_required(fields, "topic", str),
        recommended=recommended,
        reason=_required(fields, "reason", str),
        options=options,
        ruling=_option_ruling(fields, letters),
        ruled_on=_optional_date(fields, "ruled_on"),
        via=_optional_member(fields, "via", RulingVia, "board, chat or default"),
        card_hash=_required(fields, "card_hash", str),
    )


def _option_ruling(
    fields: dict[str, object], letters: tuple[OptionLetter, ...]
) -> OptionLetter | OtherAnswer | None:
    answer = fields.get(OTHER)
    if fields["ruling"] == OTHER:
        if not isinstance(answer, str) or not answer.strip():
            raise _unreadable("other is not text on a line ruled other")
        return OtherAnswer(answer)
    if answer is not None:
        raise _unreadable("other belongs only to a line ruled other")
    return None if fields["ruling"] is None else _letter(fields, "ruling", letters)


def _letter(fields: dict[str, object], key: str, letters: tuple[OptionLetter, ...]) -> OptionLetter:
    value = _required(fields, key, str)
    for letter in letters:
        if letter == value:
            return letter
    raise _unreadable(f"{key} is not a letter of its options")


def _card_options(raw: object) -> tuple[CardOption, ...]:
    if not isinstance(raw, list):
        raise _unreadable("options is not a list")
    if len(raw) > len(OPTION_LETTERS):
        raise _unreadable("options hold more than the letters allow")
    return tuple(
        _card_option(letter, option) for letter, option in zip(OPTION_LETTERS, raw, strict=False)
    )


def _card_option(letter: OptionLetter, raw: object) -> CardOption:
    fields = _as_object(raw)
    if fields is None:
        raise _unreadable("an option is not an object")
    if fields.get("letter") != letter:
        raise _unreadable(f"option {letter} is out of position")
    picture = _optional_text(fields, "picture")
    if picture is None and fields.get("same_as_today") is not True:
        raise _unreadable(f"option {letter} has neither picture nor same_as_today")
    return CardOption(
        letter=letter,
        name=_required(fields, "name", str),
        effect=_required(fields, "effect", str),
        picture=picture,
        caption=_optional_text(fields, "caption"),
        notice=_required(fields, "notice", str),
        cost=_required(fields, "cost", str),
        undo=_required(fields, "undo", str),
        undo_how=_required(fields, "undo_how", str),
        contract=_required(fields, "contract", str),
    )


def _as_object(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): field for key, field in value.items()}


def _required(fields: dict[str, object], key: str, kind: type[_Field]) -> _Field:
    value = fields.get(key)
    # bool is an int subclass; a JSON true is never an item or line number.
    if not isinstance(value, kind) or isinstance(value, bool):
        raise _unreadable(f"{key} is not a {kind.__name__}")
    return value


def _optional_text(fields: dict[str, object], key: str) -> str | None:
    value = fields.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _unreadable(f"{key} is not text")
    return value


def _optional_member(
    fields: dict[str, object], key: str, vocabulary: type[_Member], noun: str
) -> _Member | None:
    value = _optional_text(fields, key)
    if value is None:
        return None
    try:
        return vocabulary(value)
    except ValueError as error:
        raise _unreadable(f"{key} is not {noun}") from error


def _optional_date(fields: dict[str, object], key: str) -> date | None:
    value = _optional_text(fields, key)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise _unreadable(f"{key} is not a date") from error


def _unreadable(detail: str) -> DecisionSourceUnavailableError:
    return DecisionSourceUnavailableError(f"aco rulings --json is unreadable: {detail}")
