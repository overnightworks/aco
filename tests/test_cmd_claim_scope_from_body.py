"""The scope `aco claim` takes from the item's own body, on real temporary git
worktrees and the real state ref: what an omitted `--scope` derives, what a
differing one refuses, what the claimed line costs, and the refusals that name
a malformed body, a missing target and a forge outage. The forge is the only
fake."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body, complete_contract
from claim_worktrees import (
    ISSUE,
    StandIn,
    assert_json_refusal_object,
    claim,
    claimed_here,
    make_stand_in,
    serve_body,
    standing_claims,
)

from aco import forge

TRUNK_FILES = ("src/widget.py", "src/other.py", "tests/test_widget.py")
CLAIM_ID = "cli-claim"
WIDE_SCOPE = ("a.py", "b.py", "c.py", "d.py")
WIDE_REFUSAL = "scope is wide: 4 paths exceeds three; pass --whole REASON or set whole in the body"


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


@dataclass(frozen=True)
class DerivationCase:
    item_scope: tuple[str, ...] | None
    requested_scope: tuple[str, ...]
    status: int
    refusal: str | None = None
    claimed_scope: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    trunk: tuple[str, ...] = ()
    cost: tuple[int, int, float] | None = None


DERIVATIONS = [
    pytest.param(
        DerivationCase(
            ("src/work.py",),
            (),
            0,
            claimed_scope=("src/work.py",),
            trunk=("src/work.py",),
            cost=(1, 5, 1 / 5),
        ),
        id="omitted-takes-the-items-own-scope",
    ),
    pytest.param(
        DerivationCase(None, (), 2, refusal="item names no scope; pass --scope"),
        id="omitted-with-no-body-scope-refuses-by-name",
    ),
    pytest.param(
        DerivationCase(
            ("src/work.py",),
            ("src/other.py",),
            2,
            refusal="claim scope differs from the item's scope; correct the item first",
        ),
        id="a-differing-explicit-scope-refuses-by-name",
    ),
    pytest.param(
        DerivationCase(
            ("a.py", "b.py"),
            ("b.py", "a.py"),
            0,
            claimed_scope=("a.py", "b.py"),
            trunk=("a.py", "b.py"),
            cost=(2, 6, 2 / 6),
        ),
        id="the-same-set-in-a-different-order-is-accepted",
    ),
    pytest.param(
        DerivationCase(WIDE_SCOPE, (), 2, refusal=WIDE_REFUSAL),
        id="a-derived-wide-scope-refuses-without-whole",
    ),
    pytest.param(
        DerivationCase(
            WIDE_SCOPE,
            (),
            0,
            claimed_scope=WIDE_SCOPE,
            flags=("--whole", "spans the whole review pass"),
            trunk=WIDE_SCOPE,
            cost=(4, 8, 4 / 8),
        ),
        id="a-derived-wide-scope-is-accepted-with-whole",
    ),
    pytest.param(
        DerivationCase(
            ("docs/report,v2.md",),
            (),
            0,
            claimed_scope=("docs/report,v2.md",),
            trunk=("docs/report,v2.md",),
            cost=(1, 5, 1 / 5),
        ),
        id="a-comma-inside-a-derived-path-grounds-and-is-kept-whole",
    ),
    pytest.param(
        DerivationCase(
            ("a.py,b.py",),
            (),
            2,
            refusal="'a.py,b.py' matches no versioned file; one --scope path per flag, so "
            "its comma is read literally -- repeat --scope for a second path",
        ),
        id="a-comma-inside-a-derived-path-that-grounds-nothing-refuses-by-name",
    ),
]


@pytest.mark.parametrize(
    "requested_scope",
    [pytest.param(("src/widget.py",), id="explicit"), pytest.param((), id="derived")],
)
def test_the_claimed_line_prints_identically_for_an_explicit_and_a_derived_scope(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    requested_scope: tuple[str, ...],
) -> None:
    """Spec: CLAIM-53. The board fetch a derived scope costs is never a
    silent, unprinted detour."""
    stand_in()
    serve_body(monkeypatch, complete_contract("Ship it.", scope=["src/widget.py"]))

    status = claim("--claim-id", CLAIM_ID, scope=requested_scope)

    assert status == 0
    assert capsys.readouterr().out == (
        f"CLAIMED issue #{ISSUE}: {CLAIM_ID}\n"
        "1 of 4 versioned files (25%); overlaps no other open claims\n"
    )


@pytest.mark.parametrize("case", DERIVATIONS)
def test_scope_derivation_against_the_items_own_body(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    case: DerivationCase,
) -> None:
    """Spec: CLAIM-53, CLAIM-54, CLAIM-55, CLAIM-67, CLM-22. An omitted
    `--scope` takes the item's, a differing one refuses by name and the same
    set in another order is accepted. A derived scope is as wide, by the same
    rule, as one passed on `--scope`, and a comma inside a derived path is
    grounded like one on `--scope`. Every row reads the open board exactly
    once and never the single-item lookup."""
    standpoint = stand_in(more_trunk_files=case.trunk)
    body = (
        complete_contract("Ship it.")
        if case.item_scope is None
        else complete_contract("Ship it.", scope=list(case.item_scope))
    )
    served = serve_body(monkeypatch, body)
    board_reads: list[None] = []
    list_board = served.list_open_board_issues

    def counted_board_read() -> tuple[object, ...]:
        board_reads.append(None)
        return list_board()

    monkeypatch.setattr(served, "list_open_board_issues", counted_board_read)

    status = claim(*case.flags, "--json", scope=case.requested_scope)

    captured = capsys.readouterr()
    assert (status, len(board_reads), served.issue_reference_lookups) == (case.status, 1, [])
    if case.refusal is not None:
        assert captured.err == f"ERROR: {case.refusal}\n"
        assert standing_claims(standpoint) == []
        return
    payload = json.loads(captured.out)
    assert payload["scope"] == list(case.claimed_scope)
    assert list(claimed_here(standpoint).scope) == list(case.claimed_scope)
    cost = (payload["versioned_files"], payload["versioned_files_total"], payload["share"])
    assert cost == case.cost


@pytest.mark.parametrize(
    ("arrange", "reason", "sentence"),
    [
        pytest.param(
            "malformed",
            "body_invalid",
            "#72 body malformed: owner: unknown top-level key owner",
            id="a-malformed-body",
        ),
        pytest.param("missing", "target_invalid", "#72 does not exist", id="a-missing-target"),
        pytest.param("outage", "unavailable", None, id="a-forge-outage"),
    ],
)
def test_claim_without_scope_refuses_a_malformed_body_a_missing_target_and_an_outage_by_name(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    arrange: str,
    reason: str,
    sentence: str | None,
) -> None:
    """Spec: CLAIM-68, CLM-24, CLM-27. A malformed `aco` block is named before
    the less specific "item names no scope", a target missing from the open
    board refuses `target_invalid`, and a forge outage while deriving the
    scope is `unavailable`, never `target_invalid`."""
    standpoint = stand_in()
    served = serve_body(monkeypatch, block_body(f'{MINIMAL_BLOCK_TOML}owner = "someone"\n'))
    if arrange != "malformed":
        served.board_issues = ()
    if arrange == "missing":
        served.issue_references[ISSUE] = forge.ItemReference(forge.ItemState.MISSING, "", "")
    if arrange == "outage":

        def unreachable(number: int) -> forge.ItemReference:
            raise forge.ForgeTransientError("gh: connection reset")

        monkeypatch.setattr(served, "item_reference", unreachable)

    status = claim("--json", scope=())

    captured = capsys.readouterr()
    assert status == 2
    if sentence is not None:
        assert captured.err == f"ERROR: {sentence}\n"
    assert_json_refusal_object(captured.err, captured.out, reason=reason)
    assert standing_claims(standpoint) == []
