"""`aco claim` against the checkout it is made in, on real temporary git
worktrees: which base and branch an omitted or given flag binds, the sentence
each checkout that cannot be claimed in is refused with, and the line naming
the standing claims a new scope overlaps. The forge is the only fake."""

from __future__ import annotations

from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, board_issue, complete_contract
from claim_worktrees import LANE_BRANCH, StandIn, Standing, Standpoint, make_stand_in
from github_fixtures import FakeForge, serve_forge

from aco import checkout, forge, protocol, store
from aco import cli as issue_claim

ISSUE = 72
TRUNK_FILES = (
    "src/widget.py",
    "src/a.py",
    "docs/b.md",
    "tests/c.py",
    "scripts/d.py",
    "tests/adapters/test_claim_cli.py",
)
NOT_THE_HEAD = "b" * 40
WORKTREE_RECIPE = checkout.ISOLATED_WORKTREE_RECIPE
NON_MAIN_REFUSAL = (
    f"build claims require an isolated non-main worktree branch; run {WORKTREE_RECIPE}"
)


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


def serve_item(monkeypatch: pytest.MonkeyPatch, scope: tuple[str, ...]) -> None:
    body = complete_contract("Build it.", scope=list(scope), whole="The scenario claims it as one.")
    served = FakeForge(
        board_issues=(board_issue(ISSUE, "Claims", body),),
        issue_references={ISSUE: forge.ItemReference(forge.ItemState.OPEN, "Claims", body)},
    )
    serve_forge(monkeypatch, served)


def claim(*flags: str, scope: tuple[str, ...] = ("src",)) -> int:
    scope_flags = [part for path in scope for part in ("--scope", path)]
    return issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            str(ISSUE),
            "--agent",
            "Codex Sol",
            *scope_flags,
            *flags,
        ]
    )


def standing_claims(standpoint: Standpoint) -> list[protocol.ActiveClaim]:
    state = store.fetch_state(worktree=standpoint.directory, remote="origin")
    return list(state.claims.values())


def claimed_here(standpoint: Standpoint) -> protocol.ActiveClaim:
    [claimed] = [
        held
        for held in standing_claims(standpoint)
        if held.identity == protocol.IssueIdentity(ISSUE)
    ]
    return claimed


@pytest.mark.parametrize(
    ("flags", "branch"),
    [
        pytest.param((), LANE_BRANCH, id="omitted-flags-bind-to-the-checkout"),
        pytest.param(("--branch", LANE_BRANCH), LANE_BRANCH, id="given-branch"),
        pytest.param(("--base", "{head}"), LANE_BRANCH, id="given-base"),
        # `master` is no default branch beside a recorded `main`, so it binds like any
        # other lane branch.
        pytest.param((), "master", id="master-beside-a-recorded-main-default"),
    ],
)
def test_claim_binds_base_and_branch_to_the_checkout_it_is_made_in(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    flags: tuple[str, ...],
    branch: str,
) -> None:
    standpoint = stand_in(branch=branch)
    serve_item(monkeypatch, ("src",))
    given = tuple(flag.format(head=standpoint.head) for flag in flags)

    status = claim(*given)

    claimed = claimed_here(standpoint)
    assert (status, str(claimed.base), claimed.branch) == (0, standpoint.head, branch)
    assert capsys.readouterr().out.startswith(f"CLAIMED issue #{ISSUE}: ")


