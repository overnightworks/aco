"""A claim request made twice, on real temporary git worktrees and the real
state ref: the retry of an interrupted request that returns the live claim,
what it reads from the claim and the item rather than the forge, and the
retries that are refused. The forge is the only fake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from board_fixtures import board_issue, complete_contract
from claim_worktrees import (
    ISSUE,
    ITEM_WHOLE_REASON,
    LANE_BRANCH,
    StandIn,
    Standing,
    claim,
    claimed_here,
    make_stand_in,
    release,
    serve_item,
    standing_claims,
)
from cli_fixtures import forbid_forge_resolution
from store_fixtures import fail_every_state_ref_push

from aco import forge, protocol

TRUNK_FILES = ("src/widget.py", "src/other.py", "tests/test_widget.py")
CLAIM_ID = "live-claim"
OVERLAP_LINE = "1 of 4 versioned files (25%); overlaps no other open claims"
LEDGER_REFUSAL = "already on this ledger, active or released"


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


def test_replay_of_a_wide_scope_without_whole_reads_only_its_own_item(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: CLAIM-13, CLM-37."""
    standpoint = stand_in()
    served = serve_item(monkeypatch, ("src",))
    assert claim("--claim-id", CLAIM_ID) == 0
    capsys.readouterr()

    def board_read_refused() -> None:
        raise protocol.MalformedStateTreeError(
            "item aco-0a0a0a is referenced as a parent but does not exist"
        )

    monkeypatch.setattr(served, "list_open_board_issues", board_read_refused)

    status = claim("--claim-id", CLAIM_ID)

    assert status == 0
    assert capsys.readouterr().out.startswith(f"CLAIMED issue #{ISSUE}: {CLAIM_ID}")
    assert claimed_here(standpoint).whole_reason == ITEM_WHOLE_REASON


def test_replay_without_scope_takes_the_live_claims_own_stored_scope(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: CLAIM-13, CLM-15."""
    stand_in()
    served = serve_item(monkeypatch, ("src/widget.py",))
    assert claim("--claim-id", CLAIM_ID, scope=("src/widget.py",)) == 0
    capsys.readouterr()
    changed = complete_contract("Build it.", scope=["src/other.py"])
    served.board_issues = (board_issue(ISSUE, "Claims", changed),)
    served.issue_references[ISSUE] = forge.ItemReference(forge.ItemState.OPEN, "Claims", changed)
    forbid_forge_resolution(monkeypatch)

    status = claim("--claim-id", CLAIM_ID, "--json", scope=())

    assert status == 0
    assert json.loads(capsys.readouterr().out)["scope"] == ["src/widget.py"]


def test_replay_reports_the_live_claim_after_an_interrupted_response(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: CLAIM-13, CLM-15."""
    standpoint = stand_in()
    serve_item(monkeypatch, ("src/widget.py",))
    with monkeypatch.context() as interrupted:
        fail_every_state_ref_push(interrupted, protocol.ClaimError("push timed out"), lands=True)
        assert claim("--claim-id", CLAIM_ID, scope=("src/widget.py",)) == 2
    capsys.readouterr()
    landed = claimed_here(standpoint)

    plain = claim("--claim-id", CLAIM_ID, scope=("src/widget.py",))
    printed = capsys.readouterr().out
    as_json = claim("--claim-id", CLAIM_ID, "--json", scope=("src/widget.py",))
    replay = json.loads(capsys.readouterr().out)

    assert (plain, as_json) == (0, 0)
    assert printed == f"CLAIMED issue #{ISSUE}: {CLAIM_ID}\n{OVERLAP_LINE}\n"
    assert {
        key: replay[key] for key in ("claim_id", "issue", "agent", "role", "branch", "scope")
    } == {
        "claim_id": CLAIM_ID,
        "issue": ISSUE,
        "agent": landed.agent,
        "role": landed.role,
        "branch": landed.branch,
        "scope": ["src/widget.py"],
    }
    assert standing_claims(standpoint) == [landed]


@pytest.mark.parametrize(
    ("agent", "role", "branch", "scope"),
    [
        pytest.param("Grok 4.6", "builder", LANE_BRANCH, ("src/widget.py",), id="agent"),
        pytest.param("Ada", "reviewer", LANE_BRANCH, ("src/widget.py",), id="role"),
        pytest.param("Ada", "builder", "codex/issue-72-retry", ("src/widget.py",), id="branch"),
        pytest.param("Ada", "builder", LANE_BRANCH, ("src/widget.py", "src/other.py"), id="scope"),
    ],
)
def test_replay_with_different_retry_fields_is_refused_and_the_live_claim_stays(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    agent: str,
    role: str,
    branch: str,
    scope: tuple[str, ...],
) -> None:
    """Spec: CLAIM-11."""
    holder = Standing(("src/widget.py",), issue=ISSUE, branch=LANE_BRANCH)
    standpoint = stand_in(branch=branch, standing=(holder,))
    serve_item(monkeypatch, scope)
    before = standing_claims(standpoint)

    status = claim("--role", role, agent=agent, scope=scope)

    assert status == 2
    holder = f"Ada (builder) on issue #{ISSUE} branch {LANE_BRANCH}"
    assert capsys.readouterr().err == f"ERROR: issue #{ISSUE} is claimed by {holder}\n"
    assert standing_claims(standpoint) == before


def test_replay_does_not_resurrect_a_released_claim(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: CLAIM-14, CLAIM-15."""
    standpoint = stand_in()
    serve_item(monkeypatch, ("src/widget.py",))
    assert claim("--claim-id", "released-claim", scope=("src/widget.py",)) == 0
    assert release("--agent", "Codex Sol") == 0
    capsys.readouterr()

    status = claim("--claim-id", "released-claim", scope=("src/widget.py",))

    assert status == 2
    assert LEDGER_REFUSAL in capsys.readouterr().err
    assert not standing_claims(standpoint)
