"""The expectation line model and its two writes: the `[[expectation]]` entries
of a work-item body as `aco rulings`, `aco rule --line` and `aco ask` see
them, and the byte-preserving edits that rule or append one. The entry grammar
is `expectation_grammar`'s; the block codec is `body`'s.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from typing import ClassVar, TypeAlias, cast

from . import protocol
from .body import (
    BodyReadState,
    Storage,
    block_expectation_dicts,
    locate_block,
    parse_body,
    replace_block,
)
from .expectation_grammar import (
    BLOCK_EXPECTATION_DEFAULTS,
    BLOCK_EXPECTATION_RULINGS,
    EXPECTATION_OPTIONAL_FIELDS,
    OPTION_LETTERS,
    DecisionKind,
    Undo,
    card_hash,
    is_option_line,
)

EXPECTATION_LINE_TEXT_MAXIMUM = 100


class LineForm(StrEnum):
    """Which of the two line forms an `[[expectation]]` entry takes."""

    YES_NO = "yes_no"
    OPTIONS = "options"


@dataclass(frozen=True)
class YesNoLine:
    """One `[[expectation]]` entry as `rule --line`, `ask`, and `rulings`
    see it: `index` is its 1-based position in block order -- what `rule
    --line` accepts and what `rulings` prints -- `text` its full prose, and
    `ruling`/`ruled_on` present only once a `rule` call has replaced its
    `default`. `default` is the line's own default (`str | None`, `None`
    once ruled) -- `aco rulings --json`'s own line payload reads it from
    here rather than re-parsing the block. `question`/`example`/`picture`
    are the card's optional operator-language heading, illustration
    sentence, and inline SVG -- `None` when `aco ask` was not given them,
    in which case a card falls back to `text`."""

    form: ClassVar[LineForm] = LineForm.YES_NO
    index: int
    text: str
    ruling: str | None
    ruled_on: date | None
    default: str | None = None
    question: str | None = None
    example: str | None = None
    picture: str | None = None

    @property
    def card_hash(self) -> str:
        """The hash of the card this line shows (BODY-89)."""
        return card_hash(asdict(self))


@dataclass(frozen=True)
class ResultPicture:
    """An option's RESULT drawn as its own picture, with an optional caption."""

    picture: str
    caption: str | None


@dataclass(frozen=True)
class CardOption:
    """One option of an option line; `letter` is derived from its position,
    and `result` is `None` when the result is the same as today."""

    letter: str
    name: str
    effect: str
    result: ResultPicture | None
    notice: str
    cost: str
    undo: Undo
    undo_how: str
    contract: str


@dataclass(frozen=True)
class OptionRuling:
    """The decided state of a ruled option line: the chosen letter and its date."""

    letter: str
    ruled_on: date


@dataclass(frozen=True)
class OptionLine:
    """One `[[expectation]]` entry that offers lettered options, as `rulings`
    sees it: the card's own fields, its options in order, `decision`
    `None` while the line is open, and `card_hash` the hash of the card it
    shows -- for a ruled line equal to the stored one, or the body would be
    malformed (BODY-87)."""

    form: ClassVar[LineForm] = LineForm.OPTIONS
    index: int
    text: str
    question: str
    problem: str
    picture: str
    caption: str
    decision_kind: DecisionKind
    area: str
    topic: str
    recommended: str
    reason: str
    options: tuple[CardOption, ...]
    decision: OptionRuling | None
    card_hash: str

    @property
    def ruling(self) -> str | None:
        return None if self.decision is None else self.decision.letter

    @property
    def ruled_on(self) -> date | None:
        return None if self.decision is None else self.decision.ruled_on


ExpectationLine: TypeAlias = YesNoLine | OptionLine


def _card_option(position: int, option: dict[str, object]) -> CardOption:
    picture = option.get("picture")
    result = (
        None
        if picture is None
        else ResultPicture(cast(str, picture), cast(str | None, option.get("caption")))
    )
    return CardOption(
        letter=OPTION_LETTERS[position],
        name=cast(str, option["name"]),
        effect=cast(str, option["effect"]),
        result=result,
        notice=cast(str, option["notice"]),
        cost=cast(str, option["cost"]),
        undo=Undo(cast(str, option["undo"])),
        undo_how=cast(str, option["undo_how"]),
        contract=cast(str, option["contract"]),
    )


