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
from typing import Protocol


class Outcome(StrEnum):
    YES = "yes"
    NO = "no"
    LATER = "later"


@dataclass(frozen=True)
class ExpectationLine:
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


class DecisionStatus(StrEnum):
    RULED = "ruled"
    ALREADY_RULED = "already_ruled"
    FAILED = "failed"


@dataclass(frozen=True)
class DecisionResult:
    status: DecisionStatus
    message: str | None = None


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
