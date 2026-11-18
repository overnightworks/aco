"""`aco check <pr>`: declarations, dependency paths and parents in the real GitHub world."""

from dataclasses import replace
from typing import NoReturn

import pytest
from board_fixtures import REPOSITORY, block_body, complete_contract, slice_entries
from check_pull_request_fixtures import (
    LANE_BRANCH,
    LANE_WORLD,
    PARENT,
    PARENT_ISSUE,
    WORK_ITEM,
    Flags,
    ParentWorld,
    PullRequestCase,
    PullRequestCheck,
    PullRequestWorld,
    declares,
    refused,
    rendered,
    unavailable,
)
from cli_fixtures import pull_request_listing
from github_fixtures import LANDING_BRANCH, MERGE_COMMIT_SHA
from store_fixtures import claim_intent

from aco import body, forge, policy, protocol

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
# a `deps` listing is one more, and so are a recorded parent's children unless
# the parent itself is refused before them.
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


def item_world(
    listing: forge.PullRequestChanges, *, scope: tuple[str, ...] = ("README.md",), shared: str = ""
) -> PullRequestWorld:
    claim = claim_intent(identity=protocol.IssueIdentity(72), branch=LANDING_BRANCH, scope=scope)
    return PullRequestWorld(
        claims=(claim,), listing=listing, lane_shared=(shared,) if shared else ()
    )


def uncovered(named: str) -> str:
    return f"changes {named}, which its claim does not cover; rescope the claim or revert them"


def item_refused(named: str, world: PullRequestWorld) -> PullRequestCase:
    return refused(WORK_ITEM_BODY, uncovered(named), 5, world, (12,))


NARROW_DEPS_WORLD = replace(
    DEPS_WORLD,
    dependency_paths=("uv.lock",),
    claims=(claim_intent(identity=protocol.LaneIdentity(), branch=LANE_BRANCH, scope=("docs",)),),
    listing=listing_of("uv.lock"),
)

COVERED_PATHS = {
    "directory-scope-covers-a-nested-path": declares(
        WORK_ITEM_BODY,
        f"Work-Item: {WORK_ITEM}",
        4,
        item_world(listing_of("docs/a/b.md"), scope=("docs",)),
    ),
    "tracked-lane-shared-file-covers": declares(
        WORK_ITEM_BODY,
        f"Work-Item: {WORK_ITEM}",
        4,
        item_world(listing_of("README.md", ".aco/board.toml"), shared=".aco/board.toml"),
    ),
}

UNCOVERED_PATHS = {
    "incomplete-listing": refused(
        WORK_ITEM_BODY,
        "lists 2 of its 1 changed files; aco judges only a complete listing",
        5,
        item_world(listing_of_files(2, reported=1)),
        (12,),
    ),
    "work-item-path-outside": item_refused(
        "docs/x.md", item_world(listing_of("README.md", "docs/x.md"))
    ),
    "four-paths-outside": item_refused("a, b, c, and 1 more", item_world(listing_of(*"dcba"))),
    "untracked-lane-shared-covers-nothing": item_refused(
        "scripts/registry.txt",
        item_world(listing_of("scripts/registry.txt"), shared="scripts/registry.txt"),
    ),
    "rename-from-outside-into-scope": item_refused(
        "docs/old.md",
        item_world(
            pull_request_listing(MERGE_COMMIT_SHA, forge.ChangedFile("README.md", "docs/old.md"))
        ),
    ),
    "directory-prefix-is-no-directory": item_refused(
        "docsX/a.md", item_world(listing_of("docsX/a.md"), scope=("docs",))
    ),
    "docs-lane-outside-its-scope": refused(
        NO_ITEM_BODY,
        uncovered("other/x.py"),
        4,
        replace(LANE_WORLD, listing=listing_of("other/x.py")),
        (12,),
    ),
    "deps-lane-inside-dependency-paths-outside-its-claim": refused(
        DEPS_BODY, uncovered("uv.lock"), 4, NARROW_DEPS_WORLD, (12,)
    ),
}


@pytest.mark.parametrize(("case", "flags"), rendered(COVERED_PATHS))
def test_a_pull_request_changing_only_paths_its_claim_covers_is_accepted(
    case: PullRequestCase, flags: Flags, check_pull_request: PullRequestCheck
) -> None:
    """Spec: LAND-87, LAND-88, LAND-90, CHECK-01"""
    check_pull_request(case, flags)


