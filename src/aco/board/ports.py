"""The board's one narrow interface to its decision source.

The board reads expectation lines and writes rulings through `DecisionPort`
only; `aco_cli.AcoCli` is its one implementation. Truth stays with the
source: the board keeps no copy of a line or a ruling.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final, Literal, Protocol, get_args


class Outcome(StrEnum):
    YES = "yes"
    NO = "no"
    LATER = "later"


class RulingVia(StrEnum):
    """`aco rulings --json` names an option line's `via` (RUL-15); the board
    keeps its own copy of the vocabulary and reads aco only through its command
    line."""

    BOARD = "board"
    CHAT = "chat"
    DEFAULT = "default"


OptionLetter = Literal["A", "B", "C", "D"]
"""The letters of an option line's options, by position."""

OTHER_RULING: Final = "other"
"""`aco rulings --json` names an option line ruled with the operator's own
answer by this `ruling` value and carries the answer beside it."""

OptionRuling = OptionLetter | Literal["other"]

OPTION_LETTERS: tuple[OptionLetter, ...] = get_args(OptionLetter)


OPTIONS_FORM = "options"
"""The `form` that marks an option line in the source's own listing."""


@dataclass(frozen=True)
class YesNoLine:
    item: int
    item_title: str
    index: int
    text: str
    question: str | None
    example: str | None
    picture: str | None
    default: Outcome | None
    """The outcome the source recommends for an open line; None when it names none."""
    ruling: Outcome | None
    ruled_on: date | None

    @property
    def is_open(self) -> bool:
        return self.ruling is None

    @property
    def fingerprint(self) -> str:
        """Names exactly what a decision card shows the operator: every field it
        renders. The ruling and its date are left out on purpose: a ruled line
        is no longer decidable, so no card for it is ever submitted."""
        shown = json.dumps(
            [
                self.item,
                self.item_title,
                self.index,
                self.text,
                self.question,
                self.example,
                self.picture,
                self.default,
            ],
            ensure_ascii=False,
        )
        return hashlib.sha256(shown.encode("utf-8", "surrogatepass")).hexdigest()


@dataclass(frozen=True)
class CardOption:
    letter: OptionLetter
    name: str
    effect: str
    picture: str | None
    """The option's RESULT picture as stored; None marks `same_as_today`."""
    caption: str | None
    notice: str
    cost: str
    undo: str
    undo_how: str
    contract: str


@dataclass(frozen=True)
class OptionLine:
    item: int
    item_title: str
    index: int
    text: str
    question: str
    problem: str
    picture: str
    caption: str
    decision_kind: str
    area: str
    topic: str
    recommended: OptionLetter
    reason: str
    options: tuple[CardOption, ...]
    ruling: OptionRuling | None
    ruled_on: date | None
    via: RulingVia | None
    card_hash: str
    other: str | None = None

    @property
    def is_open(self) -> bool:
        return self.ruling is None

    @property
    def fingerprint(self) -> str:
        """The card hash already covers every field the card shows; the item
        number and line index tell the card apart across items."""
        shown = json.dumps([self.item, self.index, self.card_hash], ensure_ascii=False)
        return hashlib.sha256(shown.encode("utf-8", "surrogatepass")).hexdigest()


ExpectationLine = YesNoLine | OptionLine


NOTE_MAX_LENGTH = 280
"""The longest note a decision may carry, after trimming. A note travels to
the source as one command-line argument, so it is also free of NUL and
encodable as UTF-8."""


@dataclass(frozen=True)
class Decision:
    item: int
    index: int
    outcome: Outcome
    note: str | None


@dataclass(frozen=True)
class OptionDecision:
    """An option line's chosen letter; an option carries no note."""

    item: int
    index: int
    letter: OptionLetter


class DecisionStatus(StrEnum):
    RULED = "ruled"
    ALREADY_RULED = "already_ruled"
    FAILED = "failed"


@dataclass(frozen=True)
class DecisionResult:
    status: DecisionStatus
    message: str | None = None


@dataclass(frozen=True)
class CardChanged:
    """The source refused an option because its card changed since the hash was read."""


class DecisionSourceUnavailableError(Exception):
    """The source could not be read; the message says why in one sentence."""


class DecisionPort(Protocol):
    def expectation_lines(self) -> tuple[ExpectationLine, ...]:
        """Every expectation line, open and ruled, in the source's own order.

        Raises `DecisionSourceUnavailableError` when the source cannot answer.
        """
        ...

    def rule(self, decision: Decision) -> DecisionResult:
        """Write one decision; the source itself refuses an already-ruled line,
        an unknown item, or a line the item does not have."""
        ...

    def rule_option(self, decision: OptionDecision, card_hash: str) -> DecisionResult | CardChanged:
        """Write one option decision for the card `card_hash` names; the source
        compares that hash again at its write and refuses a changed card."""
        ...
