"""Worlds, cases and the `check_pull_request` fixture of the `aco check <pr>` tests."""

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY
from cli_fixtures import real_git, run_cli, track_board_config
from github_fixtures import (
    LANDING_BRANCH,
    MERGE_COMMIT_SHA,
    WORK_ITEM_ISSUE,
    FakeForge,
    assert_github_world,
    landing_pull_request,
    serve_forge,
)
from store_fixtures import claim_intent, publish_claims_from_a_second_clone

from aco import body, forge, protocol, workboard

ITEM_CLAIM = claim_intent(
    identity=protocol.IssueIdentity(72), branch=LANDING_BRANCH, scope=("README.md",)
)
LANE_BRANCH = "docs/tidy-readme"
LANE_CLAIM = claim_intent(
    identity=protocol.LaneIdentity(),
    branch=LANE_BRANCH,
    scope=("README.md", "pyproject.toml", "uv.lock", ".github/workflows", "src/x.py"),
)
WORK_ITEM = f"{REPOSITORY}#72"
PARENT_ISSUE = 79
PARENT = f"{REPOSITORY}#{PARENT_ISSUE}"
README_LISTING = forge.PullRequestChanges(
    forge.ListingReading(MERGE_COMMIT_SHA, 1),
    forge.ListingReading(MERGE_COMMIT_SHA, 1),
    (forge.ChangedFile("README.md", None),),
)


@dataclass(frozen=True)
class ParentWorld:
    text: str
    other_open_children: int = 0
    foreign_open_children: int = 0
    closed_children: int = 0
    kind: body.ItemKind | None = body.ItemKind.CONTAINER
    repository: str = REPOSITORY


@dataclass(frozen=True)
class PullRequestWorld:
    claims: tuple[protocol.ClaimIntent, ...] = (ITEM_CLAIM,)
    head_branch: str = LANDING_BRANCH
    head_repository: str = REPOSITORY
    target_branch: str = "main"
    default_branch: str = "main"
    dependency_paths: tuple[str, ...] = ()
    lane_shared: tuple[str, ...] = ()
    listing: forge.PullRequestChanges | forge.ForgeError = README_LISTING
    parent: ParentWorld | None = None


ITEM_WORLD = PullRequestWorld()
LANE_WORLD = PullRequestWorld(claims=(LANE_CLAIM,), head_branch=LANE_BRANCH)


@dataclass(frozen=True)
class PullRequestCase:
    body: str
    exit: int
    stdout: str
    stderr: str
    envelope: dict[str, object]
    forge_requests: int
    world: PullRequestWorld
    changes_reads: tuple[int, ...] = ()
    json_stderr: str = ""


@dataclass(frozen=True)
class WriteTrace:
    clone_refs: tuple[str, ...]
    remote_refs: str
    created_children: tuple[tuple[int, str, str, body.ItemKind], ...]
    created_issues: tuple[tuple[str, str, body.ItemKind], ...]
    linked_children: tuple[tuple[int, int], ...]
    item_bodies: dict[int, str]
    body_writes: tuple[tuple[int, str], ...]
    retyped_items: tuple[tuple[int, body.ItemKind], ...]
    merge_requests: tuple[tuple[str, workboard.MergeMethod], ...]
    merge_calls: tuple[tuple[int, str, workboard.MergeMethod, str, str], ...]
    deleted_branches: tuple[str, ...]
    landing_comments: dict[int, str]
    closed_issues: frozenset[int]
    landings: dict[int, forge.Landing]


@dataclass(frozen=True)
class PullRequestObservation:
    exit: int | str | None
    stdout: str
    stderr: str
    forge_requests: int
    changes_reads: tuple[int, ...]
    written: WriteTrace


def declares(
    body: str,
    label: str,
    forge_requests: int,
    world: PullRequestWorld = ITEM_WORLD,
    changes_reads: tuple[int, ...] = (),
) -> PullRequestCase:
    """An accepted declaration has read the listing once; only `deps` rows count that read."""
    already_counted = bool(changes_reads)
    return PullRequestCase(
        body=body,
        exit=0,
        stdout=f"PR #12 by ada declares {label}\n",
        stderr="",
        envelope={"ok": True, "reason": "valid", "kind": "pull_request", "number": 12},
        forge_requests=forge_requests if already_counted else forge_requests + 1,
        world=world,
        changes_reads=(12,),
    )


def refused(
    body: str,
    message: str,
    forge_requests: int,
    world: PullRequestWorld = ITEM_WORLD,
    changes_reads: tuple[int, ...] = (),
) -> PullRequestCase:
    return PullRequestCase(
        body=body,
        exit=2,
        stdout="",
        stderr=f"REFUSED: pull request #12 {message}\n",
        envelope={
            "ok": False,
            "reason": "invalid_classification",
            "kind": "pull_request",
            "number": 12,
            "message": message,
        },
        forge_requests=forge_requests,
        world=world,
        changes_reads=changes_reads,
    )


def unavailable(
    body: str,
    message: str,
    forge_requests: int,
    world: PullRequestWorld,
    changes_reads: tuple[int, ...],
) -> PullRequestCase:
    return PullRequestCase(
        body=body,
        exit=2,
        stdout="",
        stderr=f"ERROR: {message}\n",
        envelope={"ok": False, "reason": "unavailable", "message": message},
        forge_requests=forge_requests,
        world=world,
        changes_reads=changes_reads,
        json_stderr=f"ERROR: {message}\n",
    )


