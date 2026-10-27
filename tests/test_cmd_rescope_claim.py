"""The live claim `aco rescope` selects and changes, on real temporary git
worktrees and the real state ref: whose claim it is, how `--add` and `--drop`
combine with its scope, what it reports, and the checkout and state-ref
refusals that come before any write. The forge is the only fake."""

from __future__ import annotations

import json
from dataclasses import dataclass
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
    make_stand_in,
    serve_body,
)
from cli_fixtures import real_git, run_cli
from store_fixtures import state_ref_tip

from aco import protocol, store

TRUNK_FILES = ("src/widget.py",)
HELD_SCOPE = ("src/widget.py",)
NEW_FILE = "src/new.py"


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


def rescope(*flags: str) -> list[str]:
    return ["--repo", REPOSITORY, "rescope", str(ISSUE), *flags]


def held_by_ada(scope: tuple[str, ...] = HELD_SCOPE) -> tuple[Standing, ...]:
    return (Standing(scope, issue=ISSUE, agent="Ada", branch=LANE_BRANCH),)


def test_a_rescope_adds_a_path_whatever_the_head_and_the_working_tree_stand_at(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: RESC-12. A rescope never reads the checkout's head
    against the claim's base, and never refuses a dirty working tree."""
    standpoint = stand_in(standing=held_by_ada())
    serve_body(monkeypatch, complete_contract("Build it."))
    (standpoint.directory / "src/widget.py").write_text("edited, not committed\n")
    before = claimed_here(standpoint)
    assert before.base != standpoint.head

    result = run_cli(rescope("--add", f"{standpoint.directory}/{NEW_FILE}"), capsys)

    assert (result.status, result.stdout, result.stderr) == (
        0,
        f"RESCOPED issue #72: {before.claim_id}\n",
        "",
    )
    after = claimed_here(standpoint)
    assert (after.claim_id, after.base, after.scope) == (
        before.claim_id,
        before.base,
        (NEW_FILE, "src/widget.py"),
    )


@dataclass(frozen=True)
class CommaRescope:
    """`--add` and `--drop` share `--scope`'s rule (one occurrence is one path,
    comma and all): the scope the claim holds, the files the trunk versions,
    the flags after `rescope 72` (`{root}` is the worktree), and what the run
    then refuses with, if it does, and the scope the claim holds."""

    held_scope: tuple[str, ...]
    trunk_files: tuple[str, ...]
    flags: tuple[str, ...]
    refusal: str | None
    scope: tuple[str, ...]


COMMA_RESCOPES = {
    "add-keeps-a-comma-inside-one-path": CommaRescope(
        ("src/widget.py",),
        ("reports/a,b.md",),
        ("--add", "{root}/reports/a,b.md"),
        None,
        ("reports/a,b.md", "src/widget.py"),
    ),
    # A split drops `reports/a`, which the claim keeps, and `b.md`, which it does not hold.
    "drop-matches-a-comma-path-as-one-whole-path": CommaRescope(
        ("reports/a", "reports/a,b.md"),
        ("reports/a", "reports/a,b.md"),
        ("--drop", "{root}/reports/a,b.md"),
        None,
        ("reports/a",),
    ),
    # `--add` is no way around the refusal `claim` applies.
    "add-refuses-a-comma-scope-matching-nothing-in-the-checkout": CommaRescope(
        ("src/widget.py",),
        ("a.py", "b.py"),
        ("--add", "{root}/a.py,b.py"),
        "'a.py,b.py' matches no versioned file; one --add path per flag, so its comma "
        "is read literally -- repeat --add for a second path",
        ("src/widget.py",),
    ),
    # The claim's own reason is truer here than the checkout's.
    "drop-of-a-value-not-in-scope-names-the-claim": CommaRescope(
        ("src/widget.py",),
        ("a.py", "b.py"),
        ("--drop", "{root}/a.py,b.py"),
        "cannot drop 'a.py,b.py'; it is not in this claim's scope",
        ("src/widget.py",),
    ),
    # A value the claim already holds is a fact about the claim, not a typo about the checkout.
    "drop-removes-a-held-comma-entry-no-file-matches": CommaRescope(
        ("a.py,b.py",),
        ("a.py", "b.py"),
        ("--drop", "{root}/a.py,b.py", "--add", "{root}/a.py", "--add", "{root}/b.py"),
        None,
        ("a.py", "b.py"),
    ),
}


@pytest.mark.parametrize("case", COMMA_RESCOPES.values(), ids=COMMA_RESCOPES.keys())
def test_a_rescope_reads_a_comma_inside_one_path_literally(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    case: CommaRescope,
) -> None:
    """Spec: RESC-06, RESC-07, RESC-12. One occurrence of a flag is one path."""
    standpoint = stand_in(standing=held_by_ada(case.held_scope), more_trunk_files=case.trunk_files)
    serve_body(monkeypatch, complete_contract("Build it."))
    before = claimed_here(standpoint)
    flags = tuple(part.replace("{root}", str(standpoint.directory)) for part in case.flags)

    result = run_cli(rescope(*flags), capsys)

    expected = (
        (0, f"RESCOPED issue #72: {before.claim_id}\n", "")
        if case.refusal is None
        else (2, "", f"ERROR: {case.refusal}\n")
    )
    assert (result.status, result.stdout, result.stderr) == expected
    assert claimed_here(standpoint).scope == case.scope


def test_a_rescope_with_json_prints_the_updated_scope_and_the_same_claim_id(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: RESC-13. The envelope keeps the claim's own fields in
    their order, and only `scope` differs from what the claim held."""
    standpoint = stand_in(standing=held_by_ada())
    serve_body(monkeypatch, complete_contract("Build it."))
    before = claimed_here(standpoint)
    root = standpoint.directory
    flags = ("--add", f"{root}/docs/PRODUCT.md", "--add", f"{root}/{NEW_FILE}")

    result = run_cli(rescope(*flags, "--drop", f"{root}/src/widget.py", "--json"), capsys)

    assert result.status == 0
    assert (
        result.stdout
        == json.dumps(
            {
                "ok": True,
                "reason": "rescoped",
                "issue": ISSUE,
                "lane": None,
                "claim_id": before.claim_id,
                "agent": before.agent,
                "role": before.role,
                "base": before.base,
                "branch": before.branch,
                "scope": ["docs/PRODUCT.md", NEW_FILE],
            }
        )
        + "\n"
    )


def test_a_rescope_by_another_agent_than_the_claimant_refuses_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: CLAIM-37, RESC-16."""
    standpoint = stand_in(standing=held_by_ada(("src",)))
    served = serve_body(monkeypatch, complete_contract("Build it."))
    tip = state_ref_tip(bare_remote)

    result = run_cli(rescope("--agent", "Grok 4.6", "--add", NEW_FILE), capsys)

    assert (result.status, result.stdout, result.stderr) == (
        2,
        "",
        "ERROR: only the original claimant may rescope "
        "(holder='Ada (builder)', this session='Grok 4.6 (builder)')\n",
    )
    assert state_ref_tip(bare_remote) == tip
    assert claimed_here(standpoint).scope == ("src",)
    assert_no_item_body_written(served)


def test_a_rescope_with_json_and_no_claim_on_the_item_refuses_as_a_failed_precondition(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: RESC-14, RESC-16. No live claim reports `precondition_failed`, not
    the `unavailable` every checkout- or store-level refusal falls to."""
    stand_in()
    served = serve_body(monkeypatch, complete_contract("Build it."))
    tip = state_ref_tip(bare_remote)

    result = run_cli(rescope("--add", NEW_FILE, "--json"), capsys)

    assert result.status == 2
    assert result.stderr == "ERROR: issue #72 has no active build claim\n"
    assert_json_refusal_object(result.stderr, result.stdout, reason="precondition_failed")
    assert state_ref_tip(bare_remote) == tip
    assert_no_item_body_written(served)


def test_a_rescope_that_names_neither_add_nor_drop_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: RESC-08."""
    standpoint = stand_in(standing=held_by_ada())
    served = serve_body(monkeypatch, complete_contract("Build it."))
    tip = state_ref_tip(bare_remote)

    result = run_cli(rescope(), capsys)

    assert (result.status, result.stdout, result.stderr) == (
        2,
        "",
        "ERROR: rescope does not change the claim scope\n",
    )
    assert state_ref_tip(bare_remote) == tip
    assert claimed_here(standpoint).scope == HELD_SCOPE
    assert_no_item_body_written(served)


def test_a_rescope_in_a_checkout_without_a_branch_refuses_even_with_an_issue_number(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: RESC-02. Rescope always operates on the checked-out worktree's own
    claim, so a detached checkout refuses -- unlike release, it never falls
    back to the issue alone."""
    standpoint = stand_in(standing=held_by_ada())
    served = serve_body(monkeypatch, complete_contract("Build it."))
    real_git(standpoint.directory, "switch", "--detach")
    tip = state_ref_tip(bare_remote)

    result = run_cli(rescope("--add", NEW_FILE), capsys)

    assert (result.status, result.stdout, result.stderr) == (
        2,
        "",
        "ERROR: rescope requires a non-empty current branch; "
        "check out the claim branch, or pass an issue number\n",
    )
    assert state_ref_tip(bare_remote) == tip
    assert_no_item_body_written(served)


def test_a_rescope_refuses_a_missing_state_ref(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: CAS-03."""
    stand_in()
    served = serve_body(monkeypatch, complete_contract("Build it."))
    real_git(bare_remote, "update-ref", "-d", store.STATE_REF)

    result = run_cli(rescope("--add", NEW_FILE), capsys)

    assert (result.status, result.stdout, result.stderr) == (
        2,
        "",
        f"ERROR: {protocol.MISSING_STATE_REF}\n",
    )
    assert state_ref_tip(bare_remote) is None
    assert_no_item_body_written(served)
