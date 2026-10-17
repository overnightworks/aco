"""Dependency listing and path decisions (LAND-71, LAND-73..76) and the adoption
preflight's precedence (ADOPT-02..07, ADOPT-11, ADOPT-16)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

import pytest
from board_fixtures import REPOSITORY, standing_active_claim
from cli_fixtures import (
    ADOPTED_BRANCH,
    ADOPTED_PULL_REQUEST,
    dependabot_pull_request,
    pull_request_listing,
    run_context_over,
)
from github_fixtures import MERGE_COMMIT_SHA, FakeForge

from agent_coordination import board, body, forge, github, policy, protocol


@pytest.mark.parametrize(
    "after_count, expected",
    [
        pytest.param(4, "changed while aco listed its files; run the command again", id="P1"),
        pytest.param(3, frozenset({"uv.lock", "old.lock", "pyproject.toml"}), id="P3"),
    ],
)
def test_listed_paths_judge_only_a_complete_listing(
    after_count: int, expected: str | frozenset[str]
) -> None:
    changes = forge.PullRequestChanges(
        forge.ListingReading(MERGE_COMMIT_SHA, 3),
        forge.ListingReading(MERGE_COMMIT_SHA, after_count),
        (
            forge.ChangedFile("uv.lock", "old.lock"),
            forge.ChangedFile("old.lock", None),
            forge.ChangedFile("pyproject.toml", None),
        ),
    )
    result = policy.listed_paths(changes, MERGE_COMMIT_SHA)
    assert (
        result.message if isinstance(result, board.ClassificationDefect) else result
    ) == expected


@pytest.mark.parametrize(
    "entry, path, expected",
    [
        pytest.param(
            "uv.lock",
            "uv.lock.bak",
            "changes uv.lock.bak, which dependency_paths in .aco/board.toml does not name",
            id="P9",
        ),
        pytest.param(
            ".github/workflows/",
            ".github/workflows/../../src/x.py",
            "changes .github/workflows/../../src/x.py, "
            "which dependency_paths in .aco/board.toml does not name",
            id="P11",
        ),
        pytest.param(
            "vendor/",
            "vendor/a\\b",
            "changes vendor/a\\b, which dependency_paths in .aco/board.toml does not name",
            id="P11-backslash",
        ),
        pytest.param(
            "vendor/",
            "vendor/a ",
            "changes vendor/a , which dependency_paths in .aco/board.toml does not name",
            id="P11-trailing-space",
        ),
        pytest.param(
            "vendor/",
            "vendor/" + "a" * 506,
            "changes vendor/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa…, "
            "which dependency_paths in .aco/board.toml does not name",
            id="P11-over-512",
        ),
    ],
)
def test_dependency_paths_cover_only_canonical_paths_up_to_a_slash(
    entry: str, path: str, expected: str
) -> None:
    config = board.BoardConfig(dependency_paths=(entry,))
    defect = policy.dependency_rule_defect(config, lambda: frozenset({path}))
    assert defect == board.ClassificationDefect(expected)


FIRST_HEAD = "1" * 40
SECOND_HEAD = "2" * 40
OTHER_REPOSITORY = "other/agent-coordination"


@dataclass(frozen=True)
class PreflightRow:
    """One pull request #45 as `adoption_preflight` meets it, with the claims
    the store holds and the refusal or plan it must reach."""

    refusal: str = ""
    planned_scope: tuple[str, ...] = ()
    planned_body: str = ""
    kind: board.NoItemKind = board.NoItemKind.FIX
    pull_request: Callable[[forge.Landing], forge.Landing] = lambda landing: landing
    reference_state: forge.ItemState = forge.ItemState.OPEN
    claims: tuple[protocol.ActiveClaim, ...] = ()
    changes: forge.PullRequestChanges = field(
        default_factory=lambda: pull_request_listing(
            FIRST_HEAD, forge.ChangedFile("README.md", None)
        )
    )
    dependency_paths: tuple[str, ...] = ()
    claim_reads: int = 1
    listing_reads: int = 0


def _pull_request_refusal(sentence: str) -> str:
    return f"pull request #{ADOPTED_PULL_REQUEST} {sentence}"


_BOB_LANE_CLAIM = standing_active_claim("Bob", lane=True, branch=ADOPTED_BRANCH)


@pytest.mark.usefixtures("github_clone")
@pytest.mark.parametrize(
    "row",
    [
        pytest.param(
            PreflightRow(
                _pull_request_refusal("is not open; it cannot be adopted"),
                reference_state=forge.ItemState.CLOSED,
                claim_reads=0,
            ),
            id="R16-closed",
        ),
        pytest.param(
            PreflightRow(
                _pull_request_refusal(
                    f"proposes a branch of {OTHER_REPOSITORY}; "
                    "cross-repository pull requests are not classified"
                ),
                pull_request=lambda landing: replace(
                    landing, source_repository=github.repository_id(OTHER_REPOSITORY)
                ),
                claim_reads=0,
            ),
            id="R18-fork",
        ),
        pytest.param(
            PreflightRow(
                (
                    f"lane '{ADOPTED_BRANCH}' is claimed by Ada (builder) "
                    f"on issue #42 branch {ADOPTED_BRANCH}"
                ),
                claims=(standing_active_claim("Ada", issue=42, branch=ADOPTED_BRANCH),),
            ),
            id="R20-issue-claim",
        ),
        pytest.param(
            PreflightRow(
                _pull_request_refusal(
                    "body would not read No-Item: fix with the line added: "
                    "carries no `Work-Item:` or `No-Item:` line"
                ),
                pull_request=lambda landing: replace(landing, body="Bump x\n```\nfoo"),
            ),
            id="R24-unclosed-fence",
        ),
        pytest.param(
            PreflightRow(
                _pull_request_refusal("targets 'release', not the default branch 'main'"),
                pull_request=lambda landing: replace(landing, target_branch="release"),
            ),
            id="R25-target",
        ),
        pytest.param(
            PreflightRow(
                _pull_request_refusal(
                    f"declares no work item but closes {REPOSITORY}#5; name it as the work item"
                ),
                pull_request=lambda landing: replace(landing, body="Closes #5"),
            ),
            id="R26-closing-reference",
        ),
        pytest.param(
            PreflightRow(
                _pull_request_refusal(
                    "declares No-Item: deps, but .aco/board.toml names no dependency_paths"
                ),
                kind=board.NoItemKind.DEPS,
            ),
            id="R27-no-dependency-paths",
        ),
        pytest.param(
            PreflightRow(
                _pull_request_refusal("changed while aco listed its files; run the command again"),
                changes=forge.PullRequestChanges(
                    forge.ListingReading(SECOND_HEAD, 1),
                    forge.ListingReading(SECOND_HEAD, 1),
                    (forge.ChangedFile("README.md", None),),
                ),
                listing_reads=1,
            ),
            id="R28-head-moved",
        ),
        pytest.param(
            PreflightRow(
                _pull_request_refusal(
                    "lists 2 of its 3 changed files; aco judges only a complete listing"
                ),
                changes=pull_request_listing(
                    FIRST_HEAD,
                    forge.ChangedFile("a.txt", None),
                    forge.ChangedFile("b.txt", None),
                    reported=3,
                ),
                listing_reads=1,
            ),
            id="R29-incomplete-listing",
        ),
        pytest.param(
            PreflightRow(
                _pull_request_refusal("changes no file; there is nothing to adopt"),
                changes=pull_request_listing(FIRST_HEAD),
                listing_reads=1,
            ),
            id="R30-empty-listing",
        ),
        pytest.param(
            PreflightRow(
                planned_scope=("README.md", "src/a.py", "src/b.py"),
                planned_body="Bump x\n\nNo-Item: fix",
                changes=pull_request_listing(
                    FIRST_HEAD,
                    forge.ChangedFile("README.md", None),
                    forge.ChangedFile("src/b.py", "src/a.py"),
                ),
                listing_reads=1,
            ),
            id="R32-fresh-fix",
        ),
        pytest.param(
            PreflightRow(
                planned_scope=("uv.lock",),
                planned_body="Bump x\n\nNo-Item: deps",
                kind=board.NoItemKind.DEPS,
                changes=pull_request_listing(FIRST_HEAD, forge.ChangedFile("uv.lock", None)),
                dependency_paths=("uv.lock",),
                listing_reads=1,
            ),
            id="fresh-deps-reads-the-listing-once",
        ),
        pytest.param(
            PreflightRow(
                _pull_request_refusal(
                    f"proposes a branch of {OTHER_REPOSITORY}; "
                    "cross-repository pull requests are not classified"
                ),
                pull_request=lambda landing: replace(
                    landing,
                    body="Closes #5",
                    source_repository=github.repository_id(OTHER_REPOSITORY),
                ),
                claim_reads=0,
            ),
            id="R38-fork-before-closing-reference",
        ),
        pytest.param(
            PreflightRow(
                (
                    f"lane '{ADOPTED_BRANCH}' is claimed by Bob (builder) "
                    f"on lane '{ADOPTED_BRANCH}' branch {ADOPTED_BRANCH}"
                ),
                pull_request=lambda landing: replace(landing, body="No-Item: fix"),
                claims=(_BOB_LANE_CLAIM,),
            ),
            id="R39-claim-before-classification-line",
        ),
    ],
)
def test_adoption_preflight_refuses_or_plans_in_precedence_order(row: PreflightRow) -> None:
    """Spec: ADOPT-02, ADOPT-03, ADOPT-04, ADOPT-06, ADOPT-07, ADOPT-11, ADOPT-16 --
    the first failing step wins, and the claims are read once, only past steps 5 and 6."""
    pull_request_forge = FakeForge(
        landings={ADOPTED_PULL_REQUEST: row.pull_request(dependabot_pull_request(FIRST_HEAD))},
        changes_by_number={ADOPTED_PULL_REQUEST: row.changes},
        issue_references={ADOPTED_PULL_REQUEST: forge.ItemReference(row.reference_state, "", "")},
    )
    run = run_context_over(pull_request_forge)
    run.config = board.BoardConfig(dependency_paths=row.dependency_paths)
    claim_reads: list[None] = []

    def claims_provider() -> protocol.ClaimState:
        claim_reads.append(None)
        return protocol.ClaimState(
            tip=protocol.ObjectId(FIRST_HEAD),
            claims={
                protocol.claim_key(claim.identity, claim.branch): claim for claim in row.claims
            },
        )

    outcome = policy.adoption_preflight(
        policy.LandingCheckContext(run, REPOSITORY, body.Storage.GITHUB),
        policy.AdoptionRequest(ADOPTED_PULL_REQUEST, row.kind),
        pull_request_forge.landing(ADOPTED_PULL_REQUEST),
        pull_request_forge.item_reference(ADOPTED_PULL_REQUEST),
        claims_provider,
    )

    expected = (
        policy.AdoptionRefusal(row.refusal)
        if row.refusal
        else policy.FreshAdoption(row.planned_scope, row.planned_body, FIRST_HEAD)
    )
    assert outcome == expected
    assert len(claim_reads) == row.claim_reads
    assert len(pull_request_forge.changes_reads) == row.listing_reads
