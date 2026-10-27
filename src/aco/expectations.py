"""The expectation line model and its writes: the `[[expectation]]` entries
of a work-item body as `aco rulings` and `aco rule --line` see
them, and the byte-preserving edits that rule one. The entry grammar
is `expectation_grammar`'s; the block codec is `body`'s.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
    OPTION_LETTERS,
    OTHER,
    RETURNED_NOTE,
    RETURNED_ON,
    DecisionKind,
    RulingVia,
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
    sentence, and inline SVG -- `None` when the line carries none,
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
class OtherAnswer:
    """The operator's own answer to an option card, verbatim, where a letter
    would stand."""

    text: str


@dataclass(frozen=True)
class OptionRuling:
    """The decided state of a ruled option line: the chosen letter or the
    operator's own answer, its date, the card hash stored with the ruling and
    how the decision reached aco."""

    answer: str | OtherAnswer
    ruled_on: date
    card_hash: str
    via: RulingVia


@dataclass(frozen=True)
class ReturnedToHead:
    """An open option line the operator sent back to its head: the day, and
    the note he gave, if any, verbatim."""

    returned_on: date
    note: str | None


@dataclass(frozen=True)
class OptionLine:
    """One `[[expectation]]` entry that offers lettered options, as `rulings`
    sees it: the card's own fields, its options in order, `decision`
    `None` while the line is open, `returned` set while the open line is with
    its head, and `card_hash` the hash of the card it shows -- for a ruled
    line equal to the stored one, or the body would be malformed (BODY-87)."""

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
    returned: ReturnedToHead | None
    card_hash: str

    @property
    def ruling(self) -> str | None:
        if self.decision is None:
            return None
        answer = self.decision.answer
        return OTHER if isinstance(answer, OtherAnswer) else answer

    @property
    def other_answer(self) -> str | None:
        """The operator's own answer, verbatim, when the line is ruled `other`."""
        answer = None if self.decision is None else self.decision.answer
        return answer.text if isinstance(answer, OtherAnswer) else None

    @property
    def ruled_on(self) -> date | None:
        return None if self.decision is None else self.decision.ruled_on

    @property
    def spoken_text(self) -> str:
        """What the line says now: the operator's own answer, else the note it
        went back with, else its text."""
        returned_note = None if self.returned is None else self.returned.note
        for words in (self.other_answer, returned_note):
            if words is not None:
                return words
        return self.text


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


def _option_ruling(entry: dict[str, object]) -> OptionRuling:
    ruling = cast(str, entry["ruling"])
    return OptionRuling(
        OtherAnswer(cast(str, entry[OTHER])) if ruling == OTHER else ruling,
        cast(date, entry["ruled_on"]),
        cast(str, entry["card_hash"]),
        RulingVia(cast(str, entry["via"])),
    )


def _with_its_head(entry: dict[str, object]) -> bool:
    return RETURNED_ON in entry


def _returned_to_head(entry: dict[str, object]) -> ReturnedToHead | None:
    if not _with_its_head(entry):
        return None
    return ReturnedToHead(
        cast(date, entry[RETURNED_ON]), cast(str | None, entry.get(RETURNED_NOTE))
    )


def _option_line(index: int, entry: dict[str, object]) -> OptionLine:
    options = cast(list[dict[str, object]], entry["option"])
    decision = _option_ruling(entry) if "ruling" in entry else None
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
        returned=_returned_to_head(entry),
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


def returned_line_indexes(body: str, *, storage: Storage = Storage.GITHUB) -> tuple[int, ...]:
    """The indexes of `body`'s option lines sent back to their head, in
    block order -- empty for a body `expectation_lines` cannot read."""
    return tuple(
        line.index
        for line in expectation_lines(body, storage=storage)
        if isinstance(line, OptionLine) and line.returned is not None
    )


