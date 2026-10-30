"""The board's one narrow interface to its decision source.

The board reads expectation lines and writes rulings through `DecisionPort`
only; `aco_source.AcoSource` is its one implementation, running aco's own
library in process. Truth stays with the source: the board keeps no copy of
a line or a ruling.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Literal, Protocol, get_args


class Outcome(StrEnum):
    YES = "yes"
    NO = "no"
    LATER = "later"


class RulingVia(StrEnum):
    """How an option line's ruling reached aco (RUL-15), in the board's own
    vocabulary."""

    BOARD = "board"
    CHAT = "chat"
    DEFAULT = "default"


OTHER = "other"
"""Both the `ruling` value and the key that carries the operator's own answer
(RUL-16) on the board's wire."""

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
"""The `form` that marks an option line on the board's wire."""


@dataclass(frozen=True)
class YesNoLine:
    """A ruled yes/no line: read-only history the board shows and never writes."""

    item: int
    item_title: str
    index: int
    text: str
    question: str | None
    example: str | None
    picture: str | None
    ruling: Outcome
    ruled_on: date | None

    @property
    def fingerprint(self) -> str:
        """Names the fields the line's decided card renders as its text. The
        ruling and its date are left out: a yes/no line is read-only history,
        so no card for it is ever submitted."""
        shown = json.dumps(
            [
                self.item,
                self.item_title,
                self.index,
                self.text,
                self.question,
                self.example,
                self.picture,
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
"""The longest note a decision may carry, after trimming. The item body stores
a note as UTF-8 text, so it is also free of NUL and encodable as UTF-8."""


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
    """The item's fresh read no longer shows the card as posted: a line changed,
    went, or was withdrawn, or the item itself is gone, malformed or closed."""


class DecisionSourceUnavailableError(Exception):
    """The source could not be read; the message says why in one sentence."""


type CardCheck = Callable[[Sequence[ExpectationLine]], CardDecision | None]
"""The board's own check of a posted card against an item's lines just read:
the card as a decision on them, or None when it no longer reads as shown."""


class DecisionPort(Protocol):
    def expectation_lines(self) -> tuple[ExpectationLine, ...]:
        """Every expectation line, open and ruled, in the source's own order.

        Raises `DecisionSourceUnavailableError` when the source cannot answer.
        """
        ...

    def rule_card(self, item: int, check: CardCheck) -> DecisionResult | CardChanged:
        """Read `item` once, run `check` on its lines, and write the decision it
        returns in one write that stores every line or none; `CardChanged` when
        the item no longer holds the card `check` was built for."""
        ...
