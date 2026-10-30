"""The board's JSON wire form, free of any socket.

Turns each repo's rows into the answer of `GET /api/board`, a request body
into a `CardRequest` for a whole option card, and a decision's result or a
refusal into its JSON answer. Every line is `aco rulings --json`'s own
rendering of it; this module only adds an option line's fingerprint and
leaves withdrawn lines out. The transport decides when to answer; this
module owns what the answer and the request look like.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeGuard, cast

from .. import expectation_grammar, expectations, rulings
from .board import RepoReading, RepoUnavailable, wire_fingerprint
from .ports import (
    NOTE_MAX_LENGTH,
    CardAnswer,
    DecisionResult,
    ListedItem,
    OtherCardAnswer,
    PostedCard,
    PostedLine,
    UnclearCardAnswer,
)

JSON_CONTENT_TYPE = "application/json"

_OTHER = "other"
"""The card post's key for one answer in the operator's own words (ABRD-77)."""
_UNCLEAR = "unclear"
"""The card post's key that sends the card back to its head (ABRD-77)."""
_OPTION_LETTERS = frozenset(expectation_grammar.OPTION_LETTERS)
"""aco's option letters, each on its own: a bare `in` on aco's letter string
would also accept an empty text or a run of letters."""


@dataclass(frozen=True)
class CardRequest:
    repo: str
    """The label of the configured repo the card belongs to."""
    card: PostedCard


_CARD_ENTRY_KEYS = frozenset({"line", "fingerprint", "option"})
_KEYS_OF_ONE_LINE = ("line", "fingerprint", "option", "outcome")
"""Keys a card post never carries beside `lines`, even as `null`."""


def board_json(readings: Sequence[RepoReading]) -> str:
    """Every configured repo, in configured order, with its items or its error."""
    return json.dumps({"repos": [_repo_json(reading) for reading in readings]})


def _repo_json(reading: RepoReading) -> dict[str, object]:
    if isinstance(reading, RepoUnavailable):
        return {"name": reading.name, "error": reading.reason, "items": []}
    items = (_item_json(row, reading.name) for row in reading.rows)
    return {
        "name": reading.name,
        "error": None,
        "items": [item for item in items if item is not None],
    }


def decision_result_json(result: DecisionResult, repo: str) -> str:
    """A refusal is `status` and `message`; a stored answer adds the written
    item as `GET /api/board` lists it (ABRD-09)."""
    answer: dict[str, object] = {"status": result.status.value, "message": result.message}
    if result.item is not None:
        answer["item"] = _item_json(result.item, repo)
    return json.dumps(answer)


def error_json(sentence: str) -> str:
    return json.dumps({"error": sentence})


def parse_rule_request(raw: bytes) -> CardRequest | None:
    """The card a request body names, or None unless every field is well-formed.

    A body without `lines` names no card and is refused (ABRD-40). `repo` is
    checked here only for its shape; whether it names a configured repo is the
    caller's own lookup, made before any `aco` call.
    """
    fields = _json_object(raw)
    if fields is None or "lines" not in fields:
        return None
    return _card_request(fields)


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
    other, unclear, note = fields.get(_OTHER), fields.get(_UNCLEAR), fields.get("note")
    if picked:
        return (None,) if other is unclear is note is None else None
    if other is not None:
        text = other.strip() if _is_note_text(other) else ""
        return (OtherCardAnswer(text),) if text and unclear is None and note is None else None
    if unclear is True and (note is None or _is_note_text(note)):
        return (UnclearCardAnswer(_note(note)),)
    return None


def _item_json(item: ListedItem, repo: str) -> dict[str, object] | None:
    """The item with its withdrawn lines left out; None when no other line is
    left, since an item of only withdrawn lines is not listed (ABRD-60)."""
    lines = [
        _line_json(line, item.number, repo)
        for line in item.lines
        if not isinstance(line, expectations.WithdrawnLine)
    ]
    if not lines:
        return None
    return {"number": item.number, "title": item.title, "lines": lines}


def _line_json(
    line: expectations.YesNoLine | expectations.OptionLine, item: int, repo: str
) -> dict[str, object]:
    """`aco rulings --json`'s line; an option line adds its fingerprint last."""
    rendered = rulings.line_json(line)
    if isinstance(line, expectations.OptionLine):
        rendered["fingerprint"] = wire_fingerprint(repo, item, line)
    return rendered


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
    """Short UTF-8 text: no NUL, no lone surrogate (ABRD-05)."""
    if not isinstance(note, str) or len(note.strip()) > NOTE_MAX_LENGTH or "\0" in note:
        return False
    try:
        note.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _is_option_letter(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and value in _OPTION_LETTERS


def _note(raw: str | None) -> str | None:
    """An empty or blank note is no note."""
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def _is_position(value: object) -> TypeGuard[int]:
    """A positive item or line number; a JSON `true` is not one."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
