"""`release --merged` releases only what its pull request's merge commit lands.

Every case releases from a real clone whose bare remote holds a real merge or squash
commit carrying the trailer block, with the claim on the real state ref; the forge is
the only fake."""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY
from cli_fixtures import CliRun, real_git, run_cli
from github_fixtures import LANDING_BRANCH, MERGE_COMMIT_SHA, WORK_ITEM_ISSUE
from merged_release import MergedPullRequest, arrange_merged_pull_request, state_ref_claims

from aco import github, protocol
from aco.workboard import MergeMethod

LANE_BRANCH = "docs/tidy-readme"
OLD_LANE_BRANCH = "codex/issue-72-old"
UNCLAIMED_LANE_BRANCH = "docs/unclaimed"
ISSUE_BODY = "Work-Item: #72\n\nCloses #72"
LATER_COMMIT = ("commit", "--allow-empty", "-q", "-m", "a later landing")
Arrange = Callable[..., MergedPullRequest]
ISSUE_LANDING = partial(arrange_merged_pull_request, trailers=("Work-Item: #72",))


def release_merged(
    capsys: pytest.CaptureFixture[str], *arguments: str, output: tuple[str, ...] = ()
) -> CliRun:
    return run_cli(["--repo", REPOSITORY, "release", *arguments, "--merged", "12", *output], capsys)


def arrange_issue_landing(
    monkeypatch: pytest.MonkeyPatch,
    clone: Path,
    remote: Path,
    *,
    pull_request_body: str = ISSUE_BODY,
) -> MergedPullRequest:
    return ISSUE_LANDING(
        monkeypatch,
        clone,
        remote,
        identity=protocol.IssueIdentity(WORK_ITEM_ISSUE),
        pull_request_body=pull_request_body,
    )


def arrange_lane_landing(
    monkeypatch: pytest.MonkeyPatch,
    clone: Path,
    remote: Path,
    *,
    trailers: tuple[str, ...],
    method: MergeMethod = MergeMethod.MERGE,
    arrange: Arrange = arrange_merged_pull_request,
) -> MergedPullRequest:
    """The lane's branch is checked out in `clone`, where a lane release starts."""
    landing = arrange(
        monkeypatch,
        clone,
        remote,
        identity=protocol.LaneIdentity(),
        trailers=trailers,
        pull_request_body="No-Item: docs",
        branch=LANE_BRANCH,
        method=method,
    )
    real_git(clone, "checkout", "-q", LANE_BRANCH)
    return landing


@pytest.mark.parametrize("kind", ["docs", "fix", "deps"])
def test_release_merged_accepts_an_issueless_lane_that_landed_without_an_item(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
    kind: str,
) -> None:
    """Spec: LAND-37, REL-16."""
    arrange_lane_landing(monkeypatch, github_clone, bare_remote, trailers=(f"No-Item: {kind}",))

    result = release_merged(capsys)

    assert (result.status, result.stderr) == (0, "")
    assert not state_ref_claims(github_clone, bare_remote)


