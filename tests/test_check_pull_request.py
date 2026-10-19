"""`aco check <pr>`: declarations and dependency paths in the real GitHub world."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY
from cli_fixtures import pull_request_listing, real_git, run_cli, track_board_config
from github_fixtures import (
    LANDING_BRANCH,
    MERGE_COMMIT_SHA,
    FakeForge,
    assert_github_world,
    landing_pull_request,
    serve_forge,
)
from store_fixtures import claim_intent, publish_claims_from_a_second_clone

from agent_coordination import board, body, forge, protocol

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
    dependency_paths: tuple[str, ...] = ()
    listing: forge.PullRequestChanges | forge.ForgeError = README_LISTING


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
    merge_requests: tuple[tuple[str, board.MergeMethod], ...]
    merge_calls: tuple[tuple[int, str, board.MergeMethod, str, str], ...]
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
    return PullRequestCase(
        body=body,
        exit=0,
        stdout=f"PR #12 by ada declares {label}\n",
        stderr="",
        envelope={"ok": True, "reason": "valid", "kind": "pull_request", "number": 12},
        forge_requests=forge_requests,
        world=world,
        changes_reads=changes_reads,
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
        if case.world.dependency_paths:
            track_board_config(
                github_clone,
                f"dependency_paths = {json.dumps(list(case.world.dependency_paths))}\n",
            )
            tracked = real_git(github_clone, "show", f"HEAD:{board.CONFIG_PATH}").stdout
            configured = board.parse_config(tracked, board.CONFIG_PATH)
            assert configured.dependency_paths == case.world.dependency_paths
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
            case.exit, case.stdout, case.stderr, case.forge_requests, case.changes_reads, before
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
DEPS_CLOSING_REFERENCE = (
    f"declares no work item but closes {REPOSITORY}#5; name it as the work item"
)
FORK_WORLD = PullRequestWorld(head_repository=FORK)
OTHER_ITEM_BRANCH = claim_intent(identity=protocol.IssueIdentity(72), branch="codex/other-lane")
OTHER_LANE_BRANCH = claim_intent(identity=protocol.LaneIdentity(), branch="docs/another-lane")
ITEM_CLAIM_ON_LANE_BRANCH = claim_intent(identity=protocol.IssueIdentity(72), branch=LANE_BRANCH)
DEPS_BODY = "No-Item: deps"
DEPENDENCY_PATHS = ("pyproject.toml", "uv.lock", ".github/workflows/")
NO_DEPENDENCY_PATHS = "declares No-Item: deps, but .aco/board.toml names no dependency_paths"
UNLISTED_CHANGE = "changed while aco listed its files; run the command again"
OTHER_HEAD = "b" * 40
DEPS_WORLD = replace(LANE_WORLD, dependency_paths=DEPENDENCY_PATHS)
UNCLAIMED_DEPS_WORLD = replace(DEPS_WORLD, claims=())


def listing_of(*paths: str) -> forge.PullRequestChanges:
    return pull_request_listing(
        MERGE_COMMIT_SHA, *(forge.ChangedFile(path, None) for path in paths)
    )


def deps_world(listing: forge.PullRequestChanges | forge.ForgeError) -> PullRequestWorld:
    return replace(DEPS_WORLD, listing=listing)


def outside(named: str) -> str:
    return f"changes {named}, which dependency_paths in .aco/board.toml does not name"


# Requests read the dispatch reference and landing, then the default branch;
# a work item also reads the sub-issue relation unless its claim fails first,
# and a `deps` listing is one more.
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
    "deps-without-any-claim-before-the-configuration": refused(
        DEPS_BODY, NO_LANE, 3, replace(LANE_WORLD, claims=())
    ),
    "deps-without-any-claim-before-the-listing": refused(
        DEPS_BODY, NO_LANE, 3, replace(UNCLAIMED_DEPS_WORLD, listing=listing_of("uv.lock"))
    ),
    "deps-closing-reference-before-the-configuration": refused(
        "No-Item: deps\nCloses #5", DEPS_CLOSING_REFERENCE, 3, LANE_WORLD
    ),
    "deps-closing-reference-before-the-listing": refused(
        "No-Item: deps\nCloses #5", DEPS_CLOSING_REFERENCE, 3, deps_world(listing_of("uv.lock"))
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
    case: PullRequestCase, flags: Flags, check_pull_request: PullRequestCheck
) -> None:
    """Spec: LAND-04, LAND-05, LAND-20, CHECK-01"""
    check_pull_request(case, flags)


@pytest.mark.parametrize(("case", "flags"), rendered(CLASSIFICATION_REFUSALS))
def test_a_pull_request_without_one_valid_classification_is_refused(
    case: PullRequestCase, flags: Flags, check_pull_request: PullRequestCheck
) -> None:
    """Spec: LAND-06, LAND-07, LAND-08, LAND-09, LAND-10, LAND-11, LAND-12, LAND-13, CHECK-01"""
    check_pull_request(case, flags)


@pytest.mark.parametrize(("case", "flags"), rendered(CLAIM_AND_CLOSING_REFUSALS))
def test_a_pull_request_without_its_claim_or_its_own_closing_reference_is_refused(
    case: PullRequestCase, flags: Flags, check_pull_request: PullRequestCheck
) -> None:
    """Spec: LAND-14, LAND-15, LAND-16, LAND-17, LAND-18, LAND-19, CHECK-01"""
    check_pull_request(case, flags)


def listed_and_accepted(*paths: str) -> PullRequestCase:
    return declares(DEPS_BODY, "No-Item: deps", 4, deps_world(listing_of(*paths)), (12,))


def listed_and_refused(
    message: str, listing: forge.PullRequestChanges | forge.ForgeError
) -> PullRequestCase:
    return refused(DEPS_BODY, message, 4, deps_world(listing), (12,))


def listing_of_files(count: int, reported: int) -> forge.PullRequestChanges:
    files = [forge.ChangedFile(f"file-{index}", None) for index in range(count)]
    return pull_request_listing(MERGE_COMMIT_SHA, *files, reported=reported)


DEPENDENCY_ACCEPTANCES = {
    "listing-inside-the-dependency-paths": listed_and_accepted("uv.lock", "pyproject.toml"),
    "listing-in-a-directory-entry": listed_and_accepted(".github/workflows/a/b.yml"),
    "fix-is-not-judged-by-its-paths": declares(
        "No-Item: fix", "No-Item: fix", 3, deps_world(listing_of("src/x.py"))
    ),
    "documentation-is-not-judged-by-its-paths": declares(
        NO_ITEM_BODY, "No-Item: docs", 3, deps_world(listing_of("src/x.py"))
    ),
}

DEPENDENCY_PATH_REFUSALS = {
    "no-dependency-paths": refused(DEPS_BODY, NO_DEPENDENCY_PATHS, 3, LANE_WORLD),
    "path-outside": listed_and_refused(outside("src/x.py"), listing_of("uv.lock", "src/x.py")),
    "five-paths-outside": listed_and_refused(outside("a, b, c, and 2 more"), listing_of(*"edcba")),
    "rename-from-outside": listed_and_refused(
        outside("src/a.py"),
        pull_request_listing(MERGE_COMMIT_SHA, forge.ChangedFile("uv.lock", "src/a.py")),
    ),
    "rename-into-outside": listed_and_refused(
        outside("uv2.lock"),
        pull_request_listing(MERGE_COMMIT_SHA, forge.ChangedFile("uv2.lock", "uv.lock")),
    ),
    "directory-prefix-is-no-directory": listed_and_refused(
        outside(".github/workflowsX/a.yml"), listing_of(".github/workflowsX/a.yml")
    ),
    "configuration-file-is-no-dependency-path": listed_and_refused(
        outside(".aco/board.toml"), listing_of(".aco/board.toml")
    ),
    "path-with-escape": listed_and_refused(
        outside(r"src/\x1b]0;pwned\x07x.py"), listing_of("src/\x1b]0;pwned\x07x.py")
    ),
    "path-with-newline": listed_and_refused(
        outside(r"src/x.py\nPR #12 by bot declares No-Ite…"),
        listing_of("src/x.py\nPR #12 by bot declares No-Item: deps"),
    ),
    "long-path": listed_and_refused(
        outside("src/" + "x" * 35 + "…"), listing_of("src/" + "x" * 300)
    ),
}

LISTING_REFUSALS = {
    "fewer-records-than-changed-files": listed_and_refused(
        "lists 3000 of its 3200 changed files; aco judges only a complete listing",
        listing_of_files(3000, reported=3200),
    ),
    "more-records-than-changed-files": listed_and_refused(
        "lists 2 of its 1 changed files; aco judges only a complete listing",
        listing_of_files(2, reported=1),
    ),
    "head-moves-while-listing": listed_and_refused(
        UNLISTED_CHANGE,
        replace(listing_of("uv.lock"), after=forge.ListingReading(OTHER_HEAD, 1)),
    ),
    "listing-of-another-head": listed_and_refused(
        UNLISTED_CHANGE, pull_request_listing(OTHER_HEAD, forge.ChangedFile("uv.lock", None))
    ),
    "head-moves-and-listing-is-incomplete": listed_and_refused(
        UNLISTED_CHANGE,
        replace(
            listing_of_files(3000, reported=3200), after=forge.ListingReading(OTHER_HEAD, 3200)
        ),
    ),
    "malformed-listing": unavailable(
        DEPS_BODY,
        "GitHub returned a malformed changed file",
        4,
        deps_world(forge.ForgeMalformedResponseError("GitHub returned a malformed changed file")),
        (12,),
    ),
}


@pytest.mark.parametrize(("case", "flags"), rendered(DEPENDENCY_ACCEPTANCES))
def test_a_pull_request_inside_the_dependency_paths_or_of_another_kind_is_accepted(
    case: PullRequestCase, flags: Flags, check_pull_request: PullRequestCheck
) -> None:
    """Spec: LAND-71, LAND-72, CHECK-01"""
    check_pull_request(case, flags)


@pytest.mark.parametrize(("case", "flags"), rendered(DEPENDENCY_PATH_REFUSALS))
def test_a_deps_pull_request_changing_a_path_no_dependency_path_names_is_refused(
    case: PullRequestCase, flags: Flags, check_pull_request: PullRequestCheck
) -> None:
    """Spec: LAND-70, LAND-71, LAND-74, LAND-77, CHECK-01"""
    check_pull_request(case, flags)


@pytest.mark.parametrize(("case", "flags"), rendered(LISTING_REFUSALS))
def test_a_deps_pull_request_is_judged_only_on_a_complete_unchanged_listing(
    case: PullRequestCase, flags: Flags, check_pull_request: PullRequestCheck
) -> None:
    """Spec: LAND-73, LAND-75, LAND-76, CHECK-10, CHECK-01"""
    check_pull_request(case, flags)
