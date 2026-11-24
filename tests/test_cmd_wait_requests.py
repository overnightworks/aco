"""What a bare `aco wait` costs the forge in requests while probes hit (`specs/wait.spec.md`,
WAIT-27): a fake forge counts every request, a fake probe every answer that is billed, and the
real command ticks over a board with a container and an item with a dependency."""

from collections.abc import Callable
from dataclasses import replace

import pytest
from board_fixtures import (
    REPOSITORY,
    FakeBoardProbe,
    block_dependency,
    blocked_issue,
    board_issue,
    serve_board_probe,
)
from cli_fixtures import run_cli
from github_fixtures import FakeForge, serve_forge
from wait_fixtures import ITEM, OTHER_ITEM, free_item, install, open_reference, waiting_card

from aco import board_wait, body, cmd_wait, forge, workboard

HITS = 22
FULL_READS = 4
LISTED_ROW_CHANGES = (4, 10, 21)
REQUESTS_PER_HIT = 3
PAUSES_PER_PROBE = int(board_wait.PROBE_SECONDS / cmd_wait.SIGNAL_POLL_SECONDS)
HIT_OFFSET = 5
READ_OFFSET = 1
CONTAINERS = (20, 22, 24)
BLOCKED = (30, 31, 32)
PULL_REQUEST = workboard.PullRequest(9, "Change", "Closes #50", "branch")

pytestmark = pytest.mark.usefixtures("frozen_wait_world")


def board_with_children_and_dependencies() -> FakeForge:
    """A waiting card, containers that each have a child and items blocked by the card."""
    containers = tuple(
        board_issue(
            number,
            "Container",
            "",
            kind=body.ItemKind.CONTAINER,
            children_total=1,
            children_closed=0,
        )
        for number in CONTAINERS
    )
    children: dict[int, workboard.ChildList] = {
        number: (workboard.ChildItem(number + 1, workboard.ChildState.OPEN, "Child"),)
        for number in CONTAINERS
    }
    blocked = [blocked_issue(number, "Blocked", block_dependency(ITEM)) for number in BLOCKED]
    return FakeForge(
        board_issues=(waiting_card(), *containers, *(issue for issue, _ in blocked)),
        board_dependencies={
            number: deps for _, dependencies in blocked for number, deps in dependencies.items()
        },
        children=children,
        issue_references={ITEM: open_reference(waiting_card().body)},
    )


def test_hits_that_change_no_listed_row_cost_the_probe_and_two_listings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-27 -- of 22 hits three change a listed row (a body, a label, an item that
    opens with a pull request) and each of those ends in a read that sees the change; the
    other 19 cost the probe and the two listings only."""
    client = serve_forge(monkeypatch, board_with_children_and_dependencies())
    probe = serve_board_probe(monkeypatch, FakeBoardProbe())
    ticks = install(monkeypatch, lambda: client.requests)
    target = forge.ProbeTarget(REPOSITORY)
    builds_after_each_hit: list[int] = []

    def comment() -> None:
        client.board_issues = tuple(
            replace(issue, updated_at="2026-08-21T00:00:00Z") for issue in client.board_issues
        )

    def edit_the_body() -> None:
        card, *rest = client.board_issues
        client.board_issues = (replace(card, body=card.body + "\nNote.\n"), *rest)

    def add_a_label() -> None:
        *rest, blocked = client.board_issues
        client.board_issues = (*rest, replace(blocked, labels=("documentation",)))

    def open_a_pull_request_that_frees_an_item() -> None:
        client.board_open_pull_requests = (PULL_REQUEST,)
        client.board_issues = (*client.board_issues, free_item())

    changes = {
        LISTED_ROW_CHANGES[0]: edit_the_body,
        LISTED_ROW_CHANGES[1]: add_a_label,
        LISTED_ROW_CHANGES[2]: open_a_pull_request_that_frees_an_item,
    }

    def hit_with(change: Callable[[], None]) -> Callable[[], None]:
        def happen() -> None:
            change()
            probe.change(target)

        return happen

    def note_the_builds() -> None:
        builds_after_each_hit.append(client.board_builds)

    for hit in range(HITS):
        ticks.afterwards[hit * PAUSES_PER_PROBE + HIT_OFFSET] = hit_with(changes.get(hit, comment))
    for hit in LISTED_ROW_CHANGES:
        ticks.afterwards[(hit + 1) * PAUSES_PER_PROBE + READ_OFFSET] = note_the_builds
    result = run_cli(["wait"], capsys)
    full_read = ticks.reads_seen[0]
    cost = client.requests + probe.billed
    assert (result.status, result.stdout, result.stderr) == (0, f"ACTIONABLE #{OTHER_ITEM}\n", "")
    assert len(ticks.pauses) == HITS * PAUSES_PER_PROBE
    assert cost <= HITS * REQUESTS_PER_HIT + FULL_READS * full_read
    assert full_read > 2 * REQUESTS_PER_HIT + 1
    assert (builds_after_each_hit[:2], client.board_builds) == ([2, 3], FULL_READS)


def test_a_hit_that_changes_a_listed_row_reads_the_board_over_the_listings_it_fetched(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-27 -- the hit costs the probe and the two listings, and the read it asks for
    reuses those listings, so it fetches the full read less the two listings."""
    client = serve_forge(monkeypatch, board_with_children_and_dependencies())
    probe = serve_board_probe(monkeypatch, FakeBoardProbe())
    ticks = install(monkeypatch, lambda: client.requests)
    costs_before_the_hit: list[int] = []

    def open_an_item_with_a_new_body() -> None:
        costs_before_the_hit.append(client.requests + probe.billed)
        card, *rest = client.board_issues
        client.board_issues = (replace(card, body=card.body + "\nNote.\n"), *rest, free_item())
        probe.change(forge.ProbeTarget(REPOSITORY))

    ticks.afterwards[HIT_OFFSET] = open_an_item_with_a_new_body
    result = run_cli(["wait"], capsys)
    full_read = ticks.reads_seen[0]
    cost_of_the_hit = client.requests + probe.billed - costs_before_the_hit[0]
    assert (result.status, result.stdout) == (0, f"ACTIONABLE #{OTHER_ITEM}\n")
    assert cost_of_the_hit == REQUESTS_PER_HIT + full_read - 2