def test_release_merged_refuses_an_issueless_lane_landing_off_trunk(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: LAND-64."""
    arrange_lane_landing(
        monkeypatch,
        github_clone,
        bare_remote,
        trailers=("No-Item: docs",),
        arrange=partial(arrange_merged_pull_request, forge_merge_commit=MERGE_COMMIT_SHA),
    )

    result = release_merged(capsys)

    assert (result.status, result.stderr) == (
        2,
        f"ERROR: merge commit {MERGE_COMMIT_SHA} of pull request #12 "
        "is not on the first-parent trunk\n",
    )
    assert state_ref_claims(github_clone, bare_remote)


def test_release_merged_refuses_an_issueless_lane_landing_with_a_classification_defect(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: LAND-64."""
    landing = arrange_lane_landing(
        monkeypatch, github_clone, bare_remote, trailers=("No-Item: docs", "No-Item: fix")
    )

    result = release_merged(capsys)

    assert (result.status, result.stderr) == (
        2,
        f"ERROR: merge commit {landing.merge_commit} of pull request #12 "
        "carries more than one `No-Item:` trailer\n",
    )
    assert state_ref_claims(github_clone, bare_remote)


@pytest.mark.parametrize(
    ("arrange", "reason"),
    [
        pytest.param(
            partial(ISSUE_LANDING, forge_reports_merged=False),
            "pull request #12 is not merged",
            id="not-merged",
        ),
        pytest.param(
            partial(ISSUE_LANDING, forge_base="release"),
            "pull request #12 merged into 'release', not the default branch 'main'",
            id="wrong-base",
        ),
        pytest.param(
            partial(ISSUE_LANDING, forge_merge_commit=MERGE_COMMIT_SHA),
            "merge commit {reported} of pull request #12 is not on the first-parent trunk",
            id="off-trunk",
        ),
        pytest.param(
            partial(arrange_merged_pull_request, trailers=()),
            "merge commit {reported} of pull request #12 carries no `Work-Item:` trailer; "
            'release it with --abandoned "landed as PR #12 without a Work-Item: trailer" '
            "and close #72 by hand",
            id="no-trailer",
        ),
        pytest.param(
            partial(arrange_merged_pull_request, trailers=("Work-Item: #99",)),
            "merge commit {reported} of pull request #12 does not name work item #72",
            id="another-item",
        ),
        pytest.param(
            partial(arrange_merged_pull_request, trailers=("No-Item: docs",)),
            "merge commit {reported} of pull request #12 does not name work item #72",
            id="trunk-declares-no-item",
        ),
    ],
)
def test_release_merged_refuses_a_landing_it_cannot_verify(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
    arrange: Arrange,
    reason: str,
) -> None:
    """Spec: LAND-30, LAND-31, LAND-62, LAND-80. The pull request's body names #72
    throughout."""
    landing = arrange(
        monkeypatch,
        github_clone,
        bare_remote,
        identity=protocol.IssueIdentity(WORK_ITEM_ISSUE),
        pull_request_body=ISSUE_BODY,
    )
    reported = landing.forge.landings[12].merge_commit

    result = release_merged(capsys, "72")

    assert (result.status, result.stderr) == (2, f"ERROR: {reason.format(reported=reported)}\n")
    assert state_ref_claims(github_clone, bare_remote)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("", id="empty-body"),
        pytest.param("Advances #72", id="no-work-item-line"),
        pytest.param("Work-Item: #99\n\nCloses #99", id="wrong-numbered-work-item"),
    ],
)
def test_release_merged_ignores_the_pull_requests_own_body_for_an_issue(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
    body: str,
) -> None:
    """Spec: LAND-29, LAND-62."""
    landing = arrange_issue_landing(monkeypatch, github_clone, bare_remote, pull_request_body=body)

    result = release_merged(capsys, "72")

    assert (result.status, result.stderr, landing.forge.closed_issues) == (0, "", {WORK_ITEM_ISSUE})
    assert not state_ref_claims(github_clone, bare_remote)


