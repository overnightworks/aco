"""`aco wait` without an item after a probe hit (`specs/wait.spec.md`, WAIT-27, WAIT-28): the
open listings decide whether a hit reads the board, and a blocker in another repository is judged
from its own answer, through the real entry with only the forge, its probe, the pause and the
clock injected."""

from dataclasses import dataclass, replace

import pytest
from board_fixtures import (
    REPOSITORY,
    FakeBoardProbe,
    block_dependency,
    blocked_issue,
    serve_board_probe,
)
from cli_fixtures import FROZEN_CLI_NOW, run_cli
from github_fixtures import FakeForge, serve_forge
from wait_fixtures import ITEM, OTHER_ITEM, free_item, install, open_reference, waiting_card

from aco import board_wait, cmd_wait, forge, workboard

FOREIGN = "other/repo"
FOREIGN_BLOCKER = forge.ProbeTarget(FOREIGN, 3)
REPOSITORY_TARGET = forge.ProbeTarget(REPOSITORY)
HIT_AT = 5
SECOND_HIT_AT = 40
PAUSES_PER_PROBE = int(board_wait.PROBE_SECONDS / cmd_wait.SIGNAL_POLL_SECONDS)
DOWN = "the forge is down"
STILL_WAITING = "WARNING: the board could not be read, still waiting: "
ACTIONABLE = f"ACTIONABLE #{OTHER_ITEM}\n"

pytestmark = pytest.mark.usefixtures("frozen_wait_world")


@dataclass
class ListingForge(FakeForge):
    """A forge whose listing of the open issues fails with `listing_failure` while one is set."""

    listing_failure: forge.ForgeError | None = None

    def list_open_board_issues(self) -> tuple[workboard.Issue, ...]:
        if self.listing_failure is not None:
            raise self.listing_failure
        return super().list_open_board_issues()


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> FakeBoardProbe:
    probe = FakeBoardProbe()
    serve_board_probe(monkeypatch, probe)
    return probe


def card_references() -> dict[int, forge.ItemReference]:
    """Item 7 as the forge serves it for the wait's reread of an item it watches."""
    return {ITEM: open_reference(waiting_card().body)}


def test_a_hit_that_changes_the_body_of_a_listed_item_wakes_it_within_the_minute(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    probe: FakeBoardProbe,
) -> None:
    """Spec: WAIT-27 -- a changed body is a changed row: the read that follows names the
    action `aco next` would."""
    client = serve_forge(
        monkeypatch, FakeForge(board_issues=(waiting_card(),), issue_references=card_references())
    )
    ticks = install(monkeypatch, lambda: 0)

    def rewrite_the_body() -> None:
        client.board_issues = (free_item(),)
        probe.change(REPOSITORY_TARGET)

    ticks.afterwards[HIT_AT] = rewrite_the_body
    result = run_cli(["wait"], capsys)
    assert (result.status, result.stdout, result.stderr) == (0, ACTIONABLE, "")
    assert len(ticks.pauses) == PAUSES_PER_PROBE


