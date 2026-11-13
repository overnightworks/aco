"""How `aco next` reads the claims live on the state ref: an item under claim is not pulled,
and a claim's scope is occupied for the parallel walk. The forge is the only fake."""

import json
from pathlib import Path

import pytest
from board_fixtures import board_issue, complete_contract
from cli_fixtures import freeze_cli_now, run_cli
from github_fixtures import FakeForge, serve_forge
from store_fixtures import claim_intent, publish_claims_from_a_second_clone

from aco import protocol, workboard


@pytest.fixture(autouse=True)
def _freeze_clock(monkeypatch: pytest.MonkeyPatch, github_world: Path) -> None:
    freeze_cli_now(monkeypatch)


def claim_of(issue: int, scope: tuple[str, ...]) -> protocol.ClaimIntent:
    return claim_intent(
        identity=protocol.IssueIdentity(issue),
        claim_id=f"claim-{issue}",
        operation_id=f"op-{issue}",
        branch=f"codex/issue-{issue}-work",
        scope=scope,
    )


def serve_board(
    monkeypatch: pytest.MonkeyPatch,
    github_clone: Path,
    bare_remote: Path,
    issues: tuple[workboard.Issue, ...],
    *claims: protocol.ClaimIntent,
) -> None:
    serve_forge(monkeypatch, FakeForge(board_issues=issues))
    publish_claims_from_a_second_clone(github_clone, bare_remote, claims)


def lane_claim_of(branch: str, scope: tuple[str, ...]) -> protocol.ClaimIntent:
    return claim_intent(
        identity=protocol.LaneIdentity(),
        claim_id="claim-lane",
        operation_id="op-lane",
        branch=branch,
        scope=scope,
    )


def overlap_json(
    *,
    issue: int | None = None,
    lane: str | None = None,
    claim_id: str | None = None,
    paths: tuple[str, ...],
) -> dict[str, object]:
    return {"issue": issue, "lane": lane, "claim_id": claim_id, "paths": list(paths)}


def parallel_items() -> tuple[workboard.Issue, ...]:
    return (
        board_issue(
            50, "Alpha", complete_contract("Ship Alpha.", scope=["src/alpha1.py", "src/alpha2.py"])
        ),
        board_issue(51, "Beta", complete_contract("Ship Beta.", scope=["src/shared.py"])),
        board_issue(52, "Gamma", complete_contract("Ship Gamma.", scope=["src/shared.py"])),
        board_issue(53, "Delta", complete_contract("Ship Delta.")),
        board_issue(
            54,
            "Epsilon",
            complete_contract(
                "Ship Epsilon.",
                scope=[
                    "claimed/deep/file.py",
                    "claimed/b.py",
                    "claimed/c.py",
                    "claimed/d.py",
                    "src/alpha1.py",
                ],
            ),
        ),
    )


def test_next_names_an_item_under_a_live_claim_as_claimed_and_pulls_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: NEXT-01, NEXT-08."""
    item = board_issue(10, "Claimed", complete_contract("Claim #10."))
    serve_board(monkeypatch, github_clone, bare_remote, (item,), claim_of(10, ("a.py",)))

    result = run_cli(["next"], capsys)

    assert (result.status, result.stdout) == (
        3,
        "No actionable item.\nparallel: none\nscope unknown: none\nclose: none\n"
        "\nSKIPPED\n#10: claimed\n",
    )


def test_next_places_every_free_item_with_a_scope_and_notes_each_overlap_it_meets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: NEXT-09, NEXT-15, NEXT-17, NEXT-21, NEXT-22, NEXT-56..NEXT-58."""
    serve_board(
        monkeypatch,
        github_clone,
        bare_remote,
        parallel_items(),
        claim_of(990, ("claimed",)),
        claim_of(991, ("claimed/two.py",)),
        lane_claim_of("codex/lane-x", ("src/shared.py",)),
    )

    text = run_cli(["next"], capsys)
    as_json = run_cli(["next", "--json"], capsys)

    assert (text.status, text.stdout) == (
        0,
        "#50 score -10: Alpha\nNext: Ship Alpha.\n"
        "Run: aco start 50 --slug=alpha\n"
        "parallel: #51 (1 path; overlaps lane codex/lane-x on src/shared.py), "
        "#52 (1 path; overlaps lane codex/lane-x on src/shared.py, issue #51 on src/shared.py), "
        "#54 (5 paths; overlaps issue #990 on claimed/b.py, claimed/c.py, claimed/d.py, "
        "and 1 more, issue #50 on src/alpha1.py)\n"
        "scope unknown: #53\nclose: none\n",
    )
    parallel = json.loads(as_json.stdout)["parallel"]
    assert (as_json.status, parallel["scope_unknown"]) == (0, [53])
    assert [
        (candidate["number"], candidate["overlaps"]) for candidate in parallel["candidates"]
    ] == [
        (51, [overlap_json(lane="codex/lane-x", claim_id="claim-lane", paths=("src/shared.py",))]),
        (
            52,
            [
                overlap_json(lane="codex/lane-x", claim_id="claim-lane", paths=("src/shared.py",)),
                overlap_json(issue=51, paths=("src/shared.py",)),
            ],
        ),
        (
            54,
            [
                overlap_json(
                    issue=990,
                    claim_id="claim-990",
                    paths=("claimed/b.py", "claimed/c.py", "claimed/d.py", "claimed/deep/file.py"),
                ),
                overlap_json(issue=50, paths=("src/alpha1.py",)),
            ],
        ),
    ]
