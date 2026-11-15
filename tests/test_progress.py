"""The progress view's numbers (specs/serve.spec.md, ABRD-131 to ABRD-134)."""

from collections.abc import Callable
from dataclasses import replace

import pytest
from board_fixtures import board_issue, complete_contract, container_with_children, slice_entries

from aco import body, forge, progress, workboard
from aco.body import ItemKind

type ParentOf = Callable[[int], workboard.ParentIssue | None]


def _container(
    number: int, *, closed: int, open_count: int = 0, uncut: int = 0, member: bool = True
) -> workboard.Issue:
    container, _children = container_with_children(
        number,
        closed=closed,
        open_children=tuple(range(1, open_count + 1)),
        title=f"Container {number}",
        body=complete_contract("Build.", slice=slice_entries(*(f"S{n}" for n in range(uncut)))),
    )
    return replace(container, author_is_member=member)


def _no_parent(_number: int) -> workboard.ParentIssue | None:
    return None


def _parent_in(repository: str) -> ParentOf:
    parent = workboard.ParentIssue(workboard.IssueReference(repository, 1), "")
    return lambda _number: parent


def _failing_read(number: int) -> workboard.ParentIssue | None:
    raise forge.ForgeTransientError(f"no parent of #{number}")


def _read(
    issues: list[workboard.Issue], parent_of: ParentOf = _no_parent, waiting: int = 0
) -> progress.Progress | progress.ProgressUnavailable:
    return progress.of(issues, storage=body.Storage.GITHUB, waiting=waiting, parent_of=parent_of)


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
    issues = [_container(10, closed=closed, open_count=open_count, uncut=uncut)]

    shown = _shown(_read(issues))

    assert [(c.closed, c.planned, c.percent) for c in shown.containers] == [
        (closed, planned, percent)
    ]
    assert (shown.closed, shown.planned, shown.percent) == (closed, planned, percent)
    assert (shown.open, shown.uncut) == (open_count, uncut)


def test_the_repository_line_sums_its_top_level_containers() -> None:
    issues = [
        _container(10, closed=1, open_count=2, uncut=1),
        _container(20, closed=4, open_count=0, uncut=3),
    ]

    shown = _shown(_read(issues))

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
    issues = [_container(10, closed=1, open_count=1)]

    shown = _shown(_read(issues, parent_of))

    assert (shown.containers, shown.planned) == ((), 0)


def test_only_a_parentless_container_stays_top_level_beside_a_nested_one() -> None:
    parent = workboard.ParentIssue(workboard.IssueReference("owner/repo", 1), "")

    def parent_of(number: int) -> workboard.ParentIssue | None:
        return parent if number == 20 else None

    issues = [_container(10, closed=1, open_count=1), _container(20, closed=9)]

    shown = _shown(_read(issues, parent_of))

    assert [container.number for container in shown.containers] == [10]


@pytest.mark.parametrize(
    "issue",
    [
        pytest.param(_container(10, closed=1, member=False), id="not-a-member's"),
        pytest.param(
            board_issue(10, "Plain", complete_contract("Build."), kind=ItemKind.TASK),
            id="not-a-container",
        ),
        pytest.param(
            replace(_container(10, closed=1), children_total=None, children_closed=None),
            id="a-container-the-forge-gave-no-counts",
        ),
    ],
)
def test_only_a_members_counted_container_is_shown(issue: workboard.Issue) -> None:
    shown = _shown(_read([issue]))

    assert shown.containers == ()


def test_the_operator_waiting_count_is_carried_per_repository() -> None:
    shown = _shown(_read([], waiting=3))

    assert shown.waiting == 3


def test_a_failed_parent_read_is_a_visible_state_not_a_number() -> None:
    issues = [_container(10, closed=1, open_count=1)]

    read = _read(issues, _failing_read)

    assert read == progress.ProgressUnavailable("no parent of #10")
