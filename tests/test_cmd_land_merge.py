"""Land merge decisions through real claims, pushed branches and forge-side merges."""

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

import pytest
from cli_fixtures import (
    CliRun,
    MainBranchState,
    add_lane_worktree,
    landed_from_another_clone,
    local_branches,
    move_trunk,
    pull_request_listing,
    real_git,
    run_cli,
    track_board_config,
)
from github_fixtures import (
    LANDING_BRANCH,
    FakeForge,
    LaneLandingWorld,
    RefusalLength,
    assert_github_world,
    landed_observations,
    lane_landing_world,
    refusal_observations,
)

from aco import cmd_land, forge, protocol, workboard


class ClaimHolder(Enum):
    SELF = "Ada"
    FOREIGN = "Grok"


class HeldRole(Enum):
    BUILDER = "builder"
    COORDINATOR = "coordinator"


class LaneWorktree(Enum):
    ABSENT = False
    PRESENT = True


class ReviewedHead(Enum):
    OMITTED = "omitted"
    FULL = "full"
    UPPERCASE_PREFIX = "uppercase-prefix"


class DefaultBranch(Enum):
    MAIN = ("main", None)
    TRUNK_WITHOUT_MAIN = ("trunk", MainBranchState.ABSENT)
    TRUNK_WITH_REMOTE_MAIN = ("trunk", MainBranchState.REMOTE_LEFTOVER)


@dataclass(frozen=True)
class Landed:
    method: workboard.MergeMethod = workboard.MergeMethod.SQUASH
    title: str = "feat: land the lane (#12)"
    parents: int = 1
    trailer: str = "Work-Item: #72"
    closed: frozenset[int] = frozenset({72})
    release: str = "RELEASED issue #72: landing\n"


@dataclass(frozen=True)
class MergeCase:
    outcome: Landed | str
    branch: str = LANDING_BRANCH
    identity: protocol.ClaimIdentity = field(default_factory=lambda: protocol.IssueIdentity(72))
    body: str = "Work-Item: #72\n\nCloses #72"
    holder: ClaimHolder = ClaimHolder.SELF
    role: HeldRole = HeldRole.BUILDER
    lane_worktree: LaneWorktree = LaneWorktree.ABSENT
    reviewed: ReviewedHead = ReviewedHead.OMITTED
    arguments: tuple[str, ...] = ()
    trunk_config: str = ""
    head_config: str = ""
    quality_config: str | None = None
    methods: frozenset[workboard.MergeMethod] | None = None
    rules: tuple[frozenset[workboard.MergeMethod], ...] = ()
    error: forge.ForgeError | None = None
    oversized_foreign_text: bool = False
    distinct_detail: bool = False
    dependency_listing: bool = False
    invalid_configuration: bool = False
    default_branch: DefaultBranch = DefaultBranch.MAIN
    decoy_rules: tuple[frozenset[workboard.MergeMethod], ...] = ()
    length: RefusalLength = RefusalLength.WITHIN_LIMIT
    unknown_reads_before_clean: int = 0
    merged_before_error: bool = False
    unreadable_after_merge_request: bool = False
    reads_after_merge_request: int | None = None


@dataclass
class MergeWorld(LaneLandingWorld):
    case: MergeCase
    lane: Path


def arrange_unsettled_readiness(client: FakeForge, unknown_reads_before_clean: int) -> None:
    if not unknown_reads_before_clean:
        return
    clean = client.readiness_by_number[12]
    unknown = replace(clean, mergeable_state="unknown")
    settling = (*(unknown,) * (unknown_reads_before_clean - 1), clean)
    client.readiness_by_number[12], client.later_readiness_by_number[12] = unknown, settling


