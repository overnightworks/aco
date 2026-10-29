"""`aco claim` beside a higher-ranked item or an open blocker, on real temporary
git worktrees and the real state ref: the out-of-order refusal and its
downgrade, the items that do not rank, and the replay that skips the check.
The forge is the only fake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from board_fixtures import (
    FROZEN_UNTIL,
    block_dependency,
    blocked_issue,
    board_issue,
    complete_contract,
)
from claim_worktrees import StandIn, Standpoint, claim, make_stand_in, standing_claims
from github_fixtures import FakeForge, serve_forge
from option_cards import open_option_entry

from aco import forge, protocol, workboard

TRUNK_FILES = ("src/work.py",)
CLAIMED_SCOPE = ("src/work.py",)
TOP_SCOPE = ["src/top.py"]
HIGHER_PRIORITY = "ERROR: higher-priority actionable item #11"
OUT_OF_ORDER_REASON = "Urgent customer incident."


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


def lane_branch(issue: int) -> str:
    return f"codex/issue-{issue}-out-of-order"


def claimable(number: int, title: str) -> workboard.Issue:
    """An item whose body scope is the one `claim` passes."""
    return board_issue(
        number, title, complete_contract(f"Claim #{number}.", scope=list(CLAIMED_SCOPE))
    )


def top_item(title: str = "Top work") -> workboard.Issue:
    return board_issue(11, title, complete_contract("Claim #11.", scope=TOP_SCOPE))


def serve_board(
    monkeypatch: pytest.MonkeyPatch,
    issues: tuple[workboard.Issue, ...],
    *,
    dependencies: dict[int, tuple[workboard.IssueDependency, ...]] | None = None,
    pull_requests: tuple[workboard.PullRequest, ...] = (),
) -> FakeForge:
    """The forge serving `issues` open, as the board lists them and as item references."""
    served = FakeForge(
        board_issues=issues,
        board_dependencies=dependencies or {},
        board_open_pull_requests=pull_requests,
    )
    for issue in issues:
        served.issue_references[issue.number] = forge.ItemReference(
            forge.ItemState.OPEN, issue.title, issue.body
        )
    serve_forge(monkeypatch, served)
    return served


def claimed_issues(standpoint: Standpoint) -> list[protocol.ClaimIdentity]:
    return [held.identity for held in standing_claims(standpoint)]


def issues_behind_a_top_item() -> tuple[workboard.Issue, ...]:
    """#10 to claim, #11 ranked above it, #12 waiting for #11."""
    dependent, _ = blocked_issue(12, "Depends on top", block_dependency(11))
    return (claimable(10, "Lower work"), top_item(), dependent)


def dependency_of_the_dependent() -> dict[int, tuple[workboard.IssueDependency, ...]]:
    return {12: (block_dependency(11),)}


