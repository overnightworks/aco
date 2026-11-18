"""The board's one narrow interface to its decision source.

The board reads aco's rows and writes rulings through `DecisionPort` only;
`aco_source.AcoSource` is its one implementation, running aco's own library
in process. Truth stays with the source: the board keeps no copy of a line or
a ruling, and reads aco's own types rather than copies of them.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .. import expectations, inbox, item_step

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


@dataclass(frozen=True)
class StepPost:
    """The operator's answer to a step as the browser posted it: the fingerprint of
    the step it was shown with, before it is checked against a fresh read."""

    item: int
    fingerprint: str
    result: item_step.StepResult


class DecisionStatus(StrEnum):
    ANSWERED = "answered"
    RULED = "ruled"
    RETURNED = "returned"
    ALREADY_RULED = "already_ruled"
    FAILED = "failed"


class ListedItem(Protocol):
    """An item with its lines, as the board lists it: `rulings.Row`,
    `decide.Committed` and the re-read item of a kept write satisfy it.
    Read-only properties, so frozen dataclass fields and tuples fit."""

    @property
    def number(self) -> int: ...

    @property
    def title(self) -> str: ...

    @property
    def lines(self) -> Sequence[expectations.ExpectationLine]: ...


@dataclass(frozen=True)
class DecisionResult:
    status: DecisionStatus
    message: str | None = None
    item: ListedItem | None = None
    """The item as written, set on a stored card answer (`ruled`, `returned`)."""
    note: str | None = None
    """What the operator should know of a stored answer; set only beside `item`
    or on an `answered` step."""


@dataclass(frozen=True)
class CardChanged:
    """The item's fresh read no longer shows the card or step as posted: a line
    changed, went, or was withdrawn, the step was answered or marked again, or the
    item itself is gone, malformed or closed."""


class DecisionSourceUnavailableError(Exception):
    """The source could not be read; the message says why in one sentence."""


type CardCheck = Callable[[Sequence[expectations.ExpectationLine]], CardDecision | None]
"""The board's own check of a posted card against aco's lines of the one item
just read: the card as a decision on them, or None when it no longer reads as
shown."""


type StepCheck = Callable[[inbox.Step], bool]
"""The board's own check of a posted step against aco's step of the one item just
read: whether it still reads as shown."""


class DecisionPort(Protocol):
    def reading(self) -> inbox.Reading:
        """What one listing of the open items holds for the operator: every item
        with expectation lines, as `aco rulings` reads them in its order (RUL-03).

        Raises `DecisionSourceUnavailableError` when the source cannot answer.
        """
        ...

    def rule_card(self, item: int, check: CardCheck) -> DecisionResult | CardChanged:
        """Read `item` once, run `check` on its lines, and write the decision it
        returns in one write that stores every line or none; `CardChanged` when
        the item no longer holds the card `check` was built for."""
        ...

    def answer_step(
        self, item: int, result: item_step.StepResult, check: StepCheck
    ) -> DecisionResult | CardChanged:
        """Read `item` once, run `check` on the step that read shows, and write
        `result` as its answer; `CardChanged` when the item shows no step of the
        operator's or `check` refuses it."""
        ...
