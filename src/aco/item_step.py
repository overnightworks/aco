"""The one typed `step` table of an item's `aco` block: the detail of a step only the
operator can take, behind the one-line `next` and `wait.operator` that name it."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import cast

from .toml_text import toml_multiline_string, toml_string

STEP_KEY = "step"
PURPOSE_KEY = "purpose"
ACTIONS_KEY = "actions"
EXPECTED_KEY = "expected"
ANSWER_KEY = "answer"
REQUIRED_KEYS = (PURPOSE_KEY, ACTIONS_KEY, EXPECTED_KEY)
_STEP_KEYS = frozenset((*REQUIRED_KEYS, ANSWER_KEY))


@dataclass(frozen=True)
class StepCard:
    """Why the operator takes the step, what to do (a paste-ready block, or a link with
    each click), what to expect and the answer to give back (`None`: yes or no)."""

    purpose: str
    actions: str
    expected: str
    answer: str | None


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def step_defects(data: Mapping[str, object]) -> list[tuple[str, str]]:
    """The `(field, message)` refusals of the block's `step`, none when it is absent."""
    if STEP_KEY not in data:
        return []
    value = data[STEP_KEY]
    if not isinstance(value, dict):
        return [(STEP_KEY, f"{STEP_KEY} must be a table")]
    table = cast("dict[str, object]", value)
    defects = [
        (f"{STEP_KEY}.{key}", f"{STEP_KEY}.{key} must be a non-empty string")
        for key in REQUIRED_KEYS
        if not _is_text(table.get(key))
    ]
    if ANSWER_KEY in table and not _is_text(table[ANSWER_KEY]):
        defects.append(
            (f"{STEP_KEY}.{ANSWER_KEY}", f"{STEP_KEY}.{ANSWER_KEY} must be a non-empty string")
        )
    defects.extend(
        (f"{STEP_KEY}.{key}", f"unknown key {STEP_KEY}.{key}")
        for key in sorted(set(table) - _STEP_KEYS)
    )
    return defects


def parse_step(data: Mapping[str, object]) -> StepCard | None:
    """The block's `step`, which `step_defects` has already found valid."""
    value = data.get(STEP_KEY)
    if value is None:
        return None
    table = cast("dict[str, str]", value)
    answer = table.get(ANSWER_KEY)
    return StepCard(
        table[PURPOSE_KEY].strip(),
        table[ACTIONS_KEY].strip(),
        table[EXPECTED_KEY].strip(),
        None if answer is None else answer.strip(),
    )


def step_table(card: StepCard) -> dict[str, object]:
    """The `step` table that holds `card`."""
    table: dict[str, object] = {
        PURPOSE_KEY: card.purpose,
        ACTIONS_KEY: card.actions,
        EXPECTED_KEY: card.expected,
    }
    if card.answer is not None:
        table[ANSWER_KEY] = card.answer
    return table


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

NEXT_AFTER_ANSWER = "Act on the operator's answer in now."
"""The `next` of an item whose step the operator answered."""


def asks_for_report(card: StepCard | None) -> bool:
    """Whether the operator answers `card` with a report; a step without a card, or
    without an `answer`, is answered with yes or no."""
    return card is not None and card.answer is not None


def result_fits(result: StepResult, card: StepCard | None) -> bool:
    """Whether `result` answers a step with `card`: a report only a step that asks
    for one, Erfolgreich only one that does not, a failure either."""
    if isinstance(result, StepFailed):
        return True
    return isinstance(result, StepReported) == asks_for_report(card)


def answered_now(step: str, result: StepResult, today: date) -> str:
    """The `now` of an item whose `step` the operator answered with `result` on `today`."""
    if isinstance(result, StepSucceeded):
        outcome = "Erfolgreich"
    elif isinstance(result, StepFailed):
        outcome = f"Fehlgeschlagen: {result.note}"
    else:
        outcome = result.report
    return f'The operator answered "{step}" on the board on {today.isoformat()}: {outcome}'
