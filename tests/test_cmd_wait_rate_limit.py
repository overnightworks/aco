"""`aco wait` under a GitHub rate limit (`specs/wait.spec.md`, WAIT-22): both waits warn once and
read again only at the reset, at their start and while they wait. The wall clock is frozen and
the wait's own clock starts far from its epoch seconds; only the forge and its probe are fakes."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pytest
from board_fixtures import (
    REPOSITORY,
    FakeBoardProbe,
    board_issue,
    complete_contract,
    holding_for_the_operator,
    serve_board_probe,
)
from cli_fixtures import FROZEN_CLI_NOW, CliRun, freeze_cli_now, run_cli
from github_fixtures import FakeForge, serve_forge
from option_cards import decide, group_body, ruled_card
from wait_fixtures import ITEM, Ticks, install, open_reference, reads_of, serve_item

from aco import board_wait, cmd_wait, forge, protocol, session, store, workboard

OTHER = 50
RESET_IN = timedelta(minutes=30)
RETRY_AT_THE_RESET = RESET_IN.total_seconds()
RETRY_WITHOUT_A_RESET = board_wait.PROBE_SECONDS
SENTENCE = "GitHub's REST rate limit is reached; it resets at 2026-08-21T00:30:00Z"
UNREAD_SENTENCE = "GitHub's REST rate limit is reached; its reset time could not be read"
DOWN = "the forge is down"
BOARD_WARNING = "WARNING: the board could not be read, still waiting: "
ITEM_WARNING = "WARNING: the item could not be read, still waiting: "
SLOW_READ_PAUSES = int(cmd_wait.ITEM_READ_SECONDS / cmd_wait.SIGNAL_POLL_SECONDS)
LIMIT = forge.ForgeRateLimitedError(SENTENCE, FROZEN_CLI_NOW + RESET_IN)
LIMIT_WITHOUT_A_RESET = forge.ForgeRateLimitedError(UNREAD_SENTENCE)
ACTIONABLE = f"ACTIONABLE #{OTHER}\n"
Failing = Callable[[float], forge.ForgeError | None]


def never_failing(_now: float) -> forge.ForgeError | None:
    return None


def failing_in(*windows: tuple[float, float, forge.ForgeError]) -> Failing:
    """The failure of the window that holds the wait-clock time: from its start up to, not
    including, its end."""

    def failure_at(now: float) -> forge.ForgeError | None:
        return next((failure for start, end, failure in windows if start <= now < end), None)

    return failure_at


@dataclass
class TimedProbe(FakeBoardProbe):
    """A probe that notes the wait-clock time of each question and fails as `failing` says."""

    clock: Callable[[], float] = lambda: 0.0
    failing: Failing = never_failing
    asked_at: list[float] = field(default_factory=list)

    def changed_since(self, target: forge.ProbeTarget, token: str | None) -> forge.ProbeAnswer:
        now = self.clock()
        self.asked_at.append(now)
        failure = self.failing(now)
        if failure is not None:
            raise failure
        return super().changed_since(target, token)


@dataclass
class TimedBoardForge(FakeForge):
    """A forge that notes the wait-clock time of each board read and fails as `failing` says."""

    clock: Callable[[], float] = lambda: 0.0
    failing: Failing = never_failing
    read_at: list[float] = field(default_factory=list)

    def list_open_board_issues(self) -> tuple[workboard.Issue, ...]:
        now = self.clock()
        self.read_at.append(now)
        failure = self.failing(now)
        if failure is not None:
            raise failure
        return super().list_open_board_issues()


@dataclass
class BoardWorld:
    """What a bare wait is run against: its forge, its probe and the wait's clock."""

    client: TimedBoardForge
    probe: TimedProbe
    ticks: Ticks


def waiting_card() -> workboard.Issue:
    return board_issue(ITEM, "Karte", holding_for_the_operator(group_body()))


def free_item() -> workboard.Issue:
    return board_issue(OTHER, "Alpha", complete_contract(f"Claim #{OTHER}."))


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch, github_world: Path) -> None:
    freeze_cli_now(monkeypatch)


