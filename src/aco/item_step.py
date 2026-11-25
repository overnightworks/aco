"""The one typed `step` table of an item's `aco` block: the detail of a step only the
operator can take, behind the one-line `wait.operator` that names it. A step holds one
paste: a command line or a link. A table stored with `actions` (and maybe an `answer`)
is the older form; it stays readable and writes back key for key."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import cast

from .card_rules import PROBLEM_MAXIMUM_WORDS, STEP_MAXIMUM_WORDS, is_one_line, word_count
from .toml_text import toml_multiline_string, toml_string

STEP_KEY = "step"
PURPOSE_KEY = "purpose"
PASTE_KEY = "paste"
ACTIONS_KEY = "actions"
EXPECTED_KEY = "expected"
ANSWER_KEY = "answer"
REQUIRED_KEYS = (PURPOSE_KEY, PASTE_KEY, EXPECTED_KEY)
_OLD_REQUIRED_KEYS = (PURPOSE_KEY, ACTIONS_KEY, EXPECTED_KEY)
_OLD_KEYS = frozenset((*_OLD_REQUIRED_KEYS, ANSWER_KEY))
_SCHEME_AND_SLASHES = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_ALLOWED_LINK = re.compile(r"https://\S+|http://127\.0\.0\.1(?::\d+)?(?:[/?#]\S*)?")
_LEADING_CD = re.compile(r"^cd [^\s;&|$`<>()]+ && ")
_COMMAND_JOINERS = ("&&", "||", ";", "|", "&", "$(", "`")


@dataclass(frozen=True)
class StepCard:
    """Why the operator takes the step, the one paste to copy or open, and what to
    expect."""

    purpose: str
    paste: str
    expected: str


@dataclass(frozen=True)
class OldStepCard:
    """A step stored before the paste: what to do (a block, or a link with each click)
    and the answer to give back (`None`: yes or no)."""

    purpose: str
    actions: str
    expected: str
    answer: str | None


type StoredStepCard = StepCard | OldStepCard


class PasteKind(StrEnum):
    """What a paste is: a command line to copy or a link to open."""

    COMMAND = "command"
    LINK = "link"


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_old_table(table: Mapping[str, object]) -> bool:
    return PASTE_KEY not in table and ACTIONS_KEY in table


def step_defects(data: Mapping[str, object]) -> list[tuple[str, str]]:
    """The `(field, message)` refusals of the block's `step`, none when it is absent.
    The shape only: a stored paste is not judged by the tool's rules."""
    if STEP_KEY not in data:
        return []
    value = data[STEP_KEY]
    if not isinstance(value, dict):
        return [(STEP_KEY, f"{STEP_KEY} must be a table")]
    table = cast("dict[str, object]", value)
    old = _is_old_table(table)
    required = _OLD_REQUIRED_KEYS if old else REQUIRED_KEYS
    known = _OLD_KEYS if old else frozenset(required)
    defects = [
        (f"{STEP_KEY}.{key}", f"{STEP_KEY}.{key} must be a non-empty string")
        for key in required
        if not _is_text(table.get(key))
    ]
    if ANSWER_KEY in table and old and not _is_text(table[ANSWER_KEY]):
        defects.append(
            (f"{STEP_KEY}.{ANSWER_KEY}", f"{STEP_KEY}.{ANSWER_KEY} must be a non-empty string")
        )
    defects.extend(
        (f"{STEP_KEY}.{key}", f"unknown key {STEP_KEY}.{key}") for key in sorted(set(table) - known)
    )
    return defects


def parse_step(data: Mapping[str, object]) -> StoredStepCard | None:
    """The block's `step`, which `step_defects` has already found valid."""
    value = data.get(STEP_KEY)
    if value is None:
        return None
    table = cast("dict[str, str]", value)
    purpose, expected = table[PURPOSE_KEY].strip(), table[EXPECTED_KEY].strip()
    if not _is_old_table(table):
        return StepCard(purpose, table[PASTE_KEY].strip(), expected)
    answer = table.get(ANSWER_KEY)
    return OldStepCard(
        purpose,
        table[ACTIONS_KEY].strip(),
        expected,
        None if answer is None else answer.strip(),
    )


