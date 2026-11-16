"""The progress view: how much of each top-level container is closed.

Derived from one listing of a repository's open items and the sub-issue list
of each top-level container. A container's planned work is every child it has
plus every `[[slice]]` row it has not yet cut; its closed work is the children
that are closed, whatever way they closed, of which the landed ones are those a
trunk commit's trailer names. Its waiting work is its open children that wait
on the operator. A container with a parent is part of that parent's work and
has no line of its own, so a repository's line is the sum of its top-level
containers.
"""

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import body, protocol, workboard

_PERCENT = 100
_CONTAINER_READ_CONCURRENCY = 8


def percent(closed: int, planned: int) -> int | None:
    """The whole percent of `planned` that is `closed`, rounded down, so that
    100 shows only when nothing is open or uncut; `None` when nothing is planned."""
    return None if planned == 0 else _PERCENT * closed // planned


@dataclass(frozen=True)
class Container:
    number: int
    title: str
    closed: int
    landed: int
    open: int
    waiting: int
    uncut: int

    @property
    def planned(self) -> int:
        return self.closed + self.open + self.uncut

    @property
    def percent(self) -> int | None:
        return percent(self.closed, self.planned)


@dataclass(frozen=True)
class Marks:
    """The items other sources of the repository mark: those waiting on the
    operator, and those a trunk commit's trailer names as landed."""

    operator_steps: frozenset[int]
    landed: frozenset[int]


@dataclass(frozen=True)
class Progress:
    """One repository's top-level containers and the steps waiting on the operator."""

    containers: tuple[Container, ...]
    waiting: int

    @property
    def closed(self) -> int:
        return sum(container.closed for container in self.containers)

    @property
    def landed(self) -> int:
        return sum(container.landed for container in self.containers)

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


def _counted_containers(issues: Iterable[workboard.Issue]) -> tuple[workboard.Issue, ...]:
    """The members' readable open containers among `issues` that the forge
    reports counts for, by ascending number; the counts only say that it does."""
    found = [
        issue
        for issue in issues
        if issue.author_is_member
        and issue.unreadable is None
        and issue.kind is body.ItemKind.CONTAINER
        and issue.children_total is not None
    ]
    return tuple(sorted(found, key=lambda issue: issue.number))


def _container(
    issue: workboard.Issue,
    children: workboard.ChildList,
    *,
    marks: Marks,
    storage: body.Storage,
) -> Container:
    """`issue` counted from its sub-issue list alone, the way the board counts it."""
    local = workboard.local_children(children)
    closed = [child for child in children if child.state is workboard.ChildState.CLOSED]
    open_local = [child for child in local if child.state is workboard.ChildState.OPEN]
    return Container(
        issue.number,
        issue.title,
        len(closed),
        sum(
            1
            for child in local
            if child.state is workboard.ChildState.CLOSED and child.number in marks.landed
        ),
        len(children) - len(closed),
        sum(1 for child in open_local if child.number in marks.operator_steps),
        len(body.parse_body(issue.body, storage=storage).slices),
    )


def of(
    issues: Iterable[workboard.Issue],
    *,
    storage: body.Storage,
    marks: Marks,
    parent_of: Callable[[int], workboard.ParentIssue | None],
    children_of: Callable[[int], workboard.ChildList],
) -> Progress | ProgressUnavailable:
    """The progress of `issues`, which are listed once: the containers none of
    whose `parent_of` is a parent, in whichever repository it sits, counted
    from their `children_of` lists, with the `marks` of its items. A failed read of a parent or of
    children leaves the repository unknown rather than counted wrong."""
    counted = _counted_containers(issues)

    def read(issue: workboard.Issue) -> workboard.ChildList | None:
        if parent_of(issue.number) is not None:
            return None
        return children_of(issue.number)

    try:
        with ThreadPoolExecutor(
            max_workers=max(1, min(len(counted), _CONTAINER_READ_CONCURRENCY))
        ) as pool:
            lists = tuple(pool.map(read, counted))
    except protocol.ClaimError as error:
        return ProgressUnavailable(str(error))
    top_level = tuple(
        _container(issue, children, marks=marks, storage=storage)
        for issue, children in zip(counted, lists, strict=True)
        if children is not None
    )
    return Progress(top_level, len(marks.operator_steps))
