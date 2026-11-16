"""The progress view's numbers (specs/serve.spec.md, ABRD-131 to ABRD-137)."""

from collections.abc import Callable
from dataclasses import replace

import pytest
from board_fixtures import board_issue, complete_contract, container_with_children, slice_entries

from aco import body, forge, progress, workboard
from aco.body import ItemKind

type ParentOf = Callable[[int], workboard.ParentIssue | None]
type Arranged = tuple[workboard.Issue, workboard.ChildList]

CLOSED_CHILD = 1000
"""The number `container_with_children` gives a container's first closed child."""


def _container(
    number: int,
    *,
    closed: int,
    open_count: int = 0,
    uncut: int = 0,
    member: bool = True,
    foreign_open: tuple[workboard.IssueReference, ...] = (),
) -> Arranged:
    container, children = container_with_children(
        number,
        closed=closed,
        open_children=tuple(range(1, open_count + 1)),
        title=f"Container {number}",
        body=complete_contract("Build.", slice=slice_entries(*(f"S{n}" for n in range(uncut)))),
        foreign_open=foreign_open,
    )
    return replace(container, author_is_member=member), children


def _no_parent(_number: int) -> workboard.ParentIssue | None:
    return None


def _parent_in(repository: str) -> ParentOf:
    parent = workboard.ParentIssue(workboard.IssueReference(repository, 1), "")
    return lambda _number: parent


def _failing_read(number: int) -> workboard.ParentIssue | None:
    raise forge.ForgeTransientError(f"no parent of #{number}")


def _read(
    arranged: list[Arranged],
    parent_of: ParentOf = _no_parent,
    *,
    operator_steps: frozenset[int] = frozenset(),
    landed: frozenset[int] = frozenset(),
    children_of: Callable[[int], workboard.ChildList] | None = None,
) -> progress.Progress | progress.ProgressUnavailable:
    listed = {issue.number: children for issue, children in arranged}
    return progress.of(
        [issue for issue, _children in arranged],
        storage=body.Storage.GITHUB,
        marks=progress.Marks(operator_steps, landed),
        parent_of=parent_of,
        children_of=children_of or listed.__getitem__,
    )


def _shown(read: progress.Progress | progress.ProgressUnavailable) -> progress.Progress:
    assert isinstance(read, progress.Progress)
    return read


@pytest.mark.parametrize(
    ("closed", "open_count", "uncut", "planned", "percent"),
    [
        pytest.param(7, 31, 10, 48, 14, id="closed-over-children-and-uncut-rows"),
        pytest.param(199, 1, 0, 200, 99, id="rounds-down-never-up-to-one-hundred"),
        pytest.param(5, 0, 0, 5, 100, id="one-hundred-when-nothing-is-open-or-uncut"),
        pytest.param(3, 0, 1, 4, 75, id="an-uncut-row-keeps-it-below-one-hundred"),
        pytest.param(0, 0, 0, 0, None, id="nothing-planned-has-no-percent"),
    ],
)
def test_a_container_shows_closed_over_planned_children_and_uncut_rows(
    closed: int, open_count: int, uncut: int, planned: int, percent: int | None
) -> None:
    arranged = [_container(10, closed=closed, open_count=open_count, uncut=uncut)]

    shown = _shown(_read(arranged))

    assert [(c.closed, c.planned, c.percent) for c in shown.containers] == [
        (closed, planned, percent)
    ]
    assert (shown.closed, shown.planned, shown.percent) == (closed, planned, percent)
    assert (shown.open, shown.uncut) == (open_count, uncut)


def test_the_repository_line_sums_its_top_level_containers() -> None:
    arranged = [
        _container(10, closed=1, open_count=2, uncut=1),
        _container(20, closed=4, open_count=0, uncut=3),
    ]

    shown = _shown(_read(arranged))

    assert (shown.closed, shown.planned, shown.open, shown.uncut, shown.percent) == (
        5,
        11,
        2,
        4,
        45,
    )


@pytest.mark.parametrize(
    "parent_of",
    [
        pytest.param(_parent_in("owner/repo"), id="parent-in-this-repository"),
        pytest.param(_parent_in("owner/other"), id="parent-in-another-repository"),
    ],
)
def test_a_container_with_a_parent_is_nested_and_not_on_the_top_level(parent_of: ParentOf) -> None:
    arranged = [_container(10, closed=1, open_count=1)]

    shown = _shown(_read(arranged, parent_of))

    assert (shown.containers, shown.planned) == ((), 0)