def _option_line(index: int, entry: dict[str, object]) -> OptionLine:
    options = cast(list[dict[str, object]], entry["option"])
    decision = (
        OptionRuling(cast(str, entry["ruling"]), cast(date, entry["ruled_on"]))
        if "ruling" in entry
        else None
    )
    return OptionLine(
        index=index,
        text=cast(str, entry["text"]),
        question=cast(str, entry["question"]),
        problem=cast(str, entry["problem"]),
        picture=cast(str, entry["picture"]),
        caption=cast(str, entry["caption"]),
        decision_kind=DecisionKind(cast(str, entry["decision_kind"])),
        area=cast(str, entry["area"]),
        topic=cast(str, entry["topic"]),
        recommended=cast(str, entry["recommended"]),
        reason=cast(str, entry["reason"]),
        options=tuple(_card_option(position, option) for position, option in enumerate(options)),
        decision=decision,
        card_hash=card_hash(entry),
    )


def _yes_no_line(index: int, entry: dict[str, object]) -> YesNoLine:
    return YesNoLine(
        index=index,
        text=cast(str, entry["text"]),
        ruling=cast(str | None, entry.get("ruling")),
        ruled_on=cast("date | None", entry.get("ruled_on")),
        default=cast(str | None, entry.get("default")),
        question=cast(str | None, entry.get("question")),
        example=cast(str | None, entry.get("example")),
        picture=cast(str | None, entry.get("picture")),
    )


def expectation_lines(
    body: str, *, storage: Storage = Storage.GITHUB
) -> tuple[ExpectationLine, ...]:
    """Every `[[expectation]]` entry of `body`'s `aco` block, in
    block order -- the one projection `rulings`, `rule --line`, and `ask`'s
    fresh index all share, so a printed index always matches what `rule`
    accepts. Empty for a body with no block, no expectations, or one
    `parse_body` reads as MALFORMED -- a malformed body's lines are not
    addressable until it is fixed by hand. `storage` is forwarded to
    `parse_body` unchanged."""
    if parse_body(body, storage=storage).read_state is not BodyReadState.VALID:
        return ()
    entries = block_expectation_dicts(locate_block(body).data)
    return tuple(
        _option_line(position, entry) if is_option_line(entry) else _yes_no_line(position, entry)
        for position, entry in enumerate(entries, start=1)
    )


def expectation_line_state(line: ExpectationLine) -> str:
    """`open`, or `ruled <ruling> <ruled_on>` -- the one state text
    `rulings`' human form prints; `--json` carries `ruling`/`ruled_on`
    directly and does not call this."""
    if line.ruling is None:
        return "open"
    ruled_on = cast(date, line.ruled_on)
    return f"ruled {line.ruling} {ruled_on.isoformat()}"


def expectation_line_summary(line: ExpectationLine) -> str:
    """`line.text` on one line, truncated to `EXPECTATION_LINE_TEXT_MAXIMUM`
    characters -- `rulings`' human form; `--json` carries the full text."""
    one_line = " ".join(line.text.split())
    maximum = EXPECTATION_LINE_TEXT_MAXIMUM
    return one_line if len(one_line) <= maximum else one_line[: maximum - 1] + "…"


class ExpectationAlreadyRuledError(protocol.ClaimError):
    """`rule_expectation`'s own already-ruled refusal -- a
    distinct type from `ExpectationOutOfRangeError` so a `--json`-emitting
    caller can choose `already_ruled` without parsing the refusal prose."""


class ExpectationOutOfRangeError(protocol.ClaimError):
    """`rule_expectation`'s own out-of-range `--line` refusal."""


class ExpectationOptionLineError(protocol.ClaimError):
    """`rule_expectation`'s own refusal to rule an option line with a
    yes/no outcome, which would store a value the grammar refuses."""


