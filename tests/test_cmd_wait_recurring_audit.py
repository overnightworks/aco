"""`aco wait` without an item and the recurring audits (`specs/wait.spec.md`, WAIT-23, WAIT-25,
E-WAIT-10), through the real entry over a real git trunk and a GitHub forge fake, with the
pause and clock the command takes."""

import json
from pathlib import Path

import pytest
from audit_world import LABEL, NAME, World, build_world, entry_toml
from board_fixtures import FakeBoardProbe, board_issue, complete_contract, serve_board_probe
from cli_fixtures import run_cli
from wait_fixtures import install

from aco import board_wait, cmd_wait, protocol

POLLS_PER_HOUR = int(board_wait.FULL_READ_SECONDS / cmd_wait.SIGNAL_POLL_SECONDS)
ACTION = "ACTIONABLE #11\n"


@pytest.fixture(autouse=True)
def _probe(monkeypatch: pytest.MonkeyPatch) -> None:
    serve_board_probe(monkeypatch, FakeBoardProbe())


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, github_clone: Path, github_world: Path) -> World:
    return build_world(monkeypatch, github_clone)


def due_without_anchor(world: World) -> None:
    world.configure(entry_toml())
    world.label_issue("nothing audited yet")


def run_both(capsys: pytest.CaptureFixture[str]) -> tuple[str, dict[str, object]]:
    printed = run_cli(["wait"], capsys)
    result = run_cli(["wait", "--json"], capsys)
    assert (printed.status, result.status) == (0, 0)
    return printed.stdout, json.loads(result.stdout)


def test_a_due_audit_alone_ends_the_wait_with_its_line_and_the_audit_due_reason(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-23, WAIT-25 (E-WAIT-10)."""
    world.own.board_issues = ()
    due_without_anchor(world)
    ticks = install(monkeypatch, lambda: 0)

    printed, payload = run_both(capsys)

    assert (printed, payload, ticks.pauses) == (
        f"AUDIT {NAME}\n",
        {"ok": True, "reason": "audit_due", "audits": [NAME]},
        [],
    )


def test_a_due_audit_is_printed_before_the_action_and_the_reason_stays_actionable(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-25 (E-WAIT-10)."""
    due_without_anchor(world)
    install(monkeypatch, lambda: 0)

    printed, payload = run_both(capsys)

    assert (printed, payload) == (
        f"AUDIT {NAME}\n{ACTION}",
        {"ok": True, "reason": "actionable", "item": 11, "audits": [NAME]},
    )


def test_each_due_audit_has_its_line_in_entry_order(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-25."""
    world.own.board_issues = ()
    world.configure(entry_toml(name="second", label="audit-second") + entry_toml())
    world.label_issue("nothing audited yet")
    world.own.labelled_issues["audit-second"] = world.own.labelled_issues[LABEL]
    install(monkeypatch, lambda: 0)

    printed, payload = run_both(capsys)

    assert (printed, payload["audits"]) == (f"AUDIT second\nAUDIT {NAME}\n", ["second", NAME])


@pytest.mark.parametrize("unavailable", [False, True], ids=["not due", "unavailable"])
def test_an_audit_that_is_not_due_or_unavailable_does_not_end_the_wait(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    unavailable: bool,
) -> None:
    """Spec: WAIT-23."""
    world.own.board_issues = ()
    world.configure(entry_toml())
    world.label_issue(f"audited through {world.anchor_at(days_ago=0, commits_after=0)}")
    if unavailable:
        world.own.labelled_listing_error = protocol.ClaimError("GitHub is down")
    ticks = install(monkeypatch, lambda: 0)
    ticks.afterwards[5] = lambda: setattr(
        world.own,
        "board_issues",
        (board_issue(11, "Top work", complete_contract("Claim #11.")),),
    )

    printed, payload = run_both(capsys)

    assert (printed, payload["audits"], len(ticks.pauses)) == (ACTION, [], POLLS_PER_HOUR)


def test_without_an_entry_nothing_is_listed_and_the_output_gains_only_an_empty_audits_key(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-25."""
    install(monkeypatch, lambda: 0)

    printed, payload = run_both(capsys)

    assert (printed, payload, world.own.labelled_listings) == (
        ACTION,
        {"ok": True, "reason": "actionable", "item": 11, "audits": []},
        [],
    )
