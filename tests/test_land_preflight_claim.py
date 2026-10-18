"""Land classification and checkout refusals with claims published by another clone."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, complete_contract, slice_entries
from cli_fixtures import (
    pull_request_listing,
    real_git,
    run_cli,
    track_board_config,
    trunk_git_calls,
    without_git_identity,
)
from github_fixtures import (
    LANDING_BRANCH,
    MERGE_COMMIT_SHA,
    FakeForge,
    LandingWorld,
    RefusalLength,
    assert_github_world,
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
    state_ref_tip,
)

from agent_coordination import board, body, forge, protocol, store


class CheckoutState(Enum):
    CLEAN = ("", "main\n")
    UNTRACKED_FILE = ("?? untracked.txt\n", "main\n")
    TRACKED_CHANGE = (" M .aco/board.toml\n", "main\n")
    OTHER_BRANCH = ("", "other\n")


class IdentityState(Enum):
    PRESENT = "present"
    ABSENT = "absent"
    AUTHOR_ONLY = "author-only"


@dataclass(frozen=True)
class ClaimCase:
    sentence: str
    pull_request: forge.Landing = field(
        default_factory=lambda: landing_pull_request(body="Work-Item: #72\n\nCloses #72")
    )
    readiness: forge.LandingReadiness = field(default_factory=landing_readiness)
    intents: tuple[protocol.ClaimIntent, ...] = field(
        default_factory=lambda: (
            claim_intent(identity=protocol.IssueIdentity(72), branch=LANDING_BRANCH),
        )
    )
    trunk_config: str = ""
    head_config: str | None = ""
    closed_items: frozenset[int] = frozenset()
    listing: forge.PullRequestChanges = field(
        default_factory=lambda: pull_request_listing(
            MERGE_COMMIT_SHA, forge.ChangedFile("uv.lock", None)
        )
    )
    arguments: tuple[str, ...] = ()
    checkout: CheckoutState = CheckoutState.CLEAN
    identity: IdentityState = IdentityState.PRESENT
    lane_worktree: bool = False
    default_branch: str = "main"
    item_reads: tuple[int, ...] = (72,)
    changes_reads: tuple[int, ...] = ()
    file_reads: tuple[tuple[str, str], ...] = ((".aco/board.toml", MERGE_COMMIT_SHA),)
    check_claims: bool = False
    claims_present: bool = False
    parent: board.ParentIssue | None = None
    length: RefusalLength = RefusalLength.UNCHECKED


@dataclass
class ClaimWorld(LandingWorld):
    case: ClaimCase
    claims: tuple[protocol.ActiveClaim, ...]
    checkout_before: tuple[str, str]
    lane: Path
    trunk_calls: list[tuple[str, Path]]
    default_trunk: str | None


@pytest.fixture
def world(
    request: pytest.FixtureRequest,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> ClaimWorld:
    case: ClaimCase = request.param
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("GIT_DISCOVERY_ACROSS_FILESYSTEM", "1")
    assert_github_world(github_clone, bare_remote)
    if case.trunk_config:
        track_board_config(github_clone, case.trunk_config)
        real_git(github_clone, "push", "-q", "origin", "main")
    seeded = publish_claims_from_a_second_clone(github_clone, bare_remote, case.intents)
    claims = tuple(seeded.claims.values())
    observed = tuple((c.identity, c.branch, c.agent, c.role) for c in claims)
    expected = tuple((c.identity, c.branch, c.agent, c.role) for c in case.intents)
    assert observed == expected
    observed = (
        lineage_observation(github_clone),
        state_ref_tip(github_clone),
        state_ref_tip(bare_remote),
    )
    expected = ((None, None), None, seeded.tip)
    assert observed == expected
    if case.default_branch == "trunk":
        real_git(github_clone, "branch", "trunk")
        real_git(github_clone, "push", "-q", "origin", "trunk")
        real_git(github_clone, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
        observed = (
            real_git(
                github_clone, "rev-parse", "-q", "--verify", "refs/remotes/origin/HEAD", check=False
            ).returncode
            == 0,
            real_git(github_clone, "rev-parse", "-q", "--verify", "trunk", check=False).returncode
            == 0,
            real_git(bare_remote, "rev-parse", "-q", "--verify", "trunk", check=False).returncode
            == 0,
        )
        assert observed == (False, True, True)
    lane = github_clone.parent / "lane"
    if case.lane_worktree:
        real_git(
            github_clone,
            "worktree",
            "add",
            "-q",
            "-b",
            LANDING_BRANCH,
            str(lane),
            "main",
        )
    if case.checkout is CheckoutState.UNTRACKED_FILE:
        (github_clone / "untracked.txt").write_text("dirty\n")
    elif case.checkout is CheckoutState.TRACKED_CHANGE:
        (github_clone / ".aco/board.toml").write_text(case.trunk_config + "# dirty\n")
    elif case.checkout is CheckoutState.OTHER_BRANCH:
        real_git(github_clone, "checkout", "-q", "-b", "other")
    if case.identity is not IdentityState.PRESENT:
        without_git_identity(monkeypatch, github_clone)
        if case.identity is IdentityState.AUTHOR_ONLY:
            monkeypatch.setenv("GIT_AUTHOR_NAME", "Author")
            monkeypatch.setenv("GIT_AUTHOR_EMAIL", "author@example.com")
        observed = tuple(
            real_git(github_clone, "var", key, check=False).returncode == 0
            for key in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT")
        )
        expected = (case.identity is IdentityState.AUTHOR_ONLY, False)
        assert observed == expected
    client = serve_forge(
        monkeypatch,
        FakeForge(
            landings={12: case.pull_request},
            readiness_by_number={12: case.readiness},
            head_board_config=case.head_config,
            closed_issues=set(case.closed_items),
            changes_by_number={12: case.listing},
            default_branch_name=case.default_branch,
            parents={72: case.parent} if case.parent is not None else {},
            children={case.parent.reference.number: ()} if case.parent is not None else {},
        ),
    )
    shared = landing_world(github_clone, bare_remote, client, remote_tip=seeded.tip)
    unchanged = shared.unchanged
    checkout_before = (
        real_git(github_clone, "status", "--porcelain").stdout,
        real_git(github_clone, "branch", "--show-current").stdout,
    )
    assert checkout_before == case.checkout.value
    result = ClaimWorld(
        github_clone,
        bare_remote,
        client,
        unchanged,
        case,
        claims,
        checkout_before,
        lane,
        trunk_git_calls(monkeypatch, "origin"),
        real_git(github_clone, "rev-parse", "trunk").stdout
        if case.default_branch == "trunk"
        else None,
    )
    return result


def assert_refusal(world: ClaimWorld, capsys: pytest.CaptureFixture[str]) -> None:
    case = world.case
    capsys.readouterr()
    result = run_cli(["land", "12", *case.arguments], capsys)
    observed, expected = refusal_observations(world, result, case.sentence, length=case.length)
    observed.update(
        {
            "status": real_git(world.clone, "status", "--porcelain").stdout,
            "branch": real_git(world.clone, "branch", "--show-current").stdout,
            "item": tuple(world.forge.issue_reference_lookups),
            "changes": tuple(world.forge.changes_reads),
            "file": tuple((path.as_posix(), sha) for path, sha in world.forge.file_reads),
        }
    )
    expected.update(
        {
            "status": world.checkout_before[0],
            "branch": world.checkout_before[1],
            "item": case.item_reads,
            "changes": case.changes_reads,
            "file": case.file_reads,
        }
    )
    if case.check_claims or case.claims_present:
        claims = tuple(store.peek_state(worktree=world.clone, remote="origin").claims.values())
        if case.check_claims:
            observed["claims"] = claims
            expected["claims"] = world.claims
        if case.claims_present:
            observed["claims-present"] = bool(claims)
            expected["claims-present"] = True
    if case.lane_worktree:
        observed["lane_worktree"] = world.lane.exists()
        expected["lane_worktree"] = True
    if world.default_trunk is not None:
        local_trunk = real_git(world.clone, "rev-parse", "trunk").stdout
        observed.update(
            {
                "trunk-fetches": [call for call in world.trunk_calls if call[0] == "fetch"],
                "default-trunk": local_trunk,
                "trunk-is-merge": local_trunk.strip() == world.forge.landings[12].merge_commit,
            }
        )
        expected.update(
            {"trunk-fetches": [], "default-trunk": world.default_trunk, "trunk-is-merge": False}
        )
    assert observed == expected


def toml_error(text: str) -> str:
    """The syntax diagnostic owned by the interpreter for this row's input."""
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        return str(error)
    raise AssertionError(f"{text!r} parses as TOML")


