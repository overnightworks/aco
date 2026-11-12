"""The earlier rulings of the area a card names (`specs/mcp.spec.md`), free of any
process or network call: the query a forge's search takes for the area, and the
ruled lines kept from what that search found."""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date

from . import expectations, forge, protocol

LINE_LIMIT = 5
QUERY_LIMIT = 256
"""The forge's limit on the length of a query, in characters."""
_WORD = re.compile(r"[^\W_]+")


class RecallUnavailableError(protocol.ClaimError):
    """The earlier rulings of an area cannot be answered completely."""


@dataclass(frozen=True)
class LineKey:
    """Where a line stands: the tracked repository, the item and the line's index."""

    repository: str
    item: int
    index: int


@dataclass(frozen=True)
class EarlierLine:
    """One earlier ruling: the line's place, its item's title, the question, the
    ruled option's name or the operator's own words, the day and the way."""

    repository: str
    item: int
    index: int
    title: str
    question: str
    answer: str
    ruled_on: date
    via: str

    @property
    def key(self) -> LineKey:
        return LineKey(self.repository, self.item, self.index)


@dataclass(frozen=True)
class Recall:
    """The newest `LINE_LIMIT` lines kept and how many more were kept."""

    lines: tuple[EarlierLine, ...]
    more: int


def owners_of(labels: Iterable[str]) -> tuple[str, ...]:
    """The distinct owners, sorted, of those `labels` that are `OWNER/REPO`."""
    return tuple(
        sorted(
            {
                label.partition("/")[0]
                for label in labels
                if protocol.REPOSITORY_PATTERN.fullmatch(label)
            }
        )
    )


def search_query(area: str, owners: Iterable[str]) -> str:
    """The query for the ruled lines of `area` in issue bodies of `owners`: one
    phrase of the word `area` and the area's lowercased letter and digit words,
    so no character of the area acts as an operator, and one qualifier per
    owner. Raises `RecallUnavailableError` for an area without such a word, no
    owner, or a query over the forge's length limit."""
    words = _WORD.findall(area.lower())
    qualifiers = [f"user:{owner}" for owner in sorted(set(owners))]
    if not words:
        raise RecallUnavailableError("the card's area holds no letter or digit word to search for")
    if not qualifiers:
        raise RecallUnavailableError("no tracked repository names an owner to search")
    query = " ".join((f'"area {" ".join(words)}"', "in:body", "is:issue", *qualifiers))
    if len(query) > QUERY_LIMIT:
        raise RecallUnavailableError(f"the search query runs past {QUERY_LIMIT} characters")
    return query


def _answer(line: expectations.OptionLine, ruling: expectations.OptionRuling) -> str:
    answer = ruling.answer
    if isinstance(answer, expectations.OtherAnswer):
        return answer.text
    return {option.letter: option.name for option in line.options}[answer]


def _ruled_lines(item: forge.RulingItem, repository: str, area: str) -> Iterator[EarlierLine]:
    """The option lines of `item`, which `repository` names, that are ruled and
    whose area equals `area` without regard to case."""
    for line in expectations.expectation_lines(item.body):
        if (
            isinstance(line, expectations.OptionLine)
            and line.decision is not None
            and line.area.casefold() == area.casefold()
        ):
            yield EarlierLine(
                repository,
                item.number,
                line.index,
                item.title,
                line.question,
                _answer(line, line.decision),
                line.decision.ruled_on,
                line.decision.via.value,
            )


def _order(line: EarlierLine) -> tuple[int, str, int, int]:
    return (-line.ruled_on.toordinal(), line.repository, -line.item, line.index)


def recall(
    result: forge.RulingSearchResult,
    *,
    area: str,
    tracked: Iterable[str],
    asked: LineKey,
) -> Recall:
    """The ruled lines of `area` among the items of `result` that a member wrote
    in a `tracked` repository, `asked` left out, newest ruling day first, the
    newest `LINE_LIMIT` of them. Raises `RecallUnavailableError` for an
    incomplete result, whose newest line may be missing."""
    if not result.complete:
        raise RecallUnavailableError("the forge's search result is incomplete")
    labels = {label.casefold(): label for label in tracked}
    members = {
        (labels[item.repository.casefold()], item.number): item
        for item in result.items
        if item.author_is_member and item.repository.casefold() in labels
    }
    kept = sorted(
        (
            line
            for (repository, _), item in members.items()
            for line in _ruled_lines(item, repository, area)
            if line.key != asked
        ),
        key=_order,
    )
    return Recall(tuple(kept[:LINE_LIMIT]), len(kept[LINE_LIMIT:]))


def earlier_json(found: Recall) -> dict[str, object]:
    """The keys `earlier` and `earlier_more` of the `ask` answer."""
    return {
        "earlier": [
            {
                "repository": line.repository,
                "item": line.item,
                "title": line.title,
                "question": line.question,
                "answer": line.answer,
                "ruled_on": line.ruled_on.isoformat(),
                "via": line.via,
            }
            for line in found.lines
        ],
        "earlier_more": found.more,
    }