def test_claim_refuses_out_of_order_without_a_reason_before_mutating(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CLM-08."""
    standpoint = stand_in(branch=lane_branch(10))
    serve_board(monkeypatch, issues_behind_a_top_item(), dependencies=dependency_of_the_dependent())

    status = claim(scope=CLAIMED_SCOPE, issue=10)

    assert status == 2
    err = capsys.readouterr().err
    assert HIGHER_PRIORITY in err
    assert "Top work" in err
    assert "--out-of-order REASON" in err
    assert claimed_issues(standpoint) == []


def test_claim_allows_out_of_order_with_a_reason_and_records_it(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CLM-09."""
    standpoint = stand_in(branch=lane_branch(10))
    serve_board(monkeypatch, issues_behind_a_top_item(), dependencies=dependency_of_the_dependent())

    status = claim("--out-of-order", OUT_OF_ORDER_REASON, scope=CLAIMED_SCOPE, issue=10)

    assert status == 0
    output = capsys.readouterr().out
    assert "WARNING: higher-priority actionable item #11" in output
    assert claimed_issues(standpoint) == [protocol.IssueIdentity(10)]


def test_claim_refuses_when_the_higher_priority_item_needs_refining(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CLM-08."""
    standpoint = stand_in(branch=lane_branch(10))
    unruled = board_issue(
        11,
        "Needs rulings",
        complete_contract(
            "Claim #11.",
            scope=["src/needs-rulings.py"],
            expectation=[open_option_entry("Name it.")],
        ),
    )
    waiting, waiting_dependencies = blocked_issue(
        12, "Waits for rulings", block_dependency(11), next_step="Claim #12."
    )
    serve_board(
        monkeypatch,
        (claimable(10, "Ready work"), unruled, waiting),
        dependencies=waiting_dependencies,
    )

    status = claim(scope=CLAIMED_SCOPE, issue=10)

    assert status == 2
    err = capsys.readouterr().err
    assert HIGHER_PRIORITY in err
    assert "Needs rulings" in err
    assert "--out-of-order REASON" in err
    assert claimed_issues(standpoint) == []


def test_claim_refuses_for_a_higher_priority_item_even_at_a_lower_score(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CLM-08. `board`/`next` rank a labelled blocker ahead of an
    unlabelled item even when the blocker scores lower; the refusal must agree,
    or claiming the unlabelled item would silently skip past the very item
    `next` would have named."""
    standpoint = stand_in(branch=lane_branch(51))
    blocker = board_issue(
        50,
        "Prerequisite the operator prioritized",
        complete_contract("Unblock #52.", scope=["src/prerequisite.py"]),
    )
    dependent, dependent_blockers = blocked_issue(
        52, "Depends on the prerequisite", block_dependency(50), next_step="Ship it."
    )
    in_flight_unlabelled = claimable(51, "In-flight, unlabelled")
    open_pull_request = workboard.PullRequest(200, "Fixes #51", "", "branch")
    serve_board(
        monkeypatch,
        (blocker, dependent, in_flight_unlabelled),
        dependencies=dependent_blockers,
        pull_requests=(open_pull_request,),
    )

    status = claim(scope=CLAIMED_SCOPE, issue=51)

    assert status == 2
    err = capsys.readouterr().err
    assert "ERROR: higher-priority actionable item #50" in err
    assert claimed_issues(standpoint) == []


def test_claim_json_refusal_reports_out_of_order_without_mutating(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CLM-08."""
    standpoint = stand_in(branch=lane_branch(10))
    serve_board(monkeypatch, issues_behind_a_top_item(), dependencies=dependency_of_the_dependent())

    status = claim("--json", scope=CLAIMED_SCOPE, issue=10)

    assert status == 2
    payload = json.loads(capsys.readouterr().out)
    assert (payload["ok"], payload["reason"], payload["issue"]) == (
        False,
        "precondition_failed",
        10,
    )
    [check] = payload["checks"]
    assert (check["level"], check["check"], check["issue"], check["slice"]) == (
        "error",
        "out-of-order",
        11,
        None,
    )
    assert "#11" in check["text"]
    assert "Top work" in check["text"]
    assert "--out-of-order REASON" in check["text"]
    assert claimed_issues(standpoint) == []


def test_claim_allows_an_open_dependency_with_out_of_order(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CLM-10, CLM-09."""
    standpoint = stand_in(branch=lane_branch(10))
    blocker = board_issue(9, "Blocker 9", complete_contract("Claim #9."))
    blocked = board_issue(
        10,
        "Work",
        complete_contract("Claim #10.", scope=list(CLAIMED_SCOPE)),
        labels=("security",),
        blocked_by_count=1,
    )
    serve_board(monkeypatch, (blocked, blocker), dependencies={10: (block_dependency(9),)})
    reason = "Blocker #9 is stuck on review; unblocking manually."

    status = claim("--out-of-order", reason, scope=CLAIMED_SCOPE, issue=10)

    assert status == 0
    assert "WARNING: #10 is blocked by #9 (open)" in capsys.readouterr().out
    assert claimed_issues(standpoint) == [protocol.IssueIdentity(10)]


def test_claim_does_not_require_out_of_order_for_the_top_ranked_item(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CLM-08."""
    standpoint = stand_in(branch=lane_branch(10))
    serve_board(monkeypatch, (claimable(10, "Top work"), top_item("Lower work")))

    status = claim(scope=CLAIMED_SCOPE, issue=10)

    assert status == 0
    assert "WARNING: higher-priority actionable item" not in capsys.readouterr().out
    assert claimed_issues(standpoint) == [protocol.IssueIdentity(10)]


def test_claim_does_not_require_out_of_order_past_a_higher_ranked_labelled_idea(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CLM-08."""
    standpoint = stand_in(branch=lane_branch(10))
    idea = board_issue(
        11,
        "Higher-ranked idea",
        complete_contract("Build it.", scope=["src/idea.py"]),
        labels=("idea", "security"),
    )
    serve_board(monkeypatch, (claimable(10, "Regular work"), idea))

    status = claim(scope=CLAIMED_SCOPE, issue=10)

    assert status == 0
    assert "higher-priority actionable item" not in capsys.readouterr().err
    assert claimed_issues(standpoint) == [protocol.IssueIdentity(10)]


@pytest.mark.parametrize(
    "higher",
    [
        pytest.param(
            board_issue(
                11,
                "Highest scored",
                complete_contract("Claim #11.", scope=TOP_SCOPE, frozen_until=FROZEN_UNTIL),
                labels=("security",),
            ),
            id="frozen",
        ),
        pytest.param(
            board_issue(
                11,
                "Highest scored",
                complete_contract("wait for session with the operator", scope=TOP_SCOPE),
                labels=("security", workboard.NEEDS_OPERATOR_LABEL),
            ),
            id="waiting_on_the_operator",
        ),
        pytest.param(
            board_issue(
                11, "Highest scored", complete_contract("Claim #11."), labels=("security",)
            ),
            id="naming_no_scope",
        ),
    ],
)
def test_claim_does_not_warn_about_a_higher_scored_item_no_agent_can_pull(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    higher: workboard.Issue,
) -> None:
    """Spec: CLM-08, CLM-23, CLM-35."""
    standpoint = stand_in(branch=lane_branch(10))
    serve_board(monkeypatch, (higher, claimable(10, "Lower work")))

    status = claim(scope=CLAIMED_SCOPE, issue=10)

    assert status == 0
    assert "WARNING" not in capsys.readouterr().out
    assert claimed_issues(standpoint) == [protocol.IssueIdentity(10)]


def claim_while_free_then_rank_a_top_item_above(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn
) -> Standpoint:
    """Ada claims #10 when it is the only item, then #11 and its dependent
    appear on the board."""
    standpoint = stand_in(branch=lane_branch(10))
    served = serve_board(monkeypatch, (claimable(10, "Lower work"),))
    assert claim("--claim-id", "live-claim", scope=CLAIMED_SCOPE, issue=10, agent="Ada") == 0
    served.board_issues = issues_behind_a_top_item()
    served.board_dependencies = dependency_of_the_dependent()
    return standpoint


def test_cli_claim_replay_skips_out_of_order_for_the_matching_lower_priority_item(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CLM-15, CLAIM-13."""
    standpoint = claim_while_free_then_rank_a_top_item_above(monkeypatch, stand_in)
    capsys.readouterr()

    status = claim("--claim-id", "live-claim", scope=CLAIMED_SCOPE, issue=10, agent="Ada")

    assert status == 0
    assert "out-of-order" not in capsys.readouterr().out
    [held] = standing_claims(standpoint)
    assert (held.identity, held.agent, held.claim_id) == (
        protocol.IssueIdentity(10),
        "Ada",
        "live-claim",
    )


def test_cli_claim_replay_does_not_bypass_out_of_order_for_another_agent(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CLM-15, CLAIM-13."""
    standpoint = claim_while_free_then_rank_a_top_item_above(monkeypatch, stand_in)
    capsys.readouterr()

    status = claim("--claim-id", "live-claim", scope=CLAIMED_SCOPE, issue=10, agent="Grok 4.6")

    assert status == 2
    assert HIGHER_PRIORITY in capsys.readouterr().err
    [held] = standing_claims(standpoint)
    assert (held.identity, held.agent) == (protocol.IssueIdentity(10), "Ada")
