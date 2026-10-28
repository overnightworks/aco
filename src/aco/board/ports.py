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
from typing import Literal, Protocol, get_args


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


OTHER = "other"
"""Both the `ruling` value and the key that carries the operator's own answer
(RUL-16); the board keeps its own copy and reads aco only through its command
line."""

UNCLEAR = "unclear"
"""The key that sends an option line back to its head; never a `ruling` value."""

OptionLetter = Literal["A", "B", "C", "D"]
"""The letters of an option line's options, by position."""

OPTION_LETTERS: tuple[OptionLetter, ...] = get_args(OptionLetter)


@dataclass(frozen=True)
class OtherAnswer:
    """An option line's ruling when the operator answered in his own words,
    kept verbatim."""

    text: str


OPTIONS_FORM = "options"
"""The `form` that marks an option line in the source's own listing."""

WITHDRAWN_FORM = "withdrawn"
"""The `form` that marks a line its head withdrew; the board does not list it."""


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
    ruling: OptionLetter | OtherAnswer | None
    ruled_on: date | None
    via: RulingVia | None
    returned_on: date | None
    returned_note: str | None
    card_hash: str

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
class OtherCardAnswer:
    """One text in the operator's own words for every line of a card, stripped."""

    text: str


@dataclass(frozen=True)
class UnclearCardAnswer:
    """Every line of a card sent back to its head, with one optional note."""

    note: str | None


CardAnswer = OtherCardAnswer | UnclearCardAnswer | None
"""What a card answers as a whole; None means each line carries its own letter."""


@dataclass(frozen=True)
class PostedLine:
    """A line of a posted card: the fingerprint it was shown with and, when the
    card answers with letters, its own letter."""

    index: int
    fingerprint: str
    letter: OptionLetter | None


@dataclass(frozen=True)
class PostedCard:
    """A card as the browser posted it, before it is checked against a fresh read."""

    item: int
    lines: tuple[PostedLine, ...]
    answer: CardAnswer


@dataclass(frozen=True)
class CardLine:
    """A checked line of a card: the `card_hash` just read and its letter, if any."""

    index: int
    card_hash: str
    letter: OptionLetter | None


@dataclass(frozen=True)
class CardDecision:
    """A checked card, ready for one write that stores every line or none."""

    item: int
    lines: tuple[CardLine, ...]
    answer: CardAnswer


class DecisionStatus(StrEnum):
    RULED = "ruled"
    RETURNED = "returned"
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

    def rule_card(self, decision: CardDecision) -> DecisionResult | CardChanged:
        """Write every line of one card in a single call: the source stores all of
        them or none, and compares each line's hash again at its write."""
        ...
