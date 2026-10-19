"""`aco check <pr>`: classification, claims and closing references in the real GitHub world."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY
from cli_fixtures import real_git, run_cli
from github_fixtures import (
    LANDING_BRANCH,
    MERGE_COMMIT_SHA,
    FakeForge,
    assert_github_world,
    landing_pull_request,
    serve_forge,
)
from store_fixtures import claim_intent, publish_claims_from_a_second_clone

from agent_coordination import forge, protocol

ITEM_CLAIM = claim_intent(identity=protocol.IssueIdentity(72), branch=LANDING_BRANCH)
LANE_BRANCH = "docs/tidy-readme"
LANE_CLAIM = claim_intent(identity=protocol.LaneIdentity(), branch=LANE_BRANCH)
WORK_ITEM = f"{REPOSITORY}#72"
README_LISTING = forge.PullRequestChanges(
    forge.ListingReading(MERGE_COMMIT_SHA, 1),
    forge.ListingReading(MERGE_COMMIT_SHA, 1),
    (forge.ChangedFile("README.md", None),),
)


@dataclass(frozen=True)
class PullRequestWorld:
    claims: tuple[protocol.ClaimIntent, ...] = (ITEM_CLAIM,)
    head_branch: str = LANDING_BRANCH
    head_repository: str = REPOSITORY
    target_branch: str = "main"
    default_branch: str = "main"


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


@dataclass(frozen=True)
class PullRequestObservation:
    exit: int | str | None
    stdout: str
    stderr: str
    forge_requests: int
    changes_reads: tuple[int, ...]
    written: tuple[object, ...]


def declares(
    body: str, label: str, forge_requests: int, world: PullRequestWorld = ITEM_WORLD
) -> PullRequestCase:
    return PullRequestCase(
        body=body,
        exit=0,
        stdout=f"PR #12 by ada declares {label}\n",
        stderr="",
        envelope={"ok": True, "reason": "valid", "kind": "pull_request", "number": 12},
        forge_requests=forge_requests,
        world=world,
    )


def refused(
    body: str, message: str, forge_requests: int, world: PullRequestWorld = ITEM_WORLD
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
    )


def rendered(rows: dict[str, PullRequestCase]) -> list[object]:
    return [
        param
        for identifier, case in rows.items()
        for param in (
            pytest.param(case, [], id=identifier),
            pytest.param(
                replace(case, stdout=json.dumps(case.envelope) + "\n", stderr=""),
                ["--json"],
                id=identifier + "-json",
            ),
        )
    ]


def written_by(forge_world: FakeForge, clone: Path, remote: Path) -> tuple[object, ...]:
    return (
        tuple(
            record
            for record in real_git(
                clone, "for-each-ref", "--format=%(refname) %(objectname)"
            ).stdout.splitlines()
            if record.split(" ", 1)[0] != "refs/worktree/aco/state"
        ),
        real_git(remote, "for-each-ref").stdout,
        tuple(forge_world.created_children),
        tuple(forge_world.created_issues),
        tuple(forge_world.linked_children),
        dict(forge_world.item_bodies),
        tuple(forge_world.body_writes),
        tuple(forge_world.retyped_items),
        tuple(forge_world.merge_requests),
        tuple(forge_world.merge_calls),
        tuple(forge_world.deleted_branches),
        dict(forge_world.landing_comments),
        frozenset(forge_world.closed_issues),
        dict(forge_world.landings),
    )


PullRequestCheck = Callable[[PullRequestCase, list[str]], None]


@pytest.fixture
def check_pull_request(
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> PullRequestCheck:
    monkeypatch.setenv("LC_ALL", "C")
    assert_github_world(github_clone, bare_remote)

    def check(case: PullRequestCase, flags: list[str]) -> None:
        publish_claims_from_a_second_clone(github_clone, bare_remote, case.world.claims)
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
                changes_by_number={12: README_LISTING},
                default_branch_name=case.world.default_branch,
            ),
        )
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
            case.exit, case.stdout, case.stderr, case.forge_requests, (), before
        )
        assert observed == expected

    return check


WORK_ITEM_BODY = "Work-Item: #72\n\nCloses #72"
NO_ITEM_BODY = "No-Item: docs\n\nTidy the README."
FORK = "fork/agent-coordination"
FORK_REFUSAL = f"proposes a branch of {FORK}; cross-repository pull requests are not classified"
NO_LINE = "carries no `Work-Item:` or `No-Item:` line"
TWO_LINES = "carries 2 classification lines; exactly one is required"
NO_CLAIM = f"has no active claim for #72 on branch {LANDING_BRANCH!r}"
NO_LANE = f"has no active issue-less lane claim on branch {LANE_BRANCH!r}"
FORK_WORLD = PullRequestWorld(head_repository=FORK)
OTHER_ITEM_BRANCH = claim_intent(identity=protocol.IssueIdentity(72), branch="codex/other-lane")
OTHER_LANE_BRANCH = claim_intent(identity=protocol.LaneIdentity(), branch="docs/another-lane")
ITEM_CLAIM_ON_LANE_BRANCH = claim_intent(identity=protocol.IssueIdentity(72), branch=LANE_BRANCH)

DECLARATIONS = {
    "qualified-work-item": declares(
        f"Work-Item: {WORK_ITEM}\n\nCloses #72", f"Work-Item: {WORK_ITEM}", 4
    ),
    "short-work-item": declares(
        f"Work-Item: #72\n\nCloses {WORK_ITEM}", f"Work-Item: {WORK_ITEM}", 4
    ),
    "implements-is-no-closing-reference": declares(
        "Work-Item: #72\n\nCloses #72\n\nImplements #80", f"Work-Item: {WORK_ITEM}", 4
    ),
    "documentation": declares(NO_ITEM_BODY, "No-Item: docs", 3, LANE_WORLD),
    "keyword-and-value-in-any-case": declares(
        "no-item:  DOCS \n\nTidy.", "No-Item: docs", 3, LANE_WORLD
    ),
}

CLASSIFICATION_REFUSALS = {
    "no-classification-line": refused("Advances #72\n\nJust some prose.", NO_LINE, 2),
    "classification-line-in-a-fence": refused(
        "Documents the convention:\n\n```\nWork-Item: #72\n```\n", NO_LINE, 2
    ),
    "work-item-and-no-item": refused("Work-Item: #72\nNo-Item: docs\n\nCloses #72", TWO_LINES, 2),
    "two-no-item-lines": refused("No-Item: docs\nNo-Item: fix\n", TWO_LINES, 2),
    "two-work-items": refused(
        "Work-Item: #72\nWork-Item: #73\n\nCloses #72\nCloses #73",
        "names two work items, #72 and #73; split it",
        2,
    ),
    "free-text-work-item": refused(
        "Work-Item: soon\n\nCloses #72",
        "carries `Work-Item: soon`; a work item reads OWNER/REPO#n or #n",
        2,
    ),
    "bare-number-work-item": refused(
        "Work-Item: 72\n\nCloses #72",
        "carries `Work-Item: 72`; a work item reads OWNER/REPO#n or #n",
        2,
    ),
    "unknown-no-item-kind": refused(
        "No-Item: chore\n\nHousekeeping.",
        "carries `No-Item: chore`; an issue-less pull request is docs, fix, or deps",
        2,
    ),
    "branch-of-another-repository": refused(WORK_ITEM_BODY, FORK_REFUSAL, 2, FORK_WORLD),
    "branch-of-another-repository-for-deps": refused("No-Item: deps", FORK_REFUSAL, 2, FORK_WORLD),
    "branch-of-another-repository-before-the-body": refused(
        "Advances #72", FORK_REFUSAL, 2, FORK_WORLD
    ),
    "not-the-default-branch": refused(
        WORK_ITEM_BODY,
        "targets 'release', not the default branch 'trunk'",
        3,
        PullRequestWorld(target_branch="release", default_branch="trunk"),
    ),
}

CLAIM_AND_CLOSING_REFUSALS = {
    "work-item-of-another-repository": refused(
        "Work-Item: other/repo#5\n\nCloses other/repo#5",
        "names work item other/repo#5 of another repository, which holds no claim here",
        3,
    ),
    "work-item-claimed-on-another-branch": refused(
        WORK_ITEM_BODY, NO_CLAIM, 3, PullRequestWorld(claims=(OTHER_ITEM_BRANCH,))
    ),
    "work-item-without-any-claim": refused(
        WORK_ITEM_BODY, NO_CLAIM, 3, PullRequestWorld(claims=())
    ),
    "lane-claimed-on-another-branch": refused(
        NO_ITEM_BODY,
        NO_LANE,
        3,
        PullRequestWorld(claims=(OTHER_LANE_BRANCH,), head_branch=LANE_BRANCH),
    ),
    "item-claim-on-the-head-branch": refused(
        NO_ITEM_BODY,
        NO_LANE,
        3,
        PullRequestWorld(claims=(ITEM_CLAIM_ON_LANE_BRANCH,), head_branch=LANE_BRANCH),
    ),
    "lane-without-any-claim": refused(
        NO_ITEM_BODY, NO_LANE, 3, PullRequestWorld(claims=(), head_branch=LANE_BRANCH)
    ),
    "issue-less-closing-reference": refused(
        "No-Item: fix\n\nCloses #72",
        f"declares no work item but closes {WORK_ITEM}; name it as the work item",
        3,
        LANE_WORLD,
    ),
    "lane-claim-before-closing-reference": refused(
        "No-Item: fix\n\nCloses #72",
        NO_LANE,
        3,
        PullRequestWorld(claims=(), head_branch=LANE_BRANCH),
    ),
    "missing-closing-reference": refused(
        "Work-Item: #72\n\nNo closing keyword here.",
        f"carries no closing reference for its work item {WORK_ITEM}",
        4,
    ),
    "closing-another-item": refused(
        "Work-Item: #72\n\nCloses #72\nCloses #99",
        f"closes {REPOSITORY}#99 besides its work item {WORK_ITEM}; a pull request lands one item",
        4,
    ),
}


@pytest.mark.parametrize(("case", "flags"), rendered(DECLARATIONS))
def test_a_pull_request_declaring_a_claimed_item_or_lane_is_accepted(
    case: PullRequestCase, flags: list[str], check_pull_request: PullRequestCheck
) -> None:
    """Spec: LAND-04, LAND-05, LAND-20, CHECK-01"""
    check_pull_request(case, flags)


@pytest.mark.parametrize(("case", "flags"), rendered(CLASSIFICATION_REFUSALS))
def test_a_pull_request_without_one_valid_classification_is_refused(
    case: PullRequestCase, flags: list[str], check_pull_request: PullRequestCheck
) -> None:
    """Spec: LAND-06, LAND-07, LAND-08, LAND-09, LAND-10, LAND-11, LAND-12, LAND-13, CHECK-01"""
    check_pull_request(case, flags)


@pytest.mark.parametrize(("case", "flags"), rendered(CLAIM_AND_CLOSING_REFUSALS))
def test_a_pull_request_without_its_claim_or_its_own_closing_reference_is_refused(
    case: PullRequestCase, flags: list[str], check_pull_request: PullRequestCheck
) -> None:
    """Spec: LAND-14, LAND-15, LAND-16, LAND-17, LAND-18, LAND-19, CHECK-01"""
    check_pull_request(case, flags)
