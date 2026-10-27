"""Cut preconditions, child creation, adoption and recovery through the real GitHub world."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body, board_issue, container_issue
from cli_fixtures import FROZEN_CLI_NOW, freeze_cli_now, real_git, run_cli, track_board_config
from github_fixtures import FakeForge, assert_github_world, serve_forge

from aco import body, forge, workboard
from aco.workboard import IssueReference, ParentIssue


class ForgeEvent(Enum):
    RELATION_WRITE_FAILS = "relation write fails"
    ISSUE_TYPE_DROPPED = "issue type dropped"
    ROW_REMOVAL_FAILS = "row removal fails"
    WRITES_RECOVER = "writes recover"
    ISSUE_TYPE_SET_BY_HAND = "issue type set by hand"
    BODIES_READ_AS_CRLF = "bodies read as CRLF"
    NEW_CHILD_READABLE = "new child readable"


def occur(forge_world: FakeForge, event: ForgeEvent) -> None:
    if event is ForgeEvent.RELATION_WRITE_FAILS:
        forge_world.fail_create_child_relation = True
    elif event is ForgeEvent.ISSUE_TYPE_DROPPED:
        forge_world.drop_created_issue_type = True
    elif event is ForgeEvent.ROW_REMOVAL_FAILS:
        forge_world.fail_update_item_body = True
    elif event is ForgeEvent.WRITES_RECOVER:
        forge_world.fail_create_child_relation = False
        forge_world.drop_created_issue_type = False
        forge_world.fail_update_item_body = False
    elif event is ForgeEvent.ISSUE_TYPE_SET_BY_HAND:
        forge_world.board_issues = tuple(
            replace(issue, kind=body.ItemKind.TASK) if issue.kind is None else issue
            for issue in forge_world.board_issues
        )
    elif event is ForgeEvent.NEW_CHILD_READABLE:
        forge_world.issue_references.update(
            {
                number: forge.ItemReference(forge.ItemState.OPEN, title, text, False)
                for number, (title, text) in enumerate(
                    ((title, text) for title, text, _kind in forge_world.created_issues),
                    start=900,
                )
            }
        )
    else:
        forge_world.board_issues = tuple(
            replace(issue, body=issue.body.replace("\n", "\r\n"))
            for issue in forge_world.board_issues
        )


@dataclass(frozen=True)
class CutObservation:
    exit: int | str | None
    stdout: str
    stderr: str
    forge_read: bool
    created_children: tuple[tuple[int, str, str, body.ItemKind], ...]
    created_issues: tuple[tuple[str, str, body.ItemKind], ...]
    linked_children: tuple[tuple[int, int], ...]
    item_bodies: Mapping[int, str]
    closed_issue_cutoffs: tuple[datetime, ...]


@dataclass(frozen=True)
class CutCase:
    issues: tuple[workboard.Issue, ...]
    arguments: tuple[str, ...]
    exit: int | str | None
    stdout: str
    stderr: str
    forge_read: bool
    created_children: tuple[tuple[int, str, str, body.ItemKind], ...]
    created_issues: tuple[tuple[str, str, body.ItemKind], ...]
    item_bodies: Mapping[int, str]
    envelope: Mapping[str, object]
    linked_children: tuple[tuple[int, int], ...] = ()
    closed_issue_cutoffs: tuple[datetime, ...] = ()
    parents: Mapping[int, ParentIssue] = field(default_factory=dict)
    children: Mapping[int, tuple[workboard.ChildItem, ...]] = field(default_factory=dict)
    references: Mapping[int, forge.ItemReference] = field(default_factory=dict)
    recently_closed: tuple[forge.ClosedIssue, ...] = ()
    events: tuple[ForgeEvent, ...] = ()
    rerun: CutCase | None = None


def rendered(identifier: str, case: CutCase) -> tuple[object, ...]:
    def as_json(stage: CutCase) -> CutCase:
        return replace(
            stage,
            arguments=(*stage.arguments, "--json"),
            stdout=json.dumps(dict(stage.envelope)) + "\n",
            rerun=None if stage.rerun is None else as_json(stage.rerun),
        )

    return (pytest.param(case, id=identifier), pytest.param(as_json(case), id=identifier + "-json"))


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
    pin = 'body_contract = "block"\nidea_label = "idea"\n'
    track_board_config(github_clone, pin)
    assert real_git(github_clone, "show", "HEAD:.aco/board.toml").stdout == pin
    freeze_cli_now(monkeypatch)

    def check(case: CutCase) -> None:
        client = serve_forge(
            monkeypatch,
            FakeForge(
                board_issues=case.issues,
                parents=dict(case.parents),
                children=dict(case.children),
                issue_references=dict(case.references),
                recently_closed_issues=case.recently_closed,
            ),
        )
        assert client.board_issues == case.issues
        assert client.parents == case.parents
        assert client.children == case.children
        assert client.issue_references == case.references
        assert client.recently_closed_issues == case.recently_closed
        stage: CutCase | None = case
        position = 0
        while stage is not None:
            position += 1
            for event in stage.events:
                occur(client, event)
            capsys.readouterr()
            requests_before = client.requests
            result = run_cli(["cut", "79", *stage.arguments], capsys)
            observed = CutObservation(
                result.status,
                result.stdout,
                result.stderr,
                client.requests > requests_before,
                tuple(client.created_children),
                tuple(client.created_issues),
                tuple(client.linked_children),
                dict(client.item_bodies),
                tuple(client.closed_issue_cutoffs),
            )
            expected = CutObservation(
                stage.exit,
                stage.stdout,
                stage.stderr,
                stage.forge_read,
                stage.created_children,
                stage.created_issues,
                stage.linked_children,
                stage.item_bodies,
                stage.closed_issue_cutoffs,
            )
            assert observed == expected, f"stage {position}"
            stage = stage.rerun

    return check


SLICE_ROW = '[[slice]]\nindex = {0}\ntitle = "{1}"\n{2}'
CHILD_BODY = (
    'Parent: #79\n\n```aco\nversion = 1\nnow = "Cut from #79"\n'
    'next = "Build this slice; claim it with aco start."\n'
    'done_when = "{0}"\n{1}```\n'
)
ONE_ROW = MINIMAL_BLOCK_TOML + SLICE_ROW.format(1, "Slice A", 'done_when = "D"\n')
ROW_REMOVED = {79: block_body(MINIMAL_BLOCK_TOML + "\nslice = []")}
TWIN_SEARCH_START = FROZEN_CLI_NOW - timedelta(days=30)


def refused(
    message: str,
    reason: str,
    issues: tuple[workboard.Issue, ...],
    arguments: tuple[str, ...],
    *,
    forge_read: bool = True,
    searched: bool = False,
    parents: dict[int, ParentIssue] | None = None,
) -> CutCase:
    return CutCase(
        issues=issues,
        arguments=arguments,
        exit=2,
        stdout="",
        stderr=f"ERROR: {message}\n",
        forge_read=forge_read,
        created_children=(),
        created_issues=(),
        item_bodies={},
        closed_issue_cutoffs=(TWIN_SEARCH_START,) if searched else (),
        envelope={"ok": False, "reason": reason, "message": message},
        parents=parents or {},
    )


def cut(
    before: str,
    arguments: tuple[str, ...],
    row: int | None,
    title: str,
    child: str,
    after: Mapping[int, str],
    *,
    searched: bool = True,
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
        created_issues=((title, child, body.ItemKind.TASK),),
        linked_children=((79, 900),),
        item_bodies=after,
        closed_issue_cutoffs=(TWIN_SEARCH_START,) if searched else (),
        envelope={"ok": True, "reason": "cut", "container": 79, "row": row, "child": 900},
    )


def adopted(
    child: int,
    *,
    linked: bool,
    issues: tuple[workboard.Issue, ...] = (),
    arguments: tuple[str, ...] = ("--title", "Slice A"),
) -> CutCase:
    return replace(
        cut(
            ONE_ROW,
            arguments,
            1,
            "Slice A",
            CHILD_BODY.format("D", ""),
            ROW_REMOVED,
            searched=False,
        ),
        issues=(container_issue(79, ONE_ROW), *issues),
        stdout=f"ADOPTED #79 row 1 -> #{child}\n",
        created_children=(),
        created_issues=(),
        linked_children=((79, child),) if linked else (),
        envelope={"ok": True, "reason": "adopted", "container": 79, "row": 1, "child": child},
    )


def child_issue(
    number: int,
    title: str = "Slice A",
    *,
    parent: int = 79,
    kind: body.ItemKind | None = body.ItemKind.TASK,
    labels: tuple[str, ...] = (),
) -> workboard.Issue:
    return board_issue(
        number,
        title,
        CHILD_BODY.format("D", "").replace("#79", f"#{parent}"),
        labels=labels,
        kind=kind,
    )


def with_linked_child(
    case: CutCase, number: int, state: workboard.ChildState, title: str = "Slice A"
) -> CutCase:
    open_child = (child_issue(number, title),) if state is workboard.ChildState.OPEN else ()
    return replace(
        case,
        issues=(*case.issues, *open_child),
        children={79: (workboard.ChildItem(number, state),)},
        references={
            number: forge.ItemReference(
                forge.ItemState(state.value), title, CHILD_BODY.format("D", ""), False
            )
        },
        parents={number: ParentIssue(IssueReference("example/agent-coordination", 79), "")},
    )


def partial(message: str, failed: str, event: ForgeEvent) -> CutCase:
    child = CHILD_BODY.format("D", "")
    return replace(
        refused(
            message,
            "partial_write",
            (container_issue(79, ONE_ROW),),
            ("--title", "Slice A"),
            searched=True,
        ),
        created_children=((79, "Slice A", child, body.ItemKind.TASK),),
        created_issues=(("Slice A", child, body.ItemKind.TASK),),
        linked_children=() if event is ForgeEvent.ISSUE_TYPE_DROPPED else ((79, 900),),
        envelope={
            "ok": False,
            "reason": "partial_write",
            "written": 900,
            "failed": failed,
            "message": message,
        },
        events=(event,),
    )


def then(first: CutCase, *stages: CutCase) -> CutCase:
    if not stages:
        return first
    return replace(first, rerun=then(*stages))


def look_alikes(
    case: CutCase, open_titles: Mapping[int, str], closed_titles: Mapping[int, str]
) -> CutCase:
    return replace(
        case,
        issues=(
            *case.issues,
            *(board_issue(number, title, "Some work.") for number, title in open_titles.items()),
        ),
        recently_closed=tuple(
            forge.ClosedIssue(number, title) for number, title in closed_titles.items()
        ),
    )


def twin_of(
    number: int, title: str, open_titles: Mapping[int, str], closed_titles: Mapping[int, str]
) -> CutCase:
    return look_alikes(
        refused(
            f"possible twin #{number}; pass --not-a-twin",
            "precondition_failed",
            (container_issue(79, MINIMAL_BLOCK_TOML),),
            ("--title", title),
            searched=True,
        ),
        open_titles,
        closed_titles,
    )


def no_twin(
    title: str, open_titles: Mapping[int, str], closed_titles: Mapping[int, str]
) -> CutCase:
    return look_alikes(
        cut(MINIMAL_BLOCK_TOML, ("--title", title), None, title, CHILD_BODY.format("", ""), {}),
        open_titles,
        closed_titles,
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
                (board_issue(79, "Not a container", block_body(MINIMAL_BLOCK_TOML)),),
                ("--title", "Slice A"),
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
                        79, MINIMAL_BLOCK_TOML + SLICE_ROW.format(1, "Slice A", 'done_when = "D"\n')
                    ),
                ),
                ("--title", "Slice A"),
                parents={
                    79: ParentIssue(
                        IssueReference("example/agent-coordination", 1),
                        "",
                        body.ItemKind.CONTAINER,
                    )
                },
            ),
        ),
    ],
)
def test_cut_requires_an_open_top_level_container(case: CutCase, cut_check: CutCheck) -> None:
    """Spec: CUT-01, CUT-02, CUT-03, CUT-33, OUT-05, OUT-06, E-CUT-01."""
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
            ),
        ),
        *rendered(
            "unknown-key-with-display-controls",
            refused(
                "#79 body malformed: k\\x1b]0;x\\x07: unknown top-level key k\\x1b]0;x\\x07; "
                "cut needs a valid aco block",
                "precondition_failed",
                (container_issue(79, MINIMAL_BLOCK_TOML + '"k\\u001b]0;x\\u0007" = 1\n'),),
                ("--title", "X"),
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
                            SLICE_ROW.format(1, "Clean", 'done_when = "D"\n')
                            + SLICE_ROW.format(2, "Dirty", 'done_when = "one\\u000Btwo"\n')
                        ),
                    ),
                ),
                ("--row", "2"),
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
                            SLICE_ROW.format(1, "Clean", 'done_when = "D"\n')
                            + SLICE_ROW.format(2, "Dirty", 'done_when = "one\\u001Btwo"\n')
                        ),
                    ),
                ),
                ("--row", "2"),
            ),
        ),
        *rendered(
            "other-row-title-control-is-cut-around",
            cut(
                MINIMAL_BLOCK_TOML
                + (
                    SLICE_ROW.format(1, "Good row", 'done_when = "Clean."\n')
                    + SLICE_ROW.format(2, "Bad\\u000Btitle", "")
                ),
                (),
                1,
                "Good row",
                CHILD_BODY.format("Clean.", ""),
                {
                    79: block_body(
                        MINIMAL_BLOCK_TOML
                        + "\n"
                        + SLICE_ROW.format(2, "Bad\\u000Btitle", "").rstrip("\n")
                    )
                },
            ),
        ),
        *rendered(
            "other-row-done-when-control-is-cut-around",
            cut(
                MINIMAL_BLOCK_TOML
                + (
                    SLICE_ROW.format(1, "Good row", 'done_when = "Clean."\n')
                    + SLICE_ROW.format(2, "Other", 'done_when = "a\\u001B[2Jb"\n')
                ),
                (),
                1,
                "Good row",
                CHILD_BODY.format("Clean.", ""),
                {
                    79: block_body(
                        MINIMAL_BLOCK_TOML
                        + "\n"
                        + SLICE_ROW.format(2, "Other", 'done_when = "a\\u001B[2Jb"').rstrip("\n")
                    )
                },
            ),
        ),
    ],
)
def test_cut_requires_a_valid_block_for_the_row_it_cuts(case: CutCase, cut_check: CutCheck) -> None:
    """Spec: CUT-05, CUT-39, BODY-68, E-CUT-03."""
    cut_check(case)


@pytest.mark.parametrize(
    "case",
    [
        *rendered(
            "row-selected-by-number",
            cut(
                MINIMAL_BLOCK_TOML
                + (
                    SLICE_ROW.format(1, "Scheibe 1", 'done_when = "D"\n')
                    + SLICE_ROW.format(2, "Scheibe 2", 'done_when = "D"\n')
                ),
                ("--row", "2"),
                2,
                "Scheibe 2",
                CHILD_BODY.format("D", ""),
                {
                    79: block_body(
                        MINIMAL_BLOCK_TOML
                        + "\n"
                        + SLICE_ROW.format(1, "Scheibe 1", 'done_when = "D"').rstrip("\n")
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
                        79,
                        MINIMAL_BLOCK_TOML + SLICE_ROW.format(1, "Scheibe 1", 'done_when = "D"\n'),
                    ),
                ),
                ("--title", "Wrong title"),
            ),
        ),
        *rendered(
            "row-number-without-a-slice-table",
            refused(
                "#79 has no slice table; --row needs one to select a row from",
                "precondition_failed",
                (container_issue(79, MINIMAL_BLOCK_TOML),),
                ("--title", "X", "--row", "1"),
            ),
        ),
        *rendered(
            "row-number-not-in-the-table",
            refused(
                "#79 has no row 9; cuttable rows: 1",
                "precondition_failed",
                (
                    container_issue(
                        79,
                        MINIMAL_BLOCK_TOML + SLICE_ROW.format(1, "Scheibe 1", 'done_when = "D"\n'),
                    ),
                ),
                ("--row", "9"),
            ),
        ),
        *rendered(
            "row-number-in-an-empty-table",
            refused(
                "#79 has no row 9; cuttable rows: none",
                "precondition_failed",
                (container_issue(79, MINIMAL_BLOCK_TOML + "slice = []\n"),),
                ("--row", "9"),
            ),
        ),
        *rendered(
            "no-title-without-a-slice-key",
            refused(
                "#79 has no slice row; pass --title",
                "precondition_failed",
                (container_issue(79, MINIMAL_BLOCK_TOML),),
                (),
            ),
        ),
        *rendered(
            "no-title-with-an-empty-slice",
            refused(
                "#79 has no slice row; pass --title",
                "precondition_failed",
                (container_issue(79, MINIMAL_BLOCK_TOML + "slice = []\n"),),
                (),
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
                    SLICE_ROW.format(1, "Scheibe 1", 'done_when = "D"\n')
                    + SLICE_ROW.format(2, "Scheibe 2", 'done_when = "D"\n')
                ),
                (),
                1,
                "Scheibe 1",
                CHILD_BODY.format("D", ""),
                {
                    79: block_body(
                        MINIMAL_BLOCK_TOML
                        + "\n"
                        + SLICE_ROW.format(2, "Scheibe 2", 'done_when = "D"').rstrip("\n")
                    )
                },
            ),
        ),
        *rendered(
            "row-without-done-when",
            cut(
                MINIMAL_BLOCK_TOML + SLICE_ROW.format(1, "Scheibe 1", ""),
                (),
                1,
                "Scheibe 1",
                CHILD_BODY.format("", ""),
                ROW_REMOVED,
            ),
        ),
        *rendered(
            "untied-without-a-slice-key",
            cut(
                MINIMAL_BLOCK_TOML,
                ("--title", "Untied"),
                None,
                "Untied",
                CHILD_BODY.format("", ""),
                {},
            ),
        ),
        *rendered(
            "untied-with-an-empty-slice",
            cut(
                MINIMAL_BLOCK_TOML + "slice = []\n",
                ("--title", "Untied"),
                None,
                "Untied",
                CHILD_BODY.format("", ""),
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
                MINIMAL_BLOCK_TOML + SLICE_ROW.format(1, "Scheibe 1", 'done_when = "D"\n'),
                ("--scope", "src/c.py"),
                1,
                "Scheibe 1",
                CHILD_BODY.format("D", '\nscope = ["src/c.py"]\n'),
                ROW_REMOVED,
            ),
        ),
        *rendered(
            "inherits-the-rows-scope",
            cut(
                MINIMAL_BLOCK_TOML
                + SLICE_ROW.format(1, "Slice C", 'done_when = "D"\nscope = ["src/c.py"]\n'),
                (),
                1,
                "Slice C",
                CHILD_BODY.format("D", '\nscope = ["src/c.py"]\n'),
                ROW_REMOVED,
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
                        + SLICE_ROW.format(1, "Slice C", 'done_when = "D"\nscope = ["src/c.py"]\n'),
                    ),
                ),
                ("--scope", "src/other.py"),
            ),
        ),
        *rendered(
            "no-row-takes-the-scope-directly",
            cut(
                MINIMAL_BLOCK_TOML,
                ("--title", "Loose Cut", "--scope", "src/loose.py"),
                None,
                "Loose Cut",
                CHILD_BODY.format("", '\nscope = ["src/loose.py"]\n'),
                {},
            ),
        ),
    ],
)
def test_cut_fills_inherits_or_refuses_the_scope(case: CutCase, cut_check: CutCheck) -> None:
    """Spec: CUT-20, CUT-21, CUT-22, CUT-23, E-CUT-06."""
    cut_check(case)


@pytest.mark.parametrize(
    "case",
    [
        *rendered(
            "linked-open-child",
            with_linked_child(adopted(950, linked=False), 950, workboard.ChildState.OPEN),
        ),
        *rendered(
            "orphan-of-an-interrupted-cut",
            adopted(950, linked=True, issues=(child_issue(950),)),
        ),
        *rendered(
            "orphan-titled-in-another-case",
            refused(
                "possible twin #951; pass --not-a-twin",
                "precondition_failed",
                (container_issue(79, ONE_ROW), child_issue(951, "slice a")),
                ("--title", "Slice A"),
                searched=True,
            ),
        ),
        *rendered(
            "linked-child-with-another-title",
            with_linked_child(
                cut(
                    ONE_ROW,
                    ("--title", "Slice A"),
                    1,
                    "Slice A",
                    CHILD_BODY.format("D", ""),
                    ROW_REMOVED,
                ),
                950,
                workboard.ChildState.OPEN,
                "Slice B",
            ),
        ),
        *rendered(
            "closed-child",
            with_linked_child(
                refused(
                    "#79 already has a closed child #950 titled 'Slice A'; "
                    "reopen it or remove the row by hand",
                    "precondition_failed",
                    (container_issue(79, ONE_ROW),),
                    ("--title", "Slice A"),
                ),
                950,
                workboard.ChildState.CLOSED,
            ),
        ),
        *rendered(
            "two-open-matches",
            with_linked_child(
                refused(
                    "#79's row 'Slice A' matches more than one open issue (#950, #951); "
                    "adopt the right one by hand and remove the row",
                    "precondition_failed",
                    (container_issue(79, ONE_ROW), child_issue(951)),
                    ("--title", "Slice A"),
                ),
                950,
                workboard.ChildState.OPEN,
            ),
        ),
    ],
)
def test_cut_adopts_the_open_child_instead_of_creating_one(
    case: CutCase, cut_check: CutCheck
) -> None:
    """Spec: CUT-13, CUT-14, CUT-15, CUT-16, CUT-31, CUT-38, E-CUT-05."""
    cut_check(case)


def created_beside(issue: workboard.Issue) -> CutCase:
    case = cut(
        ONE_ROW,
        ("--title", "Slice A", "--not-a-twin"),
        1,
        "Slice A",
        CHILD_BODY.format("D", ""),
        ROW_REMOVED,
        searched=False,
    )
    return replace(case, issues=(*case.issues, issue))


@pytest.mark.parametrize(
    "case",
    [
        *rendered(
            "free-text-body",
            created_beside(board_issue(951, "Slice A", "Just an idea.", kind=body.ItemKind.TASK)),
        ),
        *rendered("labelled-idea", created_beside(child_issue(951, labels=("idea",)))),
        *rendered("names-another-container", created_beside(child_issue(951, parent=80))),
        *rendered("not-a-task", created_beside(child_issue(951, kind=body.ItemKind.FEATURE))),
    ],
)
def test_cut_never_adopts_an_issue_that_is_not_its_own_recovery_orphan(
    case: CutCase, cut_check: CutCheck
) -> None:
    """Spec: CUT-16, CUT-31, E-CUT-05."""
    cut_check(case)


@pytest.mark.parametrize(
    "case",
    [
        *rendered(
            "open-two-of-three-words", twin_of(951, "Scheibe 1", {951: "Scheibe 1 bauen"}, {})
        ),
        *rendered("closed-last-week", twin_of(85, "Import ledger", {}, {85: "Import the ledger"})),
        *rendered("closed-in-another-case", twin_of(952, "Scheibe 1", {}, {952: "scheibe 1"})),
        *rendered(
            "closest-then-lower-number",
            twin_of(
                952, "Scheibe 1", {951: "Scheibe 1 bauen", 953: "Scheibe 1"}, {952: "Scheibe 1"}
            ),
        ),
        *rendered(
            "three-of-five-words",
            twin_of(951, "Scheibe 1 bauen", {951: "Scheibe 1 bauen und testen"}, {}),
        ),
        *rendered("identical-wordless-title", twin_of(951, "!!!", {951: "!!!"}, {})),
        *rendered(
            "title-taken-from-the-row",
            replace(
                twin_of(951, "Import ledger", {951: "Import ledger"}, {}),
                issues=(
                    container_issue(
                        79,
                        MINIMAL_BLOCK_TOML
                        + SLICE_ROW.format(1, "Import the ledger", 'done_when = "D"\n'),
                    ),
                    board_issue(951, "Import ledger", "Some work."),
                ),
                arguments=(),
            ),
        ),
        *rendered("one-of-three-words", no_twin("Scheibe 1", {951: "Scheibe 2"}, {})),
        *rendered("two-of-four-words", no_twin("Scheibe 1 bauen", {951: "Scheibe 1 testen"}, {})),
        *rendered("different-wordless-titles", no_twin("!!!", {951: "???"}, {})),
        *rendered(
            "not-a-twin-skips-the-search",
            replace(
                no_twin("Scheibe 1", {951: "Scheibe 1"}, {}),
                arguments=("--title", "Scheibe 1", "--not-a-twin"),
                closed_issue_cutoffs=(),
            ),
        ),
        *rendered(
            "the-container-is-no-twin",
            replace(
                no_twin("Slice A", {}, {}),
                issues=(replace(container_issue(79, MINIMAL_BLOCK_TOML), title="Slice A"),),
            ),
        ),
    ],
)
def test_cut_refuses_a_child_whose_title_twins_an_open_or_recently_closed_issue(
    case: CutCase, cut_check: CutCheck
) -> None:
    """Spec: CUT-29, CUT-30, CUT-31, E-CUT-05, E-CUT-09."""
    cut_check(case)


RELATION_FAILS = (
    "created #900 but failed to record #900 as a sub-issue of #79: "
    "relation POST failed (simulated); re-run the same cut -- it adopts the child"
)
ROW_REMOVAL_FAILS = (
    "created #900 but failed to remove row 1 from #79's aco block: "
    "update item body failed (simulated); re-run the same cut -- it adopts the child"
)
TYPE_DROPPED = (
    "created #900 but GitHub did not set its type Task; "
    "set that type on the forge by hand, then re-run the same cut -- it adopts the child"
)


@pytest.mark.parametrize(
    "case",
    [
        *rendered(
            "relation-write-fails",
            partial(
                RELATION_FAILS, "record #900 as a sub-issue of #79", ForgeEvent.RELATION_WRITE_FAILS
            ),
        ),
        *rendered(
            "row-removal-fails",
            partial(
                ROW_REMOVAL_FAILS, "remove row 1 from #79's aco block", ForgeEvent.ROW_REMOVAL_FAILS
            ),
        ),
        *rendered(
            "issue-type-dropped",
            partial(TYPE_DROPPED, "set #900's type Task", ForgeEvent.ISSUE_TYPE_DROPPED),
        ),
    ],
)
def test_cut_names_the_child_it_created_when_a_later_write_fails(
    case: CutCase, cut_check: CutCheck
) -> None:
    """Spec: CUT-17, CUT-18, CUT-28, CUT-32, E-CUT-08."""
    cut_check(case)


def twin_refusal(number: int) -> CutCase:
    case = refused(
        f"possible twin #{number}; pass --not-a-twin",
        "precondition_failed",
        (),
        ("--title", "Slice A"),
        searched=True,
    )
    return replace(
        case,
        created_children=((79, "Slice A", CHILD_BODY.format("D", ""), body.ItemKind.TASK),),
        created_issues=(("Slice A", CHILD_BODY.format("D", ""), body.ItemKind.TASK),),
        closed_issue_cutoffs=(TWIN_SEARCH_START, TWIN_SEARCH_START),
        events=(ForgeEvent.WRITES_RECOVER,),
    )


def rerun(*events: ForgeEvent) -> CutCase:
    return replace(
        adopted(900, linked=True),
        issues=(),
        created_children=((79, "Slice A", CHILD_BODY.format("D", ""), body.ItemKind.TASK),),
        created_issues=(("Slice A", CHILD_BODY.format("D", ""), body.ItemKind.TASK),),
        closed_issue_cutoffs=(TWIN_SEARCH_START,),
        events=events,
    )


@pytest.mark.parametrize(
    "case",
    [
        *rendered(
            "relation-failure",
            then(
                partial(
                    RELATION_FAILS,
                    "record #900 as a sub-issue of #79",
                    ForgeEvent.RELATION_WRITE_FAILS,
                ),
                replace(rerun(ForgeEvent.WRITES_RECOVER), linked_children=((79, 900), (79, 900))),
            ),
        ),
        *rendered(
            "relation-failure-with-a-crlf-body",
            then(
                partial(
                    RELATION_FAILS,
                    "record #900 as a sub-issue of #79",
                    ForgeEvent.RELATION_WRITE_FAILS,
                ),
                replace(
                    rerun(ForgeEvent.WRITES_RECOVER, ForgeEvent.BODIES_READ_AS_CRLF),
                    linked_children=((79, 900), (79, 900)),
                    item_bodies={79: ROW_REMOVED[79].replace("\n", "\r\n")},
                ),
            ),
        ),
        *rendered(
            "row-removal-failure",
            then(
                partial(
                    ROW_REMOVAL_FAILS,
                    "remove row 1 from #79's aco block",
                    ForgeEvent.ROW_REMOVAL_FAILS,
                ),
                replace(
                    rerun(ForgeEvent.WRITES_RECOVER, ForgeEvent.NEW_CHILD_READABLE),
                    linked_children=((79, 900),),
                ),
            ),
        ),
        *rendered(
            "dropped-type-is-a-twin-until-set",
            then(
                partial(TYPE_DROPPED, "set #900's type Task", ForgeEvent.ISSUE_TYPE_DROPPED),
                twin_refusal(900),
                replace(
                    rerun(ForgeEvent.ISSUE_TYPE_SET_BY_HAND),
                    closed_issue_cutoffs=(TWIN_SEARCH_START, TWIN_SEARCH_START),
                    linked_children=((79, 900),),
                ),
            ),
        ),
    ],
)
def test_cut_rerun_adopts_the_child_a_failed_cut_left_behind(
    case: CutCase, cut_check: CutCheck
) -> None:
    """Spec: BODY-07, CUT-16, CUT-19, CUT-30, CUT-31, CUT-38."""
    cut_check(case)
