"""What a `--scope` path may be for `aco claim`, on real temporary git
worktrees and the real state ref: the lane claim that names no scope or a
path with a display control, the comma a path may hold, and the comma value
that matches no versioned file. The forge is the only fake."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from board_fixtures import complete_contract
from claim_worktrees import (
    ISSUE,
    LANE_MODE_BRANCH,
    StandIn,
    Standing,
    claim,
    make_stand_in,
    serve_body,
    standing_claims,
)
from cli_fixtures import forbid_forge_resolution

from aco import cli as issue_claim
from aco import protocol

TRUNK_FILES = ("src/widget.py", "docs/PRODUCT.md")
COMMA_PATH = "docs/report,v2.md"
JOINED_PATH = "docs/PRODUCT.md,src/widget.py"
SEPARATE_PATHS = ("docs/PRODUCT.md", "src/widget.py")
HELD_BY_OTHER_ISSUE = 73
HELD_BRANCH = "claude/issue-73-held"
LANE_SCOPE_REQUIRED = "lane claim requires --scope; a lane names no item to derive it from"
UNMATCHED_COMMA_REFUSAL = (
    "'a.py,b.py' matches no versioned file; one --scope path per flag, so its comma is read "
    "literally -- repeat --scope for a second path"
)


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


@pytest.mark.parametrize(
    ("scope_arguments", "refusal"),
    [
        pytest.param([], LANE_SCOPE_REQUIRED, id="no-scope"),
        *(
            pytest.param(
                ["--scope", scope_path], protocol.SCOPE_ENTRIES_MUST_BE_CANONICAL, id=control_id
            )
            for scope_path, control_id in (
                ("docs/a\N{RIGHT-TO-LEFT OVERRIDE}b.md", "RLO"),
                ("docs/a\N{LEFT-TO-RIGHT ISOLATE}b.md", "LRI"),
                ("docs/a\N{ZERO WIDTH SPACE}b.md", "ZWSP"),
                ("docs/\x9b2J.md", "C1-CSI"),
                ("docs/a\tb.md", "TAB"),
            )
        ),
    ],
)
def test_a_lane_claim_refuses_a_missing_or_display_control_scope_by_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    clone: Path,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
    scope_arguments: list[str],
    refusal: str,
) -> None:
    """Spec: CLM-06, CLAIM-20, NEXT-37. Lane mode has no item to derive a
    scope from, and a path holding a display control or a TAB refuses with the
    scope grammar's own sentence; both before any write, forge-free."""
    place = make_stand_in(monkeypatch, tmp_path, clone, bare_remote, TRUNK_FILES)
    standpoint = place(branch=LANE_MODE_BRANCH)
    forbid_forge_resolution(monkeypatch)

    status = issue_claim.main(["claim", "--role", "builder", *scope_arguments])

    assert status == 2
    assert capsys.readouterr().err == f"ERROR: {refusal}\n"
    assert not standing_claims(standpoint)


@dataclass(frozen=True)
class CommaCase:
    item_scope: tuple[str, ...]
    held_scope: tuple[str, ...]
    trunk: tuple[str, ...]
    cost_line: str


ONE_OF_FOUR = "1 of 4 versioned files (25%); overlaps no other open claims"
TWO_OF_FOUR = "2 of 4 versioned files (50%); overlaps no other open claims"
COMMA_CASES = [
    pytest.param(
        CommaCase((COMMA_PATH,), ("docs/report",), (COMMA_PATH,), ONE_OF_FOUR),
        id="a-comma-path-is-one-path",
    ),
    pytest.param(
        CommaCase((JOINED_PATH,), SEPARATE_PATHS, (JOINED_PATH,), ONE_OF_FOUR),
        id="a-joined-value-is-one-path-beside-the-two-separate-paths",
    ),
    pytest.param(
        CommaCase(SEPARATE_PATHS, (JOINED_PATH,), (JOINED_PATH,), TWO_OF_FOUR),
        id="repeated-flags-are-two-paths-beside-the-joined-value",
    ),
]


@pytest.mark.parametrize("case", COMMA_CASES)
def test_one_scope_value_is_one_path_comma_and_all(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    case: CommaCase,
) -> None:
    """Spec: CLAIM-18, CLAIM-32. A comma inside one `--scope` value stays in
    the path, so it overlaps nothing the comma would have split it into, and
    repeating the flag is the only way to claim a second path."""
    standpoint = stand_in(
        standing=(Standing(case.held_scope, issue=HELD_BY_OTHER_ISSUE, branch=HELD_BRANCH),),
        more_trunk_files=case.trunk,
    )
    serve_body(monkeypatch, complete_contract("Ship it.", scope=list(case.item_scope)))

    status = claim("--claim-id", "comma", scope=case.item_scope)

    assert status == 0
    assert capsys.readouterr().out == f"CLAIMED issue #{ISSUE}: comma\n{case.cost_line}\n"
    assert {held.scope for held in standing_claims(standpoint)} == {
        case.held_scope,
        case.item_scope,
    }


@pytest.mark.parametrize(
    ("scope", "status", "stderr", "claimed_scopes"),
    [
        pytest.param(
            "a.py,b.py",
            2,
            f"ERROR: {UNMATCHED_COMMA_REFUSAL}\n",
            [],
            id="a-comma-matching-nothing-is-refused-before-any-write",
        ),
        pytest.param(
            "src/not-created-yet.py",
            0,
            "",
            [("src/not-created-yet.py",)],
            id="a-comma-free-path-git-never-heard-of-still-claims",
        ),
    ],
)
def test_only_a_comma_scope_that_matches_nothing_in_the_checkout_refuses(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    scope: str,
    status: int,
    stderr: str,
    claimed_scopes: list[tuple[str, ...]],
) -> None:
    """Spec: CLAIM-18, CLAIM-24. A lane routinely claims files it is about to
    create; a comma value that grounds nothing guards nothing and refuses."""
    standpoint = stand_in()
    serve_body(monkeypatch, complete_contract("Ship it.", scope=[scope]))

    observed = claim(scope=(scope,))

    assert (observed, capsys.readouterr().err) == (status, stderr)
    assert [held.scope for held in standing_claims(standpoint)] == claimed_scopes