def test_only_a_parentless_container_stays_top_level_beside_a_nested_one() -> None:
    parent = workboard.ParentIssue(workboard.IssueReference("owner/repo", 1), "")

    def parent_of(number: int) -> workboard.ParentIssue | None:
        return parent if number == 20 else None

    arranged = [_container(10, closed=1, open_count=1), _container(20, closed=9)]

    shown = _shown(_read(arranged, parent_of))

    assert [container.number for container in shown.containers] == [10]


@pytest.mark.parametrize(
    "arranged",
    [
        pytest.param(_container(10, closed=1, member=False), id="not-a-member's"),
        pytest.param(
            (board_issue(10, "Plain", complete_contract("Build."), kind=ItemKind.TASK), ()),
            id="not-a-container",
        ),
        pytest.param(
            (
                replace(_container(10, closed=1)[0], children_total=None, children_closed=None),
                (),
            ),
            id="a-container-the-forge-gave-no-counts",
        ),
    ],
)
def test_only_a_members_counted_container_is_shown(arranged: Arranged) -> None:
    shown = _shown(_read([arranged]))

    assert shown.containers == ()


def test_the_operator_waiting_count_is_carried_per_repository() -> None:
    shown = _shown(_read([], operator_steps=frozenset({4, 5, 6})))

    assert shown.waiting == 3


def test_a_container_counts_from_its_sub_issue_list_not_from_its_summary() -> None:
    issue, children = _container(10, closed=2, open_count=1)

    shown = _shown(_read([(replace(issue, children_closed=0, children_total=9), children)]))

    assert [(c.closed, c.open) for c in shown.containers] == [(2, 1)]


def test_a_closed_child_a_trunk_commit_names_is_landed_apart_from_other_closes() -> None:
    arranged = [_container(10, closed=3)]

    shown = _shown(_read(arranged, landed=frozenset({CLOSED_CHILD, CLOSED_CHILD + 2})))

    assert [(c.closed, c.landed) for c in shown.containers] == [(3, 2)]
    assert (shown.closed, shown.landed) == (3, 2)


def test_an_open_child_a_trunk_commit_names_is_not_landed() -> None:
    arranged = [_container(10, closed=0, open_count=1)]

    shown = _shown(_read(arranged, landed=frozenset({1})))

    assert shown.landed == 0


def test_a_closed_child_in_another_repository_is_never_landed() -> None:
    issue, _children = _container(10, closed=0)
    foreign = workboard.ForeignChild(
        workboard.IssueReference("owner/other", CLOSED_CHILD), workboard.ChildState.CLOSED
    )

    shown = _shown(_read([(issue, (foreign,))], landed=frozenset({CLOSED_CHILD})))

    assert [(c.closed, c.landed) for c in shown.containers] == [(1, 0)]


def test_a_container_waits_with_its_open_children_that_wait_on_the_operator() -> None:
    arranged = [
        _container(10, closed=1, open_count=3),
        _container(20, closed=0, open_count=1),
    ]

    shown = _shown(_read(arranged, operator_steps=frozenset({1, 3, 9})))

    assert [(c.number, c.waiting) for c in shown.containers] == [(10, 2), (20, 1)]
    assert shown.waiting == 3


def test_a_closed_child_that_waits_is_not_counted_as_waiting() -> None:
    arranged = [_container(10, closed=1)]

    shown = _shown(_read(arranged, operator_steps=frozenset({CLOSED_CHILD})))

    assert [c.waiting for c in shown.containers] == [0]


def test_a_foreign_open_child_is_open_but_never_waiting() -> None:
    foreign = workboard.IssueReference("owner/other", 1)
    arranged = [_container(10, closed=0, foreign_open=(foreign,))]

    shown = _shown(_read(arranged, operator_steps=frozenset({1})))

    assert [(c.open, c.waiting) for c in shown.containers] == [(1, 0)]


def test_a_nested_container_reads_no_children() -> None:
    reads: list[int] = []

    def children_of(number: int) -> workboard.ChildList:
        reads.append(number)
        return ()

    _read([_container(10, closed=1)], _parent_in("owner/repo"), children_of=children_of)

    assert reads == []


def test_a_failed_parent_read_is_a_visible_state_not_a_number() -> None:
    arranged = [_container(10, closed=1, open_count=1)]

    read = _read(arranged, _failing_read)

    assert read == progress.ProgressUnavailable("no parent of #10")


def test_a_failed_child_read_is_a_visible_state_not_a_number() -> None:
    def failing_children(number: int) -> workboard.ChildList:
        raise forge.ForgeTransientError(f"no children of #{number}")

    read = _read([_container(10, closed=1)], children_of=failing_children)

    assert read == progress.ProgressUnavailable("no children of #10")
