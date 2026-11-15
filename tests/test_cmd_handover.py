"""`aco handover` on real temporary git worktrees and the real state ref: the acting
session becomes the holder of a predecessor's claim, the item records who took over from
whom and why, and every refusal writes nothing. The forge is the only fake."""

import json
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, complete_contract
from claim_worktrees import (
    ISSUE,
    LANE_BRANCH,
    StandIn,
    Standing,
    assert_json_refusal_object,
    assert_no_item_body_written,
    claimed_here,
    held_by_ada,
    make_stand_in,
    replace_item_body,
    rescope_arguments,
    serve_body,
    standing_claims,
)
from cli_fixtures import run_cli
from github_fixtures import FakeForge
from store_fixtures import fail_every_state_ref_push, state_ref_tip

from aco import body, item_handover
from aco.protocol import ClaimError

TRUNK_FILES = ("src/widget.py",)
HELD_SCOPE = ("src/widget.py",)
PREDECESSOR = "Claude af547fd1"
SUCCESSOR = "Ada"
REASON = "the operator restarted every head"
NEW_FILE = "src/new.py"


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


def held_by_the_predecessor() -> tuple[Standing, ...]:
    return (Standing(HELD_SCOPE, issue=ISSUE, agent=PREDECESSOR, branch=LANE_BRANCH),)


def handover_arguments(*flags: str) -> list[str]:
    """`aco handover` on item `ISSUE`, from the predecessor, with the reason, then `flags`."""
    return [
        "--repo",
        REPOSITORY,
        "handover",
        str(ISSUE),
        "--from",
        PREDECESSOR,
        "--reason",
        REASON,
        *flags,
    ]


def recorded_handover(served: FakeForge) -> item_handover.ItemHandover | None:
    return item_handover.parse_handover(body.locate_block(served.item_bodies[ISSUE]).data)


