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

from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import body, lane_measure, protocol, workboard

_PERCENT = 100
_CONTAINER_READ_CONCURRENCY = 8


def percent(closed: int, planned: int) -> int | None:
    """The whole percent of `planned` that is `closed`, rounded down, so that
    100 shows only when nothing is open or uncut; `None` when nothing is planned."""
    return None if planned == 0 else _PERCENT * closed // planned


@dataclass(frozen=True)
class ClosedChild:
    """A closed child of this repository; `actuals` is `None` when no lane record names it."""

    number: int
    title: str
    actuals: lane_measure.ItemActuals | None


@dataclass(frozen=True)
class Container:
    number: int
    title: str
    closed: int
    landed: int
    open: int
    waiting: int
    uncut: int
    estimate: lane_measure.RemainingWork | lane_measure.NoRange | None
    """The agent work left; `None` when no lane is left."""
    closed_children: tuple[ClosedChild, ...]

    @property
    def lanes_left(self) -> int:
        """The open children that do not wait on the operator, and the uncut rows."""
        return self.open - self.waiting + self.uncut

    @property
    def planned(self) -> int:
        return self.closed + self.open + self.uncut

    @property
    def percent(self) -> int | None:
        return percent(self.closed, self.planned)


@dataclass(frozen=True)
class Marks:
    """What other sources of the repository say: the items waiting on the operator,
    those a trunk commit's trailer names as landed, and what a lane costs by the lane
    records on the state ref, and what each item's lanes took (both `None` when the records
    could not be read)."""

    operator_steps: frozenset[int]
    landed: frozenset[int]
    prices: lane_measure.LanePrices | None
    actuals: Mapping[int, lane_measure.ItemActuals] | None


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


def _declared_size(issue: workboard.Issue | None, storage: body.Storage) -> body.Size | None:
    """The size class a readable open item declares; a nested container is one lane of no
    class, as is an item the listing does not hold."""
    if issue is None or issue.unreadable is not None or issue.kind is body.ItemKind.CONTAINER:
        return None
    return body.parse_body(issue.body, storage=storage).size


def _container(
    issue: workboard.Issue,
    children: workboard.ChildList,
    *,
    marks: Marks,
    storage: body.Storage,
    open_items: Mapping[int, workboard.Issue],
) -> Container:
    """`issue` counted from its sub-issue list alone, the way the board counts it."""
    local = workboard.local_children(children)
    closed = [child for child in children if child.state is workboard.ChildState.CLOSED]
    open_local = [child for child in local if child.state is workboard.ChildState.OPEN]
    waiting = [child for child in open_local if child.number in marks.operator_steps]
    uncut = len(body.parse_body(issue.body, storage=storage).slices)
    open_total = len(children) - len(closed)
    sizes = [
        _declared_size(open_items.get(child.number), storage)
        for child in open_local
        if child not in waiting
    ]
    lanes_left = open_total - len(waiting) + uncut
    sizes += [None] * (lanes_left - len(sizes))
    return Container(
        issue.number,
        issue.title,
        len(closed),
        sum(
            1
            for child in local
            if child.state is workboard.ChildState.CLOSED and child.number in marks.landed
        ),
        open_total,
        len(waiting),
        uncut,
        lane_measure.remaining_work(marks.prices, sizes) if lanes_left else None,
        _closed_children(local, marks.actuals),
    )


def _closed_children(
    local: tuple[workboard.ChildItem, ...],
    actuals: Mapping[int, lane_measure.ItemActuals] | None,
) -> tuple[ClosedChild, ...]:
    """The closed `local` children by number; with unreadable lane records every figure is
    unknown, with none naming a child it has no actuals."""
    return tuple(
        ClosedChild(
            child.number,
            child.title,
            lane_measure.ItemActuals(None, None) if actuals is None else actuals.get(child.number),
        )
        for child in sorted(local, key=lambda child: child.number)
        if child.state is workboard.ChildState.CLOSED
    )


def of(
    issues: Iterable[workboard.Issue],
    *,
    storage: body.Storage,
    marks: Marks,
    children_of: Callable[[int], workboard.ChildList],
) -> Progress | ProgressUnavailable:
    """The progress of `issues`, which are listed once: the containers whose listed row names
    no parent, in whichever repository it sits, counted
    from their `children_of` lists, with the `marks` of its items, from which each gets the
    work left. A failed read of children leaves the repository unknown rather
    than counted wrong."""
    listed = tuple(issues)
    open_items = {issue.number: issue for issue in listed}
    counted = _counted_containers(listed)

    def read(issue: workboard.Issue) -> workboard.ChildList | None:
        if issue.parent is not None:
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
        _container(issue, children, marks=marks, storage=storage, open_items=open_items)
        for issue, children in zip(counted, lists, strict=True)
        if children is not None
    )
    return Progress(top_level, len(marks.operator_steps))
