"""What `aco claim` leaves behind and prints, on real temporary git
worktrees and the real state ref: a lane claim released again, the `--json`
object of a claim made, and the `--json` refusal of a conflict and of a
failed write. The forge is the only fake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY
from claim_worktrees import (
    ISSUE,
    LANE_BRANCH,
    StandIn,
    Standing,
    assert_json_refusal_object,
    claim,
    make_stand_in,
    serve_item,
    standing_claims,
)
from cli_fixtures import set_agent_identity_env

from aco import cli as issue_claim
from aco import protocol, store

LANE_MODE_BRANCH = "docs/lane-cleanup"
JSON_SCOPE = ("src/widget.py", "docs/guide.md")
TRUNK_FILES = ("src/widget.py", "docs/guide.md", "tests/c.py", "scripts/d.py")


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


def test_a_lane_claim_and_its_release_never_name_an_issue_number(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn
) -> None:
    """Spec: CLAIM-03, CLM-06, REL-03."""
    standpoint = stand_in(branch=LANE_MODE_BRANCH)
    set_agent_identity_env(monkeypatch, {"ACO_AGENT": "Codex Sol"})

    claimed = claim("--role", "builder", scope=("docs/guide.md",), agent=None, issue=None)
    [live] = standing_claims(standpoint)
    released = issue_claim.main(["--repo", REPOSITORY, "release", "--abandoned", "stopped"])

    assert (claimed, live.identity, live.branch, live.scope) == (
        0,
        protocol.LaneIdentity(),
        LANE_MODE_BRANCH,
        ("docs/guide.md",),
    )
    assert released == 0
    assert not standing_claims(standpoint)


@pytest.mark.parametrize(
    ("issue", "branch", "identity_fields"),
    [
        pytest.param(ISSUE, LANE_BRANCH, {"issue": ISSUE, "lane": None}, id="issue"),
        pytest.param(None, LANE_MODE_BRANCH, {"issue": None, "lane": True}, id="lane"),
    ],
)
def test_claim_json_prints_the_acquired_claim_object(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    issue: int | None,
    branch: str,
    identity_fields: dict[str, object],
) -> None:
    """Spec: CLAIM-69, CLM-16, CLM-19, OUT-01, OUT-02."""
    standpoint = stand_in(branch=branch)
    serve_item(monkeypatch, JSON_SCOPE)

    status = claim(
        "--role",
        "builder",
        "--claim-id",
        "cli-claim",
        "--json",
        scope=JSON_SCOPE,
        issue=issue,
    )

    assert status == 0
    assert capsys.readouterr().out == (
        json.dumps(
            {
                "ok": True,
                "reason": "claimed",
                **identity_fields,
                "claim_id": "cli-claim",
                "agent": "Codex Sol",
                "role": "builder",
                "base": standpoint.head,
                "branch": branch,
                "scope": ["docs/guide.md", "src/widget.py"],
                "resource": None,
                "resource_value": None,
                "versioned_files": 2,
                "versioned_files_total": 5,
                "share": 0.4,
                "touches": [],
                "checks": [],
            }
        )
        + "\n"
    )


def test_claim_json_conflict_prints_the_error_object_and_changes_no_claim(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: CLM-25, OUT-01, OUT-03."""
    standpoint = stand_in(standing=(Standing(("src",), issue=ISSUE),))
    serve_item(monkeypatch, ("docs",))
    held_before = standing_claims(standpoint)

    status = claim("--role", "builder", "--json", scope=("docs",), agent="Grok 4.6")

    captured = capsys.readouterr()
    assert status == 2
    assert_json_refusal_object(captured.err, captured.out, reason="claim_conflict")
    assert standing_claims(standpoint) == held_before


def test_claim_json_reports_unavailable_when_the_state_ref_cannot_be_written(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: CLM-27, OUT-01, OUT-03."""
    standpoint = stand_in()
    serve_item(monkeypatch, ("docs",))
    (bare_remote / f"{store.STATE_REF}.lock").write_text("")

    status = claim("--role", "builder", "--json", scope=("docs",), agent="Grok 4.6")

    captured = capsys.readouterr()
    assert status == 2
    assert_json_refusal_object(captured.err, captured.out, reason="unavailable")
    assert not standing_claims(standpoint)
