"""The decisions waiting on the operator.

The per-repository read: the rows `aco rulings` prints, on the items a member
of the repository wrote and no other. In a public repository a stranger can
open an item that carries a card, and a card reaches the operator's decision
surface only from a writer of the repository.

The read across repositories: of those rows, the option lines still waiting on
the operator, for every repository discovery found.
"""

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from . import body, expectations, protocol, repositories, rulings, workboard


def rows(issues: Iterable[workboard.Issue], *, storage: body.Storage) -> tuple[rulings.Row, ...]:
    """`rulings.rows` over the members' items among `issues`."""
    members = (issue for issue in issues if issue.author_is_member)
    return rulings.rows(members, storage=storage)


def waiting_rows(rows_read: Iterable[rulings.Row]) -> tuple[rulings.Row, ...]:
    """Of `rows_read`, each item that still has a line waiting on the operator,
    reduced to those lines: an option line neither ruled, nor returned to its
    head, nor withdrawn. A returned line is with its head."""
    waiting: list[rulings.Row] = []
    for row in rows_read:
        lines = tuple(
            line for line in row.lines if expectations.is_open(line) and line.returned is None
        )
        if lines:
            waiting.append(replace(row, lines=lines))
    return tuple(waiting)


type RowReader = Callable[[repositories.Repository], tuple[rulings.Row, ...]]
"""One repository's rows, as `rows` returns them; raises `protocol.ClaimError`
or `OSError` when that repository cannot be read."""


@dataclass(frozen=True)
class Waiting:
    repository: str
    rows: tuple[rulings.Row, ...]


@dataclass(frozen=True)
class Unavailable:
    repository: str
    reason: str


@dataclass(frozen=True)
class Inbox:
    root: Path
    entries: tuple[Waiting | Unavailable, ...]
    """One per discovered repository, in discovery's order."""
    unreadable: tuple[repositories.UnavailableCheckout, ...]


def read(discovery: repositories.Discovery, read_rows: RowReader) -> Inbox:
    """What waits on the operator in every repository of `discovery`, the
    repositories read concurrently; one that cannot be read is listed as
    unavailable and the others are still read."""

    def read_one(repository: repositories.Repository) -> Waiting | Unavailable:
        try:
            return Waiting(repository.label, waiting_rows(read_rows(repository)))
        except (protocol.ClaimError, OSError) as error:
            return Unavailable(repository.label, str(error))

    with ThreadPoolExecutor(max_workers=max(1, len(discovery.repositories))) as pool:
        entries = tuple(pool.map(read_one, discovery.repositories))
    return Inbox(discovery.root, entries, discovery.unavailable)


def inbox_json(inbox: Inbox) -> dict[str, object]:
    """The inbox as JSON: items and lines in the shapes `aco rulings --json` prints."""
    return {
        "root": str(inbox.root),
        "repositories": [
            {"repository": entry.repository, "unavailable": entry.reason}
            if isinstance(entry, Unavailable)
            else {
                "repository": entry.repository,
                "items": [rulings.row_json(row) for row in entry.rows],
            }
            for entry in inbox.entries
        ],
        "unreadable": [
            {"directory": str(checkout.directory), "reason": checkout.reason}
            for checkout in inbox.unreadable
        ],
    }