class TestLandClassification:
    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                ClaimCase(
                    "pull request #12 carries no `Work-Item:` or `No-Item:` line",
                    pull_request=landing_pull_request(body="Advances #72", head_ref_name="fix/x"),
                    intents=(claim_intent(identity=protocol.LaneIdentity(), branch="fix/x"),),
                    item_reads=(),
                    file_reads=(),
                    check_claims=True,
                ),
                id="unclassified",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 proposes a branch of other/repo; "
                    "cross-repository pull requests are not classified",
                    pull_request=landing_pull_request(
                        body="Work-Item: #72\n\nCloses #72", head_repository="other/repo"
                    ),
                    item_reads=(),
                    file_reads=(),
                ),
                id="cross-repository",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 targets 'develop', not the default branch 'main'",
                    pull_request=landing_pull_request(
                        body="Work-Item: #72\n\nCloses #72", base_ref_name="develop"
                    ),
                    item_reads=(),
                    file_reads=(),
                ),
                id="target-branch",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 has non-successful checks: b "
                    "(failure); land only after every check succeeds",
                    pull_request=landing_pull_request(body="Advances #72"),
                    readiness=landing_readiness(checks=(forge.CheckRun("b", "failure"),)),
                    item_reads=(),
                    file_reads=(),
                ),
                id="failed-check-and-unclassified",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 carries no `Work-Item:` or `No-Item:` line",
                    pull_request=landing_pull_request(body="Advances #72"),
                    head_config=None,
                    item_reads=(),
                    file_reads=(),
                ),
                id="unclassified-and-head-without-config",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 declares No-Item: deps, but "
                    ".aco/board.toml names no dependency_paths",
                    pull_request=landing_pull_request(body="No-Item: deps", head_ref_name="fix/x"),
                    intents=(claim_intent(identity=protocol.LaneIdentity(), branch="fix/x"),),
                    item_reads=(),
                    check_claims=True,
                ),
                id="deps-without-dependency-paths",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 changed while aco listed its files; run the command again",
                    pull_request=replace(
                        landing_pull_request(body="No-Item: deps", head_ref_name="fix/x"),
                        head_sha="b" * 40,
                    ),
                    intents=(claim_intent(identity=protocol.LaneIdentity(), branch="fix/x"),),
                    item_reads=(),
                    trunk_config=(
                        'dependency_paths = ["pyproject.toml", "uv.lock", ".github/workflows/"]\n'
                    ),
                    changes_reads=(12,),
                    listing=pull_request_listing("b" * 40, forge.ChangedFile("uv.lock", None)),
                    arguments=("--head", MERGE_COMMIT_SHA),
                    check_claims=True,
                ),
                id="listing-changed-under-us",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 changes src/x.py, which "
                    "dependency_paths in .aco/board.toml does not name",
                    pull_request=landing_pull_request(body="No-Item: deps", head_ref_name="fix/x"),
                    intents=(claim_intent(identity=protocol.LaneIdentity(), branch="fix/x"),),
                    item_reads=(),
                    trunk_config=(
                        'dependency_paths = ["pyproject.toml", "uv.lock", ".github/workflows/"]\n'
                    ),
                    changes_reads=(12,),
                    listing=pull_request_listing(
                        MERGE_COMMIT_SHA,
                        forge.ChangedFile("uv.lock", None),
                        forge.ChangedFile("src/x.py", None),
                    ),
                    arguments=("--head", MERGE_COMMIT_SHA),
                    check_claims=True,
                ),
                id="path-outside",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 changes "
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa…, "
                    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb…, "
                    "ccccccccccccccccccccccccccccccccccccccc…, which "
                    "dependency_paths in .aco/board.toml…",
                    pull_request=landing_pull_request(body="No-Item: deps", head_ref_name="fix/x"),
                    intents=(claim_intent(identity=protocol.LaneIdentity(), branch="fix/x"),),
                    item_reads=(),
                    trunk_config=(
                        'dependency_paths = ["pyproject.toml", "uv.lock", ".github/workflows/"]\n'
                    ),
                    changes_reads=(12,),
                    listing=pull_request_listing(
                        MERGE_COMMIT_SHA,
                        forge.ChangedFile(
                            "a" * 300,
                            None,
                        ),
                        forge.ChangedFile(
                            "b" * 300,
                            None,
                        ),
                        forge.ChangedFile(
                            "c" * 300,
                            None,
                        ),
                    ),
                    arguments=("--head", MERGE_COMMIT_SHA),
                    check_claims=True,
                    length=RefusalLength.EXACTLY_LIMIT,
                ),
                id="many-long-paths-bounded",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 changes src/\\x1b]0;pwned\\x07x.py, "
                    "which dependency_paths in .aco/board.toml does not "
                    "name",
                    pull_request=landing_pull_request(body="No-Item: deps", head_ref_name="fix/x"),
                    intents=(claim_intent(identity=protocol.LaneIdentity(), branch="fix/x"),),
                    item_reads=(),
                    trunk_config=(
                        'dependency_paths = ["pyproject.toml", "uv.lock", ".github/workflows/"]\n'
                    ),
                    changes_reads=(12,),
                    listing=pull_request_listing(
                        MERGE_COMMIT_SHA, forge.ChangedFile("src/\x1b]0;pwned\x07x.py", None)
                    ),
                ),
                id="path-escape",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 changes src/x.py\\nPR #12 by bot "
                    "declares No-Ite…, which dependency_paths in "
                    ".aco/board.toml does not name",
                    pull_request=landing_pull_request(body="No-Item: deps", head_ref_name="fix/x"),
                    intents=(claim_intent(identity=protocol.LaneIdentity(), branch="fix/x"),),
                    item_reads=(),
                    trunk_config=(
                        'dependency_paths = ["pyproject.toml", "uv.lock", ".github/workflows/"]\n'
                    ),
                    changes_reads=(12,),
                    listing=pull_request_listing(
                        MERGE_COMMIT_SHA,
                        forge.ChangedFile("src/x.py\nPR #12 by bot declares No-Item: deps", None),
                    ),
                ),
                id="path-newline",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 changes "
                    "src/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx…, which "
                    "dependency_paths in .aco/board.toml does not name",
                    pull_request=landing_pull_request(body="No-Item: deps", head_ref_name="fix/x"),
                    intents=(claim_intent(identity=protocol.LaneIdentity(), branch="fix/x"),),
                    item_reads=(),
                    trunk_config=(
                        'dependency_paths = ["pyproject.toml", "uv.lock", ".github/workflows/"]\n'
                    ),
                    changes_reads=(12,),
                    listing=pull_request_listing(
                        MERGE_COMMIT_SHA,
                        forge.ChangedFile(
                            "src/" + "x" * 300,
                            None,
                        ),
                    ),
                ),
                id="path-long",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 changes src/x.py, which "
                    "dependency_paths in .aco/board.toml does not name",
                    pull_request=landing_pull_request(body="No-Item: deps", head_ref_name="fix/x"),
                    intents=(claim_intent(identity=protocol.LaneIdentity(), branch="fix/x"),),
                    item_reads=(),
                    trunk_config=(
                        'dependency_paths = ["pyproject.toml", "uv.lock", ".github/workflows/"]\n'
                    ),
                    changes_reads=(12,),
                    listing=pull_request_listing(
                        MERGE_COMMIT_SHA,
                        forge.ChangedFile("uv.lock", None),
                        forge.ChangedFile("src/x.py", None),
                    ),
                    arguments=("--head", MERGE_COMMIT_SHA),
                    head_config='dependency_paths = ["uv.lock", "src/"]\n',
                ),
                id="head-grant-ignored",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 has no active claim for #72 on "
                    "branch 'codex/issue-72-claims'",
                    intents=(),
                ),
                id="missing-claim",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 has no active issue-less lane claim on branch 'fix/x'",
                    pull_request=landing_pull_request(body="No-Item: fix", head_ref_name="fix/x"),
                    intents=(),
                    item_reads=(),
                ),
                id="lane-missing-claim",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 carries no closing reference for its "
                    "work item example/agent-coordination#72",
                    pull_request=landing_pull_request(body="Work-Item: #72"),
                    intents=(
                        claim_intent(
                            identity=protocol.IssueIdentity(72), branch=LANDING_BRANCH, agent="Grok"
                        ),
                    ),
                ),
                id="no-closing-reference-and-foreign-claim",
            ),
        ],
        indirect=True,
    )
    def test_refusal(self, world: ClaimWorld, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-07, LANDCMD-09, LANDCMD-06, PIN-47 -- exact refusal and no writes."""
        assert_refusal(world, capsys)


class TestLandHeadConfig:
    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                ClaimCase(
                    "pull request #12 removes .aco/board.toml; "
                    "aco land cannot release its claim across that change",
                    head_config=None,
                    item_reads=(),
                    length=RefusalLength.WITHIN_LIMIT,
                ),
                id="head-without-config",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 removes .aco/board.toml; "
                    "aco land cannot release its claim across that change",
                    head_config=None,
                    closed_items=frozenset({72}),
                    item_reads=(),
                    length=RefusalLength.WITHIN_LIMIT,
                ),
                id="removed-ahead-of-a-closed-item",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 changes storage in .aco/board.toml; "
                    "aco land cannot release its claim across that change",
                    head_config='storage = "state-ref"\n',
                    item_reads=(),
                    length=RefusalLength.WITHIN_LIMIT,
                ),
                id="storage-changed",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 changes canonical_remote in .aco/board.toml; "
                    "aco land cannot release its claim across that change",
                    head_config='canonical_remote = "upstream"\n',
                    item_reads=(),
                    length=RefusalLength.WITHIN_LIMIT,
                ),
                id="canonical-remote-changed",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 carries an invalid .aco/board.toml: board configuration "
                    ".aco/board.toml storage must be 'github' or 'state-ref'",
                    head_config='storage = "gitlab"\n',
                    item_reads=(),
                    length=RefusalLength.WITHIN_LIMIT,
                ),
                id="invalid",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 carries an invalid .aco/board.toml: board configuration "
                    ".aco/board.toml merge_method must be 'merge' or 'squash'",
                    head_config='merge_method = "rebase"\n',
                    item_reads=(),
                    length=RefusalLength.WITHIN_LIMIT,
                ),
                id="invalid-merge-method",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 carries an invalid .aco/board.toml: cannot read board "
                    f"configuration .aco/board.toml: {toml_error('not toml =')}",
                    head_config="not toml =",
                    item_reads=(),
                    length=RefusalLength.WITHIN_LIMIT,
                ),
                id="invalid-syntax",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 carries an invalid .aco/board.toml: board configuration "
                    ".aco/board.toml has unknown top-level key " + "x" * 77 + "…",
                    head_config=f'{"x" * 300} = "y"\n',
                    item_reads=(),
                    length=RefusalLength.EXACTLY_LIMIT,
                ),
                id="invalid-bounded",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 carries an invalid .aco/board.toml: board configuration "
                    ".aco/board.toml has unknown top-level key bad\\nkey, esc\\x1b[31m",
                    head_config='"bad\\nkey" = 1\n"esc\\u001b[31m" = 2\n',
                    item_reads=(),
                    length=RefusalLength.WITHIN_LIMIT,
                ),
                id="invalid-control-characters-escaped",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 carries an invalid .aco/board.toml: board configuration "
                    ".aco/board.toml has unknown top-level key a\N{REVERSE SOLIDUS}u202eb"
                    "\\u2066c\\u200bd\\x9be\tf\xa0g",
                    head_config=('"a\u202eb\u2066c\u200bd\x9be\tf\N{NO-BREAK SPACE}g" = 1\n'),
                    item_reads=(),
                    length=RefusalLength.WITHIN_LIMIT,
                ),
                id="invalid-display-controls-escaped",
            ),
        ],
        indirect=True,
    )
    def test_refusal(self, world: ClaimWorld, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-22, LANDCMD-23, LANDCMD-24 -- exact refusal and no writes."""
        assert_refusal(world, capsys)


class TestLandItemAndClaim:
    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                ClaimCase(
                    "work item #72 is not open; it cannot be landed", closed_items=frozenset({72})
                ),
                id="closed-item",
            ),
            pytest.param(
                ClaimCase(
                    "work item #72 is not open; it cannot be landed",
                    closed_items=frozenset({72}),
                    intents=(),
                ),
                id="closed-before-missing-claim",
            ),
            pytest.param(
                ClaimCase(
                    f"pull request #12 closes parent {REPOSITORY}#79 although its body "
                    "still holds an uncut slice row; cut it or delete the row first",
                    pull_request=landing_pull_request(
                        body="Work-Item: #72\n\nCloses #72\nCloses #79"
                    ),
                    parent=board.ParentIssue(
                        board.IssueReference(REPOSITORY, 79),
                        complete_contract("keiner", slice=slice_entries("Scheibe 1")),
                        body.ItemKind.CONTAINER,
                    ),
                    check_claims=True,
                ),
                id="closing-a-parent-with-an-uncut-row",
            ),
            pytest.param(
                ClaimCase(
                    "pull request #12 has no active issue-less lane claim on branch 'fix/x'",
                    closed_items=frozenset({72}),
                    pull_request=landing_pull_request(body="No-Item: fix", head_ref_name="fix/x"),
                    intents=(),
                    item_reads=(),
                ),
                id="issue-less-skips-the-item-check",
            ),
            pytest.param(
                ClaimCase(
                    "only the original claimant may release; repeat as the "
                    "holder with `aco land 12 --agent Grok`, or use an "
                    "explicit coordinator override (holder='Grok "
                    "(builder)', this session='Ada (builder)')",
                    intents=(
                        claim_intent(
                            identity=protocol.IssueIdentity(72), branch=LANDING_BRANCH, agent="Grok"
                        ),
                    ),
                    arguments=(),
                ),
                id="foreign-claim",
            ),
            pytest.param(
                ClaimCase(
                    "only the original claimant may release; repeat as the "
                    "holder with `aco land 12 --keep-worktree --agent "
                    "Grok`, or use an explicit coordinator override "
                    "(holder='Grok (builder)', this session='Ada "
                    "(builder)')",
                    intents=(
                        claim_intent(
                            identity=protocol.IssueIdentity(72), branch=LANDING_BRANCH, agent="Grok"
                        ),
                    ),
                    arguments=("--keep-worktree",),
                ),
                id="foreign-claim-keeps-the-worktree-flag",
            ),
            pytest.param(
                ClaimCase(
                    "only the original claimant may release; repeat as the "
                    "holder with `aco land 12 --head a1b2c3d "
                    "--keep-worktree --agent Grok`, or use an explicit "
                    "coordinator override (holder='Grok (builder)', this "
                    "session='Ada (builder)')",
                    intents=(
                        claim_intent(
                            identity=protocol.IssueIdentity(72), branch=LANDING_BRANCH, agent="Grok"
                        ),
                    ),
                    arguments=("--keep-worktree", "--head", "A1B2C3D"),
                ),
                id="foreign-claim-keeps-the-reviewed-head",
            ),
            pytest.param(
                ClaimCase(
                    "only the original claimant may release; repeat as the "
                    "holder with `aco land 12 --agent Ada --role "
                    "coordinator`, or use an explicit coordinator override "
                    "(holder='Ada (coordinator)', this session='Ada "
                    "(builder)')",
                    intents=(
                        claim_intent(
                            identity=protocol.IssueIdentity(72),
                            branch=LANDING_BRANCH,
                            role="coordinator",
                        ),
                    ),
                    arguments=("--role", "builder"),
                ),
                id="foreign-role",
            ),
            pytest.param(
                ClaimCase(
                    "only the original claimant may release; repeat as the "
                    "holder with `aco land 12 --agent Grok`, or use an "
                    "explicit coordinator override (holder='Grok "
                    "(builder)', this session='Ada (builder)')",
                    intents=(
                        claim_intent(
                            identity=protocol.IssueIdentity(72), branch=LANDING_BRANCH, agent="Grok"
                        ),
                    ),
                    arguments=(),
                    checkout=CheckoutState.UNTRACKED_FILE,
                ),
                id="foreign-claim-and-dirty-checkout",
            ),
        ],
        indirect=True,
    )
    def test_refusal(self, world: ClaimWorld, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-08, LANDCMD-10 -- exact refusal and no writes."""
        assert_refusal(world, capsys)


class TestLandCheckout:
    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                ClaimCase(
                    "land must run from a clean checkout of the default branch 'main'",
                    checkout=CheckoutState.UNTRACKED_FILE,
                ),
                id="dirty-checkout",
            ),
            pytest.param(
                ClaimCase(
                    "land must run from a clean checkout of the default branch 'main'",
                    checkout=CheckoutState.TRACKED_CHANGE,
                ),
                id="tracked-change",
            ),
            pytest.param(
                ClaimCase(
                    "land must run from a clean checkout of the default branch 'main'",
                    checkout=CheckoutState.OTHER_BRANCH,
                ),
                id="other-branch",
            ),
            pytest.param(
                ClaimCase(
                    "land must run from a clean checkout of the default branch 'main'",
                    checkout=CheckoutState.UNTRACKED_FILE,
                    identity=IdentityState.ABSENT,
                ),
                id="dirty-checkout-and-no-identity",
            ),
            pytest.param(
                ClaimCase(
                    "land must run from a checkout with a git identity; "
                    "set user.name and user.email there so its release can "
                    "commit to the claim state",
                    identity=IdentityState.ABSENT,
                    lane_worktree=True,
                    claims_present=True,
                ),
                id="no-identity-refuses-before-the-merge",
            ),
            pytest.param(
                ClaimCase(
                    "land must run from a checkout with a git identity; "
                    "set user.name and user.email there so its release can "
                    "commit to the claim state",
                    pull_request=landing_pull_request(
                        body="Work-Item: #72\n\nCloses #72", merged=True
                    ),
                    identity=IdentityState.ABSENT,
                    item_reads=(),
                    file_reads=(),
                ),
                id="rerun-no-identity",
            ),
            pytest.param(
                ClaimCase(
                    "land must run from a checkout with a git identity; "
                    "set user.name and user.email there so its release can "
                    "commit to the claim state",
                    identity=IdentityState.AUTHOR_ONLY,
                ),
                id="committer-only",
            ),
            pytest.param(
                ClaimCase(
                    "land must run from a clean checkout of the default branch 'trunk'",
                    pull_request=landing_pull_request(
                        body="Work-Item: #72\n\nCloses #72", base_ref_name="trunk"
                    ),
                    default_branch="trunk",
                    lane_worktree=True,
                ),
                id="checkout-on-main-names-trunk",
            ),
        ],
        indirect=True,
    )
    def test_refusal(self, world: ClaimWorld, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-11, LANDCMD-25, LANDCMD-20, LANDCMD-18 -- exact refusal and no writes."""
        assert_refusal(world, capsys)
