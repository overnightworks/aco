"""The board's JSON wire form, free of any socket.

Turns a `BoardSnapshot` into the answer of `GET /api/board`, a request body
into a `DecisionRequest` for one yes/no line or a `CardRequest` for a whole option
card, and a decision's result or a refusal into its JSON answer. The transport
decides when to answer; this module owns what the answer and the request look like.
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
    UNCLEAR,
    CardAnswer,
    CardOption,
    Decision,
    DecisionResult,
    ExpectationLine,
    OptionLetter,
    OptionLine,
    OtherAnswer,
    OtherCardAnswer,
    Outcome,
    PostedCard,
    PostedLine,
    UnclearCardAnswer,
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
    decision: Decision


@dataclass(frozen=True)
class CardRequest:
    repo: str
    """The label of the configured repo the card belongs to."""
    card: PostedCard


RuleRequest = DecisionRequest | CardRequest

_CARD_ENTRY_KEYS = frozenset({"line", "fingerprint", "option"})
_KEYS_OF_ONE_LINE = ("line", "fingerprint", "option", "outcome")
"""Keys a card post never carries beside `lines`, even as `null`."""


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


def parse_rule_request(raw: bytes) -> RuleRequest | None:
    """The decision a request body names, or None unless every field is well-formed.

    A body with `lines` is a whole card, any other body one line. `repo` is
    checked here only for its shape; whether it names a configured repo is the
    caller's own lookup, made before any `aco` call.
    """
    fields = _json_object(raw)
    if fields is None:
        return None
    if "lines" in fields:
        return _card_request(fields)
    return _line_request(fields)


def _line_request(fields: dict[str, object]) -> DecisionRequest | None:
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


def _card_request(fields: dict[str, object]) -> CardRequest | None:
    """ABRD-81's card key rules: `lines` of picked or plain entries, and the one
    answer kind that goes with them."""
    repo, item = fields.get("repo"), fields.get("item")
    if (
        not isinstance(repo, str)
        or repo == ""
        or not _is_position(item)
        or any(key in fields for key in _KEYS_OF_ONE_LINE)
    ):
        return None
    lines = _posted_lines(fields["lines"])
    if lines is None:
        return None
    answer = _card_answer(fields, picked=lines[0].letter is not None)
    if answer is None:
        return None
    return CardRequest(repo, PostedCard(item, lines, answer[0]))


def _posted_lines(entries: object) -> tuple[PostedLine, ...] | None:
    """Each entry's line named once; a letter on every entry or on none."""
    if not isinstance(entries, list) or not entries:
        return None
    lines = [_posted_line(entry) for entry in entries]
    if any(line is None for line in lines):
        return None
    posted = cast(list[PostedLine], lines)
    named_once = len({line.index for line in posted}) == len(posted)
    lettered = {line.letter is not None for line in posted}
    return tuple(posted) if named_once and len(lettered) == 1 else None


def _posted_line(entry: object) -> PostedLine | None:
    if not isinstance(entry, dict) or not set(entry) <= _CARD_ENTRY_KEYS:
        return None
    index, fingerprint = entry.get("line"), entry.get("fingerprint")
    if not _is_position(index) or not isinstance(fingerprint, str):
        return None
    if "option" not in entry:
        return PostedLine(index, fingerprint, None)
    letter = entry["option"]
    return PostedLine(index, fingerprint, letter) if _is_option_letter(letter) else None


def _card_answer(fields: dict[str, object], *, picked: bool) -> tuple[CardAnswer] | None:
    """The card's answer in a one-tuple, None when the keys break the rules: picks
    name no `other`, `unclear` or `note`; otherwise exactly one of `other` (no
    note) and `unclear` (an optional note) is named."""
    other, unclear, note = fields.get(OTHER), fields.get(UNCLEAR), fields.get("note")
    if picked:
        return (None,) if other is unclear is note is None else None
    if other is not None:
        text = other.strip() if _is_note_text(other) else ""
        return (OtherCardAnswer(text),) if text and unclear is None and note is None else None
    if unclear is True and (note is None or _is_note_text(note)):
        return (UnclearCardAnswer(_note(note)),)
    return None


def _decision(item: int, line: int, fields: dict[str, object]) -> Decision | None:
    """An `outcome` with an optional note and nothing else: a non-null `other` or `unclear`,
    or any `option` key, names an option line's answer, which only a card carries."""
    if any(fields.get(key) is not None for key in (OTHER, UNCLEAR)) or "option" in fields:
        return None
    outcome, note = fields.get("outcome"), fields.get("note")
    if (
        isinstance(outcome, str)
        and outcome in _VALID_OUTCOME_VALUES
        and (note is None or _is_note_text(note))
    ):
        return Decision(item=item, index=line, outcome=Outcome(outcome), note=_note(note))
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
        "returned_on": line.returned_on.isoformat() if line.returned_on is not None else None,
        "returned_note": line.returned_note,
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
    except ValueError, RecursionError:
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


def _note(raw: str | None) -> str | None:
    """An empty or blank note is no note."""
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def _is_position(value: object) -> TypeGuard[int]:
    """A positive item or line number; a JSON `true` is not one."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
