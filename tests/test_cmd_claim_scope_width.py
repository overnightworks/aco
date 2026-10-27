"""The scope-width gate of `aco claim`, `aco claim` in lane mode and
`aco rescope`, on real temporary worktrees: which scopes are refused without
`--whole` and with which sentence, which are accepted and what the claim then
holds, and the refusals a failed git read keeps apart from a wide scope. The
forge is the only fake."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, board_issue, complete_contract
from claim_worktrees import LANE_BRANCH, StandIn, Standing, Standpoint, make_stand_in
from cli_fixtures import stub_one_git_call
from github_fixtures import FakeForge, serve_forge

from aco import checkout, forge, policy, protocol, store
from aco import cli as issue_claim
from aco.protocol import ClaimError

ISSUE = 72
LANE_MODE_BRANCH = "docs/lane-cleanup"
CUT_BODY = complete_contract("Claim #72.") + "\n\n## Schnitt\n\n**Scheibe 1: Title**\n"
UNCUT_BODY = complete_contract("Claim #72.") + "\n\n## Schnitt\n\nNo slices yet.\n"

# The trunk files beside the tracked board configuration: eleven make twelve
# versioned files, `protocol.WIDE_SCOPE_SHARE_FLOOR`: LICENSE, README.md and
# `src` cover four of them.
TRUNK_OF_TWELVE = (
    "LICENSE",
    "README.md",
    "pyproject.toml",
    "src/a.py",
    "src/b.py",
    "docs/c.md",
    "docs/d.md",
    "docs/e.md",
    "docs/f.md",
    "docs/g.md",
    "docs/h.md",
)
TRUNK_OF_ELEVEN = TRUNK_OF_TWELVE[:-1]
BOARD_CONFIG_AND_TRUNK_OF_TWELVE = (".aco/board.toml", *TRUNK_OF_TWELVE)
SMALL_TREE = ("src/widget.py", "docs/a.md")
SMALL_TREE_WITH_TWO_DOCS = ("LICENSE", "README.md", "docs/a.md", "docs/b.md")
FOUR_NEW_FILES = ("new_a.py", "new_b.py", "new_c.py", "new_d.py")
SCOPE_READ_FAILURE = "fatal: object database unreadable"


class Command(Enum):
    CLAIM = "claim"
    LANE = "lane"
    RESCOPE = "rescope"


@dataclass(frozen=True)
class WidthCase:
    """One scope, the command that claims it, the tree it lands in and the
    claim a rescope widens."""

    command: Command
    scope: tuple[str, ...]
    trunk: tuple[str, ...] = SMALL_TREE
    standing_scope: tuple[str, ...] = ()
    whole: str | None = None
    body: str | None = None
    json_output: bool = False
    empty_directories: tuple[str, ...] = ()

    @property
    def branch(self) -> str:
        return LANE_MODE_BRANCH if self.command is Command.LANE else LANE_BRANCH


@dataclass(frozen=True)
class Refusal:
    case: WidthCase
    sentence: str | None = None


@dataclass(frozen=True)
class Acceptance:
    case: WidthCase
    printed_ends_with: str | None = None
    share: tuple[int, int] | None = None


def wide(condition: str) -> str:
    return f"ERROR: scope is wide: {condition}; pass --whole REASON or set whole in the body\n"


REFUSALS = [
    pytest.param(
        Refusal(WidthCase(Command.CLAIM, ("docs",)), wide("1 directory in scope (docs)")),
        id="a-directory",
    ),
    pytest.param(
        Refusal(WidthCase(Command.CLAIM, ("docs", "docs/a.md"))),
        id="a-directory-beside-its-child",
    ),
    pytest.param(
        Refusal(WidthCase(Command.CLAIM, ("docs",), body=CUT_BODY)),
        id="a-directory-of-a-cut-item",
    ),
    pytest.param(
        Refusal(WidthCase(Command.CLAIM, ("docs",), body=UNCUT_BODY)),
        id="a-directory-under-a-schnitt-heading-without-a-slice",
    ),
    pytest.param(
        Refusal(WidthCase(Command.CLAIM, ("docs",), trunk=SMALL_TREE_WITH_TWO_DOCS, body=CUT_BODY)),
        id="a-directory-of-a-cut-item-holding-a-high-share",
    ),
    pytest.param(Refusal(WidthCase(Command.LANE, ("docs",)), None), id="a-directory-in-lane-mode"),
    pytest.param(
        Refusal(
            WidthCase(Command.CLAIM, ("fresh",), empty_directories=("fresh",)),
            wide("1 directory in scope (fresh)"),
        ),
        id="a-directory-git-does-not-track-yet",
    ),
    pytest.param(
        Refusal(WidthCase(Command.CLAIM, FOUR_NEW_FILES), wide("4 paths exceeds three")),
        id="four-named-paths",
    ),
    pytest.param(
        Refusal(
            WidthCase(
                Command.RESCOPE,
                ("docs",),
                standing_scope=("src/widget.py",),
            )
        ),
        id="rescope-adding-a-directory",
    ),
    pytest.param(
        Refusal(
            WidthCase(
                Command.RESCOPE,
                ("LICENSE", "README.md"),
                trunk=("src/widget.py", "LICENSE", "README.md"),
                standing_scope=("src",),
            )
        ),
        id="rescope-adding-files-beside-a-standing-directory",
    ),
    pytest.param(
        Refusal(
            WidthCase(
                Command.RESCOPE,
                FOUR_NEW_FILES[1:],
                standing_scope=FOUR_NEW_FILES[:1],
            )
        ),
        id="rescope-widening-to-four-paths",
    ),
]

ACCEPTANCES = [
    pytest.param(
        Acceptance(
            WidthCase(
                Command.CLAIM,
                ("LICENSE", "README.md", "pyproject.toml"),
                trunk=TRUNK_OF_ELEVEN,
            ),
            printed_ends_with="3 of 11 versioned files (27%); overlaps no other open claims\n",
        ),
        id="a-share-above-a-quarter-below-the-floor",
    ),
    pytest.param(
        Acceptance(
            WidthCase(
                Command.CLAIM,
                ("LICENSE", "README.md", "pyproject.toml"),
                trunk=TRUNK_OF_TWELVE,
            ),
            printed_ends_with="3 of 12 versioned files (25%); overlaps no other open claims\n",
        ),
        id="a-share-at-a-quarter",
    ),
    pytest.param(
        Acceptance(
            WidthCase(
                Command.CLAIM,
                ("LICENSE", "README.md", "src"),
                trunk=TRUNK_OF_TWELVE,
                whole="cover four files",
                json_output=True,
            ),
            share=(4, 12),
        ),
        id="a-share-above-a-quarter-with-whole",
    ),
    pytest.param(
        Acceptance(WidthCase(Command.CLAIM, FOUR_NEW_FILES[:3])),
        id="three-named-paths",
    ),
    pytest.param(
        Acceptance(
            WidthCase(Command.CLAIM, FOUR_NEW_FILES, whole="the four adapters share one lock")
        ),
        id="four-named-paths-with-whole",
    ),
    pytest.param(
        Acceptance(WidthCase(Command.CLAIM, ("docs",), whole="rewrite the docs tree")),
        id="a-directory-with-whole",
    ),
    pytest.param(
        Acceptance(
            WidthCase(
                Command.RESCOPE,
                ("docs",),
                standing_scope=("src/widget.py",),
                whole="widen to the docs tree",
            )
        ),
        id="rescope-adding-a-directory-with-whole",
    ),
]


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, ())


def serve_item(monkeypatch: pytest.MonkeyPatch, body: str | None = None) -> None:
    served_body = body or complete_contract("Claim #72.")
    serve_forge(
        monkeypatch,
        FakeForge(
            board_issues=(board_issue(ISSUE, "Work", served_body),),
            issue_references={
                ISSUE: forge.ItemReference(forge.ItemState.OPEN, "Work", served_body)
            },
        ),
    )


def held_claims(standpoint: Standpoint) -> list[protocol.ActiveClaim]:
    state = store.fetch_state(worktree=standpoint.directory, remote="origin")
    return list(state.claims.values())


def arrange(stand_in: StandIn, monkeypatch: pytest.MonkeyPatch, case: WidthCase) -> Standpoint:
    standing = (
        (Standing(case.standing_scope, issue=ISSUE, branch=LANE_BRANCH),)
        if case.command is Command.RESCOPE
        else ()
    )
    standpoint = stand_in(branch=case.branch, standing=standing, more_trunk_files=case.trunk)
    for name in case.empty_directories:
        (standpoint.directory / name).mkdir()
    serve_item(monkeypatch, case.body)
    return standpoint


def arguments(case: WidthCase, standpoint: Standpoint) -> list[str]:
    tail = ["--json"] if case.json_output else []
    if case.whole is not None:
        tail = ["--whole", case.whole, *tail]
    if case.command is Command.RESCOPE:
        added = [
            flag for path in case.scope for flag in ("--add", str(standpoint.directory / path))
        ]
        return ["--repo", REPOSITORY, "rescope", str(ISSUE), *added, *tail]
    scoped = [flag for path in case.scope for flag in ("--scope", path)]
    number = [] if case.command is Command.LANE else [str(ISSUE)]
    return ["--repo", REPOSITORY, "claim", *number, *scoped, *tail]


@pytest.mark.parametrize("refusal", REFUSALS)
def test_a_wide_scope_is_refused_without_whole_and_changes_no_claim(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    refusal: Refusal,
) -> None:
    standpoint = arrange(stand_in, monkeypatch, refusal.case)
    held_before = held_claims(standpoint)

    status = issue_claim.main(arguments(refusal.case, standpoint))

    captured = capsys.readouterr()
    assert (status, captured.out) == (2, "")
    if refusal.sentence is not None:
        assert captured.err == refusal.sentence
    else:
        assert "scope is wide" in captured.err
        assert "--whole" in captured.err
    assert held_claims(standpoint) == held_before


@pytest.mark.parametrize("acceptance", ACCEPTANCES)
def test_a_scope_within_the_width_limits_or_with_whole_is_claimed_with_its_reason(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    acceptance: Acceptance,
) -> None:
    case = acceptance.case
    standpoint = arrange(stand_in, monkeypatch, case)

    status = issue_claim.main(arguments(case, standpoint))

    out = capsys.readouterr().out
    [held] = [claim for claim in held_claims(standpoint) if claim.branch == case.branch]
    assert status == 0
    assert (held.scope, held.whole_reason) == (
        tuple(sorted({*case.standing_scope, *case.scope})),
        case.whole,
    )
    if acceptance.printed_ends_with is not None:
        assert out.endswith(acceptance.printed_ends_with)
    if acceptance.share is not None:
        payload = json.loads(out)
        assert (payload["versioned_files"], payload["versioned_files_total"]) == acceptance.share
        assert payload["share"] == pytest.approx(1 / 3)
        assert payload["touches"] == []


def test_claim_under_state_ref_storage_refuses_repo_as_invalid_usage_before_the_width_gate(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    standpoint = stand_in(board_config='storage = "state-ref"\n', more_trunk_files=FOUR_NEW_FILES)

    status = issue_claim.main(
        [
            "--repo",
            "acme/items",
            "claim",
            str(ISSUE),
            *(flag for path in FOUR_NEW_FILES for flag in ("--scope", path)),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    message = "--repo is meaningless under storage = state-ref"
    assert status == 2
    assert captured.err == f"ERROR: {message}\n"
    assert (
        captured.out
        == json.dumps({"ok": False, "reason": "invalid_usage", "message": message}) + "\n"
    )
    assert not held_claims(standpoint)


def fail_reading_tree_entry(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    calls = stub_one_git_call(
        monkeypatch,
        ["ls-tree", "--full-tree", "HEAD", "--", path],
        exit_status=128,
        stderr=SCOPE_READ_FAILURE,
    )
    assert calls == []


def unavailable(message: str) -> str:
    return json.dumps({"ok": False, "reason": "unavailable", "message": message}) + "\n"


@pytest.mark.parametrize(
    ("case", "path"),
    [
        pytest.param(WidthCase(Command.CLAIM, ("docs",), json_output=True), "docs", id="claim"),
        pytest.param(
            WidthCase(
                Command.RESCOPE,
                ("src/new.py",),
                standing_scope=("src/widget.py",),
                json_output=True,
            ),
            "src/new.py",
            id="rescope",
        ),
    ],
)
def test_a_git_failure_reading_a_scope_entry_is_unavailable_and_never_a_wide_scope(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    case: WidthCase,
    path: str,
) -> None:
    standpoint = arrange(stand_in, monkeypatch, case)
    fail_reading_tree_entry(monkeypatch, path)

    status = issue_claim.main(arguments(case, standpoint))

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == f"ERROR: {SCOPE_READ_FAILURE}\n"
    assert captured.out == unavailable(SCOPE_READ_FAILURE)


def test_an_untracked_scope_entry_outside_a_working_tree_keeps_the_checkout_refusal(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = WidthCase(Command.CLAIM, ("scratch",))
    standpoint = arrange(stand_in, monkeypatch, case)
    read_git = checkout.git_output

    def outside_a_working_tree(
        arguments: list[str], *, directory: Path | None = None, literal_pathspecs: bool = False
    ) -> str:
        if arguments == ["rev-parse", "--show-toplevel"]:
            raise ClaimError("fatal: this operation must be run in a work tree")
        return read_git(arguments, directory=directory, literal_pathspecs=literal_pathspecs)

    monkeypatch.setattr(checkout, "git_output", outside_a_working_tree)

    status = issue_claim.main(arguments(case, standpoint))

    assert status == 2
    assert capsys.readouterr().err == (
        "ERROR: this command reads the repository's body contract from "
        ".aco/board.toml and needs a checkout (a shallow one is "
        "enough): fatal: this operation must be run in a work tree\n"
    )


def test_a_share_above_a_quarter_of_the_versioned_files_is_refused_with_its_numbers() -> None:
    """No real tree reaches this refusal: a share over a quarter of at least
    twelve files takes four covered files, which three named paths hold only
    through a directory, and a directory is refused first."""
    with pytest.raises(ClaimError) as refusal:
        policy.reject_wide_scope(
            ("LICENSE", "README.md", "src"), BOARD_CONFIG_AND_TRUNK_OF_TWELVE, None, directories=()
        )

    assert str(refusal.value) == (
        "scope is wide: 4 paths of 12 versioned files (33 %) exceeds a quarter; pass --whole REASON"
    )
