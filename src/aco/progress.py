"""The progress view: how much of each top-level container is closed.

Derived from one listing of a repository's open items. A container's planned
work is every child it has plus every `[[slice]]` row it has not yet cut; its
closed work is the children that are closed, whatever way they closed. A
container with a parent is part of that parent's work and has no line of its
own, so a repository's line is the sum of its top-level containers.
"""

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import body, protocol, workboard

_PERCENT = 100
_PARENT_READ_CONCURRENCY = 8


def percent(closed: int, planned: int) -> int | None:
    """The whole percent of `planned` that is `closed`, rounded down, so that
    100 shows only when nothing is open or uncut; `None` when nothing is planned."""
    return None if planned == 0 else _PERCENT * closed // planned


@dataclass(frozen=True)
class Container:
    number: int
    title: str
    closed: int
    open: int
    uncut: int

    @property
    def planned(self) -> int:
        return self.closed + self.open + self.uncut

    @property
    def percent(self) -> int | None:
        return percent(self.closed, self.planned)


@dataclass(frozen=True)
class Progress:
    """One repository's top-level containers and the steps waiting on the operator."""

    containers: tuple[Container, ...]
    waiting: int

    @property
    def closed(self) -> int:
        return sum(container.closed for container in self.containers)

    @property
    def open(self) -> int:
        return sum(container.open for container in self.containers)

    @property
    def uncut(self) -> int:
        return sum(container.uncut for container in self.containers)

    @property
    def planned(self) -> int:
        return self.closed + self.open + self.uncut

    @property
    def percent(self) -> int | None:
        return percent(self.closed, self.planned)


@dataclass(frozen=True)
class ProgressUnavailable:
    """The sentence of the read that kept a repository's progress from being known."""

    reason: str


def containers(
    issues: Iterable[workboard.Issue], *, storage: body.Storage
) -> tuple[Container, ...]:
    """The members' readable open containers among `issues` that the forge
    reports counts for, by ascending number."""
    found = [
        Container(
            issue.number,
            issue.title,
            issue.children_closed or 0,
            issue.children_total - (issue.children_closed or 0),
            len(body.parse_body(issue.body, storage=storage).slices),
        )
        for issue in issues
        if issue.author_is_member
        and issue.unreadable is None
        and issue.kind is body.ItemKind.CONTAINER
        and issue.children_total is not None
    ]
    return tuple(sorted(found, key=lambda container: container.number))


def of(
    issues: Iterable[workboard.Issue],
    *,
    storage: body.Storage,
    waiting: int,
    parent_of: Callable[[int], workboard.ParentIssue | None],
) -> Progress | ProgressUnavailable:
    """The progress of `issues`, which are listed once: the containers none of
    whose `parent_of` is a parent, in whichever repository it sits, with
    `waiting` operator steps. A failed read of a parent leaves the repository
    unknown rather than counted wrong."""
    counted = containers(issues, storage=storage)
    try:
        with ThreadPoolExecutor(
            max_workers=max(1, min(len(counted), _PARENT_READ_CONCURRENCY))
        ) as pool:
            parents = tuple(pool.map(lambda container: parent_of(container.number), counted))
    except protocol.ClaimError as error:
        return ProgressUnavailable(str(error))
    top_level = tuple(
        container for container, parent in zip(counted, parents, strict=True) if parent is None
    )
    return Progress(top_level, waiting)