def arrange_pending_merge(
    client: FakeForge, monkeypatch: pytest.MonkeyPatch, case: MergeCase
) -> None:
    """A merge call whose failure leaves the pull request pending: it merges first when the case
    says so. A case with `reads_after_merge_request` lets the pull request be read that often
    while the failure stands, unreadably when the case says so; any further read fails the test."""
    merge, read = client.merge_landing, client.landing
    reads_left = case.reads_after_merge_request
    if case.merged_before_error:

        def merge_then_fail(
            number: int, *, head_sha: str, method: workboard.MergeMethod, title: str, body: str
        ) -> str:
            error, client.merge_error = client.merge_error, None
            merge(number, head_sha=head_sha, method=method, title=title, body=body)
            client.merge_error = error
            assert error is not None
            raise error

        monkeypatch.setattr(client, "merge_landing", merge_then_fail)

    def landing_while_merge_fails(number: int) -> forge.Landing:
        nonlocal reads_left
        if client.merge_error is None or not client.merge_requests:
            return read(number)
        if not reads_left:
            pytest.fail("the pull request was read more often than the merge failure allows")
        reads_left -= 1
        if case.unreadable_after_merge_request:
            raise forge.ForgeTransientError("gh: Server Error (HTTP 503)")
        return read(number)

    if reads_left is not None:
        monkeypatch.setattr(client, "landing", landing_while_merge_fails)


