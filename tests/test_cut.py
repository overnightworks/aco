"""Cut preconditions and child creation through the real GitHub repository world."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body, board_issue, container_issue
from cli_fixtures import real_git, run_cli, track_board_config
from github_fixtures import FakeForge, assert_github_world, serve_forge

from agent_coordination import board, body, forge


@dataclass(frozen=True)
class CutObservation:
    exit: int | str | None
    stdout: str
    stderr: str
    forge_read: bool
    created_children: tuple[tuple[int, str, str, body.ItemKind], ...]
    item_bodies: Mapping[int, str]


@dataclass(frozen=True)
class CutCase:
    issues: tuple[board.Issue, ...]
    arguments: tuple[str, ...]
    exit: int | str | None
    stdout: str
    stderr: str
    forge_read: bool
    created_children: tuple[tuple[int, str, str, body.ItemKind], ...]
    item_bodies: Mapping[int, str]
    envelope: Mapping[str, object]
    parents: dict[int, board.ParentIssue] = field(default_factory=dict)
    capabilities: dict[forge.ForgeOperation, forge.Capability] = field(default_factory=dict)


def rendered(identifier: str, case: CutCase) -> tuple[object, ...]:
    return (
        pytest.param(case, id=identifier),
        pytest.param(
            replace(
                case,
                arguments=(*case.arguments, "--json"),
                stdout=json.dumps(dict(case.envelope)) + "\n",
            ),
            id=identifier + "-json",
        ),
    )


@pytest.fixture(autouse=True)
def _github_world(github_clone: Path, bare_remote: Path) -> None:
    assert_github_world(github_clone, bare_remote)


CutCheck = Callable[[CutCase], None]


@pytest.fixture
def cut_check(
    github_clone: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> CutCheck:
    track_board_config(github_clone, 'body_contract = "block"\n')
    assert real_git(github_clone, "show", "HEAD:.aco/board.toml").stdout == (
        'body_contract = "block"\n'
    )

    def check(case: CutCase) -> None:
        client = serve_forge(
            monkeypatch,
            FakeForge(
                board_issues=case.issues,
                parents=case.parents,
                capability_overrides=case.capabilities,
            ),
        )
        assert client.board_issues == case.issues
        assert client.parents == case.parents
        assert client.capability_overrides == case.capabilities
        capsys.readouterr()
        command = ["cut", "79", *case.arguments]
        result = run_cli(command, capsys)
        observed = CutObservation(
            result.status,
            result.stdout,
            result.stderr,
            client.requests > 0,
            tuple(client.created_children),
            dict(client.item_bodies),
        )
        expected = CutObservation(
            case.exit,
            case.stdout,
            case.stderr,
            case.forge_read,
            case.created_children,
            case.item_bodies,
        )
        assert observed == expected

    return check


def slice_row(index: int, title: str, fields: str = "") -> str:
    return f'[[slice]]\nindex = {index}\ntitle = "{title}"\n{fields}'


def child_body(done_when: str, scope: str = "") -> str:
    return (
        'Parent: #79\n\n```aco\nversion = 1\nnow = "Cut from #79"\n'
        'next = "Build this slice; claim it with aco start."\n'
        f'done_when = "{done_when}"\n{scope}```\n'
    )


def refused(
    message: str,
    reason: str,
    issues: tuple[board.Issue, ...],
    arguments: tuple[str, ...],
    *,
    forge_read: bool = True,
    parents: dict[int, board.ParentIssue] | None = None,
    capabilities: dict[forge.ForgeOperation, forge.Capability] | None = None,
) -> CutCase:
    return CutCase(
        issues=issues,
        arguments=arguments,
        exit=2,
        stdout="",
        stderr=f"ERROR: {message}\n",
        forge_read=forge_read,
        created_children=(),
        item_bodies={},
        envelope={"ok": False, "reason": reason, "message": message},
        parents=parents or {},
        capabilities=capabilities or {},
    )


def cut(
    before: str,
    arguments: tuple[str, ...],
    row: int | None,
    title: str,
    child: str,
    after: Mapping[int, str],
) -> CutCase:
    row_text = "" if row is None else f" row {row}"
    return CutCase(
        issues=(container_issue(79, before),),
        arguments=arguments,
        exit=0,
        stdout=f"CUT #79{row_text} -> #900\n",
        stderr="",
        forge_read=True,
        created_children=((79, title, child, body.ItemKind.TASK),),
        item_bodies=after,
        envelope={"ok": True, "reason": "cut", "container": 79, "row": row, "child": 900},
    )


@pytest.mark.parametrize(
    "case",
    [
        *rendered(
            "not-an-open-container",
            refused(
                "#79 is not an open container",
                "precondition_failed",
                (),
                ("--title", "Slice A"),
                forge_read=True,
            ),
        ),
        *rendered(
            "blank-title",
            refused(
                "--title must be a non-empty string",
                "invalid_usage",
                (container_issue(79, MINIMAL_BLOCK_TOML),),
                ("--title", " \t "),
                forge_read=False,
            ),
        ),
        *rendered(
            "not-a-container",
            refused(
                "#79 is not a container",
                "precondition_failed",
                (board_issue(79, "Not a container", MINIMAL_BLOCK_TOML + "x"),),
                ("--title", "Slice A"),
                forge_read=True,
            ),
        ),
        *rendered(
            "itself-a-child",
            refused(
                "#79 is itself a child of example/agent-coordination#1; "
                "nested containers are not supported",
                "precondition_failed",
                (
                    container_issue(
                        79, MINIMAL_BLOCK_TOML + slice_row(1, "Slice A", 'done_when = "D"\n')
                    ),
                ),
                ("--title", "Slice A"),
                forge_read=True,
                parents={
                    79: board.ParentIssue(
                        board.IssueReference("example/agent-coordination", 1),
                        "",
                        body.ItemKind.CONTAINER,
                    )
                },
            ),
        ),
        *rendered(
            "forge-cannot-create-child",
            refused(
                "this forge cannot create_child; cut the slice by hand",
                "precondition_failed",
                (
                    container_issue(
                        79, MINIMAL_BLOCK_TOML + slice_row(1, "Slice A", 'done_when = "D"\n')
                    ),
                ),
                (),
                forge_read=False,
                capabilities={forge.ForgeOperation.CREATE_CHILD: forge.Capability.READ_ONLY},
            ),
        ),
        *rendered(
            "forge-cannot-link-child",
            refused(
                "this forge cannot link_child; cut the slice by hand",
                "precondition_failed",
                (
                    container_issue(
                        79, MINIMAL_BLOCK_TOML + slice_row(1, "Slice A", 'done_when = "D"\n')
                    ),
                ),
                (),
                forge_read=False,
                capabilities={forge.ForgeOperation.LINK_CHILD: forge.Capability.READ_ONLY},
            ),
        ),
        *rendered(
            "forge-cannot-update-item-body",
            refused(
                "this forge cannot update_item_body; cut the slice by hand",
                "precondition_failed",
                (
                    container_issue(
                        79, MINIMAL_BLOCK_TOML + slice_row(1, "Slice A", 'done_when = "D"\n')
                    ),
                ),
                (),
                forge_read=False,
                capabilities={forge.ForgeOperation.UPDATE_ITEM_BODY: forge.Capability.READ_ONLY},
            ),
        ),
    ],
)
def test_cut_requires_an_open_top_level_container_and_a_writable_forge(
    case: CutCase, cut_check: CutCheck
) -> None:
    """Spec: CUT-01, CUT-02, CUT-03, CUT-04, CUT-33, OUT-05, OUT-06, E-CUT-01."""
    cut_check(case)


@pytest.mark.parametrize(
    "case",
    [
        *rendered(
            "no-aco-block",
            refused(
                "#79 body malformed: aco: no aco block; cut needs a valid aco block",
                "precondition_failed",
                (board_issue(79, "Epic", "## Now\nOld prose.\n", kind=body.ItemKind.CONTAINER),),
                ("--title", "X"),
                forge_read=True,
            ),
        ),
        *rendered(
            "malformed-version",
            refused(
                "#79 body malformed: version: version must be exactly 1; "
                "cut needs a valid aco block",
                "precondition_failed",
                (container_issue(79, 'version = 2\nnow = "N"\nnext = "X"\ndone_when = "D"\n'),),
                ("--title", "X"),
                forge_read=True,
            ),
        ),
        *rendered(
            "selected-row-done-when-U+000B",
            refused(
                "#79 body malformed: slice[1].done_when: slice[1].done_when of row 2 holds U+000B; "
                "a slice done_when stays on one line; cut needs a valid aco block",
                "precondition_failed",
                (
                    container_issue(
                        79,
                        MINIMAL_BLOCK_TOML
                        + (
                            slice_row(1, "Clean", 'done_when = "D"\n')
                            + slice_row(2, "Dirty", 'done_when = "one\\u000Btwo"\n')
                        ),
                    ),
                ),
                ("--row", "2"),
                forge_read=True,
            ),
        ),
        *rendered(
            "selected-row-done-when-U+001B",
            refused(
                "#79 body malformed: slice[1].done_when: slice[1].done_when of row 2 holds U+001B; "
                "a slice done_when stays on one line; cut needs a valid aco block",
                "precondition_failed",
                (
                    container_issue(
                        79,
                        MINIMAL_BLOCK_TOML
                        + (
                            slice_row(1, "Clean", 'done_when = "D"\n')
                            + slice_row(2, "Dirty", 'done_when = "one\\u001Btwo"\n')
                        ),
                    ),
                ),
                ("--row", "2"),
                forge_read=True,
            ),
        ),
        *rendered(
            "other-row-title-control-is-cut-around",
            cut(
                MINIMAL_BLOCK_TOML
                + (
                    slice_row(1, "Good row", 'done_when = "Clean."\n')
                    + slice_row(2, "Bad\\u000Btitle", "")
                ),
                (),
                1,
                "Good row",
                child_body("Clean.", ""),
                {
                    79: block_body(
                        'version = 1\nnow = "N"\nnext = "X"\ndone_when = "D"\n\n'
                        + slice_row(2, "Bad\\u000Btitle", "").rstrip("\n")
                    )
                },
            ),
        ),
        *rendered(
            "other-row-done-when-control-is-cut-around",
            cut(
                MINIMAL_BLOCK_TOML
                + (
                    slice_row(1, "Good row", 'done_when = "Clean."\n')
                    + slice_row(2, "Other", 'done_when = "a\\u001B[2Jb"\n')
                ),
                (),
                1,
                "Good row",
                child_body("Clean.", ""),
                {
                    79: block_body(
                        'version = 1\nnow = "N"\nnext = "X"\ndone_when = "D"\n\n'
                        + slice_row(2, "Other", 'done_when = "a\\u001B[2Jb"').rstrip("\n")
                    )
                },
            ),
        ),
    ],
)
def test_cut_requires_a_valid_block_for_the_row_it_cuts(case: CutCase, cut_check: CutCheck) -> None:
    """Spec: CUT-05, CUT-39, E-CUT-03."""
    cut_check(case)


@pytest.mark.parametrize(
    "case",
    [
        *rendered(
            "row-selected-by-number",
            cut(
                MINIMAL_BLOCK_TOML
                + (
                    slice_row(1, "Scheibe 1", 'done_when = "D"\n')
                    + slice_row(2, "Scheibe 2", 'done_when = "D"\n')
                ),
                ("--row", "2"),
                2,
                "Scheibe 2",
                child_body("D", ""),
                {
                    79: block_body(
                        'version = 1\nnow = "N"\nnext = "X"\ndone_when = "D"\n\n'
                        + slice_row(1, "Scheibe 1", 'done_when = "D"').rstrip("\n")
                    )
                },
            ),
        ),
        *rendered(
            "title-differs-from-the-row",
            refused(
                "#79's slice 1 is titled 'Scheibe 1'; --title must match it exactly",
                "precondition_failed",
                (
                    container_issue(
                        79, MINIMAL_BLOCK_TOML + slice_row(1, "Scheibe 1", 'done_when = "D"\n')
                    ),
                ),
                ("--title", "Wrong title"),
                forge_read=True,
            ),
        ),
        *rendered(
            "row-number-without-a-slice-table",
            refused(
                "#79 has no slice table; --row needs one to select a row from",
                "precondition_failed",
                (container_issue(79, MINIMAL_BLOCK_TOML),),
                ("--title", "X", "--row", "1"),
                forge_read=True,
            ),
        ),
        *rendered(
            "row-number-not-in-the-table",
            refused(
                "#79 has no row 9; cuttable rows: 1",
                "precondition_failed",
                (
                    container_issue(
                        79, MINIMAL_BLOCK_TOML + slice_row(1, "Scheibe 1", 'done_when = "D"\n')
                    ),
                ),
                ("--row", "9"),
                forge_read=True,
            ),
        ),
        *rendered(
            "row-number-in-an-empty-table",
            refused(
                "#79 has no row 9; cuttable rows: none",
                "precondition_failed",
                (container_issue(79, MINIMAL_BLOCK_TOML + "slice = []\n"),),
                ("--row", "9"),
                forge_read=True,
            ),
        ),
        *rendered(
            "no-title-without-a-slice-key",
            refused(
                "#79 has no slice row; pass --title",
                "precondition_failed",
                (container_issue(79, MINIMAL_BLOCK_TOML),),
                (),
                forge_read=True,
            ),
        ),
        *rendered(
            "no-title-with-an-empty-slice",
            refused(
                "#79 has no slice row; pass --title",
                "precondition_failed",
                (container_issue(79, MINIMAL_BLOCK_TOML + "slice = []\n"),),
                (),
                forge_read=True,
            ),
        ),
    ],
)
def test_cut_selects_a_row_and_requires_its_title(case: CutCase, cut_check: CutCheck) -> None:
    """Spec: CUT-06, CUT-07, CUT-08, CUT-09, CUT-35, E-CUT-02, E-CUT-03, E-CUT-04."""
    cut_check(case)


@pytest.mark.parametrize(
    "case",
    [
        *rendered(
            "first-of-two-rows",
            cut(
                MINIMAL_BLOCK_TOML
                + (
                    slice_row(1, "Scheibe 1", 'done_when = "D"\n')
                    + slice_row(2, "Scheibe 2", 'done_when = "D"\n')
                ),
                (),
                1,
                "Scheibe 1",
                child_body("D", ""),
                {
                    79: block_body(
                        'version = 1\nnow = "N"\nnext = "X"\ndone_when = "D"\n\n'
                        + slice_row(2, "Scheibe 2", 'done_when = "D"').rstrip("\n")
                    )
                },
            ),
        ),
        *rendered(
            "row-without-done-when",
            cut(
                MINIMAL_BLOCK_TOML + slice_row(1, "Scheibe 1", ""),
                (),
                1,
                "Scheibe 1",
                child_body("", ""),
                {
                    79: block_body(
                        'version = 1\nnow = "N"\nnext = "X"\ndone_when = "D"\n\nslice = []'
                    )
                },
            ),
        ),
        *rendered(
            "untied-without-a-slice-key",
            cut(MINIMAL_BLOCK_TOML, ("--title", "Untied"), None, "Untied", child_body("", ""), {}),
        ),
        *rendered(
            "untied-with-an-empty-slice",
            cut(
                MINIMAL_BLOCK_TOML + "slice = []\n",
                ("--title", "Untied"),
                None,
                "Untied",
                child_body("", ""),
                {},
            ),
        ),
    ],
)
def test_cut_creates_the_child_and_removes_its_row(case: CutCase, cut_check: CutCheck) -> None:
    """Spec: CUT-06, CUT-10, CUT-11, CUT-12, CUT-24, CUT-25, CUT-37, E-CUT-02, E-CUT-04."""
    cut_check(case)


@pytest.mark.parametrize(
    "case",
    [
        *rendered(
            "fills-an-empty-row",
            cut(
                MINIMAL_BLOCK_TOML + slice_row(1, "Scheibe 1", 'done_when = "D"\n'),
                ("--scope", "src/c.py"),
                1,
                "Scheibe 1",
                child_body("D", '\nscope = ["src/c.py"]\n'),
                {
                    79: block_body(
                        'version = 1\nnow = "N"\nnext = "X"\ndone_when = "D"\n\nslice = []'
                    )
                },
            ),
        ),
        *rendered(
            "inherits-the-rows-scope",
            cut(
                MINIMAL_BLOCK_TOML
                + slice_row(1, "Slice C", 'done_when = "D"\nscope = ["src/c.py"]\n'),
                (),
                1,
                "Slice C",
                child_body("D", '\nscope = ["src/c.py"]\n'),
                {
                    79: block_body(
                        'version = 1\nnow = "N"\nnext = "X"\ndone_when = "D"\n\nslice = []'
                    )
                },
            ),
        ),
        *rendered(
            "refuses-a-row-that-names-one",
            refused(
                "slice 1 already names a scope; edit the container instead",
                "precondition_failed",
                (
                    container_issue(
                        79,
                        MINIMAL_BLOCK_TOML
                        + slice_row(1, "Slice C", 'done_when = "D"\nscope = ["src/c.py"]\n'),
                    ),
                ),
                ("--scope", "src/other.py"),
                forge_read=True,
            ),
        ),
        *rendered(
            "no-row-takes-the-scope-directly",
            cut(
                MINIMAL_BLOCK_TOML,
                ("--title", "Loose Cut", "--scope", "src/loose.py"),
                None,
                "Loose Cut",
                child_body("", '\nscope = ["src/loose.py"]\n'),
                {},
            ),
        ),
    ],
)
def test_cut_fills_inherits_or_refuses_the_scope(case: CutCase, cut_check: CutCheck) -> None:
    """Spec: CUT-20, CUT-21, CUT-22, CUT-23, E-CUT-06."""
    cut_check(case)