def serve_board(
    monkeypatch: pytest.MonkeyPatch,
    *,
    issues: tuple[workboard.Issue, ...],
    probe_failing: Failing = never_failing,
    read_failing: Failing = never_failing,
) -> BoardWorld:
    ticks = install(monkeypatch, lambda: 0)
    client = serve_forge(
        monkeypatch,
        TimedBoardForge(
            board_issues=issues,
            issue_references={ITEM: open_reference(group_body())},
            clock=ticks.clock,
            failing=read_failing,
        ),
    )
    probe = TimedProbe(clock=ticks.clock, failing=probe_failing)
    serve_board_probe(monkeypatch, probe)
    return BoardWorld(client, probe, ticks)


def a_board_that_gains_an_action(world: BoardWorld) -> Callable[[], None]:
    """What happens when the board changes: the probe answers `changed` from then on."""

    def change() -> None:
        world.client.board_issues = (free_item(),)
        world.probe.change(forge.ProbeTarget(REPOSITORY))

    return change


class TestTheBareWait:
    @pytest.mark.parametrize(
        ("probe_failing", "read_failing", "warning", "asked_at", "read_at"),
        [
            pytest.param(
                failing_in((0.0, RETRY_AT_THE_RESET, LIMIT)),
                never_failing,
                SENTENCE,
                [0.0, RETRY_AT_THE_RESET],
                [RETRY_AT_THE_RESET],
                id="probe-at-the-start",
            ),
            pytest.param(
                never_failing,
                failing_in((0.0, RETRY_AT_THE_RESET, LIMIT)),
                SENTENCE,
                [0.0, RETRY_AT_THE_RESET],
                [0.0, RETRY_AT_THE_RESET],
                id="read-at-the-start",
            ),
            pytest.param(
                failing_in((0.0, RETRY_WITHOUT_A_RESET, LIMIT_WITHOUT_A_RESET)),
                never_failing,
                UNREAD_SENTENCE,
                [0.0, RETRY_WITHOUT_A_RESET],
                [RETRY_WITHOUT_A_RESET],
                id="no-reset-known",
            ),
        ],
    )
    def test_a_rate_limit_at_the_start_warns_once_and_reads_at_the_retry_time(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe_failing: Failing,
        read_failing: Failing,
        warning: str,
        asked_at: list[float],
        read_at: list[float],
    ) -> None:
        """Spec: WAIT-22, WAIT-10, WAIT-14 -- no question to GitHub before the reset (a minute
        when none was read), and the first board read is still owed then."""
        world = serve_board(
            monkeypatch,
            issues=(free_item(),),
            probe_failing=probe_failing,
            read_failing=read_failing,
        )
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stdout, result.stderr) == (
            0,
            ACTIONABLE,
            f"{BOARD_WARNING}{warning}\n",
        )
        assert (world.probe.asked_at, world.client.read_at) == (asked_at, read_at)

    def test_a_rate_limit_while_it_waits_holds_the_probe_and_the_read_until_the_reset(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: WAIT-22 -- the board changed during the limit; nothing is asked before the
        reset, and the read that follows names the action."""
        first_refused, lifted = 60.0, 60.0 + RETRY_AT_THE_RESET
        world = serve_board(
            monkeypatch,
            issues=(waiting_card(),),
            probe_failing=failing_in((first_refused, lifted, LIMIT)),
        )
        world.ticks.afterwards[int(first_refused / cmd_wait.SIGNAL_POLL_SECONDS)] = (
            a_board_that_gains_an_action(world)
        )
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stdout, result.stderr) == (
            0,
            ACTIONABLE,
            f"{BOARD_WARNING}{SENTENCE}\n",
        )
        assert (world.probe.asked_at, world.client.read_at) == (
            [0.0, 0.0, first_refused, lifted],
            [0.0, lifted],
        )

    def test_the_retry_time_counts_from_the_end_of_the_call_that_was_refused(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: WAIT-22 -- a refusal that took 90 seconds to come lifts no earlier than the
        reset, which is asked of the wall clock as it stood when the call ended."""
        first_refused, call_seconds = 60.0, 90.0
        world = serve_board(monkeypatch, issues=(waiting_card(),))
        frozen = session.run_context

        def run_context(repo: forge.RepositoryId | None) -> session.RunContext:
            context = frozen(repo)
            context.now = lambda: FROZEN_CLI_NOW + timedelta(seconds=world.ticks.now)
            return context

        def refusing_slowly(now: float) -> forge.ForgeError | None:
            if now == first_refused:
                world.ticks.now += call_seconds
            return LIMIT if first_refused <= now < RETRY_AT_THE_RESET else None

        monkeypatch.setattr(session, "run_context", run_context)
        world.probe.failing = refusing_slowly
        world.ticks.afterwards[1] = a_board_that_gains_an_action(world)
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stdout) == (0, ACTIONABLE)
        asked_after_the_refusal = world.probe.asked_at[3:]
        assert asked_after_the_refusal
        assert min(asked_after_the_refusal) >= RETRY_AT_THE_RESET

    def test_a_run_of_failures_that_met_another_failure_first_warns_again_for_a_rate_limit(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: WAIT-22, WAIT-10 -- one warning per run of failures, one more where the run
        began with another failure and then met a rate limit."""
        down = forge.ForgeTransientError(DOWN)
        lifted = 120.0 + RETRY_AT_THE_RESET
        world = serve_board(
            monkeypatch,
            issues=(waiting_card(),),
            probe_failing=failing_in((60.0, 120.0, down), (120.0, lifted, LIMIT)),
        )
        world.ticks.afterwards[1] = a_board_that_gains_an_action(world)
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stdout) == (0, ACTIONABLE)
        assert result.stderr == f"{BOARD_WARNING}{DOWN}\n{BOARD_WARNING}{SENTENCE}\n"
        assert world.probe.asked_at == [0.0, 0.0, 60.0, 120.0, lifted]

    def test_a_later_failure_without_a_reset_never_moves_the_known_retry_time_earlier(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Spec: WAIT-22 -- the state ref cannot be reached at the first probe, which fails
        without a reset: the owed read still waits for the reset, and nothing is said twice."""
        world = serve_board(
            monkeypatch,
            issues=(free_item(),),
            probe_failing=failing_in((0.0, RETRY_AT_THE_RESET, LIMIT)),
        )
        reachable = store.ls_remote_state
        unreachable = [False]

        def ls_remote(worktree: Path, remote: str) -> protocol.ObjectId | None:
            if unreachable[0]:
                raise protocol.ClaimError("cannot reach origin refs/aco/state")
            return reachable(worktree, remote)

        monkeypatch.setattr(store, "ls_remote_state", ls_remote)
        world.ticks.afterwards[29] = lambda: unreachable.__setitem__(0, True)
        world.ticks.afterwards[31] = lambda: unreachable.__setitem__(0, False)
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stdout, result.stderr) == (
            0,
            ACTIONABLE,
            f"{BOARD_WARNING}{SENTENCE}\n",
        )
        assert world.client.read_at == [RETRY_AT_THE_RESET]