@pytest.fixture
def world(
    request: pytest.FixtureRequest,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> MergeWorld:
    case: MergeCase = request.param
    monkeypatch.setattr(cmd_land, "pause_between_reads", lambda _seconds: None)
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("GIT_DISCOVERY_ACROSS_FILESYSTEM", "1")
    assert_github_world(github_clone, bare_remote)
    default_branch, main_state = case.default_branch.value
    if main_state is not None:
        move_trunk(github_clone, bare_remote, main_state=main_state)
    if case.trunk_config and not case.invalid_configuration:
        track_board_config(github_clone, case.trunk_config)
        real_git(github_clone, "push", "-q", "origin", default_branch)
    lane = github_clone.parent / "lane"

    def arrange(client: FakeForge, head: str) -> None:
        client.quality_config = case.quality_config
        if case.decoy_rules:
            client.branch_rules = {"main": case.decoy_rules}
        if case.invalid_configuration:
            track_board_config(github_clone, case.trunk_config)
            real_git(github_clone, "push", "-q", "origin", default_branch)
        arrange_unsettled_readiness(client, case.unknown_reads_before_clean)
        arrange_pending_merge(client, monkeypatch, case)
        if case.lane_worktree is LaneWorktree.PRESENT:
            add_lane_worktree(github_clone, lane, case.branch)
        observed = (
            lane.exists(),
            real_git(github_clone, "rev-parse", case.branch).stdout.strip(),
            real_git(bare_remote, "rev-parse", case.branch).stdout.strip(),
            real_git(github_clone, "status", "--porcelain").stdout,
            real_git(github_clone, "branch", "--show-current").stdout,
            bool(real_git(github_clone, "diff", default_branch, case.branch).stdout),
        )
        expected = (case.lane_worktree.value, head, head, "", default_branch + "\n", True)
        assert observed == expected
        if case.dependency_listing:
            client.changes_by_number[12] = pull_request_listing(
                head, forge.ChangedFile("uv.lock", None)
            )
        if case.oversized_foreign_text:
            oversized = "1" * 4301
            client.board_open_pull_requests = (
                workboard.PullRequest(300, "Foreign", f"Refs #{oversized}", "foreign/branch"),
            )
            landed_from_another_clone(
                bare_remote.parent,
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                f"Foreign\n\nWork-Item: #{oversized}",
            )

    shared = lane_landing_world(
        github_clone,
        bare_remote,
        monkeypatch,
        default_branch=default_branch,
        identity=case.identity,
        branch=case.branch,
        body=case.body,
        methods=case.methods,
        holder=case.holder.value,
        role=case.role.value,
        distinct_detail=case.distinct_detail,
        error=case.error,
        rules=case.rules,
        head_config=case.head_config,
        arrange=arrange,
    )
    if main_state is not None:
        observed = (
            shared.default_branch,
            shared.forge.default_branch_name,
            shared.forge.landings[12].target_branch,
            shared.forge.branch_rules,
        )
        expected = (
            "trunk",
            "trunk",
            "trunk",
            {"main": case.decoy_rules} if case.decoy_rules else {"trunk": case.rules},
        )
        assert observed == expected
    return MergeWorld(
        github_clone,
        bare_remote,
        shared.forge,
        shared.unchanged,
        shared.head,
        shared.entry_lineage,
        case,
        lane,
        default_branch=shared.default_branch,
    )


def land(world: MergeWorld, capsys: pytest.CaptureFixture[str]):
    arguments = ["land", "12", *world.case.arguments]
    if world.case.reviewed is not ReviewedHead.OMITTED:
        arguments += [
            "--head",
            world.head[:7].upper()
            if world.case.reviewed is ReviewedHead.UPPERCASE_PREFIX
            else world.head,
        ]
    capsys.readouterr()
    return run_cli(arguments, capsys)


def merge_observations(world: MergeWorld, result: CliRun):
    case = world.case
    outcome = case.outcome
    assert isinstance(outcome, Landed)
    observed, expected = landed_observations(
        world,
        result,
        branch=case.branch,
        method=outcome.method,
        title=outcome.title,
        parents=outcome.parents,
        closed=outcome.closed,
        release=outcome.release,
        remaining_branches=frozenset({world.default_branch})
        if case.lane_worktree is LaneWorktree.PRESENT
        else frozenset({world.default_branch, case.branch}),
    )
    calls = world.forge.merge_calls
    observed["merge.end"] = calls[0][4].strip().split("\n\n")[-1] if calls else ""
    expected["merge.end"] = outcome.trailer
    if case.oversized_foreign_text:
        reads = world.forge.file_reads
        read = reads[0] if reads else (Path("missing"), "missing")
        observed.update(
            {
                "freed-line": "freed:" in result.stdout,
                "next-line": "next:" in result.stdout,
                "file.count": len(reads),
                "file.path": read[0].as_posix(),
                "file.sha": read[1],
            }
        )
        expected.update(
            {
                "freed-line": True,
                "next-line": True,
                "file.count": 1,
                "file.path": ".aco/board.toml",
                "file.sha": world.head,
            }
        )
    if isinstance(case.identity, protocol.LaneIdentity):
        observed["no-reinstall"] = "reinstall:" not in result.stdout
        expected["no-reinstall"] = True
    return observed, expected


def refused_observations(world: MergeWorld, capsys: pytest.CaptureFixture[str]):
    sentence = world.case.outcome
    assert isinstance(sentence, str)
    if world.case.invalid_configuration:
        sentence = sentence.format(clone=world.clone)
    observed, expected = refusal_observations(
        world, land(world, capsys), sentence, length=world.case.length
    )
    if world.case.invalid_configuration:
        observed["requests.zero"] = world.forge.requests
        expected["requests.zero"] = 0
    return observed, expected


class TestLandMerge:
    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(MergeCase(Landed(), oversized_foreign_text=True), id="config-unchanged"),
            pytest.param(
                MergeCase(
                    Landed(),
                    oversized_foreign_text=True,
                    head_config='priority_labels = ["ux"]\nidea_label = "idea"\n',
                ),
                id="only-non-governing-settings-changed",
            ),
            pytest.param(MergeCase(Landed(), reviewed=ReviewedHead.FULL), id="full-sha-matches"),
            pytest.param(
                MergeCase(
                    Landed(),
                    quality_config='[[root.allow]]\nrule = "python-print"\npath = "src/a.py"\n',
                ),
                id="root-entries-only-config-lands-on-green-checks-without-a-verdict",
            ),
            pytest.param(
                MergeCase(Landed(), reviewed=ReviewedHead.FULL, unknown_reads_before_clean=2),
                id="unknown-settles-to-clean-and-the-reviewed-head-lands",
            ),
            pytest.param(
                MergeCase(Landed(), reviewed=ReviewedHead.UPPERCASE_PREFIX),
                id="uppercase-prefix-matches",
            ),
            pytest.param(
                MergeCase(
                    Landed(
                        trailer="No-Item: docs",
                        closed=frozenset(),
                        release="RELEASED lane fix/x: landing\n",
                    ),
                    branch="fix/x",
                    identity=protocol.LaneIdentity(),
                    body="No-Item: docs",
                    reviewed=ReviewedHead.FULL,
                ),
                id="issueless-docs-lane",
            ),
            pytest.param(
                MergeCase(
                    Landed(
                        trailer="No-Item: docs",
                        closed=frozenset(),
                        release="RELEASED lane dependabot/x: landing\n",
                    ),
                    branch="dependabot/x",
                    identity=protocol.LaneIdentity(),
                    body="No-Item: docs",
                    reviewed=ReviewedHead.FULL,
                ),
                id="19",
            ),
            pytest.param(
                MergeCase(
                    Landed(
                        trailer="No-Item: deps",
                        closed=frozenset(),
                        release="RELEASED lane fix/x: landing\n",
                    ),
                    branch="fix/x",
                    identity=protocol.LaneIdentity(),
                    body="No-Item: deps",
                    reviewed=ReviewedHead.FULL,
                    dependency_listing=True,
                    trunk_config=(
                        'dependency_paths = ["pyproject.toml", "uv.lock", ".github/workflows/"]\n'
                    ),
                ),
                id="cell-35",
            ),
            pytest.param(
                MergeCase(
                    Landed(),
                    holder=ClaimHolder.FOREIGN,
                    arguments=("--coordinator-override", "--role", "coordinator"),
                ),
                id="coordinator-override-lands-a-foreign-claim",
            ),
            pytest.param(
                MergeCase(Landed(), distinct_detail=True),
                id="pinned-to-the-readiness-head-not-the-detail-head",
            ),
            pytest.param(
                MergeCase(Landed(), role=HeldRole.COORDINATOR),
                id="holder-in-another-role-lands-without-a-role-flag",
            ),
            pytest.param(
                MergeCase(
                    Landed(),
                    error=forge.ForgeMergeUnansweredError("gh: Server Error (HTTP 502)"),
                    merged_before_error=True,
                ),
                id="server-error-after-the-merge-went-through",
            ),
        ],
        indirect=True,
    )
    def test_lands(self, world: MergeWorld, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-09, LANDCMD-10, LANDCMD-12, LANDCMD-13, LANDCMD-23, LANDCMD-29,
        LANDCMD-32, LANDCMD-43, LANDCMD-72.
        The reviewed head lands, releases the real claim and retains the classification trailer.
        """
        observed, expected = merge_observations(world, land(world, capsys))
        assert observed == expected


class TestLandMergeMethod:
    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                MergeCase(Landed(), lane_worktree=LaneWorktree.PRESENT), id="settings-withheld"
            ),
            pytest.param(
                MergeCase(
                    Landed(),
                    lane_worktree=LaneWorktree.PRESENT,
                    methods=frozenset({workboard.MergeMethod.MERGE, workboard.MergeMethod.SQUASH}),
                ),
                id="both",
            ),
            pytest.param(
                MergeCase(
                    Landed(),
                    lane_worktree=LaneWorktree.PRESENT,
                    methods=frozenset({workboard.MergeMethod.SQUASH, workboard.MergeMethod.REBASE}),
                ),
                id="squash-and-rebase-without-a-merge-commit",
            ),
            pytest.param(
                MergeCase(
                    Landed(),
                    lane_worktree=LaneWorktree.PRESENT,
                    trunk_config='merge_method = "squash"\n',
                    methods=frozenset({workboard.MergeMethod.MERGE, workboard.MergeMethod.SQUASH}),
                ),
                id="pinned-squash-lands-a-squash",
            ),
            pytest.param(
                MergeCase(
                    Landed(),
                    lane_worktree=LaneWorktree.PRESENT,
                    methods=frozenset(workboard.MergeMethod),
                    rules=(
                        frozenset({workboard.MergeMethod.SQUASH, workboard.MergeMethod.REBASE}),
                    ),
                ),
                id="ruleset-narrows-all-three-settings-to-a-squash",
            ),
            pytest.param(
                MergeCase(
                    Landed(),
                    lane_worktree=LaneWorktree.PRESENT,
                    rules=(
                        frozenset({workboard.MergeMethod.MERGE, workboard.MergeMethod.SQUASH}),
                        frozenset({workboard.MergeMethod.SQUASH, workboard.MergeMethod.REBASE}),
                        frozenset({workboard.MergeMethod.MERGE, workboard.MergeMethod.SQUASH}),
                    ),
                ),
                id="withheld-settings-narrowed-by-every-ruleset",
            ),
            pytest.param(
                MergeCase(
                    Landed(workboard.MergeMethod.MERGE, "Merge pull request #12", 2),
                    lane_worktree=LaneWorktree.PRESENT,
                    trunk_config='merge_method = "merge"\n',
                    methods=frozenset(workboard.MergeMethod),
                ),
                id="pinned-merge-with-every-method-allowed",
            ),
            pytest.param(
                MergeCase(
                    Landed(),
                    lane_worktree=LaneWorktree.PRESENT,
                    methods=frozenset(workboard.MergeMethod),
                ),
                id="all-three-settings-and-no-rule-pick-a-squash",
            ),
            pytest.param(
                MergeCase(
                    Landed(workboard.MergeMethod.MERGE, "Merge pull request #12", 2),
                    lane_worktree=LaneWorktree.PRESENT,
                    methods=frozenset({workboard.MergeMethod.MERGE, workboard.MergeMethod.REBASE}),
                ),
                id="merge-commit-where-no-squash-is-allowed",
            ),
            pytest.param(
                MergeCase(
                    Landed(),
                    lane_worktree=LaneWorktree.PRESENT,
                    default_branch=DefaultBranch.TRUNK_WITHOUT_MAIN,
                    methods=frozenset(workboard.MergeMethod),
                    rules=(
                        frozenset({workboard.MergeMethod.SQUASH, workboard.MergeMethod.REBASE}),
                    ),
                ),
                id="trunk-rule-narrows-the-method",
            ),
            pytest.param(
                MergeCase(
                    Landed(),
                    lane_worktree=LaneWorktree.PRESENT,
                    default_branch=DefaultBranch.TRUNK_WITH_REMOTE_MAIN,
                    methods=frozenset(workboard.MergeMethod),
                    decoy_rules=(
                        frozenset({workboard.MergeMethod.SQUASH, workboard.MergeMethod.REBASE}),
                    ),
                ),
                id="decoy-main-rule-is-ignored",
            ),
        ],
        indirect=True,
    )
    def test_lands(self, world: MergeWorld, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-27, LANDCMD-29, LANDCMD-39, LANDCMD-42.
        Every rule narrows the methods; successful landings remove their lane and upstream.
        """
        result = land(world, capsys)
        observed, expected = merge_observations(world, result)
        branches = local_branches(world.clone)
        observed.update(
            {
                "removed-line": "worktree: removed\n" in result.stdout,
                "lane.absent": not world.lane.exists(),
                "branch.absent": world.case.branch not in branches,
                "upstream": real_git(
                    world.clone, "config", f"branch.{world.case.branch}.remote", check=False
                ).stdout,
            }
        )
        expected.update(
            {"removed-line": True, "lane.absent": True, "branch.absent": True, "upstream": ""}
        )
        assert observed == expected

    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                MergeCase(
                    "pull request #12 cannot land: this repository allows "
                    "neither a merge commit nor a squash merge",
                    lane_worktree=LaneWorktree.PRESENT,
                    methods=frozenset({workboard.MergeMethod.REBASE}),
                ),
                id="only-rebase-refuses-before-the-merge",
            ),
            pytest.param(
                MergeCase(
                    "board.toml merge_method merge is not allowed on main: "
                    "GitHub allows squash, rebase",
                    lane_worktree=LaneWorktree.PRESENT,
                    trunk_config='merge_method = "merge"\n',
                    rules=(
                        frozenset({workboard.MergeMethod.SQUASH, workboard.MergeMethod.REBASE}),
                    ),
                ),
                id="pinned-merge-a-ruleset-excludes-refuses-before-the-merge",
            ),
            pytest.param(
                MergeCase(
                    "board.toml merge_method merge is not allowed on main: GitHub allows squash",
                    lane_worktree=LaneWorktree.PRESENT,
                    trunk_config='merge_method = "merge"\n',
                    methods=frozenset({workboard.MergeMethod.SQUASH}),
                ),
                id="pinned-merge-the-settings-exclude-refuses-before-the-merge",
            ),
            pytest.param(
                MergeCase(
                    "board.toml merge_method merge is not allowed on main: GitHub allows rebase",
                    lane_worktree=LaneWorktree.PRESENT,
                    trunk_config='merge_method = "merge"\n',
                    methods=frozenset(workboard.MergeMethod),
                    rules=(frozenset({workboard.MergeMethod.REBASE}),),
                ),
                id="pinned-merge-a-rebase-only-ruleset-excludes-refuses-before-the-merge",
            ),
            pytest.param(
                MergeCase(
                    "GitHub allows no merge method aco can use on main",
                    lane_worktree=LaneWorktree.PRESENT,
                    methods=frozenset({workboard.MergeMethod.MERGE}),
                    rules=(
                        frozenset({workboard.MergeMethod.SQUASH, workboard.MergeMethod.REBASE}),
                    ),
                ),
                id="ruleset-leaving-no-usable-method-refuses-before-the-merge",
            ),
            pytest.param(
                MergeCase(
                    "GitHub allows no merge method aco can use on main",
                    lane_worktree=LaneWorktree.PRESENT,
                    trunk_config='merge_method = "squash"\n',
                    methods=frozenset({workboard.MergeMethod.MERGE}),
                    rules=(
                        frozenset({workboard.MergeMethod.SQUASH, workboard.MergeMethod.REBASE}),
                    ),
                ),
                id="pinned-squash-a-ruleset-leaving-no-method-refuses-before-the-merge",
            ),
            pytest.param(
                MergeCase(
                    "pull request #12 cannot land: this repository allows "
                    "neither a merge commit nor a squash merge",
                    lane_worktree=LaneWorktree.PRESENT,
                    trunk_config='merge_method = "merge"\n',
                    methods=frozenset({workboard.MergeMethod.REBASE}),
                ),
                id="pinned-merge-and-a-rebase-only-repository",
            ),
            pytest.param(
                MergeCase(
                    "GitHub allows no merge method aco can use on main",
                    lane_worktree=LaneWorktree.PRESENT,
                    methods=frozenset(workboard.MergeMethod),
                    rules=(frozenset({workboard.MergeMethod.REBASE}),),
                ),
                id="unpinned-land-a-rebase-only-ruleset",
            ),
            pytest.param(
                MergeCase(
                    "board configuration {clone}/.aco/board.toml merge_method "
                    "must be 'merge' or 'squash'",
                    trunk_config='merge_method = "rebase"\n',
                    invalid_configuration=True,
                    length=RefusalLength.UNCHECKED,
                ),
                id="invalid-merge-method-pin",
            ),
        ],
        indirect=True,
    )
    def test_refusal(self, world: MergeWorld, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-28, LANDCMD-30, LANDCMD-40, LANDCMD-41.
        Invalid pins and unavailable methods refuse without changing the landing world.
        """
        observed, expected = refused_observations(world, capsys)
        assert observed == expected


class TestLandMergeForgeAnswer:
    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                MergeCase(
                    "pull request #12 changed while it was checked; re-run land",
                    error=forge.ForgeMergeConflictError(
                        "gh: Head branch was modified. Review and try the merge again. (HTTP 409)"
                    ),
                ),
                id="head-moved-409",
            ),
            pytest.param(
                MergeCase(
                    "GitHub refused the merge of pull request #12: "
                    "gh: Repository rule violations found (HTTP 405)",
                    error=forge.ForgeMergeRefusedError(
                        "gh: Repository rule violations found (HTTP 405)"
                    ),
                ),
                id="refused-405",
            ),
            pytest.param(
                MergeCase(
                    "GitHub refused the merge of pull request #12: blocked\\x1b[31m\\nagain",
                    error=forge.ForgeMergeRefusedError("blocked\x1b[31m\nagain"),
                ),
                id="refused-display-controls-escaped",
            ),
            pytest.param(
                MergeCase(
                    "pull request #12 may still be merging (gh: Server Error (HTTP 502)); "
                    "re-run aco land 12",
                    error=forge.ForgeMergeUnansweredError("gh: Server Error (HTTP 502)"),
                    reads_after_merge_request=1,
                ),
                id="server-error-with-the-pull-request-still-open",
            ),
            pytest.param(
                MergeCase(
                    "pull request #12 may still be merging (gh: Server Error (HTTP 502)); "
                    "re-run aco land 12",
                    error=forge.ForgeMergeUnansweredError("gh: Server Error (HTTP 502)"),
                    unreadable_after_merge_request=True,
                    reads_after_merge_request=1,
                ),
                id="server-error-and-the-pull-request-unreadable",
            ),
            pytest.param(
                MergeCase(
                    "pull request #12 may still be merging "
                    "(gh: Merge already in progress (HTTP 405)); re-run aco land 12",
                    error=forge.ForgeMergeInProgressError(
                        "gh: Merge already in progress (HTTP 405)"
                    ),
                    reads_after_merge_request=0,
                ),
                id="merge-already-in-progress-405",
            ),
        ],
        indirect=True,
    )
    def test_refusal(self, world: MergeWorld, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-14, LANDCMD-37, LANDCMD-71, LANDCMD-72.
        A rejected pinned request names its reason and leaves every durable effect unchanged.
        """
        observed, expected = refused_observations(world, capsys)
        requests = world.forge.merge_requests
        request = requests[0] if requests else ("missing", None)
        entry = world.entry_lineage[0] if world.entry_lineage else ("missing", "missing")
        observed.update(
            {
                "request.count": len(requests),
                "request.head": request[0],
                "request.method": request[1],
                "entry.stamp": entry[0],
                "entry.anchor": entry[1],
            }
        )
        expected.update(
            {
                "request.count": 1,
                "request.head": world.head,
                "request.method": workboard.MergeMethod.SQUASH,
                "entry.stamp": None,
                "entry.anchor": None,
            }
        )
        assert observed == expected

    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                MergeCase(
                    Landed(),
                    error=forge.ForgeMergeUnansweredError("gh: Server Error (HTTP 502)"),
                    merged_before_error=True,
                    unreadable_after_merge_request=True,
                    reads_after_merge_request=1,
                ),
                id="server-error-the-merge-outlived",
            ),
        ],
        indirect=True,
    )
    def test_rerun_after_a_pending_merge_finishes_without_a_second_merge(
        self, world: MergeWorld, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: LANDCMD-73, LANDCMD-18.
        A pull request that merged while the first run refused is released by the re-run.
        """
        first = land(world, capsys)
        world.forge.merge_error = None

        observed, expected = merge_observations(world, land(world, capsys))

        assert first.stderr.startswith("ERROR: pull request #12 may still be merging (")
        assert observed == expected