def expectation_line_state(line: ExpectationLine) -> str:
    """`open`, `with head <returned_on>` or `ruled <ruling> <ruled_on>` -- the
    one state text `rulings`' human form prints; `--json` carries
    `ruling`/`ruled_on`/`returned_on` directly and does not call this."""
    if isinstance(line, OptionLine) and line.returned is not None:
        return f"with head {line.returned.returned_on.isoformat()}"
    if line.ruling is None:
        return "open"
    ruled_on = cast(date, line.ruled_on)
    return f"ruled {line.ruling} {ruled_on.isoformat()}"


def expectation_line_summary(line: ExpectationLine) -> str:
    """`line.text` -- the operator's own answer for an option line ruled
    `other`, the note of one with its head -- on one line, truncated to
    `EXPECTATION_LINE_TEXT_MAXIMUM` characters -- `rulings`' human form;
    `--json` carries the full text."""
    words = line.spoken_text if isinstance(line, OptionLine) else line.text
    one_line = " ".join(words.split())
    maximum = EXPECTATION_LINE_TEXT_MAXIMUM
    return one_line if len(one_line) <= maximum else one_line[: maximum - 1] + "…"


class ExpectationAlreadyRuledError(protocol.ClaimError):
    """The already-ruled refusal -- a
    distinct type from `ExpectationOutOfRangeError` so a `--json`-emitting
    caller can choose `already_ruled` without parsing the refusal prose."""


class ExpectationOutOfRangeError(protocol.ClaimError):
    """The out-of-range `--line` refusal."""


class ExpectationLineFormError(protocol.ClaimError):
    """A ruling aimed at a yes/no line: an option outcome on it would store
    a value the grammar refuses."""


class ExpectationCardChangedError(protocol.ClaimError):
    """`rule_option`'s refusal of a card that changed since it was shown."""


class ExpectationWithHeadError(protocol.ClaimError):
    """A send-back or a default ruling that a line already with its head
    refuses."""


class ExpectationOptionChoiceError(protocol.ClaimError):
    """`rule_option`'s refusal of a letter the card does not offer, or of a
    kept recommendation that names another letter."""


_OPTION_FLAG = "--option"
_OTHER_FLAG = "--other"
_UNCLEAR_FLAG = "--unclear"
_RETURNED_KEYS = (RETURNED_ON, RETURNED_NOTE)


def _open_entry(
    entries: list[dict[str, object]], index: int, option_flag: str
) -> dict[str, object]:
    """Line `index` of `entries`, still open and an option line; refuses an
    out-of-range index, a yes/no line and an already-ruled line, in that
    order -- the checks both writes share."""
    if not 1 <= index <= len(entries):
        raise ExpectationOutOfRangeError(
            f"line {index} out of range: this item has {len(entries)} expectation line(s)"
        )
    entry = entries[index - 1]
    if not is_option_line(entry):
        verb = "returns" if option_flag == _UNCLEAR_FLAG else "rules"
        raise ExpectationLineFormError(
            f"line {index} is a yes/no line; {option_flag} {verb} only an option line"
        )
    if "ruling" in entry:
        raise ExpectationAlreadyRuledError(
            f"line {index} is already ruled; a changed ruling is a new line"
        )
    return entry


_Decide: TypeAlias = Callable[[dict[str, object]], dict[str, object]]


def _rule_entry(body: str, index: int, decide: _Decide, option_flag: str = _OPTION_FLAG) -> str:
    """`body` with its open option line `index` replaced by `decide`'s
    ruled entry; bytes outside the block are preserved."""
    located = locate_block(body)
    entries = block_expectation_dicts(located.data)
    ruled_entry = decide(_open_entry(entries, index, option_flag))
    new_entries = [*entries[: index - 1], ruled_entry, *entries[index:]]
    new_data = {**located.data, "expectation": new_entries}
    return replace_block(body, located, new_data)