def test_a_listing_the_claim_scope_covers_never_reads_the_trunk_configuration(
    check_pull_request: PullRequestCheck, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: LAND-90"""

    def trunk_read(*_: object) -> NoReturn:
        raise AssertionError("the trunk's lane_shared was read")

    monkeypatch.setattr(policy, "trunk_lane_shared_reading", trunk_read)
    covered = declares(
        WORK_ITEM_BODY, f"Work-Item: {WORK_ITEM}", 4, item_world(listing_of("README.md"))
    )
    check_pull_request(covered, [])


@pytest.mark.parametrize(("case", "flags"), rendered(UNCOVERED_PATHS))
def test_a_pull_request_changing_a_path_its_claim_does_not_cover_is_refused(
    case: PullRequestCase, flags: Flags, check_pull_request: PullRequestCheck
) -> None:
    """Spec: LAND-87, LAND-88, LAND-74, LAND-77, LAND-90, CHECK-01"""
    check_pull_request(case, flags)


def accepted_with_parent(body: str, parent: ParentWorld) -> PullRequestCase:
    return declares(body, f"Work-Item: {WORK_ITEM}", 5, PullRequestWorld(parent=parent))


def refused_with_parent(
    body: str, message: str, parent: ParentWorld, forge_requests: int = 5
) -> PullRequestCase:
    return refused(body, message, forge_requests, PullRequestWorld(parent=parent))


CLOSES_ITEM_AND_PARENT = f"Work-Item: #72\n\nCloses #72\nCloses #{PARENT_ISSUE}"
CLOSES_PARENT_ONLY = f"Work-Item: #72\n\nCloses #{PARENT_ISSUE}"
CLOSE_PARENT_TOO = f"closes the last open child of parent {PARENT}; close the parent too"
UNCUT_ROW = (
    f"closes parent {PARENT} although its body still holds an uncut slice row; "
    "cut it or delete the row first"
)
NO_NEXT_LINE = (
    f"leaves parent {PARENT} open with {{}} other open {{}}, whose body carries no Next line"
)
NOT_A_CONTAINER = (
    f"has parent {PARENT} of kind {{}}, which is not a container; only a container holds children"
)
ONE_UNCUT_ROW = slice_entries("Scheibe 1")
STALE_NEXT_PROSE = "\n\n## Next\nnichts\n"
NEXT_IN_BLOCK = block_body(
    'version = 1\nnow = "N"\nnext = "Cut the next slice."\ndone_when = "D"\n'
)


PARENT_ACCEPTANCES = {
    "last-child-parent-next-names-work": accepted_with_parent(
        WORK_ITEM_BODY, ParentWorld(complete_contract("Cut the next slice."))
    ),
    "last-child-parent-next-read-from-the-block-not-prose": accepted_with_parent(
        WORK_ITEM_BODY, ParentWorld(NEXT_IN_BLOCK + STALE_NEXT_PROSE)
    ),
    "last-child-with-an-uncut-row-leaves-the-parent-open": accepted_with_parent(
        WORK_ITEM_BODY, ParentWorld(complete_contract("keiner", slice=ONE_UNCUT_ROW))
    ),
    "closing-the-parent-with-further-next-work": accepted_with_parent(
        CLOSES_ITEM_AND_PARENT, ParentWorld(complete_contract("Cut the next slice."))
    ),
    "closing-the-completed-parent": accepted_with_parent(
        CLOSES_ITEM_AND_PARENT, ParentWorld(complete_contract("keiner", now="Epic."))
    ),
    "closed-children-do-not-keep-the-parent-open": accepted_with_parent(
        CLOSES_ITEM_AND_PARENT, ParentWorld(complete_contract("keiner"), closed_children=2)
    ),
    "other-children-parent-says-what-comes-next": accepted_with_parent(
        WORK_ITEM_BODY, ParentWorld(complete_contract("Dispatch slice 4."), other_open_children=1)
    ),
    "foreign-child-and-next-names-no-work": accepted_with_parent(
        WORK_ITEM_BODY, ParentWorld(complete_contract("keiner"), foreign_open_children=1)
    ),
    "other-child-and-next-names-no-work": accepted_with_parent(
        WORK_ITEM_BODY, ParentWorld(complete_contract("keiner"), other_open_children=1)
    ),
    "parent-in-another-repository-sets-no-parent-rule": declares(
        WORK_ITEM_BODY,
        f"Work-Item: {WORK_ITEM}",
        4,
        PullRequestWorld(parent=ParentWorld(complete_contract("keiner"), repository="other/repo")),
    ),
}

PARENT_CLOSING_REFUSALS = {
    "last-child-must-close-the-parent": refused_with_parent(
        WORK_ITEM_BODY, CLOSE_PARENT_TOO, ParentWorld(complete_contract("keiner"))
    ),
    "other-children-and-no-next-line": refused_with_parent(
        WORK_ITEM_BODY,
        NO_NEXT_LINE.format(1, "child"),
        ParentWorld(complete_contract("", now="Epic without a next step."), other_open_children=1),
    ),
    "foreign-child-and-no-next-line": refused_with_parent(
        WORK_ITEM_BODY,
        NO_NEXT_LINE.format(1, "child"),
        ParentWorld(complete_contract(""), foreign_open_children=1),
    ),
    "two-other-children-and-no-next-line": refused_with_parent(
        WORK_ITEM_BODY,
        NO_NEXT_LINE.format(2, "children"),
        ParentWorld(complete_contract(""), other_open_children=2),
    ),
    "closing-the-parent-besides-other-children": refused_with_parent(
        CLOSES_ITEM_AND_PARENT,
        f"closes {PARENT} besides its work item {WORK_ITEM}; a pull request lands one item",
        ParentWorld(complete_contract("Dispatch slice 4."), other_open_children=1),
    ),
    "closing-a-parent-in-another-repository": refused_with_parent(
        f"Work-Item: #72\n\nCloses #72\nCloses other/repo#{PARENT_ISSUE}",
        f"closes other/repo#{PARENT_ISSUE} besides its work item {WORK_ITEM}; "
        "a pull request lands one item",
        ParentWorld(complete_contract("keiner"), repository="other/repo"),
        forge_requests=4,
    ),
    "closing-the-parent-with-an-uncut-row": refused_with_parent(
        CLOSES_ITEM_AND_PARENT,
        UNCUT_ROW,
        ParentWorld(complete_contract("keiner", slice=ONE_UNCUT_ROW)),
    ),
    "closing-the-parent-with-an-unprintable-uncut-row": refused_with_parent(
        CLOSES_ITEM_AND_PARENT,
        UNCUT_ROW,
        ParentWorld(complete_contract("keiner", slice=slice_entries("Scheibe\nzwei"))),
    ),
    "uncut-row-before-one-item-per-landing": refused_with_parent(
        CLOSES_ITEM_AND_PARENT,
        UNCUT_ROW,
        ParentWorld(
            complete_contract("Dispatch slice 4.", slice=ONE_UNCUT_ROW), other_open_children=1
        ),
    ),
    "no-next-line-before-the-uncut-row": refused_with_parent(
        CLOSES_ITEM_AND_PARENT,
        NO_NEXT_LINE.format(1, "child"),
        ParentWorld(complete_contract("", slice=ONE_UNCUT_ROW), other_open_children=1),
    ),
    "missing-closing-reference-before-the-uncut-row": refused_with_parent(
        CLOSES_PARENT_ONLY,
        f"carries no closing reference for its work item {WORK_ITEM}",
        ParentWorld(complete_contract("keiner", slice=ONE_UNCUT_ROW)),
    ),
}

PARENT_REFUSALS = {
    "blockless-parent": refused_with_parent(
        WORK_ITEM_BODY,
        f"has parent {PARENT} with a body malformed: aco: no aco block",
        ParentWorld("## Now\nOld prose.\n"),
        forge_requests=4,
    ),
    "malformed-parent-block": refused_with_parent(
        WORK_ITEM_BODY,
        f"has parent {PARENT} with a body malformed: version: version must be exactly 1",
        ParentWorld(block_body('version = 2\nnow = "N"\nnext = "X"\ndone_when = "D"\n')),
        forge_requests=4,
    ),
    "first-defect-of-a-malformed-parent": refused_with_parent(
        WORK_ITEM_BODY,
        f"has parent {PARENT} with a body malformed: version: version must be exactly 1",
        ParentWorld(block_body("version = 2\n")),
        forge_requests=4,
    ),
    "parent-that-is-no-container": refused_with_parent(
        WORK_ITEM_BODY,
        NOT_A_CONTAINER.format("task"),
        ParentWorld(complete_contract("keiner"), kind=body.ItemKind.TASK),
        forge_requests=4,
    ),
    "parent-of-unknown-kind": refused_with_parent(
        WORK_ITEM_BODY,
        NOT_A_CONTAINER.format("unknown"),
        ParentWorld(complete_contract("keiner"), kind=None),
        forge_requests=4,
    ),
    "parent-defect-before-the-closing-reference": refused_with_parent(
        CLOSES_PARENT_ONLY,
        NOT_A_CONTAINER.format("task"),
        ParentWorld(complete_contract("keiner"), kind=body.ItemKind.TASK),
        forge_requests=4,
    ),
}


@pytest.mark.parametrize(("case", "flags"), rendered(PARENT_ACCEPTANCES))
def test_a_landing_is_accepted_when_its_parent_stays_open_or_closes_with_it(
    case: PullRequestCase, flags: Flags, check_pull_request: PullRequestCheck
) -> None:
    """Spec: LAND-21, LAND-22, LAND-23, LAND-25, LAND-28, LAND-86, CHECK-01"""
    check_pull_request(case, flags)


@pytest.mark.parametrize(("case", "flags"), rendered(PARENT_CLOSING_REFUSALS))
def test_a_landing_that_contradicts_what_its_parent_still_holds_is_refused(
    case: PullRequestCase, flags: Flags, check_pull_request: PullRequestCheck
) -> None:
    """Spec: LAND-18, LAND-19, LAND-21, LAND-24, LAND-79, LAND-86, CHECK-01"""
    check_pull_request(case, flags)


@pytest.mark.parametrize(("case", "flags"), rendered(PARENT_REFUSALS))
def test_a_landing_whose_parent_cannot_be_read_or_holds_no_children_is_refused(
    case: PullRequestCase, flags: Flags, check_pull_request: PullRequestCheck
) -> None:
    """Spec: LAND-18, LAND-26, LAND-27, CHECK-01"""
    check_pull_request(case, flags)
