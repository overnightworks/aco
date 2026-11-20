"""`aco wait` without an item and the recurring audits (`specs/wait.spec.md`, WAIT-23, WAIT-25,
E-WAIT-10), through the real entry over a real git trunk and a GitHub forge fake, with the
pause and clock the command takes."""

import json
import re

import pytest
from audit_world import LABEL, NAME, World, entry_toml
from board_fixtures import board_issue, complete_contract, holding_for_the_operator
from cli_fixtures import run_cli
from option_cards import group_body, ruled_card
from wait_fixtures import FIRST_PAUSE_AFTER_THE_READ, ITEM, install, open_reference

from aco import board_wait, cmd_wait, protocol

POLLS_PER_HOUR = int(board_wait.FULL_READ_SECONDS / cmd_wait.SIGNAL_POLL_SECONDS)
ACTION = "ACTIONABLE #11\n"


def due_without_anchor(audit_world: World) -> None:
    audit_world.configure(entry_toml())
    audit_world.label_issue("nothing audited yet")


def run_both(capsys: pytest.CaptureFixture[str]) -> tuple[str, dict[str, object]]:
    printed = run_cli(["wait"], capsys)
    result = run_cli(["wait", "--json"], capsys)
    assert (printed.status, result.status) == (0, 0)
    return printed.stdout, json.loads(result.stdout)


def test_a_due_audit_alone_ends_the_wait_with_its_line_and_the_audit_due_reason(
    audit_world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-23, WAIT-25 (E-WAIT-10)."""
    audit_world.own.board_issues = ()
    due_without_anchor(audit_world)
    ticks = install(monkeypatch, lambda: 0)

    printed, payload = run_both(capsys)

    assert (printed, payload, ticks.pauses) == (
        f"AUDIT {NAME}\n",
        {"ok": True, "reason": "audit_due", "audits": [NAME]},
        [],
    )


def test_a_due_audit_is_printed_before_the_action_and_the_reason_stays_actionable(
    audit_world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-25 (E-WAIT-10)."""
    due_without_anchor(audit_world)
    install(monkeypatch, lambda: 0)

    printed, payload = run_both(capsys)

    assert (printed, payload) == (
        f"AUDIT {NAME}\n{ACTION}",
        {"ok": True, "reason": "actionable", "item": 11, "audits": [NAME]},
    )


def test_each_due_audit_has_its_line_in_entry_order(
    audit_world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-25."""
    audit_world.own.board_issues = ()
    audit_world.configure(entry_toml(name="second", label="audit-second") + entry_toml())
    audit_world.label_issue("nothing audited yet")
    audit_world.own.labelled_issues["audit-second"] = audit_world.own.labelled_issues[LABEL]
    install(monkeypatch, lambda: 0)

    printed, payload = run_both(capsys)

    assert (printed, payload["audits"]) == (f"AUDIT second\nAUDIT {NAME}\n", ["second", NAME])


@pytest.mark.parametrize("unavailable", [False, True], ids=["not due", "unavailable"])
def test_an_audit_that_is_not_due_or_unavailable_does_not_end_the_wait(
    audit_world: World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    unavailable: bool,
) -> None:
    """Spec: WAIT-23."""
    audit_world.own.board_issues = ()
    audit_world.configure(entry_toml())
    audit_world.label_issue(f"audited through {audit_world.anchor_at(days_ago=0, commits_after=0)}")
    if unavailable:
        audit_world.own.labelled_listing_error = protocol.ClaimError("GitHub is down")
    ticks = install(monkeypatch, lambda: 0)
    ticks.afterwards[FIRST_PAUSE_AFTER_THE_READ] = lambda: setattr(
        audit_world.own,
        "board_issues",
        (board_issue(11, "Top work", complete_contract("Claim #11.")),),
    )

    printed, payload = run_both(capsys)

    assert (printed, payload["audits"], len(ticks.pauses)) == (ACTION, [], POLLS_PER_HOUR)


def test_without_an_entry_nothing_is_listed_and_the_output_gains_only_an_empty_audits_key(
    audit_world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: WAIT-25."""
    install(monkeypatch, lambda: 0)

    printed, payload = run_both(capsys)

    assert (printed, payload, audit_world.own.labelled_listings) == (
        ACTION,
        {"ok": True, "reason": "actionable", "item": 11, "audits": []},
        [],
    )


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_a_due_audit_with_changed_lines_and_no_action_prints_the_audit_first_and_carries_the_lines(
    audit_world: World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    as_json: bool,
) -> None:
    """Spec: WAIT-25 (E-WAIT-10)."""
    raw = holding_for_the_operator(group_body())
    audit_world.own.board_issues = (board_issue(ITEM, "Karte", raw),)
    audit_world.own.issue_references[ITEM] = open_reference(raw)
    audit_world.configure(entry_toml())
    audit_world.label_issue(f"audited through {audit_world.anchor_at(days_ago=0, commits_after=0)}")
    ticks = install(monkeypatch, lambda: 0)

    def land_and_rule_by_hand() -> None:
        ruled = holding_for_the_operator(group_body(ruled_card()))
        audit_world.land(days_ago=0, count=3)
        audit_world.own.board_issues = (board_issue(ITEM, "Karte", ruled),)
        audit_world.own.issue_references[ITEM] = open_reference(ruled)

    ticks.afterwards[POLLS_PER_HOUR] = land_and_rule_by_hand

    result = run_cli(["wait", *(["--json"] if as_json else [])], capsys)

    if as_json:
        payload = json.loads(result.stdout)
        assert (payload["reason"], payload["audits"], payload["lines"][0]["index"]) == (
            "audit_due",
            [NAME],
            3,
        )
    else:
        assert re.fullmatch(
            rf"AUDIT {NAME}\nCHANGED #{ITEM} line 3: ruled A \d{{4}}-\d{{2}}-\d{{2}}\n",
            result.stdout,
        )
