"""The decisions waiting on the operator.

The per-repository read: the rows `aco rulings` prints, on the items a member
of the repository wrote and no other. In a public repository a stranger can
open an item that carries a card, and a card reaches the operator's decision
surface only from a writer of the repository.

The steps only the operator can take come from the same items: those a member
wrote that carry the `needs-operator` label, each with its block's `next`.

The read across repositories: of those rows, the option lines still waiting on
the operator, and the steps, for every repository discovery found.
"""

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from . import body, expectations, protocol, repositories, rulings, session, workboard


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


@dataclass(frozen=True)
class Step:
    number: int
    title: str
    next_step: str | None
    """The block's `next`; `None` when the body has no readable block."""


def steps(issues: Iterable[workboard.Issue], *, storage: body.Storage) -> tuple[Step, ...]:
    """The members' readable items among `issues` that carry the
    `needs-operator` label, by descending number."""
    found = [
        Step(
            issue.number,
            issue.title,
            body.parse_body(issue.body, storage=storage).contract.next,
        )
        for issue in issues
        if issue.author_is_member
        and issue.unreadable is None
        and workboard.has_label(issue.labels, workboard.NEEDS_OPERATOR_LABEL)
    ]
    return tuple(sorted(found, key=lambda step: -step.number))


@dataclass(frozen=True)
class Reading:
    """What one listing of a repository's open items holds for the operator."""

    rows: tuple[rulings.Row, ...]
    steps: tuple[Step, ...]


def read_issues(issues: Iterable[workboard.Issue], *, storage: body.Storage) -> Reading:
    """The rows and the steps among `issues`, which are listed once."""
    listed = tuple(issues)
    return Reading(rows(listed, storage=storage), steps(listed, storage=storage))


def read_context(context: session.RunContext) -> Reading:
    """The rows and the steps of the checkout `context` is bound to, from one
    listing of its open items."""
    return read_issues(context.forge.list_open_board_issues(), storage=context.config.storage)


type IssueReader = Callable[[repositories.Repository], Reading]
"""One repository's `Reading`; raises `protocol.ClaimError` or `OSError` when
that repository cannot be read."""


@dataclass(frozen=True)
class Waiting:
    repository: str
    rows: tuple[rulings.Row, ...]
    steps: tuple[Step, ...]


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


def read(discovery: repositories.Discovery, read_issues_of: IssueReader) -> Inbox:
    """What waits on the operator in every repository of `discovery`, the
    repositories read concurrently; one that cannot be read is listed as
    unavailable and the others are still read."""

    def read_one(repository: repositories.Repository) -> Waiting | Unavailable:
        try:
            reading = read_issues_of(repository)
            return Waiting(repository.label, waiting_rows(reading.rows), reading.steps)
        except (protocol.ClaimError, OSError) as error:
            return Unavailable(repository.label, str(error))

    with ThreadPoolExecutor(max_workers=max(1, len(discovery.repositories))) as pool:
        entries = tuple(pool.map(read_one, discovery.repositories))
    return Inbox(discovery.root, entries, discovery.unavailable)


def step_json(step: Step) -> dict[str, object]:
    return {"number": step.number, "title": step.title, "step": step.next_step}


def inbox_json(inbox: Inbox) -> dict[str, object]:
    """The inbox as JSON: items and lines in the shapes `aco rulings --json`
    prints, and the steps."""
    return {
        "root": str(inbox.root),
        "repositories": [
            {"repository": entry.repository, "unavailable": entry.reason}
            if isinstance(entry, Unavailable)
            else {
                "repository": entry.repository,
                "items": [rulings.row_json(row) for row in entry.rows],
                "steps": [step_json(step) for step in entry.steps],
            }
            for entry in inbox.entries
        ],
        "unreadable": [
            {"directory": str(checkout.directory), "reason": checkout.reason}
            for checkout in inbox.unreadable
        ],
    }