def rule_expectation(
    body: str, index: int, ruling: str, ruled_on: date, *, note: str | None = None
) -> str:
    """Rule one proposed line, preserving card fields and bytes outside the block.

    Replace the default with outcome/date; append any note to its text.
    Refuse invalid outcomes, out-of-range indices, option lines and
    already-ruled lines, in that order.
    """
    if ruling not in BLOCK_EXPECTATION_RULINGS:
        raise protocol.ClaimError(
            f"ruling must be one of {', '.join(sorted(BLOCK_EXPECTATION_RULINGS))}"
        )
    located = locate_block(body)
    entries = block_expectation_dicts(located.data)
    if not 1 <= index <= len(entries):
        raise ExpectationOutOfRangeError(
            f"line {index} out of range: this item has {len(entries)} expectation line(s)"
        )
    entry = entries[index - 1]
    if is_option_line(entry):
        raise ExpectationOptionLineError(
            f"line {index} is an option line; --yes, --no and --later rule only a yes/no line"
        )
    if "ruling" in entry:
        raise ExpectationAlreadyRuledError(
            f"line {index} is already ruled; a changed ruling is a new line"
        )
    text = cast(str, entry["text"]) if note is None else f"{entry['text']} Anmerkung: {note}"
    ruled_entry = dict(entry)
    ruled_entry.pop("default", None)
    ruled_entry.update(text=text, ruling=ruling, ruled_on=ruled_on)
    new_entries = [*entries[: index - 1], ruled_entry, *entries[index:]]
    new_data = {**located.data, "expectation": new_entries}
    return replace_block(body, located, new_data)


@dataclass(frozen=True)
class ExpectationCardFields:
    """The three optional `[[expectation]]` card fields `aco ask` may
    attach, grouped so a caller passes one value instead of
    three positional strings that must stay paired: `question` and
    `example`, one operator-language sentence each, and `picture`, an
    inline SVG. Each defaults to absent, matching a line with none of
    them -- the card then falls back to `text`."""

    question: str | None = None
    example: str | None = None
    picture: str | None = None


class ExpectationTextError(protocol.ClaimError):
    """`append_expectation`'s own blank-`text` refusal -- a
    distinct type from `ExpectationFieldError` so a `--json`-emitting caller
    can choose `invalid_expectation` without parsing the refusal prose."""


class ExpectationFieldError(protocol.ClaimError):
    """`append_expectation`'s own optional-card-field refusal -- `question`,
    `example`, or `picture` failing its own content rule --
    carrying the failing `field` by name so a `--json`-emitting caller can
    choose `invalid_expectation` (`question`, `example`) or `invalid_picture`
    (`picture`) without parsing the refusal prose."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def append_expectation(
    body: str, text: str, default: str, *, card: ExpectationCardFields | None = None
) -> str:
    """`body` with one fresh proposed `[[expectation]]` entry appended:
    `text` verbatim, `default` as given, plus whichever of `card`'s
    optional fields `aco ask` was given -- each validated by
    the same check `_block_expectation_optional_field_defects` reads a
    stored body with, so a value this refuses can never be written.
    Byte-preserving outside the appended entry, the same write path as
    `rule_expectation`."""
    if not text.strip():
        raise ExpectationTextError("expectation text must be a non-empty string")
    if default not in BLOCK_EXPECTATION_DEFAULTS:
        raise protocol.ClaimError(
            f"default must be one of {', '.join(sorted(BLOCK_EXPECTATION_DEFAULTS))}"
        )
    provided = asdict(card if card is not None else ExpectationCardFields())
    entry: dict[str, object] = {"text": text, "default": default}
    for key, check in EXPECTATION_OPTIONAL_FIELDS:
        value = provided[key]
        if value is None:
            continue
        reason = check(value)
        if reason is not None:
            raise ExpectationFieldError(key, f"{key} {reason}")
        entry[key] = value
    located = locate_block(body)
    entries = block_expectation_dicts(located.data)
    new_entries = [*entries, entry]
    new_data = {**located.data, "expectation": new_entries}
    return replace_block(body, located, new_data)
