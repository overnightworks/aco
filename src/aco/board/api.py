"""The board's JSON wire form, free of any socket.

Turns a `BoardSnapshot` into the answer of `GET /api/board`, a request body
into a `DecisionRequest`, and a decision's result or a refusal into its JSON
answer. The transport decides when to answer; this module owns what the
answer and the request look like.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeGuard, cast

from .board import RepoReading, RepoUnavailable, wire_fingerprint
from .ports import (
    NOTE_MAX_LENGTH,
    OPTION_LETTERS,
    OPTIONS_FORM,
    OTHER,
    CardOption,
    Decision,
    DecisionResult,
    ExpectationLine,
    OptionDecision,
    OptionLetter,
    OptionLine,
    OtherAnswer,
    Outcome,
)

JSON_CONTENT_TYPE = "application/json"

_VALID_OUTCOME_VALUES = frozenset(
    outcome.value for outcome in (Outcome.YES, Outcome.NO, Outcome.LATER)
)
"""The three outcomes a posted decision may name, spelled out by name rather
than taken from a generic `Outcome` iteration: this is the one place that
decides which wire values are valid, so it is also the one place every
member needs to be named."""


@dataclass(frozen=True)
class DecisionRequest:
    repo: str
    """The label of the configured repo this decision belongs to."""
    fingerprint: str
    """The fingerprint of the card as it was shown when the operator chose."""
    decision: Decision | OptionDecision


def board_json(readings: Sequence[RepoReading]) -> str:
    """Every configured repo, in configured order, with its items or its error."""
    return json.dumps({"repos": [_repo_json(reading) for reading in readings]})


def _repo_json(reading: RepoReading) -> dict[str, object]:
    if isinstance(reading, RepoUnavailable):
        return {"name": reading.name, "error": reading.reason, "items": []}
    lines_by_item: dict[int, list[ExpectationLine]] = {}
    for line in reading.lines:
        lines_by_item.setdefault(line.item, []).append(line)
    return {
        "name": reading.name,
        "error": None,
        "items": [_item_json(lines, reading.name) for lines in lines_by_item.values()],
    }


def decision_result_json(result: DecisionResult) -> str:
    return json.dumps({"status": result.status.value, "message": result.message})


def error_json(sentence: str) -> str:
    return json.dumps({"error": sentence})


def parse_decision_request(raw: bytes) -> DecisionRequest | None:
    """The decision a request body names, or None unless every field is well-formed.

    `repo` is checked here only for its shape; whether it names a configured
    repo is the caller's own lookup, made before any `aco` call.
    """
    fields = _json_object(raw)
    if fields is None:
        return None
    repo = fields.get("repo")
    fingerprint, item, line = fields.get("fingerprint"), fields.get("item"), fields.get("line")
    if (
        isinstance(repo, str)
        and repo != ""
        and isinstance(fingerprint, str)
        and _is_position(item)
        and _is_position(line)
    ):
        decision = _decision(item, line, fields)
        if decision is not None:
            return DecisionRequest(repo=repo, fingerprint=fingerprint, decision=decision)
    return None


def _decision(item: int, line: int, fields: dict[str, object]) -> Decision | OptionDecision | None:
    """Exactly one of `outcome` (with an optional note) and `option` (with none);
    an absent key and a `null` both name nothing, but a post carrying both keys
    is refused whatever their values."""
    if "outcome" in fields and "option" in fields:
        return None
    outcome, option, note = fields.get("outcome"), fields.get("option"), fields.get("note")
    if option is None:
        if (
            isinstance(outcome, str)
            and outcome in _VALID_OUTCOME_VALUES
            and (note is None or _is_note_text(note))
        ):
            return Decision(item=item, index=line, outcome=Outcome(outcome), note=_note(note))
        return None
    if outcome is None and _is_option_letter(option) and (note is None or _is_blank_text(note)):
        return OptionDecision(item=item, index=line, letter=option)
    return None


def _item_json(lines: list[ExpectationLine], repo: str) -> dict[str, object]:
    first = lines[0]
    return {
        "number": first.item,
        "title": first.item_title,
        "lines": [_line_json(line, repo) for line in lines],
    }


def _line_json(line: ExpectationLine, repo: str) -> dict[str, object]:
    if isinstance(line, OptionLine):
        return _option_line_json(line, repo)
    return {
        "index": line.index,
        "text": line.text,
        "question": line.question,
        "example": line.example,
        "picture": line.picture,
        "default": line.default,
        "ruling": line.ruling,
        "ruled_on": line.ruled_on.isoformat() if line.ruled_on is not None else None,
        "fingerprint": wire_fingerprint(repo, line),
    }


def _option_line_json(line: OptionLine, repo: str) -> dict[str, object]:
    """ABRD-34: pictures stay SVG text for the browser to turn into data URIs."""
    return {
        "index": line.index,
        "form": OPTIONS_FORM,
        "text": line.text,
        "question": line.question,
        "problem": line.problem,
        "picture": line.picture,
        "caption": line.caption,
        "decision_kind": line.decision_kind,
        "area": line.area,
        "topic": line.topic,
        "recommended": line.recommended,
        "reason": line.reason,
        "options": [_card_option_json(option) for option in line.options],
        "ruling": OTHER if isinstance(line.ruling, OtherAnswer) else line.ruling,
        "ruled_on": line.ruled_on.isoformat() if line.ruled_on is not None else None,
        "via": line.via,
        "other": line.ruling.text if isinstance(line.ruling, OtherAnswer) else None,
        "fingerprint": wire_fingerprint(repo, line),
    }


def _card_option_json(option: CardOption) -> dict[str, object]:
    result: dict[str, object] = {"same_as_today": True}
    if option.picture is not None:
        result = {"picture": option.picture}
    if option.caption is not None:
        result["caption"] = option.caption
    return {
        "letter": option.letter,
        "name": option.name,
        "effect": option.effect,
        **result,
        "notice": option.notice,
        "cost": option.cost,
        "undo": option.undo,
        "undo_how": option.undo_how,
        "contract": option.contract,
    }


def _json_object(raw: bytes) -> dict[str, object] | None:
    try:
        fields: object = json.loads(raw)
    # ValueError covers undecodable bytes, invalid JSON, and an integer past
    # Python's digit limit; RecursionError a body nested deeper than the stack.
    except (ValueError, RecursionError):
        return None
    if not isinstance(fields, dict):
        return None
    return cast(dict[str, object], fields)


def _is_note_text(note: object) -> TypeGuard[str]:
    """Short text a command-line argument can carry: no NUL, no lone surrogate."""
    if not isinstance(note, str) or len(note.strip()) > NOTE_MAX_LENGTH or "\0" in note:
        return False
    try:
        note.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _is_option_letter(value: object) -> TypeGuard[OptionLetter]:
    return isinstance(value, str) and value in OPTION_LETTERS


def _is_blank_text(value: object) -> bool:
    return isinstance(value, str) and not value.strip()


def _note(raw: str | None) -> str | None:
    """An empty or blank note is no note."""
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def _is_position(value: object) -> TypeGuard[int]:
    """A positive item or line number; a JSON `true` is not one."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
