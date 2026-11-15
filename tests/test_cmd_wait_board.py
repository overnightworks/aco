"""`aco wait` without an item (`specs/wait.spec.md`, WAIT-14 to WAIT-21): an idle head's wait on its
board, through the real entry over a real bare remote, injecting only the forge, its probe and
the pause and clock the command takes."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import pytest
from board_fixtures import (
    REPOSITORY,
    FakeBoardProbe,
    block_dependency,
    blocked_issue,
    board_issue,
    complete_contract,
    serve_board_probe,
)
from cli_fixtures import FROZEN_CLI_NOW, freeze_cli_now, real_git, run_cli, set_git_identity
from cli_fixtures import track_board_config as pin_board_config
from github_fixtures import FakeForge, serve_forge
from option_cards import decide, group_body, open_option_entry
from store_fixtures import (
    claim_intent,
    item_record,
    path_without_gh,
    publish_claims_from_a_second_clone,
    push_item_tree,
)
from wait_fixtures import ITEM, install, open_reference

from aco import board_wait, cmd_wait, forge, protocol, session, store, workboard
from aco.body import BLOCK_FENCE_INFO, render_block

FOREIGN = "other/repo"
BLOCKED = 50
ACTIONABLE_AFTER_THE_BLOCKER = f"ACTIONABLE #{BLOCKED}\n"
POLLS_PER_PROBE = int(board_wait.PROBE_SECONDS / cmd_wait.SIGNAL_POLL_SECONDS)
POLLS_PER_HOUR = int(board_wait.FULL_READ_SECONDS / cmd_wait.SIGNAL_POLL_SECONDS)
CHANGED_LINE = re.compile(r"CHANGED #7 line 2: ruled A \d{4}-\d{2}-\d{2}\n")
DOWN = "the forge is down"
STILL_WAITING = "WARNING: the board could not be read, still waiting: "


@dataclass
class UnreadableBoardForge(FakeForge):
    """A forge whose board read answers `board_failure` while one is set."""

    board_failure: forge.ForgeError | None = None

    def list_open_board_issues(self) -> tuple[workboard.Issue, ...]:
        if self.board_failure is not None:
            raise self.board_failure
        return super().list_open_board_issues()


@dataclass
class RulingDuringTheReadForge(FakeForge):
    """A forge that runs `during_the_read` once, after the board read has taken its
    snapshot and before it returns it."""

    during_the_read: Callable[[], None] | None = None

    def list_open_board_issues(self) -> tuple[workboard.Issue, ...]:
        snapshot = super().list_open_board_issues()
        happening, self.during_the_read = self.during_the_read, None
        if happening is not None:
            happening()
        return snapshot


def blocked_board(*, closed: bool) -> UnreadableBoardForge:
    """Item 50, blocked by an issue of another repository, closed or not."""
    state = workboard.BlockerState.CLOSED if closed else workboard.BlockerState.OPEN
    closed_at = FROZEN_CLI_NOW if closed else None
    issue, dependencies = blocked_issue(
        BLOCKED,
        "Alpha",
        block_dependency(3, repository=FOREIGN, state=state, closed_at=closed_at),
    )
    return UnreadableBoardForge(board_issues=(issue,), board_dependencies=dependencies)


def card_issue(raw: str) -> workboard.Issue:
    """Item 7 holding open cards, labelled as its head labels an item that waits on them."""
    return board_issue(ITEM, "Karte", raw, labels=(workboard.NEEDS_OPERATOR_LABEL,))


def free_item() -> workboard.Issue:
    return board_issue(BLOCKED, "Alpha", complete_contract(f"Claim #{BLOCKED}."))


@pytest.fixture(autouse=True)
def _world(monkeypatch: pytest.MonkeyPatch, github_world: Path) -> None:
    freeze_cli_now(monkeypatch)


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> FakeBoardProbe:
    return serve_board_probe(monkeypatch, FakeBoardProbe())


def rule_through_aco(client: FakeForge, capsys: pytest.CaptureFixture[str]) -> str:
    """`aco rule` on line 2 of item 7, which the forge then serves as the item's body."""
    assert run_cli(["rule", str(ITEM), *decide("A", "chat")], capsys).status == 0
    written = client.body_writes[-1][1]
    client.issue_references[ITEM] = open_reference(written)
    return written


def close_the_blocker(client: FakeForge, probe: FakeBoardProbe) -> Callable[[], None]:
    def close() -> None:
        client.board_dependencies = blocked_board(closed=True).board_dependencies
        probe.change(forge.ProbeTarget(FOREIGN, 3))

    return close


