"""The board's one narrow interface to its decision source.

The board reads aco's rows and writes rulings through `DecisionPort` only;
`aco_source.AcoSource` is its one implementation, running aco's own library
in process. Truth stays with the source: the board keeps no copy of a line or
a ruling, and reads aco's own types rather than copies of them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .. import expectations, rulings

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
    letter: str | None


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
    letter: str | None


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


type CardCheck = Callable[[Sequence[expectations.ExpectationLine]], CardDecision | None]
"""The board's own check of a posted card against aco's lines of the one item
just read: the card as a decision on them, or None when it no longer reads as
shown."""


class DecisionPort(Protocol):
    def rows(self) -> tuple[rulings.Row, ...]:
        """Every open item with expectation lines, as `aco rulings` reads them,
        in its order (RUL-03).

        Raises `DecisionSourceUnavailableError` when the source cannot answer.
        """
        ...

    def rule_card(self, item: int, check: CardCheck) -> DecisionResult | CardChanged:
        """Read `item` once, run `check` on its lines, and write the decision it
        returns in one write that stores every line or none; `CardChanged` when
        the item no longer holds the card `check` was built for."""
        ...
