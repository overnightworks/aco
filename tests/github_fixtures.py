"""Pull-request scenario values and the fake forge."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, board_issue
from cli_fixtures import CliRun, local_branches, push_lane_branch, real_git, worktrees_and_branches
from store_fixtures import (
    claim_intent,
    lineage_observation,
    publish_claims_from_a_second_clone,
    state_ref_tip,
)

from agent_coordination import board, body, cmd_land, forge, github, protocol, store
from agent_coordination.protocol import ClaimError

WORK_ITEM_ISSUE = 72
LANDING_BRANCH = f"codex/issue-{WORK_ITEM_ISSUE}-claims"
# A well-formed 40-hex sha (issue #397): the merge commit a merged `Landing`
# carries, matching `protocol.COMMIT_PATTERN` -- its own digits never mean
# anything beyond "a plausible sha", so every scenario that just needs one
# shares this instead of inventing a fresh, equally arbitrary string.
MERGE_COMMIT_SHA = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"


def landing_pull_request(
    *,
    body: str,
    number: int = 12,
    base_ref_name: str = "main",
    head_ref_name: str = LANDING_BRANCH,
    head_repository: str = REPOSITORY,
    author: str = "ada",
    merged: bool = False,
    merge_commit: str | None = None,
    title: str = "feat: land the lane",
) -> forge.Landing:
    """`merge_commit` defaults to a shared, well-formed sha once `merged` is
    true (a real merged pull request always carries one) and to `None`
    otherwise; a test proving the merge commit's own authority
    (issue #397) passes its own sha instead."""
    return forge.Landing(
        number,
        author,
        body,
        github.repository_id(head_repository),
        head_ref_name,
        base_ref_name,
        merged,
        merge_commit if merge_commit is not None else (MERGE_COMMIT_SHA if merged else None),
        title,
        MERGE_COMMIT_SHA,
    )


def landing_readiness(
    number: int = 12,
    *,
    head_sha: str = MERGE_COMMIT_SHA,
    mergeable_state: str = forge.MERGEABLE_STATE_CLEAN,
    checks: tuple[forge.CheckRun, ...] = (forge.CheckRun("ci", forge.CHECK_CONCLUSION_SUCCESS),),
) -> forge.LandingReadiness:
    return forge.LandingReadiness(number, True, head_sha, mergeable_state, checks)


def serve_forge(monkeypatch: pytest.MonkeyPatch, forge: FakeForge) -> FakeForge:
    """Install one arranged forge at the GitHub adapter boundary."""
    monkeypatch.setattr(github, "GitHubForge", lambda repository: forge)
    return forge


def merge_on_the_forge(
    remote: Path,
    default_branch: str,
    source_branch: str,
    message: str,
    method: board.MergeMethod,
) -> str:
    """The commit a forge's own merge of `source_branch` into
    `default_branch` with `method` pushes to the bare `remote` -- a merge
    commit, or one squashed single-parent commit -- built in a clone of it
    beside `remote` so no landing checkout moves with it."""
    clone = remote.parent / "forge-merge"
    real_git(remote.parent, "clone", "-q", "-b", default_branch, str(remote), str(clone))
    real_git(clone, "config", "user.name", "Forge")
    real_git(clone, "config", "user.email", "forge@example.com")
    real_git(clone, "config", "commit.gpgsign", "false")
    if method is board.MergeMethod.SQUASH:
        real_git(clone, "merge", "-q", "--squash", f"origin/{source_branch}")
        real_git(clone, "commit", "-q", "-m", message)
    else:
        real_git(clone, "merge", "-q", "--no-ff", "-m", message, f"origin/{source_branch}")
    real_git(clone, "push", "-q", "origin", f"HEAD:{default_branch}")
    return real_git(clone, "rev-parse", "HEAD").stdout.strip()


@dataclass
class FakeForge:
    board_issues: tuple[board.Issue, ...] = ()
    board_open_pull_requests: tuple[board.PullRequest, ...] = ()
    board_merged_pull_requests: tuple[board.PullRequest, ...] = ()
    board_dependencies: dict[int, tuple[board.IssueDependency, ...]] = field(default_factory=dict)
    repository: forge.RepositoryId = field(default_factory=lambda: github.repository_id(REPOSITORY))
    default_branch_name: str = "main"
    default_branch_error: forge.ForgeError | None = None
    landings: dict[int, forge.Landing] = field(default_factory=dict)
    changes_by_number: dict[int, forge.PullRequestChanges | forge.ForgeError] = field(
        default_factory=dict
    )
    changes_reads: list[int] = field(default_factory=list)
    parents: dict[int, board.ParentIssue] = field(default_factory=dict)
    children: dict[int, tuple[board.ChildItem, ...]] = field(default_factory=dict)
    closed_issues: set[int] = field(default_factory=set)
    recently_closed_issues: tuple[forge.ClosedIssue, ...] = ()
    closed_issue_cutoffs: list[datetime] = field(default_factory=list)
    landing_comments: dict[int, str] = field(default_factory=dict)
    issue_references: dict[int, forge.ItemReference] = field(default_factory=dict)
    issue_reference_lookups: list[int] = field(default_factory=list)
    created_children: list[tuple[int, str, str, body.ItemKind]] = field(default_factory=list)
    created_issues: list[tuple[str, str, body.ItemKind]] = field(default_factory=list)
    linked_children: list[tuple[int, int]] = field(default_factory=list)
    retyped_items: list[tuple[int, body.ItemKind]] = field(default_factory=list)
    next_created_child_number: int = 900
    item_bodies: dict[int, str] = field(default_factory=dict)
    fail_update_item_body: bool = False
    update_item_body_error: ClaimError | None = None
    update_item_body_lands_before_error: bool = False
    body_writes: list[tuple[int, str]] = field(default_factory=list)
    scripted_item_reads: list[str | forge.ForgeError | None] = field(default_factory=list)
    fail_create_child_relation: bool = False
    fail_set_item_kind: bool = False
    drop_created_issue_type: bool = False
    capability_overrides: dict[forge.ForgeOperation, forge.Capability] = field(default_factory=dict)
    readiness_by_number: dict[int, forge.LandingReadiness] = field(default_factory=dict)
    merge_calls: list[tuple[int, str, board.MergeMethod, str, str]] = field(default_factory=list)
    merge_requests: list[tuple[str, board.MergeMethod]] = field(default_factory=list)
    merge_error: forge.ForgeError | None = None
    delete_error: forge.ForgeError | None = None
    close_error: forge.ForgeError | None = None
    merge_sha: str = MERGE_COMMIT_SHA
    merge_remote: Path | None = None
    closes_on_merge: bool = False
    allowed_methods: frozenset[board.MergeMethod] | None = None
    branch_rules: dict[str, tuple[frozenset[board.MergeMethod], ...]] = field(default_factory=dict)
    deleted_branches: list[str] = field(default_factory=list)
    head_board_config: str | None = ""
    file_reads: list[tuple[Path, str]] = field(default_factory=list)
    quality_config: str | None = None
    quality_config_at_other_refs: str | None = None
    quality_config_error: forge.ForgeError | None = None
    quality_config_reads: list[str] = field(default_factory=list)
    requests: int = field(default=0, init=False)
    _requests_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    def _run(self) -> None:
        """This fake's mirror of `GitHubForge._run` (issue #168): every board
        read that would cost a real round trip calls this once, so a test can
        assert `requests` against a hand-counted expectation the same way it
        would against the real adapter. Locked for the same reason: `board`
        fans these reads out across worker threads."""
        with self._requests_lock:
            self.requests += 1

    def capability(self, operation: forge.ForgeOperation) -> forge.Capability:
        return self.capability_overrides.get(operation, github.GITHUB_CAPABILITIES[operation])

    def create_issue(self, *, title: str, body: str, kind: body.ItemKind) -> int:
        """This fake's mirror of `GitHubForge.create_issue`: a fresh issue
        with no recorded parent, immediately visible to
        `list_open_board_issues` -- the orphan shape a failed `link_child`
        leaves behind (#260). Carries `kind` (#260 Sonnet finding), since a
        repeat `cut`'s orphan scan refuses to adopt anything but a `TASK`.
        `drop_created_issue_type` simulates GitHub silently dropping that
        type (#444): the issue exists untyped and the create raises."""
        number = self.next_created_child_number
        self.next_created_child_number += 1
        self.created_issues.append((title, body, kind))
        stored_kind = None if self.drop_created_issue_type else kind
        self.board_issues = (
            *self.board_issues,
            board_issue(number, title, body, kind=stored_kind),
        )
        if self.drop_created_issue_type:
            raise forge.ForgeIssueTypeNotSetError(
                created=number, type_name=github.ITEM_KIND_TYPE_NAMES[kind]
            )
        return number

    def link_child(self, parent: int, child: int) -> None:
        """This fake's mirror of `GitHubForge.link_child`: records `child` as
        `parent`'s open sub-issue, so a later `list_children`/`parent_issue`
        call sees it exactly as real GitHub would after the sub-issue POST
        succeeds. `fail_create_child_relation` simulates that POST itself
        failing, leaving `child` the orphan a repeat `cut` must adopt (#260).
        """
        self.linked_children.append((parent, child))
        if self.fail_create_child_relation:
            raise ClaimError("relation POST failed (simulated)")
        self.children[parent] = (
            *self.children.get(parent, ()),
            board.ChildItem(child, board.ChildState.OPEN),
        )
        self.parents[child] = board.ParentIssue(
            board.IssueReference(self.repository.path, parent), ""
        )

    def create_child(self, *, parent: int, title: str, body: str, kind: body.ItemKind) -> int:
        """This fake's mirror of `GitHubForge.create_child`: composed from
        `create_issue` and `link_child` exactly as the real adapter is
        (#260), so a relation failure leaves the same real orphan behind
        for a repeat `cut` to find."""
        self.created_children.append((parent, title, body, kind))
        number = self.create_issue(title=title, body=body, kind=kind)
        try:
            self.link_child(parent, number)
        except ClaimError as error:
            raise forge.ForgePartialChildCreationError(
                child=number,
                parent=parent,
                step=f"record #{number} as a sub-issue of #{parent}",
                cause=error,
            ) from error
        return number

    def update_item_body(self, number: int, body: str) -> None:
        """`update_item_body_error` is the forge's answer instead of a write,
        unless `update_item_body_lands_before_error` says the write happened
        and only its answer failed. A pull request's body is its landing's."""
        if self.fail_update_item_body:
            raise ClaimError("update item body failed (simulated)")
        if self.update_item_body_error is None or self.update_item_body_lands_before_error:
            self.body_writes.append((number, body))
            self.item_bodies[number] = body
            if number in self.landings:
                self.landings[number] = replace(self.landings[number], body=body)
        if self.update_item_body_error is not None:
            raise self.update_item_body_error

    def set_item_kind(self, number: int, kind: body.ItemKind) -> None:
        """`fail_set_item_kind` simulates GitHub dropping the new type
        (ITEM-46): the item keeps its old type and the retype raises."""
        if self.fail_set_item_kind:
            raise forge.ForgeError("retype dropped (simulated)")
        self.retyped_items.append((number, kind))

    def close_landed_item(self, number: int, *, pull_request: int) -> None:
        """This fake's mirror of `GitHubForge.close_landed_item` (issue
        #359 Card 1): records the comment and the close as state, the same
        two facts a test asserts against the real adapter's own two `_run`
        calls."""
        if self.close_error is not None:
            raise self.close_error
        self.landing_comments[number] = github.landing_comment(pull_request)
        self.closed_issues.add(number)

    def landing_readiness(self, number: int) -> forge.LandingReadiness:
        """This fake's mirror of `GitHubForge.landing_readiness` (issue
        #405): a test seeds `readiness_by_number` directly, one
        `forge.LandingReadiness` per scenario, rather than reconstructing it
        from other fields."""
        self._run()
        readiness = self.readiness_by_number.get(number)
        if readiness is None:
            raise ClaimError(f"GitHub has no readiness for pull request #{number}")
        return readiness

    def allowed_merge_methods(self) -> frozenset[board.MergeMethod] | None:
        """This fake's mirror of `GitHubForge.allowed_merge_methods` (issue
        #578): `allowed_methods`, `None` -- settings withheld -- by default."""
        self._run()
        return self.allowed_methods

    def branch_merge_rules(self, branch: str) -> tuple[frozenset[board.MergeMethod], ...]:
        """This fake's mirror of `GitHubForge.branch_merge_rules` (issue
        #615): `branch_rules` for `branch`, no rule by default."""
        self._run()
        return self.branch_rules.get(branch, ())

    def merge_landing(
        self,
        number: int,
        *,
        head_sha: str,
        method: board.MergeMethod,
        title: str,
        body: str,
    ) -> str:
        """This fake's mirror of `GitHubForge.merge_landing` (issue #405):
        records every call for an adapter-shaped assertion, and, when
        `merge_remote` names a real bare repository (`land`'s own end-to-end
        tests), merges there into its default branch with `method`, as the
        forge does on its own side, so the landing checkout stands behind
        until its own real fast-forward. `closes_on_merge` closes every issue
        the pull request body names with `Closes #<n>`, as GitHub itself does
        on the merge, before the release ever reads it (issue #578). The
        merged pull request keeps `head_sha` as its recorded head, as
        GitHub does (issue #590)."""
        self._run()
        self.merge_requests.append((head_sha, method))
        if self.merge_error is not None:
            raise self.merge_error
        self.merge_calls.append((number, head_sha, method, title, body))
        sha = self.merge_sha
        landing = self.landings[number]
        if self.closes_on_merge:
            self.closed_issues.update(
                int(closed) for closed in re.findall(r"Closes #(\d+)", landing.body)
            )
        if self.merge_remote is not None:
            sha = merge_on_the_forge(
                self.merge_remote,
                self.default_branch_name,
                landing.source_branch,
                f"{title}\n\n{body}",
                method,
            )
        self.landings[number] = replace(landing, merged=True, merge_commit=sha, head_sha=head_sha)
        return sha

    def delete_branch(self, branch: str) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self._run()
        self.deleted_branches.append(branch)

    def file_at_commit(self, path: Path, sha: str) -> str | None:
        """This fake's mirror of `GitHubForge.file_at_commit` (issue #505):
        every pull request head carries `head_board_config` as its board
        configuration -- by default an empty one, which pins exactly what an
        unconfigured checkout does -- and `None` removes it. Each read's
        path and commit land in `file_reads`."""
        self._run()
        if path == cmd_land._LAND_QUALITY_CONFIG_PATH:
            self.quality_config_reads.append(sha)
            if self.quality_config_error is not None:
                raise self.quality_config_error
            if sha == self.default_branch_name:
                return self.quality_config
            return self.quality_config_at_other_refs
        self.file_reads.append((path, sha))
        return self.head_board_config

    def list_open_board_issues(self) -> tuple[board.Issue, ...]:
        self._run()
        return self.board_issues

    def landing(self, number: int) -> forge.Landing:
        self._run()
        detail = self.landings.get(number)
        if detail is None:
            raise ClaimError(f"GitHub has no pull request #{number}")
        return detail

    def pull_request_changes(self, number: int) -> forge.PullRequestChanges:
        self._run()
        self.changes_reads.append(number)
        changes = self.changes_by_number[number]
        if isinstance(changes, forge.ForgeError):
            raise changes
        return changes

    def _item_reference_value(self, number: int) -> forge.ItemReference:
        served = self.issue_references.get(number)
        if served is not None:
            return served
        state = forge.ItemState.CLOSED if number in self.closed_issues else forge.ItemState.OPEN
        # `landings` is this fake's set of pull requests, so the one flag that
        # distributes `check` is derived from it rather than set twice, and
        # a pull request's body is its landing's.
        landing = self.landings.get(number)
        return forge.ItemReference(
            state, "", "" if landing is None else landing.body, landing is not None
        )

    def item_reference(self, number: int) -> forge.ItemReference:
        """`scripted_item_reads` answers the next reads in order -- a body, a
        failure, or `None` for the served reference -- before the served one."""
        self._run()
        self.issue_reference_lookups.append(number)
        served = self._item_reference_value(number)
        scripted = self.scripted_item_reads.pop(0) if self.scripted_item_reads else None
        if isinstance(scripted, forge.ForgeError):
            raise scripted
        return served if scripted is None else replace(served, body=scripted)

    def item_references(self, numbers: Iterable[int]) -> Mapping[int, forge.ItemReference]:
        """This fake's mirror of `GitHubForge.item_references` (issue #440):
        one `_run()` for the whole batch -- never one per number -- so a
        test can assert `requests` against the same one-round-trip count the
        real adapter now pays for any closed-item history that fits one
        GraphQL block."""
        ordered = tuple(dict.fromkeys(numbers))
        if not ordered:
            return {}
        self._run()
        self.issue_reference_lookups.extend(ordered)
        return {number: self._item_reference_value(number) for number in ordered}

    def default_branch(self) -> str:
        self._run()
        if self.default_branch_error is not None:
            raise self.default_branch_error
        return self.default_branch_name

    def parent_issue(self, number: int) -> board.ParentIssue | None:
        self._run()
        return self.parents.get(number)

    def parent_number(self, number: int) -> int | None:
        self._run()
        parent = self.parents.get(number)
        return parent.reference.number if parent else None

    def list_children(self, number: int) -> tuple[board.ChildItem, ...]:
        self._run()
        return self.children.get(number, ())

    def list_board_dependencies(self, number: int) -> tuple[board.IssueDependency, ...]:
        self._run()
        return self.board_dependencies.get(number, ())

    def list_open_board_pull_requests(self) -> tuple[board.PullRequest, ...]:
        self._run()
        return self.board_open_pull_requests

    def list_recent_merged_board_pull_requests(
        self, since: datetime
    ) -> tuple[board.PullRequest, ...]:
        self._run()
        return self.board_merged_pull_requests

    def list_recently_closed_issues(self, since: datetime) -> tuple[forge.ClosedIssue, ...]:
        self._run()
        self.closed_issue_cutoffs.append(since)
        return self.recently_closed_issues


class ReaderOnlyForge(FakeForge):
    """A `FakeForge` whose write operations fail the test instead of quietly
    succeeding -- the enforcement that a read-only command never writes,
    independent of the `ForgeReader`/`ForgeWriter` annotations (documentation
    only; nothing type-checks in CI)."""

    def create_issue(self, *, title: str, body: str, kind: body.ItemKind) -> int:
        pytest.fail("a read-only command must never create an issue")

    def link_child(self, parent: int, child: int) -> None:
        pytest.fail("a read-only command must never link a child")

    def create_child(self, *, parent: int, title: str, body: str, kind: body.ItemKind) -> int:
        pytest.fail("a read-only command must never create a child")

    def update_item_body(self, number: int, body: str) -> None:
        pytest.fail("a read-only command must never update an item body")

    def set_item_kind(self, number: int, kind: body.ItemKind) -> None:
        pytest.fail("a read-only command must never retype an item")

    def close_landed_item(self, number: int, *, pull_request: int) -> None:
        pytest.fail("a read-only command must never close a landed item")

    def merge_landing(
        self, number: int, *, head_sha: str, method: board.MergeMethod, title: str, body: str
    ) -> str:
        pytest.fail("a read-only command must never merge a pull request")

    def delete_branch(self, branch: str) -> None:
        pytest.fail("a read-only command must never delete a branch")


def assert_github_world(github_clone: Path, bare_remote: Path) -> None:
    """Verify the arranged GitHub checkout before running its command."""
    assert real_git(github_clone, "ls-files", ".aco/board.toml").stdout == ".aco/board.toml\n"
    main = real_git(github_clone, "rev-parse", "main").stdout.strip()
    assert real_git(github_clone, "rev-parse", "origin/HEAD").stdout.strip() == main
    assert (
        real_git(github_clone, "config", "--get", "remote.origin.url").stdout
        == "git@github.com:example/agent-coordination.git\n"
    )
    assert (
        real_git(github_clone, "ls-remote", "origin", "refs/heads/main").stdout
        == f"{main}\trefs/heads/main\n"
    )
    assert state_ref_tip(bare_remote) is None


LANDING_DEFAULT_BRANCH = "main"


@dataclass
class LandingWorld:
    clone: Path
    remote: Path
    forge: FakeForge
    unchanged: dict[str, object]
    default_branch: str = field(default=LANDING_DEFAULT_BRANCH, kw_only=True)


@dataclass
class LaneLandingWorld(LandingWorld):
    head: str
    entry_lineage: list[tuple[object, object]]


def lane_landing_world(
    clone: Path,
    remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity: protocol.ClaimIdentity,
    branch: str,
    body: str,
    methods: frozenset[board.MergeMethod] | None,
    default_branch: str = LANDING_DEFAULT_BRANCH,
    holder: str = "Ada",
    role: str = "builder",
    distinct_detail: bool = False,
    error: forge.ForgeError | None = None,
    rules: tuple[frozenset[board.MergeMethod], ...] = (),
    head_config: str = "",
    arrange: Callable[[FakeForge, str], None] | None = None,
) -> LaneLandingWorld:
    """Publish a claimed lane and snapshot it after the caller's final arrangement."""
    head = push_lane_branch(clone, branch)
    intent = claim_intent(
        identity=identity,
        branch=branch,
        agent=holder,
        role=role,
        claim_id="landing",
        base=protocol.ObjectId(real_git(clone, "rev-parse", default_branch).stdout.strip()),
    )
    seeded = publish_claims_from_a_second_clone(clone, remote, (intent,))
    observed = tuple(
        (c.identity, c.branch, c.agent, c.role, str(c.claim_id)) for c in seeded.claims.values()
    )
    expected = ((identity, branch, holder, role, "landing"),)
    assert observed == expected
    detail = replace(
        landing_pull_request(body=body, head_ref_name=branch, base_ref_name=default_branch),
        head_sha=real_git(clone, "rev-parse", default_branch).stdout.strip()
        if distinct_detail
        else head,
    )
    client = serve_forge(
        monkeypatch,
        FakeForge(
            landings={12: detail, 13: replace(detail, number=13)},
            readiness_by_number={12: landing_readiness(head_sha=head)},
            merge_remote=remote,
            merge_error=error,
            allowed_methods=methods,
            branch_rules={default_branch: rules},
            default_branch_name=default_branch,
            head_board_config=head_config,
        ),
    )
    if arrange is not None:
        arrange(client, head)
    shared = landing_world(
        clone, remote, client, remote_tip=seeded.tip, default_branch=default_branch
    )
    entry: list[tuple[object, object]] = []
    merge = client.merge_landing

    def observe_entry(
        number: int, *, head_sha: str, method: board.MergeMethod, title: str, body: str
    ) -> str:
        entry.append(lineage_observation(clone))
        return merge(number, head_sha=head_sha, method=method, title=title, body=body)

    monkeypatch.setattr(client, "merge_landing", observe_entry)
    return LaneLandingWorld(
        clone, remote, client, shared.unchanged, head, entry, default_branch=shared.default_branch
    )


def landing_world(
    clone: Path,
    remote: Path,
    forge: FakeForge,
    *,
    remote_tip: str | None = None,
    default_branch: str = LANDING_DEFAULT_BRANCH,
) -> LandingWorld:
    """Snapshot the fully arranged checkout before invoking land."""
    worktrees, branches = worktrees_and_branches(clone)
    world = LandingWorld(clone, remote, forge, {}, default_branch=default_branch)
    unchanged = {
        "merge": [],
        "delete": [],
        "close": set(forge.closed_issues),
        "body": [],
        "remote": remote_tip,
        "local": None,
        "worktrees": worktrees,
        "branches": branches,
        "trunk": real_git(clone, "rev-parse", world.default_branch).stdout,
        "stamp": None,
        "anchor": None,
    }
    world.unchanged = unchanged
    observed = landing_effects(world)
    assert observed == unchanged
    return world


def landing_effects(world: LandingWorld) -> dict[str, object]:
    worktrees, branches = worktrees_and_branches(world.clone)
    stamp, anchor = lineage_observation(world.clone)
    return {
        "merge": list(world.forge.merge_calls),
        "delete": list(world.forge.deleted_branches),
        "close": set(world.forge.closed_issues),
        "body": list(world.forge.body_writes),
        "remote": state_ref_tip(world.remote),
        "local": state_ref_tip(world.clone),
        "worktrees": worktrees,
        "branches": branches,
        "trunk": real_git(world.clone, "rev-parse", world.default_branch).stdout,
        "stamp": stamp,
        "anchor": anchor,
    }


def landed_observations(
    world: LaneLandingWorld,
    result: CliRun,
    *,
    branch: str,
    method: board.MergeMethod,
    title: str,
    parents: int,
    closed: frozenset[int],
    release: str,
    remaining_branches: frozenset[str],
) -> tuple[dict[str, object], dict[str, object]]:
    """Observe a completed landing against caller-owned outcomes without invoking land."""
    effects = landing_effects(world)
    calls = world.forge.merge_calls
    trunk = real_git(world.clone, "rev-parse", world.default_branch).stdout.strip()
    remote_claims = store.peek_state(worktree=world.clone, remote=str(world.remote)).claims
    topology = tuple(
        line
        for line in real_git(world.clone, "worktree", "list", "--porcelain").stdout.splitlines()
        if line.startswith(("worktree ", "branch "))
    )
    branches = local_branches(world.clone)
    entry = world.entry_lineage[0] if world.entry_lineage else ("missing", "missing")
    merge = calls[0] if calls else (None, None, None, None, "")
    comparisons: dict[str, tuple[object, object]] = {
        "exit": (result.status, 0),
        "stderr": (result.stderr, ""),
        "stdout.release": (release in result.stdout, True),
        "merge.count": (len(calls), 1),
        "merge.number": (merge[0], 12),
        "merge.head": (merge[1], world.head),
        "merge.method": (merge[2], method),
        "merge.title": (merge[3], title),
        "delete": (effects["delete"], [branch]),
        "close": (effects["close"], set(closed)),
        "body": (effects["body"], []),
        "remote.moved": (effects["remote"] != world.unchanged["remote"], True),
        "claims": (remote_claims, {}),
        "local": (effects["local"], None),
        "worktrees": (
            topology,
            (f"worktree {world.clone}", f"branch refs/heads/{world.default_branch}"),
        ),
        "branches": (branches, remaining_branches),
        "trunk.changed": (trunk + "\n" != world.unchanged["trunk"], True),
        "trunk.same": (trunk == world.forge.landings[12].merge_commit, True),
        "trunk.parents": (
            len(real_git(world.clone, "rev-list", "--parents", "-n", "1", trunk).stdout.split())
            - 1,
            parents,
        ),
        "stamp": (effects["stamp"] is not None, True),
        "anchor": (effects["anchor"] is not None, True),
        "entry.stamp": (entry[0], None),
        "entry.anchor": (entry[1], None),
    }
    return (
        {key: actual for key, (actual, _) in comparisons.items()},
        {key: wanted for key, (_, wanted) in comparisons.items()},
    )


@dataclass(frozen=True)
class ParserExit:
    exited: bool
    usage_prefix: str


class RefusalLength(Enum):
    UNCHECKED = "unchecked"
    WITHIN_LIMIT = "within-limit"
    EXACTLY_LIMIT = "exactly-limit"


def refusal_observations(
    world: LandingWorld,
    result: CliRun,
    sentence: str,
    *,
    length: RefusalLength = RefusalLength.UNCHECKED,
    parser_exit: ParserExit | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    observed = {"exit": result.status, "out": result.stdout, **landing_effects(world)}
    expected = {"exit": 2, "out": "", **world.unchanged}
    if parser_exit is not None:
        observed.update(
            {
                "exception": parser_exit.exited,
                "usage": result.stderr.startswith(parser_exit.usage_prefix),
                "last": result.stderr.splitlines()[-1] if result.stderr else "",
            }
        )
        expected.update({"exception": True, "usage": True, "last": sentence})
    else:
        observed["err"] = result.stderr
        expected["err"] = "ERROR: " + sentence + "\n"
    if length is not RefusalLength.UNCHECKED:
        actual_length = len(result.stderr.rstrip("\n"))
        exact = length is RefusalLength.EXACTLY_LIMIT
        observed["length"] = actual_length if exact else actual_length <= 200
        expected["length"] = 200 if exact else True
    return observed, expected