@pytest.mark.parametrize(
    ("flags", "layout", "sentence"),
    [
        pytest.param(
            ("--base", NOT_THE_HEAD),
            {},
            f"claim base {NOT_THE_HEAD} does not match checkout HEAD {{head}}; "
            "omit --base to use checkout HEAD",
            id="a-base-that-is-not-the-checkout-head",
        ),
        pytest.param(
            ("--base", NOT_THE_HEAD, "--branch", "other"),
            {},
            f"claim base {NOT_THE_HEAD} does not match checkout HEAD {{head}}; "
            "omit --base to use checkout HEAD",
            id="base-and-branch-both-wrong-names-the-base-first",
        ),
        pytest.param(
            ("--base", "not-a-sha"),
            {},
            "base must be a full lowercase commit SHA",
            id="a-base-that-is-no-commit-sha",
        ),
        pytest.param(
            ("--branch", "other"),
            {},
            f"claim branch 'other' does not match checkout branch '{LANE_BRANCH}'",
            id="another-branch",
        ),
        pytest.param((), {"branch": "main", "linked": False}, NON_MAIN_REFUSAL, id="main-branch"),
        pytest.param(
            (),
            {"linked": False},
            f"build claims require a linked isolated worktree checkout; run {WORKTREE_RECIPE}",
            id="shared-checkout",
        ),
    ],
)
def test_claim_refuses_a_checkout_that_cannot_hold_the_claim_with_the_repair(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    flags: tuple[str, ...],
    layout: dict[str, object],
    sentence: str,
) -> None:
    standpoint = stand_in(**layout)
    serve_item(monkeypatch, ("src",))

    status = claim(*flags)

    assert status == 2
    assert capsys.readouterr().err == f"ERROR: {sentence.format(head=standpoint.head)}\n"
    assert not standing_claims(standpoint)


def test_claim_refuses_a_checkout_edited_before_the_claim_and_names_the_path(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    standpoint = stand_in()
    (standpoint.directory / "src" / "widget.py").write_text("changed\n")
    serve_item(monkeypatch, ("src",))

    status = claim()

    assert status == 2
    assert capsys.readouterr().err == (
        "ERROR: claim must be acquired before the first worktree edit: src/widget.py\n"
    )
    assert not standing_claims(standpoint)


@pytest.mark.parametrize(
    ("standing", "own_scope", "touches"),
    [
        pytest.param(
            (Standing(("src",), issue=55),),
            ("src/widget.py",),
            "overlaps issue #55 on src/widget.py",
            id="an-overlapping-standing-claim",
        ),
        pytest.param(
            (Standing(("docs",), branch="docs/foo"),),
            ("src",),
            "overlaps no other open claims",
            id="no-overlap",
        ),
        pytest.param(
            (
                Standing(("src",), issue=55),
                Standing(("docs",), branch="docs/foo"),
            ),
            ("src", "docs"),
            "overlaps issue #55 on src, lane docs/foo on docs",
            id="an-issue-claim-and-a-lane-claim",
        ),
        pytest.param(
            (Standing(("tests/adapters/test_claim_cli.py",), issue=1400),),
            ("tests",),
            "overlaps issue #1400 on tests/adapters/test_claim_cli.py",
            id="a-directory-meeting-a-single-file-of-a-standing-claim",
        ),
        pytest.param(
            (Standing(("src/a.py", "docs/b.md", "tests/c.py", "scripts/d.py"), issue=55),),
            ("src", "docs", "tests", "scripts"),
            "overlaps issue #55 on docs/b.md, scripts/d.py, src/a.py, and 1 more",
            id="overflow-counts-the-paths-past-the-named-three",
        ),
        pytest.param(
            (
                Standing(("src/a.py",), issue=55),
                Standing(("docs/b.md",), issue=57),
                Standing(("tests/c.py",), branch="docs/foo"),
            ),
            ("src", "docs", "tests"),
            "overlaps issue #55 on src/a.py, issue #57 on docs/b.md, lane docs/foo on tests/c.py",
            id="every-overlapping-claim-separately",
        ),
    ],
)
def test_claim_prints_the_standing_claims_its_scope_overlaps(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    standing: tuple[Standing, ...],
    own_scope: tuple[str, ...],
    touches: str,
) -> None:
    standpoint = stand_in(standing=standing)
    serve_item(monkeypatch, own_scope)

    status = claim(scope=own_scope)

    assert status == 0
    cost_line = capsys.readouterr().out.splitlines()[1]
    assert cost_line.endswith(f"; {touches}")
    assert claimed_here(standpoint).scope == tuple(sorted(own_scope))