@dataclass(frozen=True)
class OptionChoice:
    """What a decider picked on a shown option card: the `answer` -- a letter
    or the operator's own words -- how the decision reached aco, and the hash
    of the card that was shown."""

    answer: str | OtherAnswer
    via: RulingVia
    shown_card_hash: str


@dataclass(frozen=True)
class HeadReturn:
    """What the operator asked for on a shown option card he found unclear:
    the note he gave, if any, and the hash of the card that was shown. Nothing
    is decided, so it is never an `OptionChoice`."""

    note: str | None
    shown_card_hash: str


def _refuse_a_changed_card(index: int, entry: dict[str, object], shown_card_hash: str) -> None:
    """The card shown is the card now."""
    if shown_card_hash != card_hash(entry):
        raise ExpectationCardChangedError(
            f"line {index} changed since its card was shown; show it again and rule what it "
            "shows now"
        )


def _refuse_a_wrong_choice(index: int, entry: dict[str, object], choice: OptionChoice) -> None:
    """The choice checks after the card's: a letter is on it and, kept as
    recommended, is the recommended one, in that order. An own answer needs no
    letter."""
    letter = choice.answer
    if isinstance(letter, OtherAnswer):
        return
    letters = tuple(OPTION_LETTERS[: len(cast(list[object], entry["option"]))])
    if letter not in letters:
        raise ExpectationOptionChoiceError(
            f"line {index} has no option {letter}; its options are {', '.join(letters)}"
        )
    recommended = entry["recommended"]
    if choice.via is RulingVia.DEFAULT and letter != recommended:
        raise ExpectationOptionChoiceError(
            f"--via default keeps only the recommended option {recommended}, not {letter}"
        )


def rule_option(body: str, index: int, choice: OptionChoice, ruled_on: date) -> str:
    """Decide one open option line: it gains `ruling`, `ruled_on`,
    `card_hash` and `via` -- and `other` when the answer is the operator's
    own -- and keeps every other key, so its stored hash is the hash of the
    card it shows -- and drops `returned_on` and `returned_note` of a line that
    was with its head. Refuses as `_open_entry` does, then a default ruling of
    a line with its head, a changed card, and as `_refuse_a_wrong_choice` does,
    before any write."""
    answer = choice.answer
    if isinstance(answer, OtherAnswer):
        ruling, own_answer, flag = OTHER, {OTHER: answer.text}, _OTHER_FLAG
    else:
        ruling, own_answer, flag = answer, {}, _OPTION_FLAG

    def decide(entry: dict[str, object]) -> dict[str, object]:
        if _with_its_head(entry) and choice.via is RulingVia.DEFAULT:
            raise ExpectationWithHeadError(
                f"line {index} was answered Unclear; --via default records no answer"
            )
        _refuse_a_changed_card(index, entry, choice.shown_card_hash)
        _refuse_a_wrong_choice(index, entry, choice)
        return {
            **{key: value for key, value in entry.items() if key not in _RETURNED_KEYS},
            "ruling": ruling,
            "ruled_on": ruled_on,
            "card_hash": choice.shown_card_hash,
            "via": choice.via.value,
            **own_answer,
        }

    return _rule_entry(body, index, decide, flag)


def return_to_head(body: str, index: int, request: HeadReturn, returned_on: date) -> str:
    """Send one open option line back to its head: it gains `returned_on` and,
    with a note, `returned_note`, and keeps every other key. Refuses as
    `_open_entry` does, then a line already with its head, then a changed
    card, before any write."""

    def decide(entry: dict[str, object]) -> dict[str, object]:
        if _with_its_head(entry):
            raise ExpectationWithHeadError(
                f"line {index} is already with its head; it comes back once revised"
            )
        _refuse_a_changed_card(index, entry, request.shown_card_hash)
        note = {} if request.note is None else {RETURNED_NOTE: request.note}
        return {**entry, RETURNED_ON: returned_on, **note}

    return _rule_entry(body, index, decide, _UNCLEAR_FLAG)