def step_table(card: StoredStepCard) -> dict[str, object]:
    """The `step` table that holds `card`, with the keys of its form."""
    if isinstance(card, StepCard):
        return {PURPOSE_KEY: card.purpose, PASTE_KEY: card.paste, EXPECTED_KEY: card.expected}
    table: dict[str, object] = {
        PURPOSE_KEY: card.purpose,
        ACTIONS_KEY: card.actions,
        EXPECTED_KEY: card.expected,
    }
    if card.answer is not None:
        table[ANSWER_KEY] = card.answer
    return table


def paste_kind(text: str) -> PasteKind:
    """A paste that starts `<scheme>://` is a link, any other a command."""
    return PasteKind.LINK if _SCHEME_AND_SLASHES.match(text) else PasteKind.COMMAND


def _line_reasons(field: str, text: str, maximum_words: int) -> list[str]:
    reasons: list[str] = []
    if word_count(text) > maximum_words:
        reasons.append(f"{field} must be at most {maximum_words} words")
    if not is_one_line(text):
        reasons.append(f"{field} must be one line")
    return reasons


def _paste_reasons(paste: str) -> list[str]:
    if not is_one_line(paste):
        return ["paste must be one line; write a script and paste its one call"]
    if paste_kind(paste) is PasteKind.LINK:
        if _ALLOWED_LINK.fullmatch(paste):
            return []
        return ["paste is a link and must start with https:// or http://127.0.0.1, without spaces"]
    command = _LEADING_CD.sub("", paste, count=1)
    joiner = next((token for token in _COMMAND_JOINERS if token in command), None)
    if joiner is None:
        return []
    return [
        f'paste must be one command, it holds "{joiner}"; write a script and paste its one call'
    ]


def step_rule_defects(step: str, purpose: str, paste: str, expected: str) -> list[str]:
    """The sentences for every rule the `step` tool holds a new step to, none when it
    keeps them all: `step` and the card's `purpose` and `expected` short and one line,
    `paste` one command or one link. What no rule can see (nothing to fill in, no secret)
    stays the writer's duty."""
    return [
        *_line_reasons("step", step, STEP_MAXIMUM_WORDS),
        *_line_reasons("purpose", purpose, PROBLEM_MAXIMUM_WORDS),
        *_paste_reasons(paste),
        *_line_reasons("expected", expected, PROBLEM_MAXIMUM_WORDS),
    ]


def _toml_text(value: str) -> str:
    return toml_multiline_string(value) if "\n" in value else toml_string(value)


def render_step(data: Mapping[str, object]) -> list[str]:
    """The block lines of the `step` table, none when absent."""
    card = parse_step(data)
    if card is None:
        return []
    fields = step_table(card)
    return [
        "",
        f"[{STEP_KEY}]",
        *(f"{key} = {_toml_text(cast(str, fields[key]))}" for key in fields),
    ]


@dataclass(frozen=True)
class StepSucceeded:
    """The operator took the step and it worked: Erfolgreich."""


@dataclass(frozen=True)
class StepFailed:
    """The operator took the step and it failed, with the note that says how."""

    note: str


@dataclass(frozen=True)
class StepReported:
    """The operator took the step and gives the report it asks for."""

    report: str


type StepResult = StepSucceeded | StepFailed | StepReported

NEXT_OF_STEP_ITEM = "Act on the operator's answer in now."
"""The `next` of an item the step tool opens; a step on an existing item and its answer
leave that item's `next` as it is."""


def asks_for_report(card: StoredStepCard | None) -> bool:
    """Whether the operator answers `card` with a report; only a stored older step
    with an `answer` asks for one, every other is answered with yes or no."""
    return isinstance(card, OldStepCard) and card.answer is not None


def result_fits(result: StepResult, card: StoredStepCard | None) -> bool:
    """Whether `result` answers a step with `card`: a report only a step that asks
    for one, Erfolgreich only one that does not, a failure either."""
    if isinstance(result, StepFailed):
        return True
    return isinstance(result, StepReported) == asks_for_report(card)


class AnswerChannel(StrEnum):
    """Where the operator gave his answer to a step, as the `now` sentence says it."""

    BOARD = "on the board"
    CHAT = "in chat"


def answered_now(step: str, result: StepResult, today: date, channel: AnswerChannel) -> str:
    """The `now` of an item whose `step` the operator answered with `result` on `today`
    through `channel`."""
    if isinstance(result, StepSucceeded):
        outcome = "Erfolgreich"
    elif isinstance(result, StepFailed):
        outcome = f"Fehlgeschlagen: {result.note}"
    else:
        outcome = result.report
    return f'The operator answered "{step}" {channel} on {today.isoformat()}: {outcome}'