def test_release_merged_closes_the_still_open_work_item(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: LAND-29, LAND-55."""
    landing = arrange_issue_landing(monkeypatch, github_clone, bare_remote)

    result = release_merged(capsys, "72")

    assert result.status == 0
    assert landing.forge.closed_issues == {WORK_ITEM_ISSUE}
    assert landing.forge.landing_comments == {WORK_ITEM_ISSUE: github.landing_comment(12)}
    assert not state_ref_claims(github_clone, bare_remote)


@pytest.mark.parametrize(
    "output",
    [pytest.param((), id="text"), pytest.param(("--json",), id="json")],
)
@pytest.mark.parametrize(
    "work_item_value",
    [pytest.param("#72", id="valid-reference"), pytest.param("fix/x", id="branch-name")],
)
def test_release_merged_refuses_a_lane_whose_merge_commit_names_a_work_item(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
    work_item_value: str,
    output: tuple[str, ...],
) -> None:
    """Spec: LAND-66, LAND-67. One squash commit; the pull request's body declares
    `No-Item:` and is not the authority."""
    arrange_lane_landing(
        monkeypatch,
        github_clone,
        bare_remote,
        trailers=(f"Work-Item: {work_item_value}",),
        method=MergeMethod.SQUASH,
    )
    landed = real_git(bare_remote, "rev-parse", "main").stdout.strip()
    refusal = (
        f"merge commit {landed} of pull request #12 carries "
        f"`Work-Item: {work_item_value}`; an issue-less lane needs a "
        '`No-Item: <docs|fix|deps>` trailer; release it with --abandoned "landed as PR #12 '
        'with a malformed trailer"'
    )
    printed = json.dumps({"ok": False, "reason": "precondition_failed", "message": refusal})

    result = release_merged(capsys, output=output)

    assert result.status == 2
    assert (result.stdout, result.stderr) == (
        (printed + "\n", f"ERROR: {refusal}\n") if output else ("", f"ERROR: {refusal}\n")
    )
    assert state_ref_claims(github_clone, bare_remote)


def test_release_merged_refuses_an_unclassified_lane_merge_commit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: LAND-64, LAND-66."""
    landing = arrange_lane_landing(monkeypatch, github_clone, bare_remote, trailers=())

    result = release_merged(capsys)

    assert (result.status, result.stderr) == (
        2,
        f"ERROR: merge commit {landing.merge_commit} of pull request #12 carries no "
        "`Work-Item:` or `No-Item:` trailer\n",
    )
    assert state_ref_claims(github_clone, bare_remote)


@pytest.mark.parametrize(
    ("arguments", "pull_request_branch", "claim_branch", "after_the_merge", "refusal"),
    [
        pytest.param(
            ("999",),
            LANDING_BRANCH,
            LANDING_BRANCH,
            None,
            "merge commit {merge} of pull request #12 does not name work item #999",
            id="no-claim-and-a-merge-naming-another-item",
        ),
        pytest.param(
            ("72", "--branch", OLD_LANE_BRANCH),
            OLD_LANE_BRANCH,
            LANDING_BRANCH,
            None,
            f"issue #72 is claimed on '{LANDING_BRANCH}', not on pull request #12's branch "
            f"'{OLD_LANE_BRANCH}'; release that claim by itself",
            id="claim-off-the-pull-requests-branch",
        ),
        pytest.param(
            ("72",),
            LANDING_BRANCH,
            LANDING_BRANCH,
            LATER_COMMIT,
            f"issue #72 was claimed on '{LANDING_BRANCH}' after pull request #12 landed; "
            "release that claim by itself",
            id="claim-opened-after-the-landing",
        ),
        pytest.param(
            ("72",),
            LANDING_BRANCH,
            LANDING_BRANCH,
            (),
            f"issue #72 was claimed on '{LANDING_BRANCH}' after pull request #12 landed; "
            "release that claim by itself",
            id="claim-opened-at-the-landing-commit",
        ),
        pytest.param(
            ("--branch", UNCLAIMED_LANE_BRANCH),
            LANE_BRANCH,
            LANE_BRANCH,
            None,
            f"lane '{UNCLAIMED_LANE_BRANCH}' has no active build claim",
            id="unclaimed-lane-off-the-pull-requests-claimed-branch",
        ),
    ],
)
def test_release_merged_refuses_what_its_landing_does_not_back_and_keeps_every_claim(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
    arguments: tuple[str, ...],
    pull_request_branch: str,
    claim_branch: str,
    after_the_merge: tuple[str, ...] | None,
    refusal: str,
) -> None:
    """Spec: REL-47, REL-48, REL-53, REL-54."""
    lane = pull_request_branch == LANE_BRANCH
    landing = arrange_merged_pull_request(
        monkeypatch,
        github_clone,
        bare_remote,
        identity=protocol.LaneIdentity() if lane else protocol.IssueIdentity(WORK_ITEM_ISSUE),
        trailers=("No-Item: docs",) if lane else ("Work-Item: #72",),
        pull_request_body="No-Item: docs" if lane else ISSUE_BODY,
        branch=pull_request_branch,
        claim_branch=claim_branch,
        claim_after_the_merge=after_the_merge,
    )
    claims_before = state_ref_claims(github_clone, bare_remote)

    result = release_merged(capsys, *arguments)

    assert (result.status, result.stderr) == (
        2,
        f"ERROR: {refusal.format(merge=landing.merge_commit)}\n",
    )
    assert (landing.forge.closed_issues, landing.forge.landing_comments) == (set(), {})
    assert state_ref_claims(github_clone, bare_remote) == claims_before