class TestTheItemWait:
    @pytest.mark.parametrize(
        ("reads", "warnings", "pauses"),
        [
            pytest.param([LIMIT], [SENTENCE], [RETRY_AT_THE_RESET], id="reset-known"),
            pytest.param(
                [LIMIT_WITHOUT_A_RESET],
                [UNREAD_SENTENCE],
                [RETRY_WITHOUT_A_RESET],
                id="no-reset-known",
            ),
            pytest.param(
                [LIMIT, LIMIT],
                [SENTENCE],
                [RETRY_AT_THE_RESET, RETRY_AT_THE_RESET],
                id="the-limit-lasts",
            ),
        ],
    )
    def test_a_rate_limit_at_the_start_warns_once_and_reads_again_at_the_retry_time(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        reads: list[forge.ForgeError],
        warnings: list[str],
        pauses: list[float],
    ) -> None:
        """Spec: WAIT-22, WAIT-10 -- the first read is refused, so the wait pauses until the
        reset (a minute when none was read) instead of refusing, and reads again."""
        client = serve_item(monkeypatch, open_reference(group_body()))
        client.scripted_item_reads.extend([*reads, group_body(ruled_card())])
        ticks = install(monkeypatch, reads_of(client))
        result = run_cli(["wait", "7", "--line", "3"], capsys)
        assert (result.status, result.stderr, ticks.pauses) == (
            0,
            "".join(f"{ITEM_WARNING}{sentence}\n" for sentence in warnings),
            pauses,
        )
        assert re.fullmatch(r"CHANGED #7 line 3: ruled A \d{4}-\d{2}-\d{2}\n", result.stdout)

    @pytest.mark.parametrize(
        ("reference", "message"),
        [
            pytest.param(
                forge.ItemReference(forge.ItemState.MISSING), "#7 does not exist", id="missing"
            ),
            pytest.param(
                forge.ItemReference(forge.ItemState.CLOSED, "Karte", group_body()),
                "#7 is closed; there is nothing to wait for",
                id="closed",
            ),
        ],
    )
    def test_the_refusals_for_the_item_apply_once_its_first_read_answers(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        reference: forge.ItemReference,
        message: str,
    ) -> None:
        """Spec: WAIT-22, WAIT-04, WAIT-05 -- the item decides when it has been read."""
        client = serve_item(monkeypatch, reference)
        client.scripted_item_reads.append(LIMIT)
        ticks = install(monkeypatch, reads_of(client))
        result = run_cli(["wait", "7", "--line", "3", "--json"], capsys)
        assert (result.status, ticks.pauses) == (2, [RETRY_AT_THE_RESET])
        assert result.stderr.endswith(f"ERROR: {message}\n")
        assert json.loads(result.stdout)["reason"] == "invalid_item"

    @pytest.mark.parametrize(
        ("reads", "warnings", "paused_for"),
        [
            pytest.param(
                [None, LIMIT],
                [SENTENCE],
                cmd_wait.ITEM_READ_SECONDS + RETRY_AT_THE_RESET,
                id="reset-known",
            ),
            pytest.param(
                [None, LIMIT_WITHOUT_A_RESET],
                [UNREAD_SENTENCE],
                cmd_wait.ITEM_READ_SECONDS + RETRY_WITHOUT_A_RESET,
                id="no-reset-known",
            ),
            pytest.param(
                [None, LIMIT, LIMIT_WITHOUT_A_RESET],
                [SENTENCE],
                cmd_wait.ITEM_READ_SECONDS + RETRY_AT_THE_RESET + RETRY_WITHOUT_A_RESET,
                id="the-limit-lasts",
            ),
            pytest.param(
                [None, forge.ForgeTransientError(DOWN), LIMIT],
                [DOWN, SENTENCE],
                2 * cmd_wait.ITEM_READ_SECONDS + RETRY_AT_THE_RESET,
                id="after-another-failure",
            ),
        ],
    )
    def test_a_rate_limit_while_it_waits_is_said_once_and_the_next_read_waits_for_the_reset(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        reads: list[forge.ForgeError | None],
        warnings: list[str],
        paused_for: float,
    ) -> None:
        """Spec: WAIT-22, WAIT-10 -- the retry time replaces the slow read's timer for that one
        read; a run that began with another failure warns again for the limit."""
        client = serve_item(monkeypatch, open_reference(group_body()))
        client.scripted_item_reads.extend([*reads, group_body(ruled_card())])
        ticks = install(monkeypatch, reads_of(client))
        result = run_cli(["wait", "7", "--line", "3"], capsys)
        assert (result.status, result.stderr, ticks.now) == (
            0,
            "".join(f"{ITEM_WARNING}{sentence}\n" for sentence in warnings),
            paused_for,
        )

    def test_a_signal_that_moves_during_the_limit_causes_no_read_before_the_retry_time(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: WAIT-22, WAIT-07 -- a ruling during the limit moves the signal; the item is
        still read only at the reset."""
        client = serve_item(monkeypatch, open_reference(group_body()))
        client.scripted_item_reads.extend([None, LIMIT])
        ticks = install(monkeypatch, reads_of(client))
        ruling: list[CliRun] = []
        reads_after_the_ruling: list[int] = []

        def rule() -> None:
            ruling.append(run_cli(["rule", "7", *decide("A", "chat")], capsys))
            client.issue_references[ITEM] = open_reference(client.body_writes[-1][1])
            reads_after_the_ruling.append(len(client.issue_reference_lookups))

        ruled_at = SLOW_READ_PAUSES + 10
        ticks.afterwards[ruled_at] = rule
        result = run_cli(["wait", "7", "--line", "2"], capsys)
        # The ruling's own run drains what the wait had printed by then: the warning.
        assert (ruling[0].status, ruling[0].stderr) == (0, f"{ITEM_WARNING}{SENTENCE}\n")
        assert (result.status, result.stderr) == (0, "")
        assert set(ticks.reads_seen[ruled_at:]) == set(reads_after_the_ruling)
        assert ticks.now == cmd_wait.ITEM_READ_SECONDS + RETRY_AT_THE_RESET
