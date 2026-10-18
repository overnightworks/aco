"""Land merge decisions through real claims, pushed branches and forge-side merges."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

import pytest
from cli_fixtures import (
    landed_from_another_clone,
    pull_request_listing,
    push_lane_branch,
    real_git,
    run_cli,
    track_board_config,
)
from github_fixtures import (
    LANDING_BRANCH,
    FakeForge,
    LandingWorld,
    RefusalLength,
    assert_github_world,
    landing_effects,
    landing_pull_request,
    landing_readiness,
    landing_world,
    refusal_observations,
    serve_forge,
)
from store_fixtures import (
    claim_intent,
    lineage_observation,
    publish_claims_from_a_second_clone,
)

from agent_coordination import board, forge, protocol, store


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


@dataclass(frozen=True)
class Landed:
    method: board.MergeMethod = board.MergeMethod.MERGE
    title: str = "Merge pull request #12"
    parents: int = 2
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
    methods: frozenset[board.MergeMethod] | None = None
    rules: tuple[frozenset[board.MergeMethod], ...] = ()
    error: forge.ForgeError | None = None
    oversized_foreign_text: bool = False
    distinct_detail: bool = False
    dependency_listing: bool = False
    invalid_configuration: bool = False
    length: RefusalLength = RefusalLength.WITHIN_LIMIT


@dataclass
class MergeWorld(LandingWorld):
    case: MergeCase
    head: str
    lane: Path
    entry_lineage: list[tuple[object, object]]


@pytest.fixture
def world(
    request: pytest.FixtureRequest,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> MergeWorld:
    case: MergeCase = request.param
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("GIT_DISCOVERY_ACROSS_FILESYSTEM", "1")
    assert_github_world(github_clone, bare_remote)
    if case.trunk_config and not case.invalid_configuration:
        track_board_config(github_clone, case.trunk_config)
        real_git(github_clone, "push", "-q", "origin", "main")
    head = push_lane_branch(github_clone, case.branch)
    intent = claim_intent(
        identity=case.identity,
        branch=case.branch,
        agent=case.holder.value,
        role=case.role.value,
        claim_id="landing",
        base=protocol.ObjectId(real_git(github_clone, "rev-parse", "main").stdout.strip()),
    )
    seeded = publish_claims_from_a_second_clone(github_clone, bare_remote, (intent,))
    observed = tuple(
        (c.identity, c.branch, c.agent, c.role, str(c.claim_id)) for c in seeded.claims.values()
    )
    expected = ((case.identity, case.branch, case.holder.value, case.role.value, "landing"),)
    assert observed == expected
    if case.invalid_configuration:
        track_board_config(github_clone, case.trunk_config)
        real_git(github_clone, "push", "-q", "origin", "main")
    lane = github_clone.parent / "lane"
    if case.lane_worktree is LaneWorktree.PRESENT:
        real_git(github_clone, "worktree", "add", "-q", str(lane), case.branch)
        real_git(github_clone, "branch", "--set-upstream-to", f"origin/{case.branch}", case.branch)
        observed = (
            real_git(lane, "branch", "--show-current").stdout,
            real_git(github_clone, "config", f"branch.{case.branch}.remote").stdout,
        )
        expected = (case.branch + "\n", "origin\n")
        assert observed == expected
    observed = (
        lane.exists(),
        real_git(github_clone, "rev-parse", case.branch).stdout.strip(),
        real_git(bare_remote, "rev-parse", case.branch).stdout.strip(),
        real_git(github_clone, "status", "--porcelain").stdout,
        real_git(github_clone, "branch", "--show-current").stdout,
        bool(real_git(github_clone, "diff", "main", case.branch).stdout),
    )
    expected = (case.lane_worktree.value, head, head, "", "main\n", True)
    assert observed == expected
    detail = replace(
        landing_pull_request(body=case.body, head_ref_name=case.branch),
        head_sha=real_git(github_clone, "rev-parse", "main").stdout.strip()
        if case.distinct_detail
        else head,
    )
    client = serve_forge(
        monkeypatch,
        FakeForge(
            landings={12: detail, 13: replace(detail, number=13)},
            readiness_by_number={12: landing_readiness(head_sha=head)},
            merge_remote=bare_remote,
            merge_error=case.error,
            allowed_methods=case.methods,
            branch_rules={"main": case.rules},
            head_board_config=case.head_config,
        ),
    )
    if case.dependency_listing:
        client.changes_by_number[12] = pull_request_listing(
            head, forge.ChangedFile("uv.lock", None)
        )
    if case.oversized_foreign_text:
        oversized = "1" * 4301
        client.board_open_pull_requests = (
            board.PullRequest(300, "Foreign", f"Refs #{oversized}", "foreign/branch"),
        )
        landed_from_another_clone(
            bare_remote.parent,
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            f"Foreign\n\nWork-Item: #{oversized}",
        )
    shared = landing_world(github_clone, bare_remote, client, remote_tip=seeded.tip)
    entry: list[tuple[object, object]] = []
    merge = client.merge_landing

    def observe_entry(
        number: int, *, head_sha: str, method: board.MergeMethod, title: str, body: str
    ) -> str:
        entry.append(lineage_observation(github_clone))
        return merge(number, head_sha=head_sha, method=method, title=title, body=body)

    monkeypatch.setattr(client, "merge_landing", observe_entry)
    return MergeWorld(github_clone, bare_remote, client, shared.unchanged, case, head, lane, entry)


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


def landed_observations(world: MergeWorld, capsys: pytest.CaptureFixture[str]):
    case = world.case
    outcome = case.outcome
    assert isinstance(outcome, Landed)
    result = land(world, capsys)
    effects = landing_effects(world)
    calls = world.forge.merge_calls
    trunk = real_git(world.clone, "rev-parse", "main").stdout.strip()
    remote_claims = store.peek_state(worktree=world.clone, remote=str(world.remote)).claims
    topology = tuple(
        line
        for line in real_git(world.clone, "worktree", "list", "--porcelain").stdout.splitlines()
        if line.startswith(("worktree ", "branch "))
    )
    branches = frozenset(
        real_git(
            world.clone, "for-each-ref", "--format=%(refname:short)", "refs/heads"
        ).stdout.splitlines()
    )
    entry = world.entry_lineage[0] if world.entry_lineage else ("missing", "missing")
    merge = calls[0] if calls else (None, None, None, None, "")
    observed = {
        "exit+": result.status,
        "err+": result.stderr,
        "release-line": (outcome.release in result.stdout),
        "merge.count": len(calls),
        "merge.number": merge[0],
        "merge.head": merge[1],
        "merge.method": merge[2],
        "merge.title": merge[3],
        "merge.end": merge[4].strip().split("\n\n")[-1],
        "delete+": effects["delete"],
        "close+": effects["close"],
        "body": effects["body"],
        "remote.moved": effects["remote"] != world.unchanged["remote"],
        "claims.empty": remote_claims,
        "local": effects["local"],
        "worktrees+": topology,
        "branches+": branches,
        "trunk.changed": trunk + "\n" != world.unchanged["trunk"],
        "trunk.is-merge": trunk == world.forge.landings[12].merge_commit,
        "trunk.parents": len(
            real_git(world.clone, "rev-list", "--parents", "-n", "1", trunk).stdout.split()
        )
        - 1,
        "stamp+": effects["stamp"] is not None,
        "anchor+": effects["anchor"] is not None,
        "entry.stamp": entry[0],
        "entry.anchor": entry[1],
    }
    expected = {
        "exit+": 0,
        "err+": "",
        "release-line": True,
        "merge.count": 1,
        "merge.number": 12,
        "merge.head": world.head,
        "merge.method": outcome.method,
        "merge.title": outcome.title,
        "merge.end": outcome.trailer,
        "delete+": [case.branch],
        "close+": set(outcome.closed),
        "body": [],
        "remote.moved": True,
        "claims.empty": {},
        "local": None,
        "worktrees+": (f"worktree {world.clone}", "branch refs/heads/main"),
        "branches+": frozenset({"main"})
        if case.lane_worktree is LaneWorktree.PRESENT
        else frozenset({"main", case.branch}),
        "trunk.changed": True,
        "trunk.is-merge": True,
        "trunk.parents": outcome.parents,
        "stamp+": True,
        "anchor+": True,
        "entry.stamp": None,
        "entry.anchor": None,
    }
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
    return observed, expected, result, branches


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
                    head_config=(
                        'priority_labels = ["ux"]\nidea_label = "idea"\nbody_contract = "block"\n'
                    ),
                ),
                id="only-non-governing-settings-changed",
            ),
            pytest.param(MergeCase(Landed(), reviewed=ReviewedHead.FULL), id="full-sha-matches"),
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
        ],
        indirect=True,
    )
    def test_lands(self, world: MergeWorld, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-09, LANDCMD-10, LANDCMD-12, LANDCMD-13, LANDCMD-23, LANDCMD-29, LANDCMD-32.
        The reviewed head lands, releases the real claim and retains the classification trailer.
        """
        observed, expected, _, _ = landed_observations(world, capsys)
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
                    methods=frozenset({board.MergeMethod.MERGE, board.MergeMethod.SQUASH}),
                ),
                id="both",
            ),
            pytest.param(
                MergeCase(
                    Landed(board.MergeMethod.SQUASH, "feat: land the lane (#12)", 1),
                    lane_worktree=LaneWorktree.PRESENT,
                    methods=frozenset({board.MergeMethod.SQUASH, board.MergeMethod.REBASE}),
                ),
                id="squash-and-rebase-without-a-merge-commit",
            ),
            pytest.param(
                MergeCase(
                    Landed(board.MergeMethod.SQUASH, "feat: land the lane (#12)", 1),
                    lane_worktree=LaneWorktree.PRESENT,
                    trunk_config='merge_method = "squash"\n',
                    methods=frozenset({board.MergeMethod.MERGE, board.MergeMethod.SQUASH}),
                ),
                id="pinned-squash-beats-the-default",
            ),
            pytest.param(
                MergeCase(
                    Landed(board.MergeMethod.SQUASH, "feat: land the lane (#12)", 1),
                    lane_worktree=LaneWorktree.PRESENT,
                    methods=frozenset(board.MergeMethod),
                    rules=(frozenset({board.MergeMethod.SQUASH, board.MergeMethod.REBASE}),),
                ),
                id="ruleset-narrows-all-three-settings-to-a-squash",
            ),
            pytest.param(
                MergeCase(
                    Landed(board.MergeMethod.SQUASH, "feat: land the lane (#12)", 1),
                    lane_worktree=LaneWorktree.PRESENT,
                    rules=(
                        frozenset({board.MergeMethod.MERGE, board.MergeMethod.SQUASH}),
                        frozenset({board.MergeMethod.SQUASH, board.MergeMethod.REBASE}),
                        frozenset({board.MergeMethod.MERGE, board.MergeMethod.SQUASH}),
                    ),
                ),
                id="withheld-settings-narrowed-by-every-ruleset",
            ),
            pytest.param(
                MergeCase(
                    Landed(),
                    lane_worktree=LaneWorktree.PRESENT,
                    trunk_config='merge_method = "merge"\n',
                    methods=frozenset(board.MergeMethod),
                ),
                id="pinned-merge-with-every-method-allowed",
            ),
            pytest.param(
                MergeCase(
                    Landed(),
                    lane_worktree=LaneWorktree.PRESENT,
                    methods=frozenset(board.MergeMethod),
                ),
                id="all-three-settings-and-no-rule-pick-a-merge-commit",
            ),
        ],
        indirect=True,
    )
    def test_lands(self, world: MergeWorld, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-27, LANDCMD-29, LANDCMD-39, LANDCMD-42.
        Every rule narrows the methods; successful landings remove their lane and upstream.
        """
        observed, expected, result, branches = landed_observations(world, capsys)
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
                    methods=frozenset({board.MergeMethod.REBASE}),
                ),
                id="only-rebase-refuses-before-the-merge",
            ),
            pytest.param(
                MergeCase(
                    "board.toml merge_method merge is not allowed on main: "
                    "GitHub allows squash, rebase",
                    lane_worktree=LaneWorktree.PRESENT,
                    trunk_config='merge_method = "merge"\n',
                    rules=(frozenset({board.MergeMethod.SQUASH, board.MergeMethod.REBASE}),),
                ),
                id="pinned-merge-a-ruleset-excludes-refuses-before-the-merge",
            ),
            pytest.param(
                MergeCase(
                    "board.toml merge_method merge is not allowed on main: GitHub allows squash",
                    lane_worktree=LaneWorktree.PRESENT,
                    trunk_config='merge_method = "merge"\n',
                    methods=frozenset({board.MergeMethod.SQUASH}),
                ),
                id="pinned-merge-the-settings-exclude-refuses-before-the-merge",
            ),
            pytest.param(
                MergeCase(
                    "board.toml merge_method merge is not allowed on main: GitHub allows rebase",
                    lane_worktree=LaneWorktree.PRESENT,
                    trunk_config='merge_method = "merge"\n',
                    methods=frozenset(board.MergeMethod),
                    rules=(frozenset({board.MergeMethod.REBASE}),),
                ),
                id="pinned-merge-a-rebase-only-ruleset-excludes-refuses-before-the-merge",
            ),
            pytest.param(
                MergeCase(
                    "GitHub allows no merge method aco can use on main",
                    lane_worktree=LaneWorktree.PRESENT,
                    methods=frozenset({board.MergeMethod.MERGE}),
                    rules=(frozenset({board.MergeMethod.SQUASH, board.MergeMethod.REBASE}),),
                ),
                id="ruleset-leaving-no-usable-method-refuses-before-the-merge",
            ),
            pytest.param(
                MergeCase(
                    "GitHub allows no merge method aco can use on main",
                    lane_worktree=LaneWorktree.PRESENT,
                    trunk_config='merge_method = "squash"\n',
                    methods=frozenset({board.MergeMethod.MERGE}),
                    rules=(frozenset({board.MergeMethod.SQUASH, board.MergeMethod.REBASE}),),
                ),
                id="pinned-squash-a-ruleset-leaving-no-method-refuses-before-the-merge",
            ),
            pytest.param(
                MergeCase(
                    "pull request #12 cannot land: this repository allows "
                    "neither a merge commit nor a squash merge",
                    lane_worktree=LaneWorktree.PRESENT,
                    trunk_config='merge_method = "merge"\n',
                    methods=frozenset({board.MergeMethod.REBASE}),
                ),
                id="pinned-merge-and-a-rebase-only-repository",
            ),
            pytest.param(
                MergeCase(
                    "GitHub allows no merge method aco can use on main",
                    lane_worktree=LaneWorktree.PRESENT,
                    methods=frozenset(board.MergeMethod),
                    rules=(frozenset({board.MergeMethod.REBASE}),),
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
        ],
        indirect=True,
    )
    def test_refusal(self, world: MergeWorld, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-14, LANDCMD-37.
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
                "request.method": board.MergeMethod.MERGE,
                "entry.stamp": None,
                "entry.anchor": None,
            }
        )
        assert observed == expected