def rendered(rows: dict[str, PullRequestCase]) -> list[object]:
    return [
        param
        for identifier, case in rows.items()
        for param in (
            pytest.param(case, [], id=identifier),
            pytest.param(
                replace(case, stdout=json.dumps(case.envelope) + "\n", stderr=case.json_stderr),
                ["--json"],
                id=identifier + "-json",
            ),
        )
    ]


def parent_of_work_item(parent: ParentWorld | None) -> dict[int, workboard.ParentIssue]:
    if parent is None:
        return {}
    reference = workboard.IssueReference(parent.repository, PARENT_ISSUE)
    return {WORK_ITEM_ISSUE: workboard.ParentIssue(reference, parent.text, parent.kind)}


def children_of_parent(parent: ParentWorld | None) -> dict[int, workboard.ChildList]:
    if parent is None:
        return {}
    open_numbers = (WORK_ITEM_ISSUE, *range(73, 73 + parent.other_open_children))
    closed_numbers = range(90, 90 + parent.closed_children)
    return {
        PARENT_ISSUE: (
            *(workboard.ChildItem(n, workboard.ChildState.OPEN, "Child") for n in open_numbers),
            *(
                workboard.ForeignChild(
                    workboard.IssueReference("other/repo", number), workboard.ChildState.OPEN
                )
                for number in range(954, 954 + parent.foreign_open_children)
            ),
            *(
                workboard.ChildItem(number, workboard.ChildState.CLOSED, "Child")
                for number in closed_numbers
            ),
        )
    }


def assert_parent_arranged(forge_world: FakeForge, parent: ParentWorld | None) -> None:
    if parent is None:
        assert (forge_world.parents, forge_world.children) == ({}, {})
        return
    assert set(forge_world.parents) == {WORK_ITEM_ISSUE}
    listed = forge_world.children.get(PARENT_ISSUE, ())
    children = workboard.local_children(listed)
    open_numbers = [child.number for child in children if child.state is workboard.ChildState.OPEN]
    closed_numbers = [
        child.number for child in children if child.state is workboard.ChildState.CLOSED
    ]
    assert WORK_ITEM_ISSUE in open_numbers
    assert len(open_numbers) - 1 == parent.other_open_children
    assert len(closed_numbers) == parent.closed_children
    assert len({*open_numbers, *closed_numbers}) == len(children)
    assert len(listed) - len(children) == parent.foreign_open_children


def written_by(forge_world: FakeForge, clone: Path, remote: Path) -> WriteTrace:
    return WriteTrace(
        clone_refs=tuple(
            record
            for record in real_git(
                clone, "for-each-ref", "--format=%(refname) %(objectname)"
            ).stdout.splitlines()
            if record.split(" ", 1)[0] != "refs/worktree/aco/state"
        ),
        remote_refs=real_git(remote, "for-each-ref").stdout,
        created_children=tuple(forge_world.created_children),
        created_issues=tuple(forge_world.created_issues),
        linked_children=tuple(forge_world.linked_children),
        item_bodies=dict(forge_world.item_bodies),
        body_writes=tuple(forge_world.body_writes),
        retyped_items=tuple(forge_world.retyped_items),
        merge_requests=tuple(forge_world.merge_requests),
        merge_calls=tuple(forge_world.merge_calls),
        deleted_branches=tuple(forge_world.deleted_branches),
        landing_comments=dict(forge_world.landing_comments),
        closed_issues=frozenset(forge_world.closed_issues),
        landings=dict(forge_world.landings),
    )


Flags = list[str]
PullRequestCheck = Callable[[PullRequestCase, Flags], None]


@pytest.fixture
def check_pull_request(
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> PullRequestCheck:
    monkeypatch.setenv("LC_ALL", "C")
    assert_github_world(github_clone, bare_remote)

    def check(case: PullRequestCase, flags: Flags) -> None:
        if case.world.dependency_paths or case.world.lane_shared:
            track_board_config(
                github_clone,
                f"dependency_paths = {json.dumps(list(case.world.dependency_paths))}\n"
                f"lane_shared = {json.dumps(list(case.world.lane_shared))}\n",
            )
            real_git(github_clone, "push", "-q", "origin", "main")
        tracked = real_git(github_clone, "show", f"HEAD:{workboard.CONFIG_PATH}").stdout
        configured = workboard.parse_config(tracked, workboard.CONFIG_PATH)
        assert configured.dependency_paths == case.world.dependency_paths
        assert configured.lane_shared == case.world.lane_shared
        seeded = publish_claims_from_a_second_clone(github_clone, bare_remote, case.world.claims)
        assert tuple((claim.identity, claim.branch) for claim in seeded.claims.values()) == tuple(
            (claim.identity, claim.branch) for claim in case.world.claims
        )
        forge_world = serve_forge(
            monkeypatch,
            FakeForge(
                landings={
                    12: landing_pull_request(
                        body=case.body,
                        head_ref_name=case.world.head_branch,
                        head_repository=case.world.head_repository,
                        base_ref_name=case.world.target_branch,
                    )
                },
                changes_by_number={12: case.world.listing},
                default_branch_name=case.world.default_branch,
                parents=parent_of_work_item(case.world.parent),
                children=children_of_parent(case.world.parent),
            ),
        )
        assert_parent_arranged(forge_world, case.world.parent)
        before = written_by(forge_world, github_clone, bare_remote)
        result = run_cli(["check", "12", *flags], capsys)
        observed = PullRequestObservation(
            result.status,
            result.stdout,
            result.stderr,
            forge_world.requests,
            tuple(forge_world.changes_reads),
            written_by(forge_world, github_clone, bare_remote),
        )
        expected = PullRequestObservation(
            case.exit, case.stdout, case.stderr, case.forge_requests, case.changes_reads, before
        )
        assert observed == expected

    return check