def test_a_handover_makes_the_acting_session_the_holder_and_records_it_on_the_item(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: HANDOVER-01, HANDOVER-02, HANDOVER-03."""
    standpoint = stand_in(standing=held_by_the_predecessor())
    served = serve_body(monkeypatch, complete_contract("Build it."))
    before = claimed_here(standpoint)

    result = run_cli(handover_arguments(), capsys)

    after = claimed_here(standpoint)
    assert (result.status, result.stderr) == (0, "")
    assert result.stdout == f"HANDED OVER #{ISSUE}: {PREDECESSOR} -> {SUCCESSOR}\n"
    assert (after.agent, after.role, after.claim_id, after.branch, after.scope) == (
        SUCCESSOR,
        before.role,
        before.claim_id,
        before.branch,
        before.scope,
    )
    record = recorded_handover(served)
    assert record is not None
    assert (record.from_agent, record.to_agent, record.reason) == (PREDECESSOR, SUCCESSOR, REASON)


def test_the_new_holder_rescopes_and_releases_without_an_override(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: HANDOVER-04."""
    standpoint = stand_in(standing=held_by_the_predecessor())
    serve_body(monkeypatch, complete_contract("Build it."))
    taken = run_cli(handover_arguments(), capsys)

    rescoped = run_cli(rescope_arguments("--add", NEW_FILE), capsys)
    released = run_cli(
        ["--repo", REPOSITORY, "release", str(ISSUE), "--abandoned", "stopped"], capsys
    )

    assert (taken.status, rescoped.status, released.status) == (0, 0, 0)
    assert standing_claims(standpoint) == []


def test_the_predecessor_is_refused_once_the_claim_has_moved(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: HANDOVER-04, HANDOVER-09."""
    stand_in(standing=held_by_the_predecessor())
    serve_body(monkeypatch, complete_contract("Build it."))
    run_cli(handover_arguments(), capsys)

    result = run_cli(
        rescope_arguments("--agent", PREDECESSOR, "--add", NEW_FILE),
        capsys,
    )

    assert (result.status, result.stdout) == (2, "")
    assert f"holder='{SUCCESSOR} (builder)'" in result.stderr


def test_a_repeat_changes_nothing_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: HANDOVER-07."""
    stand_in(standing=held_by_the_predecessor())
    served = serve_body(monkeypatch, complete_contract("Build it."))
    first = run_cli(handover_arguments(), capsys)
    replace_item_body(served, served.item_bodies[ISSUE])
    tip = state_ref_tip(bare_remote)

    repeated = run_cli(handover_arguments(), capsys)

    assert (first.status, repeated.status) == (0, 0)
    assert repeated.stdout == f"ALREADY HANDED OVER #{ISSUE}: {PREDECESSOR} -> {SUCCESSOR}\n"
    assert (state_ref_tip(bare_remote), len(served.body_writes)) == (tip, 1)


def test_a_failed_claim_write_leaves_the_record_and_the_same_command_finishes_it(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: HANDOVER-06."""
    standpoint = stand_in(standing=held_by_the_predecessor())
    served = serve_body(monkeypatch, complete_contract("Build it."))
    with monkeypatch.context() as failing:
        fail_every_state_ref_push(failing, ClaimError("push rejected (simulated)"))
        refused = run_cli(handover_arguments(), capsys)
    held_after_the_failure = claimed_here(standpoint).agent
    replace_item_body(served, served.item_bodies[ISSUE])

    repeated = run_cli(handover_arguments(), capsys)

    assert (refused.status, held_after_the_failure) == (2, PREDECESSOR)
    assert "run the same command again" in refused.stderr
    assert (repeated.status, claimed_here(standpoint).agent) == (0, SUCCESSOR)
    assert len(served.body_writes) == 1


@pytest.mark.parametrize(
    ("flags", "sentence"),
    [
        pytest.param(
            ("--from", "Someone Else"),
            f"#{ISSUE} is held by {PREDECESSOR!r}, not by 'Someone Else'",
            id="from-is-not-the-holder",
        ),
        pytest.param(("--reason", "  "), "reason must be one bounded non-empty line", id="blank"),
        pytest.param(
            ("--reason", "one\ntwo"), "reason must be one bounded non-empty line", id="two-lines"
        ),
    ],
)
def test_a_refused_handover_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
    flags: tuple[str, ...],
    sentence: str,
) -> None:
    """Spec: HANDOVER-05, HANDOVER-08."""
    standpoint = stand_in(standing=held_by_the_predecessor())
    served = serve_body(monkeypatch, complete_contract("Build it."))
    tip = state_ref_tip(bare_remote)
    arguments = handover_arguments()
    for flag, value in zip(flags[::2], flags[1::2], strict=True):
        arguments[arguments.index(flag) + 1] = value

    result = run_cli(arguments, capsys)

    assert (result.status, result.stdout) == (2, "")
    assert sentence in result.stderr
    assert state_ref_tip(bare_remote) == tip
    assert claimed_here(standpoint).agent == PREDECESSOR
    assert_no_item_body_written(served)


def test_a_session_that_holds_the_claim_refuses_a_handover_nobody_recorded(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: HANDOVER-05."""
    stand_in(standing=held_by_ada(HELD_SCOPE))
    served = serve_body(monkeypatch, complete_contract("Build it."))
    tip = state_ref_tip(bare_remote)

    result = run_cli(handover_arguments(), capsys)

    assert (result.status, result.stdout) == (2, "")
    assert f"this session already holds #{ISSUE}" in result.stderr
    assert (state_ref_tip(bare_remote), served.body_writes) == (tip, [])


def test_a_handover_of_an_item_nobody_claims_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: HANDOVER-05."""
    stand_in()
    served = serve_body(monkeypatch, complete_contract("Build it."))
    tip = state_ref_tip(bare_remote)

    result = run_cli(handover_arguments(), capsys)

    assert (result.status, result.stdout) == (2, "")
    assert f"#{ISSUE} has no active build claim" in result.stderr
    assert (state_ref_tip(bare_remote), served.body_writes) == (tip, [])


def test_a_json_handover_reports_both_agents(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: HANDOVER-10."""
    stand_in(standing=held_by_the_predecessor())
    serve_body(monkeypatch, complete_contract("Build it."))

    result = run_cli(handover_arguments("--json"), capsys)

    assert json.loads(result.stdout) == {
        "ok": True,
        "reason": "handed_over",
        "item": ISSUE,
        "from": PREDECESSOR,
        "to": SUCCESSOR,
    }


def test_a_json_refusal_is_a_failed_precondition(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: HANDOVER-10."""
    stand_in()
    serve_body(monkeypatch, complete_contract("Build it."))

    result = run_cli(handover_arguments("--json"), capsys)

    assert result.status == 2
    assert_json_refusal_object(result.stderr, result.stdout, reason="precondition_failed")
