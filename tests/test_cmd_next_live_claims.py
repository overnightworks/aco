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
            complete_contract("Ship Epsilon.", scope=["claimed/deep/file.py", "src/alpha1.py"]),
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
        "#54 (2 paths; overlaps issue #990 on claimed/deep/file.py, issue #50 on src/alpha1.py)\n"
        "scope unknown: #53\nclose: none\n",
    )
    assert (as_json.status, json.loads(as_json.stdout)["parallel"]) == (
        0,
        {
            "first_scope_unknown": False,
            "candidates": [
                {
                    "number": 51,
                    "scope": ["src/shared.py"],
                    "overlaps": [
                        {
                            "issue": None,
                            "lane": "codex/lane-x",
                            "claim_id": "claim-lane",
                            "paths": ["src/shared.py"],
                        }
                    ],
                },
                {
                    "number": 52,
                    "scope": ["src/shared.py"],
                    "overlaps": [
                        {
                            "issue": None,
                            "lane": "codex/lane-x",
                            "claim_id": "claim-lane",
                            "paths": ["src/shared.py"],
                        },
                        {
                            "issue": 51,
                            "lane": None,
                            "claim_id": None,
                            "paths": ["src/shared.py"],
                        },
                    ],
                },
                {
                    "number": 54,
                    "scope": ["claimed/deep/file.py", "src/alpha1.py"],
                    "overlaps": [
                        {
                            "issue": 990,
                            "lane": None,
                            "claim_id": "claim-990",
                            "paths": ["claimed/deep/file.py"],
                        },
                        {
                            "issue": 50,
                            "lane": None,
                            "claim_id": None,
                            "paths": ["src/alpha1.py"],
                        },
                    ],
                },
            ],
            "scope_unknown": [53],
        },
    )


def test_next_carries_an_empty_overlaps_list_for_an_item_meeting_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: NEXT-15, NEXT-58."""
    serve_board(
        monkeypatch,
        github_clone,
        bare_remote,
        parallel_items(),
        claim_of(990, ("elsewhere",)),
    )

    text = run_cli(["next"], capsys)
    as_json = run_cli(["next", "--json"], capsys)

    candidates = json.loads(as_json.stdout)["parallel"]["candidates"]
    assert (
        text.stdout.splitlines()[3],
        [(candidate["number"], len(candidate["overlaps"])) for candidate in candidates],
        candidates[0]["overlaps"],
    ) == (
        "parallel: #51 (1 path), #52 (1 path; overlaps issue #51 on src/shared.py), "
        "#54 (2 paths; overlaps issue #50 on src/alpha1.py)",
        [(51, 0), (52, 1), (54, 1)],
        [],
    )