class TestWaitingOnTheBoard:
    @pytest.mark.parametrize(
        ("flags", "printed"),
        [
            pytest.param([], ACTIONABLE_AFTER_THE_BLOCKER, id="text"),
            pytest.param(
                ["--json"],
                json.dumps({"ok": True, "reason": "actionable", "item": BLOCKED}) + "\n",
                id="json",
            ),
        ],
    )
    def test_a_blocker_closed_in_another_repository_wakes_it_with_the_item_at_the_next_probe(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
        flags: list[str],
        printed: str,
    ) -> None:
        """Spec: WAIT-14, WAIT-15, WAIT-16, WAIT-18 -- the probe of the blocker moved, the read
        that follows names the item `aco next` would."""
        client = serve_forge(monkeypatch, blocked_board(closed=False))
        ticks = install(monkeypatch, lambda: 0)
        ticks.afterwards[10] = close_the_blocker(client, probe)
        result = run_cli(["wait", *flags], capsys)
        assert (result.status, result.stderr, result.stdout) == (0, "", printed)
        assert len(ticks.pauses) == POLLS_PER_PROBE
        assert set(probe.asked) == {forge.ProbeTarget(REPOSITORY), forge.ProbeTarget(FOREIGN, 3)}

    def test_an_action_at_the_start_ends_it_at_once_without_a_pause(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
    ) -> None:
        """Spec: WAIT-14 -- it ends at once if `aco next` names an action at the start."""
        serve_forge(monkeypatch, FakeForge(board_issues=(free_item(),)))
        ticks = install(monkeypatch, lambda: 0)
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stdout, ticks.pauses) == (0, ACTIONABLE_AFTER_THE_BLOCKER, [])
        assert probe.asked == [forge.ProbeTarget(REPOSITORY)]

    @pytest.mark.parametrize(
        "as_json", [pytest.param(False, id="text"), pytest.param(True, id="json")]
    )
    @pytest.mark.parametrize(
        "board_down",
        [pytest.param(False, id="board-readable"), pytest.param(True, id="board-unreadable")],
    )
    def test_a_card_ruled_by_aco_rule_ends_it_at_the_next_signal_poll_naming_the_line(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
        as_json: bool,
        board_down: bool,
    ) -> None:
        """Spec: WAIT-14 to WAIT-17 -- the real write signals; no probe moved; only the ruled
        item is read again, so a board that cannot be read does not hold the ruling back."""
        raw = group_body()
        client = serve_forge(
            monkeypatch,
            UnreadableBoardForge(
                board_issues=(card_issue(raw),), issue_references={ITEM: open_reference(raw)}
            ),
        )
        ticks = install(monkeypatch, lambda: 0)

        def rule() -> None:
            if board_down:
                client.board_failure = forge.ForgeTransientError(DOWN)
            rule_through_aco(client, capsys)

        ticks.afterwards[3] = rule
        result = run_cli(["wait", *(["--json"] if as_json else [])], capsys)
        assert (result.status, result.stderr, len(ticks.pauses)) == (0, "", 3)
        assert probe.tokens == {forge.ProbeTarget(REPOSITORY): "first"}
        if as_json:
            envelope = json.loads(result.stdout)
            line = envelope["lines"][0]
            assert (envelope["reason"], envelope.get("item")) == ("changed", None)
            assert (line["item"], line["index"]) == (ITEM, 2)
            assert re.fullmatch(r"ruled A \d{4}-\d{2}-\d{2}", line["state"])
        else:
            assert CHANGED_LINE.fullmatch(result.stdout)

    def test_a_change_the_probes_do_not_see_is_read_at_the_hour(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
    ) -> None:
        """Spec: WAIT-19 -- a full read runs hourly, whatever the probes say."""
        client = serve_forge(monkeypatch, FakeForge())
        ticks = install(monkeypatch, lambda: 0)
        ticks.afterwards[5] = lambda: setattr(client, "board_issues", (free_item(),))
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stdout) == (0, ACTIONABLE_AFTER_THE_BLOCKER)
        assert len(ticks.pauses) == POLLS_PER_HOUR

    def test_a_state_ref_moved_by_another_session_is_read_at_the_next_probe(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
        github_clone: Path,
        bare_remote: Path,
    ) -> None:
        """Spec: WAIT-18 -- the `ls-remote` of the state ref asks for a read; no probe moved."""
        client = serve_forge(monkeypatch, FakeForge())
        ticks = install(monkeypatch, lambda: 0)
        claim = claim_intent(
            identity=protocol.IssueIdentity(99),
            claim_id="claim-99",
            operation_id="op-99",
            branch="codex/issue-99-work",
            scope=("src/other.py",),
        )

        def another_session_claims_and_the_board_changes() -> None:
            client.board_issues = (free_item(),)
            publish_claims_from_a_second_clone(github_clone, bare_remote, (claim,))

        ticks.afterwards[5] = another_session_claims_and_the_board_changes
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stdout) == (0, ACTIONABLE_AFTER_THE_BLOCKER)
        assert len(ticks.pauses) == POLLS_PER_PROBE
        assert probe.tokens == {forge.ProbeTarget(REPOSITORY): "first"}

    def test_an_until_date_that_arrives_wakes_it_on_the_first_tick_of_that_day(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: WAIT-19 -- the date is compared on each tick; no probe or signal moved."""
        today = [FROZEN_CLI_NOW.date()]
        real_run_context = session.run_context

        def with_a_moving_today(repo: forge.RepositoryId | None) -> session.RunContext:
            context = real_run_context(repo)
            context.today = lambda: today[0]
            return context

        monkeypatch.setattr(session, "run_context", with_a_moving_today)
        waiting = board_issue(
            BLOCKED,
            "Alpha",
            complete_contract(
                "Claim.", wait={"until": date(2026, 8, 22), "since": date(2026, 8, 20)}
            ),
        )
        serve_forge(monkeypatch, FakeForge(board_issues=(waiting,)))
        serve_board_probe(monkeypatch, FakeBoardProbe())
        ticks = install(monkeypatch, lambda: 0)
        ticks.afterwards[10] = lambda: today.__setitem__(0, date(2026, 8, 22))
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stdout) == (0, ACTIONABLE_AFTER_THE_BLOCKER)
        assert len(ticks.pauses) == 10

    def test_a_ruling_during_the_first_read_is_seen_by_the_next_tick(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
    ) -> None:
        """Spec: WAIT-17 -- a card ruled after its lines were read but before its signal was
        first looked at ends the wait with the next tick, not with the hourly read."""
        raw = group_body()
        client = serve_forge(
            monkeypatch,
            RulingDuringTheReadForge(
                board_issues=(card_issue(raw),), issue_references={ITEM: open_reference(raw)}
            ),
        )
        client.during_the_read = lambda: rule_through_aco(client, capsys)
        ticks = install(monkeypatch, lambda: 0)
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stderr, len(ticks.pauses)) == (0, "", 1)
        assert CHANGED_LINE.fullmatch(result.stdout)

    def test_a_blocker_that_closes_before_its_first_probe_wakes_it_at_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
    ) -> None:
        """Spec: WAIT-14, WAIT-18 -- the token a blocker takes at its first probe is of a
        blocker the read found open, so a read follows that probe."""
        client = serve_forge(monkeypatch, blocked_board(closed=False))
        ticks = install(monkeypatch, lambda: 0)
        ask = probe.changed_since

        def close_when_first_asked(
            target: forge.ProbeTarget, token: str | None
        ) -> forge.ProbeAnswer:
            if target.number is not None and token is None:
                client.board_dependencies = blocked_board(closed=True).board_dependencies
            return ask(target, token)

        monkeypatch.setattr(probe, "changed_since", close_when_first_asked)
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stderr, result.stdout) == (
            0,
            "",
            ACTIONABLE_AFTER_THE_BLOCKER,
        )
        assert ticks.pauses == []

    def test_a_ruled_card_whose_item_no_longer_reads_as_one_is_left_to_the_board_read(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
    ) -> None:
        """Spec: WAIT-17 -- an item that is not readable as a card is no refusal of the wait;
        the board read decides."""
        raw = group_body()
        client = serve_forge(
            monkeypatch,
            FakeForge(
                board_issues=(card_issue(raw),), issue_references={ITEM: open_reference(raw)}
            ),
        )
        ticks = install(monkeypatch, lambda: 0)

        def rule_and_garble_the_item() -> None:
            written = rule_through_aco(client, capsys)
            client.board_issues = (card_issue(written),)
            client.issue_references[ITEM] = open_reference("no aco block here")

        ticks.afterwards[3] = rule_and_garble_the_item
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stderr, len(ticks.pauses)) == (0, "", 3)
        assert CHANGED_LINE.fullmatch(result.stdout)

    def test_a_ruled_item_that_is_closed_is_not_reported(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
    ) -> None:
        """Spec: WAIT-14 -- a line of an item that is no longer open is not reported."""
        raw = group_body()
        client = serve_forge(
            monkeypatch,
            FakeForge(
                board_issues=(card_issue(raw),), issue_references={ITEM: open_reference(raw)}
            ),
        )
        ticks = install(monkeypatch, lambda: 0)

        def rule_and_close() -> None:
            rule_through_aco(client, capsys)
            client.issue_references[ITEM] = replace(
                client.issue_references[ITEM], state=forge.ItemState.CLOSED
            )

        ticks.afterwards[3] = rule_and_close
        ticks.afterwards[10] = lambda: setattr(client, "board_issues", (free_item(),))
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stdout) == (0, ACTIONABLE_AFTER_THE_BLOCKER)
        assert len(ticks.pauses) == POLLS_PER_HOUR


class TestFailingWhileItWaits:
    def test_a_transient_failure_is_said_once_per_run_of_failures_and_the_wait_goes_on(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
    ) -> None:
        """Spec: WAIT-20, WAIT-10 -- two failed rounds warn once, an answering round between
        runs of failures makes the next one warn again, and a change then wakes it."""
        client = serve_forge(monkeypatch, blocked_board(closed=False))
        ticks = install(monkeypatch, lambda: 0)
        down = forge.ForgeTransientError(DOWN)
        ticks.afterwards[10] = lambda: setattr(probe, "failure", down)
        ticks.afterwards[70] = lambda: setattr(probe, "failure", None)
        ticks.afterwards[100] = lambda: setattr(probe, "failure", down)
        ticks.afterwards[130] = lambda: setattr(probe, "failure", None)
        ticks.afterwards[160] = close_the_blocker(client, probe)
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stdout) == (0, ACTIONABLE_AFTER_THE_BLOCKER)
        assert result.stderr == f"{STILL_WAITING}{DOWN}\n" * 2

    def test_a_read_that_keeps_failing_while_the_probes_answer_is_said_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
    ) -> None:
        """Spec: WAIT-20 -- a run of failed reads warns once, though the probes between the
        retries answer; the read that answers decides."""
        client = serve_forge(monkeypatch, blocked_board(closed=False))
        ticks = install(monkeypatch, lambda: 0)

        def the_board_changes_but_cannot_be_read() -> None:
            client.board_failure = forge.ForgeTransientError(DOWN)
            probe.change(forge.ProbeTarget(FOREIGN, 3))

        def the_board_is_readable_and_the_blocker_closed() -> None:
            client.board_failure = None
            client.board_dependencies = blocked_board(closed=True).board_dependencies

        ticks.afterwards[10] = the_board_changes_but_cannot_be_read
        ticks.afterwards[130] = the_board_is_readable_and_the_blocker_closed
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stdout) == (0, ACTIONABLE_AFTER_THE_BLOCKER)
        assert result.stderr == f"{STILL_WAITING}{DOWN}\n"

    def test_a_ruled_item_that_cannot_be_read_is_tried_again_after_the_minute_and_said_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
    ) -> None:
        """Spec: WAIT-17, WAIT-20 -- the moved signal stays owed through the retry pause."""
        raw = group_body()
        client = serve_forge(
            monkeypatch,
            FakeForge(
                board_issues=(card_issue(raw),), issue_references={ITEM: open_reference(raw)}
            ),
        )
        ticks = install(monkeypatch, lambda: 0)

        def rule_while_the_item_cannot_be_read() -> None:
            rule_through_aco(client, capsys)
            client.scripted_item_reads = [forge.ForgeTransientError(DOWN)]

        ticks.afterwards[3] = rule_while_the_item_cannot_be_read
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stderr) == (0, f"{STILL_WAITING}{DOWN}\n")
        assert CHANGED_LINE.fullmatch(result.stdout)
        assert len(ticks.pauses) == 3 + POLLS_PER_PROBE

    def test_a_state_ref_that_cannot_be_reached_is_said_like_a_transient_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
    ) -> None:
        """Spec: WAIT-20 -- a failed `ls-remote` warns once and the wait goes on."""
        client = serve_forge(monkeypatch, FakeForge())
        ticks = install(monkeypatch, lambda: 0)
        reachable = store.ls_remote_state
        unreachable = [False]

        def ls_remote(worktree: Path, remote: str) -> protocol.ObjectId | None:
            if unreachable[0]:
                raise protocol.ClaimError("cannot reach origin refs/aco/state")
            return reachable(worktree, remote)

        monkeypatch.setattr(store, "ls_remote_state", ls_remote)
        ticks.afterwards[10] = lambda: unreachable.__setitem__(0, True)
        ticks.afterwards[70] = lambda: unreachable.__setitem__(0, False)
        ticks.afterwards[80] = lambda: setattr(client, "board_issues", (free_item(),))
        ticks.afterwards[90] = lambda: probe.change(forge.ProbeTarget(REPOSITORY))
        result = run_cli(["wait", "--json"], capsys)
        assert (result.status, json.loads(result.stdout)["reason"]) == (0, "actionable")
        assert result.stderr == f"{STILL_WAITING}cannot reach origin refs/aco/state\n"

    @pytest.mark.parametrize("flags", [[], ["--json"]], ids=["text", "json"])
    def test_a_failure_that_is_not_transient_refuses_unavailable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
        flags: list[str],
    ) -> None:
        """Spec: WAIT-20, WAIT-11 -- any other failure ends the wait, exit 2."""
        serve_forge(monkeypatch, FakeForge())
        ticks = install(monkeypatch, lambda: 0)
        gone = forge.ForgeNotFoundError("HTTP 404")
        ticks.afterwards[10] = lambda: setattr(probe, "failure", gone)
        result = run_cli(["wait", *flags], capsys)
        assert (result.status, result.stderr) == (2, "ERROR: HTTP 404\n")
        assert result.stdout == (
            json.dumps({"ok": False, "reason": "unavailable", "message": "HTTP 404"}) + "\n"
            if flags
            else ""
        )

    def test_a_failure_at_the_start_refuses_before_any_pause(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        probe: FakeBoardProbe,
    ) -> None:
        """Spec: WAIT-20, WAIT-10 -- the first round of probes fails, so it refuses."""
        serve_forge(monkeypatch, FakeForge())
        probe.failure = forge.ForgeTransientError(DOWN)
        ticks = install(monkeypatch, lambda: 0)
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stderr, ticks.pauses) == (2, f"ERROR: {DOWN}\n", [])


@pytest.mark.parametrize("flags", [[], ["--json"]], ids=["text", "json"])
@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param(["--line", "2"], id="line-without-an-item"),
        pytest.param(["7"], id="item-without-a-line"),
    ],
)
def test_an_item_without_a_line_or_a_line_without_an_item_refuses_invalid_usage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    flags: list[str],
) -> None:
    """Spec: WAIT-21 -- the target is the item with its lines, or the board; never half."""
    ticks = install(monkeypatch, lambda: 0)
    message = "wait needs an item together with --line, or neither of them"
    result = run_cli(["wait", *arguments, *flags], capsys)
    envelope = {"ok": False, "reason": "invalid_usage", "message": message}
    assert (result.status, result.stderr, ticks.pauses) == (2, f"ERROR: {message}\n", [])
    assert result.stdout == (json.dumps(envelope) + "\n" if flags else "")


class TestUnderStateRef:
    """A real checkout pinned to `storage = "state-ref"` whose state ref carries one item with an
    open option line, run with a `PATH` that has no `gh`: a GitHub probe would fail the run."""

    ITEM_ID = "aco-000004"

    @pytest.fixture(autouse=True)
    def _state_ref_world(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        bare_remote: Path,
        github_clone: Path,
    ) -> None:
        set_git_identity(monkeypatch)
        record = item_record(
            title="Karte", state="open", kind="task", labels=(workboard.NEEDS_OPERATOR_LABEL,)
        )
        data: dict[str, object] = {
            "version": 1,
            "now": "Now.",
            "next": "Next.",
            "done_when": "Done.",
            "record": record,
            "expectation": [open_option_entry()],
        }
        text = f"Prose.\n\n```{BLOCK_FENCE_INFO}\n{render_block(data)}```\n"
        push_item_tree(bare_remote, github_clone, {f"{self.ITEM_ID}.md": text.encode()})
        real_git(github_clone, "push", "origin", "main")
        real_git(github_clone, "remote", "set-head", "origin", "main")
        pin_board_config(github_clone, 'storage = "state-ref"\ncanonical_remote = "origin"\n')
        monkeypatch.setenv("PATH", path_without_gh(tmp_path))

    def test_it_waits_on_the_state_ref_alone_and_ends_when_its_card_is_ruled(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        github_clone: Path,
    ) -> None:
        """Spec: WAIT-14, WAIT-15, WAIT-18 -- no GitHub probe; the ruling signals the wait."""
        monkeypatch.chdir(github_clone)
        ticks = install(monkeypatch, lambda: 0)

        def rule() -> None:
            ruling = ["rule", self.ITEM_ID, *decide("A", "chat", line=1)]
            assert run_cli(ruling, capsys).status == 0

        ticks.afterwards[3] = rule
        result = run_cli(["wait"], capsys)
        assert (result.status, result.stderr, len(ticks.pauses)) == (0, "", 3)
        assert re.fullmatch(
            rf"CHANGED {self.ITEM_ID} line 1: ruled A \d{{4}}-\d{{2}}-\d{{2}}\n", result.stdout
        )
