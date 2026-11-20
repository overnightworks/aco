"""The wait on a board and the recurring audits (`specs/wait.spec.md`, WAIT-23, WAIT-24): the end a
due audit brings, and the key (newest trunk landing, today) under which the anchor is listed
again, with the time, the trunk and the forge as the existing wait tests control them."""

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pytest
from audit_world import LABEL, NAME, World, build_world, entry_toml
from board_fixtures import FakeBoardProbe, board_issue, complete_contract, serve_board_probe
from cli_fixtures import FROZEN_CLI_NOW, run_cli
from wait_fixtures import Ticks, install

from aco import board_wait, cmd_wait, forge, protocol, session, workboard

POLLS_PER_HOUR = int(board_wait.FULL_READ_SECONDS / cmd_wait.SIGNAL_POLL_SECONDS)
FIRST_PAUSE_AFTER_THE_READ = 5


def reading(
    *, audits_due: tuple[str, ...] = (), actionable_item: int | None = None
) -> board_wait.BoardReading:
    return board_wait.BoardReading(actionable_item, (), (), None, audits_due)


@pytest.mark.parametrize(
    ("found", "expected"),
    [
        pytest.param(reading(), None, id="nothing-to-do"),
        pytest.param(
            reading(audits_due=(NAME, "second")),
            board_wait.BoardEnd(None, (), (NAME, "second")),
            id="a-due-audit-alone-in-entry-order",
        ),
        pytest.param(
            reading(audits_due=(NAME,), actionable_item=5),
            board_wait.BoardEnd(5, (), (NAME,)),
            id="a-due-audit-beside-an-action",
        ),
    ],
)
def test_a_due_audit_ends_the_wait_beside_the_action_aco_next_names(
    found: board_wait.BoardReading, expected: board_wait.BoardEnd | None
) -> None:
    """Spec: WAIT-23."""
    assert board_wait.ending(frozenset(), found) == expected


@pytest.fixture(autouse=True)
def _probe(monkeypatch: pytest.MonkeyPatch) -> None:
    serve_board_probe(monkeypatch, FakeBoardProbe())


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, github_clone: Path, github_world: Path) -> World:
    built = build_world(monkeypatch, github_clone)
    built.own.board_issues = ()
    return built


def free_item() -> workboard.Issue:
    return board_issue(11, "Top work", complete_contract("Claim #11."))


def move_today(monkeypatch: pytest.MonkeyPatch) -> Callable[[date], None]:
    """Makes the command's `today` the one the returned function last set."""
    today = [FROZEN_CLI_NOW.date()]
    frozen_run_context = session.run_context

    def with_a_moving_today(repo: forge.RepositoryId | None) -> session.RunContext:
        context = frozen_run_context(repo)
        context.today = lambda: today[0]
        return context

    monkeypatch.setattr(session, "run_context", with_a_moving_today)
    return lambda day: today.__setitem__(0, day)


def end_at_the_hourly_read(world: World, ticks: Ticks, change: Callable[[], None]) -> None:
    """Applies `change` after the fifth pause, then lets the board gain its action so the
    wait is sure to end at the next full read, the hour's."""

    def change_then_offer_an_action() -> None:
        change()
        world.own.board_issues = (free_item(),)

    ticks.afterwards[FIRST_PAUSE_AFTER_THE_READ] = change_then_offer_an_action


def test_the_anchor_is_not_listed_again_while_the_trunk_tip_and_the_day_stand(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-24."""
    world.configure(entry_toml())
    world.label_issue(f"audited through {world.anchor_at(days_ago=0, commits_after=0)}")
    ticks = install(monkeypatch, lambda: 0)
    end_at_the_hourly_read(world, ticks, lambda: None)

    result = run_cli(["wait"], capsys)

    assert (result.stdout, len(ticks.pauses), world.own.labelled_listings) == (
        "ACTIONABLE #11\n",
        POLLS_PER_HOUR,
        [LABEL],
    )


def test_the_anchor_is_listed_again_after_a_landing(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-24."""
    world.configure(entry_toml())
    world.label_issue(f"audited through {world.anchor_at(days_ago=0, commits_after=0)}")
    ticks = install(monkeypatch, lambda: 0)
    ticks.afterwards[FIRST_PAUSE_AFTER_THE_READ] = lambda: world.land(days_ago=0, count=3)

    result = run_cli(["wait"], capsys)

    assert (result.stdout, len(ticks.pauses), world.own.labelled_listings) == (
        f"AUDIT {NAME}\n",
        POLLS_PER_HOUR,
        [LABEL, LABEL],
    )


def test_the_anchor_is_listed_again_on_a_new_day(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-24."""
    world.configure(entry_toml())
    world.label_issue(f"audited through {world.anchor_at(days_ago=6, commits_after=1)}")
    set_today = move_today(monkeypatch)
    ticks = install(monkeypatch, lambda: 0)
    ticks.afterwards[FIRST_PAUSE_AFTER_THE_READ] = lambda: set_today(
        FROZEN_CLI_NOW.date() + timedelta(days=1)
    )

    result = run_cli(["wait"], capsys)

    assert (result.stdout, len(ticks.pauses), world.own.labelled_listings) == (
        f"AUDIT {NAME}\n",
        POLLS_PER_HOUR,
        [LABEL, LABEL],
    )


def test_a_failed_listing_is_not_kept_and_is_read_again_at_the_next_read(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-24."""
    world.configure(entry_toml())
    world.label_issue("nothing audited yet")
    world.own.labelled_listing_error = protocol.ClaimError("GitHub is down")
    ticks = install(monkeypatch, lambda: 0)
    ticks.afterwards[FIRST_PAUSE_AFTER_THE_READ] = lambda: setattr(
        world.own, "labelled_listing_error", None
    )

    result = run_cli(["wait"], capsys)

    assert (result.stdout, len(ticks.pauses), world.own.labelled_listings) == (
        f"AUDIT {NAME}\n",
        POLLS_PER_HOUR,
        [LABEL, LABEL],
    )