def test_a_blocker_of_the_same_repository_that_closes_wakes_its_dependent_within_the_minute(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    probe: FakeBoardProbe,
) -> None:
    """Spec: WAIT-27 -- the closed blocker leaves the open listing, which is a changed listing."""
    dependent, dependencies = blocked_issue(OTHER_ITEM, "Alpha", block_dependency(ITEM))
    client = serve_forge(
        monkeypatch,
        FakeForge(
            board_issues=(waiting_card(), dependent),
            board_dependencies=dependencies,
            issue_references=card_references(),
        ),
    )
    ticks = install(monkeypatch, lambda: 0)

    def close_the_blocker() -> None:
        closed = block_dependency(
            ITEM, state=workboard.BlockerState.CLOSED, closed_at=FROZEN_CLI_NOW
        )
        client.board_issues = (dependent,)
        client.board_dependencies = {OTHER_ITEM: (closed,)}
        probe.change(REPOSITORY_TARGET)

    ticks.afterwards[HIT_AT] = close_the_blocker
    result = run_cli(["wait"], capsys)
    assert (result.status, result.stdout, result.stderr) == (0, ACTIONABLE, "")
    assert len(ticks.pauses) == PAUSES_PER_PROBE


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(forge.ForgeTransientError(DOWN), id="transient"),
        pytest.param(
            forge.ForgeRateLimitedError("GitHub's REST rate limit is reached"), id="rate-limited"
        ),
    ],
)
def test_a_listing_check_that_fails_is_made_again_and_the_read_after_it_sees_the_latest_rows(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    probe: FakeBoardProbe,
    failure: forge.ForgeTransientError,
) -> None:
    """Spec: WAIT-27, WAIT-20, WAIT-22 -- the hit stays owed when the probes after it answer
    unchanged, the warning is said once, and the rows read at last are the latest."""
    client = serve_forge(
        monkeypatch,
        ListingForge(board_issues=(waiting_card(),), issue_references=card_references()),
    )
    ticks = install(monkeypatch, lambda: 0)

    def hit_while_the_listing_fails() -> None:
        client.listing_failure = failure
        client.board_issues = (replace(free_item(), number=OTHER_ITEM + 1),)
        probe.change(REPOSITORY_TARGET)

    def answer_with_the_latest_rows() -> None:
        client.listing_failure = None
        client.board_issues = (free_item(),)

    ticks.afterwards[HIT_AT] = hit_while_the_listing_fails
    ticks.afterwards[4 * PAUSES_PER_PROBE] = answer_with_the_latest_rows
    result = run_cli(["wait"], capsys)
    assert (result.status, result.stdout) == (0, ACTIONABLE)
    assert result.stderr == f"{STILL_WAITING}{failure}\n"
    assert len(ticks.pauses) == 4 * PAUSES_PER_PROBE


@pytest.fixture
def foreign_blocked(monkeypatch: pytest.MonkeyPatch) -> FakeForge:
    """A forge whose one item is blocked by item 3 of another repository."""
    dependent, dependencies = blocked_issue(
        OTHER_ITEM, "Alpha", block_dependency(3, repository=FOREIGN)
    )
    return serve_forge(
        monkeypatch, FakeForge(board_issues=(dependent,), board_dependencies=dependencies)
    )


def close_foreign_blocker(client: FakeForge) -> None:
    client.board_dependencies = {
        OTHER_ITEM: (
            block_dependency(
                3,
                repository=FOREIGN,
                state=workboard.BlockerState.CLOSED,
                closed_at=FROZEN_CLI_NOW,
            ),
        )
    }


def test_a_hit_on_an_open_blocker_reads_no_board(
    capsys: pytest.CaptureFixture[str],
    probe: FakeBoardProbe,
    foreign_blocked: FakeForge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec: WAIT-28 -- a comment on a blocker moves its probe only; the board is read once
    at the start and once when the blocker closes."""
    ticks = install(monkeypatch, lambda: 0)
    builds_after_the_comment: list[int] = []

    def comment_on_the_blocker() -> None:
        probe.change(FOREIGN_BLOCKER)

    def note_the_builds() -> None:
        builds_after_the_comment.append(foreign_blocked.board_builds)
        close_foreign_blocker(foreign_blocked)
        probe.close(FOREIGN_BLOCKER)

    ticks.afterwards[HIT_AT] = comment_on_the_blocker
    ticks.afterwards[SECOND_HIT_AT] = note_the_builds
    run_cli(["wait"], capsys)
    assert builds_after_the_comment == [1]


def test_a_blocker_in_another_repository_that_closes_wakes_its_dependent_within_the_minute(
    capsys: pytest.CaptureFixture[str],
    probe: FakeBoardProbe,
    foreign_blocked: FakeForge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec: WAIT-28 -- the closing wakes the wait with the item, and a blocker first probed
    after a read costs no second read."""
    ticks = install(monkeypatch, lambda: 0)

    def close_the_blocker() -> None:
        close_foreign_blocker(foreign_blocked)
        probe.close(FOREIGN_BLOCKER)

    ticks.afterwards[HIT_AT] = close_the_blocker
    result = run_cli(["wait"], capsys)
    assert (result.status, result.stdout, result.stderr) == (0, ACTIONABLE, "")
    assert (foreign_blocked.board_builds, len(ticks.pauses)) == (2, PAUSES_PER_PROBE)
