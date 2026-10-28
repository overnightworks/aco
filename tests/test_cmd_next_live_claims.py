"""How `aco next` reads the claims live on the state ref: an item under claim is not pulled,
and a claim's scope is occupied for the parallel walk. The forge is the only fake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from board_fixtures import board_issue, complete_contract
from cli_fixtures import freeze_cli_now, run_cli
from github_fixtures import FakeForge, assert_github_world, serve_forge
from store_fixtures import claim_intent, publish_claims_from_a_second_clone

from aco import protocol, workboard


@pytest.fixture(autouse=True)
def github_world(monkeypatch: pytest.MonkeyPatch, github_clone: Path, bare_remote: Path) -> None:
    assert_github_world(github_clone, bare_remote)
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


def parallel_items() -> tuple[workboard.Issue, ...]:
    return (
        board_issue(
            50, "Alpha", complete_contract("Ship Alpha.", scope=["src/alpha1.py", "src/alpha2.py"])
        ),
        board_issue(51, "Beta", complete_contract("Ship Beta.", scope=["src/shared.py"])),
        board_issue(52, "Gamma", complete_contract("Ship Gamma.", scope=["src/shared.py"])),
        board_issue(53, "Delta", complete_contract("Ship Delta.")),
        board_issue(
            54, "Epsilon", complete_contract("Ship Epsilon.", scope=["claimed/deep/file.py"])
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


def test_next_places_only_the_free_items_disjoint_from_the_first_action_and_every_live_claim(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: NEXT-09, NEXT-15, NEXT-17, NEXT-21, NEXT-22."""
    serve_board(
        monkeypatch,
        github_clone,
        bare_remote,
        parallel_items(),
        claim_of(990, ("claimed",)),
        claim_of(991, ("claimed/two.py",)),
    )

    text = run_cli(["next"], capsys)
    as_json = run_cli(["next", "--json"], capsys)

    assert (text.status, text.stdout) == (
        0,
        "#50 score -10: Alpha\nNext: Ship Alpha.\n"
        "Run: aco start 50 --slug=alpha\n"
        "parallel: #51 (1 path)\nscope unknown: #53\nclose: none\n",
    )
    assert (as_json.status, json.loads(as_json.stdout)) == (
        0,
        {
            "ok": True,
            "reason": "work_item",
            "number": 50,
            "score": -10,
            "title": "Alpha",
            "next": "Ship Alpha.",
            "command": "aco start 50 --slug=alpha",
            "recovery": [],
            "skipped": [],
            "ruling_landings": None,
            "ruling_old": None,
            "parallel": {
                "first_scope_unknown": False,
                "candidates": [{"number": 51, "scope": ["src/shared.py"]}],
                "scope_unknown": [53],
            },
            "close": [],
            "waiting_on_operator": [],
            "ideas": [],
            "with_head": [],
        },
    )
