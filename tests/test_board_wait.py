"""The decisions of the wait on a board (`specs/wait.spec.md`, WAIT-14, WAIT-15, WAIT-18,
WAIT-19): when it ends and when it looks, with the times and the date as plain values."""

from datetime import date

import pytest

from aco import board_wait, forge, item_wait

TODAY = date(2026, 11, 15)
TOMORROW = date(2026, 11, 16)
HOUR = board_wait.FULL_READ_SECONDS
MINUTE = board_wait.PROBE_SECONDS


def line(item: int, index: int, state: str, *, waiting: bool) -> board_wait.LineStatus:
    return board_wait.LineStatus(item, index, state, waiting)


def reading(
    *lines: board_wait.LineStatus, actionable_item: int | None = None
) -> board_wait.BoardReading:
    return board_wait.BoardReading(actionable_item, lines, (), None)


def until_on(day: date) -> item_wait.UntilWait:
    return item_wait.UntilWait(day, TODAY)


def ended(end: board_wait.BoardEnd | None) -> tuple[int | None, list[tuple[int, int, str]]] | None:
    """The action and the changed lines' item, index and state of an end, `None` for none."""
    if end is None:
        return None
    return end.actionable_item, [(held.item, held.index, held.state) for held in end.changed]


@pytest.mark.parametrize(
    ("waiting_before", "found", "expected"),
    [
        pytest.param(frozenset(), reading(), None, id="nothing-waits-and-nothing-to-do"),
        pytest.param(
            frozenset({(7, 2)}),
            reading(line(7, 2, "open", waiting=True)),
            None,
            id="a-line-still-waiting",
        ),
        pytest.param(frozenset(), reading(actionable_item=5), (5, []), id="an-action-at-the-start"),
        pytest.param(
            frozenset({(7, 2), (8, 1)}),
            reading(
                line(7, 1, "ruled no 2026-10-01", waiting=False),
                line(7, 2, "ruled A 2026-11-15", waiting=False),
                line(8, 1, "with head 2026-11-15", waiting=False),
            ),
            (None, [(7, 2, "ruled A 2026-11-15"), (8, 1, "with head 2026-11-15")]),
            id="changed-lines-in-board-order-and-never-one-that-was-not-waiting",
        ),
        pytest.param(
            frozenset({(7, 2)}),
            reading(line(7, 2, "withdrawn 2026-11-15", waiting=False), actionable_item=9),
            (9, [(7, 2, "withdrawn 2026-11-15")]),
            id="an-action-and-a-changed-line-together",
        ),
        pytest.param(
            frozenset({(7, 2)}), reading(), None, id="an-item-no-longer-open-is-no-change"
        ),
    ],
)
def test_the_wait_ends_on_an_action_or_a_line_that_stopped_waiting(
    waiting_before: frozenset[tuple[int, int]],
    found: board_wait.BoardReading,
    expected: tuple[int | None, list[tuple[int, int, str]]] | None,
) -> None:
    """Spec: WAIT-14, WAIT-15 -- `aco next`'s action, or a line open at the previous read."""
    assert ended(board_wait.ending(waiting_before, found)) == expected


def test_the_lines_that_wait_are_the_ones_the_reading_marks() -> None:
    """Spec: WAIT-14 -- the lines compared at the next read."""
    found = reading(
        line(7, 1, "ruled no 2026-10-01", waiting=False), line(7, 2, "open", waiting=True)
    )
    assert board_wait.waiting_lines(found) == frozenset({(7, 2)})


@pytest.mark.parametrize(
    ("untils", "expected"),
    [
        pytest.param([], None, id="no-wait"),
        pytest.param([until_on(TODAY)], None, id="reached-today"),
        pytest.param(
            [until_on(date(2026, 12, 1)), until_on(TOMORROW), until_on(TODAY)],
            until_on(TOMORROW),
            id="the-earliest-still-ahead",
        ),
        pytest.param(
            [item_wait.OperatorWait("Ask", TODAY), item_wait.TriggerWait("a fact", TODAY), None],
            None,
            id="other-waits-have-no-date",
        ),
    ],
)
def test_the_earliest_until_is_one_that_lies_after_today(
    untils: list[item_wait.ItemWait | None], expected: item_wait.UntilWait | None
) -> None:
    """Spec: WAIT-19 -- the date a read is due on, recomputed after each read."""
    assert board_wait.earliest_pending_until(untils, TODAY) == expected


@pytest.mark.parametrize(
    ("now", "last_probe", "due"),
    [
        pytest.param(MINUTE - 1, 0.0, False, id="before-the-minute"),
        pytest.param(MINUTE, 0.0, True, id="at-the-minute"),
        pytest.param(MINUTE + 5, 5.0, True, id="a-minute-after-the-last-probe"),
    ],
)
def test_the_forge_is_probed_every_minute(now: float, last_probe: float, due: bool) -> None:
    """Spec: WAIT-18 -- one round of conditional questions per 60 s."""
    assert board_wait.probe_due(now, board_wait.Schedule(last_probe, 0.0)) is due


@pytest.mark.parametrize(
    ("now", "schedule", "pending", "today", "until", "due"),
    [
        pytest.param(MINUTE, board_wait.Schedule(0.0, 0.0), False, TODAY, None, False, id="quiet"),
        pytest.param(5.0, board_wait.Schedule(0.0, 0.0), True, TODAY, None, True, id="asked-for"),
        pytest.param(HOUR - 1, board_wait.Schedule(0.0, 0.0), False, TODAY, None, False, id="59"),
        pytest.param(HOUR, board_wait.Schedule(0.0, 0.0), False, TODAY, None, True, id="hourly"),
        pytest.param(
            2 * HOUR - 1, board_wait.Schedule(0.0, HOUR), False, TODAY, None, False, id="last-read"
        ),
        pytest.param(
            5.0,
            board_wait.Schedule(0.0, 0.0),
            False,
            TOMORROW,
            until_on(TOMORROW),
            True,
            id="until-reached",
        ),
        pytest.param(
            5.0,
            board_wait.Schedule(0.0, 0.0),
            False,
            TODAY,
            until_on(TOMORROW),
            False,
            id="until-ahead",
        ),
        pytest.param(
            5.0,
            board_wait.Schedule(0.0, 0.0, retry_after=65.0),
            True,
            TODAY,
            None,
            False,
            id="not-again-before-the-retry",
        ),
    ],
)
def test_the_board_is_read_when_asked_hourly_or_on_the_until_date(
    now: float,
    schedule: board_wait.Schedule,
    pending: bool,
    today: date,
    until: item_wait.UntilWait | None,
    due: bool,
) -> None:
    """Spec: WAIT-19 -- hourly, on the first tick on or after the date, never in a retry pause."""
    assert (
        board_wait.read_due(now, schedule, pending=pending, today=today, earliest_until=until)
        is due
    )


def test_the_forge_is_asked_about_the_repository_then_each_foreign_blocker() -> None:
    """Spec: WAIT-18 -- the newest updated issue, then one question per open foreign blocker."""
    blockers = (forge.ProbeTarget("other/repo", 3),)
    assert board_wait.probe_targets("owner/repo", blockers) == (
        forge.ProbeTarget("owner/repo"),
        forge.ProbeTarget("other/repo", 3),
    )
