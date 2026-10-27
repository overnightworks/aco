from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import runpy
import shlex
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from types import MappingProxyType
from typing import TextIO, cast

import pytest
from board_fixtures import (
    BASE,
    BIDI_AND_ZERO_WIDTH_CONTROLS,
    FROZEN_TRIGGER,
    FROZEN_UNTIL,
    MINIMAL_BLOCK_TOML,
    REPOSITORY,
    block_body,
    block_dependency,
    blocked_issue,
    board_issue,
    complete_contract,
    container_issue,
    container_with_children,
    idea_body,
    projected_board,
    proposed_expectation,
    request,
    ruled_expectation,
    slice_entries,
    standing_active_claim,
    store_claim_from_request,
    unfilled_block_body,
    write_repository_config,
)
from cli_fixtures import (
    GIT_FAILURE_INJECTIONS,
    ITEM_NEW_BODY,
    LIVE_TRUNK_REF_AFTER,
    RECORDED_ORIGIN_HEAD_READ,
    FixedDateTime,
    arguments_bash_hands_aco,
    arrange_scope_width,
    assert_missing_identity_message,
    bare_remote_repository_with_one_commit,
    body_file_on_stdin,
    closed_stdin,
    count_context_reads,
    dangle_recorded_head,
    devnull_on_stdin,
    empty_harness_socket_on_stdin,
    fail_git_launch,
    fetched_once_then_read,
    forbid_forge_resolution,
    forbid_git_fill,
    forbid_github_construction,
    freeze_cli_now,
    fresh_observation,
    git_checkout,
    init_bare_repository,
    landed_from_another_clone,
    piped_body_on_stdin,
    piping,
    push_repository_trunk,
    read_end_of_a_pipe_carrying,
    real_git,
    real_repository_with_bare_remote,
    recorded_head_read,
    redirect_toplevel,
    run_cli,
    run_context_over,
    set_agent_identity_env,
    stub_board_config_tracked,
    stub_every_remote_configured,
    stub_one_git_call,
    terminal_on_stdin,
    trunk_git_calls,
    worktrees_and_branches,
)
from github_fixtures import (
    LANDING_BRANCH,
    MERGE_COMMIT_SHA,
    WORK_ITEM_ISSUE,
    FakeForge,
    ReaderOnlyForge,
    landing_pull_request,
    landing_readiness,
)
from store_fixtures import (
    RaceOnceTransport,
    blob,
    claim_intent,
    lineage_observation,
    push_raw_state_tree,
    raw_tree,
    unrelated_racer_commit,
)

from aco import (
    __version__,
    board_read,
    body,
    checkout,
    cmd_check,
    cmd_claim,
    cmd_cut,
    cmd_land,
    cmd_next,
    cmd_start,
    cmd_status,
    forge,
    github,
    items,
    metrics,
    process,
    protocol,
    report,
    session,
    state_board,
    store,
    workboard,
)
from aco import cli as issue_claim
from aco.cmd_status import _status
from aco.protocol import (
    ClaimError,
    ClaimRequest,
    ClaimUnavailableError,
)
from aco.session import RunContext
from aco.workboard import (
    NEEDS_OPERATOR_LABEL,
    BlockerState,
    ChildItem,
    ChildState,
    Issue,
    IssueDependency,
    NoItemClassification,
    NoItemKind,
    TrunkWorkItemClassification,
)

GitHubForge = github.GitHubForge

# Captured before the autouse `_stub_trunk` fixture (below) ever
# monkeypatches `checkout.trunk_landings` to `()`: the atomic-landing tests
# need the real first-parent walk against a real repository,
# the same way `test_checkout.py`'s own `_LIVE_TRUNK_LANDINGS` does. A test
# on a real repository (`redirect_toplevel`) resolves and fetches its trunk
# for real as well.
_LIVE_TRUNK_LANDINGS = checkout.trunk_landings
_LIVE_UNCONFIGURED_REMOTE_REFUSAL = checkout.unconfigured_remote_refusal
_LIVE_PATH_IS_TRACKED = checkout.path_is_tracked
_LIVE_FILE_AT_REVISION = checkout.file_at_revision

LANDED = protocol.MergedRelease(12)

# Exactly `protocol.WIDE_SCOPE_SHARE_FLOOR` versioned files: three named scope
# paths (LICENSE, README.md, src) cover four of them (src holds two), the
# minimal fixture that still trips the share condition.
TWELVE_VERSIONED_FILES = (
    "LICENSE",
    "README.md",
    "pyproject.toml",
    "src/aco/__init__.py",
    "src/a.py",
    "docs/b.md",
    "docs/c.md",
    "docs/d.md",
    "docs/e.md",
    "docs/f.md",
    "docs/g.md",
    "docs/h.md",
)


def _live_store_claim() -> protocol.ActiveClaim:
    """The single live claim on the in-memory store fake."""
    state = store.fetch_state(worktree=Path("."), remote="origin")
    assert len(state.claims) == 1
    return next(iter(state.claims.values()))


@dataclass
class _MinimalForgeReader:
    """A `forge.ForgeReader` shape narrower than `FakeForge` for tests that
    exercise only `board_read.build_board`'s own priority/child-fetch wiring: no request
    counter, no write surface, no repository target resolution -- just the
    open issues, children, and merged-PR floor a `board_read.build_board` build reads. One
    shared shape rather than three near-identical inline classes, each
    repeating the same `forge.ForgeReader` stub methods."""

    open_issues: tuple[Issue, ...] = ()
    children_by_number: dict[int, tuple[ChildItem, ...]] = field(default_factory=dict)
    repository: forge.RepositoryId = field(default_factory=lambda: github.repository_id(REPOSITORY))
    requests: int = 0
    observed_children_lookups: list[int] = field(default_factory=list)
    observed_merged_pull_request_floors: list[datetime] = field(default_factory=list)
    lists_pull_requests: bool = True

    def item_reference(self, number: int) -> forge.ItemReference:
        return forge.ItemReference(state=forge.ItemState.MISSING)

    def item_references(self, numbers: Iterable[int]) -> Mapping[int, forge.ItemReference]:
        return dict.fromkeys(numbers, forge.ItemReference(state=forge.ItemState.MISSING))

    def landing(self, number: int) -> forge.Landing:
        raise NotImplementedError

    def pull_request_changes(self, number: int) -> forge.PullRequestChanges:
        raise NotImplementedError

    def parent_issue(self, number: int) -> workboard.ParentIssue | None:
        return None

    def parent_number(self, number: int) -> int | None:
        return None

    def default_branch(self) -> str:
        return "main"

    def list_board_dependencies(self, number: int) -> tuple[IssueDependency, ...]:
        return ()

    def list_open_board_issues(self) -> tuple[Issue, ...]:
        return self.open_issues

    def list_open_board_pull_requests(self) -> tuple[workboard.PullRequest, ...]:
        return ()

    def list_recent_merged_board_pull_requests(
        self, since: datetime
    ) -> tuple[workboard.PullRequest, ...]:
        self.observed_merged_pull_request_floors.append(since)
        return ()

    def list_recently_closed_issues(self, since: datetime) -> tuple[forge.ClosedIssue, ...]:
        return ()

    def list_children(self, number: int) -> tuple[ChildItem, ...]:
        self.observed_children_lookups.append(number)
        return self.children_by_number.get(number, ())


_LIVE_FETCH_ISSUE_REFERENCE = board_read.fetch_issue_reference


def test_read_only_commands_never_write_through_a_reader_only_forge(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: rulings Never 1 -- reads without forge writes."""
    client = ReaderOnlyForge()
    client.board_issues = (board_issue(72, "Work", complete_contract("Ship it.")),)
    client.landings[12] = landing_pull_request(body="Work-Item: #72\n\nCloses #72")
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "git_output", lambda _arguments, **_kwargs: "")
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())

    for argv in (
        ["status"],
        ["status", "--path", "src"],
        ["board"],
        ["next"],
        ["rulings"],
        ["check", "12"],
    ):
        issue_claim.main(["--repo", REPOSITORY, *argv])
        capsys.readouterr()


def _board_fixture_environment(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    issues_json = [
        {
            "number": 10,
            "title": "Security boundary",
            "labels": ["security"],
            "body": complete_contract("Land #10.", now="Inspect.", done_when="Merged."),
            "createdAt": "2026-08-10T00:00:00Z",
            "updatedAt": "2026-08-20T00:00:00Z",
            "blockedByCount": 0,
        },
        {
            "number": 11,
            "title": "Product dependency",
            "labels": ["product"],
            "body": complete_contract(
                "Review implementation.", now="Implement.", done_when="Released."
            ),
            "createdAt": "2026-08-12T00:00:00Z",
            "updatedAt": "2026-08-20T00:00:00Z",
            "blockedByCount": 1,
        },
        {
            "number": 12,
            "title": "Old notes",
            "labels": ["ux"],
            "body": "Unstructured notes.",
            "createdAt": "2026-08-01T00:00:00Z",
            "updatedAt": "2026-08-10T00:00:00Z",
            "blockedByCount": 0,
        },
        {
            "number": 13,
            "title": "Cleanup landed",
            "labels": ["cleanup"],
            "body": complete_contract("Close issue.", now="Verify.", done_when="Released."),
            "createdAt": "2026-08-02T00:00:00Z",
            "updatedAt": "2026-08-19T00:00:00Z",
            "blockedByCount": 0,
        },
        {
            "number": 14,
            "title": "Older cleanup",
            "labels": ["cleanup"],
            "body": "Unstructured notes.",
            "createdAt": "2026-08-02T00:00:00Z",
            "updatedAt": "2026-08-20T00:00:00Z",
            "blockedByCount": 0,
        },
    ]
    open_prs_json = [
        {"number": 90, "title": "Fixes #10", "body": "", "headRefName": "other", "mergedAt": None},
        {
            "number": 91,
            "title": "In progress",
            "body": "",
            "headRefName": "codex/issue-11-claims",
            "mergedAt": None,
        },
        {
            "number": 93,
            "title": "Planning note",
            "body": None,
            "headRefName": "notes",
            "mergedAt": None,
        },
    ]
    merged_prs_json = [
        {
            "number": 92,
            "title": "Fixes #13",
            "body": "",
            "headRefName": "codex/issue-13-cleanup",
            "mergedAt": "2026-08-20T12:00:00Z",
        },
        {
            "number": 94,
            "title": "Fixes #14",
            "body": "",
            "headRefName": "codex/issue-14-cleanup",
            "mergedAt": "2026-08-06T23:59:59Z",
        },
    ]
    active = request("board-claim", issue=11, branch="codex/issue-11-claims")
    repository = github.repository_id(REPOSITORY)
    observed: list[list[str]] = []

    def run(arguments: list[str], *, input_data: bytes | None = None) -> str:
        assert input_data is None
        observed.append(arguments)
        endpoint = next((argument for argument in arguments if argument.startswith("repos/")), "")
        if "/issues?" in endpoint:
            rows = issues_json
        elif endpoint.startswith(f"repos/{repository}/issues/11/dependencies/blocked_by"):
            rows = [
                {
                    "number": 10,
                    "state": "open",
                    "closedAt": None,
                    "repository": str(repository),
                    "isPullRequest": False,
                }
            ]
        elif arguments[:2] == ["pr", "list"] and "open" in arguments:
            rows = open_prs_json
        elif arguments[:2] == ["pr", "list"] and "merged" in arguments:
            day = arguments[arguments.index("--search") + 1].removeprefix("merged:")
            rows = [row for row in merged_prs_json if row["mergedAt"].startswith(day)]
        else:
            pytest.fail(f"unexpected board request: {arguments}")
        return "\n".join(json.dumps(row) for row in rows)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 21, tzinfo=UTC)

    client = GitHubForge(repository, run=run)
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(github, "datetime", FixedDateTime)
    _patch_store_write(monkeypatch, store_claim_from_request(active))
    return observed


def test_board_json_shards_the_merged_pull_request_query_by_day_without_writes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    observed = _board_fixture_environment(monkeypatch)

    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 0
    capsys.readouterr()
    assert all("--method" not in arguments for arguments in observed)
    assert all("--jq" in arguments for arguments in observed)
    merged_days = {
        arguments[arguments.index("--search") + 1].removeprefix("merged:")
        for arguments in observed
        if arguments[:2] == ["pr", "list"] and "merged" in arguments
    }
    # The floor is the oldest open issue's creation (#12, 2026-08-01), not a
    # fixed 14 days back — nothing merged before #12 existed could touch any
    # currently open issue. Each day between that floor and "now" is its own
    # query shard (`github._query_days`), fetched in parallel.
    assert merged_days == {
        day.isoformat() for day in github._query_days(date(2026, 8, 1), date(2026, 8, 21))
    }


def test_board_projects_fixture_json_without_github_writes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _board_fixture_environment(monkeypatch)

    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {
        "ok",
        "reason",
        "items",
        "ready_now",
        "stale",
        "recovery",
        "landings",
        "uncut",
        "requests",
        "measurements",
    }
    assert (payload["ok"], payload["reason"]) == (True, "projected")
    first = payload["items"][0]
    ten = next(item for item in payload["items"] if item["number"] == 10)
    eleven = next(item for item in payload["items"] if item["number"] == 11)
    thirteen = next(item for item in payload["items"] if item["number"] == 13)
    fourteen = next(item for item in payload["items"] if item["number"] == 14)
    assert first["number"] == 10
    assert ten["stage"] == "in-flight"
    assert ten["unblocks_count"] == 1
    assert ten["contract"]["next"] == "Land #10."
    assert ten["contract_complete"] is True
    assert ten["actionable"] is True
    assert ten["actionable_reason"] is None
    assert eleven["active_claim"] == "Codex Sol (builder)"
    assert eleven["actionable_reason"] == "claimed"
    assert thirteen["stage"] == "code-landed"
    # #94 "Fixes #14" merged 2026-08-06, five days before the old fixed
    # 14-day floor (2026-08-07) would have admitted it — the oldest-open-
    # issue floor (2026-08-01) correctly still counts it.
    assert fourteen["stage"] == "code-landed"
    assert fourteen["actionable_reason"] == "body malformed: aco: no aco block"
    assert [item["number"] for item in payload["ready_now"]] == [10, 13]
    assert [item["number"] for item in payload["stale"]] == [12]
    assert next(item for item in payload["items"] if item["number"] == 12)["stage"] == "text-only"
    assert 11 not in [item["number"] for item in payload["ready_now"]]


def test_board_json_pins_the_raw_envelope_text_for_a_single_item(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The raw bytes `board` prints on success (OUT-nn's own key order,
    `ok`/`reason` first, and its trailing newline), not just the parsed dict
    `test_board_projects_fixture_json_without_github_writes` already covers."""
    _single_item_board_environment(monkeypatch, tmp_path)

    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 0

    assert capsys.readouterr().out == (
        '{"ok": true, "reason": "projected", "items": [{"number": 10, "title": "Plain item", '
        '"labels": [], "kind": null, "priority_category": 6, "priority_bucket": "unlabelled", '
        '"priority_order": 0, "container": null, "container_parent": null, "scope": null, '
        '"contract": {"now": "Work is ready.", "next": "Ship #10.", '
        '"done_when": "The work is merged.", "defects": []}, "next_step": "Ship #10.", '
        '"contract_complete": true, "idea": false, "expectation_state": "-", '
        '"expectation_progress": {"open": 0, "total": 0}, "ruling_landings": null, '
        '"ruling_old": null, "frozen_trigger": null, "freed_on": null, "freed_days": null, '
        '"stage": "text-only", "age_days": 1, "idle_days": 1, "active_claim": null, '
        '"claim_age": null, "claim_old": false, "unblocks_count": 0, "score": -10, '
        '"actionable": true, "actionable_reason": null, "size": null, "has_slices": false, '
        '"estimate": null, "open_blockers": [], "foreign_blockers": []}], '
        '"ready_now": [{"number": 10, "title": "Plain item", "labels": [], "kind": null, '
        '"priority_category": 6, "priority_bucket": "unlabelled", "priority_order": 0, '
        '"container": null, "container_parent": null, "scope": null, '
        '"contract": {"now": "Work is ready.", "next": "Ship #10.", '
        '"done_when": "The work is merged.", "defects": []}, "next_step": "Ship #10.", '
        '"contract_complete": true, "idea": false, "expectation_state": "-", '
        '"expectation_progress": {"open": 0, "total": 0}, "ruling_landings": null, '
        '"ruling_old": null, "frozen_trigger": null, "freed_on": null, "freed_days": null, '
        '"stage": "text-only", "age_days": 1, "idle_days": 1, "active_claim": null, '
        '"claim_age": null, "claim_old": false, "unblocks_count": 0, "score": -10, '
        '"actionable": true, "actionable_reason": null, "size": null, "has_slices": false, '
        '"estimate": null, "open_blockers": [], "foreign_blockers": []}], "stale": [], '
        '"recovery": [], "landings": [], "uncut": [], "requests": 3, '
        '"measurements": {"classes": [], "unfinished": 0, "unparsed": 0, "since": null, '
        '"as_of": "2026-08-21"}}\n'
    )


def _lane(item: str, day: int, hours: int) -> metrics.LaneEvent:
    return metrics.LaneEvent(
        item=item,
        size=None,
        claimed_at=datetime(2026, 8, day, tzinfo=UTC),
        released_at=datetime(2026, 8, day, hours, tzinfo=UTC),
        rescopes=0,
    )


def test_board_shows_measured_estimates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Pinned through the CLI rather than only through
    `workboard.build_board` directly: one `FakeForge` board build shows every
    estimate state -- a class with `n >= 3` measured lanes (two of them
    completed by items that have since closed, R2's own closed-item join),
    one with `n < 3` ("schwach"), and an item with no `size` at all ("keine
    Größe") -- through `--json`."""
    client = FakeForge()
    client.board_issues = (
        board_issue(30, "Measured M", complete_contract("Ship #30.", size="M")),
        board_issue(31, "Weak S", complete_contract("Ship #31.", size="S")),
        board_issue(32, "Unsized", complete_contract("Ship #32.")),
    )
    client.issue_references[33] = forge.ItemReference(
        forge.ItemState.CLOSED, body=complete_contract("Closed.", size="M")
    )
    client.issue_references[34] = forge.ItemReference(
        forge.ItemState.CLOSED, body=complete_contract("Closed.", size="M")
    )
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())
    lane_events = (
        _lane("30", 10, 4),
        _lane("33", 11, 5),
        _lane("34", 12, 6),
        _lane("31", 15, 2),
    )
    _patch_store_write(monkeypatch, lane_events=lane_events)
    measured_size, measured_median_hours, measured_sample_count = "M", 5, 3
    board_args = ["--repo", REPOSITORY, "board"]

    assert issue_claim.main([*board_args, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    thirty = next(item for item in payload["items"] if item["number"] == 30)
    thirty_one = next(item for item in payload["items"] if item["number"] == 31)
    thirty_two = next(item for item in payload["items"] if item["number"] == 32)
    assert thirty["estimate"] == {
        "item": "30",
        "size": measured_size,
        "median_hours": measured_median_hours,
        "n": measured_sample_count,
        "weak": False,
    }
    assert thirty_one["estimate"]["weak"] is True
    assert thirty_two["size"] is None
    assert thirty_two["estimate"] is None
    assert payload["measurements"]["classes"]
    # Both closed items come from one batched read -- open
    # issues, open PRs, merged PRs, and that one batch, never one per item.
    assert sorted(client.issue_reference_lookups) == [33, 34]
    assert payload["requests"] == client.requests == 4


def test_board_shows_the_empty_measurements_sentence_with_nothing_measured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The fourth estimate/Messungen state: with no
    lifecycle data read at all, `--json` shows the board's own
    empty-measurements sentinel (`since: null`), never a fabricated
    estimate."""
    _single_item_board_environment(monkeypatch, tmp_path)

    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["measurements"]["classes"] == []
    assert payload["measurements"]["since"] is None


def test_board_projects_with_no_state_ref_bootstrapped_at_all(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A repository that has never bootstrapped `refs/aco/state` still boards
    cleanly: `board_read.claim_ages`/`board_read._claim_lifecycle` both read a missing
    ref as empty rather than crashing, so `measurements` shows the
    empty-measurements sentence and no claim ages are read at all."""
    _single_item_board_environment(monkeypatch, tmp_path)
    _patch_store_write(monkeypatch, tip=None)

    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["measurements"]["classes"] == []


def test_board_reports_requests_equal_to_the_adapters_own_invocation_count(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`observed` is the fixture's own independent tally of every
    `gh` call the injected `run` actually received -- never read from the
    counter under test -- so a matching `requests` field is real evidence,
    not a tautology."""
    observed = _board_fixture_environment(monkeypatch)

    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["requests"] == len(observed)


def _single_item_board_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeForge:
    client = FakeForge()
    client.board_issues = (board_issue(10, "Plain item", complete_contract("Ship #10.")),)
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())
    _patch_store_write(monkeypatch)
    return client


def test_board_marks_an_item_landed_by_a_trailer_carrying_trunk_commit_without_a_pull_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A trunk commit's own
    `Work-Item:` trailer lands an item even when no merged pull request body
    names it -- `landed_references` unions the trunk-derived set
    (`entry.item` of each `BoardBuildInputs.trunk_landing_items` entry)
    with the PR-derived one, so the union still holds an item a merge/squash
    commit landed without a matching pull request body."""
    _single_item_board_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        checkout,
        "trunk_landings",
        lambda *_args, **_kwargs: (
            checkout.TrunkLanding(
                "trailersha",
                datetime(2026, 8, 29, tzinfo=UTC),
                TrunkWorkItemClassification((10,)),
                ("#10",),
            ),
        ),
    )

    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    ten = next(item for item in payload["items"] if item["number"] == 10)
    assert ten["stage"] == "code-landed"


def test_board_dedupes_a_landing_between_the_trunk_trailer_and_a_squash_pull_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Under `github`, a trunk-trailer landing (#10)
    and an older-style squash pull request with no trailer of its own (#11)
    both show as one row each in `board --json`'s `landings` array -- the
    trailer path winning for #10 even though pull request #89 also plainly
    closes it, proving the dedup rather than merely two different items
    landing."""
    client = _single_item_board_environment(monkeypatch, tmp_path)
    client.board_issues = (
        board_issue(10, "Trailer landed", complete_contract("Ship #10.")),
        board_issue(11, "Squash landed", complete_contract("Ship #11.")),
    )
    client.board_merged_pull_requests = (
        workboard.PullRequest(
            number=89,
            title="New-style trailer landing",
            body="Work-Item: #10\n\nCloses #10",
            head_ref_name="codex/issue-10-fix",
            merged_at="2026-08-29T00:00:00Z",
        ),
        workboard.PullRequest(
            number=90,
            title="Old-style squash",
            body="Closes #11",
            head_ref_name="old/squash-11",
            merged_at="2026-08-18T00:00:00Z",
        ),
    )
    trailer_landing = checkout.TrunkLanding(
        "a" * 40,
        datetime(2026, 8, 29, tzinfo=UTC),
        TrunkWorkItemClassification((10,)),
        ("#10",),
    )
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: (trailer_landing,))
    board_command = ["--repo", REPOSITORY, "board"]

    assert issue_claim.main([*board_command, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    landings = {row["item"]: row for row in payload["landings"]}
    assert landings.keys() == {10, 11}
    assert landings[10]["sha"] == "a" * 40
    assert landings[10]["pull_request"] is None
    assert landings[11]["sha"] is None
    assert landings[11]["pull_request"] == 90


def test_board_naming_no_output_mode_refuses_before_any_read(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """BOARD-44: the retired text table left `board` with no
    default mode, so a bare `aco board` must name `--json` instead of
    reading a forge, a pin, or a repository just to guess."""
    status = issue_claim.main(["board"])

    assert status == 2
    assert capsys.readouterr().err == "ERROR: aco board requires --json\n"


def test_board_serve_flag_is_an_unknown_argument(capsys: pytest.CaptureFixture[str]) -> None:
    """The retired `aco board --serve` is no longer declared, so argparse
    refuses it like any unknown flag (BOARD-44's neighbour)."""
    with pytest.raises(SystemExit) as refused:
        issue_claim.main(["board", "--serve"])

    assert refused.value.code == 2
    assert "aco: error: unrecognized arguments: --serve" in capsys.readouterr().err


def test_board_skips_the_children_list_for_a_container_with_zero_children(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A container whose own summary already says 0/0 must never
    pay for `list_children` -- there is no open child either way -- while a
    container that does carry children still gets its detail list."""
    issues = (
        board_issue(10, "Plain item", complete_contract("Ship #10.")),
        replace(
            board_issue(20, "Empty container", complete_contract("Ship #20.")),
            kind=body.ItemKind.CONTAINER,
            children_closed=0,
            children_total=0,
        ),
        replace(
            board_issue(30, "Container with children", complete_contract("Ship #30.")),
            kind=body.ItemKind.CONTAINER,
            children_closed=1,
            children_total=2,
        ),
    )
    client = FakeForge()
    client.board_issues = issues
    client.children[30] = (ChildItem(31, ChildState.OPEN),)
    observed_children_calls: list[int] = []
    original_list_children = client.list_children

    def spy_list_children(number: int) -> tuple[ChildItem, ...]:
        observed_children_calls.append(number)
        return original_list_children(number)

    monkeypatch.setattr(client, "list_children", spy_list_children)
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())
    _patch_store_write(monkeypatch)

    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert observed_children_calls == [30]
    # Open issues, open PRs, merged PRs, and exactly one `list_children`
    # call (for #30, never #20) -- claims come from the store now,
    # never from a ledger-comments request. No issue here names a
    # blocker, so `list_board_blockers` never runs -- an empty numbers set
    # costs no request, on the fake exactly as on the real adapter.
    assert payload["requests"] == client.requests == 4


def test_board_skips_the_dependency_list_for_a_zero_blocker_item_in_block_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """An
    item whose own count already says 0 must never pay for its dependency
    list, only the one that actually carries a blocker."""
    write_repository_config(tmp_path, 'body_contract = "block"\n')
    unblocked = board_issue(10, "Unblocked", block_body(MINIMAL_BLOCK_TOML))
    blocked = replace(
        board_issue(11, "Blocked", block_body(MINIMAL_BLOCK_TOML)), blocked_by_count=1
    )
    client = FakeForge()
    client.board_issues = (unblocked, blocked)
    client.board_dependencies[11] = (block_dependency(10),)
    observed_dependency_calls: list[int] = []
    original_list_board_dependencies = client.list_board_dependencies

    def spy_list_board_dependencies(number: int) -> tuple[IssueDependency, ...]:
        observed_dependency_calls.append(number)
        return original_list_board_dependencies(number)

    monkeypatch.setattr(client, "list_board_dependencies", spy_list_board_dependencies)
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())
    _patch_store_write(monkeypatch)

    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert observed_dependency_calls == [11]
    # Open issues, open PRs, merged PRs, and exactly one dependency lookup
    # (for #11, never #10) -- block mode never calls `list_board_blockers`,
    # and claims come from the store now, never a ledger
    # comments request.
    assert payload["requests"] == client.requests == 4


def test_board_shows_open_and_total_instead_of_proposed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    issues = (
        board_issue(10, "No expectations", complete_contract("Claim #10.")),
        board_issue(
            11,
            "Proposed expectations",
            complete_contract(
                "Claim #11.",
                expectation=[
                    ruled_expectation("Name it."),
                    proposed_expectation("Settle it.", default="no"),
                ],
            ),
        ),
        board_issue(
            12,
            "Ruled expectations",
            complete_contract("Claim #12.", expectation=[ruled_expectation("Name it.")]),
        ),
    )
    client = FakeForge()
    monkeypatch.setattr(client, "list_open_board_issues", lambda: issues)
    monkeypatch.setattr(client, "list_open_board_pull_requests", lambda: ())
    monkeypatch.setattr(client, "list_recent_merged_board_pull_requests", lambda _since: ())
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())

    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 0
    items = {item["number"]: item for item in json.loads(capsys.readouterr().out)["items"]}
    expectation_states = {number: item["expectation_state"] for number, item in items.items()}
    assert expectation_states == {10: "-", 11: "proposed", 12: "ruled"}
    assert items[11]["expectation_progress"] == {"open": 1, "total": 2}


def _configured_board_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    open_issues: tuple[Issue, ...] = (),
    open_pull_requests: tuple[workboard.PullRequest, ...] = (),
    dependencies: Mapping[int, tuple[IssueDependency, ...]] = MappingProxyType({}),
    standing: tuple[ClaimRequest, ...] = (),
) -> FakeForge:
    """A `FakeForge` client wired the way every board-reading claim test needs."""
    client = FakeForge()
    monkeypatch.setattr(client, "list_open_board_issues", lambda: open_issues)
    monkeypatch.setattr(client, "list_open_board_pull_requests", lambda: open_pull_requests)
    client.board_open_pull_requests = open_pull_requests
    client.board_dependencies = dict(dependencies)
    monkeypatch.setattr(client, "list_recent_merged_board_pull_requests", lambda _since: ())
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_lane_worktree_git(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())
    _patch_store_write(monkeypatch, *(store_claim_from_request(claimed) for claimed in standing))
    return client


def _fake_every_git_read_as_tmp_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every git read answers `tmp_path`, except the width gate's `ls-tree`
    read of a scope entry, which finds no entry."""
    monkeypatch.setattr(
        checkout,
        "git_output",
        lambda arguments, **_kwargs: "" if arguments[0] == "ls-tree" else str(tmp_path),
    )


def _fake_lane_worktree_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every git read answers `tmp_path`, and the run stands in a linked lane
    worktree, where `next` advises `claim`; its advice from the default
    branch's checkout is driven against real git in
    `test_next_advises_a_pull_that_runs_as_printed_where_it_stands`."""
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        checkout,
        "resolve_path_checkout",
        lambda directory: checkout.PathCheckout(
            directory, "lane", checkout.CheckoutKind.LINKED_WORKTREE, tmp_path, True
        ),
    )


def _stub_issue_reference(
    monkeypatch: pytest.MonkeyPatch,
    states: dict[int, tuple[forge.ItemState, str | None, str]],
) -> None:
    """Overrides the autouse OPEN default for exactly the given issue numbers."""

    def fetch(client: object, number: int) -> forge.ItemReference:
        state, title, body = states[number]
        return forge.ItemReference(state, title, body)

    monkeypatch.setattr(board_read, "fetch_issue_reference", fetch)


_TOP_AND_BLOCKED = (
    board_issue(10, "Lower work", complete_contract("Claim #10.")),
    board_issue(11, "Top work", complete_contract("Claim #11.")),
    board_issue(12, "Depends on top", complete_contract("Claim #12."), blocked_by_count=1),
)
_BLOCKED_BY_ELEVEN = {12: (block_dependency(11),)}
# A security item outranks every other one, but it waits on the
# operator's ruling, so no agent can pull it.
_WAITING_AND_PULLABLE = (
    board_issue(
        230,
        "Operator ruling",
        complete_contract("wait for session with the operator"),
        labels=("security", NEEDS_OPERATOR_LABEL),
    ),
    board_issue(11, "Top work", complete_contract("Claim #11.")),
)


def _childless_container(number: int, body_text: str, *, labels: tuple[str, ...] = ()) -> Issue:
    return Issue(
        number,
        f"Epic {number}",
        labels,
        body_text,
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=1,
        children_total=1,
    )


# Containers the operator holds -- one labelled with an
# uncut row, one frozen whose `Next` still names work, one labelled but
# closable -- beside one pullable item.
_OPERATOR_HELD_CONTAINERS = (
    _childless_container(
        441,
        complete_contract("Cut it.", slice=slice_entries("Scheibe A")),
        labels=(NEEDS_OPERATOR_LABEL,),
    ),
    _childless_container(442, complete_contract("Check it.", frozen_until=FROZEN_UNTIL)),
    _childless_container(443, complete_contract("keiner"), labels=(NEEDS_OPERATOR_LABEL,)),
    board_issue(11, "Top work", complete_contract("Claim #11.")),
)

# Every `next` golden below a scopeless `WorkItemAction` needs
# this note right after its `Run:` line -- the item's own body names no
# scope, so `claim` cannot derive one either -- and this tail once the
# action's own lines end: a scopeless first action leaves `parallel_set`
# nothing to found a set on, so `parallel:`/`scope unknown:` collapse into
# the one `unknown` sentence, and `close:` still prints `none`.
_SCOPE_UNKNOWN_NOTE_LINE = "scope unknown\n"
_PARALLEL_UNKNOWN_TAIL = "parallel: unknown (first action names no scope)\nclose: none\n"
_UNKNOWN_SCOPE_NEXT_TAIL = _SCOPE_UNKNOWN_NOTE_LINE + _PARALLEL_UNKNOWN_TAIL
# The same tail once there is no first action to found a parallel set on at
# all (`workboard.parallel_set` returns an empty, *not* first-scope-unknown, set).
_NO_ACTION_NEXT_TAIL = "parallel: none\nscope unknown: none\nclose: none\n"
_UNKNOWN_SCOPE_PARALLEL_JSON: dict[str, object] = {
    "first_scope_unknown": True,
    "candidates": [],
    "scope_unknown": [],
}
_EMPTY_PARALLEL_JSON: dict[str, object] = {
    "first_scope_unknown": False,
    "candidates": [],
    "scope_unknown": [],
}
_NOTHING_NAMED_JSON: dict[str, object] = {
    "close": [],
    "waiting_on_operator": [],
    "ideas": [],
    "with_head": [],
}

# Five free items -- Beta and Gamma name the same
# path (the "two overlapping each other" pair), Delta names no scope at
# all, Epsilon names a path under claim-live-1's own directory scope (the
# "excluded by a live claim, not by another candidate" case; R1 review) --
# read against two live claims, claim-live-2's own path sitting inside
# claim-live-1's directory scope, so the two are not disjoint from each
# other either; only the free items are checked for disjointness here.
# Alpha out-ranks the rest purely by its lower issue number (every item
# shares the same score), so it is always the first action; Beta then wins
# the walk over Gamma (board order), and Gamma is dropped silently --
# neither `parallel:` nor `scope unknown:` names an item excluded for
# overlap, only one excluded for lacking a scope at all. Epsilon is
# dropped the same silent way, but for a different reason: were the walk
# not occupying the live claims' own scopes, Epsilon would have nothing to
# collide with and would surface in `parallel:` instead.
_PARALLEL_ALPHA = board_issue(
    50, "Alpha", complete_contract("Ship Alpha.", scope=["src/alpha1.py", "src/alpha2.py"])
)
_PARALLEL_BETA = board_issue(51, "Beta", complete_contract("Ship Beta.", scope=["src/shared.py"]))
_PARALLEL_GAMMA = board_issue(
    52, "Gamma", complete_contract("Ship Gamma.", scope=["src/shared.py"])
)
_PARALLEL_DELTA = board_issue(53, "Delta", complete_contract("Ship Delta."))
_PARALLEL_EPSILON = board_issue(
    54, "Epsilon", complete_contract("Ship Epsilon.", scope=["claimed/deep/file.py"])
)
_PARALLEL_ITEMS = (
    _PARALLEL_ALPHA,
    _PARALLEL_BETA,
    _PARALLEL_GAMMA,
    _PARALLEL_DELTA,
    _PARALLEL_EPSILON,
)
_PARALLEL_LIVE_CLAIMS = (
    request(claim_id="claim-live-1", issue=990, scope=("claimed",)),
    request(claim_id="claim-live-2", issue=991, scope=("claimed/two.py",)),
)


@pytest.mark.parametrize(
    ("issues", "dependencies", "claims", "arguments", "expected_exit", "expected_output"),
    [
        pytest.param(
            _TOP_AND_BLOCKED,
            _BLOCKED_BY_ELEVEN,
            (),
            ("next",),
            0,
            "#11 score 10: Top work\nNext: Claim #11.\n"
            "Run: aco claim 11 --scope <paths>\n" + _UNKNOWN_SCOPE_NEXT_TAIL + "\nSKIPPED\n"
            "#12: blocked by #11\n",
            id="names_the_highest_scored_actionable_item",
        ),
        pytest.param(
            _TOP_AND_BLOCKED,
            _BLOCKED_BY_ELEVEN,
            (),
            ("next", "--json"),
            0,
            {
                "ok": True,
                "reason": "work_item",
                "number": 11,
                "score": 10,
                "title": "Top work",
                "next": "Claim #11.",
                "command": "aco claim 11 --scope <paths>",
                "recovery": [],
                "skipped": [{"number": 12, "reason": "blocked by #11"}],
                "ruling_landings": None,
                "ruling_old": None,
                "parallel": _UNKNOWN_SCOPE_PARALLEL_JSON,
                **_NOTHING_NAMED_JSON,
            },
            id="emits_the_highest_scored_actionable_item_as_json",
        ),
        pytest.param(
            (board_issue(10, "Incomplete", complete_contract("", done_when="")),),
            {},
            (),
            ("next",),
            3,
            "No actionable item.\n" + _NO_ACTION_NEXT_TAIL + "\nSKIPPED\n"
            "#10: body incomplete: Next, Done when\n",
            id="names_an_incomplete_body_as_the_reason_nothing_is_pullable",
        ),
        pytest.param(
            (board_issue(10, "Blockless", "## Now\nInvestigate."),),
            {},
            (),
            ("next",),
            3,
            "No actionable item.\n" + _NO_ACTION_NEXT_TAIL + "\nSKIPPED\n"
            "#10: body malformed: aco: no aco block\n",
            id="names_a_body_with_no_block_as_malformed",
        ),
        pytest.param(
            (board_issue(10, "Claimed", complete_contract("Claim #10.")),),
            {},
            (request(issue=10),),
            ("next",),
            3,
            "No actionable item.\n" + _NO_ACTION_NEXT_TAIL + "\nSKIPPED\n#10: claimed\n",
            id="names_a_live_claim_as_the_reason_nothing_is_pullable",
        ),
        pytest.param(
            (
                board_issue(9, "Open blocker", complete_contract("Claim #9.")),
                board_issue(10, "Blocked", complete_contract("Claim #10."), blocked_by_count=1),
            ),
            {10: (block_dependency(9),)},
            (),
            ("next",),
            0,
            "#9 score 10: Open blocker\nNext: Claim #9.\n"
            "Run: aco claim 9 --scope <paths>\n" + _UNKNOWN_SCOPE_NEXT_TAIL + "\nSKIPPED\n"
            "#10: blocked by #9\n",
            id="excludes_items_with_open_blockers",
        ),
        pytest.param(
            (),
            {},
            (),
            ("next",),
            3,
            "No actionable item.\n" + _NO_ACTION_NEXT_TAIL,
            id="prints_no_actionable_item_on_a_fully_empty_board",
        ),
        pytest.param(
            (),
            {},
            (),
            ("next", "--json"),
            3,
            {
                "ok": False,
                "reason": "nothing_actionable",
                "recovery": [],
                "skipped": [],
                "parallel": _EMPTY_PARALLEL_JSON,
                **_NOTHING_NAMED_JSON,
            },
            id="emits_nothing_actionable_on_a_fully_empty_board",
        ),
        pytest.param(
            _PARALLEL_ITEMS,
            {},
            _PARALLEL_LIVE_CLAIMS,
            ("next",),
            0,
            "#50 score -10: Alpha\nNext: Ship Alpha.\n"
            "Run: aco claim 50\n"
            "parallel: #51 (1 path)\n"
            "scope unknown: #53\n"
            "close: none\n",
            id="parallel_set_names_the_maximal_disjoint_set_and_the_unknown_scope_item",
        ),
        pytest.param(
            _PARALLEL_ITEMS,
            {},
            _PARALLEL_LIVE_CLAIMS,
            ("next", "--json"),
            0,
            {
                "ok": True,
                "reason": "work_item",
                "number": 50,
                "score": -10,
                "title": "Alpha",
                "next": "Ship Alpha.",
                "command": "aco claim 50",
                "recovery": [],
                "skipped": [],
                "ruling_landings": None,
                "ruling_old": None,
                "parallel": {
                    "first_scope_unknown": False,
                    "candidates": [{"number": 51, "scope": ["src/shared.py"]}],
                    "scope_unknown": [53],
                },
                **_NOTHING_NAMED_JSON,
            },
            id="parallel_set_json_carries_full_scopes_for_every_candidate",
        ),
        pytest.param(
            _WAITING_AND_PULLABLE,
            {},
            (),
            ("next",),
            0,
            "#11 score -10: Top work\nNext: Claim #11.\n"
            "Run: aco claim 11 --scope <paths>\n"
            + _UNKNOWN_SCOPE_NEXT_TAIL
            + "waiting on operator: #230\n",
            id="names_the_pullable_item_and_the_one_waiting_on_the_operator_apart",
        ),
        pytest.param(
            _WAITING_AND_PULLABLE,
            {},
            (),
            ("next", "--json"),
            0,
            {
                "ok": True,
                "reason": "work_item",
                "number": 11,
                "score": -10,
                "title": "Top work",
                "next": "Claim #11.",
                "command": "aco claim 11 --scope <paths>",
                "recovery": [],
                "skipped": [],
                "ruling_landings": None,
                "ruling_old": None,
                "parallel": _UNKNOWN_SCOPE_PARALLEL_JSON,
                "close": [],
                "waiting_on_operator": [230],
                "ideas": [],
                "with_head": [],
            },
            id="json_lists_the_item_waiting_on_the_operator_apart_from_skipped",
        ),
        pytest.param(
            _OPERATOR_HELD_CONTAINERS,
            {},
            (),
            ("next",),
            0,
            "#11 score -10: Top work\nNext: Claim #11.\n"
            "Run: aco claim 11 --scope <paths>\n"
            + _SCOPE_UNKNOWN_NOTE_LINE
            + "parallel: unknown (first action names no scope)\nclose: #443\n"
            + "waiting on operator: #441, #442\n",
            id="never_cuts_or_checks_a_container_the_operator_holds_but_still_closes_one",
        ),
        pytest.param(
            _OPERATOR_HELD_CONTAINERS,
            {},
            (),
            ("next", "--json"),
            0,
            {
                "ok": True,
                "reason": "work_item",
                "number": 11,
                "score": -10,
                "title": "Top work",
                "next": "Claim #11.",
                "command": "aco claim 11 --scope <paths>",
                "recovery": [],
                "skipped": [],
                "ruling_landings": None,
                "ruling_old": None,
                "parallel": _UNKNOWN_SCOPE_PARALLEL_JSON,
                "close": [443],
                "waiting_on_operator": [441, 442],
                "ideas": [],
                "with_head": [],
            },
            id="json_lists_operator_held_containers_as_waiting_and_a_closable_one_under_close",
        ),
    ],
)
def test_next_reports_the_highest_scored_actionable_item(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    issues: tuple[Issue, ...],
    dependencies: dict[int, tuple[IssueDependency, ...]],
    claims: tuple[ClaimRequest, ...],
    arguments: tuple[str, ...],
    expected_exit: int,
    expected_output: str | dict[str, object],
) -> None:
    _configured_board_client(
        monkeypatch,
        tmp_path,
        open_issues=issues,
        dependencies=dependencies,
        standing=claims,
    )

    assert issue_claim.main(["--repo", REPOSITORY, *arguments]) == expected_exit
    rendered = capsys.readouterr().out

    if isinstance(expected_output, str):
        assert rendered == expected_output
    else:
        assert json.loads(rendered) == expected_output


def test_next_json_pins_the_raw_envelope_text_for_a_work_item_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The raw bytes `next` prints on success (OUT-nn's own key order,
    `ok`/`reason` first, and its trailing newline), not just the parsed dict
    `test_next_reports_the_highest_scored_actionable_item` already covers."""
    _configured_board_client(
        monkeypatch, tmp_path, open_issues=_TOP_AND_BLOCKED, dependencies=_BLOCKED_BY_ELEVEN
    )

    assert issue_claim.main(["--repo", REPOSITORY, "next", "--json"]) == 0

    assert capsys.readouterr().out == (
        '{"ok": true, "reason": "work_item", "recovery": [], '
        '"skipped": [{"number": 12, "reason": "blocked by #11"}], '
        '"parallel": {"first_scope_unknown": true, "candidates": [], "scope_unknown": []}, '
        '"close": [], "waiting_on_operator": [], "ideas": [], "with_head": [], '
        '"number": 11, "score": 10, '
        '"title": "Top work", "next": "Claim #11.", '
        '"command": "aco claim 11 --scope <paths>", "ruling_landings": null, '
        '"ruling_old": null}\n'
    )


PULLED_WITH_REFINING_FIRST = (
    "#10 score -10: Work\nNext: Claim #10.\n"
    "Run: aco claim 10 --scope <paths>\n"
    + _SCOPE_UNKNOWN_NOTE_LINE
    + "expectations unruled: refine before the pull\n"
    + _PARALLEL_UNKNOWN_TAIL
)


@pytest.mark.parametrize(
    ("expectations", "expected_state", "expected_output"),
    [
        pytest.param(
            (),
            body.ExpectationState.NONE,
            "#10 score -10: Work\nNext: Claim #10.\n"
            "Run: aco claim 10 --scope <paths>\n" + _UNKNOWN_SCOPE_NEXT_TAIL,
            id="no_expectation_entry_remains_actionable",
        ),
        pytest.param(
            (proposed_expectation("Name it.", default="yes"),),
            body.ExpectationState.PROPOSED,
            PULLED_WITH_REFINING_FIRST,
            id="proposed_expectations_are_pulled_with_refining_first",
        ),
        pytest.param(
            (ruled_expectation("Name it."), ruled_expectation("Remove it.", ruling="no")),
            body.ExpectationState.RULED,
            "#10 score -10: Work\nNext: Claim #10.\n"
            "Run: aco claim 10 --scope <paths>\n" + _UNKNOWN_SCOPE_NEXT_TAIL,
            id="fully_ruled_expectations_remain_actionable",
        ),
        pytest.param(
            (ruled_expectation("Name it.", ruling="no"), proposed_expectation("Remove it.")),
            body.ExpectationState.PROPOSED,
            PULLED_WITH_REFINING_FIRST,
            id="mixed_expectations_are_pulled_with_refining_first",
        ),
    ],
)
def test_next_reports_expectation_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    expectations: tuple[dict[str, object], ...],
    expected_state: body.ExpectationState,
    expected_output: str,
) -> None:
    issue = board_issue(10, "Work", complete_contract("Claim #10.", expectation=list(expectations)))
    client = FakeForge()
    monkeypatch.setattr(client, "list_open_board_issues", lambda: (issue,))
    monkeypatch.setattr(client, "list_open_board_pull_requests", lambda: ())
    monkeypatch.setattr(client, "list_recent_merged_board_pull_requests", lambda _since: ())
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_lane_worktree_git(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())

    assert issue_claim.main(["--repo", REPOSITORY, "next"]) == 0
    assert capsys.readouterr().out == expected_output

    projected = projected_board(
        (issue,), (), (), (), workboard.BoardConfig(), now=datetime(2026, 8, 21, tzinfo=UTC)
    )
    assert projected.items[0].expectation_state is expected_state


def test_next_pulls_an_unruled_item_and_names_only_unworkable_ones_as_skipped(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    unruled = board_issue(
        11,
        "Needs rulings",
        complete_contract(
            "Claim #11.", expectation=[proposed_expectation("Name it.", default="no")]
        ),
    )
    blocked, blocked_dependencies = blocked_issue(
        12, "Waits for rulings", block_dependency(11), next_step="Claim #12."
    )
    claimed = board_issue(13, "Another lane", complete_contract("Claim #13."))
    standing = request(issue=13)
    client = FakeForge()
    client.board_dependencies = dict(blocked_dependencies)
    monkeypatch.setattr(client, "list_open_board_issues", lambda: (unruled, blocked, claimed))
    monkeypatch.setattr(client, "list_open_board_pull_requests", lambda: ())
    monkeypatch.setattr(client, "list_recent_merged_board_pull_requests", lambda _since: ())
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_lane_worktree_git(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())
    _patch_store_write(monkeypatch, store_claim_from_request(standing))

    assert issue_claim.main(["--repo", REPOSITORY, "next"]) == 0
    assert capsys.readouterr().out == (
        "#11 score 10: Needs rulings\n"
        "Next: Claim #11.\n"
        "Run: aco claim 11 --scope <paths>\n"
        + _SCOPE_UNKNOWN_NOTE_LINE
        + "expectations unruled: refine before the pull\n"
        + _PARALLEL_UNKNOWN_TAIL
        + "\n"
        "SKIPPED\n"
        "#12: blocked by #11\n"
        "#13: claimed\n"
    )

    assert issue_claim.main(["--repo", REPOSITORY, "next", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "ok": True,
        "reason": "work_item",
        "number": 11,
        "score": 10,
        "title": "Needs rulings",
        "next": "Claim #11.",
        "command": "aco claim 11 --scope <paths>",
        "ruling_landings": None,
        "ruling_old": None,
        "ruling_hint": "expectations unruled: refine before the pull",
        "recovery": [],
        "skipped": [
            {"number": 12, "reason": "blocked by #11"},
            {"number": 13, "reason": "claimed"},
        ],
        "parallel": _UNKNOWN_SCOPE_PARALLEL_JSON,
        **_NOTHING_NAMED_JSON,
    }


def _start_scenario(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, agent: str = "Codex Sol"
) -> Path:
    """A real bare-remote-backed repository, item #314 open
    with a titled, scoped body, and this test's own toplevel redirected onto
    it -- `start`'s own worktree creation runs real git, unlike every other
    claim test in this module, which never builds one at all."""
    repo, _remote = real_repository_with_bare_remote(tmp_path)
    (repo / "base.txt").write_text("base\n")
    real_git(repo, "add", "base.txt")
    real_git(repo, "commit", "-q", "-m", "initial")
    push_repository_trunk(repo, "origin")
    _serve_start_board(monkeypatch, _start_item())
    _patch_store_write(monkeypatch)
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: agent})
    redirect_toplevel(monkeypatch, repo)
    return repo


def _start_item(body_text: str | None = None, *, kind: body.ItemKind | None = None) -> Issue:
    """Item #314 as `start`'s scenarios know it: a scoped, complete body
    unless the scenario names another."""
    if body_text is None:
        body_text = complete_contract("Build it.", scope=["src/x.py"])
    return board_issue(314, "Fresh Slug Title", body_text, kind=kind)


def _serve_start_board(monkeypatch: pytest.MonkeyPatch, *issues: Issue) -> FakeForge:
    """A fake forge listing `issues` as the open board, the first of them the
    open item `start` targets."""
    target = issues[0]
    client = FakeForge(board_issues=issues)
    client.issue_references[target.number] = forge.ItemReference(
        forge.ItemState.OPEN, target.title, target.body
    )
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    return client


_START_WORKTREE_NAME = "issue-314-fresh-slug-title"
_START_BRANCH = "codex/issue-314-fresh-slug-title"
_CLAIM_ID_PATTERN = r"[0-9a-f]{32}"


def _claimed_line_id(out: str, subject: str) -> str:
    """The claim id `CLAIMED <subject>: <id>` printed in `out`:
    `start` mints a fresh id exactly as a bare `aco
    claim` does, so a test proving it never pins one -- only that a create
    prints a real one and a resume reprints the same one."""
    match = re.search(rf"CLAIMED {re.escape(subject)}: ({_CLAIM_ID_PATTERN})\n", out)
    assert match is not None
    return match.group(1)


def test_start_creates_the_linked_worktree_and_claims_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)

    assert issue_claim.main(["--repo", REPOSITORY, "start", "314"]) == 0

    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    out = capsys.readouterr().out
    claim_id = _claimed_line_id(out, "issue #314")
    assert out == (
        f"worktree: {worktree}\n"
        f"branch: {_START_BRANCH}\n"
        f"CLAIMED issue #314: {claim_id}\n"
        "0 of 4 versioned files (0%); overlaps no other open claims\n"
    )
    resolved = checkout.resolve_path_checkout(worktree)
    assert resolved is not None
    assert resolved.branch == _START_BRANCH
    assert resolved.kind is checkout.CheckoutKind.LINKED_WORKTREE
    live = store.fetch_state(worktree=Path("."), remote="origin").claims
    assert protocol.claim_key(protocol.IssueIdentity(314), _START_BRANCH) in live
    assert Path.cwd() == repo


def test_start_resumes_an_existing_worktree_by_only_claiming(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)
    assert issue_claim.main(["--repo", REPOSITORY, "start", "314"]) == 0
    first_claim_id = _claimed_line_id(capsys.readouterr().out, "issue #314")
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME

    assert issue_claim.main(["--repo", REPOSITORY, "start", "314"]) == 0

    resumed_claim_id = _claimed_line_id(capsys.readouterr().out, "issue #314")
    assert resumed_claim_id == first_claim_id
    assert len(store.fetch_state(worktree=Path("."), remote="origin").claims) == 1
    assert checkout.resolve_path_checkout(worktree) is not None
    assert Path.cwd() == repo


def test_start_from_a_linked_worktree_builds_beside_the_main_checkout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The worktree's place comes from the main
    checkout, never nested under the linked worktree the call runs in."""
    repo = _start_scenario(monkeypatch, tmp_path)
    _stand_in_another_lane(monkeypatch, repo, tmp_path)

    status = issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    assert (status, capsys.readouterr().out.splitlines()[0]) == (0, f"worktree: {worktree}")
    assert checkout.resolve_path_checkout(worktree) is not None


def _stand_in_another_lane(monkeypatch: pytest.MonkeyPatch, repo: Path, tmp_path: Path) -> Path:
    """Run from a linked worktree of `repo` on another item's lane."""
    other_lane = tmp_path / "other-lane"
    real_git(repo, "worktree", "add", "-q", "-b", "codex/issue-9-other", str(other_lane))
    redirect_toplevel(monkeypatch, other_lane)
    monkeypatch.chdir(other_lane)
    return other_lane


def _stand_in_the_items_released_lane(
    monkeypatch: pytest.MonkeyPatch, repo: Path, _tmp_path: Path
) -> Path:
    """Run from item #314's own clean lane worktree after its claim was
    released: `start` claims there afresh (START-11)."""
    assert issue_claim.main(["--repo", REPOSITORY, "start", "314"]) == 0
    assert issue_claim.main(["--repo", REPOSITORY, "release", "314", "--abandoned", "paused"]) == 0
    lane = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    redirect_toplevel(monkeypatch, lane)
    monkeypatch.chdir(lane)
    return lane


@pytest.mark.parametrize(
    "stand_in_a_lane",
    [
        pytest.param(_stand_in_another_lane, id="another-lane-builds"),
        pytest.param(_stand_in_the_items_released_lane, id="own-released-lane-claims"),
    ],
)
def test_start_from_a_linked_worktree_checks_against_the_main_checkouts_board_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    stand_in_a_lane: Callable[[pytest.MonkeyPatch, Path, Path], Path],
) -> None:
    """The claim's checks read the main
    checkout's `board.toml`, never the one a lane the caller stands in has
    committed -- whether `start` builds a new worktree or claims afresh in
    the item's own released lane -- so a lane that drops `security` from the
    priority labels must not let #314 pass the security item the main
    checkout ranks first."""
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)
    lane = stand_in_a_lane(monkeypatch, repo, tmp_path)
    (lane / workboard.CONFIG_PATH).parent.mkdir()
    (lane / workboard.CONFIG_PATH).write_text('priority_labels = ["cleanup"]\n')
    real_git(lane, "add", str(workboard.CONFIG_PATH))
    real_git(lane, "commit", "-q", "-m", "lane changes its board config")
    security = board_issue(
        500,
        "Security first",
        complete_contract("Claim #500.", scope=["src/y.py"]),
        labels=("security",),
    )
    _serve_start_board(monkeypatch, _start_item(), security)
    capsys.readouterr()
    before = worktrees_and_branches(repo)

    status = issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    assert (status, worktrees_and_branches(repo)) == (2, before)
    assert "higher-priority actionable item #500" in capsys.readouterr().err


def test_start_inside_its_own_lane_worktree_reprints_the_live_claim(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """`start` run inside the item's own lane worktree
    -- its branch the live claim's, its slug not the title's, work in
    progress in it -- reprints that claim instead of building another."""
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)
    assert issue_claim.main(["--repo", REPOSITORY, "start", "314", "--slug", "own-lane"]) == 0
    claim_id = _claimed_line_id(capsys.readouterr().out, "issue #314")
    worktree = repo.parent / f"{repo.name}-worktrees" / "issue-314-own-lane"
    (worktree / "work.txt").write_text("in progress\n")
    redirect_toplevel(monkeypatch, worktree)
    monkeypatch.chdir(worktree)
    before = worktrees_and_branches(repo)

    status = issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    assert (status, worktrees_and_branches(repo)) == (0, before)
    assert capsys.readouterr().out.splitlines()[:3] == [
        f"worktree: {worktree}",
        "branch: codex/issue-314-own-lane",
        f"CLAIMED issue #314: {claim_id}",
    ]


def test_start_refuses_a_slug_the_derived_rule_would_never_produce(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)

    status = issue_claim.main(["--repo", REPOSITORY, "start", "314", "--slug", "Bad_Slug"])

    assert status == 2
    assert capsys.readouterr().err == "ERROR: --slug must be " + checkout._SLUG_SHAPE_RULE + "\n"
    assert not (repo.parent / f"{repo.name}-worktrees").exists()


def test_start_refuses_an_unsafe_identity_prefix_before_any_git_write(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """An unsafe `ACO_AGENT` first word must never
    reach `git worktree add` -- the branch it would build is refused first,
    by name, and no worktree is ever created."""
    repo = _start_scenario(monkeypatch, tmp_path, agent="-bad")
    monkeypatch.chdir(repo)

    status = issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    assert status == 2
    assert capsys.readouterr().err == (
        "ERROR: agent identity '-bad' is not usable in a branch name: "
        "'-bad/issue-314-fresh-slug-title' is not a safe Git ref\n"
    )
    assert not (repo.parent / f"{repo.name}-worktrees").exists()


def _serve_an_item_without_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve_start_board(monkeypatch, _start_item(complete_contract("Build it.")))


def _serve_a_malformed_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """The block defect is named, never the less
    specific "item names no scope"."""
    _serve_start_board(
        monkeypatch, _start_item(block_body(f'{MINIMAL_BLOCK_TOML}owner = "someone"\n'))
    )


def _serve_an_invalid_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve_start_board(
        monkeypatch,
        _start_item(
            complete_contract("Build it.", scope=["a.py", "b.py", "c.py", "d.py"], whole="x" * 513)
        ),
    )


def _serve_a_container(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve_start_board(monkeypatch, _start_item(kind=body.ItemKind.CONTAINER))


def _serve_an_incomplete_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve_start_board(monkeypatch, _start_item(unfilled_block_body()))


def _serve_a_higher_priority_item(monkeypatch: pytest.MonkeyPatch) -> None:
    security = board_issue(
        11,
        "Security first",
        complete_contract("Claim #11.", scope=["src/y.py"]),
        labels=("security",),
    )
    _serve_start_board(monkeypatch, _start_item(), security)


def _hold_a_claim_by_another_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """`protocol.claim_key` never folds in `branch`, so
    another agent's claim on #314 is never resumed as this session's own."""
    _hold_a_claim_on_the_item(monkeypatch, "Grok sess-9", branch="grok/issue-314-other")


def _hold_a_reviewer_claim_on_the_lane_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """This agent's own claim on the lane
    branch, but as `reviewer`, is never resumed as `start`'s build claim."""
    _hold_a_claim_on_the_item(monkeypatch, "Codex Sol", branch=_START_BRANCH, role="reviewer")


def _hold_a_claim_on_the_item(
    monkeypatch: pytest.MonkeyPatch, agent: str, *, branch: str, role: str = "builder"
) -> None:
    held = request("held-claim", agent, issue=314, role=role, branch=branch, scope=("src/x.py",))
    _patch_store_write(monkeypatch, store_claim_from_request(held))


@pytest.mark.parametrize(
    ("arrange", "arguments", "refusal"),
    [
        pytest.param(
            _serve_an_item_without_scope, [], "item names no scope; pass --scope", id="no-scope"
        ),
        pytest.param(
            _serve_a_malformed_body,
            [],
            "#314 body malformed: owner: unknown top-level key owner",
            id="malformed-body",
        ),
        pytest.param(
            _serve_a_container,
            [],
            "#314 is a container; claim a child",
            id="container",
        ),
        pytest.param(
            _serve_an_incomplete_body,
            ["--scope", "src/x.py"],
            "#314 body incomplete: Now, Next, Done when",
            id="incomplete-body",
        ),
        pytest.param(
            _serve_a_higher_priority_item,
            [],
            "higher-priority actionable item #11",
            id="out-of-order",
        ),
        pytest.param(
            lambda _monkeypatch: None,
            ["--scope", "a.py", "--scope", "b.py", "--scope", "c.py", "--scope", "d.py"],
            "scope is wide: ",
            id="wide-scope",
        ),
        pytest.param(
            _hold_a_claim_by_another_agent,
            [],
            "issue #314 is claimed by Grok sess-9",
            id="claimed-by-another-agent",
        ),
        pytest.param(
            _hold_a_reviewer_claim_on_the_lane_branch,
            [],
            "issue #314 is claimed by Codex Sol",
            id="reviewer-claim-on-the-lane-branch",
        ),
        *(
            pytest.param(
                _serve_an_invalid_whole,
                flags,
                f"ERROR: {label}body malformed: whole: "
                "whole reason must be one bounded non-empty line\n",
                id=f"whole-cell13{variant}",
            )
            for variant, flags, label in (
                ("a", [], "#314 "),
                ("b", ["--scope", "a.py"], ""),
                (
                    "c",
                    [
                        part
                        for path in ("a.py", "b.py", "c.py", "d.py")
                        for part in ("--scope", path)
                    ],
                    "#314 ",
                ),
                (
                    "d",
                    [
                        part
                        for path in ("a.py", "b.py", "c.py", "d.py")
                        for part in ("--scope", path)
                    ]
                    + ["--whole", "ok"],
                    "",
                ),
            )
        ),
        pytest.param(
            lambda _monkeypatch: None,
            ["--whole", "a\nb"],
            "ERROR: whole reason must be one bounded non-empty line\n",
            id="whole-cell15",
        ),
    ],
)
def test_a_refused_start_leaves_no_worktree_and_no_branch_behind(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    arrange: Callable[[pytest.MonkeyPatch], None],
    arguments: list[str],
    refusal: str,
) -> None:
    """Spec: CLM-36, CLM-37, BODY-52. T5: matrix 13, 15.

    Every check that can refuse the claim runs
    before `start` builds, so a refusal builds nothing -- no worktree, no
    branch, no `worktree:` line -- and has nothing to undo."""
    repo = _start_scenario(monkeypatch, tmp_path)
    arrange(monkeypatch)
    monkeypatch.chdir(repo)
    before = worktrees_and_branches(repo)

    client = github.GitHubForge(github.repository_id(REPOSITORY))
    stored = tuple(client.list_open_board_issues())
    claims_before = store.fetch_state(worktree=Path("."), remote="origin").claims
    status = issue_claim.main(["--repo", REPOSITORY, "start", "314", *arguments])

    out, err = capsys.readouterr()
    assert (status, worktrees_and_branches(repo), out) == (2, before, "")
    assert refusal in err
    assert "removed worktree" not in err

    if "whole reason must be" in refusal:
        assert err == refusal
        assert not claims_before
        assert not store.fetch_state(worktree=Path("."), remote="origin").claims
        assert tuple(client.list_open_board_issues()) == stored


_OWN_DETACHED_HEAD_REFUSAL = "HEAD is detached; check out the lane branch first"


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param(["claim", "314", "--scope", "base.txt"], id="claim"),
        pytest.param(
            ["claim", "314", "--scope", "base.txt", "--branch", "claude/issue-314-detached"],
            id="claim-with-branch",
        ),
        pytest.param(
            ["claim", "314", "--scope", "base.txt", "--branch", "main"],
            id="claim-with-trunk-branch",
        ),
    ],
)
def test_a_detached_head_is_named_and_nothing_is_written(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    arguments: list[str],
) -> None:
    """CLM-33: `claim` in a linked worktree on a detached HEAD
    refuses by naming its own detached HEAD -- never a claim marker field
    -- and writes no claim, worktree, or branch."""
    repo, worktree, fake = _detached_start_worktree(monkeypatch, tmp_path)
    redirect_toplevel(monkeypatch, worktree)
    monkeypatch.chdir(worktree)
    before = worktrees_and_branches(repo)

    status = issue_claim.main(["--repo", REPOSITORY, *arguments])

    assert (status, capsys.readouterr().err) == (2, f"ERROR: {_OWN_DETACHED_HEAD_REFUSAL}\n")
    assert (worktrees_and_branches(repo), fake.transitions) == (before, [])


def test_claim_in_a_lane_worktree_refuses_with_gits_text_when_the_remote_head_read_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A failed read of `<remote>/HEAD` is no trunk to guess for the claim's
    checkout checks: nothing is written."""
    repo = _start_scenario(monkeypatch, tmp_path)
    fake = _patch_store_write(monkeypatch)
    lane = _stand_in_another_lane(monkeypatch, repo, tmp_path)
    before = worktrees_and_branches(repo)
    stub_one_git_call(
        monkeypatch, list(RECORDED_ORIGIN_HEAD_READ), exit_status=128, stderr="fatal: broken"
    )

    status = issue_claim.main(["--repo", REPOSITORY, "claim", "314", "--scope", "base.txt"])

    assert (status, capsys.readouterr().err) == (2, "ERROR: fatal: broken\n")
    assert (worktrees_and_branches(repo), fake.transitions, lane.is_dir()) == (before, [], True)


@pytest.mark.parametrize(
    ("branch_exists", "switch"),
    [
        pytest.param(False, ("switch", "-c"), id="branch-absent"),
        pytest.param(True, ("switch",), id="branch-present"),
    ],
)
def test_start_names_a_runnable_command_for_a_detached_worktree(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    branch_exists: bool,
    switch: tuple[str, ...],
) -> None:
    """START-29: `start` run from main names the
    detached worktree at its computed path and the git command that
    attaches it to the lane branch, writes nothing, and that command runs
    as printed in bash -- its path shell-quoted even under a parent
    directory holding a space."""
    parent_with_space = tmp_path / "with space"
    parent_with_space.mkdir()
    repo, worktree, fake = _detached_start_worktree(monkeypatch, parent_with_space)
    if branch_exists:
        real_git(repo, "branch", _START_BRANCH)
    redirect_toplevel(monkeypatch, repo)
    monkeypatch.chdir(repo)
    before = worktrees_and_branches(repo)

    status = issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    advice = shlex.join(["git", "-C", str(worktree), *switch, _START_BRANCH])
    named = f"worktree {worktree} has a detached HEAD; run {advice} first"
    assert (status, capsys.readouterr().err) == (2, f"ERROR: {named}\n")
    assert (worktrees_and_branches(repo), fake.transitions) == (before, [])
    subprocess.run(["bash", "-c", advice], check=True, capture_output=True)
    assert real_git(worktree, "branch", "--show-current").stdout.strip() == _START_BRANCH


def _detached_start_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path, _FakeStore]:
    """A `start` scenario whose computed worktree path already holds a
    worktree on a detached HEAD."""
    repo = _start_scenario(monkeypatch, tmp_path)
    fake = _patch_store_write(monkeypatch)
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    real_git(repo, "worktree", "add", "-q", "--detach", str(worktree))
    return repo, worktree, fake


def _claim_lands_before_the_commit(monkeypatch: pytest.MonkeyPatch, _repo: Path) -> None:
    """Another agent's claim on #314 lands between `start`'s check phase and
    its one ledger write."""
    fake = _patch_store_write(monkeypatch)
    held = store_claim_from_request(
        request("held-claim", "Grok sess-9", issue=314, branch="grok/issue-314-other", scope=("a",))
    )
    commit = fake.commit_transition

    def racing_commit(
        *, observed: store.Observation, subject: str, intent: protocol.ClaimTransitionIntent
    ) -> protocol.ClaimState:
        claims = {**fake.state.claims, protocol.claim_key(held.identity, held.branch): held}
        fake.state = replace(fake.state, claims=claims)
        return commit(observed=observed, subject=subject, intent=intent)

    monkeypatch.setattr(store, "commit_transition", racing_commit)


def _git_keeps_the_raced_branch(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    _claim_lands_before_the_commit(monkeypatch, repo)
    stub_one_git_call(
        monkeypatch,
        ["branch", "-d", _START_BRANCH],
        exit_status=1,
        stderr="error: branch not fully merged",
    )


def _the_raced_branch_delete_fails_to_finish(
    failure: Exception,
) -> Callable[[pytest.MonkeyPatch, Path], None]:
    """The raced claim refuses the build, and the git deleting its branch
    raises `failure` instead of running."""

    def arrange(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
        _claim_lands_before_the_commit(monkeypatch, repo)
        fail_git_launch(monkeypatch, ["branch", "-d"], failure)

    return arrange


def _the_store_cannot_be_reached(monkeypatch: pytest.MonkeyPatch, _repo: Path) -> None:
    """The ledger write fails before anything is written, with a refusal
    that is no claim conflict."""

    def unreachable(**_arguments: object) -> protocol.ClaimState:
        raise protocol.ClaimUnavailableError("remote origin hung up")

    monkeypatch.setattr(store, "commit_transition", unreachable)


def _trunk_moves_after_the_fetch(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    """Another push moves the trunk after `start` fetched and checked it,
    so the worktree it builds stands on a commit it never checked."""
    real_commit_at = checkout.commit_at

    def check_then_the_trunk_moves(trunk: str, *, directory: Path) -> str:
        checked = real_commit_at(trunk, directory=directory)
        real_git(repo, "commit", "-q", "--allow-empty", "-m", "moved")
        real_git(repo, "push", "-q", "origin", "HEAD:main")
        return checked

    monkeypatch.setattr(checkout, "commit_at", check_then_the_trunk_moves)


def _trunk_moves_while_a_gone_worktree_is_rebuilt(
    monkeypatch: pytest.MonkeyPatch, repo: Path
) -> None:
    """Item #314's claim stays live while its worktree and branch are gone,
    and the trunk moves after `start` fetched and checked it for the
    rebuild."""
    monkeypatch.chdir(repo)
    assert issue_claim.main(["--repo", REPOSITORY, "start", "314"]) == 0
    _remove_the_lane_pair(repo)
    _trunk_moves_after_the_fetch(monkeypatch, repo)


_REMOVED_BOTH = "removed worktree {worktree} and branch '{branch}' this start created"


@pytest.mark.parametrize(
    ("arrange", "refusal", "removal"),
    [
        pytest.param(
            _claim_lands_before_the_commit,
            "issue #314 is claimed by Grok sess-9",
            _REMOVED_BOTH,
            id="ledger-race",
        ),
        pytest.param(
            _git_keeps_the_raced_branch,
            "issue #314 is claimed by Grok sess-9",
            "removed worktree {worktree} this start created; "
            "branch '{branch}' kept: git failure: error: branch not fully merged",
            id="git-keeps-the-branch",
        ),
        pytest.param(
            _the_raced_branch_delete_fails_to_finish(PermissionError("permission denied")),
            "issue #314 is claimed by Grok sess-9",
            "removed worktree {worktree} this start created; "
            "branch '{branch}' kept: git failure: git failed to launch: permission denied",
            id="branch-delete-fails-to-launch",
        ),
        pytest.param(
            _the_raced_branch_delete_fails_to_finish(process.ProcessTimedOutError()),
            "issue #314 is claimed by Grok sess-9",
            "removed worktree {worktree} this start created; "
            "branch '{branch}' unknown: git branch timed out; check git branch --list {branch}",
            id="branch-delete-timed-out",
        ),
        pytest.param(
            _trunk_moves_after_the_fetch,
            "the trunk moved after start checked it; run start again\n",
            _REMOVED_BOTH,
            id="trunk-moved",
        ),
        pytest.param(
            _trunk_moves_while_a_gone_worktree_is_rebuilt,
            "the trunk moved after start checked it; run start again\n",
            _REMOVED_BOTH,
            id="trunk-moved-under-a-rebuild",
        ),
        pytest.param(
            _the_store_cannot_be_reached,
            "remote origin hung up",
            _REMOVED_BOTH,
            id="store-unreachable",
        ),
    ],
)
def test_a_claim_refused_after_the_build_removes_what_start_built(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    arrange: Callable[[pytest.MonkeyPatch, Path], None],
    refusal: str,
    removal: str,
) -> None:
    """START-18, START-21, START-26: a claim refused between
    the build and its push -- by the ledger, by the new worktree's own
    checkout preconditions, or by a trunk that moved after the checks, a
    live claim's rebuilt worktree included -- removes exactly the worktree
    and branch this call built, and says so; when git
    will not delete the branch the safe way, it says which branch stays and
    why, and a delete that timed out reads the branch unknown with the check
    that tells (START-30)."""
    repo = _start_scenario(monkeypatch, tmp_path)
    arrange(monkeypatch, repo)
    monkeypatch.chdir(repo)

    status = issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    err = capsys.readouterr().err
    assert (status, worktree.exists()) == (2, False)
    assert err.startswith(f"ERROR: {refusal}")
    assert err.endswith(removal.format(worktree=worktree, branch=_START_BRANCH) + "\n")


def test_a_refused_start_git_cannot_undo_keeps_the_refusal_and_names_what_stays(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """START-23: when git will not remove the worktree a
    refused call built, the refusal and its exit stay, and a line names the
    worktree and branch left standing and git's reason."""
    repo = _start_scenario(monkeypatch, tmp_path)
    _claim_lands_before_the_commit(monkeypatch, repo)
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    stub_one_git_call(
        monkeypatch,
        ["worktree", "remove", str(worktree)],
        exit_status=128,
        stderr="fatal: cannot remove a locked working tree",
    )
    monkeypatch.chdir(repo)

    status = issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    err = capsys.readouterr().err
    assert (status, worktree.exists()) == (2, True)
    assert err.startswith("ERROR: issue #314 is claimed by Grok sess-9")
    assert err.endswith(
        f"worktree {worktree} and branch '{_START_BRANCH}' this start created "
        "kept: git failure: fatal: cannot remove a locked working tree\n"
    )


class _ClosedPipe(io.StringIO):
    def write(self, _text: str) -> int:
        raise BrokenPipeError


def test_start_removes_what_it_built_even_when_its_refusal_cannot_be_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """START-18: a claim refused after the build removes the
    worktree and branch this call built even when stderr is a closed pipe
    and the refusal itself cannot be written."""
    repo = _start_scenario(monkeypatch, tmp_path)
    _claim_lands_before_the_commit(monkeypatch, repo)
    monkeypatch.chdir(repo)
    before = worktrees_and_branches(repo)
    monkeypatch.setattr(sys, "stderr", _ClosedPipe())

    with pytest.raises(BrokenPipeError):
        issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    assert worktrees_and_branches(repo) == before


def test_start_keeps_its_worktree_when_the_report_fails_after_the_claim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Only a refused claim undoes the build; a
    failure printing the report of a claim already written leaves the
    worktree and branch that claim names."""
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)

    def closed_pipe(*_arguments: object) -> str:
        raise BrokenPipeError

    monkeypatch.setattr(cmd_claim, "claim_cost_line", closed_pipe)

    with pytest.raises(BrokenPipeError):
        issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    live = store.fetch_state(worktree=Path("."), remote="origin").claims
    assert protocol.claim_key(protocol.IssueIdentity(314), _START_BRANCH) in live
    assert checkout.resolve_path_checkout(worktree) is not None


def _remove_the_lane_pair(repo: Path) -> None:
    """Item #314's worktree and branch are gone while its claim stays live."""
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    real_git(repo, "worktree", "remove", str(worktree))
    real_git(repo, "branch", "-D", _START_BRANCH)


def _keep_the_lane_pair(_repo: Path) -> None:
    """Item #314's worktree and branch stand as its first `start` built them."""


_COMMIT_READ = ["rev-parse", "--verify", "--quiet", "HEAD"]


def _fail_the_read_after_the_fetch(
    monkeypatch: pytest.MonkeyPatch, failing_read: list[str]
) -> None:
    """Lets every read through until the real fetch has run, then fails
    `failing_read` (`fatal: broken`): the read a command makes after its
    fetch (`RunContext.fetched_trunk_ref`) is one a failing first read never
    reaches."""
    real_fetch_remote = checkout.fetch_remote

    def fetch_then_fail_the_read(remote: str, *, directory: Path) -> None:
        real_fetch_remote(remote, directory=directory)
        stub_one_git_call(monkeypatch, failing_read, exit_status=128, stderr="fatal: broken")

    monkeypatch.setattr(checkout, "fetch_remote", fetch_then_fail_the_read)


@pytest.mark.parametrize(
    ("first_start_ran", "reshape_lane", "failing_read", "fails_after_fetch"),
    [
        pytest.param(
            False, _keep_the_lane_pair, list(RECORDED_ORIGIN_HEAD_READ), False, id="fresh-head"
        ),
        pytest.param(
            False,
            _keep_the_lane_pair,
            list(RECORDED_ORIGIN_HEAD_READ),
            True,
            id="fresh-head-after-fetch",
        ),
        pytest.param(False, _keep_the_lane_pair, _COMMIT_READ, False, id="fresh-commit"),
        pytest.param(True, _keep_the_lane_pair, _COMMIT_READ, False, id="resume-commit"),
        pytest.param(
            True, _remove_the_lane_pair, list(RECORDED_ORIGIN_HEAD_READ), False, id="rebuild-head"
        ),
        pytest.param(
            True,
            _remove_the_lane_pair,
            list(RECORDED_ORIGIN_HEAD_READ),
            True,
            id="rebuild-head-after-fetch",
        ),
        pytest.param(True, _remove_the_lane_pair, _COMMIT_READ, False, id="rebuild-commit"),
    ],
)
def test_start_refuses_with_gits_text_and_leaves_its_state_when_a_trunk_read_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    failing_read: list[str],
    first_start_ran: bool,
    reshape_lane: Callable[[Path], None],
    fails_after_fetch: bool,
) -> None:
    """A git failure reading `<remote>/HEAD` or the checkout's commit is
    neither a trunk to guess nor a checkout with no commit: a fresh start
    builds no worktree, branch or claim, and a resume or rebuild leaves the
    standing ones exactly as they were."""
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)
    if first_start_ran:
        assert issue_claim.main(["--repo", REPOSITORY, "start", "314"]) == 0
    reshape_lane(repo)
    capsys.readouterr()
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME

    def standing() -> tuple[bool, str, set[str]]:
        claims = store.fetch_state(worktree=Path("."), remote="origin").claims
        branches = real_git(repo, "branch", "--list", _START_BRANCH).stdout
        return worktree.exists(), branches, set(claims)

    before = standing()
    if fails_after_fetch:
        _fail_the_read_after_the_fetch(monkeypatch, failing_read)
    else:
        stub_one_git_call(monkeypatch, failing_read, exit_status=128, stderr="fatal: broken")

    status = issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    assert (status, capsys.readouterr().err) == (2, "ERROR: fatal: broken\n")
    assert standing() == before


def test_start_rebuilds_the_gone_worktree_of_its_live_claim_and_reprints_that_claim(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A live claim of this session whose worktree and branch
    are both gone gets its worktree built again at the computed path and the
    same claim reprinted, never a second id minted."""
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)
    assert issue_claim.main(["--repo", REPOSITORY, "start", "314"]) == 0
    claim_id = _claimed_line_id(capsys.readouterr().out, "issue #314")
    _remove_the_lane_pair(repo)

    def refuse_to_mint() -> uuid.UUID:
        raise AssertionError("a resume computed a second claim id")

    monkeypatch.setattr(uuid, "uuid4", refuse_to_mint)
    status = issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    assert status == 0
    assert capsys.readouterr().out == (
        f"worktree: {worktree}\n"
        f"branch: {_START_BRANCH}\n"
        f"CLAIMED issue #314: {claim_id}\n"
        "0 of 4 versioned files (0%); overlaps no other open claims\n"
    )
    assert len(store.fetch_state(worktree=Path("."), remote="origin").claims) == 1
    resolved = checkout.resolve_path_checkout(worktree)
    assert resolved is not None
    assert resolved.branch == _START_BRANCH


_REAL_VERSIONED_PATHS = checkout.versioned_paths


def test_start_refuses_to_rebuild_a_live_claim_whose_scope_the_trunk_no_longer_grounds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """START-22: the live claim's scope is measured against the
    fetched trunk before its gone worktree is built again, so a comma path
    the trunk has since deleted refuses with nothing built."""
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "versioned_paths", _REAL_VERSIONED_PATHS)
    (repo / "a,b.py").write_text("x\n")
    real_git(repo, "add", "a,b.py")
    real_git(repo, "commit", "-q", "-m", "comma path")
    push_repository_trunk(repo, "origin")
    _serve_start_board(monkeypatch, _start_item(complete_contract("Build it.", scope=["a,b.py"])))
    monkeypatch.chdir(repo)
    assert issue_claim.main(["--repo", REPOSITORY, "start", "314"]) == 0
    _remove_the_lane_pair(repo)
    real_git(repo, "rm", "-q", "a,b.py")
    real_git(repo, "commit", "-q", "-m", "comma path gone")
    push_repository_trunk(repo, "origin")
    capsys.readouterr()
    before = worktrees_and_branches(repo)

    status = issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    captured = capsys.readouterr()
    assert (status, captured.out, worktrees_and_branches(repo)) == (2, "", before)
    assert captured.err.startswith("ERROR: 'a,b.py' matches no versioned file")


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(_keep_the_lane_pair, id="worktree-standing"),
        pytest.param(_remove_the_lane_pair, id="worktree-gone"),
    ],
)
def test_start_resume_refuses_a_scope_that_differs_from_the_live_claim(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    arrange: Callable[[Path], None],
) -> None:
    """An explicit `--scope` on resume that disagrees
    with the live claim's own stored scope is refused rather than silently
    ignored, and with the worktree gone nothing is built again;
    the identical scope is accepted (covered by
    `test_start_resumes_an_existing_worktree_by_only_claiming`'s bare
    resume, which passes no `--scope` at all)."""
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)
    assert issue_claim.main(["--repo", REPOSITORY, "start", "314"]) == 0
    capsys.readouterr()
    arrange(repo)
    before = worktrees_and_branches(repo)

    status = issue_claim.main(["--repo", REPOSITORY, "start", "314", "--scope", "src/other.py"])

    captured = capsys.readouterr()
    assert (status, captured.out) == (2, "")
    assert captured.err == f"ERROR: {cmd_start._RESUME_SCOPE_MISMATCH}\n"
    assert worktrees_and_branches(repo) == before


def test_start_resumes_a_wide_claim_without_repeating_whole(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The stored claim's own `whole_reason` already
    justifies a wide scope once; resuming it must not re-demand `--whole`."""
    repo, _remote = real_repository_with_bare_remote(tmp_path)
    for name in ("a.py", "b.py", "c.py", "d.py"):
        (repo / name).write_text("x\n")
    real_git(repo, "add", *("a.py", "b.py", "c.py", "d.py"))
    real_git(repo, "commit", "-q", "-m", "initial")
    push_repository_trunk(repo, "origin")
    issue = board_issue(
        314,
        "Fresh Slug Title",
        complete_contract("Build it.", scope=["a.py", "b.py", "c.py", "d.py"]),
    )
    client = FakeForge(board_issues=(issue,))
    client.issue_references[314] = forge.ItemReference(
        forge.ItemState.OPEN, issue.title, issue.body
    )
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _patch_store_write(monkeypatch)
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
    redirect_toplevel(monkeypatch, repo)
    monkeypatch.chdir(repo)
    assert (
        issue_claim.main(["--repo", REPOSITORY, "start", "314", "--whole", "the whole thing"]) == 0
    )
    capsys.readouterr()

    status = issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    assert status == 0
    assert "CLAIMED issue #314" in capsys.readouterr().out


def test_start_resume_refuses_when_the_worktree_toplevel_read_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The width gate of a resumed claim never reads a failed toplevel read
    as "no untracked directory": `start` refuses with the toplevel sentence
    and prints no `CLAIMED` line."""
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)
    assert issue_claim.main(["--repo", REPOSITORY, "start", "314"]) == 0
    capsys.readouterr()
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    real_run_git = process.run_git

    def toplevel_read_exits_nonzero(
        arguments: list[str], *, directory: Path | None = None, **options: bool
    ) -> process.CapturedResult:
        if arguments == ["rev-parse", "--show-toplevel"] and directory == worktree:
            return process.CapturedResult(128, b"", b"fatal: not a work tree")
        return real_run_git(arguments, directory=directory, **options)

    monkeypatch.setattr(process, "run_git", toplevel_read_exits_nonzero)

    status = issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    captured = capsys.readouterr()
    assert (status, captured.out) == (2, "")
    assert captured.err == (
        "ERROR: this command reads the repository's body contract from .aco/board.toml "
        "and needs a checkout (a shallow one is enough): fatal: not a work tree\n"
    )


def test_start_mints_a_fresh_id_after_an_abandoned_release(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """An abandoned release frees the claim but
    never touches the worktree; the next `start` resumes that same worktree
    yet still mints a brand-new id, never reusing a terminal one a
    deterministic `start-314` id would have left behind."""
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)
    assert issue_claim.main(["--repo", REPOSITORY, "start", "314"]) == 0
    first_claim_id = _claimed_line_id(capsys.readouterr().out, "issue #314")
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME

    assert (
        issue_claim.main(
            ["--repo", REPOSITORY, "release", "314", "--abandoned", "stopped for the day"]
        )
        == 0
    )
    capsys.readouterr()

    assert issue_claim.main(["--repo", REPOSITORY, "start", "314"]) == 0

    second_claim_id = _claimed_line_id(capsys.readouterr().out, "issue #314")
    assert second_claim_id != first_claim_id
    assert worktree.exists()


def test_start_mints_a_fresh_id_after_a_merged_release_reopens_the_item(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A `--merged` release removes #72's own
    worktree and branch entirely; once the item reopens, `start` builds a
    fresh worktree and mints a brand-new id rather than failing before CAS
    on a terminal id a deterministic `start-72` would have left behind."""
    repo, _remote = real_repository_with_bare_remote(tmp_path)
    (repo / "base.txt").write_text("base\n")
    real_git(repo, "add", "base.txt")
    real_git(repo, "commit", "-q", "-m", "initial")
    push_repository_trunk(repo, "origin")
    issue = board_issue(72, "Cleanup", complete_contract("Build it.", scope=["src"]))
    client = FakeForge(board_issues=(issue,))
    client.issue_references[72] = forge.ItemReference(forge.ItemState.OPEN, issue.title, issue.body)
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _patch_store_write(monkeypatch)
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
    redirect_toplevel(monkeypatch, repo)
    monkeypatch.chdir(repo)
    assert issue_claim.main(["--repo", REPOSITORY, "start", "72"]) == 0
    first_claim_id = _claimed_line_id(capsys.readouterr().out, "issue #72")
    worktree = repo.parent / f"{repo.name}-worktrees" / _CLEANUP_WORKTREE_NAME

    (worktree / "feature.txt").write_text("feature\n")
    real_git(worktree, "add", "feature.txt")
    real_git(worktree, "commit", "-q", "-m", "feature work")
    real_git(
        repo,
        "merge",
        "-q",
        "--no-ff",
        "-m",
        "Merge feature",
        "-m",
        f"Work-Item: #{WORK_ITEM_ISSUE}",
        _CLEANUP_BRANCH,
    )
    merge_commit = real_git(repo, "rev-parse", "HEAD").stdout.strip()
    push_repository_trunk(repo, "origin")
    client.landings[12] = landing_pull_request(
        body=f"Work-Item: #{WORK_ITEM_ISSUE}\n\nCloses #{WORK_ITEM_ISSUE}",
        merged=True,
        head_ref_name=_CLEANUP_BRANCH,
        merge_commit=merge_commit,
    )
    client.closed_issues.add(WORK_ITEM_ISSUE)
    monkeypatch.setattr(board_read, "fetch_issue_reference", _LIVE_FETCH_ISSUE_REFERENCE)
    monkeypatch.setattr(checkout, "trunk_landings", _LIVE_TRUNK_LANDINGS)

    assert issue_claim.main(["--repo", REPOSITORY, "release", "72", "--merged", "12"]) == 0
    assert not worktree.exists()

    client.closed_issues.discard(WORK_ITEM_ISSUE)
    client.issue_references[72] = forge.ItemReference(forge.ItemState.OPEN, issue.title, issue.body)

    assert issue_claim.main(["--repo", REPOSITORY, "start", "72"]) == 0

    reopened_claim_id = _claimed_line_id(capsys.readouterr().out, "issue #72")
    assert reopened_claim_id != first_claim_id
    assert worktree.exists()


@pytest.mark.parametrize(
    ("closed", "message"),
    [
        pytest.param(True, "issue #314 is closed", id="closed"),
        pytest.param(False, "issue #314 does not exist here", id="missing"),
    ],
)
def test_start_refuses_a_closed_or_missing_item(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    closed: bool,
    message: str,
) -> None:
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)
    client = FakeForge()
    if closed:
        client.closed_issues.add(314)
    else:
        client.issue_references[314] = forge.ItemReference(forge.ItemState.MISSING, None, None)
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)

    assert issue_claim.main(["--repo", REPOSITORY, "start", "314"]) == 2

    assert capsys.readouterr().err == f"ERROR: {message}\n"
    assert not (repo.parent / f"{repo.name}-worktrees").exists()


def test_start_refuses_a_malformed_body_before_no_scope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A target
    whose `aco` block is malformed refuses by naming that defect --
    the same block-defect reader `claim` shares -- before `start`'s own
    claim delegation ever gets to name the less specific "item names no
    scope"."""
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)
    body = block_body(f'{MINIMAL_BLOCK_TOML}owner = "someone"\n')
    issue = board_issue(314, "Fresh Slug Title", body)
    client = FakeForge(board_issues=(issue,))
    client.issue_references[314] = forge.ItemReference(
        forge.ItemState.OPEN, issue.title, issue.body
    )
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)

    status = issue_claim.main(["--repo", REPOSITORY, "start", "314"])

    assert status == 2
    assert capsys.readouterr().err == (
        "ERROR: #314 body malformed: owner: unknown top-level key owner\n"
    )


def _state_ref_item_body(
    title: str,
    *,
    closed_at: str | None = None,
    kind: body.ItemKind = body.ItemKind.TASK,
    parent: int | None = None,
    labels: tuple[str, ...] = (),
    **block_fields: object,
) -> str:
    """A state-ref item of `kind` titled `title` carrying `labels`, open
    unless it was closed at `closed_at`, a child of `parent` when one is
    named, plus whichever further block fields (`scope`, `expectation`,
    `slice`) the scenario needs."""
    closure = {} if closed_at is None else {"state": "closed", "closed_at": closed_at}
    nesting = {} if parent is None else {"parent": items.format_item_id(parent)}
    data: dict[str, object] = {
        "version": 1,
        "now": "Ship it.",
        "next": "keiner",
        "done_when": "Merged.",
        "record": {
            "title": title,
            "state": "open",
            "kind": kind.value,
            "labels": list(labels),
            "blocked_by": [],
            "created_at": "2026-09-10T00:00:00Z",
            "updated_at": "2026-09-10T00:00:00Z",
            **closure,
            **nesting,
        },
        **block_fields,
    }
    return block_body(body.render_block(data).removesuffix("\n"), before="Prose.\n\n", after="")


def _real_state_ref_start_scenario(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, canonical_remote: str = "origin"
) -> tuple[Path, Path, protocol.ObjectId]:
    """A real bare-remote-backed, `storage = "state-ref"` repository
    with item #314 open, untitled scope, ready for
    `start` -- the state-ref counterpart of `_start_scenario`, real
    `refs/aco/state` and all (`_use_real_store`), since `_FakeStore` cannot
    see which directory a read ran against. A `canonical_remote` other than
    `origin` keeps an `origin` beside it on the same bare remote that never
    recorded its `HEAD`."""
    repo, remote, seeded = _real_state_ref_repository(
        monkeypatch,
        tmp_path,
        {314: _state_ref_item_body("Fresh Slug Title")},
        canonical_remote=canonical_remote,
    )
    return repo, remote, seeded[314]


def _real_state_ref_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    item_bodies: Mapping[int, str],
    *,
    canonical_remote: str = "origin",
) -> tuple[Path, Path, dict[int, protocol.ObjectId]]:
    """A real bare-remote-backed, `storage = "state-ref"` repository, its
    real `refs/aco/state` seeded with one item per `item_bodies` entry,
    the run standing in it; returns each seeded item's blob oid."""
    _use_real_store(monkeypatch)
    repo, remote = real_repository_with_bare_remote(tmp_path, remote_name=canonical_remote)
    write_repository_config(
        repo, f'storage = "state-ref"\ncanonical_remote = "{canonical_remote}"\n'
    )
    real_git(repo, "add", workboard.CONFIG_PATH.as_posix())
    real_git(repo, "commit", "-q", "-m", "pin state-ref storage")
    push_repository_trunk(repo, canonical_remote)
    if canonical_remote != "origin":
        real_git(repo, "remote", "add", "origin", str(remote))
    store.bootstrap(worktree=repo, remote=str(remote))
    seeded = {
        number: _seed_state_ref_item(repo, remote, number, content)
        for number, content in item_bodies.items()
    }
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
    redirect_toplevel(monkeypatch, repo)
    monkeypatch.chdir(repo)
    return repo, remote, seeded


def _seed_state_ref_item(repo: Path, remote: Path, number: int, content: str) -> protocol.ObjectId:
    item_id = items.format_item_id(number)
    seeded_oid = store.hash_blob(repo, content.encode())
    store.commit_transition(
        observed=fresh_observation(repo, remote),
        subject=store.TransitionSubject(f"seed item {item_id}"),
        intent=protocol.ItemWriteIntent(
            item_id=item_id, expected=None, new_oid=seeded_oid, operation_id=f"item-op-{number}"
        ),
    )
    return seeded_oid


@pytest.mark.parametrize(
    ("command", "checkouts_agree"),
    [(["status"], True), (["board", "--json"], True), (["next", "--json"], False)],
    ids=["status", "board", "next"],
)
def test_state_ref_reads_answer_from_a_subdirectory_as_from_the_checkout_root(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    command: list[str],
    checkouts_agree: bool,
) -> None:
    """A read run from `src/` of a checkout, or of a linked
    worktree, answers exactly as from that checkout's root -- git lists and
    archives a tree object relative to its own working directory, so the
    state tree must be read from the checkout root, never the process cwd.
    The main checkout and a linked worktree answer alike, except `next`,
    which advises `start` from the one and `claim` from the other."""
    repo, _remote, _seeded_oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    linked = tmp_path / "linked"
    real_git(repo, "worktree", "add", "-q", "-b", "lane", str(linked))
    readings = ((repo, repo), (repo, repo / "src"), (linked, linked), (linked, linked / "src"))
    answers: list[tuple[int, str]] = []
    for toplevel, directory in readings:
        directory.mkdir(exist_ok=True)
        redirect_toplevel(monkeypatch, toplevel)
        monkeypatch.chdir(directory)
        status = issue_claim.main(command)
        answers.append((status, capsys.readouterr().out))

    main_root, main_subdirectory, linked_root, linked_subdirectory = answers
    assert (main_root[0], linked_root[0]) == (0, 0)
    assert (main_subdirectory, linked_subdirectory) == (main_root, linked_root)
    assert (main_root == linked_root) is checkouts_agree


_UNREADABLE_NUMBERS = (
    pytest.param("²", id="superscript-digit"),
    pytest.param("٧٢", id="non-ascii-digits"),
    pytest.param("7" * (protocol.MAXIMUM_ISSUE_NUMBER_DIGITS + 1), id="past-the-bound"),
    pytest.param("7" * 5000, id="past-the-int-digit-limit"),
)


@pytest.mark.parametrize("number", _UNREADABLE_NUMBERS)
@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_status_refuses_a_state_ref_claim_key_whose_issue_number_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    number: str,
    as_json: bool,
) -> None:
    """Spec: CLAIM-64, STAT-18. A hand-corrupted `claims/issue-<number>.toml` beside a
    valid `issue-72` stops the read with the named refusal, never a traceback
    and never a second claim on issue 72."""
    repo, remote, _seeded_oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    state_tip = _state_ref_tip(repo, remote)
    claim_content = "\n".join(
        [
            'claim_id = "a1"',
            'agent = "Ada"',
            'role = "builder"',
            f'base = "{"c" * 40}"',
            'branch = "claude/issue-72-cut"',
            'scope = ["src/x.py"]',
            f'opened_commit = "{state_tip}"',
            "",
        ]
    )
    claim_blob = blob(repo, claim_content.encode())
    claims_tree = raw_tree(
        repo,
        [
            ("100644", "blob", claim_blob, "issue-72.toml"),
            ("100644", "blob", claim_blob, f"issue-{number}.toml"),
        ],
    )
    push_raw_state_tree(
        remote,
        repo,
        [
            ("100644", "blob", blob(repo, b"version = 2\n"), "schema.toml"),
            ("040000", "tree", claims_tree, store.CLAIMS_DIRECTORY),
        ],
        successor_of=state_tip,
    )
    refusal = f"claim key has a malformed issue number: 'issue-{number}'"

    status = issue_claim.main(["status", *(["--json"] if as_json else [])])

    assert status == 2
    captured = capsys.readouterr()
    if as_json:
        payload = json.loads(captured.out)
        assert (payload["ok"], payload["reason"], payload["message"]) == (
            False,
            "unavailable",
            refusal,
        )
    else:
        assert captured.err == f"ERROR: {refusal}\n"


@pytest.mark.parametrize("number", [*_UNREADABLE_NUMBERS, pytest.param("docs/x", id="lane")])
@pytest.mark.parametrize("command", [["board", "--json"], ["next"], ["next", "--json"]])
def test_board_and_next_read_an_unreadable_lifecycle_trailer_item_like_a_lane(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    number: str,
    command: list[str],
) -> None:
    """Spec: BOARD-56. A claim commit on `refs/aco/state` whose `item:`
    trailer is no ASCII number of at most 18 digits neither stops the read nor
    counts as unparsed."""
    repo, remote, _seeded_oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    store.commit_transition(
        observed=fresh_observation(repo, remote),
        subject=store.ClaimTransitionSubject("claim a corrupted item", item=number),
        intent=claim_intent(),
    )
    capsys.readouterr()

    status = issue_claim.main(command)

    assert status == 0
    output = capsys.readouterr().out
    if command == ["board", "--json"]:
        assert json.loads(output)["measurements"]["unparsed"] == 0


@pytest.mark.parametrize(
    "number",
    [
        pytest.param("٧٢", id="non-ascii-digits"),
        pytest.param("7" * (protocol.MAXIMUM_ISSUE_NUMBER_DIGITS + 1), id="past-the-bound"),
        pytest.param("docs/x", id="lane"),
    ],
)
def test_board_lends_no_closed_item_size_to_an_unreadable_trailer_item(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    number: str,
) -> None:
    """Spec: BOARD-56. A completed lane whose `item:` trailer reads as no
    ASCII number of at most 18 digits joins no closed item's size, though
    closed items 72 and `7` x 19 carry a size it would otherwise join --
    `٧٢` reads as 72 under `str.isdigit`, and the 19 digits as an item
    past the bound."""
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=_TOP_AND_BLOCKED[1:2])
    for lookalike in (72, int("7" * (protocol.MAXIMUM_ISSUE_NUMBER_DIGITS + 1))):
        client.issue_references[lookalike] = forge.ItemReference(
            forge.ItemState.CLOSED, body=complete_contract("Closed.", size="M")
        )
    _patch_store_write(monkeypatch, lane_events=(_lane(number, 10, 4),))

    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 0

    assert json.loads(capsys.readouterr().out)["measurements"]["classes"] == []


def test_start_under_state_ref_claims_the_worktree_it_builds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """End to end under `storage = "state-ref"`
    with a real bare remote and a real `refs/aco/state`: the claim `start`
    prints is the one the worktree it built reads back. That the claim's
    checks read the item as it stands after the fetch, never the snapshot
    `start`'s first read took, is
    `test_start_under_state_ref_checks_the_item_as_it_stands_after_the_fetch`.
    The claim is written from the built worktree, so its lineage stamp names
    the claim's own commit (CAS-09)."""
    repo, _remote, _seeded_oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    item_id = items.format_item_id(314)

    status = issue_claim.main(["start", "314", "--scope", "src/x.py"])

    assert status == 0
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    state_tip = real_git(repo, "ls-remote", "origin", store.STATE_REF).stdout.split()[0]
    assert lineage_observation(worktree)[0] == state_tip
    claim_id = _claimed_line_id(capsys.readouterr().out, f"issue {item_id}")
    live = store.fetch_state(worktree=worktree, remote="origin").claims
    claim = live[protocol.claim_key(protocol.IssueIdentity(314), _START_BRANCH)]
    assert claim.claim_id == claim_id
    assert claim.scope == ("src/x.py",)


def _lane_on_a_state_ref_board_with_registries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, trunk_configuration_tail: str
) -> None:
    """A real state-ref board whose trunk tracks `scripts/registry.txt` and
    `src/x.py` and names both registries lane-shared, and a lane `start`
    built on it for item #314; the trunk's configuration then moves on to
    `trunk_configuration_tail` -- as a newer aco's landing would -- while the
    lane's own copy stays as it was cut. The run stands in the lane."""
    repo, _remote, _oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    for registry in ("scripts/registry.txt", "src/x.py"):
        (repo / registry).parent.mkdir(exist_ok=True)
        (repo / registry).write_text("")
    configuration = repo / workboard.CONFIG_PATH
    pinned = configuration.read_text()
    configuration.write_text(f'{pinned}lane_shared = ["scripts/registry.txt", "src/x.py"]\n')
    real_git(repo, "add", "scripts", "src", workboard.CONFIG_PATH.as_posix())
    real_git(repo, "commit", "-q", "-m", "registries")
    push_repository_trunk(repo, "origin")
    assert issue_claim.main(["start", "314", "--scope", "src/x.py"]) == 0
    configuration.write_text(f"{pinned}{trunk_configuration_tail}")
    real_git(repo, "commit", "-q", "-am", "trunk configuration")
    push_repository_trunk(repo, "origin")
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    redirect_toplevel(monkeypatch, worktree)
    monkeypatch.chdir(worktree)
    monkeypatch.setattr(checkout, "file_at_revision", _LIVE_FILE_AT_REVISION)
    monkeypatch.setattr(checkout, "versioned_paths", _REAL_VERSIONED_PATHS)


def _trunk_defect(sentence: str) -> str:
    return f"board configuration refs/remotes/origin/main:.aco/board.toml {sentence}"


@pytest.mark.parametrize(
    ("trunk_configuration_tail", "shown", "entries", "defect", "path_answer"),
    [
        pytest.param(
            'lane_shared = ["scripts/registry.txt", "src"]\n',
            ["lane-shared: scripts/registry.txt, src (names no file)"],
            [
                {"path": "scripts/registry.txt", "names_a_file": True},
                {"path": "src", "names_a_file": False},
            ],
            None,
            "LANE-SHARED",
            id="a-file-and-a-directory",
        ),
        pytest.param("", [], [], None, "UNCLAIMED", id="none-named"),
        pytest.param(
            'newer_aco_key = true\nlane_shared = ["scripts/registry.txt"]\n',
            [
                "lane-shared: unavailable "
                f"({_trunk_defect('has unknown top-level key newer_aco_key')})"
            ],
            None,
            _trunk_defect("has unknown top-level key newer_aco_key"),
            "UNCLAIMED",
            id="a-newer-aco-key",
        ),
        pytest.param(
            'lane_shared = "scripts/registry.txt"\n',
            [
                "lane-shared: unavailable "
                f"({_trunk_defect('lane_shared must be a list of unique repository file paths')})"
            ],
            None,
            _trunk_defect("lane_shared must be a list of unique repository file paths"),
            "UNCLAIMED",
            id="an-invalid-value",
        ),
    ],
)
def test_status_and_brief_show_the_trunks_lane_shared_files_or_its_defect(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    trunk_configuration_tail: str,
    shown: list[str],
    entries: list[dict[str, object]] | None,
    defect: str | None,
    path_answer: str,
) -> None:
    """Spec: STAT-19, STAT-20, STAT-21, STAT-22, STAT-23. On a real
    state-ref board: `status`, `status
    --json`, `brief` and `brief --json` name the trunk's lane-shared entries,
    an entry naming no tracked file marked so; `status --path` names a
    lane-shared file `LANE-SHARED`. A trunk configuration this aco cannot
    read costs only that answer -- the claims still show, the defect named
    in text and `--json` alike, and no file reads as lane-shared."""
    _lane_on_a_state_ref_board_with_registries(monkeypatch, tmp_path, trunk_configuration_tail)
    item = items.format_item_id(314)
    registry = "scripts/registry.txt"
    capsys.readouterr()
    exits: list[int] = []

    def run(*argv: str) -> list[str]:
        exits.append(issue_claim.main(list(argv)))
        return capsys.readouterr().out.splitlines()

    status_lines = run("status")
    status_json = json.loads(run("status", "--json")[0])
    path_lines = run("status", "--path", registry)
    path_json = json.loads(run("status", "--path", registry, "--json")[0])
    brief_lines = run("brief", item)
    brief_claim = json.loads(run("brief", item, "--json")[0])["claim"]

    lane_shared = {"lane_shared": entries, "lane_shared_unavailable": defect}
    assert exits == [0] * 6
    assert (status_lines[0].split()[0], _lane_shared_lines(status_lines)) == ("CLAIMED", shown)
    assert (status_json["reason"], _lane_shared_fields(status_json)) == ("claimed", lane_shared)
    assert path_lines == [f"{path_answer} {registry}", *(shown if defect else [])]
    assert _lane_shared_fields(path_json) == lane_shared
    assert _lane_shared_lines(brief_lines) == shown
    assert (brief_claim["branch"], _lane_shared_fields(brief_claim)) == (
        _START_BRANCH,
        lane_shared,
    )


def _lane_shared_lines(output: list[str]) -> list[str]:
    return [line.strip() for line in output if line.strip().startswith("lane-shared:")]


def _lane_shared_fields(payload: Mapping[str, object]) -> dict[str, object]:
    return {key: payload[key] for key in ("lane_shared", "lane_shared_unavailable")}


def _relative_add(_worktree: Path) -> tuple[str, ...]:
    return ("--add", "src/y.py")


def _absolute_add(worktree: Path) -> tuple[str, ...]:
    return ("--add", str(worktree / "src" / "y.py"))


def _relative_drop_beside_an_absolute_add(worktree: Path) -> tuple[str, ...]:
    return ("--add", str(worktree / "src" / "y.py"), "--drop", "src/x.py")


@pytest.mark.parametrize(
    ("flags", "scope"),
    [
        pytest.param(_relative_add, ("src/x.py", "src/y.py"), id="relative-add"),
        pytest.param(_absolute_add, ("src/x.py", "src/y.py"), id="absolute-add"),
        pytest.param(_relative_drop_beside_an_absolute_add, ("src/y.py",), id="relative-drop"),
    ],
)
def test_rescope_under_state_ref_moves_the_claim_and_the_item_body_scope_together(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    flags: Callable[[Path], tuple[str, ...]],
    scope: tuple[str, ...],
) -> None:
    """RESC-22 on a real state-ref board: one rescope, run from a
    subdirectory of the claimed worktree, writes the live claim and item
    #314's own body scope to the same list -- the body write and the claim
    transition both land on the one `refs/aco/state`."""
    repo, _remote, _seeded_oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    assert issue_claim.main(["start", "314", "--scope", "src/x.py"]) == 0
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    (worktree / "src").mkdir()
    redirect_toplevel(monkeypatch, worktree)
    monkeypatch.chdir(worktree / "src")
    capsys.readouterr()

    status = issue_claim.main(["rescope", "314", *flags(worktree)])

    assert (status, capsys.readouterr().err) == (0, "")
    live = store.fetch_state(worktree=worktree, remote="origin")
    claim = live.claims[protocol.claim_key(protocol.IssueIdentity(314), _START_BRANCH)]
    tip = live.tip
    assert tip is not None
    stored = store.read_item_files(worktree, tip)[f"{items.format_item_id(314)}.md"]
    item_body = body.parse_body(stored.decode(), storage=body.Storage.STATE_REF)
    assert (claim.scope, item_body.scope) == (scope, scope)


def _into_another_repository(worktree: Path) -> Path:
    other = worktree.parent / "other"
    real_git(worktree.parent, "init", "-q", str(other))
    return other / "f.md"


def _into_the_primary_checkout(worktree: Path) -> Path:
    return worktree.parent.parent / worktree.parent.name.removesuffix("-worktrees") / "README.md"


@pytest.mark.parametrize(
    "target",
    [
        pytest.param(_into_another_repository, id="another-repository"),
        pytest.param(_into_the_primary_checkout, id="primary-checkout"),
    ],
)
def test_rescope_refuses_a_relative_entry_that_climbs_out_of_the_run_checkout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    target: Callable[[Path], Path],
) -> None:
    """RESC-05: a relative entry whose `..` leaves the checkout the command
    runs in refuses with the entry as typed, before the checkout it lands
    in is ever read, and writes nothing."""
    repo, _remote, _seeded_oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    assert issue_claim.main(["start", "314", "--scope", "src/x.py"]) == 0
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    redirect_toplevel(monkeypatch, worktree)
    monkeypatch.chdir(worktree)
    entry = os.path.relpath(target(worktree), worktree)
    state_before = store.fetch_state(worktree=worktree, remote="origin").tip
    capsys.readouterr()

    status = issue_claim.main(["rescope", "314", "--add", entry])

    assert (status, capsys.readouterr().err) == (
        2,
        f"ERROR: --add path {entry!r} is outside the resolved checkout {worktree}\n",
    )
    assert store.fetch_state(worktree=worktree, remote="origin").tip == state_before


def _relative_outside_every_repository(cwd: Path) -> tuple[tuple[str, ...], str]:
    return (
        ("--add", "src/new.py"),
        f"--add path 'src/new.py' is relative and {cwd} is not in a repository; "
        "pass it as an absolute path",
    )


def _absolute_outside_every_repository(cwd: Path) -> tuple[tuple[str, ...], str]:
    return (
        ("--drop", str(cwd / "new.py")),
        f"--drop path '{cwd / 'new.py'}' is not in a repository",
    )


def _no_path_outside_every_repository(_cwd: Path) -> tuple[tuple[str, ...], str]:
    return ((), "not in a repository")


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(_relative_outside_every_repository, id="relative-entry"),
        pytest.param(_absolute_outside_every_repository, id="absolute-entry"),
        pytest.param(_no_path_outside_every_repository, id="no-entry"),
    ],
)
def test_rescope_outside_every_repository_names_the_entry_that_located_no_checkout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    scenario: Callable[[Path], tuple[tuple[str, ...], str]],
) -> None:
    """RESC-01, RESC-18: outside every repository a relative entry has no
    checkout to be read against and an absolute one locates none; each
    refusal names the entry, and the cwd fallback keeps RESC-26's sentence."""
    monkeypatch.chdir(tmp_path)
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
    flags, reason = scenario(tmp_path)

    status = issue_claim.main(["rescope", "72", *flags])

    assert (status, capsys.readouterr().err) == (2, f"ERROR: {reason}\n")


_SEAM_FAILURE = "fatal: not a git repository"
_PUSH_TIMED_OUT = "git timed out while reading the claim state store"


@pytest.mark.parametrize(
    ("push_answer", "lands", "failing_seam", "reported", "worktree_stood"),
    [
        pytest.param(
            None,
            True,
            "_write_lineage_stamp",
            _SEAM_FAILURE,
            False,
            id="lineage-stamp-fails-after-the-push",
        ),
        pytest.param(
            protocol.PushRejectedError("fatal: the remote end hung up unexpectedly"),
            True,
            "fetch_state",
            _SEAM_FAILURE,
            False,
            id="answer-lost-and-its-search-fails",
        ),
        pytest.param(
            protocol.ClaimError(_PUSH_TIMED_OUT),
            True,
            None,
            _PUSH_TIMED_OUT,
            False,
            id="push-times-out-after-landing",
        ),
        pytest.param(
            protocol.ClaimError(_PUSH_TIMED_OUT),
            False,
            None,
            _PUSH_TIMED_OUT,
            False,
            id="push-times-out-before-the-remote-records-it",
        ),
        pytest.param(
            protocol.ClaimError(_PUSH_TIMED_OUT),
            True,
            None,
            _PUSH_TIMED_OUT,
            True,
            id="answer-lost-in-a-worktree-that-already-stood",
        ),
    ],
)
def test_start_keeps_its_worktree_once_the_claims_push_was_sent_and_a_rerun_resumes_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    push_answer: protocol.ClaimError | None,
    lands: bool,
    failing_seam: str | None,
    reported: str,
    worktree_stood: bool,
) -> None:
    """START-25: once the
    claim's push was sent and the store cannot tell whether it was written
    -- its lineage stamp, the search for a push whose answer was lost, a
    push that timed out before or after it landed -- the worktree and branch
    stay, whether `start` built them or found them standing (START-11), the
    outcome is said to be uncertain, and the next `start` resumes whichever
    outcome it finds."""
    repo, _remote, _seeded_oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    if worktree_stood:
        real_git(repo, "worktree", "add", "-q", "-b", _START_BRANCH, str(worktree))
    landed: list[protocol.ObjectId] = []
    real_push = store.GitPushTransport.push

    def push_and_note(
        transport: store.GitPushTransport,
        *,
        worktree: Path,
        remote: str,
        ref: str,
        new_oid: protocol.ObjectId,
    ) -> None:
        if lands:
            real_push(transport, worktree=worktree, remote=remote, ref=ref, new_oid=new_oid)
            landed.append(new_oid)
        if push_answer is not None:
            raise push_answer

    with monkeypatch.context() as failing:
        failing.setattr(store.GitPushTransport, "push", push_and_note)
        if failing_seam is not None:
            real_seam = getattr(store, failing_seam)

            def seam_fails_once_landed(*arguments: object, **keywords: object) -> object:
                if landed:
                    raise protocol.ClaimError(_SEAM_FAILURE)
                return real_seam(*arguments, **keywords)

            failing.setattr(store, failing_seam, seam_fails_once_landed)

        status = issue_claim.main(["start", "314", "--scope", "src/x.py"])

    err = capsys.readouterr().err
    assert status == 2
    assert err.startswith(f"ERROR: {reported}")
    assert err.endswith(
        f"\nthe claim's push was sent, its outcome unknown; worktree {worktree} and "
        f"branch '{_START_BRANCH}' kept; run start again to resume it\n"
    )
    claim_key = protocol.claim_key(protocol.IssueIdentity(314), _START_BRANCH)
    assert (claim_key in store.fetch_state(worktree=repo, remote="origin").claims) is lands
    kept = checkout.resolve_path_checkout(worktree)
    assert kept is not None
    assert (kept.kind, kept.branch) == (checkout.CheckoutKind.LINKED_WORKTREE, _START_BRANCH)

    assert issue_claim.main(["start", "314", "--scope", "src/x.py"]) == 0
    assert claim_key in store.fetch_state(worktree=repo, remote="origin").claims


def _a_rival_claim_lands_under_the_push(
    monkeypatch: pytest.MonkeyPatch, repo: Path, bare_remote: Path
) -> None:
    real_push = store.GitPushTransport.push
    rival_pending = [True]

    def rival_lands_first(
        transport: store.GitPushTransport,
        *,
        worktree: Path,
        remote: str,
        ref: str,
        new_oid: protocol.ObjectId,
    ) -> None:
        if rival_pending:
            rival_pending.clear()
            _land_real_claim(repo, bare_remote, issue=314, claim_id="rival-314")
        real_push(transport, worktree=worktree, remote=remote, ref=ref, new_oid=new_oid)

    monkeypatch.setattr(store.GitPushTransport, "push", rival_lands_first)


def _the_store_rejects_every_push(
    monkeypatch: pytest.MonkeyPatch, _repo: Path, _bare_remote: Path
) -> None:
    def rejected(
        _transport: store.GitPushTransport,
        *,
        worktree: Path,
        remote: str,
        ref: str,
        new_oid: protocol.ObjectId,
    ) -> None:
        raise protocol.PushRejectedError("! [remote rejected] (failed to lock)")

    monkeypatch.setattr(store.GitPushTransport, "push", rejected)


@pytest.mark.parametrize(
    ("arrange", "refusal"),
    [
        pytest.param(
            _a_rival_claim_lands_under_the_push,
            "issue {item} is claimed by Codex Sol (builder) on issue {item} ",
            id="rival-claim-lands",
        ),
        pytest.param(
            _the_store_rejects_every_push,
            f"{store.STATE_REF} rejected ",
            id="store-rejects-every-push",
        ),
    ],
)
@pytest.mark.parametrize(
    "worktree_stood",
    [pytest.param(False, id="built"), pytest.param(True, id="found-standing")],
)
def test_start_removes_only_its_own_build_when_the_store_refuses_its_sent_push_for_certain(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    arrange: Callable[[pytest.MonkeyPatch, Path, Path], None],
    refusal: str,
    worktree_stood: bool,
) -> None:
    """START-18, CAS-57: the claim's push was sent and
    rejected, and the store's re-read found nothing of it written -- a rival
    claim landed first, or the store rejected every retry -- so the refusal
    is certain: the worktree and branch `start` built go, one it found
    standing stays (START-11), and a rival's conflict names the item the way
    the board's storage does."""
    repo, bare_remote, _seeded_oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    if worktree_stood:
        real_git(repo, "worktree", "add", "-q", "-b", _START_BRANCH, str(worktree))
    arrange(monkeypatch, repo, bare_remote)

    status = issue_claim.main(["start", "314", "--scope", "src/x.py"])

    err = capsys.readouterr().err
    assert status == 2
    assert err.startswith(f"ERROR: {refusal.format(item=items.format_item_id(314))}")
    removal = _REMOVED_BOTH.format(worktree=worktree, branch=_START_BRANCH)
    assert (removal in err) is not worktree_stood
    assert "outcome unknown" not in err
    assert worktree.exists() is worktree_stood
    assert (_START_BRANCH in real_git(repo, "branch", "--list").stdout) is worktree_stood
    live = store.fetch_state(worktree=repo, remote="origin").claims.values()
    assert _START_BRANCH not in {claim.branch for claim in live}


def _start_in_main_checkout(
    _monkeypatch: pytest.MonkeyPatch, _repo: Path, _tmp_path: Path
) -> list[str]:
    return ["start", "314", "--scope", "src/x.py"]


def _claim_in_lane_worktree(
    monkeypatch: pytest.MonkeyPatch, repo: Path, tmp_path: Path
) -> list[str]:
    worktree = tmp_path / "lane"
    real_git(repo, "worktree", "add", "-q", "-b", "codex/issue-314-lane", str(worktree))
    redirect_toplevel(monkeypatch, worktree)
    monkeypatch.chdir(worktree)
    return ["claim", "314", "--scope", "src/x.py"]


def _close_real_item(
    repo: Path, remote: Path, *, issue: int, open_oid: protocol.ObjectId
) -> protocol.ObjectId:
    """Closes item `issue` on the real ref, as `item close` writes it."""
    item_id = items.format_item_id(issue)
    closed = _state_ref_item_body("Fresh Slug Title", closed_at="2026-09-11T00:00:00Z")
    closed_oid = store.hash_blob(repo, closed.encode())
    store.commit_transition(
        observed=fresh_observation(repo, remote),
        subject=store.TransitionSubject(f"write item {item_id}"),
        intent=protocol.ItemCloseIntent(
            protocol.ItemWriteIntent(
                item_id=item_id,
                expected=open_oid,
                new_oid=closed_oid,
                operation_id=f"close-op-{issue}",
            ),
            protocol.IssueIdentity(issue),
        ),
    )
    return closed_oid


def _close_under_the_claims_push(
    monkeypatch: pytest.MonkeyPatch, close: Callable[[], object]
) -> None:
    """The close lands after the claim's write read the ref, so its first
    push is rejected and only the retry sees the closed item."""
    real_push = store.GitPushTransport.push
    close_pending = [True]

    def close_lands_first(
        transport: store.GitPushTransport,
        *,
        worktree: Path,
        remote: str,
        ref: str,
        new_oid: protocol.ObjectId,
    ) -> None:
        if close_pending:
            close_pending.clear()
            close()
        real_push(transport, worktree=worktree, remote=remote, ref=ref, new_oid=new_oid)

    monkeypatch.setattr(store.GitPushTransport, "push", close_lands_first)


def _close_after_starts_build(monkeypatch: pytest.MonkeyPatch, close: Callable[[], object]) -> None:
    """The close lands while `start` builds, before the claim's write reads
    the ref from the new worktree, so no push is ever sent."""
    real_build = checkout.create_linked_worktree

    def build_then_close(
        path: Path, *, branch: str, start_point: str, directory: Path | None = None
    ) -> None:
        real_build(path, branch=branch, start_point=start_point, directory=directory)
        close()

    monkeypatch.setattr(checkout, "create_linked_worktree", build_then_close)


@pytest.mark.parametrize(
    ("arrange", "close_at", "build_line"),
    [
        pytest.param(
            _start_in_main_checkout,
            _close_under_the_claims_push,
            _REMOVED_BOTH,
            id="start-close-under-its-push",
        ),
        pytest.param(
            _start_in_main_checkout,
            _close_after_starts_build,
            _REMOVED_BOTH,
            id="start-close-before-its-push",
        ),
        pytest.param(
            _claim_in_lane_worktree,
            _close_under_the_claims_push,
            None,
            id="claim-close-under-its-push",
        ),
    ],
)
def test_a_claim_whose_item_closes_after_its_checks_refuses_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    arrange: Callable[[pytest.MonkeyPatch, Path, Path], list[str]],
    close_at: Callable[[pytest.MonkeyPatch, Callable[[], object]], None],
    build_line: str | None,
) -> None:
    """The item is closed after the claim's checks judged
    it open; the claim's write finds the item's blob no longer the one
    checked and refuses with CAS-20's sentence -- no live claim ever stands
    on the closed item (CLM-31, START-27). The refusal is certain, so
    `start` removes its build whether or not the claim's push was sent
    (START-18); `claim` builds nothing."""
    repo, bare_remote, open_oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    argv = arrange(monkeypatch, repo, tmp_path)
    closed_oids: list[protocol.ObjectId] = []
    close_at(
        monkeypatch,
        lambda: closed_oids.append(
            _close_real_item(repo, bare_remote, issue=314, open_oid=open_oid)
        ),
    )

    status = issue_claim.main(argv)

    [closed_oid] = closed_oids
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    build_lines = (
        [] if build_line is None else [build_line.format(worktree=worktree, branch=_START_BRANCH)]
    )
    assert status == 2
    assert capsys.readouterr().err.splitlines() == [
        f"ERROR: item '{items.format_item_id(314)}' was written since it was read "
        f"(expected {open_oid}, found '{closed_oid}'); re-read and retry",
        *build_lines,
    ]
    assert not worktree.exists()
    assert _START_BRANCH not in real_git(repo, "branch", "--list").stdout
    refetched = store.fetch_state(worktree=repo, remote="origin")
    assert not refetched.claims
    assert refetched.items[items.format_item_id(314)] == closed_oid


def test_a_github_claim_lands_though_a_stale_ledger_item_changes_under_its_rejected_push(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CAS-60: under `github` the forge holds the item's
    state, so an `items/` entry the ledger still carries pins nothing -- its
    close rejects the claim's first push and the retry lands the claim."""
    _use_real_store(monkeypatch)
    repo, bare_remote = real_repository_with_bare_remote(tmp_path)
    (repo / "base.txt").write_text("base\n")
    real_git(repo, "add", "base.txt")
    real_git(repo, "commit", "-q", "-m", "initial")
    push_repository_trunk(repo, "origin")
    store.bootstrap(worktree=repo, remote=str(bare_remote))
    open_oid = _land_real_item(repo, bare_remote, issue=314, content=b"open\n")
    _serve_start_board(monkeypatch, _start_item())
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
    argv = _claim_in_lane_worktree(monkeypatch, repo, tmp_path)
    _close_under_the_claims_push(
        monkeypatch, lambda: _close_real_item(repo, bare_remote, issue=314, open_oid=open_oid)
    )

    assert issue_claim.main(["--repo", REPOSITORY, *argv]) == 0

    refetched = store.fetch_state(worktree=repo, remote="origin")
    assert refetched.items[items.format_item_id(314)] != open_oid
    assert [claim.identity for claim in refetched.claims.values()] == [protocol.IssueIdentity(314)]


@pytest.mark.parametrize("canonical_remote", ["origin", "hub"])
def test_start_observes_the_state_ref_afresh_and_its_default_branch_after_the_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, canonical_remote: str
) -> None:
    """CAS-55: the claim's checks observe the state ref again
    once the trunk fetch is done, while the canonical remote the run
    already read stays held -- one read of it per directory `start` works
    in. The default branch the built worktree is judged against is read
    after that fetch, never one held from before it, since a fetch may
    record or move the `HEAD` it names. Both are the
    canonical remote's: a `hub` starts from its own recorded `HEAD` beside
    an `origin` that never recorded one."""
    toplevel, _remote, _seeded_oid = _real_state_ref_start_scenario(
        monkeypatch, tmp_path, canonical_remote=canonical_remote
    )
    remote_url, recorded_default_branch = checkout.remote_url, checkout.recorded_default_branch
    fetch_remote = checkout.fetch_remote
    reads: list[tuple[str, str, Path | None]] = []

    def counting_remote_url(remote: str, *, directory: Path | None = None) -> str:
        reads.append(("remote url", remote, directory))
        return remote_url(remote, directory=directory)

    def counting_recorded_default_branch(
        remote: str, *, directory: Path | None = None
    ) -> str | None:
        reads.append(("default branch", remote, directory))
        return recorded_default_branch(remote, directory=directory)

    def noted_fetch_remote(remote: str, *, directory: Path) -> None:
        reads.append(("fetch", remote, directory))
        fetch_remote(remote, directory=directory)

    monkeypatch.setattr(checkout, "remote_url", counting_remote_url)
    monkeypatch.setattr(checkout, "recorded_default_branch", counting_recorded_default_branch)
    monkeypatch.setattr(checkout, "fetch_remote", noted_fetch_remote)

    assert issue_claim.main(["start", "314", "--scope", "src/x.py"]) == 0
    assert {(kind, remote) for kind, remote, _directory in reads} == {
        ("remote url", canonical_remote),
        ("default branch", canonical_remote),
        ("fetch", canonical_remote),
    }
    remote_url_reads = [read for read in reads if read[0] == "remote url"]
    assert len(remote_url_reads) == len(set(remote_url_reads))
    after_the_fetch = reads[reads.index(("fetch", canonical_remote, toplevel)) + 1 :]
    assert ("default branch", canonical_remote, toplevel) in after_the_fetch


def test_start_under_state_ref_checks_the_item_as_it_stands_after_the_fetch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Item #314 gains a `scope` after `start`'s
    item-existence read but while it fetches the trunk, exactly the window a
    caller-checkout-cached forge cannot see. The claim's checks read a fresh
    forge once the fetch is done and refuse the now-mismatched `--scope`; a
    forge reused from the first read would still see no `scope` at all and
    wrongly let the claim through."""
    repo, remote, seeded_oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    item_id = items.format_item_id(314)
    real_fetch_remote = checkout.fetch_remote

    def fetch_trunk_then_advance_item(remote: str, *, directory: Path) -> None:
        real_fetch_remote(remote, directory=directory)
        advanced = _state_ref_item_body("Fresh Slug Title", scope=["mismatched/path.py"]).encode()
        advanced_oid = store.hash_blob(repo, advanced)
        store.commit_transition(
            observed=fresh_observation(repo, remote_path),
            subject=store.TransitionSubject(f"advance item {item_id}"),
            intent=protocol.ItemWriteIntent(
                item_id=item_id,
                expected=seeded_oid,
                new_oid=advanced_oid,
                operation_id="item-op-314-race",
            ),
        )

    remote_path = remote
    monkeypatch.setattr(checkout, "fetch_remote", fetch_trunk_then_advance_item)

    status = issue_claim.main(["start", "314", "--scope", "src/x.py"])

    assert status == 2
    assert capsys.readouterr().err == f"ERROR: {cmd_claim._CLAIM_SCOPE_MISMATCH}\n"
    live = store.fetch_state(worktree=repo, remote="origin").claims
    assert protocol.claim_key(protocol.IssueIdentity(314), _START_BRANCH) not in live


def test_claim_accepts_an_item_with_no_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    issue = board_issue(10, "Work", complete_contract("Claim #10."), labels=("security",))
    _configured_board_client(monkeypatch, tmp_path, open_issues=(issue,))
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=10, scope=("src/work.py",)),
    )

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "10",
                "--agent",
                "Codex Sol",
                "--scope",
                "src/work.py",
            ]
        )
        == 0
    )

    assert store.fetch_state(worktree=Path("."), remote="origin").claims
    assert "ERROR:" not in capsys.readouterr().err


@pytest.mark.parametrize(
    ("dependencies", "expected_blockers"),
    [
        pytest.param((block_dependency(9),), "#9", id="single-open-dependency"),
        pytest.param(
            (block_dependency(9), block_dependency(11)), "#9, #11", id="two-open-dependencies"
        ),
        pytest.param(
            (block_dependency(9), block_dependency(11, is_pull_request=True)),
            "#9, #11",
            id="a-pull-request-dependency-blocks-like-any-other",
        ),
        pytest.param(
            (block_dependency(7, repository="overnightworks/other-repo"),),
            "overnightworks/other-repo#7",
            id="a-foreign-dependency-blocks-and-is-named-qualified",
        ),
    ],
)
def test_claim_refuses_an_open_dependency_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    dependencies: tuple[IssueDependency, ...],
    expected_blockers: str,
) -> None:
    issue, blocked_by = blocked_issue(10, "Work", *dependencies, labels=("security",))
    _configured_board_client(monkeypatch, tmp_path, open_issues=(issue,), dependencies=blocked_by)
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=10, scope=("src/work.py",)),
    )

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "10",
                "--agent",
                "Codex Sol",
                "--scope",
                "src/work.py",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    assert captured.err == (
        f"ERROR: #10 is blocked by {expected_blockers} (open); "
        "pass --out-of-order REASON to claim it anyway\n"
    )


def test_claim_ignores_a_closed_dependency(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    closed = block_dependency(
        9, state=BlockerState.CLOSED, closed_at=datetime(2026, 8, 20, tzinfo=UTC)
    )
    issue, blocked_by = blocked_issue(10, "Work", closed, labels=("security",))
    _configured_board_client(monkeypatch, tmp_path, open_issues=(issue,), dependencies=blocked_by)
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=10, scope=("src/work.py",)),
    )

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "10",
                "--agent",
                "Codex Sol",
                "--scope",
                "src/work.py",
            ]
        )
        == 0
    )

    assert store.fetch_state(worktree=Path("."), remote="origin").claims
    assert "ERROR:" not in capsys.readouterr().err


def test_claim_allows_an_open_dependency_with_out_of_order_and_records_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    reason = "Blocker #9 is stuck on review; unblocking manually."
    blocker = board_issue(9, "Blocker 9", complete_contract("Claim #9."))
    issue, blocked_by = blocked_issue(10, "Work", block_dependency(9), labels=("security",))
    _configured_board_client(
        monkeypatch, tmp_path, open_issues=(issue, blocker), dependencies=blocked_by
    )
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: replace(
            request(issue=10, scope=("src/work.py",)), out_of_order_reason=reason
        ),
    )

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "10",
                "--agent",
                "Codex Sol",
                "--scope",
                "src/work.py",
                "--out-of-order",
                reason,
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "WARNING: #10 is blocked by #9 (open)" in output


def test_claim_refuses_a_malformed_block_before_mutation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A body whose block carries a key the schema does not define is refused
    by name -- the typed successor to prose's duplicate-section defect."""
    issue = board_issue(10, "Work", block_body(f'{MINIMAL_BLOCK_TOML}owner = "someone"\n'))
    _configured_board_client(monkeypatch, tmp_path, open_issues=(issue,))
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=10, scope=("src/work.py",)),
    )

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "10",
                "--agent",
                "Codex Sol",
                "--scope",
                "src/work.py",
                "--json",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["reason"] == "precondition_failed"
    assert payload["checks"] == [
        {
            "level": "error",
            "check": "body-contract",
            "text": "body malformed: owner: unknown top-level key owner",
            "slice": None,
            "issue": None,
        }
    ]


def test_claim_ignores_body_size_and_closed_next_references(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    issue = board_issue(
        10,
        "Work",
        complete_contract("#9 follow up.") + "\n\n" + "x" * 50_000,
    )
    _configured_board_client(monkeypatch, tmp_path, open_issues=(issue,))
    monkeypatch.setattr(
        board_read,
        "fetch_issue_reference",
        lambda _client, _number: pytest.fail("claim must not inspect Next references"),
    )
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=10, scope=("src/work.py",)),
    )

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "10",
                "--agent",
                "Codex Sol",
                "--scope",
                "src/work.py",
            ]
        )
        == 0
    )

    assert store.fetch_state(worktree=Path("."), remote="origin").claims
    assert "ERROR:" not in capsys.readouterr().err


def test_release_ignores_body_contract_defects(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeForge()
    client.board_issues = (
        board_issue(
            10,
            "Work",
            complete_contract("Claim #10.") + "\n\n**Done when:** Duplicate.",
        ),
    )
    monkeypatch.setattr(
        client, "list_open_board_issues", lambda: pytest.fail("release checks no body")
    )
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    standing = request("held", issue=10, scope=("src/work.py",))
    _patch_store_write(monkeypatch, store_claim_from_request(standing))

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "release",
                "10",
                "--agent",
                "Codex Sol",
                "--claim-id",
                "held",
                "--abandoned",
                "stopped",
            ]
        )
        == 0
    )

    assert "RELEASED issue #10: held" in capsys.readouterr().out


def test_claim_refuses_when_the_higher_priority_item_needs_refining(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    client = FakeForge()
    unruled = board_issue(
        11,
        "Needs rulings",
        complete_contract(
            "Claim #11.",
            scope=["src/needs-rulings.py"],
            expectation=[proposed_expectation("Name it.", default="yes")],
        ),
    )
    waiting, waiting_dependencies = blocked_issue(
        12, "Waits for rulings", block_dependency(11), next_step="Claim #12."
    )
    ready = board_issue(10, "Ready work", complete_contract("Claim #10."))
    claimed_request = request(issue=10, scope=("src/work.py",))
    client.board_dependencies = dict(waiting_dependencies)
    monkeypatch.setattr(client, "list_open_board_issues", lambda: (ready, unruled, waiting))
    monkeypatch.setattr(client, "list_open_board_pull_requests", lambda: ())
    monkeypatch.setattr(client, "list_recent_merged_board_pull_requests", lambda _since: ())
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(cmd_claim, "_request", lambda _arguments, **_kwargs: claimed_request)

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "10",
                "--agent",
                "Codex Sol",
                "--scope",
                "src/work.py",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "ERROR: higher-priority actionable item #11" in captured.err
    assert "Needs rulings" in captured.err
    assert "--out-of-order REASON" in captured.err


def test_claim_parser_description_names_what_refuses_first() -> None:
    """`claim --help` must not send an agent to the README for what refuses
    first in practice: the parser's own description, pinned at
    the layer that produces it, names an isolated worktree on a non-main
    branch, a clean tree before the first edit, and --scope paths being
    repository-relative."""
    parser = issue_claim._parser()
    subparsers_action = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    claim_parser = subparsers_action.choices["claim"]

    assert claim_parser.description == issue_claim.CLAIM_DESCRIPTION
    assert "isolated" in issue_claim.CLAIM_DESCRIPTION
    assert "non-main branch" in issue_claim.CLAIM_DESCRIPTION
    assert "clean" in issue_claim.CLAIM_DESCRIPTION
    assert "repository-relative" in issue_claim.CLAIM_DESCRIPTION


def test_help_lists_commands_in_their_stable_registration_order() -> None:
    """`aco --help`'s command order is part of the CLI's own contract:
    `cli._COMMANDS` keeps every command in its original position,
    including the forge-free and local commands."""
    parser = issue_claim._parser()
    subparsers_action = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )

    assert list(subparsers_action.choices) == [
        "bootstrap",
        "reset",
        "status",
        "board",
        "serve",
        "rulings",
        "next",
        "start",
        "claim",
        "release",
        "land",
        "adopt",
        "rescope",
        "cut",
        "rule",
        "check",
        "brief",
        "item",
    ]


def _every_parser(parser: argparse.ArgumentParser) -> Iterator[argparse.ArgumentParser]:
    yield parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub_parser in action.choices.values():
                yield from _every_parser(sub_parser)


def _all_parser_help_texts(parser: argparse.ArgumentParser) -> tuple[str, ...]:
    return tuple(each.format_help() for each in _every_parser(parser))


def test_no_registered_parser_reads_an_abbreviated_option() -> None:
    """OUT-09: the root and every subcommand level refuse an
    abbreviated long option, so a command registered later cannot forget it
    and a prefix never comes to stand for a destructive flag."""
    readers = [each.prog for each in _every_parser(issue_claim._parser()) if each.allow_abbrev]

    assert readers == []


def test_readme_and_help_texts_carry_no_stale_state_ref_read_only_sentence() -> None:
    """State-ref's write commands (`cut`/`rule`/
    `item new`/`item edit`/`item close`)
    are real; no README line and no `--help` text still calls the storage
    read-only, or names `item new`/`item edit`/`item close` as "not yet"
    built or "slice 4" future work. `state-ref`'s own still-true residual --
    a merged release's landing verification -- keeps its own
    "not yet" sentence; this proof is about the write path itself, not that
    named residual."""
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    texts = (readme, *_all_parser_help_texts(issue_claim._parser()))
    for text in texts:
        for line in text.splitlines():
            lowered = line.lower()
            if "state-ref" not in lowered and "storage" not in lowered:
                continue
            assert "read-only" not in lowered
            assert "slice 4" not in lowered
            if "not yet" in lowered:
                assert "item new" not in lowered
                assert "item edit" not in lowered
                assert "item close" not in lowered


@pytest.mark.parametrize(
    ("command", "substrings"),
    [
        pytest.param(
            "claim",
            ("refuse", "without a reason", "priority actionable item is free"),
            id="claim-names-the-out-of-order-refusal",
        ),
        pytest.param(
            "claim",
            (
                "takes it from the item's own body when omitted",
                "lane mode always requires it",
            ),
            id="claim-names-where-an-omitted-scope-comes-from",
        ),
        pytest.param(
            "claim",
            ("--whole", "three paths", "directory", "quarter", "twelve"),
            id="claim-names-the-whole-reason",
        ),
        pytest.param(
            "rescope",
            ("--whole", "three paths"),
            id="rescope-names-the-whole-reason",
        ),
        pytest.param(
            "rescope",
            (
                "--add ADD an absolute or repository-relative path to add",
                "--drop DROP an absolute or repository-relative path to drop",
            ),
            id="rescope-names-a-repository-relative-path",
        ),
        pytest.param(
            "next",
            (
                "labelled needs-operator waits on the operator",
                "gh issue edit <n> --add-label/--remove-label needs-operator",
                "aco item edit <item-id>",
            ),
            id="next-names-the-label-that-holds-an-item-for-the-operator",
        ),
    ],
)
def test_help_text_names_the_refusal_or_source_it_documents(
    capsys: pytest.CaptureFixture[str], command: str, substrings: tuple[str, ...]
) -> None:
    """`claim --help` and `rescope --help` each name, in prose, the refusal
    or derivation source their own behaviour documents -- the out-of-order
    and wide-scope refusals, and
    where an omitted `--scope` comes from; `next --help` names the label
    that holds an item for the operator and how to set it."""
    with pytest.raises(SystemExit) as exited:
        issue_claim.main([command, "--help"])

    assert exited.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    for substring in substrings:
        assert substring in help_text


@pytest.mark.parametrize(
    "arguments",
    [
        ["claim", "5", "--scope", "src", "--allow-directory", "x"],
        ["rescope", "5", "--allow-directory", "x"],
    ],
    ids=["claim", "rescope"],
)
def test_cli_claim_and_rescope_reject_the_removed_allow_directory_flag(
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    with pytest.raises(SystemExit) as exited:
        issue_claim.main(arguments)

    assert exited.value.code == 2

    command = arguments[0]
    with pytest.raises(SystemExit) as help_exited:
        issue_claim.main([command, "--help"])

    assert help_exited.value.code == 0
    assert "--allow-directory" not in capsys.readouterr().out


def test_claim_refuses_out_of_order_without_a_reason_before_mutating(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    client = FakeForge()
    issues = (
        board_issue(10, "Lower work", complete_contract("Claim #10.")),
        board_issue(11, "Top work", complete_contract("Claim #11.", scope=["src/top.py"])),
        board_issue(12, "Depends on top", complete_contract("Claim #12."), blocked_by_count=1),
    )
    client.board_dependencies = {12: (block_dependency(11),)}
    claimed_request = request("out-of-order", issue=10, scope=("src/lower.py",))
    monkeypatch.setattr(client, "list_open_board_issues", lambda: issues)
    monkeypatch.setattr(client, "list_open_board_pull_requests", lambda: ())
    monkeypatch.setattr(client, "list_recent_merged_board_pull_requests", lambda _since: ())
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(cmd_claim, "_request", lambda _arguments, **_kwargs: claimed_request)

    arguments = [
        "--repo",
        REPOSITORY,
        "claim",
        "10",
        "--agent",
        "Codex Sol",
        "--scope",
        "src/lower.py",
    ]
    assert issue_claim.main(arguments) == 2
    captured = capsys.readouterr()

    assert "ERROR: higher-priority actionable item #11" in captured.err
    assert "Top work" in captured.err
    assert "--out-of-order REASON" in captured.err


def test_claim_allows_out_of_order_with_a_reason_and_records_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    client = FakeForge()
    issues = (
        board_issue(10, "Lower work", complete_contract("Claim #10.")),
        board_issue(11, "Top work", complete_contract("Claim #11.", scope=["src/top.py"])),
        board_issue(12, "Depends on top", complete_contract("Claim #12."), blocked_by_count=1),
    )
    client.board_dependencies = {12: (block_dependency(11),)}
    reason = "Urgent customer incident."
    claimed_request = replace(
        request("out-of-order", issue=10, scope=("src/lower.py",)),
        out_of_order_reason=reason,
    )
    monkeypatch.setattr(client, "list_open_board_issues", lambda: issues)
    monkeypatch.setattr(client, "list_open_board_pull_requests", lambda: ())
    monkeypatch.setattr(client, "list_recent_merged_board_pull_requests", lambda _since: ())
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(cmd_claim, "_request", lambda _arguments, **_kwargs: claimed_request)

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "10",
                "--agent",
                "Codex Sol",
                "--scope",
                "src/lower.py",
                "--out-of-order",
                reason,
            ]
        )
        == 0
    )
    output = capsys.readouterr().out

    assert "WARNING" in output
    assert "#11" in output


def test_claim_refuses_for_a_higher_priority_item_even_at_a_lower_score(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """`board`/`next` rank a labelled blocker ahead of an unlabelled item even
    when the blocker scores lower; the out-of-order refusal must agree, or
    claiming the unlabelled item would silently skip past the very item
    `next` would have named.
    """
    client = FakeForge()
    blocker = board_issue(
        50,
        "Prerequisite the operator prioritized",
        complete_contract("Unblock #52.", scope=["src/prerequisite.py"]),
    )
    dependent, dependent_blockers = blocked_issue(
        52, "Depends on the prerequisite", block_dependency(50), next_step="Ship it."
    )
    in_flight_unlabelled = board_issue(51, "In-flight, unlabelled", complete_contract("Ship it."))
    client.board_dependencies = dict(dependent_blockers)
    open_pull_request = workboard.PullRequest(200, "Fixes #51", "", "branch")
    claimed_request = request("lower-priority", issue=51, scope=("src/lower.py",))
    monkeypatch.setattr(
        client, "list_open_board_issues", lambda: (blocker, dependent, in_flight_unlabelled)
    )
    monkeypatch.setattr(client, "list_open_board_pull_requests", lambda: (open_pull_request,))
    monkeypatch.setattr(client, "list_recent_merged_board_pull_requests", lambda _since: ())
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(cmd_claim, "_request", lambda _arguments, **_kwargs: claimed_request)

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "51",
                "--agent",
                "Codex Sol",
                "--scope",
                "src/lower.py",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()

    # #51 (score 40: in-flight + single next) outscores #50 (score 10: it
    # unblocks #52, text-only, single next), but #50 leads on the board
    # because it carries the higher-priority "blocker" bucket.
    assert "ERROR" in captured.err
    assert "#50" in captured.err


def test_claim_json_refusal_reports_out_of_order_without_mutating(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    lower = board_issue(10, "Lower work", complete_contract("Claim #10."))
    top = board_issue(11, "Top work", complete_contract("Claim #11.", scope=["src/top.py"]))
    dependent, dependent_blockers = blocked_issue(
        12, "Depends on top", block_dependency(11), next_step="Claim #12."
    )
    _configured_board_client(
        monkeypatch,
        tmp_path,
        open_issues=(lower, top, dependent),
        dependencies=dependent_blockers,
    )
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=10, scope=("src/lower.py",)),
    )

    exit_code = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "10",
            "--agent",
            "Codex Sol",
            "--scope",
            "src/lower.py",
            "--json",
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["reason"] == "precondition_failed"
    assert payload["issue"] == 10
    checks = payload["checks"]
    assert len(checks) == 1
    check = checks[0]
    assert check["level"] == "error"
    assert check["check"] == "out-of-order"
    assert check["issue"] == 11
    assert check["slice"] is None
    assert "#11" in check["text"]
    assert "Top work" in check["text"]
    assert "--out-of-order REASON" in check["text"]


def test_claim_does_not_require_out_of_order_for_the_top_ranked_item(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    top = board_issue(10, "Top work", complete_contract("Claim #10."))
    lower = board_issue(11, "Lower work", complete_contract("Claim #11."))
    _configured_board_client(monkeypatch, tmp_path, open_issues=(top, lower))
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=10, scope=("src/top.py",)),
    )

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "10",
                "--agent",
                "Codex Sol",
                "--scope",
                "src/top.py",
            ]
        )
        == 0
    )
    assert "WARNING: higher-priority actionable item" not in capsys.readouterr().out
    assert store.fetch_state(worktree=Path("."), remote="origin").claims


def test_claim_does_not_require_out_of_order_past_a_higher_ranked_labelled_idea(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    work = board_issue(10, "Regular work", complete_contract("Claim #10."))
    idea = board_issue(
        11,
        "Higher-ranked idea",
        complete_contract("Build it.", scope=["src/idea.py"]),
        labels=("idea", "security"),
    )
    _configured_board_client(monkeypatch, tmp_path, open_issues=(work, idea))
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=10, scope=("src/work.py",)),
    )

    exit_code = issue_claim.main(
        ["--repo", REPOSITORY, "claim", "10", "--agent", "Codex Sol", "--scope", "src/work.py"]
    )

    assert exit_code == 0
    assert "higher-priority actionable item" not in capsys.readouterr().err
    assert store.fetch_state(worktree=Path("."), remote="origin").claims


@pytest.mark.parametrize(
    ("state", "title", "check", "expected_text"),
    [
        (forge.ItemState.CLOSED, "Some title", "closed-issue", "issue #72 is closed"),
        (forge.ItemState.MISSING, None, "missing-issue", "issue #72 does not exist here"),
    ],
    ids=["closed", "missing"],
)
def test_claim_refuses_a_closed_or_missing_target(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    state: forge.ItemState,
    title: str | None,
    check: str,
    expected_text: str,
) -> None:
    _configured_board_client(monkeypatch, tmp_path)
    _stub_issue_reference(monkeypatch, {72: (state, title, "")})
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=72, scope=("src/work.py",)),
    )

    exit_code = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Codex Sol",
            "--scope",
            "src/work.py",
        ]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"ERROR: {expected_text}" in captured.err


def test_claim_refuses_a_container(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    container = Issue(
        72,
        "Container work",
        (),
        "",
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=0,
        children_total=0,
    )
    _configured_board_client(monkeypatch, tmp_path, open_issues=(container,))
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=72, scope=("src/work.py",)),
    )

    exit_code = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Codex Sol",
            "--scope",
            "src/work.py",
        ]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ERROR: #72 is a container; claim a child" in captured.err


def test_claim_refuses_a_freshly_cut_childs_incomplete_skeleton(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """`cut`'s fresh child from a row without `done_when` (CUT-25) is
    defect-free but incomplete -- `now` and `next` filled, `done_when`
    empty -- so it is invisible to `next`, and refused here too, exactly as
    ruled: `claim` requires a complete projection."""
    cut_child_body = cmd_cut._cut_child_body(90, body.Storage.GITHUB)
    child = board_issue(101, "Scheibe 1", cut_child_body)
    _configured_board_client(monkeypatch, tmp_path, open_issues=(child,))
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=101, scope=("src/work.py",)),
    )

    exit_code = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "101",
            "--agent",
            "Codex Sol",
            "--scope",
            "src/work.py",
        ]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ERROR: #101 body incomplete: Done when" in captured.err


def test_claim_names_an_incomplete_body_even_when_the_item_is_also_blocked(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """`item.actionable_reason` names only the first applicable reason
    (frozen, claimed, blocked, then incomplete) -- that must not mask the
    incomplete-body refusal when another reason also applies."""
    blocker = board_issue(50, "Blocker", complete_contract("Ship it."))
    dependent = board_issue(
        51, "Dependent", complete_contract("", now="Work.", done_when=""), blocked_by_count=1
    )
    _configured_board_client(
        monkeypatch,
        tmp_path,
        open_issues=(blocker, dependent),
        dependencies={51: (block_dependency(50),)},
    )
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=51, scope=("src/work.py",)),
    )

    exit_code = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "51",
            "--agent",
            "Codex Sol",
            "--scope",
            "src/work.py",
            "--json",
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert "body-incomplete" in {check["check"] for check in payload["checks"]}


CUT_CONTAINER = 79


def _cuttable_row_toml(title: str) -> str:
    """A complete block with one `[[slice]]` row, `index = 1`, carrying the
    `done_when` `cut` needs -- the container block every
    one-row cut scenario starts from."""
    return f'{MINIMAL_BLOCK_TOML}[[slice]]\nindex = 1\ntitle = "{title}"\ndone_when = "D"\n'


def _cuttable_slice_entries(*titles: str) -> list[dict[str, object]]:
    """`slice_entries(*titles)`, each row carrying the `done_when` `cut`
    needs."""
    return [{**entry, "done_when": "D"} for entry in slice_entries(*titles)]


def _one_slice_container() -> Issue:
    return container_issue(CUT_CONTAINER, _cuttable_row_toml("Scheibe 1"))


def _write_block_pin(tmp_path: Path) -> None:
    write_repository_config(tmp_path, 'body_contract = "block"\n')


def test_the_container_a_cut_empties_of_rows_still_passes_check_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Spec: BODY-49, BODY-67, E-BODY-08.

    The emptied container with a ruled expectation still passes check -.
    """
    container = container_issue(
        CUT_CONTAINER,
        f"{MINIMAL_BLOCK_TOML}"
        '[[expectation]]\ntext = "A line"\nruling = "yes"\nruled_on = 2026-10-02\n'
        '[[slice]]\nindex = 1\ntitle = "Scheibe 1"\ndone_when = "Scheibe 1 is merged."\n',
    )
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=(container,))
    _write_block_pin(tmp_path)

    exit_code = issue_claim.main(["--repo", REPOSITORY, "cut", str(CUT_CONTAINER)])

    assert exit_code == 0
    capsys.readouterr()
    assert (
        run_cli(["check", "-"], capsys, stdin=client.item_bodies[CUT_CONTAINER]).expect_success()
        == "body ok\n"
    )


@pytest.mark.parametrize(
    ("orphan", "idea_label"),
    [
        pytest.param(
            board_issue(
                CUT_CONTAINER,
                "Scheibe 1",
                cmd_cut._cut_child_body(CUT_CONTAINER, body.Storage.GITHUB, done_when="D"),
                kind=body.ItemKind.TASK,
            ),
            None,
            id="the_container_itself",
        ),
    ],
)
def test_cut_never_adopts_an_orphan_that_is_not_this_containers_recovery_shape(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    orphan: Issue,
    idea_label: str | None,
) -> None:
    """A title match alone is too weak to adopt an orphan: a
    human-filed issue, an idea, the container's own issue, or another
    container's own failed-cut orphan can all share the row's exact title
    without being this container's recovery shape, so `cut` creates a fresh
    child instead of silently re-parenting any of them -- once the caller
    has said the look-alike is no twin."""
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=(_one_slice_container(),))
    _write_block_pin(tmp_path)
    if idea_label is not None:
        write_repository_config(tmp_path, f'body_contract = "block"\nidea_label = "{idea_label}"\n')
    monkeypatch.setattr(client, "list_open_board_issues", lambda: (_one_slice_container(), orphan))

    exit_code = issue_claim.main(
        ["--repo", REPOSITORY, "cut", str(CUT_CONTAINER), "--title", "Scheibe 1", "--not-a-twin"]
    )

    assert exit_code == 0
    child = client.next_created_child_number - 1
    assert client.linked_children == [(CUT_CONTAINER, child)]
    assert client.created_children == [
        (
            CUT_CONTAINER,
            "Scheibe 1",
            cmd_cut._cut_child_body(CUT_CONTAINER, body.Storage.GITHUB, done_when="D"),
            body.ItemKind.TASK,
        )
    ]
    assert capsys.readouterr().out == f"CUT #{CUT_CONTAINER} row 1 -> #{child}\n"


RULE_ITEM = 90


def _client_with_item(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    number: int,
    body: str,
    *,
    title: str = "Decide something",
    is_landing: bool = False,
    closed: bool = False,
) -> FakeForge:
    client = _configured_board_client(monkeypatch, tmp_path)
    state = forge.ItemState.CLOSED if closed else forge.ItemState.OPEN
    client.issue_references[number] = forge.ItemReference(state, title, body, is_landing)
    return client


def test_cli_claim_reports_invalid_usage_when_repo_is_given_under_state_ref(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A wide `--scope` with no `--whole` reads the item's own body for one,
    resolving the forge before `cmd_claim.run`'s own typed-
    refusal handlers ever see it: under `storage = state-ref`,
    `--repo` is the wrong flag for this run, reported as `invalid_usage`
    rather than the generic `unavailable` bucket -- the same distinction
    `ask`/`rule`/`brief` already draw."""
    _write_state_ref_pin(tmp_path)
    client = FakeForge()
    arrange_scope_width(monkeypatch, client, versioned=("a.py", "b.py", "c.py", "d.py"))

    status = issue_claim.main(
        [
            "--repo",
            "acme/items",
            "claim",
            "72",
            "--agent",
            "Ada",
            "--base",
            BASE,
            "--branch",
            "codex/issue-72",
            "--scope",
            "a.py",
            "--scope",
            "b.py",
            "--scope",
            "c.py",
            "--scope",
            "d.py",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == "ERROR: --repo is meaningless under storage = state-ref\n"
    _assert_json_refusal_object(captured.err, captured.out, reason="invalid_usage")


@pytest.mark.parametrize(
    "slice_title",
    [
        pytest.param("Scheibe 1", id="plain_title"),
        pytest.param('Say "hi" to $HOME', id="double_quotes_and_a_shell_variable"),
        pytest.param("it's `here`", id="single_quote_and_backticks"),
        pytest.param("-draft", id="a_leading_dash"),
    ],
)
def test_next_prints_a_cut_command_bash_runs_as_printed_and_cut_accepts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    slice_title: str,
) -> None:
    """The `cut` line `next` prints runs
    unchanged in a real shell and names no title, so `cut` gives the child
    the row's own title whatever it holds -- a leading `-` included."""
    toml_text = (
        'version = 1\nnow = "N"\nnext = "nichts"\ndone_when = "D"\n'
        f'[[slice]]\nindex = 1\ntitle = {json.dumps(slice_title)}\ndone_when = "D"\n'
    )
    container = container_issue(CUT_CONTAINER, toml_text)
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=(container,))
    _write_block_pin(tmp_path)

    next_exit_code = issue_claim.main(["--repo", REPOSITORY, "next"])
    advice = capsys.readouterr().out.splitlines()[1].removeprefix("Next: ")
    bash_exit_code, cut_arguments = arguments_bash_hands_aco(advice, tmp_path)
    cut_exit_code = issue_claim.main(["--repo", REPOSITORY, *cut_arguments])

    assert (next_exit_code, bash_exit_code, cut_exit_code) == (0, 0, 0)
    assert client.created_children[0][:2] == (CUT_CONTAINER, slice_title)


def test_next_prints_a_cut_command_block_mode_accepts_a_differing_next_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A block container whose own `next` line still names work in
    its own words, while its first uncut `[[slice]]` entry carries a
    different title, must still print a `cut` command that `cut` itself
    accepts and that links exactly that entry. Without `--row`, `cut` links
    the first uncut entry and takes that entry's own title, so the
    printed command names the container alone -- no title, so the `next`
    line's prose can never reach the child -- while the action line above
    it keeps naming the container's own words. `next
    --json` carries the same split as two fields: `slice` is that human
    step, `cut_title` is the title `cut` accepts -- a JSON consumer must
    build `--title` from `cut_title`, never `slice` (the README used to say
    otherwise). The child each cut writes carries `cut`'s own fixed `next`
    (CUT-25), never the container's `next` line."""
    toml_text = (
        f'version = 1\nnow = "N"\nnext = "{_DIFFERING_NEXT_LINE}"\ndone_when = "D"\n'
        '[[slice]]\nindex = 1\ntitle = "Scheibe 1"\ndone_when = "D"\n'
    )
    container = container_issue(CUT_CONTAINER, toml_text)
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=(container,))
    _write_block_pin(tmp_path)

    json_exit_code = issue_claim.main(["--repo", REPOSITORY, "next", "--json"])
    assert json_exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "cut_slice"
    assert payload["slice"] == _DIFFERING_NEXT_LINE
    assert payload["cut_title"] == "Scheibe 1"

    json_cut_exit_code = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "cut",
            str(CUT_CONTAINER),
            "--title",
            payload["cut_title"],
        ]
    )
    assert json_cut_exit_code == 0
    capsys.readouterr()  # discard this leg's own "CUT #79 row 1 -> #N" line

    next_exit_code = issue_claim.main(["--repo", REPOSITORY, "next"])
    assert next_exit_code == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == f"cut_slice #{CUT_CONTAINER}: {_DIFFERING_NEXT_LINE}"
    command_line = out.splitlines()[1]
    cut_arguments = shlex.split(command_line.removeprefix("Next: aco "))

    cut_exit_code = issue_claim.main(["--repo", REPOSITORY, *cut_arguments])

    assert cut_exit_code == 0
    child = client.next_created_child_number - 1
    remaining_slice_entries = body.locate_block(client.item_bodies[CUT_CONTAINER]).data["slice"]
    assert remaining_slice_entries == []
    assert capsys.readouterr().out == f"CUT #{CUT_CONTAINER} row 1 -> #{child}\n"
    assert {
        body.parse_body(child_body).contract.next
        for _parent, _title, child_body, _kind in client.created_children
    } == {"Build this slice; claim it with aco start."}


def test_claim_json_refusal_carries_refused_issue_and_checks(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _configured_board_client(monkeypatch, tmp_path)
    _stub_issue_reference(monkeypatch, {72: (forge.ItemState.CLOSED, "Title", "")})
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=72, scope=("src/work.py",)),
    )

    exit_code = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Codex Sol",
            "--scope",
            "src/work.py",
            "--json",
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": False,
        "reason": "precondition_failed",
        "issue": 72,
        "checks": [
            {
                "level": "error",
                "check": "closed-issue",
                "text": "issue #72 is closed",
                "slice": None,
                "issue": 72,
            }
        ],
    }


def test_claim_does_not_corridor_on_a_slice_list(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    body = complete_contract("Ship it.", slice=slice_entries("First slice"))
    target = board_issue(72, "Epic", body)
    _configured_board_client(monkeypatch, tmp_path, open_issues=(target,))
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=72, scope=("src/work.py",)),
    )

    exit_code = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Codex Sol",
            "--scope",
            "src/work.py",
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["checks"] == []
    assert store.fetch_state(worktree=Path("."), remote="origin").claims


@pytest.mark.parametrize(
    ("title", "parents", "expect_warning"),
    [
        pytest.param(
            "Schema traegt den Titel (#79 Scheibe 21)", {}, True, id="without_sub_issue_relation"
        ),
        pytest.param(
            "Schema traegt den Titel (#79 Scheibe 21)",
            {1017: workboard.ParentIssue(workboard.IssueReference(REPOSITORY, 79), "## Now\nCut.")},
            False,
            id="with_sub_issue_relation",
        ),
        pytest.param(f"Schema (#{'9' * 4301} Scheibe 21)", {}, False, id="parent_past_the_bound"),
    ],
)
def test_claim_checks_a_slice_shaped_title_for_its_recorded_parent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    title: str,
    parents: dict[int, workboard.ParentIssue],
    expect_warning: bool,
) -> None:
    target = board_issue(1017, title, complete_contract("Claim #1017."))
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=(target,))
    client.parents.update(parents)
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=1017, scope=("src/work.py",)),
    )

    exit_code = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "1017",
            "--agent",
            "Codex Sol",
            "--scope",
            "src/work.py",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    expected = (
        "WARNING: looks like slice 21 of #79 but is no sub-issue of #79; "
        "the parent inherits nothing"
    )
    assert (expected in output) is expect_warning
    assert store.fetch_state(worktree=Path("."), remote="origin").claims


def test_next_skips_a_frozen_item_and_names_it_as_such(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    frozen = board_issue(
        301, "Highest scored", complete_contract("Claim #301.", frozen_until=FROZEN_UNTIL)
    )
    lower = board_issue(10, "Lower work", complete_contract("Claim #10."))
    client = FakeForge()
    monkeypatch.setattr(client, "list_open_board_issues", lambda: (frozen, lower))
    monkeypatch.setattr(client, "list_open_board_pull_requests", lambda: ())
    monkeypatch.setattr(client, "list_recent_merged_board_pull_requests", lambda _since: ())
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_lane_worktree_git(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())

    assert issue_claim.main(["--repo", REPOSITORY, "next"]) == 0
    assert capsys.readouterr().out == (
        "#10 score -10: Lower work\n"
        "Next: Claim #10.\n"
        "Run: aco claim 10 --scope <paths>\n" + _UNKNOWN_SCOPE_NEXT_TAIL + "\n"
        "SKIPPED\n"
        f"#301: frozen: {FROZEN_TRIGGER}\n"
    )

    assert issue_claim.main(["--repo", REPOSITORY, "next", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["number"] == 10
    assert payload["skipped"] == [{"number": 301, "reason": f"frozen: {FROZEN_TRIGGER}"}]


@pytest.mark.parametrize(
    "higher",
    [
        pytest.param(
            board_issue(
                301, "Highest scored", complete_contract("Claim #301.", frozen_until=FROZEN_UNTIL)
            ),
            id="frozen",
        ),
        pytest.param(
            board_issue(
                301,
                "Highest scored",
                complete_contract("wait for session with the operator"),
                labels=("security", NEEDS_OPERATOR_LABEL),
            ),
            id="waiting_on_the_operator",
        ),
    ],
)
def test_claim_does_not_warn_about_a_higher_scored_item_no_agent_can_pull(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    higher: Issue,
) -> None:
    client = FakeForge()
    lower = board_issue(10, "Lower work", complete_contract("Claim #10."))
    claimed_request = request(issue=10, scope=("src/lower.py",))
    monkeypatch.setattr(client, "list_open_board_issues", lambda: (higher, lower))
    monkeypatch.setattr(client, "list_open_board_pull_requests", lambda: ())
    monkeypatch.setattr(client, "list_recent_merged_board_pull_requests", lambda _since: ())
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(cmd_claim, "_request", lambda _arguments, **_kwargs: claimed_request)

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "10",
                "--agent",
                "Codex Sol",
                "--scope",
                "src/lower.py",
            ]
        )
        == 0
    )
    assert "WARNING" not in capsys.readouterr().out


def test_board_reads_priority_configuration_from_the_checkout_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    toplevel = tmp_path / "checkout"
    write_repository_config(toplevel, 'priority_labels = ["ux", "security"]\n')
    nested_directory = toplevel / "src" / "aco"
    nested_directory.mkdir(parents=True)
    monkeypatch.chdir(nested_directory)
    toplevel_read = ("rev-parse", "--show-toplevel")
    trunk_head_read = RECORDED_ORIGIN_HEAD_READ
    answers = {toplevel_read: str(toplevel), trunk_head_read: "refs/remotes/origin/main"}
    observed: list[tuple[str, ...]] = []

    def git_output(arguments: list[str], **_kwargs: object) -> str:
        observed.append(tuple(arguments))
        return answers[tuple(arguments)]

    client = _MinimalForgeReader(
        open_issues=(
            Issue(
                20,
                "Security issue",
                ("security",),
                "",
                "2026-08-20T00:00:00Z",
                "2026-08-20T00:00:00Z",
            ),
            Issue(21, "UX issue", ("ux",), "", "2026-08-20T00:00:00Z", "2026-08-20T00:00:00Z"),
        )
    )
    monkeypatch.setattr(checkout, "git_output", git_output)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())

    projected = board_read.build_board(run_context_over(client), ())

    assert [item.number for item in projected.items] == [21, 20]
    assert observed == [toplevel_read, trunk_head_read]


def test_next_names_a_cuttable_container_slice(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Exact `cut_slice #N: …` text."""
    container = Issue(
        180,
        "Epic",
        (),
        complete_contract(
            "Scheibe B — Kartenraster", slice=slice_entries("Scheibe B — Kartenraster")
        ),
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=1,
        children_total=1,
    )
    _configured_board_client(monkeypatch, tmp_path, open_issues=(container,))

    exit_code = issue_claim.main(["--repo", REPOSITORY, "next"])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "cut_slice #180: Scheibe B — Kartenraster\nNext: aco cut 180\n" + _PARALLEL_UNKNOWN_TAIL
    )


# A `Next` line whose own prose never matches any slice-table row title used
# below -- a container whose Next line and first uncut
# row disagree.
_DIFFERING_NEXT_LINE = "Weitere Aufgabe."


@dataclass(frozen=True)
class _CutRoundTripCase:
    """One round-trip scenario for a container whose block still
    carries an undispatched `[[slice]]` row: the `cut` command `next` prints
    for `container_number` must be one `cut` itself accepts.
    That row is the only thing that makes `next` print a `cut`
    command at all -- a container with no uncut row is never one of these
    cases, whatever its `Next` line says (see
    `test_next_names_a_container_with_no_slice_row_by_its_own_next_line` for
    that combination instead). `expected_item_bodies`/`expected_output` take
    the freshly created child's number, since only `cut` fixes that."""

    case_id: str
    container_number: int
    body: str
    expected_created_title: str
    expected_item_bodies: Callable[[int], dict[int, str]]
    expected_output: Callable[[int], str]


def _uncut_row_case(
    case_id: str, container_number: int, next_line: str, row_title: str
) -> _CutRoundTripCase:
    """A container whose block still carries one undispatched `[[slice]]` --
    `cut` always links it and titles the created child with that entry's own
    title, regardless of what the container's `Next` line itself says."""
    return _CutRoundTripCase(
        case_id,
        container_number,
        complete_contract(next_line, slice=_cuttable_slice_entries(row_title)),
        row_title,
        lambda _child: {container_number: complete_contract(next_line, slice=[])},
        lambda child: f"CUT #{container_number} row 1 -> #{child}\n",
    )


_CUT_ROUND_TRIP_CASES = (
    # next=no, uncut=yes -- an uncut row on its own already qualifies.
    _uncut_row_case("uncut_row_only", 184, "", "Scheibe E"),
    # next=yes, uncut=yes, and they disagree -- seven live
    # atelier-2 containers where `next` printed the `Next` line's prose and
    # `cut` refused it, because the row it actually links carries a
    # different title.
    _uncut_row_case("next_and_differing_uncut_row", 186, _DIFFERING_NEXT_LINE, "Scheibe F"),
    # The remaining combinations -- no uncut row, whether or not the `Next`
    # line still names work -- close the container instead of cutting a
    # slice (an empty slice table, with or without a `slice` key
    # at all, is the typed statement that there is nothing here to cut),
    # so they have no
    # `cut` command to round-trip; `test_next_names_a_closeable_container`
    # and `test_next_names_a_container_with_no_slice_row_by_its_own_next_line`
    # prove those instead.
)


@pytest.mark.parametrize("case", _CUT_ROUND_TRIP_CASES, ids=lambda case: case.case_id)
def test_next_prints_a_cut_command_that_cut_accepts(
    case: _CutRoundTripCase,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Whatever `cut` command
    `next` prints for a childless container is one `cut` itself accepts."""
    container = Issue(
        case.container_number,
        "Epic",
        (),
        case.body,
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=1,
        children_total=1,
    )
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=(container,))

    next_exit_code = issue_claim.main(["--repo", REPOSITORY, "next"])
    assert next_exit_code == 0
    command_line = capsys.readouterr().out.splitlines()[1]
    cut_arguments = shlex.split(command_line.removeprefix("Next: aco "))

    cut_exit_code = issue_claim.main(["--repo", REPOSITORY, *cut_arguments])

    assert cut_exit_code == 0
    child = client.next_created_child_number - 1
    assert client.created_children == [
        (
            case.container_number,
            case.expected_created_title,
            cmd_cut._cut_child_body(case.container_number, body.Storage.GITHUB, done_when="D"),
            body.ItemKind.TASK,
        )
    ]
    assert client.item_bodies == case.expected_item_bodies(child)
    assert capsys.readouterr().out == case.expected_output(child)


def test_next_prints_a_cut_command_that_cut_accepts_for_every_qualifying_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`next` only ever proves
    the round-trip invariant for the single top-ranked container a board
    carries,
    since only one container's
    printed command is ever checked per poll. This walks every container a
    real, multi-container board carries, deriving each one's own printed
    `cut` command through the public `workboard.next_action` path -- each container
    alone on its own board, so it is necessarily the one `workboard.next_action`
    names -- and proves every one of them is a command `cut` itself accepts
    on a fresh fake, not only the board's own top-ranked pick."""
    top_ranked = Issue(
        130,
        "Epic ranked first",
        (),
        complete_contract(_DIFFERING_NEXT_LINE, slice=_cuttable_slice_entries("Scheibe I-top")),
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=1,
        children_total=1,
    )
    lower_ranked = Issue(
        145,
        "Epic ranked second",
        (),
        complete_contract(_DIFFERING_NEXT_LINE, slice=_cuttable_slice_entries("Scheibe I")),
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=1,
        children_total=1,
    )
    containers = (top_ranked, lower_ranked)
    containers_by_number = {issue.number: issue for issue in containers}

    projected = projected_board(
        containers, (), (), (), workboard.BoardConfig(), now=datetime(2026, 8, 21, tzinfo=UTC)
    )
    top_action = workboard.next_action(projected)
    assert isinstance(top_action, workboard.CutSliceAction)
    assert top_action.container.number == 130

    for item in projected.items:
        if item.kind is not body.ItemKind.CONTAINER:
            continue
        isolated = projected_board(
            (containers_by_number[item.number],),
            (),
            (),
            (),
            workboard.BoardConfig(),
            now=datetime(2026, 8, 21, tzinfo=UTC),
        )
        action = workboard.next_action(isolated)
        assert isinstance(action, workboard.CutSliceAction)

        command_line = cmd_next._next_action_lines(
            action,
            body.Storage.GITHUB,
            site=cmd_next._PullSite(claims_in_place=True, scope_is_wide=False),
        )[1]
        cut_arguments = shlex.split(command_line.removeprefix("Next: aco "))
        client = _configured_board_client(
            monkeypatch, tmp_path, open_issues=(containers_by_number[item.number],)
        )

        cut_exit_code = issue_claim.main(["--repo", REPOSITORY, *cut_arguments])

        assert cut_exit_code == 0
        assert client.created_children[0][0] == item.number


@pytest.mark.parametrize(
    ("parent_kind", "parent_open", "parent_repository", "slice_titles", "repair"),
    [
        pytest.param(
            body.ItemKind.CONTAINER,
            True,
            REPOSITORY,
            ("Scheibe Z",),
            "nested container, which cut refuses; run aco item edit 299 --kind task and "
            "claim it with aco claim 299 --scope <paths> --out-of-order <reason>",
            id="open_container_parent_one_scopeless_row_names_the_task_repair",
        ),
        pytest.param(
            body.ItemKind.CONTAINER,
            True,
            REPOSITORY,
            ("Scheibe Y", "Scheibe Z"),
            f"nested container, which cut refuses; move its slice rows to {REPOSITORY}#298",
            id="several_rows_name_the_move_to_the_parent",
        ),
        pytest.param(
            body.ItemKind.FEATURE,
            True,
            REPOSITORY,
            ("Scheibe Y", "Scheibe Z"),
            f"nested container, which cut refuses; move its slice rows to {REPOSITORY}#298",
            id="feature_parent",
        ),
        pytest.param(
            body.ItemKind.CONTAINER,
            False,
            REPOSITORY,
            ("Scheibe Y", "Scheibe Z"),
            f"nested container, which cut refuses; move its slice rows to {REPOSITORY}#298",
            id="closed_parent",
        ),
        pytest.param(
            body.ItemKind.CONTAINER,
            False,
            "other-owner/other-repo",
            ("Scheibe Y", "Scheibe Z"),
            "nested container, which cut refuses; move its slice rows to "
            "other-owner/other-repo#298",
            id="parent_in_another_repository",
        ),
    ],
)
def test_next_names_a_nested_containers_repair_where_cut_refuses_its_row(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    parent_kind: body.ItemKind,
    parent_open: bool,
    parent_repository: str,
    slice_titles: tuple[str, ...],
    repair: str,
) -> None:
    """A container that is itself a child, its
    own children closed and an uncut `[[slice]]` row left. `cut` refuses it
    whatever its parent's type, state, or repository, so `next` never prints
    that `cut` -- it names the container's repair under `SKIPPED` instead,
    and `cut` keeps its refusal: the advice and the command agree."""
    parent = Issue(
        298,
        "Epic",
        (),
        complete_contract("Finish #299.", scope=["docs/epic.md"]),
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=parent_kind,
        children_closed=0 if parent_kind is body.ItemKind.CONTAINER else None,
        children_total=1 if parent_kind is body.ItemKind.CONTAINER else None,
    )
    nested = Issue(
        299,
        "Nested epic",
        (),
        complete_contract("keiner", slice=slice_entries(*slice_titles)),
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=1,
        children_total=1,
    )
    board_parent = (parent,) if parent_open and parent_repository == REPOSITORY else ()
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=(*board_parent, nested))
    client.children = {
        298: (ChildItem(299, ChildState.OPEN),),
        299: (ChildItem(300, ChildState.CLOSED),),
    }
    client.parents[299] = workboard.ParentIssue(
        workboard.IssueReference(parent_repository, 298), parent.body, parent_kind
    )
    cut_arguments = ["--repo", REPOSITORY, "cut", "299", "--title", slice_titles[0]]

    next_exit_code = issue_claim.main(["--repo", REPOSITORY, "next"])
    next_out = capsys.readouterr().out
    cut_exit_code = issue_claim.main(cut_arguments)

    assert cut_exit_code == 2
    assert f"\n#299: {repair}\n" in next_out
    assert "cut 299" not in next_out
    assert capsys.readouterr().err == (
        f"ERROR: #299 is itself a child of {parent_repository}#298; "
        "nested containers are not supported\n"
    )
    assert next_exit_code == (0 if parent_kind is body.ItemKind.FEATURE else 3)


@pytest.mark.parametrize(
    ("top_level_scope", "expected_claim"),
    [
        (None, "aco claim 299 --scope=docs/nested.md --scope='src/it'\"'\"'s here.py'"),
        (("docs/top.md",), "aco claim 299"),
    ],
    ids=["row-scope-only", "own-top-level-scope"],
)
def test_next_names_a_nested_rows_exact_scope_and_that_claim_runs_as_printed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    top_level_scope: tuple[str, ...] | None,
    expected_claim: str,
) -> None:
    """A nested container's one row carrying a scope gets
    a claim on exactly those paths -- or, when the container names its own
    top-level `scope`, the bare claim that derives it (NEXT-03) -- and once
    retyped `next`'s own `Run:` line names that same claim, which runs
    unchanged in a real shell, and the parallel tail reads the paths that
    claim occupies instead of collapsing to unknown (NEXT-16)."""
    row_scope = ("docs/nested.md", "src/it's here.py")
    row = [{"index": 1, "title": "Scheibe Z", "scope": list(row_scope)}]
    nested_contract = (
        complete_contract("keiner", slice=row)
        if top_level_scope is None
        else complete_contract("keiner", slice=row, scope=list(top_level_scope))
    )
    nested = Issue(
        299,
        "Nested epic",
        (),
        nested_contract,
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=1,
        children_total=1,
    )
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=(nested,))
    client.children = {299: (ChildItem(300, ChildState.CLOSED),)}
    client.parents[299] = workboard.ParentIssue(
        workboard.IssueReference(REPOSITORY, 298), "", body.ItemKind.CONTAINER
    )

    next_exit_code = issue_claim.main(["--repo", REPOSITORY, "next"])
    repair = capsys.readouterr().out.split("\n#299: ", 1)[1].splitlines()[0]
    claim_advice = repair.split(" and claim it with ", 1)[1]
    retyped = replace(nested, kind=body.ItemKind.TASK, children_closed=None, children_total=None)
    _configured_board_client(monkeypatch, tmp_path, open_issues=(retyped,))
    retyped_exit_code = issue_claim.main(["--repo", REPOSITORY, "next"])
    retyped_out = capsys.readouterr().out
    run_line = retyped_out.split("\nRun: ", 1)[1].splitlines()[0]
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda arguments, **_kwargs: request(issue=299, scope=tuple(arguments.scope or ())),
    )
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
    bash_exit_code, claim_arguments = arguments_bash_hands_aco(run_line, tmp_path)
    claim_exit_code = issue_claim.main(["--repo", REPOSITORY, *claim_arguments])

    assert (claim_advice, run_line) == (f"{expected_claim} --out-of-order <reason>", expected_claim)
    assert "\nparallel: none\nscope unknown: none\n" in retyped_out
    assert (next_exit_code, retyped_exit_code, bash_exit_code, claim_exit_code) == (
        3,
        0,
        0,
        0,
    ), capsys.readouterr().err
    claimed = store.fetch_state(worktree=Path("."), remote="origin").claims
    assert tuple(claim.scope for claim in claimed.values()) == (top_level_scope or row_scope,)


_WIDE_SCOPE = ("src/a.py", "src/b.py", "src/c.py", "src/d.py", "src/e.py")


@pytest.mark.parametrize(
    ("item_body", "scope", "stands_in_lane", "expected_run", "expected_branch"),
    [
        pytest.param(
            _state_ref_item_body("Fresh Slug Title", scope=["src/x.py"]),
            ("src/x.py",),
            False,
            "aco start aco-00013a --slug=fresh-slug-title",
            _START_BRANCH,
            id="default_branch_checkout_starts",
        ),
        pytest.param(
            _state_ref_item_body("Fresh Slug Title", scope=["src/x.py"]),
            ("src/x.py",),
            True,
            "aco claim aco-00013a",
            _START_BRANCH,
            id="linked_worktree_claims",
        ),
        pytest.param(
            _state_ref_item_body("!!! ???", scope=["src/x.py"]),
            ("src/x.py",),
            False,
            "aco start aco-00013a --slug=aco-00013a",
            "codex/issue-314-aco-00013a",
            id="slugless_title_starts_on_the_id_slug",
        ),
        pytest.param(
            _state_ref_item_body("Fresh Slug Title", scope=list(_WIDE_SCOPE)),
            _WIDE_SCOPE,
            False,
            "aco start aco-00013a --slug=fresh-slug-title --whole <reason>",
            _START_BRANCH,
            id="wide_scope_without_whole_starts_with_a_reason",
        ),
        pytest.param(
            _state_ref_item_body("Fresh Slug Title", scope=list(_WIDE_SCOPE)),
            _WIDE_SCOPE,
            True,
            "aco claim aco-00013a --whole <reason>",
            _START_BRANCH,
            id="wide_scope_without_whole_claims_with_a_reason",
        ),
        pytest.param(
            _state_ref_item_body(
                "Fresh Slug Title", scope=list(_WIDE_SCOPE), whole="One sweep over five files."
            ),
            _WIDE_SCOPE,
            True,
            "aco claim aco-00013a",
            _START_BRANCH,
            id="wide_scope_with_whole_claims_as_is",
        ),
        pytest.param(
            _state_ref_item_body("Fresh Slug Title", scope=["src"]),
            ("src",),
            False,
            "aco start aco-00013a --slug=fresh-slug-title --whole <reason>",
            _START_BRANCH,
            id="directory_scope_without_whole_starts_with_a_reason",
        ),
        pytest.param(
            _state_ref_item_body("Fresh Slug Title", scope=["src"]),
            ("src",),
            True,
            "aco claim aco-00013a --whole <reason>",
            _START_BRANCH,
            id="directory_scope_without_whole_claims_with_a_reason",
        ),
    ],
)
def test_next_advises_a_pull_that_runs_as_printed_where_it_stands(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    item_body: str,
    scope: tuple[str, ...],
    stands_in_lane: bool,
    expected_run: str,
    expected_branch: str,
) -> None:
    """From the default branch's
    checkout, where `claim` refuses, `next` advises `start` with the slug
    `start` derives from the title, else the item id's own; from a linked
    lane worktree it advises `claim`. A scope the width gate calls wide --
    past three paths, or naming the trunk's `src` directory -- without a
    body `whole` adds `--whole <reason>`. With the reason filled in, the
    line runs in bash and claims the item on the lane branch."""
    repo, _remote, _seeded = _real_state_ref_repository(monkeypatch, tmp_path, {314: item_body})
    (repo / "src").mkdir()
    (repo / "src" / "x.py").write_text("x = 1\n")
    real_git(repo, "add", "src/x.py")
    real_git(repo, "commit", "-q", "-m", "version src/x.py")
    push_repository_trunk(repo, "origin")
    if stands_in_lane:
        lane = tmp_path / "lane"
        real_git(repo, "worktree", "add", "-q", "-b", _START_BRANCH, str(lane))
        redirect_toplevel(monkeypatch, lane)
        monkeypatch.chdir(lane)

    next_exit_code = issue_claim.main(["next"])
    run_line = capsys.readouterr().out.split("\nRun: ", 1)[1].splitlines()[0]
    filled_line = run_line.replace("<reason>", "'One sweep over five files.'")
    bash_exit_code, pull_arguments = arguments_bash_hands_aco(filled_line, tmp_path)
    pull_exit_code = issue_claim.main(pull_arguments)

    assert (run_line, next_exit_code, bash_exit_code, pull_exit_code) == (expected_run, 0, 0, 0)
    claims = store.fetch_state(worktree=repo, remote="origin").claims
    assert tuple((claim.branch, claim.scope) for claim in claims.values()) == (
        (expected_branch, scope),
    )


def test_next_refuses_a_scope_read_git_fails_instead_of_advising_a_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """NEXT-42: a git failure reading the top item's scope never lets a
    directory look like a file; `next` refuses with git's detail and prints
    no `Next:` or `Run:` line."""
    _real_state_ref_repository(
        monkeypatch, tmp_path, {314: _state_ref_item_body("Fresh Slug Title", scope=["src"])}
    )
    stub_one_git_call(
        monkeypatch,
        ["ls-tree", "--full-tree", "HEAD", "--", "src"],
        exit_status=128,
        stderr=SCOPE_READ_FAILURE,
    )

    status = issue_claim.main(["next"])

    captured = capsys.readouterr()
    assert (status, captured.err) == (2, f"ERROR: {SCOPE_READ_FAILURE}\n")
    assert "Next:" not in captured.out
    assert "Run:" not in captured.out


def _state_ref_container_body(title: str, *slice_titles: str, parent: int | None = None) -> str:
    rows = [
        {"index": index, "title": row, "done_when": "D"}
        for index, row in enumerate(slice_titles, start=1)
    ]
    return _state_ref_item_body(title, kind=body.ItemKind.CONTAINER, parent=parent, slice=rows)


def _printed_line_after(out: str, marker: str) -> str:
    return out.split(marker, 1)[1].splitlines()[0]


@pytest.mark.parametrize(
    "advice_marker",
    [
        pytest.param("\nNext: ", id="first_actions_cut"),
        pytest.param(
            f'\n{items.format_item_id(41)}: cut slice "-später"; run ',
            id="a_skipped_containers_cut",
        ),
    ],
)
def test_state_ref_next_prints_cuts_bash_runs_as_printed_and_cut_accepts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    advice_marker: str,
) -> None:
    """Under a state-ref board a slice
    title starting with `-` still reaches the child whole, and a second
    cuttable container behind the first action is named under `SKIPPED` with
    its own `cut`, never `container; claim a child` -- each command running
    unchanged in a real shell."""
    _real_state_ref_repository(
        monkeypatch,
        tmp_path,
        {
            40: _state_ref_container_body("First epic", "-draft"),
            41: _state_ref_container_body("Second epic", "-später"),
        },
    )

    next_exit_code = issue_claim.main(["next"])
    advice = _printed_line_after(capsys.readouterr().out, advice_marker)
    bash_exit_code, cut_arguments = arguments_bash_hands_aco(advice, tmp_path)
    cut_exit_code = issue_claim.main(cut_arguments)

    assert (next_exit_code, bash_exit_code, cut_exit_code) == (0, 0, 0), capsys.readouterr().err


@pytest.mark.parametrize(
    ("field", "text"),
    [
        *(
            pytest.param("title", f"Line one{line_break}Line two", id=f"title-{name}")
            for line_break, name in (
                ("\n", "LF"),
                ("\r", "CR"),
                ("\f", "FF"),
                ("\u0085", "NEL"),
                ("\u2028", "LS"),
                ("\u2029", "PS"),
            )
        ),
        pytest.param("title", "Line one\n", id="title-trailing-LF"),
        pytest.param("title", "Retitle\x1b]0;pwned\x07", id="title-OSC-BEL"),
        pytest.param("title", "Clear\x1b[2J", id="title-CSI"),
        pytest.param("title", "Rubout\x7f", id="title-DEL"),
        *(
            pytest.param("title", f"Flip{control}side", id=f"title-{codepoint}")
            for control, codepoint in BIDI_AND_ZERO_WIDTH_CONTROLS
        ),
        pytest.param("done_when", "Line one\vline two", id="done_when-VT"),
        pytest.param("done_when", "Flip\N{RIGHT-TO-LEFT OVERRIDE}side", id="done_when-U+202E"),
    ],
)
def test_state_ref_next_names_a_slice_row_line_with_a_control_character_instead_of_a_cut(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    field: str,
    text: str,
) -> None:
    """A first
    uncut row whose title or `done_when`, stored before `item edit` refused
    it, holds a line break or another control character would split the
    printed `cut` over two lines, hand it to the terminal raw, or be refused
    by that very `cut` (CUT-39), so `next` prints no `cut` for it and names
    the row to fix instead."""
    row = {"index": 1, "title": "Slice", "done_when": "D", field: text}
    _real_state_ref_repository(
        monkeypatch,
        tmp_path,
        {50: _state_ref_item_body("Epic", kind=body.ItemKind.CONTAINER, slice=[row])},
    )

    exit_code = issue_claim.main(["next"])
    out = capsys.readouterr().out

    assert exit_code == 3
    assert (
        f"\n{items.format_item_id(50)}: slice row 1 {field} holds a line break or control "
        "character; make it one printable line\n"
    ) in out
    assert "cut" not in out


def _raw_terminal_controls(text: str) -> set[str]:
    """Every character of the ruled display-control set in
    printed `text`, apart from the newlines that end its own lines: C0 but
    TAB, DEL, C1, U+2028/2029, the bidi controls, the Arabic letter mark,
    the zero-width characters, the word joiner and the tag characters, by
    code point -- stated here rather than asked of
    `protocol.is_display_control`, so a narrowed predicate cannot narrow
    this check with it."""
    ruled_code_points = {
        *(code_point for code_point in range(0x00, 0x20) if code_point not in {0x09, 0x0A}),
        *range(0x7F, 0xA0),
        0x2028,
        0x2029,
        0x200E,
        0x200F,
        0x061C,
        *range(0x202A, 0x202F),
        *range(0x2066, 0x206A),
        *range(0x200B, 0x200E),
        0x2060,
        0xFEFF,
        *range(0xE0000, 0xE0080),
    }
    return {character for character in text if ord(character) in ruled_code_points}


def _hostile_work_item_board() -> dict[int, str]:
    """A top work item carrying a window-retitling OSC, a TAB, U+2028, an
    Umlaut, a bidi override (RLO), a bidi isolate (LRI), a zero-width space,
    a C1 CSI, an NBSP, an Arabic letter mark, a word joiner and a tag
    character in its title and a screen-clearing CSI and DEL in its `Next`
    line, beside a cuttable container whose slice title tries to close its
    prose quote and fake a `; run` segment."""
    return {
        10: _state_ref_item_body(
            "evil\x1b]0;pwned\x07\tÜber\N{LINE SEPARATOR}Größe\N{RIGHT-TO-LEFT OVERRIDE}RLO"
            "\N{LEFT-TO-RIGHT ISOLATE}LRI\N{ZERO WIDTH SPACE}ZWSP\x9bCSI\N{NO-BREAK SPACE}NBSP"
            "\N{ARABIC LETTER MARK}ALM\N{WORD JOINER}WJ\N{TAG LATIN CAPITAL LETTER A}TAG",
            next="wipe \x1b[2J then \x7f Größe",
            scope=["docs/a.md"],
        ),
        41: _state_ref_container_body("Epic", 'Größe"; run aco claim 9 \\'),
    }


def _hostile_cut_slice_board() -> dict[int, str]:
    """A cuttable container, the top action, whose `Next` clears the screen."""
    return {
        41: _state_ref_item_body(
            "Epic",
            kind=body.ItemKind.CONTAINER,
            next="cut \x1b[2J now",
            slice=[{"index": 1, "title": "Größe"}],
        )
    }


def _hostile_check_container_board() -> dict[int, str]:
    """A slice-less container, the top action, whose `Next` retitles the
    window."""
    return {
        41: _state_ref_item_body(
            "Epic", kind=body.ItemKind.CONTAINER, next="check \x1b]0;pwned\x07 done_when"
        )
    }


def _hostile_frozen_board() -> dict[int, str]:
    """An item frozen on a window-retitling trigger beside a workable one."""
    return {
        10: _state_ref_item_body("Workable", scope=["docs/a.md"]),
        42: _state_ref_item_body(
            "Frozen",
            frozen_until={"trigger": "thaw\x1b]0;pwned\x07", "ruled_on": date(2026, 9, 27)},
        ),
    }


@pytest.fixture
def hostile_next_board(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A state-ref board of `_hostile_work_item_board`'s items."""
    _real_state_ref_repository(monkeypatch, tmp_path, _hostile_work_item_board())


@pytest.mark.parametrize(
    ("item_bodies", "escaped_line"),
    [
        pytest.param(
            _hostile_work_item_board,
            f'{items.format_item_id(41)}: cut slice "Größe\\"; run aco claim 9 \\\\"; run ',
            id="work-item-top-and-quoted-skipped-slice",
        ),
        pytest.param(
            _hostile_cut_slice_board,
            f"cut_slice {items.format_item_id(41)}: cut \\x1b[2J now\n",
            id="cut-slice-top",
        ),
        pytest.param(
            _hostile_check_container_board,
            "Next: check \\x1b]0;pwned\\x07 done_when\n",
            id="check-container-top",
        ),
        pytest.param(
            _hostile_frozen_board,
            f"{items.format_item_id(42)}: frozen: thaw\\x1b]0;pwned\\x07\n",
            id="frozen-skipped",
        ),
    ],
)
def test_state_ref_next_text_hands_the_terminal_no_raw_control_character(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    item_bodies: Callable[[], dict[int, str]],
    escaped_line: str,
) -> None:
    """Whatever `next` prints -- a work item, a
    `cut_slice` or `check_container` action, a `SKIPPED` reason -- carries
    no control character a terminal would act on, each shown as its escape,
    and a slice title in `SKIPPED` prose sits inside a quote its own `"`
    cannot close."""
    _real_state_ref_repository(monkeypatch, tmp_path, item_bodies())

    exit_code = issue_claim.main(["next"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert _raw_terminal_controls(out) == set()
    assert f"\n{escaped_line}" in f"\n{out}"


@pytest.mark.usefixtures("hostile_next_board")
def test_state_ref_next_json_shares_the_quoted_skipped_prose(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The `SKIPPED` reason is
    prose text and `--json` share, so its quoted slice title carries `"` and
    `\\` escaped."""
    issue_claim.main(["next", "--json"])

    payload = json.loads(capsys.readouterr().out)
    reasons = {skipped["number"]: skipped["reason"] for skipped in payload["skipped"]}
    assert reasons[items.format_item_id(41)].startswith(
        'cut slice "Größe\\"; run aco claim 9 \\\\"; run '
    )


def _printed_title_and_next(out: str) -> tuple[str, str]:
    action_line, next_line = out.splitlines()[:2]
    return action_line.split(": ", 1)[1], next_line.removeprefix("Next: ")


def _json_title_and_next(out: str) -> tuple[str, str]:
    payload = json.loads(out)
    return payload["title"], payload["next"]


@pytest.mark.parametrize(
    ("arguments", "read_title_and_next", "shown"),
    [
        pytest.param(
            ["next"],
            _printed_title_and_next,
            (
                "evil\\x1b]0;pwned\\x07\tÜber\N{REVERSE SOLIDUS}u2028Größe"
                "\N{REVERSE SOLIDUS}u202eRLO\N{REVERSE SOLIDUS}u2066LRI"
                "\N{REVERSE SOLIDUS}u200bZWSP\\x9bCSI\N{NO-BREAK SPACE}NBSP"
                "\N{REVERSE SOLIDUS}u061cALM\N{REVERSE SOLIDUS}u2060WJ"
                "\N{REVERSE SOLIDUS}U000e0041TAG",
                "wipe \\x1b[2J then \\x7f Größe",
            ),
            id="text-escapes-controls",
        ),
        pytest.param(
            ["next", "--json"],
            _json_title_and_next,
            (
                "evil\x1b]0;pwned\x07\tÜber\N{LINE SEPARATOR}Größe\N{RIGHT-TO-LEFT OVERRIDE}RLO"
                "\N{LEFT-TO-RIGHT ISOLATE}LRI\N{ZERO WIDTH SPACE}ZWSP\x9bCSI\N{NO-BREAK SPACE}NBSP"
                "\N{ARABIC LETTER MARK}ALM\N{WORD JOINER}WJ\N{TAG LATIN CAPITAL LETTER A}TAG",
                "wipe \x1b[2J then \x7f Größe",
            ),
            id="json-as-stored",
        ),
    ],
)
@pytest.mark.usefixtures("hostile_next_board")
def test_state_ref_next_shows_foreign_title_and_next_line_as_its_format_carries_them(
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    read_title_and_next: Callable[[str], tuple[str, str]],
    shown: tuple[str, str],
) -> None:
    """Text shows each
    control character, U+2028, RLO, LRI, ZWSP, U+061C, U+2060 and a tag
    character as its printable escape, TAB, NBSP and the Umlaut as they are;
    `--json` leaves escaping to JSON, so a reader gets both back exactly as
    stored."""
    issue_claim.main(arguments)

    assert read_title_and_next(capsys.readouterr().out) == shown


def _release_freeing_titled(
    monkeypatch: pytest.MonkeyPatch, _tmp_path: Path, title: str
) -> list[str]:
    """A `--merged` release that frees one item titled `title`, its `next:`."""
    client = merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")
    client.closed_issues.add(WORK_ITEM_ISSUE)
    monkeypatch.setattr(board_read, "fetch_issue_reference", _LIVE_FETCH_ISSUE_REFERENCE)
    freed, client.board_dependencies = blocked_issue(81, title, _landed_dependency())
    client.board_issues = (freed,)
    return ["--repo", REPOSITORY, "release", str(WORK_ITEM_ISSUE), "--merged", "12"]


def _rulings_of_titled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, title: str) -> list[str]:
    """One item titled `title` whose one open expectation line says `title`."""
    contract = complete_contract("Rule it.", expectation=[proposed_expectation(title)])
    _configured_board_client(monkeypatch, tmp_path, open_issues=(board_issue(10, title, contract),))
    _write_block_pin(tmp_path)
    return ["--repo", REPOSITORY, "rulings"]


def _claim_past_titled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, title: str) -> list[str]:
    """A claim of #10 past a higher-ranked #11 titled `title`, out of order."""
    lower = board_issue(10, "Lower work", complete_contract("Claim #10."))
    top = board_issue(11, title, complete_contract("Claim #11.", scope=["src/top.py"]))
    dependent, dependent_blockers = blocked_issue(
        12, "Depends on top", block_dependency(11), next_step="Claim #12."
    )
    _configured_board_client(
        monkeypatch, tmp_path, open_issues=(lower, top, dependent), dependencies=dependent_blockers
    )
    reason = "hotfix first"
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: replace(
            request(issue=10, scope=("src/lower.py",)), out_of_order_reason=reason
        ),
    )
    return [
        "--repo",
        REPOSITORY,
        "claim",
        "10",
        "--agent",
        "Codex Sol",
        "--scope",
        "src/lower.py",
        "--out-of-order",
        reason,
    ]


def _next_under_board_config_keyed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, key: str
) -> list[str]:
    """`next` against a board configuration carrying the unknown key `key`."""
    _configured_board_client(monkeypatch, tmp_path)
    write_repository_config(tmp_path, f"{json.dumps(key, ensure_ascii=False)} = 1\n")
    return ["--repo", REPOSITORY, "next"]


@pytest.mark.parametrize(
    ("arrange", "shown_as"),
    [
        pytest.param(_release_freeing_titled, "next: #81 score {score}: {escaped}\n", id="release"),
        pytest.param(
            _rulings_of_titled,
            "#10 1/1: {escaped}\n  1 open: {escaped_on_one_line}\n",
            id="rulings",
        ),
        pytest.param(
            _claim_past_titled,
            "WARNING: higher-priority actionable item #11 (score {score}) is free: {escaped};",
            id="claim-out-of-order-warning",
        ),
        pytest.param(
            _next_under_board_config_keyed,
            "ERROR: board configuration {config} has unknown top-level key {escaped}\n",
            id="board-config-unknown-key",
        ),
    ],
)
def test_one_line_printers_show_foreign_text_as_next_escapes_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    arrange: Callable[[pytest.MonkeyPatch, Path, str], list[str]],
    shown_as: str,
) -> None:
    """Spec: RUL-02, RUL-11 -- text controls and folded summaries.

    `release`'s `next:` line, the `rulings`
    text, `claim`'s out-of-order warning and the board configuration's
    unknown-key refusal show RLO, U+061C, U+2060 and a tag character as
    their printable escapes, while TAB and the Umlaut stay as they are;
    the `rulings` line summary (RUL-11) escapes the same controls after
    RUL-02 folds its whitespace onto one line."""
    foreign = (
        "Über\N{RIGHT-TO-LEFT OVERRIDE}RLO\N{ARABIC LETTER MARK}ALM"
        "\N{WORD JOINER}WJ\N{TAG LATIN CAPITAL LETTER A}TAG\tGröße"
    )
    escaped = (
        "Über\N{REVERSE SOLIDUS}u202eRLO\N{REVERSE SOLIDUS}u061cALM"
        "\N{REVERSE SOLIDUS}u2060WJ\N{REVERSE SOLIDUS}U000e0041TAG\tGröße"
    )
    escaped_on_one_line = escaped.replace("\t", " ")
    arguments = arrange(monkeypatch, tmp_path, foreign)

    issue_claim.main(arguments)
    captured = capsys.readouterr()
    printed = captured.out + captured.err

    assert _raw_terminal_controls(printed) == set()
    expected = re.escape(shown_as).replace(r"\{escaped\}", re.escape(escaped))
    expected = expected.replace(r"\{escaped_on_one_line\}", re.escape(escaped_on_one_line))
    expected = expected.replace(r"\{score\}", r"-?\d+").replace(r"\{config\}", r"\S+")
    assert re.search(expected, printed), printed


_FOREIGN_MULTI_LINE_TEXT = (
    "Hallo\x1b[2J Welt\tÜber\N{RIGHT-TO-LEFT OVERRIDE}RLO\n\N{WORD JOINER}WJ Größe"
)


def _foreign_body_item(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[str, str]:
    """A state-ref item whose stored body opens with the foreign lines;
    returns its id and that stored body."""
    stored = f"{_FOREIGN_MULTI_LINE_TEXT}\n\n{_state_ref_item_body('Foreign body')}"
    _real_state_ref_repository(monkeypatch, tmp_path, {10: stored})
    return items.format_item_id(10), stored


def _brief_of_foreign_body(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    item, _stored = _foreign_body_item(monkeypatch, tmp_path)
    return ["brief", item]


def _item_show_of_foreign_body(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    item, _stored = _foreign_body_item(monkeypatch, tmp_path)
    return ["item", "show", item]


def _brief_step_under_brief_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str
) -> list[str]:
    """`brief --step build` against a tracked `.aco/brief.toml`
    holding `content`."""
    item, _stored = _foreign_body_item(monkeypatch, tmp_path)
    repo = Path.cwd()
    write_repository_config(repo, content, path=workboard.BRIEF_CONFIG_PATH)
    real_git(repo, "add", workboard.BRIEF_CONFIG_PATH.as_posix())
    monkeypatch.setattr(checkout, "path_is_tracked", _REAL_PATH_IS_TRACKED)
    return ["brief", item, "--step", "build"]


def _brief_config_with_foreign_top_level_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> list[str]:
    key = json.dumps(_FOREIGN_MULTI_LINE_TEXT, ensure_ascii=False)
    return _brief_step_under_brief_config(monkeypatch, tmp_path, f"{key} = 1\n")


def _brief_config_with_foreign_step_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> list[str]:
    key = json.dumps(_FOREIGN_MULTI_LINE_TEXT, ensure_ascii=False)
    return _brief_step_under_brief_config(monkeypatch, tmp_path, f"[build]\n{key} = 1\n")


def _brief_config_with_foreign_rule_and_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> list[str]:
    entry = json.dumps(_FOREIGN_MULTI_LINE_TEXT, ensure_ascii=False)
    content = f"[build]\nrules = [{entry}]\nchecks = [{entry}]\n"
    return _brief_step_under_brief_config(monkeypatch, tmp_path, content)


@pytest.mark.parametrize(
    ("arrange", "shown_as"),
    [
        pytest.param(_brief_of_foreign_body, "{block}\n\nProse.\n", id="brief"),
        pytest.param(
            _brief_config_with_foreign_rule_and_check,
            "\nRULES\n{line}\n\nCHECKS\n{line}\n",
            id="brief-step-rules-and-checks",
        ),
        pytest.param(_item_show_of_foreign_body, "{block}\n\nProse.\n", id="item-show"),
        pytest.param(
            _brief_config_with_foreign_top_level_key,
            "ERROR: brief configuration {config} has unknown top-level key {line}\n",
            id="brief-config-top-level-key",
        ),
        pytest.param(
            _brief_config_with_foreign_step_key,
            "ERROR: brief configuration {config} [build] has unknown key {line}\n",
            id="brief-config-step-key",
        ),
    ],
)
def test_body_and_brief_config_printers_show_foreign_text_as_next_escapes_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    arrange: Callable[[pytest.MonkeyPatch, Path], list[str]],
    shown_as: str,
) -> None:
    """`brief` and `item show` print a stored body
    with ESC, RLO and U+2060 as their printable escapes while its line
    feeds, TAB and Umlauts stay; the brief configuration's unknown-key
    refusals and `brief --step`'s rules and checks escape the line feed
    too, as every one-line printer does (BRIEF-23, ITEM-56, BRIEF-24;
    BRIEF-25)."""
    block = "Hallo\\x1b[2J Welt\tÜber\\u202eRLO\n\\u2060WJ Größe"
    line = "Hallo\\x1b[2J Welt\tÜber\\u202eRLO\\n\\u2060WJ Größe"
    arguments = arrange(monkeypatch, tmp_path)

    issue_claim.main(arguments)
    captured = capsys.readouterr()
    printed = captured.out + captured.err

    assert _raw_terminal_controls(printed) == set()
    expected = re.escape(shown_as).replace(r"\{block\}", re.escape(block))
    expected = expected.replace(r"\{line\}", re.escape(line)).replace(r"\{config\}", r"\S+")
    assert re.search(expected, printed), printed


@pytest.mark.parametrize(
    ("arrange", "refusal_after_path"),
    [
        pytest.param(
            _brief_config_with_foreign_top_level_key,
            " has unknown top-level key ",
            id="brief-config-top-level-key",
        ),
        pytest.param(
            _brief_config_with_foreign_step_key,
            " [build] has unknown key ",
            id="brief-config-step-key",
        ),
    ],
)
def test_brief_config_unknown_key_json_refusal_carries_the_escaped_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    arrange: Callable[[pytest.MonkeyPatch, Path], list[str]],
    refusal_after_path: str,
) -> None:
    """Under `--json` the brief configuration's
    unknown-key refusal is the `unavailable` envelope, its message and
    stderr naming the key as `next` escapes it (BRIEF-24, BRIEF-17)."""
    arguments = arrange(monkeypatch, tmp_path)
    config = Path.cwd() / workboard.BRIEF_CONFIG_PATH
    key = "Hallo\\x1b[2J Welt\tÜber\\u202eRLO\\n\\u2060WJ Größe"
    sentence = f"brief configuration {config}{refusal_after_path}{key}"

    status = issue_claim.main([*arguments, "--json"])

    captured = capsys.readouterr()
    refusal = {"ok": False, "reason": "unavailable", "message": sentence}
    assert (status, captured.err) == (2, f"ERROR: {sentence}\n")
    assert json.loads(captured.out) == refusal


@pytest.mark.parametrize(
    ("arrange", "key"),
    [
        pytest.param(_brief_of_foreign_body, "body", id="brief"),
        pytest.param(_item_show_of_foreign_body, "body", id="item-show"),
        pytest.param(_brief_config_with_foreign_rule_and_check, "rules", id="brief-step-rules"),
        pytest.param(_brief_config_with_foreign_rule_and_check, "checks", id="brief-step-checks"),
    ],
)
def test_foreign_text_printers_json_keep_the_foreign_lines_as_stored(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    arrange: Callable[[pytest.MonkeyPatch, Path], list[str]],
    key: str,
) -> None:
    """`--json` leaves a body's, a
    rule's and a check's escaping to JSON, so a reader gets the foreign
    lines back exactly as stored (BRIEF-23, ITEM-56, BRIEF-25): in the
    body, or as one whole `rules`/`checks` entry."""
    arguments = arrange(monkeypatch, tmp_path)

    issue_claim.main([*arguments, "--json"])

    assert _FOREIGN_MULTI_LINE_TEXT in json.loads(capsys.readouterr().out)[key]


def test_state_ref_next_claim_in_a_skipped_reason_runs_past_a_higher_ranked_item(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A nested container's repair names a claim that the
    ordering rule would refuse while a higher-ranked item is free, so it
    carries `--out-of-order <reason>`; filled in, the retype and the claim
    both run unchanged in a real shell and succeed."""
    repo, _remote, _seeded = _real_state_ref_repository(
        monkeypatch,
        tmp_path,
        {
            10: _state_ref_item_body("Top work", scope=["docs/top.md"]),
            20: _state_ref_container_body("Epic"),
            21: _state_ref_container_body("Nested epic", "Scheibe Z", parent=20),
        },
    )
    lane = tmp_path / "repo-worktrees" / "issue-21-nested"
    real_git(repo, "worktree", "add", "-q", str(lane), "-b", "codex/issue-21-nested")
    redirect_toplevel(monkeypatch, lane)
    monkeypatch.chdir(lane)
    nested = items.format_item_id(21)

    next_exit_code = issue_claim.main(["next"])
    repair = _printed_line_after(capsys.readouterr().out, f"\n{nested}: ")
    retype, claim = repair.removeprefix("nested container, which cut refuses; run ").split(
        " and claim it with "
    )
    retype_bash_exit_code, retype_arguments = arguments_bash_hands_aco(retype, tmp_path)
    retype_exit_code = issue_claim.main(retype_arguments)
    filled_claim = claim.replace("<paths>", "docs/nested.md").replace(
        "<reason>", shlex.quote("the operator wants it first")
    )
    claim_bash_exit_code, claim_arguments = arguments_bash_hands_aco(filled_claim, tmp_path)
    in_order_exit_code = issue_claim.main(claim_arguments[:-2])
    in_order_refusal = capsys.readouterr().err
    claim_exit_code = issue_claim.main(claim_arguments)

    assert claim_arguments[-2] == "--out-of-order"
    assert "use --out-of-order REASON to proceed" in in_order_refusal
    assert (
        next_exit_code,
        retype_bash_exit_code,
        retype_exit_code,
        claim_bash_exit_code,
        in_order_exit_code,
        claim_exit_code,
    ) == (0, 0, 0, 0, 2, 0), capsys.readouterr().err


def test_state_ref_next_pulls_past_an_item_waiting_on_the_operator_and_claim_does_not_warn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The record's `needs-operator` label keeps the
    top-ranked item out of `next`'s pull and `claim`'s precedence check;
    `next` names it on its own line, and the pullable item claims as
    printed, without `--out-of-order`."""
    repo, _remote, _seeded = _real_state_ref_repository(
        monkeypatch,
        tmp_path,
        {
            10: _state_ref_item_body(
                "Operator ruling",
                labels=("security", NEEDS_OPERATOR_LABEL),
                scope=["docs/ruling.md"],
            ),
            11: _state_ref_item_body("Pullable work", scope=["docs/work.md"]),
        },
    )
    lane = tmp_path / "repo-worktrees" / "issue-11-work"
    real_git(repo, "worktree", "add", "-q", str(lane), "-b", "codex/issue-11-work")
    redirect_toplevel(monkeypatch, lane)
    monkeypatch.chdir(lane)
    waiting, pullable = items.format_item_id(10), items.format_item_id(11)

    next_exit_code = issue_claim.main(["next"])
    printed = capsys.readouterr().out
    claim = _printed_line_after(printed, "\nRun: ")
    claim_bash_exit_code, claim_arguments = arguments_bash_hands_aco(claim, tmp_path)
    claim_exit_code = issue_claim.main(claim_arguments)
    claim_output = capsys.readouterr()

    assert printed.startswith(f"{pullable} score")
    assert f"\nwaiting on operator: {waiting}\n" in printed
    assert "SKIPPED" not in printed
    assert "WARNING" not in claim_output.out + claim_output.err
    assert (next_exit_code, claim_bash_exit_code, claim_exit_code) == (0, 0, 0), claim_output.err


def test_state_ref_next_json_names_items_by_the_ids_its_text_prints(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Under a state-ref board every item `next --json`
    names -- the action, a `parallel` candidate, a `scope_unknown` one, a
    `close` one, a `skipped` one -- is the `aco-xxxxxx` id the text prints,
    never the integer behind it."""
    _real_state_ref_repository(
        monkeypatch,
        tmp_path,
        {
            10: _state_ref_item_body("Top work", scope=["docs/top.md"]),
            11: _state_ref_item_body("Side work", scope=["docs/side.md"]),
            12: _state_ref_item_body("Unscoped work"),
            13: _state_ref_container_body("Finished epic"),
            14: _state_ref_container_body("Running epic"),
            15: _state_ref_item_body("Child work", parent=14, scope=["docs/child.md"]),
        },
    )

    exit_code = issue_claim.main(["next", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert _next_json_item_references(payload) == (
        items.format_item_id(10),
        [items.format_item_id(11), items.format_item_id(15)],
        [items.format_item_id(12)],
        [items.format_item_id(13)],
        [items.format_item_id(14)],
    )


def _next_json_item_references(
    payload: dict[str, object],
) -> tuple[object, list[object], object, object, list[object]]:
    parallel = cast(dict[str, object], payload["parallel"])
    candidates = cast(list[dict[str, object]], parallel["candidates"])
    skipped = cast(list[dict[str, object]], payload["skipped"])
    return (
        payload["number"],
        [candidate["number"] for candidate in candidates],
        parallel["scope_unknown"],
        payload["close"],
        [entry["number"] for entry in skipped],
    )


def test_next_json_names_a_cuttable_container_slice(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    container = Issue(
        181,
        "Epic",
        (),
        complete_contract("Scheibe C", slice=slice_entries("Scheibe C")),
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=2,
        children_total=2,
    )
    _configured_board_client(monkeypatch, tmp_path, open_issues=(container,))

    exit_code = issue_claim.main(["--repo", REPOSITORY, "next", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "cut_slice"
    assert payload["number"] == 181
    assert payload["title"] == "Epic"
    assert payload["slice"] == "Scheibe C"
    assert payload["cut_title"] == "Scheibe C"
    assert payload["command"] == "aco cut 181"


def test_next_names_a_closeable_container(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    container, container_children = container_with_children(
        182, closed=3, body=complete_contract("keiner")
    )
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=(container,))
    client.children[182] = container_children

    exit_code = issue_claim.main(["--repo", REPOSITORY, "next"])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "close_container #182: 3/3 children closed, no Next work\n"
        "parallel: none\nscope unknown: none\nclose: #182\n"
    )


def test_next_json_names_a_closeable_container(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    container, container_children = container_with_children(
        183, closed=4, body=complete_contract("keiner")
    )
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=(container,))
    client.children[183] = container_children

    exit_code = issue_claim.main(["--repo", REPOSITORY, "next", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "close_container"
    assert payload["number"] == 183
    assert payload["closed"] == 4
    assert payload["total"] == 4
    assert payload["next_step"] is None
    assert "command" not in payload


def test_next_names_a_container_with_no_slice_row_by_its_own_next_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """An empty slice table is the
    typed statement that there is nothing here to cut, even though the
    container's own `Next` line still names real work. `next` must not
    fabricate `cut --title "<the whole Next paragraph>"` from that prose,
    nor list it under `close:` while that sentence names work:
    it names the container for a
    `done_when` check and its own sentence, and no command."""
    container = Issue(
        187,
        "Epic",
        (),
        complete_contract("Schließen, sobald die letzte Bedingung erfüllt ist."),
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=2,
        children_total=2,
    )
    _configured_board_client(monkeypatch, tmp_path, open_issues=(container,))

    exit_code = issue_claim.main(["--repo", REPOSITORY, "next"])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "check_container #187: no open children; check done_when\n"
        "Next: Schließen, sobald die letzte Bedingung erfüllt ist.\n"
        "parallel: none\nscope unknown: none\nclose: none\n"
    )


def test_next_json_names_a_container_with_no_slice_row_by_its_own_next_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The JSON form of the same case: `reason` is
    `check_container`, never `close_container` while the `Next` line names
    work; `next_step` carries that sentence, `close` stays empty, and no
    `command` or `cut_title` is invented from it."""
    container, container_children = container_with_children(
        188, closed=2, body=complete_contract("Schließen, sobald die letzte Bedingung erfüllt ist.")
    )
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=(container,))
    client.children[188] = container_children

    exit_code = issue_claim.main(["--repo", REPOSITORY, "next", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "check_container"
    assert payload["number"] == 188
    assert payload["closed"] == 2
    assert payload["total"] == 2
    assert payload["next_step"] == "Schließen, sobald die letzte Bedingung erfüllt ist."
    assert payload["close"] == []
    assert "command" not in payload
    assert "cut_title" not in payload


def test_next_caps_the_parallel_text_list_at_three_and_counts_the_rest(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Text cap: five mutually disjoint candidates --
    the text form names only the first three, in board order, plus a
    trailing count; `--json` still carries every one with its full scope."""
    alpha = board_issue(60, "Alpha", complete_contract("Ship Alpha.", scope=["alpha/a.py"]))
    candidates = tuple(
        board_issue(60 + offset, name, complete_contract(f"Ship {name}.", scope=[f"{name}/x.py"]))
        for offset, name in enumerate(("Bravo", "Charlie", "Delta", "Echo", "Foxtrot"), start=1)
    )
    _configured_board_client(monkeypatch, tmp_path, open_issues=(alpha, *candidates))

    exit_code = issue_claim.main(["--repo", REPOSITORY, "next"])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "#60 score -10: Alpha\nNext: Ship Alpha.\nRun: aco claim 60\n"
        "parallel: #61 (1 path), #62 (1 path), #63 (1 path), and 2 more\n"
        "scope unknown: none\nclose: none\n"
    )

    json_exit_code = issue_claim.main(["--repo", REPOSITORY, "next", "--json"])
    assert json_exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["parallel"]["candidates"] == [
        {"number": 61, "scope": ["Bravo/x.py"]},
        {"number": 62, "scope": ["Charlie/x.py"]},
        {"number": 63, "scope": ["Delta/x.py"]},
        {"number": 64, "scope": ["Echo/x.py"]},
        {"number": 65, "scope": ["Foxtrot/x.py"]},
    ]


def test_next_parallel_set_uses_a_cut_proposals_own_row_scope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A cut proposal's own uncut-row scope is what
    `workboard.parallel_set` occupies and checks disjointness against -- exactly like
    a work item's top-level scope, never a second rule. `#82`'s row repeats
    `#80`'s own path and is dropped silently, the same way an overlapping
    work item would be; the scopeless-row collapse into `parallel: unknown`
    is `test_next_names_a_cuttable_container_slice`'s own proof."""
    epic1 = Issue(
        80,
        "Epic1",
        (),
        complete_contract(
            "Cut it.", slice=[{"index": 1, "title": "Slice A", "scope": ["epic/a.py"]}]
        ),
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=0,
        children_total=0,
    )
    epic2 = Issue(
        81,
        "Epic2",
        (),
        complete_contract(
            "Cut it.", slice=[{"index": 1, "title": "Slice B", "scope": ["epic/b.py"]}]
        ),
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=0,
        children_total=0,
    )
    epic3 = Issue(
        82,
        "Epic3",
        (),
        complete_contract(
            "Cut it.", slice=[{"index": 1, "title": "Slice C", "scope": ["epic/a.py"]}]
        ),
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=0,
        children_total=0,
    )
    _configured_board_client(monkeypatch, tmp_path, open_issues=(epic1, epic2, epic3))

    exit_code = issue_claim.main(["--repo", REPOSITORY, "next"])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "cut_slice #80: Cut it.\nNext: aco cut 80\n"
        "parallel: #81 (1 path)\nscope unknown: none\nclose: none\n"
        '\nSKIPPED\n#81: cut slice "Slice B"; run aco cut 81\n'
        '#82: cut slice "Slice C"; run aco cut 82\n'
    )

    json_exit_code = issue_claim.main(["--repo", REPOSITORY, "next", "--json"])
    assert json_exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["parallel"] == {
        "first_scope_unknown": False,
        "candidates": [{"number": 81, "scope": ["epic/b.py"]}],
        "scope_unknown": [],
    }


@pytest.mark.parametrize("as_container", [False, True], ids=["plain-item", "container"])
def test_next_lists_a_labelled_idea_with_a_merged_pull_request_only_under_ideas(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    as_container: bool,
) -> None:
    idea_body_text = complete_contract("Build it.")
    idea = (
        _childless_container(90, idea_body_text, labels=("idea",))
        if as_container
        else board_issue(90, "Landed idea", idea_body_text, labels=("idea",))
    )
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=(idea,))
    monkeypatch.setattr(
        client,
        "list_recent_merged_board_pull_requests",
        lambda _since: (
            workboard.PullRequest(
                150, "Lands it", "Work-Item: #90\n\nCloses #90", "branch", "2026-08-20T00:00:00Z"
            ),
        ),
    )

    assert issue_claim.main(["--repo", REPOSITORY, "next"]) == 3
    assert (
        capsys.readouterr().out == "No actionable item.\n" + _NO_ACTION_NEXT_TAIL + "ideas: #90\n"
    )

    assert issue_claim.main(["--repo", REPOSITORY, "next", "--json"]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert (payload["recovery"], payload["close"], payload["ideas"]) == ([], [], [90])


def test_next_close_names_every_zero_cost_action_regardless_of_rank(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A closable container ranked
    well below the board's top row, and a landed-but-open recovery item,
    both still appear under `close:` -- unconditionally, never gated by
    which row `next` happens to recommend -- and, named there, never again
    under `SKIPPED`, nor under `waiting on operator:`
    when the landed item still carries `needs-operator`."""
    top_ranked = board_issue(
        70,
        "Top ranked work",
        complete_contract("Ship it.", scope=["a"]),
        labels=("security",),
    )
    closable_container = Issue(
        71,
        "Closable epic",
        (),
        complete_contract("keiner"),
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=2,
        children_total=2,
    )
    landed_but_open = board_issue(
        72,
        "Landed but open",
        complete_contract("Close it."),
        labels=(NEEDS_OPERATOR_LABEL,),
    )
    client = _configured_board_client(
        monkeypatch, tmp_path, open_issues=(top_ranked, closable_container, landed_but_open)
    )
    monkeypatch.setattr(
        client,
        "list_recent_merged_board_pull_requests",
        lambda _since: (
            workboard.PullRequest(
                150, "Lands it", "Work-Item: #72\n\nCloses #72", "branch", "2026-08-20T00:00:00Z"
            ),
        ),
    )

    exit_code = issue_claim.main(["--repo", REPOSITORY, "next"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert out.startswith(f"RECOVERY\n#72: {workboard.RECOVERY_STEP}\n\n")
    assert out.splitlines()[0:2] == ["RECOVERY", f"#72: {workboard.RECOVERY_STEP}"]
    assert "#70 score" in out
    assert out.endswith("close: #71, #72\n")

    json_exit_code = issue_claim.main(["--repo", REPOSITORY, "next", "--json"])
    assert json_exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert (payload["close"], payload["skipped"], payload["waiting_on_operator"]) == (
        [71, 72],
        [],
        [],
    )


_RECOVERY_SHARED_SCOPE = "b"


def test_next_parallel_set_never_lets_a_recovery_item_occupy_or_candidate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A landed-but-open item is `workboard.zero_cost_closes`'
    own domain, never `workboard.parallel_set`'s. `landed_but_open` (#71) and
    `free_item` (#72) name the same scope, and board order visits #71
    first -- pre-fix, the walk occupied that scope for #71 and silently
    dropped #72 as "overlapping", even though #71 was never real work in
    flight. #72 must still surface in `parallel:`, and #71 only under
    `close:`, never as a candidate of its own."""
    top_ranked = board_issue(
        70, "Top ranked work", complete_contract("Ship it.", scope=["a"]), labels=("security",)
    )
    landed_but_open = board_issue(
        71, "Landed but open", complete_contract("Close it.", scope=[_RECOVERY_SHARED_SCOPE])
    )
    free_item = board_issue(
        72, "Free item", complete_contract("Ship it too.", scope=[_RECOVERY_SHARED_SCOPE])
    )
    client = _configured_board_client(
        monkeypatch, tmp_path, open_issues=(top_ranked, landed_but_open, free_item)
    )
    monkeypatch.setattr(
        client,
        "list_recent_merged_board_pull_requests",
        lambda _since: (
            workboard.PullRequest(
                150, "Lands it", "Work-Item: #71\n\nCloses #71", "branch", "2026-08-20T00:00:00Z"
            ),
        ),
    )

    exit_code = issue_claim.main(["--repo", REPOSITORY, "next"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "#70 score" in out
    assert "parallel: #72 (1 path)\n" in out
    assert "close: #71\n" in out
    assert "#71 (1 path)" not in out

    json_exit_code = issue_claim.main(["--repo", REPOSITORY, "next", "--json"])
    assert json_exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["parallel"] == {
        "first_scope_unknown": False,
        "candidates": [{"number": 72, "scope": [_RECOVERY_SHARED_SCOPE]}],
        "scope_unknown": [],
    }
    assert payload["close"] == [71]


def test_board_queries_merged_pull_requests_back_to_the_oldest_open_issue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old_epic = replace(
        board_issue(70, "Epic open for months", complete_contract("Cut the next slice.")),
        created_at="2026-06-01T00:00:00Z",
    )
    recent_issue = board_issue(71, "Recently filed work", complete_contract("Ship it."))
    client = _MinimalForgeReader(open_issues=(old_epic, recent_issue))
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())

    board_read.build_board(run_context_over(client), ())

    # A fixed 14-day window (now - 14 days = 2026-08-07) would have missed
    # anything the six-month-old epic's own slices landed months ago.
    assert client.observed_merged_pull_request_floors == [datetime(2026, 6, 1, tzinfo=UTC)]


def test_board_fetches_children_only_for_container_kinded_issues(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    container = Issue(
        90,
        "Container",
        (),
        "",
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=body.ItemKind.CONTAINER,
        children_closed=0,
        children_total=1,
    )
    plain = board_issue(91, "Plain", complete_contract("Ship it."))
    client = _MinimalForgeReader(
        open_issues=(container, plain),
        children_by_number={90: (ChildItem(92, ChildState.OPEN),)},
    )
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())

    projected = board_read.build_board(run_context_over(client), ())

    assert client.observed_children_lookups == [90]
    container_item = next(item for item in projected.items if item.number == 90)
    assert container_item.container is not None
    assert container_item.container.open_children == (ChildItem(92, ChildState.OPEN),)


def test_body_contract_checks_names_a_blockless_container_by_its_no_block_defect() -> None:
    raw_body = "## Now\nOld prose.\n\n## Next\nDo the thing.\n"
    blockless = replace(
        board_issue(201, "Blockless container", raw_body),
        kind=body.ItemKind.CONTAINER,
        children_closed=0,
        children_total=0,
    )
    projected = projected_board(
        (blockless,),
        (),
        (),
        (),
        workboard.BoardConfig(),
        now=datetime(2026, 8, 21, tzinfo=UTC),
    )
    item = next(item for item in projected.items if item.number == 201)

    checks = cmd_claim._body_checks(item, body.Storage.GITHUB)

    assert checks == (
        cmd_claim._SliceCheck("error", "body-contract", "body malformed: aco: no aco block"),
    )


def test_body_contract_checks_names_a_malformed_body_by_its_first_defect() -> None:
    malformed_body = block_body('version = 2\nnow = "N"\nnext = "X"\ndone_when = "D"\n')
    malformed = board_issue(202, "Malformed", malformed_body)
    projected = projected_board(
        (malformed,),
        (),
        (),
        (),
        workboard.BoardConfig(),
        now=datetime(2026, 8, 21, tzinfo=UTC),
    )
    item = next(item for item in projected.items if item.number == 202)

    checks = cmd_claim._body_checks(item, body.Storage.GITHUB)

    assert checks == (
        cmd_claim._SliceCheck(
            "error", "body-contract", "body malformed: version: version must be exactly 1"
        ),
    )


def test_board_shows_freed_from_a_sole_closed_local_dependency_and_claim_reaches_mutation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A complete block item whose sole dependency is closed passes body
    checks and reaches claim mutation: FREED on the projection,
    and `claim` (without `--out-of-order`) actually posts a claim comment
    through the fake, not just a non-blocked projection."""
    closed_dependency = (
        block_dependency(
            151, state=BlockerState.CLOSED, closed_at=datetime(2026, 8, 20, tzinfo=UTC)
        ),
    )
    projected = projected_board(
        (board_issue(301, "Freed", block_body(MINIMAL_BLOCK_TOML)),),
        (),
        (),
        (),
        workboard.BoardConfig(),
        now=datetime(2026, 8, 21, tzinfo=UTC),
        dependencies={301: closed_dependency},
    )
    item = next(item for item in projected.items if item.number == 301)
    assert item.open_blockers == ()
    assert item.freed_on == datetime(2026, 8, 20, tzinfo=UTC)
    assert item.actionable is True

    live_issue = replace(
        board_issue(301, "Freed by a closed dependency", block_body(MINIMAL_BLOCK_TOML)),
        blocked_by_count=1,
    )
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=(live_issue,))
    _write_block_pin(tmp_path)
    client.board_dependencies = {301: closed_dependency}
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=301, scope=("src/work.py",)),
    )

    exit_code = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "301",
            "--agent",
            "Ada",
            "--scope",
            "src/work.py",
        ]
    )

    assert exit_code == 0
    assert store.fetch_state(worktree=Path("."), remote="origin").claims
    assert "ERROR:" not in capsys.readouterr().err


def test_blocked_check_reports_a_foreign_dependency_and_the_out_of_order_warning() -> None:
    issue = board_issue(304, "Foreign blocked", block_body(MINIMAL_BLOCK_TOML))
    dependencies = {304: (block_dependency(9, repository="overnightworks/other-repo"),)}
    projected = projected_board(
        (issue,),
        (),
        (),
        (),
        workboard.BoardConfig(),
        now=datetime(2026, 8, 21, tzinfo=UTC),
        dependencies=dependencies,
    )
    item = next(item for item in projected.items if item.number == 304)

    error_check = cmd_claim._blocked_check(item, None, REPOSITORY, body.Storage.GITHUB)
    assert error_check == cmd_claim._SliceCheck(
        "error",
        "blocked",
        "#304 is blocked by overnightworks/other-repo#9 (open); "
        "pass --out-of-order REASON to claim it anyway",
        issue=304,
    )
    warning_check = cmd_claim._blocked_check(item, "reason", REPOSITORY, body.Storage.GITHUB)
    assert warning_check is not None
    assert warning_check.level == "warning"


def test_blocked_check_labels_a_local_dependency_under_the_state_ref_pin() -> None:
    """A same-repository blocker prints
    `workboard.item_label`'s own `aco-...` id under `storage = STATE_REF`, the
    same as everywhere else that pin already changes narrative output --
    never the bare `#n` GitHub uses."""
    issue = board_issue(304, "Local blocked", block_body(MINIMAL_BLOCK_TOML))
    dependencies = {304: (block_dependency(9, repository=REPOSITORY),)}
    projected = projected_board(
        (issue,),
        (),
        (),
        (),
        workboard.BoardConfig(),
        now=datetime(2026, 8, 21, tzinfo=UTC),
        dependencies=dependencies,
    )
    item = next(item for item in projected.items if item.number == 304)

    check = cmd_claim._blocked_check(item, None, REPOSITORY, body.Storage.STATE_REF)

    assert check is not None
    assert workboard.item_label(9, body.Storage.STATE_REF) in check.text
    assert "#9" not in check.text


@dataclass
class _MinimalBoardSource:
    """The smallest real `forge.BoardSource`, every read empty, for `fetch_dependencies` tests."""

    repository: forge.RepositoryId = field(default_factory=lambda: github.repository_id(REPOSITORY))
    requests: int = 0
    lists_pull_requests: bool = True
    dependencies_fetcher: Callable[[int], tuple[IssueDependency, ...]] = lambda _number: ()

    def list_open_board_issues(self) -> tuple[Issue, ...]:
        return ()

    def list_board_dependencies(self, number: int) -> tuple[IssueDependency, ...]:
        return self.dependencies_fetcher(number)

    def list_open_board_pull_requests(self) -> tuple[workboard.PullRequest, ...]:
        return ()

    def list_recent_merged_board_pull_requests(
        self, since: datetime
    ) -> tuple[workboard.PullRequest, ...]:
        del since
        return ()

    def list_children(self, number: int) -> tuple[ChildItem, ...]:
        del number
        return ()


def test_fetch_dependencies_bounds_concurrency_at_the_shared_constant() -> None:
    concurrency = board_read.BOARD_CHILD_FETCH_CONCURRENCY
    release = threading.Barrier(concurrency)
    active = 0
    peak = 0
    lock = threading.Lock()
    exceeded = threading.Event()

    def fetch(number: int) -> tuple[IssueDependency, ...]:
        nonlocal active, peak
        del number
        with lock:
            active += 1
            peak = max(peak, active)
            if active > concurrency:
                exceeded.set()
        release.wait(timeout=5)
        with lock:
            active -= 1
        return ()

    client = _MinimalBoardSource(dependencies_fetcher=fetch)

    board_read.fetch_dependencies(client, tuple(range(concurrency * 2)))

    assert not exceeded.is_set()
    assert peak == concurrency


def test_validated_dependencies_refuses_a_length_mismatch() -> None:
    issue = board_issue(305, "Length mismatch", block_body(MINIMAL_BLOCK_TOML))
    issue = replace(issue, blocked_by_count=2)
    fetched = {305: (block_dependency(1),)}

    with pytest.raises(
        forge.ForgeMalformedResponseError,
        match=r"malformed board blocked-by list for #305: listing total_blocked_by=2, "
        r"detail length=1",
    ):
        board_read.validated_dependencies((issue,), fetched)


def test_validated_dependencies_refuses_a_duplicate_dependency() -> None:
    issue = board_issue(306, "Duplicate", block_body(MINIMAL_BLOCK_TOML))
    issue = replace(issue, blocked_by_count=2)
    fetched = {306: (block_dependency(1), block_dependency(1))}

    with pytest.raises(forge.ForgeMalformedResponseError, match="malformed board blocked-by list"):
        board_read.validated_dependencies((issue,), fetched)


def test_next_names_other_work_and_lists_a_labelled_idea_apart(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    idea = board_issue(
        10, "Operator idea", complete_contract("Build it."), labels=("idea", "security")
    )
    work = board_issue(11, "Plain work", complete_contract("Claim #11."))
    _configured_board_client(monkeypatch, tmp_path, open_issues=(idea, work))

    assert issue_claim.main(["--repo", REPOSITORY, "next"]) == 0
    assert capsys.readouterr().out == (
        "#11 score -10: Plain work\nNext: Claim #11.\n"
        "Run: aco claim 11 --scope <paths>\n" + _UNKNOWN_SCOPE_NEXT_TAIL + "ideas: #10\n"
    )

    assert issue_claim.main(["--repo", REPOSITORY, "next", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert (payload["number"], payload["skipped"], payload["ideas"]) == (11, [], [10])


@pytest.mark.parametrize(
    ("body_text", "as_container"),
    [
        pytest.param(idea_body("Make the board clearer."), False, id="empty-projection"),
        pytest.param(complete_contract("Build it."), False, id="full-projection"),
        pytest.param("Just a wish.\n", False, id="no-aco-block"),
        pytest.param(
            complete_contract("Cut it.", slice=slice_entries("Scheibe A")),
            True,
            id="container-with-an-uncut-row",
        ),
    ],
)
def test_next_with_only_a_labelled_idea_names_no_action_and_the_idea(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    body_text: str,
    as_container: bool,
) -> None:
    idea = (
        _childless_container(10, body_text, labels=("idea",))
        if as_container
        else board_issue(10, "Operator idea", body_text, labels=("idea",))
    )
    _configured_board_client(monkeypatch, tmp_path, open_issues=(idea,))

    assert issue_claim.main(["--repo", REPOSITORY, "next"]) == 3
    assert (
        capsys.readouterr().out == "No actionable item.\n" + _NO_ACTION_NEXT_TAIL + "ideas: #10\n"
    )

    assert issue_claim.main(["--repo", REPOSITORY, "next", "--json"]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert (payload["reason"], payload["skipped"], payload["ideas"]) == (
        "nothing_actionable",
        [],
        [10],
    )


def test_next_still_skips_the_same_prose_without_the_label_as_malformed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _configured_board_client(
        monkeypatch, tmp_path, open_issues=(board_issue(11, "Prose work", "Just a wish.\n"),)
    )

    assert issue_claim.main(["--repo", REPOSITORY, "next"]) == 3
    assert capsys.readouterr().out == (
        "No actionable item.\n"
        + _NO_ACTION_NEXT_TAIL
        + "\nSKIPPED\n#11: body malformed: aco: no aco block\n"
    )


def test_next_keeps_an_unlabelled_projectionless_item_skipped_with_an_active_idea_label(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    write_repository_config(tmp_path, 'idea_label = "idea"\n')
    incomplete = board_issue(10, "Incomplete work", idea_body("Investigate."))
    _configured_board_client(monkeypatch, tmp_path, open_issues=(incomplete,))

    assert issue_claim.main(["--repo", REPOSITORY, "next"]) == 3
    assert capsys.readouterr().out == (
        "No actionable item.\n"
        + _NO_ACTION_NEXT_TAIL
        + "\nSKIPPED\n#10: body incomplete: Now, Next, Done when\n"
    )

    assert issue_claim.main(["--repo", REPOSITORY, "next", "--json"]) == 3
    assert json.loads(capsys.readouterr().out) == {
        "ok": False,
        "reason": "nothing_actionable",
        "recovery": [],
        "skipped": [{"number": 10, "reason": "body incomplete: Now, Next, Done when"}],
        "parallel": _EMPTY_PARALLEL_JSON,
        **_NOTHING_NAMED_JSON,
    }


def test_next_keeps_a_vision_labelled_projectionless_item_incomplete_without_configuration(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    idea = board_issue(10, "Operator vision", idea_body("Investigate."), labels=("vision",))
    _configured_board_client(monkeypatch, tmp_path, open_issues=(idea,))

    assert issue_claim.main(["--repo", REPOSITORY, "next"]) == 3
    assert capsys.readouterr().out == (
        "No actionable item.\n"
        + _NO_ACTION_NEXT_TAIL
        + "\nSKIPPED\n#10: body incomplete: Now, Next, Done when\n"
    )


def test_next_takes_the_configured_idea_label_instead_of_the_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    write_repository_config(tmp_path, 'idea_label = "vision"\n')
    default_labelled = board_issue(
        10, "Plain work", complete_contract("Claim #10."), labels=("idea",)
    )
    vision = board_issue(11, "A vision", complete_contract("Build it."), labels=("vision",))
    _configured_board_client(monkeypatch, tmp_path, open_issues=(default_labelled, vision))

    assert issue_claim.main(["--repo", REPOSITORY, "next"]) == 0
    assert capsys.readouterr().out == (
        "#10 score -10: Plain work\nNext: Claim #10.\n"
        "Run: aco claim 10 --scope <paths>\n" + _UNKNOWN_SCOPE_NEXT_TAIL + "ideas: #11\n"
    )


def test_board_json_marks_a_labelled_item_as_an_idea_that_is_not_actionable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    idea = board_issue(10, "Operator idea", complete_contract("Build it."), labels=("idea",))
    _configured_board_client(monkeypatch, tmp_path, open_issues=(idea,))

    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 0

    item = json.loads(capsys.readouterr().out)["items"][0]
    assert (item["idea"], item["actionable"], item["actionable_reason"]) == (True, False, "idea")


def test_claim_refuses_an_empty_labelled_idea_as_an_incomplete_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    idea = board_issue(10, "Operator idea", idea_body("Make it clearer."), labels=("idea",))
    _configured_board_client(monkeypatch, tmp_path, open_issues=(idea,))
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=10, scope=("src/work.py",)),
    )

    exit_code = issue_claim.main(
        ["--repo", REPOSITORY, "claim", "10", "--agent", "Codex Sol", "--scope", "src/work.py"]
    )

    assert exit_code == 2
    assert "body incomplete: Now, Next, Done when" in capsys.readouterr().err


def test_status_scope_index_never_rescans_scope_pairs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    claims = tuple(
        standing_active_claim(
            claim_id=f"claim-{claim_index}",
            issue=claim_index + 100,
            scope=tuple(f"area-{claim_index}/path-{scope_index}" for scope_index in range(32)),
        )
        for claim_index in range(50)
    )
    opened_at = datetime(2026, 8, 21, tzinfo=UTC)
    ages: dict[str, datetime] = {claim.claim_id: opened_at for claim in claims}

    def scope_pair_scan(*args, **kwargs):
        pytest.fail("status must use its single scope index")

    monkeypatch.setattr(protocol, "claims_conflict", scope_pair_scan)

    assert _status(claims, None, ages, body.Storage.GITHUB) == 0
    assert capsys.readouterr().out.count("CLAIMED") == 50
    assert _status(claims, 100, ages, body.Storage.GITHUB) == 0
    assert capsys.readouterr().out.count("CLAIMED") == 1


def _write_state_ref_pin(toplevel: Path) -> None:
    """`.aco/board.toml` pinned to `storage = "state-ref"` in
    `toplevel`: the isolated toplevel `_isolate_git_toplevel` (conftest.py)
    already redirects this process's `rev-parse --show-toplevel` to,
    or a repository `redirect_toplevel` points it at."""
    write_repository_config(toplevel, 'storage = "state-ref"\n')


def test_lazy_forge_builds_a_state_ref_board_under_the_state_ref_pin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The `session.RunContext`'s forge chooses its adapter by the repository's own `storage`
    pin, never by the canonical remote's host: a state-ref
    pin must never build a `github.GitHubForge`, even when nothing else
    about the checkout looks unusual."""
    _write_state_ref_pin(tmp_path)
    stub = FakeForge(repository=forge.RepositoryId("file", (), str(tmp_path)))
    monkeypatch.setattr(session, "_state_ref_forge", lambda _context: stub)

    def unused(*_args: object, **_kwargs: object) -> None:
        pytest.fail("storage = state-ref must never build a GitHubForge")

    monkeypatch.setattr(github, "GitHubForge", unused)

    assert issue_claim.main(["board", "--json"]) == 0


def test_repo_is_refused_under_the_state_ref_pin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """`--repo` names a GitHub target; under `storage = "state-ref"` there
    is no host-based target to override, refused before this
    ever resolves a repository identity or touches the state ref."""
    _write_state_ref_pin(tmp_path)

    status = issue_claim.main(["--repo", "acme/items", "board", "--json"])

    assert status == 2
    assert capsys.readouterr().err == "ERROR: --repo is meaningless under storage = state-ref\n"


@pytest.mark.parametrize(
    "command", [["board", "--json"], ["rulings", "--json"], ["next", "--json"]]
)
def test_cli_board_family_reports_invalid_usage_when_repo_is_given_under_state_ref(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    command: list[str],
) -> None:
    """Spec: BOARD-42, PIN-04, RUL-09, E-RUL-06 -- state-ref refuses --repo.

    PIN-04, cited by BOARD-01/02 (`specs/board.spec.md`) and reused by
    `rulings`/`next`: all three resolve the same `RunContext.forge`
    `board` does, so `--repo` under `storage = state-ref` reports the same
    `invalid_usage` `ask`/`rule`/`brief` already do, never their broad
    `unavailable` catch-all."""
    _write_state_ref_pin(tmp_path)

    status = issue_claim.main(["--repo", "acme/items", *command])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == "ERROR: --repo is meaningless under storage = state-ref\n"
    _assert_json_refusal_object(captured.err, captured.out, reason="invalid_usage")


@pytest.mark.parametrize(
    "command", [["board", "--json"], ["rulings", "--json"], ["next", "--json"]]
)
def test_cli_board_family_reports_unavailable_for_a_forge_adapter_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
) -> None:
    """Spec: RUL-09, BOARD-02 -- adapter failure reports unavailable.

    The same generic catch-all `ask`/`rule`/`brief` already fall to:
    a forge adapter construction failure that is not
    `session.RepoMeaninglessUnderStateRefError` reports `unavailable`, never
    `invalid_usage`, for `board`, `rulings`, and `next` alike."""
    monkeypatch.setattr(
        github,
        "GitHubForge",
        lambda repository: (_ for _ in ()).throw(ClaimError("adapter failed")),
    )

    status = issue_claim.main(["--repo", REPOSITORY, *command])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == "ERROR: adapter failed\n"
    _assert_json_refusal_object(captured.err, captured.out, reason="unavailable")


class _RefusingItemWriter:
    """`state_board.ItemWriter` for a landing test: `release --merged
    <sha>` under `storage = "state-ref"` folds its item write into one
    atomic `protocol.LandingIntent` and never calls
    `state_board.StateRefBoard`'s own injected writer at all -- a call reaching this is
    the test's own defect, not behaviour under test."""

    def write_item(
        self,
        item_id: str,
        *,
        expected: protocol.ObjectId | None,
        content: bytes,
        store_expected: Mapping[str, protocol.ObjectId] | None,
        parent_pin: protocol.ItemPin | None,
    ) -> protocol.ObjectId:
        raise AssertionError(f"unexpected write to item {item_id}")

    def close_item(
        self,
        item_id: str,
        *,
        number: int,
        expected: protocol.ObjectId,
        content: bytes,
        store_expected: Mapping[str, protocol.ObjectId] | None,
    ) -> protocol.ObjectId:
        raise AssertionError(f"unexpected close of item {item_id}")


def _landing_item_body(title: str, blocked_by: tuple[str, ...] = ()) -> str:
    data: dict[str, object] = {
        "version": 1,
        "now": "Ship it.",
        "next": "keiner",
        "done_when": "Merged.",
        "record": {
            "title": title,
            "state": "open",
            "kind": "task",
            "labels": [],
            "blocked_by": list(blocked_by),
            "created_at": "2026-09-10T00:00:00Z",
            "updated_at": "2026-09-10T00:00:00Z",
        },
    }
    return block_body(body.render_block(data).removesuffix("\n"), before="Prose.\n\n", after="")


def _landing_item_oid(number: int) -> protocol.ObjectId:
    """A deterministic, well-formed fake blob oid for one landing test item
    -- its actual content-addressing never matters here, only that the
    same value seeds both the fake `state_board.StateRefBoard` and the fake store's own
    `ClaimState.items`, so `protocol.LandingIntent`'s CAS agrees with what
    `prepare_landing` reads."""
    return protocol.ObjectId(hashlib.sha1(f"landing-item-{number}".encode()).hexdigest())


_LANDING_ITEM_NUMBERS = (10, 11, 13)  # merge (#10), squash (#11, #12), rebase (#13)
_UNRELATED_LANDING_ITEM_ID = "aco-000014"


def _landing_repository(tmp_path: Path) -> Path:
    """A real `origin`-backed repository whose `main` carries,
    in first-parent order: a merge commit trailer-naming item `aco-00000a`
    (#10), a squash commit whose trailer repeats `Work-Item:` for #11 and
    #12, and a commit landed through a real `git rebase` naming #13 --
    real merge/squash/rebase trunk history for `release --merged
    <sha|empty>`/`check <sha>` (LAND-47/LAND-48/LAND-52) to walk. `feature`
    never joins the first-parent line itself (only its merge commit does),
    giving the off-trunk refusal proof a real sha to reject."""
    repo = bare_remote_repository_with_one_commit(tmp_path)

    real_git(repo, "checkout", "-q", "-b", "feature")
    (repo / "feature.txt").write_text("feature\n")
    real_git(repo, "add", "feature.txt")
    real_git(repo, "commit", "-q", "-m", "feature work")
    real_git(repo, "checkout", "-q", "main")
    real_git(
        repo,
        "merge",
        "-q",
        "--no-ff",
        "-m",
        "Merge feature",
        "-m",
        "Work-Item: aco-00000a",
        "feature",
    )

    real_git(repo, "checkout", "-q", "-b", "squashed")
    (repo / "squash.txt").write_text("one\n")
    real_git(repo, "add", "squash.txt")
    real_git(repo, "commit", "-q", "-m", "squash step")
    real_git(repo, "checkout", "-q", "main")
    real_git(repo, "merge", "-q", "--squash", "squashed")
    real_git(repo, "commit", "-q", "-m", "Squash landing", "-m", "Work-Item: #11\nWork-Item: #12")

    real_git(repo, "checkout", "-q", "-b", "docslane", "feature")
    (repo / "docs.txt").write_text("docs\n")
    real_git(repo, "add", "docs.txt")
    real_git(repo, "commit", "-q", "-m", "rebased landing", "-m", "Work-Item: #13")
    real_git(repo, "rebase", "-q", "main")
    real_git(repo, "checkout", "-q", "main")
    real_git(repo, "merge", "-q", "--ff-only", "docslane")

    push_repository_trunk(repo, "origin")
    return repo


def _landing_scenario(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    unrelated_blocked_by: tuple[str, ...] = (),
    foreign_entry: str | None = None,
) -> tuple[Path, state_board.StateRefBoard]:
    """The shared fixture every atomic-landing test builds on:
    `storage = "state-ref"`, a real trunk history (`_landing_repository`),
    a fake `state_board.StateRefBoard` over the three items it lands, a live claim on
    each, and a matching fake store whose `ClaimState.items` agrees with
    the board's own oids -- so `release --merged` (this module's own CLI
    path) and `prepare_landing`/`mark_landed` (`state_board.py`'s) are
    exercised together, exactly as a real run composes them.
    `unrelated_blocked_by`, when given, seeds one further unclaimed item
    carrying exactly those stored blockers; `foreign_entry`,
    one further `items/` entry whose file name names no item."""
    monkeypatch.setattr(checkout, "trunk_landings", _LIVE_TRUNK_LANDINGS)
    repo = _landing_repository(tmp_path)
    _write_state_ref_pin(repo)
    redirect_toplevel(monkeypatch, repo)
    item_ids = {number: items.format_item_id(number) for number in _LANDING_ITEM_NUMBERS}
    item_files = {
        f"{item_id}.md": _landing_item_body(f"Item {number}").encode()
        for number, item_id in item_ids.items()
    }
    item_oids = {item_id: _landing_item_oid(number) for number, item_id in item_ids.items()}
    if unrelated_blocked_by:
        item_files[f"{_UNRELATED_LANDING_ITEM_ID}.md"] = _landing_item_body(
            "Unrelated", unrelated_blocked_by
        ).encode()
        item_oids[_UNRELATED_LANDING_ITEM_ID] = _landing_item_oid(
            items.item_number(_UNRELATED_LANDING_ITEM_ID)
        )
    if foreign_entry is not None:
        item_files[foreign_entry] = b"anything"
    client = state_board.StateRefBoard(
        repository=forge.RepositoryId("file", ("acme",), "items"),
        default_branch="main",
        item_files=item_files,
        item_oids=item_oids,
        writer=_RefusingItemWriter(),
    )
    monkeypatch.setattr(session, "_state_ref_forge", lambda _context: client)
    claims = tuple(
        standing_active_claim(
            "Codex Sol",
            claim_id=f"claim-{number}",
            issue=number,
            branch=f"codex/issue-{number}-claims",
            scope=("src",),
        )
        for number in _LANDING_ITEM_NUMBERS
    )
    _patch_store_write(monkeypatch, *claims, items=item_oids)
    monkeypatch.chdir(repo)
    return repo, client


@pytest.mark.parametrize(
    ("number", "landing_ref", "use_sha"),
    [
        pytest.param(10, "main~2", True, id="merge-by-sha"),
        pytest.param(10, "main~2", False, id="merge-by-empty"),
        pytest.param(11, "main~1", True, id="squash-by-sha"),
        pytest.param(13, "main", False, id="rebase-by-empty"),
    ],
)
def test_release_merged_closes_and_releases_atomically_under_the_state_ref_pin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    number: int,
    landing_ref: str,
    use_sha: bool,
) -> None:
    """LAND-47/LAND-52: a merge, squash, or rebase
    landing carrying `Work-Item:`/`aco-xxxxxx` in the trunk closes its item
    and releases its claim in one commit, one CAS, whether `--merged` names
    the exact sha or is given bare (the newest trunk commit naming this
    item)."""
    _repo, client = _landing_scenario(monkeypatch, tmp_path)
    args = ["release", str(number), "--agent", "Codex Sol", "--claim-id", f"claim-{number}"]
    if use_sha:
        sha = real_git(_repo, "rev-parse", landing_ref).stdout.strip()
        args += ["--merged", sha]
    else:
        args += ["--merged"]

    status = issue_claim.main(args)

    assert status == 0
    out = capsys.readouterr().out
    assert out.startswith(f"RELEASED issue {items.format_item_id(number)}: claim-{number}\n")
    assert "freed:" in out
    assert "next:" in out
    assert client.item_reference(number).state is forge.ItemState.CLOSED
    remaining = store.fetch_state(worktree=Path("."), remote="origin").claims
    assert protocol.claim_key(protocol.IssueIdentity(number), "") not in remaining
    assert len(remaining) == len(_LANDING_ITEM_NUMBERS) - 1


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
@pytest.mark.parametrize(
    ("unrelated_blocked_by", "refusal"),
    [
        (
            ("aco-ffffff",),
            f"item {_UNRELATED_LANDING_ITEM_ID} lists blocker aco-ffffff, which does not exist",
        ),
        (
            ("aco-00000b", "aco-00000b"),
            f"item {_UNRELATED_LANDING_ITEM_ID} lists blocker aco-00000b more than once",
        ),
    ],
    ids=["missing-blocker", "repeated-blocker"],
)
def test_release_merged_under_state_ref_hints_a_runnable_board_read_beside_an_unrelated_broken_item(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    unrelated_blocked_by: tuple[str, ...],
    refusal: str,
    as_json: bool,
) -> None:
    """LAND-65, PIN-17, PIN-34: an unrelated item whose stored
    blockers the board read refuses -- one `items/` lacks, or one named
    twice -- leaves the committed landing standing and prints one neutral
    hint naming no forge, whose advice bash runs as printed and which reads
    the same refusal back."""
    _landing_scenario(monkeypatch, tmp_path, unrelated_blocked_by)
    hint = (
        f"hint: could not read the board to report what this write freed ({refusal}); "
        "run `aco board --json` once it is repaired"
    )
    arguments = ["release", "10", "--agent", "Codex Sol", "--claim-id", "claim-10", "--merged"]

    status = issue_claim.main([*arguments, *(["--json"] if as_json else [])])

    captured = capsys.readouterr()
    assert status == 0
    assert hint in (captured.err if as_json else captured.out).splitlines()
    advice = hint.split("`")[1]
    assert arguments_bash_hands_aco(advice, tmp_path) == (0, ["board", "--json"])
    advised = issue_claim.main(["board", "--json"])
    assert (advised, capsys.readouterr().err) == (2, f"ERROR: {refusal}\n")


def test_release_merged_refuses_beside_an_items_entry_that_names_no_item(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """PIN-13, PIN-36: `release --merged` refuses by the
    foreign entry's name before it closes the item or releases its claim."""
    _repo, client = _landing_scenario(monkeypatch, tmp_path, foreign_entry="NOTANID")

    status = issue_claim.main(
        ["release", "10", "--agent", "Codex Sol", "--claim-id", "claim-10", "--merged"]
    )

    assert (status, capsys.readouterr().err) == (
        2,
        "ERROR: items/NOTANID is not a valid item file name\n",
    )
    assert client.item_reference(10).state is forge.ItemState.OPEN


def test_release_merged_refuses_a_trunk_item_the_state_ref_has_no_entry_for(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The squash commit's trailer names both `#11` and
    `#12` (LAND-02), but `_landing_scenario` seeds the state ref with only
    `#11`'s own item -- `release --merged` for `#12` refuses by name,
    before any claim or write, rather than crashing on a decode miss."""
    repo, client = _landing_scenario(monkeypatch, tmp_path)
    sha = real_git(repo, "rev-parse", "main~1").stdout.strip()

    status = issue_claim.main(["release", "12", "--agent", "Codex Sol", "--merged", sha])

    assert status == 2
    assert capsys.readouterr().err == (
        f"ERROR: aco-00000c does not exist in {client.repository.path}\n"
    )


@pytest.mark.parametrize(
    ("landing_ref", "reason"),
    [
        pytest.param("main~3", "carries no `Work-Item:` trailer", id="no-trailer"),
        pytest.param("main~1", "does not name work item aco-00000a", id="foreign-item"),
        pytest.param("feature", "is not on the first-parent trunk", id="off-trunk"),
    ],
)
def test_release_merged_refuses_a_landing_it_cannot_verify_under_the_state_ref_pin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    landing_ref: str,
    reason: str,
) -> None:
    """LAND-52: a commit with no trailer, one naming
    a different item, or one outside the first-parent trunk all refuse by
    name, close nothing, and leave the claim live."""
    repo, client = _landing_scenario(monkeypatch, tmp_path)
    sha = real_git(repo, "rev-parse", landing_ref).stdout.strip()

    status = issue_claim.main(
        ["release", "10", "--agent", "Codex Sol", "--claim-id", "claim-10", "--merged", sha]
    )

    assert status == 2
    assert capsys.readouterr().err == f"ERROR: {sha} {reason}\n"
    assert client.item_reference(10).state is forge.ItemState.OPEN
    remaining = store.fetch_state(worktree=Path("."), remote="origin").claims
    assert protocol.claim_key(protocol.IssueIdentity(10), "") in remaining


# --- Real `file://` state-ref proofs ------------------------
#
# Every test above this point patches `store.fetch_state`/`commit_transition`
# with `_FakeStore` (`_landing_scenario`): it proves this module's own CLI
# wiring -- argument selection, the trunk walk, the printed report -- agrees
# with `protocol.apply`, but `protocol.apply` is exactly what `_FakeStore`
# calls too, so it can never prove one real git commit, a real CAS refusal,
# a real moved-ref race, or a real replay refusal. The tests below run
# `store.fetch_state`/`commit_transition` for real against a real bare
# `file://` remote (`_use_real_store`, below in the `reset` section, applies
# module-wide from here on) and assert on the ref/tree state a real clone
# would see, never on a fake's own bookkeeping.


def _real_landing_scenario(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, numbers: tuple[int, ...] = (10,)
) -> tuple[Path, Path]:
    """The real counterpart of `_landing_scenario`: the same real trunk
    history (`_landing_repository`), but `refs/aco/state` is real too, on
    the very same bare remote -- `store.fetch_state`/`commit_transition` run
    unfaked, and `session._state_ref_forge` is never stubbed, so `release --merged`
    below drives the exact git commits and CAS its own atomicity claim is
    about."""
    _use_real_store(monkeypatch)
    monkeypatch.setattr(checkout, "trunk_landings", _LIVE_TRUNK_LANDINGS)
    repo = _landing_repository(tmp_path)
    _write_state_ref_pin(repo)
    redirect_toplevel(monkeypatch, repo)
    remote = tmp_path / "remote.git"
    store.bootstrap(worktree=repo, remote=str(remote))
    for number in numbers:
        _seed_real_claim_and_item(
            repo,
            remote,
            issue=number,
            claim_id=f"claim-{number}",
            content=_landing_item_body(f"Item {number}").encode(),
        )
    monkeypatch.chdir(repo)
    return repo, remote


def _seed_real_claim_and_item(
    worktree: Path, remote: Path, *, issue: int, claim_id: str, content: bytes
) -> tuple[protocol.ActiveClaim, protocol.ObjectId]:
    """Lands a real claim and a real item blob for `issue` in two ordinary
    transitions, so an atomicity proof below can land a third -- one
    `protocol.LandingIntent` -- and check that it, unlike these two, closes
    the item and releases the claim in the very same commit."""
    claim = _land_real_claim(worktree, remote, issue=issue, claim_id=claim_id)
    return claim, _land_real_item(worktree, remote, issue=issue, content=content)


def _land_real_claim(
    worktree: Path,
    remote: Path,
    *,
    issue: int,
    claim_id: str,
    branch: str | None = None,
    base: str = "c" * 40,
) -> protocol.ActiveClaim:
    claim_state = store.commit_transition(
        observed=fresh_observation(worktree, remote),
        subject=store.ClaimTransitionSubject(f"claim issue {issue}", item=str(issue)),
        intent=protocol.ClaimIntent(
            identity=protocol.IssueIdentity(issue),
            agent="Codex Sol",
            role="builder",
            base=protocol.ObjectId(base),
            branch=branch or f"codex/issue-{issue}-claims",
            scope=("src",),
            claim_id=protocol.ClaimId(claim_id),
            operation_id=f"claim-op-{issue}",
        ),
    )
    return next(
        value
        for value in claim_state.claims.values()
        if value.identity == protocol.IssueIdentity(issue)
    )


def _land_real_item(
    worktree: Path, remote: Path, *, issue: int, content: bytes
) -> protocol.ObjectId:
    item_id = items.format_item_id(issue)
    new_oid = store.hash_blob(worktree, content)
    item_state = store.commit_transition(
        observed=fresh_observation(worktree, remote),
        subject=store.TransitionSubject(f"seed item {item_id}"),
        intent=protocol.ItemWriteIntent(
            item_id=item_id, expected=None, new_oid=new_oid, operation_id=f"item-op-{issue}"
        ),
    )
    return item_state.items[item_id]


def _state_ref_paths(repo: Path, tip: str) -> set[str]:
    return set(real_git(repo, "ls-tree", "-r", "--name-only", tip).stdout.splitlines())


def _state_ref_blob(repo: Path, tip: str, path: str) -> str:
    return real_git(repo, "show", f"{tip}:{path}").stdout


def _state_ref_tip(repo: Path, remote: Path) -> str:
    return real_git(repo, "ls-remote", str(remote), store.STATE_REF).stdout.split()[0]


def _state_ref_item_state(repo: Path, tip: str, number: int) -> items.RecordState:
    item_id = items.format_item_id(number)
    parsed = body.parse_body(
        _state_ref_blob(repo, tip, f"items/{item_id}.md"), storage=body.Storage.STATE_REF
    )
    assert parsed.record is not None
    return items.parse_item_record(item_id, parsed.record).state


@pytest.mark.parametrize(
    ("command", "failing_read"),
    [
        pytest.param(["check", "{sha}"], list(RECORDED_ORIGIN_HEAD_READ), id="check-head"),
        pytest.param(
            ["check", "{sha}", "--json"], list(RECORDED_ORIGIN_HEAD_READ), id="check-json-head"
        ),
        pytest.param(["status"], list(RECORDED_ORIGIN_HEAD_READ), id="status-head"),
        pytest.param(["status", "--json"], list(RECORDED_ORIGIN_HEAD_READ), id="status-json-head"),
        pytest.param(
            ["status", "--path", "src"], list(RECORDED_ORIGIN_HEAD_READ), id="status-path-head"
        ),
        pytest.param(["board", "--json"], list(RECORDED_ORIGIN_HEAD_READ), id="board-head"),
        pytest.param(["next"], list(RECORDED_ORIGIN_HEAD_READ), id="next-head"),
        # Only `next`, `start` and `rescope` call
        # `checkout.resolve_path_checkout`; `check`, `status`, `board` and
        # `brief` never reach the commit read.
        pytest.param(["next"], _COMMIT_READ, id="next-commit"),
    ],
)
def test_a_failed_trunk_read_refuses_with_gits_text_instead_of_guessing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    command: list[str],
    failing_read: list[str],
) -> None:
    """The caller matrix against real trunk history: git
    failing to read `<remote>/HEAD` is never a remote that recorded none, nor
    a failing commit read a checkout with no commit, so no command falls
    back to `<remote>/main`, judges against it, or prints `cannot resolve
    the default branch`; a `--json` command reports the refusal as
    `unavailable`."""
    repo, remote = _real_landing_scenario(monkeypatch, tmp_path, numbers=(10,))
    sha = real_git(repo, "rev-parse", "main~2").stdout.strip()
    tip_before = _state_ref_tip(repo, remote)
    injected = stub_one_git_call(monkeypatch, failing_read, exit_status=128, stderr="fatal: broken")

    status = issue_claim.main([argument.format(sha=sha) for argument in command])

    captured = capsys.readouterr()
    assert injected
    assert status == 2
    if "--json" in command:
        assert json.loads(captured.out) == {
            "ok": False,
            "reason": "unavailable",
            "message": "fatal: broken",
        }
    else:
        assert captured.err.splitlines() == ["ERROR: fatal: broken"]
    assert _state_ref_tip(repo, remote) == tip_before


@pytest.mark.parametrize(
    ("lane_stands", "starts_in_lane"),
    [
        pytest.param(True, False, id="resume-head"),
        pytest.param(True, True, id="resume-head-in-lane"),
        pytest.param(False, False, id="rebuild-head"),
    ],
)
def test_start_under_state_ref_refuses_a_failed_head_read_and_keeps_the_standing_lane(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    lane_stands: bool,
    starts_in_lane: bool,
) -> None:
    """Under `storage = "state-ref"` the item is read through the state
    ref's own board, which reads `<remote>/HEAD` for the default branch
    before `start` decides between resume and build: a failed read refuses
    with git's text and leaves the live claim, the lane's worktree and
    branch, and `refs/aco/state` as they stood."""
    repo, remote = _real_landing_scenario(monkeypatch, tmp_path, numbers=(10,))
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
    lane_worktree = checkout.sibling_worktree_path(repo, "issue-10-claims")
    branch = "codex/issue-10-claims"
    if lane_stands:
        real_git(repo, "worktree", "add", "-q", "-b", branch, str(lane_worktree), "feature")
    if starts_in_lane:
        redirect_toplevel(monkeypatch, lane_worktree)
        monkeypatch.chdir(lane_worktree)
    tip_before = _state_ref_tip(repo, remote)
    injected = stub_one_git_call(
        monkeypatch, list(RECORDED_ORIGIN_HEAD_READ), exit_status=128, stderr="fatal: broken"
    )

    status = issue_claim.main(["start", "10", "--slug", "claims"])

    captured = capsys.readouterr()
    assert injected
    assert (status, captured.out, captured.err) == (2, "", "ERROR: fatal: broken\n")
    assert _state_ref_tip(repo, remote) == tip_before
    assert fresh_observation(repo, remote).state.claims
    assert lane_worktree.is_dir() is lane_stands
    assert bool(real_git(repo, "branch", "--list", branch).stdout.strip()) is lane_stands


def test_release_merged_under_state_ref_commits_once_then_refuses_a_replay_whose_claim_is_gone(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """A real `file://` proof of Beweis 1 -- one landing is
    exactly one new commit on `refs/aco/state` whose tree closes the item
    and drops the claim -- and of the replay case `_FakeStore` cannot see: a
    second `release` naming the released claim refuses it as gone (REL-09),
    through the real state re-read from the real ref, and moves the ref not
    at all."""
    repo, remote = _real_landing_scenario(monkeypatch, tmp_path, numbers=(10,))
    sha = real_git(repo, "rev-parse", "main~2").stdout.strip()
    item_id = items.format_item_id(10)
    tip_before = _state_ref_tip(repo, remote)
    assert "claims/issue-10.toml" in _state_ref_paths(repo, tip_before)
    count_before = int(real_git(repo, "rev-list", "--count", tip_before).stdout.strip())

    status = issue_claim.main(
        ["release", "10", "--agent", "Codex Sol", "--claim-id", "claim-10", "--merged", sha]
    )

    assert status == 0
    tip_after = _state_ref_tip(repo, remote)
    count_after = int(real_git(repo, "rev-list", "--count", tip_after).stdout.strip())
    assert count_after == count_before + 1
    assert real_git(repo, "rev-parse", f"{tip_after}^").stdout.strip() == tip_before
    paths_after = _state_ref_paths(repo, tip_after)
    assert "claims/issue-10.toml" not in paths_after
    assert f"items/{item_id}.md" in paths_after
    assert _state_ref_item_state(repo, tip_after, 10) is items.RecordState.CLOSED
    capsys.readouterr()

    replay_status = issue_claim.main(
        ["release", "10", "--agent", "Codex Sol", "--claim-id", "claim-10", "--merged", sha]
    )

    assert replay_status == 2
    assert capsys.readouterr().err == "ERROR: issue aco-00000a has no active build claim\n"
    assert _state_ref_tip(repo, remote) == tip_after


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_release_merged_rerun_under_state_ref_writes_nothing_and_names_its_own_rerun(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    as_json: bool,
) -> None:
    """Under `storage = "state-ref"`: a release
    whose lane worktree lives elsewhere names the line that repeats its
    cleanup there; run as printed once the claim is gone, it verifies the
    trunk commit, closes nothing, moves `refs/aco/state` not at all, and
    reports only the cleanup (REL-47, REL-49, REL-51, REL-52)."""
    repo, remote = _real_landing_scenario(monkeypatch, tmp_path, numbers=(10,))
    sha = real_git(repo, "rev-parse", "main~2").stdout.strip()
    branch = "codex/issue-10-claims"
    rerun = f"aco release {items.format_item_id(10)} --merged {sha} --branch {branch}"
    kept = (
        f"kept -- no linked worktree on {branch} in this checkout; "
        f"run {rerun} in the checkout that holds it"
    )
    assert (
        issue_claim.main(
            ["release", "10", "--agent", "Codex Sol", "--claim-id", "claim-10", "--merged", sha]
        )
        == 0
    )
    assert capsys.readouterr().out.splitlines()[-1] == f"worktree: {kept}"
    tip_after_release = _state_ref_tip(repo, remote)
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})

    status = issue_claim.main([*shlex.split(rerun)[1:], *(["--json"] if as_json else [])])

    output = capsys.readouterr().out
    reported = json.loads(output) if as_json else output
    assert (status, reported) == (
        0,
        {
            "ok": True,
            "reason": "merged",
            "outcome": "nothing left to release",
            "issue": 10,
            "lane": None,
            "branch": branch,
            "worktree": kept,
        }
        if as_json
        else f"LANDED commit {sha} already; nothing left to release\nworktree: {kept}\n",
    )
    assert _state_ref_tip(repo, remote) == tip_after_release


def _state_ref_landing_with_its_lane_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path, Path, list[str]]:
    """The real state-ref landing of item #10 with the landed lane's linked
    worktree and branch standing, and the `release --merged` call for it."""
    repo, remote = _real_landing_scenario(monkeypatch, tmp_path, numbers=(10,))
    sha = real_git(repo, "rev-parse", "main~2").stdout.strip()
    lane_worktree = tmp_path / "issue-10-lane"
    real_git(
        repo, "worktree", "add", "-q", "-b", "codex/issue-10-claims", str(lane_worktree), "feature"
    )
    landing = ["release", "10", "--agent", "Codex Sol", "--claim-id", "claim-10", "--merged", sha]
    return repo, remote, lane_worktree, landing


def test_release_merged_under_state_ref_removes_the_landed_lane_worktree(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _repo, _remote, lane_worktree, landing = _state_ref_landing_with_its_lane_worktree(
        monkeypatch, tmp_path
    )

    status = issue_claim.main(landing)

    assert (status, "worktree: removed\n" in capsys.readouterr().out) == (0, True)
    assert not lane_worktree.exists()


def test_release_merged_under_state_ref_stops_before_the_transition_when_the_head_read_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """REL-32: the trunk the landing is walked against is never guessed
    after a failed read of `<remote>/HEAD`: the claim stays, worktree and
    branch stand, and `refs/aco/state` does not move."""
    repo, remote, lane_worktree, landing = _state_ref_landing_with_its_lane_worktree(
        monkeypatch, tmp_path
    )
    tip_before = _state_ref_tip(repo, remote)
    stub_one_git_call(
        monkeypatch, list(RECORDED_ORIGIN_HEAD_READ), exit_status=128, stderr="fatal: broken"
    )

    status = issue_claim.main(landing)

    captured = capsys.readouterr()
    assert (status, captured.out, captured.err) == (2, "", "ERROR: fatal: broken\n")
    assert _state_ref_tip(repo, remote) == tip_before
    assert lane_worktree.is_dir()
    assert real_git(repo, "branch", "--list", "codex/issue-10-claims").stdout.strip()


def test_release_merged_under_state_ref_keeps_the_worktree_when_the_cleanup_head_read_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """REL-32: the remote `HEAD` read after the cleanup's fetch fails only
    then: the release already happened and stays, and the worktree and
    branch are kept with git's text, never judged merged against a guess."""
    repo, remote, lane_worktree, landing = _state_ref_landing_with_its_lane_worktree(
        monkeypatch, tmp_path
    )
    _fail_the_read_after_the_fetch(monkeypatch, list(RECORDED_ORIGIN_HEAD_READ))

    status = issue_claim.main(landing)

    assert status == 0
    assert "worktree: kept -- git failure: fatal: broken\n" in capsys.readouterr().out
    assert fresh_observation(repo, remote).state.claims == {}
    assert lane_worktree.is_dir()
    assert real_git(repo, "branch", "--list", "codex/issue-10-claims").stdout.strip()


@pytest.mark.parametrize(
    "reclaim_on",
    ["codex/issue-10-again", "codex/issue-10-claims", None],
    ids=["reclaimed-elsewhere", "reclaimed-on-the-landed-branch", "unclaimed"],
)
def test_release_merged_rerun_under_state_ref_never_touches_a_lane_opened_after_an_abandon(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    reclaim_on: str | None,
) -> None:
    """A lane lands on its branch, its claim is
    abandoned, the item stays open and may be claimed again; the old
    landing's rerun then refuses that newer claim by name -- on another
    branch (REL-48), or on the landed branch from a trunk that already holds
    the landing (REL-53) -- or, with no live claim, has nothing left to
    release (REL-47). Either way the newer claim, the open item and the
    newer lane's worktree and branch -- on the landed branch itself for
    REL-53 -- all survive, and `refs/aco/state` does not move."""
    repo, remote = _real_landing_scenario(monkeypatch, tmp_path, numbers=(10,))
    sha = real_git(repo, "rev-parse", "main~2").stdout.strip()
    landed_branch = "codex/issue-10-claims"
    newer_branch = reclaim_on or "codex/issue-10-again"
    newer_worktree = tmp_path / "issue-10-newer"
    rerun = ["release", "10", "--agent", "Codex Sol", "--merged", sha, "--branch", landed_branch]
    assert (
        issue_claim.main(
            ["release", "10", "--agent", "Codex Sol", "--claim-id", "claim-10", "--abandoned", "x"]
        )
        == 0
    )
    real_git(repo, "worktree", "add", "-q", "-b", newer_branch, str(newer_worktree), "main")
    if reclaim_on is not None:
        _land_real_claim(
            repo, remote, issue=10, claim_id="claim-10-again", branch=reclaim_on, base=sha
        )
    tip_before = _state_ref_tip(repo, remote)
    capsys.readouterr()

    status = issue_claim.main(rerun)

    printed_rerun = (
        f"aco release {items.format_item_id(10)} --merged {sha} --branch {landed_branch}"
    )
    refusals = {
        "codex/issue-10-again": (
            f"ERROR: issue aco-00000a is claimed on 'codex/issue-10-again', not on commit "
            f"{sha}'s branch '{landed_branch}'; release that claim by itself\n"
        ),
        landed_branch: (
            f"ERROR: issue aco-00000a was claimed on '{landed_branch}' after commit {sha} "
            "landed; release that claim by itself\n"
        ),
    }
    expected = (
        (
            0,
            f"LANDED commit {sha} already; nothing left to release\n"
            f"worktree: kept -- no linked worktree on {landed_branch} in this checkout; "
            f"run {printed_rerun} in the checkout that holds it\n",
            "",
        )
        if reclaim_on is None
        else (2, "", refusals[reclaim_on])
    )
    printed = capsys.readouterr()
    observed = (status, printed.out, printed.err)
    assert observed == expected
    assert _state_ref_tip(repo, remote) == tip_before
    assert _state_ref_item_state(repo, tip_before, 10) is items.RecordState.OPEN
    live_branches = [
        claim.branch for claim in fresh_observation(repo, remote).state.claims.values()
    ]
    assert live_branches == ([] if reclaim_on is None else [reclaim_on])
    assert newer_worktree.is_dir()
    assert real_git(repo, "branch", "--list", newer_branch).stdout.strip()


def test_release_merged_rerun_under_state_ref_refuses_a_newer_claim_before_judging_the_item(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """The claim decision comes before the close write is
    prepared, so a rerun of a landing whose item is already closed still
    names the newer claim on another branch (REL-48) rather than the closed
    item, and moves `refs/aco/state` not at all."""
    repo, remote = _real_landing_scenario(monkeypatch, tmp_path, numbers=(10,))
    sha = real_git(repo, "rev-parse", "main~2").stdout.strip()
    landed_branch = "codex/issue-10-claims"
    newer_branch = "codex/issue-10-again"
    landing = ["release", "10", "--agent", "Codex Sol", "--merged", sha]
    assert issue_claim.main([*landing, "--claim-id", "claim-10"]) == 0
    _land_real_claim(repo, remote, issue=10, claim_id="claim-10-again", branch=newer_branch)
    tip_before = _state_ref_tip(repo, remote)
    capsys.readouterr()

    status = issue_claim.main([*landing, "--branch", landed_branch])

    assert (status, capsys.readouterr().err) == (
        2,
        f"ERROR: issue aco-00000a is claimed on '{newer_branch}', not on commit {sha}'s "
        f"branch '{landed_branch}'; release that claim by itself\n",
    )
    assert _state_ref_tip(repo, remote) == tip_before


def test_landing_intent_survives_an_unrelated_ref_move_with_no_half_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unrelated writer lands on `refs/aco/state` between
    this transition's own fetch and its first push attempt -- the real,
    non-fast-forward rejection `commit_transition`'s retry loop exists for.
    The retry refetches, reapplies on top of the racer's own commit, and
    lands exactly one more commit: neither the racer's write nor this
    transition's is ever left half-applied."""
    worktree, bare_remote = _reset_repository(monkeypatch, tmp_path)
    _use_real_store(monkeypatch)
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    claim, open_oid = _seed_real_claim_and_item(
        worktree, bare_remote, issue=10, claim_id="claim-10", content=b"open\n"
    )
    item_id = items.format_item_id(10)
    closed_oid = store.hash_blob(worktree, b"closed\n")
    racer_commits: list[str] = []
    racer = RaceOnceTransport(
        lambda: racer_commits.append(unrelated_racer_commit(worktree, bare_remote))
    )

    new_state = store.commit_transition(
        observed=fresh_observation(worktree, bare_remote),
        subject=store.ClaimTransitionSubject("release issue 10", item="10"),
        intent=protocol.LandingIntent(
            item_id=item_id,
            item_expected=open_oid,
            item_new_oid=closed_oid,
            claim_id=claim.claim_id,
            agent="Codex Sol",
            role="builder",
            outcome=protocol.LandedRelease(commit=protocol.ObjectId("d" * 40)),
            operation_id="land-op-10",
        ),
        transport=racer,
    )

    [racer_commit] = racer_commits
    # The racer's own commit is the ref state that stood between the
    # rejected first push and the retry that succeeded -- reading its tree
    # (an immutable git object, not a live poll) proves neither the item nor
    # the claim was ever half-landed there: the item is still open at its
    # pre-landing oid and the claim is still present, exactly as they were
    # before this transition ever touched the ref.
    racer_item_oid = real_git(
        worktree, "rev-parse", f"{racer_commit}:items/{item_id}.md"
    ).stdout.strip()
    assert racer_item_oid == open_oid
    assert "claims/issue-10.toml" in _state_ref_paths(worktree, racer_commit)
    assert new_state.items[item_id] == closed_oid
    assert protocol.claim_key(protocol.IssueIdentity(10), "") not in new_state.claims
    assert new_state.tip is not None
    # The retry rebuilt directly on the racer's own commit -- no commit from
    # the rejected first attempt sits between them.
    parent = real_git(worktree, "rev-parse", f"{new_state.tip}^").stdout.strip()
    assert parent == racer_commit
    refetched = store.fetch_state(worktree=worktree, remote=str(bare_remote))
    assert refetched.items[item_id] == closed_oid
    assert protocol.claim_key(protocol.IssueIdentity(10), "") not in refetched.claims


def test_item_close_refuses_a_claim_that_lands_between_its_first_attempt_and_the_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A claim lands on the item after the close read an
    unclaimed state and before its first push, so that push is rejected; the
    retry re-applies the close to the fresh state, meets the live claim, and
    refuses with PIN-26's sentence -- the item stays open, the claim stays."""
    worktree, bare_remote = _reset_repository(monkeypatch, tmp_path)
    _use_real_store(monkeypatch)
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    open_oid = _land_real_item(worktree, bare_remote, issue=10, content=b"open\n")
    item_id = items.format_item_id(10)
    close = protocol.ItemCloseIntent(
        protocol.ItemWriteIntent(
            item_id=item_id,
            expected=open_oid,
            new_oid=store.hash_blob(worktree, b"closed\n"),
            operation_id="close-op-10",
        ),
        protocol.IssueIdentity(10),
    )
    racer = RaceOnceTransport(
        lambda: _land_real_claim(worktree, bare_remote, issue=10, claim_id="claim-10")
    )
    subject = store.TransitionSubject(f"write item {item_id}")

    observed = fresh_observation(worktree, bare_remote)
    with pytest.raises(
        protocol.ClaimUnavailableError,
        match=r"^#10 has a live claim \(Codex Sol \(builder\)\); release the claim first$",
    ):
        store.commit_transition(
            observed=observed,
            subject=subject,
            intent=close,
            transport=racer,
        )

    refetched = store.fetch_state(worktree=worktree, remote=str(bare_remote))
    assert refetched.items[item_id] == open_oid
    assert protocol.claim_key(protocol.IssueIdentity(10), "") in refetched.claims


def _claim_pinned_to_item(issue: int, open_oid: protocol.ObjectId) -> protocol.ClaimIntent:
    return protocol.ClaimIntent(
        identity=protocol.IssueIdentity(issue),
        agent="Codex Sol",
        role="builder",
        base=protocol.ObjectId("c" * 40),
        branch=f"codex/issue-{issue}-pinned",
        scope=("src",),
        claim_id=protocol.ClaimId(f"claim-{issue}"),
        operation_id=f"claim-op-{issue}",
        item_pin=protocol.ItemPin(items.format_item_id(issue), open_oid),
    )


def test_a_pinned_claim_refuses_once_its_item_closes_between_its_rejection_and_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A close lands after the claim's checks read the
    item open and before its first push, so that push is rejected; the retry
    applies the claim to the fresh state, finds the item's blob no longer
    the pinned one, and refuses with CAS-20's sentence -- the item stays
    closed and no claim is written (CAS-57, CAS-59)."""
    worktree, bare_remote = _reset_repository(monkeypatch, tmp_path)
    _use_real_store(monkeypatch)
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    open_oid = _land_real_item(worktree, bare_remote, issue=10, content=b"open\n")
    item_id = items.format_item_id(10)
    closed_oid = store.hash_blob(worktree, b"closed\n")
    close = protocol.ItemCloseIntent(
        protocol.ItemWriteIntent(
            item_id=item_id, expected=open_oid, new_oid=closed_oid, operation_id="close-op-10"
        ),
        protocol.IssueIdentity(10),
    )
    racer = RaceOnceTransport(
        lambda: store.commit_transition(
            observed=fresh_observation(worktree, bare_remote),
            subject=store.TransitionSubject(f"write item {item_id}"),
            intent=close,
        )
    )
    subject = store.ClaimTransitionSubject("claim issue 10", item="10")
    claim = _claim_pinned_to_item(10, open_oid)

    observed = fresh_observation(worktree, bare_remote)
    with pytest.raises(
        protocol.ClaimUnavailableError,
        match=(
            rf"^item '{item_id}' was written since it was read "
            rf"\(expected {open_oid}, found '{closed_oid}'\); re-read and retry$"
        ),
    ) as raised:
        store.commit_transition(observed=observed, subject=subject, intent=claim, transport=racer)

    assert type(raised.value) is protocol.ClaimUnavailableError
    refetched = store.fetch_state(worktree=worktree, remote=str(bare_remote))
    assert refetched.items[item_id] == closed_oid
    assert not refetched.claims


def test_a_pinned_claim_on_an_unchanged_open_item_lands_past_an_unrelated_racer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A racer that leaves the item's blob untouched
    rejects the claim's first push as before, and the retry lands the claim
    with its pin intact."""
    worktree, bare_remote = _reset_repository(monkeypatch, tmp_path)
    _use_real_store(monkeypatch)
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    open_oid = _land_real_item(worktree, bare_remote, issue=10, content=b"open\n")
    racer = RaceOnceTransport(lambda: unrelated_racer_commit(worktree, bare_remote))
    claim = _claim_pinned_to_item(10, open_oid)

    new_state = store.commit_transition(
        observed=fresh_observation(worktree, bare_remote),
        subject=store.ClaimTransitionSubject("claim issue 10", item="10"),
        intent=claim,
        transport=racer,
    )

    key = protocol.claim_key(protocol.IssueIdentity(10), claim.branch)
    assert key in new_state.claims
    assert key in store.fetch_state(worktree=worktree, remote=str(bare_remote)).claims


def test_landing_intent_refuses_a_stale_item_oid_without_writing_anything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `protocol.LandingIntent` built from a stale `item_expected`
    (someone else edited the item after this caller's own read) refuses by
    name, the same CAS discipline `protocol.ItemWriteIntent` already proves, and
    writes nothing -- the claim stays live and the item stays open on the
    real ref, not just in a fake's own state."""
    worktree, bare_remote = _reset_repository(monkeypatch, tmp_path)
    _use_real_store(monkeypatch)
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    claim, open_oid = _seed_real_claim_and_item(
        worktree, bare_remote, issue=10, claim_id="claim-10", content=b"open\n"
    )
    item_id = items.format_item_id(10)
    stale_oid = store.hash_blob(worktree, b"some other content\n")
    closed_oid_attempt = store.hash_blob(worktree, b"closed\n")
    tip_before = _state_ref_tip(worktree, bare_remote)
    intent = protocol.LandingIntent(
        item_id=item_id,
        item_expected=stale_oid,
        item_new_oid=closed_oid_attempt,
        claim_id=claim.claim_id,
        agent="Codex Sol",
        role="builder",
        outcome=protocol.LandedRelease(commit=protocol.ObjectId("d" * 40)),
        operation_id="land-op-10-stale",
    )

    subject = store.ClaimTransitionSubject("release issue 10", item="10")
    observed = fresh_observation(worktree, bare_remote)
    with pytest.raises(protocol.ClaimUnavailableError, match="was written since it was read"):
        store.commit_transition(
            observed=observed,
            subject=subject,
            intent=intent,
        )

    assert _state_ref_tip(worktree, bare_remote) == tip_before
    unchanged = store.fetch_state(worktree=worktree, remote=str(bare_remote))
    assert unchanged.items[item_id] == open_oid
    assert protocol.claim_key(protocol.IssueIdentity(10), "") in unchanged.claims


def test_release_merged_under_the_state_ref_pin_requires_an_issue(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """An issue-less lane has no state-ref item to close, so
    `--merged` under `storage = "state-ref"` refuses it by name rather than
    resolving a trunk walk that could never apply."""
    _write_state_ref_pin(tmp_path)
    repo = _landing_repository(tmp_path)
    monkeypatch.chdir(repo)

    status = issue_claim.main(["release", "--merged", "--agent", "Codex Sol", "--branch", "docs/x"])

    assert status == 2
    assert capsys.readouterr().err == (
        "ERROR: --merged under storage = state-ref requires an issue number; "
        "an issue-less lane has no item to close\n"
    )


def test_cli_version_exits_before_requiring_a_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exited:
        issue_claim.main(["--version"])

    assert exited.value.code == 0
    assert capsys.readouterr().out == f"aco {__version__}\n"


def _patch_release_session(
    monkeypatch: pytest.MonkeyPatch,
    client: FakeForge,
    *standing: ClaimRequest,
    agent: str = "Ada",
    branch: str | None = "lane-72",
    forbid_git: bool = False,
) -> None:
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: agent})
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    _patch_store_write(monkeypatch, *(store_claim_from_request(claimed) for claimed in standing))
    trunk_head = RECORDED_ORIGIN_HEAD_READ
    if forbid_git:

        def git(arguments: list[str], **_kwargs: object) -> str:
            if tuple(arguments) == ("rev-parse", "--show-toplevel"):
                return "/repo"
            if tuple(arguments) == trunk_head:
                return "refs/remotes/origin/main"
            pytest.fail("explicit --claim-id must not inspect checkout branch")

        monkeypatch.setattr(checkout, "git_output", git)
        return
    git_values = {
        ("branch", "--show-current"): branch or "",
        ("rev-parse", "--show-toplevel"): "/repo",
        trunk_head: "refs/remotes/origin/main",
    }
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )


def _claim_without_agent_args(*flags: str) -> list[str]:
    return [
        "claim",
        "72",
        "--role",
        "builder",
        "--scope",
        "src",
        "--claim-id",
        "cli-claim",
        *flags,
    ]


def test_matching_store_claim_never_replays_an_issueless_lane() -> None:
    """Issueless lanes keep the one-claim-per-branch contract: only a
    numbered item's replay is ever detected, matching `cmd_claim.run`'s own
    `isinstance(requested.identity, IssueIdentity)` guard around this
    function's sole call site."""
    lane_request = request(lane=True, branch="docs/lane-claim-a")
    standing = store_claim_from_request(lane_request)
    observed = protocol.ClaimState(
        tip=protocol.ObjectId(BASE),
        claims={protocol.claim_key(lane_request.identity, lane_request.branch): standing},
    )

    assert cmd_claim._matching_store_claim(observed, lane_request) is None


def test_selected_store_claim_refuses_a_lane_identity_without_a_branch() -> None:
    """`rescope`/`release` both resolve a non-empty branch before this
    function ever sees a `protocol.LaneIdentity` in production; this pins the
    function's own boundary check as a direct unit test rather than relying
    on that upstream guarantee never slipping."""
    identity = protocol.LaneIdentity()
    storage = body.Storage.GITHUB
    with pytest.raises(ClaimUnavailableError, match="lane release requires a non-empty"):
        workboard.selected_store_claim(protocol.EMPTY_STATE, identity, "", None, storage)


def test_claim_scope_is_optional_at_the_argparse_layer_for_issue_mode() -> None:
    """`required=True` is gone from `--scope` -- issue mode
    derives it from the item body when omitted, so argparse itself must
    accept the omission; `cmd_claim.run`'s own runtime checks (lane mode still
    requiring it, issue mode refusing a body with no scope) are proven
    separately, against `cli.main`."""
    parsed = issue_claim._parser().parse_args(
        ["claim", "42", "--agent", "Ada", "--role", "builder"]
    )

    assert parsed.scope is None


def test_cli_claim_role_argparse_default_unchanged_and_release_omits_role() -> None:
    claimed = issue_claim._parser().parse_args(["claim", "42", "--scope", "src/widget.py"])
    released = issue_claim._parser().parse_args(["release", "42", "--merged", "12"])

    assert claimed.role == cmd_claim.DEFAULT_CLAIM_ROLE
    assert released.role is None
    assert released.merged == "12"
    assert released.abandoned is None
    assert released.claim_id is None
    assert released.coordinator_override is False


def test_release_merged_bare_flag_parses_as_the_empty_sentinel() -> None:
    """`release --merged` with no value: the state-ref "pick
    the newest trunk landing" form -- distinct from omitting `--merged`
    altogether, which `--abandoned`'s own required-group partner still
    catches."""
    released = issue_claim._parser().parse_args(["release", "42", "--merged"])

    assert released.merged == ""


@pytest.mark.parametrize(
    ("role_flags", "role"),
    [
        ((), cmd_claim.DEFAULT_CLAIM_ROLE),
        (("--role", "builder"), "builder"),
        (("--role", "coordinator"), "coordinator"),
    ],
)
def test_cli_claim_omitted_role_posts_default_and_explicit_wins(
    monkeypatch: pytest.MonkeyPatch,
    role_flags: tuple[str, ...],
    role: str,
) -> None:
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())

    claimed = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Codex Sol",
            *role_flags,
            "--base",
            BASE,
            "--branch",
            "codex/issue-72",
            "--scope",
            "src",
            "--claim-id",
            "cli-claim",
        ]
    )

    assert claimed == 0
    posted = _live_store_claim()
    assert posted.role == role


def test_cli_claim_empty_role_fails_closed_without_posting_builder(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    argv = [
        "--repo",
        REPOSITORY,
        "claim",
        "72",
        "--agent",
        "Codex Sol",
        "--role",
        "",
        "--base",
        BASE,
        "--branch",
        "codex/issue-72",
        "--scope",
        "src",
        "--claim-id",
        "cli-claim",
    ]

    claimed = issue_claim.main(argv)
    captured = capsys.readouterr()

    assert claimed == 2
    assert captured.out == ""
    assert "ERROR:" in captured.err
    assert re.search(r"role.+must be one bounded non-empty line", captured.err)
    assert not store.fetch_state(worktree=Path("."), remote="origin").claims


@pytest.mark.parametrize(
    "arguments",
    [
        ["claim", "42", "--role", "builder", "--scope", "src/widget.py"],
        ["release", "42", "--role", "builder", "--abandoned", "stopped"],
    ],
)
def test_claim_and_release_parse_omitted_agent(arguments: list[str]) -> None:
    parsed = issue_claim._parser().parse_args(arguments)
    assert parsed.agent is None


@pytest.mark.parametrize(
    ("explicit", "environ", "agent"),
    [
        (
            "Ada",
            {
                "ACO_AGENT": "Other",
                "GROK_SESSION_ID": "grok-session",
                "CLAUDE_CODE_SESSION_ID": "claude-session",
            },
            "Ada",
        ),
        (None, {"ACO_AGENT": "Ada"}, "Ada"),
        (None, {"ACO_AGENT": "", "GROK_SESSION_ID": "sess-1"}, "Grok sess-1"),
        (
            None,
            {"GROK_SESSION_ID": "sess-1", "CLAUDE_CODE_SESSION_ID": "sess-2"},
            "Grok sess-1",
        ),
        (None, {"CLAUDE_CODE_SESSION_ID": "sess-2"}, "Claude sess-2"),
        (
            None,
            {
                "ACO_AGENT": "",
                "GROK_SESSION_ID": "",
                "CLAUDE_CODE_SESSION_ID": "sess-2",
            },
            "Claude sess-2",
        ),
    ],
)
def test_cli_claim_fills_agent_from_documented_else_chain(
    monkeypatch: pytest.MonkeyPatch,
    explicit: str | None,
    environ: dict[str, str],
    agent: str,
) -> None:
    set_agent_identity_env(monkeypatch, environ)
    git_values = git_checkout()
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    command = _claim_without_agent_args()
    if explicit is not None:
        command.extend(["--agent", explicit])

    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    assert issue_claim.main(["--repo", REPOSITORY, *command]) == 0
    posted = _live_store_claim()
    assert posted.agent == agent


@pytest.mark.parametrize(
    ("explicit", "environ"),
    [
        ("", {"ACO_AGENT": "Ada"}),
        (None, {"ACO_AGENT": " ", "GROK_SESSION_ID": "sess-1"}),
        (None, {"GROK_SESSION_ID": "bad\nid", "CLAUDE_CODE_SESSION_ID": "sess-2"}),
        (None, {"GROK_SESSION_ID": "x" * 200, "CLAUDE_CODE_SESSION_ID": "sess-2"}),
    ],
)
def test_invalid_agent_identity_fails_before_git_and_github(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    explicit: str | None,
    environ: dict[str, str],
) -> None:
    set_agent_identity_env(monkeypatch, environ)
    forbid_git_fill(monkeypatch)
    command = _claim_without_agent_args()
    if explicit is not None:
        command.extend(["--agent", explicit])

    forbid_github_construction(monkeypatch)
    releases = [
        ["release", "72", "--abandoned", "stopped"],
        ["release", "72", "--role", "builder", "--abandoned", "stopped"],
    ]
    if explicit is not None:
        for argv in releases:
            argv.extend(["--agent", explicit])
    for argv in (command, *releases):
        assert issue_claim.main(["--repo", REPOSITORY, *argv]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "ERROR:" in captured.err
        assert "agent must be one bounded non-empty line" in captured.err


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {
            "ACO_AGENT": "",
            "GROK_SESSION_ID": "",
            "CLAUDE_CODE_SESSION_ID": "",
        },
        {"GROK_AGENT": "should-not-fill"},
    ],
)
def test_missing_agent_identity_fails_closed_without_github(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    environ: dict[str, str],
) -> None:
    set_agent_identity_env(monkeypatch, environ)
    forbid_git_fill(monkeypatch)
    command = _claim_without_agent_args()

    forbid_github_construction(monkeypatch)
    for argv in (
        command,
        ["release", "72", "--abandoned", "stopped"],
        ["release", "72", "--role", "builder", "--abandoned", "stopped"],
    ):
        assert issue_claim.main(["--repo", REPOSITORY, *argv]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("ERROR:")
        assert_missing_identity_message(captured.err)


def test_cli_same_filled_agent_can_claim_and_release_without_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_agent_identity_env(monkeypatch, {"GROK_SESSION_ID": "session-1"})
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())

    claimed = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--role",
            "builder",
            "--base",
            BASE,
            "--branch",
            "codex/issue-72",
            "--scope",
            "src",
            "--claim-id",
            "cli-claim",
        ]
    )
    released = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "release",
            "72",
            "--role",
            "builder",
            "--abandoned",
            "stopped",
            "--claim-id",
            "cli-claim",
        ]
    )

    assert (claimed, released) == (0, 0)
    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


def test_cli_two_session_claimants_cannot_release_without_extra_comment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_agent_identity_env(monkeypatch, {"GROK_SESSION_ID": "session-1"})
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "72",
                "--role",
                "builder",
                "--base",
                BASE,
                "--branch",
                "codex/issue-72",
                "--scope",
                "src",
                "--claim-id",
                "cli-claim",
            ]
        )
        == 0
    )
    capsys.readouterr()

    monkeypatch.delenv(checkout.GROK_SESSION_ID_ENV)
    set_agent_identity_env(monkeypatch, {"CLAUDE_CODE_SESSION_ID": "session-2"})
    released = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "release",
            "72",
            "--role",
            "builder",
            "--abandoned",
            "stopped",
            "--claim-id",
            "cli-claim",
        ]
    )
    captured = capsys.readouterr()

    assert released == 2
    assert "original claimant" in captured.err
    live = _live_store_claim()
    assert live.agent == "Grok session-1"


@pytest.mark.parametrize("role", ["builder", "reviewer"])
def test_cli_release_omitted_flags_posts_the_outcome_using_selected_claim_role(
    monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    standing = request("mine", "Ada", issue=72, role=role, branch="lane-72", scope=("src",))
    client = FakeForge()
    _patch_release_session(monkeypatch, client, standing)

    released = issue_claim.main(["--repo", REPOSITORY, "release", "72", "--abandoned", "stopped"])

    assert released == 0
    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


def test_cli_release_omitted_claim_id_releases_when_foreign_peer_exists_on_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mine = request("mine", "Ada", issue=72, role="reviewer", branch="lane-72", scope=("src",))
    client = FakeForge()
    _patch_release_session(monkeypatch, client, mine)

    released = issue_claim.main(["--repo", REPOSITORY, "release", "72", "--abandoned", "stopped"])

    assert released == 0
    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


@pytest.mark.parametrize(
    ("holder", "session", "arguments", "session_role", "repeat"),
    [
        pytest.param(
            "Ada",
            "Other",
            ("--abandoned", "stopped"),
            "reviewer",
            "aco release 72 --abandoned stopped --agent Ada",
            id="abandoned",
        ),
        pytest.param(
            "claude-head",
            "Claude s-1",
            ("--merged", "12"),
            "reviewer",
            "aco release 72 --merged 12 --agent claude-head",
            id="merged-by-an-explicit-agent",
        ),
        pytest.param(
            "Claude s-1",
            "Other",
            ("--merged", "12", "--role", "builder"),
            "builder",
            "aco release 72 --merged 12 --agent 'Claude s-1' --role reviewer",
            id="other-role-and-a-quoted-agent",
        ),
        pytest.param(
            "Ada",
            "Other",
            ("--merged", "12", "--keep-worktree", "--json"),
            "reviewer",
            "aco release 72 --merged 12 --keep-worktree --json --agent Ada",
            id="keeps-the-worktree-and-json-flags",
        ),
    ],
)
def test_cli_release_by_another_claimant_names_the_holders_repeat_without_a_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    holder: str,
    session: str,
    arguments: tuple[str, ...],
    session_role: str,
    repeat: str,
) -> None:
    """REL-12: a release by another agent or role names
    the exact repeat as the holder before it mentions the coordinator
    override -- the songmaker case is a claim taken with `--agent
    claude-head` whose session later falls back to its session id."""
    standing = request("mine", holder, issue=72, role="reviewer", branch="lane-72", scope=("src",))
    _patch_release_session(monkeypatch, FakeForge(), standing, agent=session, branch="lane-72")

    released = issue_claim.main(["--repo", REPOSITORY, "release", "72", *arguments])
    captured = capsys.readouterr()

    assert (released, captured.out == "") == (2, "--json" not in arguments)
    assert captured.err == (
        f"ERROR: only the original claimant may release; repeat as the holder with `{repeat}`, "
        f"or use an explicit coordinator override (holder='{holder} (reviewer)', "
        f"this session='{session} ({session_role})')\n"
    )
    assert store.fetch_state(worktree=Path("."), remote="origin").claims != {}


def test_cli_release_without_a_claim_names_the_github_item_by_its_forge_number(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """REL-09 under `storage = "github"`:
    releasing an item nobody claims refuses naming it `#<n>`, byte-identical
    to the sentence before the state-ref renderer existed."""
    _patch_release_session(monkeypatch, FakeForge())

    released = issue_claim.main(["--repo", REPOSITORY, "release", "72", "--abandoned", "stopped"])

    assert released == 2
    assert capsys.readouterr().err == "ERROR: issue #72 has no active build claim\n"


def test_cli_release_explicit_claim_id_ignores_checkout_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    standing = request("mine", "Ada", issue=72, role="reviewer", branch="lane-72", scope=("src",))
    client = FakeForge()
    _patch_release_session(monkeypatch, client, standing, forbid_git=True)

    released = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "release",
            "72",
            "--claim-id",
            "mine",
            "--abandoned",
            "stopped",
        ]
    )
    assert released == 0
    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


@pytest.mark.parametrize(
    "flags",
    [
        ("--coordinator-override", "--abandoned", "takeover"),
        ("--coordinator-override", "--role", "builder", "--abandoned", "takeover"),
        ("--coordinator-override", "--merged", "12"),
    ],
)
def test_cli_release_override_fails_before_git_and_github(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flags: tuple[str, ...],
) -> None:
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Ada"})
    forbid_github_construction(monkeypatch)

    def unused(arguments: list[str], **_kwargs: object) -> str:
        pytest.fail("coordinator override must fail before git")

    monkeypatch.setattr(checkout, "git_output", unused)

    released = issue_claim.main(["--repo", REPOSITORY, "release", "72", *flags])
    captured = capsys.readouterr()

    assert released == 2
    assert captured.out == ""
    assert "ERROR:" in captured.err
    assert "coordinator override" in captured.err


def test_cli_release_omitted_claim_id_fails_closed_on_detached_head(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Ada"})
    forbid_github_construction(monkeypatch)
    monkeypatch.setattr(checkout, "git_output", lambda arguments, **_kwargs: "")

    released = issue_claim.main(["--repo", REPOSITORY, "release", "72", "--abandoned", "stopped"])
    captured = capsys.readouterr()

    assert released == 2
    assert captured.out == ""
    assert "ERROR:" in captured.err
    assert "pass --claim-id" in captured.err


def test_cli_claim_omitted_base_and_branch_posts_filled_checkout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeForge()
    git_values = git_checkout()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())

    claimed = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Codex Sol",
            "--role",
            "builder",
            "--scope",
            "src",
            "--claim-id",
            "cli-claim",
        ]
    )

    assert claimed == 0
    assert "CLAIMED issue #72" in capsys.readouterr().out
    posted = _live_store_claim()
    assert posted.base == BASE
    assert posted.branch == "codex/issue-72"
    assert posted.scope == ("src",)


def test_cli_claim_and_release_round_trip_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())

    claimed = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Codex Sol",
            "--role",
            "builder",
            "--base",
            BASE,
            "--branch",
            "codex/issue-72",
            "--scope",
            "src",
            "--claim-id",
            "cli-claim",
        ]
    )
    released = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "release",
            "72",
            "--agent",
            "Codex Sol",
            "--role",
            "builder",
            "--abandoned",
            "stopped",
            "--claim-id",
            "cli-claim",
        ]
    )

    assert (claimed, released) == (0, 0)


def test_cli_dispatch_adapter_error_denies_with_exit_code_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`cli.main`'s shared error handling: a forge adapter construction
    failure denies loud with exit 2, never a traceback."""
    monkeypatch.setattr(
        github,
        "GitHubForge",
        lambda repository: (_ for _ in ()).throw(ClaimError("adapter failed")),
    )
    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 2
    assert "ERROR: adapter failed" in capsys.readouterr().err


@pytest.fixture(autouse=True)
def _stub_versioned_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        checkout,
        "versioned_paths",
        lambda **_kwargs: (
            "LICENSE",
            "README.md",
            "pyproject.toml",
            "src/aco/__init__.py",
        ),
    )


@pytest.fixture(autouse=True)
def _stub_board_config_tracked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every CLI test reads a tracked `board.toml` by default:
    the untracked/ignored refusal is its own axis from `checkout.versioned_paths()`'s
    scope-width listing above, so a scope-width fixture fixing one never has
    to carry the other. A test proving the refusal itself overrides this."""
    stub_board_config_tracked(monkeypatch)


@pytest.fixture(autouse=True)
def _stub_canonical_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every CLI store command refuses a forge-target / canonical-remote
    mismatch. Tests talk to `--repo example/agent-coordination`
    against a fake; this stub is the matching remote URL so they are not
    refused before the behaviour under test.
    """
    monkeypatch.setattr(
        checkout, "remote_url", lambda remote, **_kwargs: f"git@github.com:{REPOSITORY}.git"
    )


@pytest.fixture(autouse=True)
def _default_open_issue_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """A claim target outside the fetched open board defaults to OPEN.

    A closed or missing issue never appears in `list_open_board_issues` and
    would otherwise need a real `gh api` call; every test that isn't
    exercising that lookup relies on this default instead, and a test that
    does exercise it overrides `board_read.fetch_issue_reference` directly.
    """
    monkeypatch.setattr(
        board_read,
        "fetch_issue_reference",
        lambda client, number: forge.ItemReference(forge.ItemState.OPEN, "", ""),
    )


# A test's toplevel is a scratch directory with no trunk (`conftest.py`'s
# `_isolate_git_toplevel`), so the live trunk reads would fail loud; tests of
# the trunk itself (tests/test_checkout.py, tests/test_session.py) and the
# real-repository scenarios here (`redirect_toplevel`) read it live. That
# trunk holds no committed board configuration, so no file is lane-shared;
# a test of the lane-shared lines restores the live read.
@pytest.fixture(autouse=True)
def _stub_trunk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(checkout, "file_at_revision", lambda _path, **_kwargs: None)
    monkeypatch.setattr(
        checkout,
        "trunk_ref_after",
        lambda remote, _recorded_head, **_kwargs: f"refs/remotes/{remote}/main",
    )
    monkeypatch.setattr(checkout, "fetch_remote", lambda *_args, **_kwargs: None)


@pytest.fixture(autouse=True)
def _freeze_cli_now(monkeypatch: pytest.MonkeyPatch) -> None:
    freeze_cli_now(monkeypatch)


def _patch_status_cli(monkeypatch: pytest.MonkeyPatch, client: FakeForge) -> None:
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(
        checkout,
        "versioned_paths",
        lambda **_kwargs: (
            "LICENSE",
            "README.md",
            "pyproject.toml",
            "src/aco/__init__.py",
        ),
    )
    monkeypatch.setattr(cmd_status, "datetime", FixedDateTime)


_STATUS_NOW = datetime(2026, 8, 21, tzinfo=UTC)


class _FakeStore:
    """An in-memory `refs/aco/state` double for CLI write-path tests:
    `fetch_state`/`commit_transition` delegate here, but every
    transition still runs through the real `protocol.apply` -- identity/
    resource conflicts, coordinator override, and the codec all behave
    exactly as the real store would, without a git subprocess. This is the
    "store fake" the plan's own acceptance criteria name for claim/release/
    rescope tests. `claim_ages` answers every live claim's age as
    `_STATUS_NOW` (matching the file's autouse `FixedDateTime` "now") unless
    `ages` names a claim id's age explicitly -- board/rulings/next read ages
    through this same fake rather than a separate one.
    """

    def __init__(
        self,
        claims: Mapping[str, protocol.ActiveClaim] | None = None,
        *,
        tip: str | None = BASE,
        ages: Mapping[str, datetime] | None = None,
        consumed_ids: frozenset[protocol.ClaimId] | None = None,
        resources: Mapping[str, protocol.ResourceRecord] | None = None,
        items: Mapping[str, protocol.ObjectId] | None = None,
        lane_events: tuple[metrics.LaneEvent, ...] = (),
        unparsed_lifecycle_commits: int = 0,
    ) -> None:
        live = dict(claims or {})
        derived_ids = frozenset(claim.claim_id for claim in live.values())
        derived_resources: dict[str, protocol.ResourceRecord] = {}
        occupied: dict[str, set[int]] = {}
        for claim in live.values():
            if claim.resource is None:
                continue
            occupied.setdefault(claim.resource.name, set()).add(claim.resource.value)
        derived_resources = {
            name: protocol.ResourceRecord(name, tuple(sorted(values)))
            for name, values in occupied.items()
        }
        self.state = protocol.ClaimState(
            tip=None if tip is None else protocol.ObjectId(tip),
            claims=live,
            consumed_ids=consumed_ids if consumed_ids is not None else derived_ids,
            resources=dict(resources) if resources is not None else derived_resources,
            items=dict(items or {}),
        )
        self.transitions: list[protocol.ClaimTransitionIntent] = []
        self._ages = dict(ages or {})
        self._lane_events = lane_events
        self._unparsed_lifecycle_commits = unparsed_lifecycle_commits

    def fetch_state(self, *, worktree: Path, remote: str) -> protocol.ClaimState:
        return self.state

    def peek_state(self, *, worktree: Path, remote: str) -> protocol.ClaimState:
        # This fake never models the anchor/lineage-stamp side effect
        # `fetch_state` alone carries against real git, so the same
        # in-memory state answers both: `land`'s claims
        # observation is the one caller this fake needs it for.
        return self.state

    def commit_transition(
        self,
        *,
        observed: store.Observation,
        subject: str,
        intent: protocol.ClaimTransitionIntent,
        transport: object = None,
    ) -> protocol.ClaimState:
        if observed.state.tip is None:
            raise protocol.ClaimError(protocol.MISSING_STATE_REF)
        self.transitions.append(intent)
        self.state = protocol.apply(self.state, intent)
        return self.state

    def claim_ages(
        self,
        *,
        worktree: Path,
        tip: protocol.ObjectId,
        claims: Iterable[protocol.ActiveClaim],
    ) -> dict[str, datetime]:
        return {claim.claim_id: self._ages.get(claim.claim_id, _STATUS_NOW) for claim in claims}

    def claim_lifecycle(self, *, worktree: Path, tip: protocol.ObjectId) -> store.ClaimLifecycle:
        return store.ClaimLifecycle(
            events=self._lane_events, unparsed=self._unparsed_lifecycle_commits
        )


def _patch_store_write(
    monkeypatch: pytest.MonkeyPatch,
    *claims: protocol.ActiveClaim,
    tip: str | None = BASE,
    ages: Mapping[str, datetime] | None = None,
    consumed_ids: frozenset[protocol.ClaimId] | None = None,
    resources: Mapping[str, protocol.ResourceRecord] | None = None,
    items: Mapping[str, protocol.ObjectId] | None = None,
    lane_events: tuple[metrics.LaneEvent, ...] = (),
    unparsed_lifecycle_commits: int = 0,
) -> _FakeStore:
    fake = _FakeStore(
        {protocol.claim_key(claim.identity, claim.branch): claim for claim in claims},
        tip=tip,
        ages=ages,
        consumed_ids=consumed_ids,
        resources=resources,
        items=items,
        lane_events=lane_events,
        unparsed_lifecycle_commits=unparsed_lifecycle_commits,
    )
    monkeypatch.setattr(store, "fetch_state", fake.fetch_state)
    monkeypatch.setattr(store, "peek_state", fake.peek_state)
    monkeypatch.setattr(store, "commit_transition", fake.commit_transition)
    monkeypatch.setattr(store, "claim_ages", fake.claim_ages)
    monkeypatch.setattr(store, "claim_lifecycle", fake.claim_lifecycle)
    monkeypatch.setattr(
        checkout, "remote_url", lambda remote, **_kwargs: f"git@github.com:{REPOSITORY}.git"
    )
    stub_every_remote_configured(monkeypatch)
    return fake


@pytest.fixture(autouse=True)
def _stub_store_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every CLI write/read of `refs/aco/state` uses the in-memory fake unless
    a test installs a more specific one (`_patch_store_write` with standing
    claims, `_patch_status_store`, or `tip=None` for the missing-ref case).
    """
    _patch_store_write(monkeypatch)


def _patch_status_store(
    monkeypatch: pytest.MonkeyPatch,
    *claims: protocol.ActiveClaim,
    ages: Mapping[str, datetime] | None = None,
) -> None:
    """Fake `status`'s two store reads: the fetched claim state,
    and each claim's age (every claim reads as opened at `_STATUS_NOW` -- 0h
    0m old -- unless `ages` names it by claim id). Every `status`/
    `status --path` test builds its live claims via `standing_active_claim` and
    wires them in here instead of posting through a ledger-comment
    `FakeForge`.
    """
    monkeypatch.setattr(
        checkout, "remote_url", lambda remote, **_kwargs: f"git@github.com:{REPOSITORY}.git"
    )
    stub_every_remote_configured(monkeypatch)
    keyed = {protocol.claim_key(claim.identity, claim.branch): claim for claim in claims}
    state = protocol.ClaimState(tip=protocol.ObjectId(BASE), claims=keyed)
    monkeypatch.setattr(store, "fetch_state", lambda *, worktree, remote: state)
    resolved_ages: dict[str, datetime] = {claim.claim_id: _STATUS_NOW for claim in claims}
    if ages is not None:
        resolved_ages.update(ages)

    def fake_claim_ages(
        *,
        worktree: Path,
        tip: protocol.ObjectId,
        claims: Iterable[protocol.ActiveClaim],
    ) -> dict[str, datetime]:
        return {claim.claim_id: resolved_ages[claim.claim_id] for claim in claims}

    monkeypatch.setattr(store, "claim_ages", fake_claim_ages)
    monkeypatch.setattr(cmd_status, "datetime", FixedDateTime)


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        pytest.param(
            ["claim", "10", "--agent", "Codex Sol", "--scope", "src/work.py"],
            "ERROR: #10 body incomplete: ",
            id="claim",
        ),
        pytest.param(["check", "10"], "ISSUE #10 body incomplete: ", id="check"),
        pytest.param(["next"], "#10: body incomplete: ", id="next"),
        pytest.param(["next", "--json"], '"command": "aco claim 11 ', id="next-json"),
        pytest.param(["status", "10"], "UNCLAIMED issue #10", id="status"),
        pytest.param(["board", "--json"], '"actionable_reason": "blocked by #11"', id="board-json"),
    ],
)
def test_every_output_names_a_github_item_by_its_number(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    arguments: list[str],
    expected: str,
) -> None:
    """The `storage = github` twin of
    `TestCliStateRefForge`'s id proof: the same commands name an item
    `#<n>`, and a pasteable argument its bare `n`. `item edit`/`close` have
    no twin: under `github` they refuse outright (PIN-10, PIN-11)."""
    unfilled_body = unfilled_block_body()
    incomplete = board_issue(10, "Fresh work", unfilled_body)
    actionable = board_issue(11, "Slice A", complete_contract("Ship slice A."))
    blocked, dependencies = blocked_issue(12, "Slice B", block_dependency(11))
    client = _configured_board_client(
        monkeypatch,
        tmp_path,
        open_issues=(incomplete, actionable, blocked),
        dependencies=dependencies,
    )
    client.issue_references[10] = forge.ItemReference(
        forge.ItemState.OPEN, "Fresh work", unfilled_body
    )
    monkeypatch.setattr(
        cmd_claim,
        "_request",
        lambda _arguments, **_kwargs: request(issue=10, scope=("src/work.py",)),
    )

    issue_claim.main(["--repo", REPOSITORY, *arguments])

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert expected in output
    assert "aco-" not in output


def test_cli_lane_claim_and_release_round_trip_without_issue_number(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The `claim`/`release` scenario: a docs/ checkout claims
    and releases again, all without ever passing an issue number. (The
    `status` half -- that the store shows a live lane claim -- is proven
    separately below.)"""
    set_agent_identity_env(monkeypatch, {"ACO_AGENT": "Codex Sol"})
    client = FakeForge()
    _patch_status_cli(monkeypatch, client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    git_values = {
        ("branch", "--show-current"): "docs/lane-cleanup",
        ("rev-parse", "--show-toplevel"): "/repo",
        ("rev-parse", "HEAD"): BASE,
    }
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "--role",
                "builder",
                "--base",
                BASE,
                "--branch",
                "docs/lane-cleanup",
                "--scope",
                "docs",
                "--claim-id",
                "cli-lane-claim",
            ]
        )
        == 0
    )
    capsys.readouterr()

    released = issue_claim.main(["--repo", REPOSITORY, "release", "--abandoned", "stopped"])
    assert released == 0
    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


@pytest.mark.parametrize("command", ["claim", "release"])
def test_cli_lane_mode_refuses_a_non_conventional_branch(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_agent_identity_env(monkeypatch, {"ACO_AGENT": "Codex Sol"})
    client = FakeForge()
    _patch_status_cli(monkeypatch, client)
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: "codex/issue-38-issueless-claims"
    )

    arguments = ["--repo", REPOSITORY, command]
    if command == "claim":
        arguments += [
            "--role",
            "builder",
            "--base",
            BASE,
            "--branch",
            "codex/issue-38-issueless-claims",
            "--scope",
            "src",
            "--claim-id",
            "cli-lane-claim",
        ]
    else:
        arguments += ["--abandoned", "stopped"]

    assert issue_claim.main(arguments) == 2
    captured = capsys.readouterr()
    assert "codex/issue-38-issueless-claims" in captured.err
    assert "issue number" in captured.err
    assert "'docs/'" in captured.err
    assert "'fix/'" in captured.err


def test_cli_release_requires_a_non_empty_current_branch_without_an_issue(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_agent_identity_env(monkeypatch, {"ACO_AGENT": "Codex Sol"})
    client = FakeForge()
    _patch_status_cli(monkeypatch, client)
    monkeypatch.setattr(checkout, "git_output", lambda arguments, **_kwargs: "")

    status = issue_claim.main(["--repo", REPOSITORY, "release", "--abandoned", "stopped"])

    assert status == 2
    assert "lane release requires a non-empty current branch" in capsys.readouterr().err


def test_cli_rescope_requires_a_non_empty_current_branch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rescope always operates on the checked-out worktree's own claim, so a
    detached or branchless checkout must refuse even when an issue number is
    also given -- unlike release, it never falls back to the issue alone."""
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    git_values = git_checkout(branch="")
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )

    status = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "rescope",
            "72",
            "--agent",
            "Ada",
            "--add",
            "/repo/src/new.py",
        ]
    )

    assert status == 2
    assert "non-empty current branch" in capsys.readouterr().err


def _no_lane_shared() -> dict[str, object]:
    """`--json`'s lane-shared keys when the trunk names none."""
    return {"lane_shared": [], "lane_shared_unavailable": None}


def test_cli_claim_and_release_accept_json_while_parent_and_bootstrap_reject_it() -> None:
    claimed = issue_claim._parser().parse_args(
        ["claim", "42", "--scope", "src/widget.py", "--json"]
    )
    released = issue_claim._parser().parse_args(["release", "42", "--merged", "12", "--json"])
    omitted_claim = issue_claim._parser().parse_args(["claim", "42", "--scope", "src"])
    omitted_release = issue_claim._parser().parse_args(["release", "42", "--merged", "12"])

    assert claimed.json is True
    assert released.json is True
    assert omitted_claim.json is False
    assert omitted_release.json is False
    with pytest.raises(SystemExit) as refused_parent:
        issue_claim.main(["--json", "status"])
    assert refused_parent.value.code == 2
    with pytest.raises(SystemExit) as refused_bootstrap:
        issue_claim.main(["bootstrap", "--json"])
    assert refused_bootstrap.value.code == 2


@pytest.mark.parametrize(
    ("scope_flags", "board_issues"),
    [
        pytest.param(("--scope", "src"), (), id="an-explicit-scope"),
        pytest.param(
            (),
            (board_issue(72, "Work", complete_contract("Ship it.", scope=["src"])),),
            id="a-derived-scope",
        ),
    ],
)
def test_cli_claim_without_json_prints_the_claimed_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scope_flags: tuple[str, ...],
    board_issues: tuple[Issue, ...],
) -> None:
    """The human cost line prints
    identically whether the scope came from `--scope` or was derived from
    the item's own body -- the board fetch a derived scope costs is never a
    silent, unprinted detour."""
    client = _arranged_claim_client(monkeypatch)
    client.board_issues = board_issues

    claimed = issue_claim.main(_claim_argv(*scope_flags))

    assert claimed == 0
    assert capsys.readouterr().out == (
        "CLAIMED issue #72: cli-claim\n"
        "1 of 4 versioned files (25%); overlaps no other open claims\n"
    )


def _arranged_claim_client(monkeypatch: pytest.MonkeyPatch) -> FakeForge:
    """The GitHub-storage `claim` arrangement every scope-derivation proof
    below shares: a fake forge, a no-op checkout validator, a
    fixed versioned-file listing via `git_checkout`, and a fresh in-memory
    store -- the same six lines `test_cli_claim_without_json_prints_the_claimed_line`
    repeats inline, factored so each derivation case states only what makes
    it different."""
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    git_values = git_checkout()
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    _patch_store_write(monkeypatch)
    return client


def _claim_argv(*flags: str, issue: int = 72, claim_id: str = "cli-claim") -> list[str]:
    return [
        "--repo",
        REPOSITORY,
        "claim",
        str(issue),
        "--agent",
        "Codex Sol",
        "--role",
        "builder",
        "--base",
        BASE,
        "--branch",
        f"codex/issue-{issue}",
        "--claim-id",
        claim_id,
        *flags,
    ]


def test_claim_with_an_untracked_scope_entry_outside_a_working_tree_keeps_the_checkout_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The width gate asks the run's toplevel for an
    entry that is no git tree before the claim's own toplevel refusal runs;
    that failed read must leave the refusal exactly as the claim reports it
    without the gate."""
    scope_directories = checkout.scope_directories
    _arranged_claim_client(monkeypatch)
    monkeypatch.setattr(checkout, "scope_directories", scope_directories)
    git_values = git_checkout()

    def outside_a_working_tree(arguments: list[str], **_kwargs: object) -> str:
        if arguments[0] == "ls-tree":
            return ""
        if arguments[0] == "rev-parse":
            raise ClaimError("fatal: this operation must be run in a work tree")
        return git_values[tuple(arguments)]

    monkeypatch.setattr(checkout, "git_output", outside_a_working_tree)

    assert issue_claim.main(_claim_argv("--scope", "scratch")) == 2
    assert capsys.readouterr().err == (
        "ERROR: this command reads the repository's body contract from "
        ".aco/board.toml and needs a checkout (a shallow one is "
        "enough): fatal: this operation must be run in a work tree\n"
    )


def test_cli_claim_json_reports_a_git_failure_reading_the_scope_as_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLAIM-26: a git failure reading a scope entry is not a path that is no
    directory, so the claim refuses `unavailable` with git's detail instead
    of admitting a directory without `--whole`."""
    scope_directories = checkout.scope_directories
    _arranged_claim_client(monkeypatch)
    monkeypatch.setattr(checkout, "scope_directories", scope_directories)
    _fail_scope_reads(monkeypatch)

    status = issue_claim.main(_claim_argv("--scope", "docs", "--json"))

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == f"ERROR: {SCOPE_READ_FAILURE}\n"
    _assert_json_refusal_object(captured.err, captured.out, reason="unavailable")


@pytest.mark.parametrize(
    (
        "item_scope",
        "requested_scope_flags",
        "expected_status",
        "expected_scope_or_error",
        "versioned",
        "expected_cost",
    ),
    [
        pytest.param(
            ["src/work.py"],
            (),
            0,
            ["src/work.py"],
            None,
            (0, 4, 0.0),
            id="omitted-takes-the-items-own-scope",
        ),
        pytest.param(
            None,
            (),
            2,
            cmd_claim._CLAIM_SCOPE_MISSING,
            None,
            None,
            id="omitted-with-no-body-scope-refuses-by-name",
        ),
        pytest.param(
            ["src/work.py"],
            ("--scope", "src/other.py"),
            2,
            cmd_claim._CLAIM_SCOPE_MISMATCH,
            None,
            None,
            id="a-differing-explicit-scope-refuses-by-name",
        ),
        pytest.param(
            ["a.py", "b.py"],
            ("--scope", "b.py", "--scope", "a.py"),
            0,
            ["a.py", "b.py"],
            None,
            (0, 4, 0.0),
            id="the-same-set-in-a-different-order-is-accepted",
        ),
        pytest.param(
            ["a.py", "b.py", "c.py", "d.py"],
            (),
            2,
            "scope is wide: 4 paths exceeds three; pass --whole REASON or set whole in the body",
            None,
            None,
            id="a-derived-wide-scope-refuses-without-whole",
        ),
        pytest.param(
            ["a.py", "b.py", "c.py", "d.py"],
            ("--whole", "spans the whole review pass"),
            0,
            ["a.py", "b.py", "c.py", "d.py"],
            None,
            (0, 4, 0.0),
            id="a-derived-wide-scope-is-accepted-with-whole",
        ),
        pytest.param(
            ["docs/report,v2.md"],
            (),
            0,
            ["docs/report,v2.md"],
            ("docs/report,v2.md",),
            (1, 1, 1.0),
            id="a-comma-inside-a-derived-path-grounds-and-is-kept-whole",
        ),
        pytest.param(
            ["a.py,b.py"],
            (),
            2,
            "'a.py,b.py' matches no versioned file; one --scope path per flag, so its comma "
            "is read literally -- repeat --scope for a second path",
            None,
            None,
            id="a-comma-inside-a-derived-path-that-grounds-nothing-refuses-by-name",
        ),
    ],
)
def test_cli_claim_scope_derivation_against_the_items_own_body(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    item_scope: list[str] | None,
    requested_scope_flags: tuple[str, ...],
    expected_status: int,
    expected_scope_or_error: list[str] | str,
    versioned: tuple[str, ...] | None,
    expected_cost: tuple[int, int, float] | None,
) -> None:
    """Issue-mode `--scope`
    derivation and validation against the item's own body -- omitted takes
    it, refusing by name when the body carries none; an explicit value must
    name the same canonical set (`protocol.valid_scope`),
    refusing by name when it differs and accepting the same set typed in a
    different order; a derived scope is exactly as wide, by the same rule,
    as one passed on `--scope` -- refused without `--whole`, accepted with
    it. Every row reads the open board -- the listing `claim` needs anyway
    for its slice-rule checks -- exactly once, whether the scope came from
    it (omitted `--scope`) or was only checked against it (explicit
    `--scope`), and never falls back to the single-item lookup, since #72
    is always open and always in that listing.

    A derived scope routes through the same
    `cmd_claim.scope_versioning` call as an explicit one (`cmd_claim.run`),
    so the comma-grounding rule proved on `--scope` by
    `test_cli_claim_scope_keeps_a_comma_inside_one_path` and
    `test_cli_claim_refuses_a_comma_scope_that_matches_nothing_in_the_checkout`
    must hold identically for a body-derived one -- the two trailing rows
    here ground a comma-bearing entry against a matching versioned file and
    refuse one that matches nothing, by the same message. Every accepting
    row also asserts the `--json` cost fields (`versioned_files`,
    `versioned_files_total`, `share`) a derived claim prints, not only its
    resolved `scope` -- the same fields an explicit `--scope` claim prints,
    since both origins feed the one shared `cmd_claim.scope_versioning` call."""
    client = _arranged_claim_client(monkeypatch)
    body = (
        complete_contract("Ship it.")
        if item_scope is None
        else complete_contract("Ship it.", scope=item_scope)
    )
    client.board_issues = (board_issue(72, "Work", body),)
    if versioned is not None:
        monkeypatch.setattr(checkout, "versioned_paths", lambda **_kwargs: versioned)
    board_reads: list[None] = []
    real_list_open_board_issues = client.list_open_board_issues

    def _counted_list_open_board_issues() -> tuple[Issue, ...]:
        board_reads.append(None)
        return real_list_open_board_issues()

    monkeypatch.setattr(client, "list_open_board_issues", _counted_list_open_board_issues)

    status = issue_claim.main(_claim_argv(*requested_scope_flags, "--json"))

    assert len(board_reads) == 1
    assert client.issue_reference_lookups == []
    assert status == expected_status
    if expected_status == 0:
        payload = json.loads(capsys.readouterr().out)
        assert payload["scope"] == expected_scope_or_error
        if expected_cost is not None:
            n, total, share = expected_cost
            assert payload["versioned_files"] == n
            assert payload["versioned_files_total"] == total
            assert payload["share"] == share
        return
    assert capsys.readouterr().err == f"ERROR: {expected_scope_or_error}\n"
    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


def test_cli_claim_without_scope_names_a_malformed_body_before_no_scope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A target whose `aco` block is
    malformed refuses by naming that defect -- reusing the same block-
    defect reader `check -` uses -- before scope derivation ever gets
    to name the less specific "item names no scope"."""
    client = _arranged_claim_client(monkeypatch)
    client.board_issues = (
        board_issue(72, "Work", block_body(f'{MINIMAL_BLOCK_TOML}owner = "someone"\n')),
    )

    status = issue_claim.main(_claim_argv("--json"))

    assert status == 2
    captured = capsys.readouterr()
    assert captured.err == "ERROR: #72 body malformed: owner: unknown top-level key owner\n"
    _assert_json_refusal_object(captured.err, captured.out, reason="body_invalid")


def test_cli_claim_without_scope_refuses_a_missing_target_by_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A target unreachable through the open-board listing:
    scope derivation itself refuses `target_invalid`, before any slice-rule
    check ever runs against it."""
    client = _arranged_claim_client(monkeypatch)
    client.issue_references[72] = forge.ItemReference(forge.ItemState.MISSING, "", "")

    status = issue_claim.main(_claim_argv("--json"))

    assert status == 2
    captured = capsys.readouterr()
    assert captured.err == "ERROR: #72 does not exist\n"
    _assert_json_refusal_object(captured.err, captured.out, reason="target_invalid")


def test_cli_claim_without_scope_reports_unavailable_for_a_forge_outage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A forge outage while deriving scope (CLM-27) is a
    different failure from a missing or pull-request target: it never
    appears in the open-board listing `client.item_reference` itself
    raises `forge.ForgeTransientError` reading it, so `claim --json`
    reports `unavailable`, not `target_invalid`."""
    client = _arranged_claim_client(monkeypatch)

    def unreachable(number: int) -> forge.ItemReference:
        raise forge.ForgeTransientError("gh: connection reset")

    monkeypatch.setattr(client, "item_reference", unreachable)

    status = issue_claim.main(_claim_argv("--json"))

    assert status == 2
    captured = capsys.readouterr()
    _assert_json_refusal_object(captured.err, captured.out, reason="unavailable")


def test_cli_claim_derives_whole_from_the_items_own_body_when_wide(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--whole` omitted, a target naming its own body
    `whole` justifies a wide derived scope exactly as `--whole REASON`
    would -- the item's own sentence lands on the claim itself."""
    reason = "the four adapters share one lock"
    client = _arranged_claim_client(monkeypatch)
    client.board_issues = (
        board_issue(
            72,
            "Work",
            complete_contract("Ship it.", scope=["a.py", "b.py", "c.py", "d.py"], whole=reason),
        ),
    )

    status = issue_claim.main(_claim_argv())

    assert status == 0
    assert "CLAIMED issue #72" in capsys.readouterr().out
    assert _live_store_claim().whole_reason == reason


def test_cli_claim_names_both_remedies_when_the_body_has_no_whole(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Neither `--whole` nor the item's own body `whole`
    present, the width gate's refusal names both remedies."""
    client = _arranged_claim_client(monkeypatch)
    client.board_issues = (
        board_issue(
            72, "Work", complete_contract("Ship it.", scope=["a.py", "b.py", "c.py", "d.py"])
        ),
    )

    status = issue_claim.main(_claim_argv())

    assert status == 2
    assert capsys.readouterr().err == (
        "ERROR: scope is wide: 4 paths exceeds three; "
        "pass --whole REASON or set whole in the body\n"
    )


def test_cli_claim_explicit_whole_overrides_the_items_own_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An explicit `--whole` always wins over the
    item's own body `whole`."""
    body_reason = "the four adapters share one lock"
    cli_reason = "urgent, splitting later"
    client = _arranged_claim_client(monkeypatch)
    client.board_issues = (
        board_issue(
            72,
            "Work",
            complete_contract(
                "Ship it.", scope=["a.py", "b.py", "c.py", "d.py"], whole=body_reason
            ),
        ),
    )

    status = issue_claim.main(_claim_argv("--whole", cli_reason))

    assert status == 0
    assert _live_store_claim().whole_reason == cli_reason


@pytest.mark.parametrize("source", ["flag", "body"])
@pytest.mark.parametrize(
    "value", ["x" * 513, "a\nb", " a", ""], ids=["long", "multiline", "padded", "empty"]
)
def test_claim_whole_flag_and_body_share_the_bound(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], source: str, value: str
) -> None:
    """Spec: CLM-21, CLM-36, BODY-62. T3: matrix 9, 34."""
    client = _arranged_claim_client(monkeypatch)
    raw_body = complete_contract(
        "Ship it.", scope=["a.py"], whole=value if source == "body" else "ok"
    )
    _serve_whole_claim_body(client, raw_body)
    flags = ("--whole", value) if source == "flag" else ()
    assert issue_claim.main(_claim_argv(*flags)) == 2
    assert "whole reason must be one bounded non-empty line" in capsys.readouterr().err
    assert not store.fetch_state(worktree=Path("."), remote="origin").claims
    _assert_whole_body_unchanged(client, raw_body)


def _serve_whole_claim_body(client: FakeForge, raw_body: str) -> None:
    client.board_issues = (board_issue(72, "Work", raw_body),)
    client.issue_references[72] = forge.ItemReference(forge.ItemState.OPEN, "Work", raw_body)
    client.item_bodies[72] = raw_body


def _assert_whole_body_unchanged(client: FakeForge, raw_body: str) -> None:
    assert client.board_issues[0].body == raw_body
    assert client.issue_references[72].body == raw_body
    assert client.item_bodies[72] == raw_body
    assert not client.created_issues


@pytest.mark.parametrize(
    ("cell", "value", "scope", "flag", "reason", "field"),
    [
        (3, "x" * 513, (), None, "body_invalid", "whole"),
        (4, "a\nb", ("a.py",), None, "precondition_failed", "whole"),
        (5, " a", ("a.py", "b.py", "c.py", "d.py"), None, "body_invalid", "whole"),
        (6, "x" * 513, ("a.py", "b.py", "c.py", "d.py"), "ok", "precondition_failed", "whole"),
        (7, "ok", ("a.py", "b.py", "c.py", "d.py"), None, "body_invalid", "size"),
        (8, None, ("a.py", "b.py", "c.py", "d.py"), None, "unavailable", ""),
    ],
    ids=["cell3", "cell4", "cell5", "cell6", "cell7", "cell8"],
)
def test_claim_whole_body_refusal_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cell: int,
    value: str | None,
    scope: tuple[str, ...],
    flag: str | None,
    reason: str,
    field: str,
) -> None:
    """Spec: CLM-22, CLM-37, BODY-52. T4: fresh claims never write."""
    client = _arranged_claim_client(monkeypatch)
    entries: dict[str, str] = {} if value is None else {"whole": value}
    if field == "size":
        entries["size"] = "XL"
    raw_body = complete_contract("Ship it.", scope=["a.py", "b.py", "c.py", "d.py"], **entries)
    _serve_whole_claim_body(client, raw_body)
    flags = [part for path in scope for part in ("--scope", path)]
    if flag is not None:
        flags.extend(("--whole", flag))
    defect = (
        "size must be S, M, or L"
        if field == "size"
        else "whole reason must be one bounded non-empty line"
    )
    label = "#72 " if reason == "body_invalid" else ""
    expected = f"ERROR: {label}body malformed: {field}: {defect}\n"
    if cell == 8:
        expected = (
            "ERROR: scope is wide: 4 paths exceeds three; "
            "pass --whole REASON or set whole in the body\n"
        )
    for json_flags in ((), ("--json",)):
        assert issue_claim.main(_claim_argv(*flags, *json_flags)) == 2
        captured = capsys.readouterr()
        assert captured.err == ("" if json_flags and reason == "precondition_failed" else expected)
        if json_flags:
            payload = json.loads(captured.out)
            assert payload["reason"] == reason
            if reason == "precondition_failed":
                assert payload["checks"]
        assert not store.fetch_state(worktree=Path("."), remote="origin").claims
        _assert_whole_body_unchanged(client, raw_body)


@pytest.mark.parametrize("wide", [False, True], ids=["cell10", "cell11"])
def test_claim_whole_replay_preserves_the_claim(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], wide: bool
) -> None:
    """Spec: CLM-15, CLM-37. T4: only wide replay reads the body."""
    client = _arranged_claim_client(monkeypatch)
    scope = ["a.py", "b.py", "c.py", "d.py"] if wide else ["a.py"]
    _serve_whole_claim_body(client, complete_contract("Ship it.", scope=scope, whole="ok"))
    assert issue_claim.main(_claim_argv()) == 0
    capsys.readouterr()
    before = _live_store_claim()
    raw_body = complete_contract("Ship it.", scope=scope, whole="x" * 513)
    _serve_whole_claim_body(client, raw_body)
    assert issue_claim.main(_claim_argv()) == (2 if wide else 0)
    captured = capsys.readouterr()
    if wide:
        assert (
            captured.err
            == "ERROR: #72 body malformed: whole: whole reason must be one bounded non-empty line\n"
        )
        assert issue_claim.main(_claim_argv("--json")) == 2
        assert json.loads(capsys.readouterr().out)["reason"] == "body_invalid"
    else:
        assert captured.out.startswith("CLAIMED issue #72: cli-claim\n")
    assert _live_store_claim() == before
    _assert_whole_body_unchanged(client, raw_body)


def test_claim_whole_accepts_the_body_boundary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CLM-21. T4: matrix 12."""
    client = _arranged_claim_client(monkeypatch)
    raw_body = complete_contract(
        "Ship it.", scope=["a.py", "b.py", "c.py", "d.py"], whole="x" * 512
    )
    _serve_whole_claim_body(client, raw_body)
    assert issue_claim.main(_claim_argv()) == 0
    assert capsys.readouterr().out.startswith("CLAIMED issue #72: cli-claim\n")
    assert _live_store_claim().whole_reason == "x" * 512
    _assert_whole_body_unchanged(client, raw_body)


@pytest.mark.parametrize(
    "operation", ["rescope-body", "rescope-flag", "new-flag", "edit-flag", "edit-body", "new-body"]
)
def test_whole_github_write_refusals_preserve_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], operation: str
) -> None:
    """Spec: CLM-36, RESC-24, BODY-52. T4: matrix 16-19."""
    client = _rescope_forge()
    _arrange_github_rescope(monkeypatch, client)
    before = _live_store_claim()
    invalid = complete_contract("Ship it.", whole="x" * 513)
    raw_body = (
        invalid if operation in {"rescope-body", "edit-body"} else complete_contract("Ship it.")
    )
    _serve_whole_claim_body(client, raw_body)
    commands = {
        "rescope-body": ["rescope", "72", "--add", "x.py"],
        "rescope-flag": ["rescope", "72", "--whole", " a"],
        "new-flag": ["item", "new", "--title", "Fresh", "--whole", "x" * 513],
        "edit-flag": ["item", "edit", "72", "--whole", ""],
        "edit-body": ["item", "edit", "72", "--whole", "ok"],
        "new-body": ["item", "new", "--title", "Fresh"],
    }
    for json_flags in ((), ("--json",)):
        monkeypatch.setattr(sys, "stdin", io.StringIO(invalid if operation == "new-body" else ""))
        argv = ["--repo", REPOSITORY, *commands[operation], *json_flags]
        result = run_cli(argv, capsys, stdin=invalid if operation == "new-body" else None)
        assert result.status == 2
        sentence = "whole reason must be one bounded non-empty line"
        if operation in {"rescope-body", "edit-body"}:
            command = "rescope" if operation == "rescope-body" else "item edit --whole"
            assert (
                result.stderr == f"ERROR: #72 body malformed: whole: {sentence}; "
                f"{command} needs a valid aco block\n"
            )
        elif operation == "new-body":
            assert f"body malformed: whole: {sentence}" in result.stderr
        else:
            assert result.stderr == f"ERROR: {sentence}\n"
        if json_flags:
            assert json.loads(result.stdout)["reason"] == (
                "body_invalid"
                if operation == "new-body"
                else "unavailable"
                if operation == "rescope-flag"
                else "precondition_failed"
            )
        assert _live_store_claim() == before
        _assert_whole_body_unchanged(client, raw_body)


def test_whole_github_next_and_board_report_the_defect(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BODY-52, NEXT-36. T4: matrix 30."""
    client = _arranged_claim_client(monkeypatch)
    raw_body = complete_contract("Ship it.", scope=["a.py"], whole="x" * 513)
    _serve_whole_claim_body(client, raw_body)
    assert issue_claim.main(["--repo", REPOSITORY, "next"]) == 3
    output = capsys.readouterr().out
    defect = "body malformed: whole: whole reason must be one bounded non-empty line"
    assert "SKIPPED" in output
    assert f"#72: {defect}" in output
    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 0
    row = next(row for row in json.loads(capsys.readouterr().out)["items"] if row["number"] == 72)
    assert (row["actionable"], row["actionable_reason"]) == (False, defect)
    _assert_whole_body_unchanged(client, raw_body)


@pytest.mark.parametrize(
    "mode",
    ["standing", "rebuild", "invalid-flag", "invalid-flag-standing"],
    ids=["cell14a", "cell14b", "cell38", "cell38a"],
)
def test_start_whole_resume_preserves_the_claim(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path, mode: str
) -> None:
    """Spec: START-06, CLM-36. T4: resumes preserve claims and stored bodies."""
    repo = _start_scenario(monkeypatch, tmp_path)
    valid_body = complete_contract("Build it.", scope=["a.py"])
    _serve_start_board(monkeypatch, _start_item(valid_body))
    monkeypatch.chdir(repo)
    argv = ["--repo", REPOSITORY, "start", "314"]
    assert issue_claim.main(argv) == 0
    capsys.readouterr()
    before_claim = _live_store_claim()
    built = worktrees_and_branches(repo)
    if mode not in {"standing", "invalid-flag-standing"}:
        _remove_the_lane_pair(repo)
    before = worktrees_and_branches(repo)
    refuses_flag = mode.startswith("invalid-flag")
    raw_body = (
        valid_body
        if refuses_flag
        else complete_contract("Build it.", scope=["a.py"], whole="x" * 513)
    )
    client = _serve_start_board(monkeypatch, _start_item(raw_body))
    flags = ["--whole", "a\nb"] if refuses_flag else []
    assert issue_claim.main([*argv, *flags]) == (2 if refuses_flag else 0)
    captured = capsys.readouterr()
    if refuses_flag:
        assert captured.err == "ERROR: whole reason must be one bounded non-empty line\n"
        assert "worktree:" not in captured.out
        assert worktrees_and_branches(repo) == before
    else:
        assert "worktree: " in captured.out
        assert f"branch: {_START_BRANCH}\n" in captured.out
        assert f"CLAIMED issue #314: {before_claim.claim_id}\n" in captured.out
        assert worktrees_and_branches(repo) == built
    assert _live_store_claim() == before_claim
    assert client.board_issues[0].body == raw_body
    assert client.issue_references[314].body == raw_body
    assert not client.item_bodies


def test_cli_claim_replay_of_a_wide_scope_without_whole_reads_only_its_own_item(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """PIN-29/CLM-15: a replayed wide claim that names no
    `--whole` takes its item's own `whole` from that item alone, so a
    whole-board read that would refuse (PIN-16) never stops the replay."""
    reason = "the four adapters share one lock"
    wide_scope = ["a.py", "b.py", "c.py", "d.py"]
    item_body = complete_contract("Ship it.", scope=wide_scope, whole=reason)
    client = _arranged_claim_client(monkeypatch)
    client.board_issues = (board_issue(72, "Work", item_body),)
    client.issue_references[72] = forge.ItemReference(forge.ItemState.OPEN, "Work", item_body)
    argv = _claim_argv(*(flag for path in wide_scope for flag in ("--scope", path)))
    assert issue_claim.main(argv) == 0
    capsys.readouterr()

    def board_read_refused() -> tuple[Issue, ...]:
        raise protocol.MalformedStateTreeError(
            "item aco-0a0a0a is referenced as a parent but does not exist"
        )

    monkeypatch.setattr(client, "list_open_board_issues", board_read_refused)

    status = issue_claim.main(argv)

    assert status == 0
    assert "CLAIMED issue #72: cli-claim" in capsys.readouterr().out
    assert _live_store_claim().whole_reason == reason


def test_cli_claim_replay_without_scope_takes_the_live_claims_own_stored_scope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A live claim already on this
    identity is a replayed, interrupted request even when the retry omits
    `--scope` -- its own stored scope is taken outright, with no forge call
    and no body read at all, so a retry never refuses merely because
    `--scope` was dropped, or the body changed, since the original claim was
    opened. The item's own current body now names a different scope
    entirely (`src/other.py`, not the claim's stored `src`); the stored
    scope still wins, proving the body is never consulted for a replay."""
    existing = request("live-claim", "Ada", issue=72, branch="codex/issue-72", scope=("src",))
    client = FakeForge(
        board_issues=(
            board_issue(72, "Work", complete_contract("Ship it.", scope=["src/other.py"])),
        )
    )
    _patch_status_cli(monkeypatch, client)
    _patch_store_write(monkeypatch, store_claim_from_request(existing))
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())

    claimed = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Ada",
            "--role",
            "builder",
            "--base",
            BASE,
            "--branch",
            "codex/issue-72",
            "--claim-id",
            "live-claim",
            "--json",
        ]
    )

    assert claimed == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["scope"] == ["src"]
    assert client.issue_reference_lookups == []
    assert client.requests == 0


@pytest.mark.parametrize(
    ("scope_arguments", "refusal"),
    [
        pytest.param([], cmd_claim._LANE_CLAIM_SCOPE_REQUIRED, id="no-scope"),
        *(
            pytest.param(
                ["--scope", scope_path], protocol.SCOPE_ENTRIES_MUST_BE_CANONICAL, id=control_id
            )
            for scope_path, control_id in (
                ("docs/a\N{RIGHT-TO-LEFT OVERRIDE}b.md", "RLO"),
                ("docs/a\N{LEFT-TO-RIGHT ISOLATE}b.md", "LRI"),
                ("docs/a\N{ZERO WIDTH SPACE}b.md", "ZWSP"),
                ("docs/\x9b2J.md", "C1-CSI"),
                ("docs/a\tb.md", "TAB"),
            )
        ),
    ],
)
def test_cli_lane_claim_refuses_a_missing_or_display_control_scope_by_name(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scope_arguments: list[str],
    refusal: str,
) -> None:
    """Lane mode has no item to derive a scope from, so
    omitting `--scope` still refuses, by name, and forge-free like every
    other lane claim. A `--scope` path holding a
    character `next` would escape, or a TAB, which `next` keeps but a path
    refuses (CLAIM-20), refuses with the scope grammar's own sentence before
    any write."""
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Ada"})
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    git_values = {("branch", "--show-current"): "docs/lane-cleanup"}
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    forbid_forge_resolution(monkeypatch)

    status = issue_claim.main(
        ["claim", "--base", BASE, "--branch", "docs/lane-cleanup", *scope_arguments]
    )

    assert status == 2
    assert capsys.readouterr().err == f"ERROR: {refusal}\n"


def test_cli_claim_replay_reports_the_matching_live_claim_after_an_interrupted_response(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    existing = request("live-claim", "Ada", issue=72, branch="codex/issue-72", scope=("src",))
    client = FakeForge()
    _patch_status_cli(monkeypatch, client)
    _patch_store_write(monkeypatch, store_claim_from_request(existing))
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    arguments = [
        "--repo",
        REPOSITORY,
        "claim",
        "72",
        "--agent",
        "Ada",
        "--role",
        "builder",
        "--base",
        BASE,
        "--branch",
        "codex/issue-72",
        "--scope",
        "src",
        "--claim-id",
        "live-claim",
    ]

    assert issue_claim.main(arguments) == 0
    assert capsys.readouterr().out == (
        "CLAIMED issue #72: live-claim\n"
        "1 of 4 versioned files (25%); overlaps no other open claims\n"
    )

    assert issue_claim.main([*arguments, "--json"]) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["claim_id"] == "live-claim"
    assert replay["issue"] == 72
    assert replay["agent"] == "Ada"
    assert replay["role"] == "builder"
    assert replay["branch"] == "codex/issue-72"
    assert replay["scope"] == ["src"]
    assert store.fetch_state(worktree=Path("."), remote="origin").claims


@pytest.mark.parametrize(
    ("agent", "role", "branch", "scope"),
    [
        ("Grok 4.6", "builder", "codex/issue-72", ("src",)),
        ("Ada", "reviewer", "codex/issue-72", ("src",)),
        ("Ada", "builder", "codex/issue-72-retry", ("src",)),
        ("Ada", "builder", "codex/issue-72", ("src", "tests")),
    ],
    ids=["agent", "role", "branch", "scope"],
)
def test_cli_claim_replay_refuses_a_live_claim_with_different_retry_fields(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    agent: str,
    role: str,
    branch: str,
    scope: tuple[str, ...],
) -> None:
    """CLAIM-11 under `storage = "github"`:
    a claim on a claimed item refuses naming both the item and the
    holder's claim `#<n>`, byte-identical to the sentence before the
    state-ref renderer existed."""
    existing = request("live-claim", "Ada", issue=72, branch="codex/issue-72", scope=("src",))
    client = FakeForge()
    _patch_status_cli(monkeypatch, client)
    _patch_store_write(monkeypatch, store_claim_from_request(existing))
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "72",
                "--agent",
                agent,
                "--role",
                role,
                "--base",
                BASE,
                "--branch",
                branch,
                *(part for path in scope for part in ("--scope", path)),
            ]
        )
        == 2
    )

    assert capsys.readouterr().err == (
        "ERROR: issue #72 is claimed by Ada (builder) on issue #72 branch codex/issue-72\n"
    )
    assert store.fetch_state(worktree=Path("."), remote="origin").claims


def test_cli_claim_replay_skips_out_of_order_for_the_matching_lower_priority_item(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    existing = request("live-claim", "Ada", issue=10, branch="codex/issue-10", scope=("src",))
    client = FakeForge()
    client.board_issues = (
        board_issue(10, "Lower work", complete_contract("Claim #10.")),
        board_issue(11, "Top work", complete_contract("Claim #11.")),
        board_issue(12, "Depends on top", complete_contract("Claim #12."), blocked_by_count=1),
    )
    client.board_dependencies = {12: (block_dependency(11),)}
    _patch_status_cli(monkeypatch, client)
    _patch_store_write(monkeypatch, store_claim_from_request(existing))
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "10",
                "--agent",
                "Ada",
                "--role",
                "builder",
                "--base",
                BASE,
                "--branch",
                "codex/issue-10",
                "--scope",
                "src",
                "--claim-id",
                "live-claim",
            ]
        )
        == 0
    )

    assert "out-of-order" not in capsys.readouterr().out
    assert store.fetch_state(worktree=Path("."), remote="origin").claims


def test_cli_claim_replay_does_not_bypass_out_of_order_for_another_agent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    existing = request("live-claim", "Ada", issue=10, branch="codex/issue-10", scope=("src",))
    client = FakeForge()
    client.board_issues = (
        board_issue(10, "Lower work", complete_contract("Claim #10.")),
        board_issue(11, "Top work", complete_contract("Claim #11.", scope=["src/top.py"])),
        board_issue(12, "Depends on top", complete_contract("Claim #12."), blocked_by_count=1),
    )
    client.board_dependencies = {12: (block_dependency(11),)}
    _patch_status_cli(monkeypatch, client)
    _patch_store_write(monkeypatch, store_claim_from_request(existing))
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "10",
                "--agent",
                "Grok 4.6",
                "--role",
                "builder",
                "--base",
                BASE,
                "--branch",
                "codex/issue-10",
                "--scope",
                "src",
            ]
        )
        == 2
    )

    assert "ERROR: higher-priority actionable item #11" in capsys.readouterr().err
    assert store.fetch_state(worktree=Path("."), remote="origin").claims


def test_cli_claim_replay_does_not_resurrect_a_released_claim(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeForge()
    _patch_status_cli(monkeypatch, client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    _patch_store_write(monkeypatch, consumed_ids=frozenset({protocol.ClaimId("released-claim")}))

    assert (
        issue_claim.main(
            [
                "--repo",
                REPOSITORY,
                "claim",
                "72",
                "--agent",
                "Ada",
                "--role",
                "builder",
                "--base",
                BASE,
                "--branch",
                "codex/issue-72",
                "--scope",
                "src",
                "--claim-id",
                "released-claim",
            ]
        )
        == 2
    )

    assert "already on this ledger, active or released" in capsys.readouterr().err


@pytest.fixture
def comma_scope_world(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "GitHubForge", lambda repository: FakeForge())
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())


@pytest.mark.usefixtures("comma_scope_world")
def test_cli_claim_scope_keeps_a_comma_inside_one_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A repository-relative path may itself contain a comma
    (`docs/report,v2.md`); the removed comma-splitting used to turn that
    silently into two wrong paths. One --scope occurrence is now exactly one
    path, comma and all -- proved here end to end through the real store, and
    by the absence of an overlap with the substring before the comma, which
    the old splitting would have claimed as its own path."""
    monkeypatch.setattr(checkout, "versioned_paths", lambda **_kwargs: ("docs/report,v2.md",))

    claimed = issue_claim.main(_claim_argv("--scope", "docs/report,v2.md", claim_id="comma-path"))

    assert claimed == 0
    assert _live_store_claim().scope == ("docs/report,v2.md",)

    second = issue_claim.main(_claim_argv("--scope", "docs/report", issue=73, claim_id="half-path"))
    captured = capsys.readouterr()

    assert second == 0
    assert "CLAIMED issue #73: half-path" in captured.out
    assert "overlaps no other open claims" in captured.out
    assert len(store.fetch_state(worktree=Path("."), remote="origin").claims) == 2


@pytest.mark.usefixtures("comma_scope_world")
def test_cli_claim_scope_comma_differs_from_repeated_scope_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A comma inside one --scope value is no longer equivalent to repeating
    the flag: the joined form is a single path whose name contains a comma,
    the repeated form two distinct paths."""
    monkeypatch.setattr(
        checkout, "versioned_paths", lambda **_kwargs: ("docs/PRODUCT.md,src/widget.py",)
    )

    joined = issue_claim.main(
        _claim_argv("--scope", "docs/PRODUCT.md,src/widget.py", claim_id="joined")
    )
    repeated = issue_claim.main(
        _claim_argv(
            "--scope", "docs/PRODUCT.md", "--scope", "src/widget.py", issue=73, claim_id="repeated"
        )
    )

    assert (joined, repeated) == (0, 0)
    claims = store.fetch_state(worktree=Path("."), remote="origin").claims
    assert {claim.scope for claim in claims.values()} == {
        ("docs/PRODUCT.md,src/widget.py",),
        ("docs/PRODUCT.md", "src/widget.py"),
    }


@pytest.mark.usefixtures("comma_scope_world")
@pytest.mark.parametrize(
    ("scope", "status", "stderr", "claimed_scopes"),
    [
        # `a.py,b.py` from the removed comma-splitting habit used to store one path
        # that guards nothing, so the lane's real files stayed unclaimed.
        pytest.param(
            "a.py,b.py",
            2,
            "ERROR: 'a.py,b.py' matches no versioned file; one --scope path per flag, so its "
            "comma is read literally -- repeat --scope for a second path\n",
            [],
            id="a-comma-matching-nothing-is-refused-before-any-write",
        ),
        # A lane routinely claims files it is about to create.
        pytest.param(
            "src/not-created-yet.py",
            0,
            "",
            [("src/not-created-yet.py",)],
            id="a-comma-free-path-git-never-heard-of-still-claims",
        ),
    ],
)
def test_cli_claim_refuses_only_a_comma_scope_that_matches_nothing_in_the_checkout(
    scope: str,
    status: int,
    stderr: str,
    claimed_scopes: list[tuple[str, ...]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed = issue_claim.main(_claim_argv("--scope", scope))

    claims = store.fetch_state(worktree=Path("."), remote="origin").claims
    assert (observed, capsys.readouterr().err, [claim.scope for claim in claims.values()]) == (
        status,
        stderr,
        claimed_scopes,
    )


def _rescope_forge(whole: str | None = None) -> FakeForge:
    """A forge serving issue #72 with a valid `aco` block, naming
    `whole` when given -- the body a rescope keeps in step with its claim."""
    client = FakeForge()
    _serve_rescoped_item(client, whole=whole)
    return client


def _serve_rescoped_item(client: FakeForge, *, whole: str | None = None) -> None:
    block_entries = {} if whole is None else {"whole": whole}
    client.issue_references[72] = forge.ItemReference(
        forge.ItemState.OPEN, "Rescoped item", complete_contract("Build it.", **block_entries)
    )


def _written_scope_and_whole(written_body: str) -> tuple[tuple[str, ...] | None, str | None]:
    parsed = body.parse_body(written_body)
    return parsed.scope, parsed.whole


def _arrange_github_rescope(
    monkeypatch: pytest.MonkeyPatch,
    client: FakeForge,
    *,
    held_scope: tuple[str, ...] = ("src/widget.py",),
) -> None:
    """Issue #72 claimed by Codex Sol on `held_scope` in the faked
    checkout at `/repo`, while the run stands in this suite's own cwd -- so
    a relative entry lands in `/repo` only when it is read against the
    checkout's toplevel, never against the cwd itself."""
    claimed = request(issue=72, branch="codex/issue-72", scope=held_scope)
    _patch_store_write(monkeypatch, store_claim_from_request(claimed))
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    git_values = git_checkout()
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})


@dataclass(frozen=True)
class _BodyRescope:
    """One rescope that must move the claim and the item body together: the
    flags after `rescope 72`, the scope and `whole` both must then hold, and
    the `whole` the body named before."""

    id: str
    argv_tail: tuple[str, ...]
    scope: tuple[str, ...]
    whole: str | None = None
    body_whole: str | None = None


_FOUR_FILE_REASON = "the four files share one lock"
_BODY_RESCOPES = (
    _BodyRescope("absolute-add", ("--add", "/repo/src/new.py"), ("src/new.py", "src/widget.py")),
    _BodyRescope("relative-add", ("--add", "src/new.py"), ("src/new.py", "src/widget.py")),
    _BodyRescope(
        "relative-drop-beside-an-absolute-add",
        ("--add", "/repo/src/new.py", "--drop", "src/widget.py"),
        ("src/new.py",),
    ),
    _BodyRescope(
        "whole-flag-written-into-the-body",
        ("--add", "a.py", "--add", "b.py", "--add", "c.py", "--whole", _FOUR_FILE_REASON),
        ("a.py", "b.py", "c.py", "src/widget.py"),
        whole=_FOUR_FILE_REASON,
    ),
    _BodyRescope(
        "body-whole-admits-a-wide-scope-as-for-start",
        ("--add", "a.py", "--add", "b.py", "--add", "c.py"),
        ("a.py", "b.py", "c.py", "src/widget.py"),
        whole=_FOUR_FILE_REASON,
        body_whole=_FOUR_FILE_REASON,
    ),
)


@pytest.mark.parametrize("case", _BODY_RESCOPES, ids=[case.id for case in _BODY_RESCOPES])
def test_cli_rescope_moves_the_claim_and_the_item_body_scope_together(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], case: _BodyRescope
) -> None:
    """RESC-22..25 under the github fake: one call, both owners of the scope."""
    client = _rescope_forge(whole=case.body_whole)
    _arrange_github_rescope(monkeypatch, client)
    argv = ["--repo", REPOSITORY, "rescope", "72", *case.argv_tail]

    status = issue_claim.main(argv)

    assert (status, capsys.readouterr().err) == (0, "")
    standing = _live_store_claim()
    assert (standing.scope, standing.whole_reason) == (case.scope, case.whole)
    assert _written_scope_and_whole(client.item_bodies[72]) == (case.scope, case.whole)


def _reject_the_claim_push(monkeypatch: pytest.MonkeyPatch, client: FakeForge) -> None:
    def rejected(**_kwargs: object) -> protocol.ClaimState:
        raise ClaimError("push rejected (simulated)")

    monkeypatch.setattr(store, "commit_transition", rejected)


def _reject_the_body_write(monkeypatch: pytest.MonkeyPatch, client: FakeForge) -> None:
    client.fail_update_item_body = True


@pytest.mark.parametrize(
    ("fail_step", "body_scope", "refusal"),
    [
        pytest.param(
            _reject_the_body_write,
            None,
            "ERROR: update item body failed (simulated)\n",
            id="body-write-fails-first-and-the-claim-stays",
        ),
        pytest.param(
            _reject_the_claim_push,
            ("src/new.py", "src/widget.py"),
            "ERROR: #72 body scope now reads ['src/new.py', 'src/widget.py'], but the claim "
            "was not rescoped: push rejected (simulated); run the same rescope again\n",
            id="claim-write-fails-second-and-names-the-written-body",
        ),
    ],
)
def test_cli_rescope_names_what_went_through_when_a_write_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fail_step: Callable[[pytest.MonkeyPatch, FakeForge], None],
    body_scope: tuple[str, ...] | None,
    refusal: str,
) -> None:
    """RESC-23: the body is written first, so a failed body write leaves the
    claim as it stood, and a failed claim write after it says the body
    already moved and how to bring the claim in step."""
    client = _rescope_forge()
    _arrange_github_rescope(monkeypatch, client)
    fail_step(monkeypatch, client)
    argv = ["--repo", REPOSITORY, "rescope", "72", "--add", "src/new.py"]

    status = issue_claim.main(argv)

    assert (status, capsys.readouterr().err) == (2, refusal)
    assert _live_store_claim().scope == ("src/widget.py",)
    written = client.item_bodies.get(72)
    assert (None if written is None else _written_scope_and_whole(written)[0]) == body_scope


def test_cli_rescope_refuses_an_item_body_without_a_block_before_any_write(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """RESC-24: a body that cannot carry the scope refuses with both owners
    as they stood."""
    client = FakeForge()
    _arrange_github_rescope(monkeypatch, client)
    argv = ["--repo", REPOSITORY, "rescope", "72", "--add", "src/new.py", "--json"]

    status = issue_claim.main(argv)

    refusal = json.loads(capsys.readouterr().out)
    assert status == 2
    assert (refusal["reason"], refusal["message"]) == (
        "precondition_failed",
        "#72 body malformed: aco: no aco block; rescope needs a valid aco block",
    )
    assert (_live_store_claim().scope, client.item_bodies) == (("src/widget.py",), {})


def test_cli_rescope_adds_a_path_without_matching_head_or_a_clean_tree(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = _rescope_forge()
    claimed_request = request(issue=72, branch="codex/issue-72", scope=("src/widget.py",))
    acquired = store_claim_from_request(claimed_request)
    _patch_store_write(monkeypatch, acquired)
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    git_values = git_checkout(head="b" * 40, dirty=" M file")
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})

    status = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "rescope",
            "72",
            "--add",
            "/repo/src/new.py",
        ]
    )

    assert status == 0
    assert capsys.readouterr().out == f"RESCOPED issue #72: {acquired.claim_id}\n"
    standing = _live_store_claim()
    assert standing.claim_id == acquired.claim_id
    assert standing.base == BASE
    assert standing.scope == ("src/new.py", "src/widget.py")


@dataclass(frozen=True)
class _CommaRescope:
    """`--add` and `--drop` share `--scope`'s rule (one occurrence is one path,
    comma and all): the scope the claim holds, the files the checkout versions,
    the flags after `rescope 72`, and what the run then says and the claim holds."""

    held_scope: tuple[str, ...]
    versioned_paths: tuple[str, ...]
    argv_tail: tuple[str, ...]
    status: int
    stdout: str
    stderr: str
    scope: tuple[str, ...]


_RESCOPED = "RESCOPED issue #72: claim-a\n"
_COMMA_RESCOPES = {
    "add-keeps-a-comma-inside-one-path": _CommaRescope(
        ("src/widget.py",),
        ("reports/a,b.md",),
        ("--add", "/repo/reports/a,b.md"),
        0,
        _RESCOPED,
        "",
        ("reports/a,b.md", "src/widget.py"),
    ),
    # The old comma-splitting would have tried, and failed, to drop `reports/a` and `b.md`.
    "drop-matches-a-comma-path-as-one-whole-path": _CommaRescope(
        ("reports/a", "reports/a,b.md"),
        ("reports/a,b.md",),
        ("--drop", "/repo/reports/a,b.md"),
        0,
        _RESCOPED,
        "",
        ("reports/a",),
    ),
    # `--add` is no way around the refusal `claim` applies.
    "add-refuses-a-comma-scope-matching-nothing-in-the-checkout": _CommaRescope(
        ("src/widget.py",),
        (),
        ("--add", "/repo/a.py,b.py"),
        2,
        "",
        "ERROR: 'a.py,b.py' matches no versioned file; one --add path per flag, so its comma "
        "is read literally -- repeat --add for a second path\n",
        ("src/widget.py",),
    ),
    # The claim's own reason is truer here than the checkout's.
    "drop-of-a-value-not-in-scope-names-the-claim": _CommaRescope(
        ("src/widget.py",),
        (),
        ("--drop", "/repo/a.py,b.py"),
        2,
        "",
        "ERROR: cannot drop 'a.py,b.py'; it is not in this claim's scope\n",
        ("src/widget.py",),
    ),
    # A value the claim already holds is a fact about the claim, not a typo about the checkout.
    "drop-removes-a-held-comma-entry-no-file-matches": _CommaRescope(
        ("a.py,b.py",),
        ("a.py", "b.py"),
        ("--drop", "/repo/a.py,b.py", "--add", "/repo/a.py", "--add", "/repo/b.py"),
        0,
        _RESCOPED,
        "",
        ("a.py", "b.py"),
    ),
}


@pytest.mark.parametrize("case", _COMMA_RESCOPES.values(), ids=_COMMA_RESCOPES.keys())
def test_cli_rescope_reads_a_comma_inside_one_path_literally(
    case: _CommaRescope, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _arrange_github_rescope(monkeypatch, _rescope_forge(), held_scope=case.held_scope)
    monkeypatch.setattr(checkout, "versioned_paths", lambda **_kwargs: case.versioned_paths)

    status = issue_claim.main(["--repo", REPOSITORY, "rescope", "72", *case.argv_tail])
    captured = capsys.readouterr()

    assert (status, captured.out, captured.err, _live_store_claim().scope) == (
        case.status,
        case.stdout,
        case.stderr,
        case.scope,
    )


def test_cli_rescope_json_prints_updated_scope_and_same_claim_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = _rescope_forge()
    standing = request(
        "cli-claim", "Ada", issue=72, branch="codex/issue-72", scope=("src/widget.py",)
    )
    _patch_store_write(monkeypatch, store_claim_from_request(standing))
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    git_values = git_checkout()
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Ada"})

    status = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "rescope",
            "72",
            "--add",
            "/repo/docs/PRODUCT.md",
            "--add",
            "/repo/src/new.py",
            "--drop",
            "/repo/src/widget.py",
            "--json",
        ]
    )

    assert status == 0
    assert (
        capsys.readouterr().out
        == json.dumps(
            {
                "ok": True,
                "reason": "rescoped",
                "issue": 72,
                "lane": None,
                "claim_id": "cli-claim",
                "agent": "Ada",
                "role": "builder",
                "base": BASE,
                "branch": "codex/issue-72",
                "scope": ["docs/PRODUCT.md", "src/new.py"],
            }
        )
        + "\n"
    )


def test_cli_rescope_refuses_a_different_agent_than_the_claimant(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = _rescope_forge()
    claimed_request = request(agent="Ada", issue=72, branch="codex/issue-72", scope=("src",))
    _patch_store_write(monkeypatch, store_claim_from_request(claimed_request))
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    git_values = git_checkout()
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Grok 4.6"})

    status = issue_claim.main(["--repo", REPOSITORY, "rescope", "72", "--add", "/repo/src/new.py"])

    assert status == 2
    assert capsys.readouterr().err == (
        "ERROR: only the original claimant may rescope "
        "(holder='Ada (builder)', this session='Grok 4.6 (builder)')\n"
    )


def test_cli_rescope_json_refuses_no_active_claim_with_precondition_failed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """RESC-14: no live claim on the target identity/branch at
    all reports `precondition_failed`, not the generic `unavailable`
    bucket every checkout- or store-level refusal falls to."""
    client = FakeForge()
    _patch_store_write(monkeypatch)
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    git_values = git_checkout()
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Ada"})

    status = issue_claim.main(
        ["--repo", REPOSITORY, "rescope", "72", "--add", "/repo/src/new.py", "--json"]
    )

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == "ERROR: issue #72 has no active build claim\n"
    _assert_json_refusal_object(captured.err, captured.out, reason="precondition_failed")


SCOPE_READ_FAILURE = "fatal: object database unreadable"


def _fail_scope_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every read of one scope entry's tree entry fails; any other git read
    keeps answering from the faked checkout, so a gate that swallows the
    failure shows as a wrong outcome, not as a missing fake entry."""
    answers = git_checkout()

    def read(arguments: list[str], **_kwargs: object) -> str:
        if arguments[0] == "ls-tree":
            raise ClaimError(SCOPE_READ_FAILURE)
        return answers[tuple(arguments)]

    monkeypatch.setattr(checkout, "git_output", read)


def test_cli_rescope_json_reports_a_git_failure_reading_the_scope_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """RESC-17: a git failure while the width gate reads the scope is not a
    scope that is too wide, so it is `unavailable`, never
    `precondition_failed`."""
    scope_directories = checkout.scope_directories
    _arrange_github_rescope(monkeypatch, _rescope_forge())
    monkeypatch.setattr(checkout, "scope_directories", scope_directories)
    _fail_scope_reads(monkeypatch)

    status = issue_claim.main(
        ["--repo", REPOSITORY, "rescope", "72", "--add", "/repo/src/new.py", "--json"]
    )

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == f"ERROR: {SCOPE_READ_FAILURE}\n"
    _assert_json_refusal_object(captured.err, captured.out, reason="unavailable")


def test_cli_rescope_without_add_or_drop_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeForge()
    _patch_store_write(
        monkeypatch,
        store_claim_from_request(
            request(issue=72, branch="codex/issue-72", scope=("src/widget.py",))
        ),
    )
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    git_values = git_checkout()
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})

    status = issue_claim.main(["--repo", REPOSITORY, "rescope", "72"])
    captured = capsys.readouterr()

    assert status == 2
    assert captured.out == ""
    assert "ERROR:" in captured.err
    assert "does not change the claim scope" in captured.err or "--add" in captured.err


def test_cli_rescope_refuses_primary_checkout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeForge()
    _patch_store_write(
        monkeypatch,
        store_claim_from_request(
            request(issue=72, branch="codex/issue-72", scope=("src/widget.py",))
        ),
    )
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    git_values = git_checkout(git_directory="/repo/.git", common_directory="/repo/.git")
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})

    status = issue_claim.main(["--repo", REPOSITORY, "rescope", "72", "--add", "/repo/src/new.py"])
    captured = capsys.readouterr()

    assert status == 2
    assert captured.out == ""
    assert "linked isolated worktree" in captured.err


@dataclass(frozen=True)
class _ScopeWidthRefusal:
    """One `claim`/`rescope` case that must refuse for a wide scope, sharing
    the monkeypatch quadruple and argv skeleton with every other row and
    differing only in what trips the width check and what the refusal says."""

    id: str
    command: str
    argv_tail: tuple[str, ...]
    directories: frozenset[str] = frozenset()
    versioned: tuple[str, ...] | None = None
    board_issues: tuple[Issue, ...] = ()
    standing_scope: tuple[str, ...] | None = None
    exact_err: str | None = None


_SCOPE_WIDTH_REFUSALS = (
    _ScopeWidthRefusal(
        id="directory-scope",
        command="claim",
        argv_tail=("--scope", "docs", "--claim-id", "tree"),
        directories=frozenset({"docs"}),
    ),
    _ScopeWidthRefusal(
        id="named-directory",
        command="claim",
        argv_tail=("--scope", "docs", "--claim-id", "named-directory"),
        directories=frozenset({"docs"}),
        exact_err=(
            "ERROR: scope is wide: 1 directory in scope (docs); "
            "pass --whole REASON or set whole in the body\n"
        ),
    ),
    _ScopeWidthRefusal(
        id="directory-plus-child-scope",
        command="claim",
        argv_tail=("--scope", "docs", "--scope", "docs/a.md", "--claim-id", "tree"),
        directories=frozenset({"docs"}),
    ),
    _ScopeWidthRefusal(
        id="rescope-add-directory",
        command="rescope",
        argv_tail=("--add", "/repo/docs"),
        directories=frozenset({"docs"}),
        standing_scope=("src/widget.py",),
    ),
    _ScopeWidthRefusal(
        id="share-above-quarter",
        command="claim",
        argv_tail=(
            "--scope",
            "LICENSE",
            "--scope",
            "README.md",
            "--scope",
            "src",
            "--claim-id",
            "wide",
        ),
        versioned=TWELVE_VERSIONED_FILES,
    ),
    _ScopeWidthRefusal(
        id="named-share",
        command="claim",
        argv_tail=(
            "--scope",
            "LICENSE",
            "--scope",
            "README.md",
            "--scope",
            "src",
            "--claim-id",
            "named-share",
        ),
        versioned=TWELVE_VERSIONED_FILES,
        exact_err=(
            "ERROR: scope is wide: 4 paths of 12 versioned files (33 %) exceeds a quarter; "
            "pass --whole REASON or set whole in the body\n"
        ),
    ),
    _ScopeWidthRefusal(
        id="cut-directory-scope",
        command="claim",
        argv_tail=("--scope", "docs", "--claim-id", "cut"),
        directories=frozenset({"docs"}),
        board_issues=(
            board_issue(
                72,
                "Cut work",
                complete_contract("Claim #72.") + "\n\n## Schnitt\n\n**Scheibe 1: Title**\n",
            ),
        ),
    ),
    _ScopeWidthRefusal(
        id="schnitt-heading-without-scheibe",
        command="claim",
        argv_tail=("--scope", "docs", "--claim-id", "heading"),
        directories=frozenset({"docs"}),
        board_issues=(
            board_issue(
                72,
                "Uncut",
                complete_contract("Claim #72.") + "\n\n## Schnitt\n\nNo slices yet.\n",
            ),
        ),
    ),
    _ScopeWidthRefusal(
        id="lane-directory",
        command="claim-lane",
        argv_tail=("--scope", "docs", "--claim-id", "lane-docs"),
        directories=frozenset({"docs"}),
    ),
    _ScopeWidthRefusal(
        id="cut-directory-high-share",
        command="claim",
        argv_tail=("--scope", "docs", "--claim-id", "wide-cut"),
        directories=frozenset({"docs"}),
        versioned=("LICENSE", "README.md", "docs/a.md", "docs/b.md"),
        board_issues=(
            board_issue(
                72,
                "Cut work",
                complete_contract("Claim #72.") + "\n\n## Schnitt\n\n**Scheibe 1: Title**\n",
            ),
        ),
    ),
    _ScopeWidthRefusal(
        id="rescope-add-combined-share",
        command="rescope",
        argv_tail=("--add", "/repo/LICENSE", "--add", "/repo/README.md"),
        versioned=TWELVE_VERSIONED_FILES,
        standing_scope=("src",),
    ),
    _ScopeWidthRefusal(
        id="claim-refuses-four-named-paths",
        command="claim",
        argv_tail=(
            "--scope",
            "new_a.py",
            "--scope",
            "new_b.py",
            "--scope",
            "new_c.py",
            "--scope",
            "new_d.py",
            "--claim-id",
            "four",
        ),
    ),
    _ScopeWidthRefusal(
        id="named-path-count",
        command="claim",
        argv_tail=(
            "--scope",
            "new_a.py",
            "--scope",
            "new_b.py",
            "--scope",
            "new_c.py",
            "--scope",
            "new_d.py",
            "--claim-id",
            "named-path-count",
        ),
        exact_err=(
            "ERROR: scope is wide: 4 paths exceeds three; "
            "pass --whole REASON or set whole in the body\n"
        ),
    ),
    _ScopeWidthRefusal(
        id="rescope-widening-to-four-paths",
        command="rescope",
        argv_tail=("--add", "/repo/new_b.py", "--add", "/repo/new_c.py", "--add", "/repo/new_d.py"),
        standing_scope=("new_a.py",),
    ),
)


@dataclass(frozen=True)
class _ScopeWidthAcceptance:
    """One `claim`/`rescope` case that must accept a scope within the width
    limits, sharing the same arrangement as `_ScopeWidthRefusal` and
    differing only in the trigger and in what the acceptance reports."""

    id: str
    command: str
    argv_tail: tuple[str, ...]
    check: Callable[[str, str], None]
    directories: frozenset[str] = frozenset()
    versioned: tuple[str, ...] | None = None
    standing_scope: tuple[str, ...] | None = None


def _assert_below_share_floor_human_line(out: str, err: str) -> None:
    assert out.endswith("4 of 11 versioned files (36%); overlaps no other open claims\n")


def _assert_share_at_quarter_human_line(out: str, err: str) -> None:
    assert out.endswith("3 of 12 versioned files (25%); overlaps no other open claims\n")


def _assert_share_above_a_quarter_with_whole_payload(out: str, err: str) -> None:
    payload = json.loads(out)
    assert payload["versioned_files"] == 4
    assert payload["versioned_files_total"] == 12
    assert payload["share"] == pytest.approx(1 / 3)
    assert payload["touches"] == []


def _assert_rescope_persisted_whole_reason(out: str, err: str) -> None:
    standing = _live_store_claim()
    assert standing.scope == ("docs", "src/widget.py")
    assert standing.whole_reason == "widen to the docs tree"


def _assert_claim_accepted_three_named_paths(out: str, err: str) -> None:
    posted = _live_store_claim()
    assert posted.scope == ("new_a.py", "new_b.py", "new_c.py")
    assert posted.whole_reason is None


def _assert_claim_persisted_whole_reason(out: str, err: str) -> None:
    posted = _live_store_claim()
    assert posted.whole_reason == "the four adapters share one lock"


def _assert_claim_allowed_directory_with_whole(out: str, err: str) -> None:
    posted = _live_store_claim()
    assert posted.scope == ("docs",)
    assert posted.whole_reason == "rewrite the docs tree"


_SCOPE_WIDTH_ACCEPTANCES = (
    _ScopeWidthAcceptance(
        id="below-share-floor",
        command="claim",
        argv_tail=(
            "--scope",
            "LICENSE",
            "--scope",
            "README.md",
            "--scope",
            "src",
            "--claim-id",
            "below-floor",
        ),
        versioned=TWELVE_VERSIONED_FILES[:-1],
        check=_assert_below_share_floor_human_line,
    ),
    _ScopeWidthAcceptance(
        id="share-above-quarter-with-whole",
        command="claim",
        argv_tail=(
            "--scope",
            "LICENSE",
            "--scope",
            "README.md",
            "--scope",
            "src",
            "--whole",
            "cover four files",
            "--claim-id",
            "wide",
            "--json",
        ),
        versioned=TWELVE_VERSIONED_FILES,
        check=_assert_share_above_a_quarter_with_whole_payload,
    ),
    _ScopeWidthAcceptance(
        id="share-at-quarter",
        command="claim",
        argv_tail=(
            "--scope",
            "LICENSE",
            "--scope",
            "README.md",
            "--scope",
            "pyproject.toml",
            "--claim-id",
            "quarter",
        ),
        versioned=TWELVE_VERSIONED_FILES,
        check=_assert_share_at_quarter_human_line,
    ),
    _ScopeWidthAcceptance(
        id="rescope-persists-whole-reason",
        command="rescope",
        argv_tail=("--add", "/repo/docs", "--whole", "widen to the docs tree"),
        directories=frozenset({"docs"}),
        standing_scope=("src/widget.py",),
        check=_assert_rescope_persisted_whole_reason,
    ),
    _ScopeWidthAcceptance(
        id="claim-accepts-three-named-paths",
        command="claim",
        argv_tail=(
            "--scope",
            "new_a.py",
            "--scope",
            "new_b.py",
            "--scope",
            "new_c.py",
            "--claim-id",
            "three",
        ),
        check=_assert_claim_accepted_three_named_paths,
    ),
    _ScopeWidthAcceptance(
        id="claim-persists-whole-reason",
        command="claim",
        argv_tail=(
            "--scope",
            "new_a.py",
            "--scope",
            "new_b.py",
            "--scope",
            "new_c.py",
            "--scope",
            "new_d.py",
            "--whole",
            "the four adapters share one lock",
            "--claim-id",
            "wide",
        ),
        check=_assert_claim_persisted_whole_reason,
    ),
    _ScopeWidthAcceptance(
        id="claim-allows-directory-with-whole",
        command="claim",
        argv_tail=("--scope", "docs", "--whole", "rewrite the docs tree", "--claim-id", "tree"),
        directories=frozenset({"docs"}),
        check=_assert_claim_allowed_directory_with_whole,
    ),
)


def _run_scope_width_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    command: str,
    argv_tail: tuple[str, ...],
    directories: frozenset[str] = frozenset(),
    versioned: tuple[str, ...] | None = None,
    standing_scope: tuple[str, ...] | None = None,
    board_issues: tuple[Issue, ...] = (),
) -> tuple[int, str, str]:
    """Run one `claim`/`rescope` scope-width case end to end and return its
    exit status, stdout, and stderr, for the refusal and acceptance tables
    that share every arrangement and differ only in trigger and outcome."""
    client = _rescope_forge() if command == "rescope" else FakeForge(board_issues=board_issues)
    if command == "claim":
        raw_body = board_issues[0].body if board_issues else complete_contract("Claim #72.")
        client.issue_references[72] = forge.ItemReference(forge.ItemState.OPEN, "Work", raw_body)
    if command == "rescope":
        assert standing_scope is not None
        _patch_store_write(
            monkeypatch,
            store_claim_from_request(
                request(issue=72, branch="codex/issue-72", scope=standing_scope)
            ),
        )
        git_values = git_checkout()
        monkeypatch.setattr(
            checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
        )
        set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
        arrange_scope_width(
            monkeypatch,
            client,
            directories=directories,
            versioned=versioned,
            validate_checkout=False,
        )
        argv = ["--repo", REPOSITORY, "rescope", "72", *argv_tail]
    elif command == "claim-lane":
        set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Ada"})
        git_values = {("branch", "--show-current"): "docs/lane-cleanup"}
        monkeypatch.setattr(
            checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
        )
        arrange_scope_width(monkeypatch, client, directories=directories, versioned=versioned)
        argv = [
            "--repo",
            REPOSITORY,
            "claim",
            "--base",
            BASE,
            "--branch",
            "docs/lane-cleanup",
            *argv_tail,
        ]
    else:
        arrange_scope_width(monkeypatch, client, directories=directories, versioned=versioned)
        argv = [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Ada",
            "--base",
            BASE,
            "--branch",
            "codex/issue-72",
            *argv_tail,
        ]

    status = issue_claim.main(argv)
    captured = capsys.readouterr()
    return status, captured.out, captured.err


@pytest.mark.parametrize(
    "case", _SCOPE_WIDTH_REFUSALS, ids=[case.id for case in _SCOPE_WIDTH_REFUSALS]
)
def test_cli_claim_and_rescope_refuse_a_wide_scope_without_whole(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: _ScopeWidthRefusal,
) -> None:
    status, out, err = _run_scope_width_command(
        monkeypatch,
        capsys,
        command=case.command,
        argv_tail=case.argv_tail,
        directories=case.directories,
        versioned=case.versioned,
        standing_scope=case.standing_scope,
        board_issues=case.board_issues,
    )

    assert status == 2
    assert out == ""
    if case.exact_err is not None:
        assert err == case.exact_err
    else:
        assert "scope is wide" in err
        assert "--whole" in err
    if case.command == "rescope":
        assert _live_store_claim().scope == case.standing_scope


@pytest.mark.parametrize(
    "case", _SCOPE_WIDTH_ACCEPTANCES, ids=[case.id for case in _SCOPE_WIDTH_ACCEPTANCES]
)
def test_cli_claim_and_rescope_accept_a_scope_within_width_limits(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: _ScopeWidthAcceptance,
) -> None:
    status, out, err = _run_scope_width_command(
        monkeypatch,
        capsys,
        command=case.command,
        argv_tail=case.argv_tail,
        directories=case.directories,
        versioned=case.versioned,
        standing_scope=case.standing_scope,
    )

    assert status == 0
    case.check(out, err)


def test_cli_claim_touches_stay_empty_beside_a_disjoint_standing_claim(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    standing = request("claim-a", "Ada", issue=73, scope=("LICENSE",))
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    _patch_store_write(monkeypatch, store_claim_from_request(standing))

    status = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Ada",
            "--base",
            BASE,
            "--branch",
            "codex/issue-72",
            "--scope",
            "src",
            "--claim-id",
            "disjoint",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert status == 0
    assert payload["touches"] == []


def test_cli_claim_json_lists_an_overlapping_standing_claim_as_a_touch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    standing = request("claim-a", "Ada", issue=73, scope=("src",))
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    _patch_store_write(monkeypatch, store_claim_from_request(standing))

    status = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Ada",
            "--base",
            BASE,
            "--branch",
            "codex/issue-72",
            "--scope",
            "src/work.py",
            "--claim-id",
            "overlapping",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert status == 0
    assert payload["touches"] == [
        {"issue": 73, "lane": None, "claim_id": "claim-a", "agent": "Ada", "scope": ["src"]}
    ]


def test_cli_claim_json_touch_key_set_is_unchanged_by_the_human_overlap_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A consumer pins `touches`' exact field set: naming the
    colliding path on the human line must add no key here, and the full
    scope a touch already carries is how a consumer can compute that path
    itself today."""
    standing = request("claim-a", "Ada", issue=1400, scope=("tests/adapters/test_claim_cli.py",))
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(
        checkout,
        "scope_directories",
        lambda paths, **_kwargs: tuple(p for p in paths if p == "tests"),
    )
    _patch_store_write(monkeypatch, store_claim_from_request(standing))

    status = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "1401",
            "--agent",
            "Grok 4.6",
            "--base",
            BASE,
            "--branch",
            "codex/issue-1401",
            "--scope",
            "tests",
            "--claim-id",
            "challenger",
            "--whole",
            "the whole test tree",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert status == 0
    assert len(payload["touches"]) == 1
    assert set(payload["touches"][0]) == {"issue", "lane", "claim_id", "agent", "scope"}
    assert payload["touches"][0] == {
        "issue": 1400,
        "lane": None,
        "claim_id": "claim-a",
        "agent": "Ada",
        "scope": ["tests/adapters/test_claim_cli.py"],
    }


@pytest.mark.parametrize(
    ("opened_at", "claim_age", "claim_old"),
    [
        pytest.param(datetime(2026, 8, 20, 23, 30, tzinfo=UTC), "0h 30m", False, id="young"),
        pytest.param(
            datetime(2026, 8, 20, 22, 59, tzinfo=UTC), "1h 1m", True, id="sixty-one-minutes"
        ),
    ],
)
def test_board_shows_a_claims_age_and_marks_it_old_after_sixty_minutes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    opened_at: datetime,
    claim_age: str,
    claim_old: bool,
) -> None:
    claimed = request("mine", "Ada", issue=72, branch="codex/issue-72", scope=("src",))
    client = FakeForge()
    client.board_issues = (board_issue(72, "Work", complete_contract("Claim #72.")),)
    _patch_status_cli(monkeypatch, client)
    _fake_every_git_read_as_tmp_path(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: ())
    _patch_store_write(monkeypatch, store_claim_from_request(claimed), ages={"mine": opened_at})

    assert issue_claim.main(["--repo", REPOSITORY, "board", "--json"]) == 0
    item = next(row for row in json.loads(capsys.readouterr().out)["items"] if row["number"] == 72)
    assert item["claim_age"] == claim_age
    assert item["claim_old"] is claim_old


def test_cli_release_without_json_prints_the_released_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    standing = request("mine", "Ada", issue=72, role="reviewer", branch="lane-72", scope=("src",))
    client = FakeForge()
    _patch_release_session(monkeypatch, client, standing)

    released = issue_claim.main(["--repo", REPOSITORY, "release", "72", "--abandoned", "stopped"])

    assert released == 0
    assert capsys.readouterr().out == "RELEASED issue #72: mine\n"


@pytest.mark.parametrize(
    ("issue_argument", "branch", "identity_fields"),
    [
        (["72"], "codex/issue-72", {"issue": 72, "lane": None}),
        ([], "docs/lane-cleanup", {"issue": None, "lane": True}),
    ],
    ids=["issue", "lane"],
)
def test_cli_claim_json_prints_acquired_claim_object(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    issue_argument: list[str],
    branch: str,
    identity_fields: dict[str, object],
) -> None:
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())

    claimed = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            *issue_argument,
            "--agent",
            "Codex Sol",
            "--role",
            "builder",
            "--base",
            BASE,
            "--branch",
            branch,
            "--scope",
            "src",
            "--scope",
            "docs",
            "--claim-id",
            "cli-claim",
            "--json",
        ]
    )

    assert claimed == 0
    assert (
        capsys.readouterr().out
        == json.dumps(
            {
                "ok": True,
                "reason": "claimed",
                **identity_fields,
                "claim_id": "cli-claim",
                "agent": "Codex Sol",
                "role": "builder",
                "base": BASE,
                "branch": branch,
                "scope": ["docs", "src"],
                "resource": None,
                "resource_value": None,
                "versioned_files": 1,
                "versioned_files_total": 4,
                "share": 0.25,
                "touches": [],
                "checks": [],
            }
        )
        + "\n"
    )
    posted = _live_store_claim()
    assert posted.scope == ("docs", "src")


@pytest.mark.parametrize(
    (
        "issue_argument",
        "branch",
        "identity_fields",
        "standing_role",
        "flags",
        "agent",
        "role",
        "outcome",
    ),
    [
        (
            ["72"],
            "lane-72",
            {"issue": 72, "lane": None},
            "reviewer",
            ("--abandoned", "stopped", "--json"),
            "Ada",
            "reviewer",
            "abandoned: stopped",
        ),
        (
            ["72"],
            "lane-72",
            {"issue": 72, "lane": None},
            "reviewer",
            (
                "--claim-id",
                "mine",
                "--coordinator-override",
                "--role",
                "coordinator",
                "--abandoned",
                "verified abandoned",
                "--json",
            ),
            "Fleet Coordinator",
            "coordinator",
            "abandoned: verified abandoned",
        ),
        (
            [],
            "docs/lane-cleanup",
            {"issue": None, "lane": True},
            "reviewer",
            ("--abandoned", "stopped", "--json"),
            "Ada",
            "reviewer",
            "abandoned: stopped",
        ),
        (
            [],
            "docs/lane-cleanup",
            {"issue": None, "lane": True},
            "reviewer",
            (
                "--claim-id",
                "mine",
                "--coordinator-override",
                "--role",
                "coordinator",
                "--abandoned",
                "verified abandoned",
                "--json",
            ),
            "Fleet Coordinator",
            "coordinator",
            "abandoned: verified abandoned",
        ),
    ],
    ids=["issue-abandoned", "issue-override", "lane-abandoned", "lane-override"],
)
def test_cli_release_json_prints_effective_posted_identity(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    issue_argument: list[str],
    branch: str,
    identity_fields: dict[str, object],
    standing_role: str,
    flags: tuple[str, ...],
    agent: str,
    role: str,
    outcome: str,
) -> None:
    lane = not issue_argument
    standing = request(
        "mine", "Ada", issue=72, lane=lane, role=standing_role, branch=branch, scope=("src",)
    )
    client = FakeForge()
    # Lane mode always derives its branch from the checkout, even with an explicit
    # --claim-id (LaneIdentity carries no branch of its own), so git
    # is only forbidden for the issue-mode explicit-claim-id case.
    forbid_git = bool(issue_argument) and "--claim-id" in flags
    _patch_release_session(
        monkeypatch, client, standing, agent=agent, branch=branch, forbid_git=forbid_git
    )

    released = issue_claim.main(["--repo", REPOSITORY, "release", *issue_argument, *flags])

    assert released == 0
    assert (
        capsys.readouterr().out
        == json.dumps(
            {
                "ok": True,
                "reason": "abandoned",
                "outcome": outcome,
                **identity_fields,
                "branch": branch,
                "claim_id": "mine",
                "agent": agent,
                "role": role,
            }
        )
        + "\n"
    )
    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


def _assert_json_refusal_object(err: str, out: str, *, reason: str) -> None:
    """`ask`/`rule`/`brief`'s own `report.emit_json` refusal (
    `specs/output.spec.md`): the identical sentence stderr already printed,
    now under `message`, next to `reason` instead of a dropped `error`
    key. Compares the raw JSON text, not a parsed dict, so a reordering of
    OUT-01's `ok`, `reason`, `message` sequence would fail this assertion."""
    assert err.startswith("ERROR: ")
    message = err.removeprefix("ERROR: ").rstrip("\n")
    expected = {"ok": False, "reason": reason, "message": message}
    assert out == json.dumps(expected) + "\n"
    assert json.loads(out) == expected


@pytest.mark.parametrize(
    ("arguments", "assert_refusal"),
    [
        pytest.param(
            ["claim", "72", "--agent", "Ada", "--scope", "src", "--claim-id", "cli-claim"],
            lambda err, out: _assert_json_refusal_object(err, out, reason="unavailable"),
            id="claim-envelope-refusal",
        ),
        pytest.param(
            ["release", "72", "--agent", "Ada", "--claim-id", "mine", "--abandoned", "stopped"],
            lambda err, out: _assert_json_refusal_object(err, out, reason="precondition_failed"),
            id="release-precondition-failed",
        ),
    ],
)
def test_cli_claim_and_release_json_errors_choose_their_own_shape(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    assert_refusal: Callable[[str, str], None],
) -> None:
    """`claim`'s own dirty-tree checkout precondition reports
    through the shared emitter, `reason: unavailable`; `release`'s own
    generic refusal bucket reports `reason: precondition_failed`."""
    _patch_status_cli(monkeypatch, FakeForge())

    assert issue_claim.main(["--repo", REPOSITORY, *arguments, "--json"]) == 2
    captured = capsys.readouterr()
    assert_refusal(captured.err, captured.out)


def _prepare_identity_or_release_branch_refusal(
    monkeypatch: pytest.MonkeyPatch, agent: str | None, branch: str | None
) -> None:
    """Prepare identity and release refusals before forbidden git or forge reads.
    Supply an identity unless the case is about a missing one, and a checkout
    branch only where the refusal may read one -- `None` forbids git outright."""
    if agent:
        set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: agent})
    forbid_github_construction(monkeypatch)
    if branch is None:

        def unused(arguments: list[str], **_kwargs: object) -> str:
            pytest.fail("this refusal must fire before git is read")

        monkeypatch.setattr(checkout, "git_output", unused)
        return
    monkeypatch.setattr(checkout, "git_output", lambda _arguments, **_kwargs: branch)


@pytest.mark.parametrize(
    ("arguments", "agent", "branch", "sentence"),
    [
        pytest.param(_claim_without_agent_args(), None, None, None, id="claim-without-an-identity"),
        pytest.param(
            ["rescope", "72", "--add", "/repo/x.py"],
            None,
            None,
            None,
            id="rescope-without-an-identity",
        ),
        pytest.param(
            ["release", "--abandoned", "stopped"],
            "Ada",
            "",
            "lane release requires a non-empty current branch; "
            "check out the docs/ or fix/ lane branch, or pass an issue number",
            id="release-without-issue-or-branch",
        ),
        pytest.param(
            ["release", "72", "--abandoned", "stopped"],
            "Ada",
            "",
            "release without --claim-id requires a non-empty current branch; pass --claim-id",
            id="release-without-claim-id",
        ),
        pytest.param(
            ["release", "72", "--coordinator-override", "--abandoned", "takeover"],
            "Ada",
            None,
            None,
            id="release-override-without-the-coordinator-role",
        ),
    ],
)
def test_cli_identity_and_release_refusals_print_the_shared_envelope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    agent: str | None,
    branch: str | None,
    sentence: str | None,
) -> None:
    """Identity resolution and `release`'s own branch and
    override checks (REL-06..08) print the shared envelope (OUT-05); the text form keeps the bare
    `ERROR:` sentence it always printed."""
    _prepare_identity_or_release_branch_refusal(monkeypatch, agent, branch)
    text_status = issue_claim.main(["--repo", REPOSITORY, *arguments])
    text = capsys.readouterr()

    _prepare_identity_or_release_branch_refusal(monkeypatch, agent, branch)
    json_status = issue_claim.main(["--repo", REPOSITORY, *arguments, "--json"])
    envelope = capsys.readouterr()

    assert (text_status, json_status) == (2, 2)
    assert text.out == ""
    if sentence is not None:
        assert text.err == f"ERROR: {sentence}\n"
        assert json.loads(envelope.out)["message"] == sentence
    assert envelope.err == text.err
    _assert_json_refusal_object(envelope.err, envelope.out, reason="precondition_failed")


@pytest.mark.parametrize(
    ("item", "agent", "sentence", "reason"),
    [
        pytest.param(
            "16777216",
            None,
            "16777216 names no state-ref item; an item id ends at aco-ffffff",
            "invalid_usage",
            id="pin-31-before-identity",
        ),
        pytest.param("72", "Ada", "handler refused", None, id="handler-outside-identity-catch"),
    ],
)
def test_cli_repository_refusals_preserve_pin_and_handler_error_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    item: str,
    agent: str | None,
    sentence: str,
    reason: str | None,
) -> None:
    """PIN-31 precedes identity resolution; handler errors keep their plain report."""
    _write_state_ref_pin(tmp_path)
    set_agent_identity_env(monkeypatch, {} if agent is None else {checkout.ACO_AGENT_ENV: agent})

    def refuse_handler(parsed: argparse.Namespace, context: RunContext) -> int:
        raise protocol.ClaimError(sentence)

    command = cast(issue_claim._RepositoryCommand, issue_claim._COMMANDS["claim"])
    monkeypatch.setitem(issue_claim._COMMANDS, "claim", replace(command, run=refuse_handler))

    status = issue_claim.main(["claim", item, "--json"])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == f"ERROR: {sentence}\n"
    if reason is None:
        assert captured.out == ""
    else:
        _assert_json_refusal_object(captured.err, captured.out, reason=reason)


def test_cli_claim_json_conflict_prints_the_stdout_error_object_not_a_success_shape(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    standing = request(issue=72, scope=("src",))
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    _patch_store_write(monkeypatch, store_claim_from_request(standing))

    claimed = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Grok 4.6",
            "--role",
            "builder",
            "--base",
            BASE,
            "--branch",
            "codex/issue-72",
            "--scope",
            "docs",
            "--claim-id",
            "challenger",
            "--json",
        ]
    )
    captured = capsys.readouterr()

    assert claimed == 2
    _assert_json_refusal_object(captured.err, captured.out, reason="claim_conflict")


def test_cli_claim_json_transport_failure_reports_unavailable_not_conflict(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A transport/CAS failure surfacing from `store.commit_transition` is a
    plain `protocol.ClaimError`, never `protocol.ClaimConflictError`
    (CLM-27): `claim --json` reports `unavailable`, not
    `claim_conflict`, exactly as `release`'s own retry-exhaustion refusal
    does."""
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    _patch_store_write(monkeypatch)

    def failing_commit_transition(*args: object, **kwargs: object) -> protocol.ClaimState:
        raise protocol.ClaimUnavailableError(
            f"{store.STATE_REF} moved 5 times while retrying: another writer on "
            "origin keeps landing first; retry the command"
        )

    monkeypatch.setattr(store, "commit_transition", failing_commit_transition)

    claimed = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Grok 4.6",
            "--role",
            "builder",
            "--base",
            BASE,
            "--branch",
            "codex/issue-72",
            "--scope",
            "docs",
            "--claim-id",
            "challenger",
            "--json",
        ]
    )
    captured = capsys.readouterr()

    assert claimed == 2
    _assert_json_refusal_object(captured.err, captured.out, reason="unavailable")


def test_cli_module_entry_point_exits_with_mains_return_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`python -m aco.cli` and the installed console script run
    the `if __name__ == "__main__":` guard, not `cli.main()` as a library call --
    exercise that guard directly rather than only ever calling `cli.main()`.

    An unknown command is refused by the parser before any repository, git,
    GitHub or store is reached, so the exit code this observes is
    `cli.main`'s own return value and nothing else's."""
    monkeypatch.setattr(sys, "argv", ["aco", "no-such-command"])

    with (
        pytest.warns(RuntimeWarning, match="aco.cli"),
        pytest.raises(SystemExit) as exited,
    ):
        runpy.run_module("aco.cli", run_name="__main__")

    assert exited.value.code == 2
    assert "invalid choice: 'no-such-command'" in capsys.readouterr().err


def test_cli_claim_resource_prints_the_allocated_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())

    status = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Ada",
            "--base",
            BASE,
            "--branch",
            "codex/issue-72",
            "--scope",
            "src",
            "--resource",
            "schema-hop",
            "--claim-id",
            "hop-1",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert status == 0
    assert payload["resource"] == "schema-hop"
    assert payload["resource_value"] == 1
    posted = _live_store_claim()
    assert posted.resource == protocol.ResourceHold("schema-hop", 1)


@dataclass(frozen=True)
class AdvisoryClaims:
    first_issue: int
    first_scope: str
    second_issue: int
    second_scope: str
    wholes: tuple[bool, bool]
    directories: tuple[str, ...]
    overlap: str


ADVISORY_CLAIMS = {
    "directory-and-directory": AdvisoryClaims(
        72, "src", 73, "src", (True, True), ("src",), "overlaps issue #72 on src"
    ),
    "file-and-file": AdvisoryClaims(
        72,
        "src/widget.py",
        73,
        "src/widget.py",
        (False, False),
        (),
        "overlaps issue #72 on src/widget.py",
    ),
    # The directory in the newly granted scope holds a file a standing claim holds.
    "directory-over-a-held-file": AdvisoryClaims(
        1400,
        "tests/adapters/test_claim_cli.py",
        1401,
        "tests",
        (False, True),
        ("tests",),
        "overlaps issue #1400 on tests/adapters/test_claim_cli.py",
    ),
}


@pytest.mark.parametrize("case", ADVISORY_CLAIMS.values(), ids=ADVISORY_CLAIMS.keys())
def test_cli_two_claims_of_overlapping_scopes_are_advisory(
    case: AdvisoryClaims, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_status_cli(monkeypatch, FakeForge())
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(
        checkout,
        "scope_directories",
        lambda paths, **_kwargs: tuple(path for path in paths if path in case.directories),
    )

    first_whole, second_whole = (("--whole", "wide on purpose") if w else () for w in case.wholes)
    first = issue_claim.main(
        _claim_argv(
            "--scope", case.first_scope, *first_whole, issue=case.first_issue, claim_id="claim-a"
        )
    )
    capsys.readouterr()
    second = issue_claim.main(
        _claim_argv(
            "--scope", case.second_scope, *second_whole, issue=case.second_issue, claim_id="claim-b"
        )
    )
    claimed = capsys.readouterr().out

    assert (first, second, "CONFLICT" in claimed, case.overlap in claimed) == (0, 0, False, True)


def test_cli_two_resource_claims_allocate_one_then_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_status_cli(monkeypatch, FakeForge())
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    resource = ("--resource", "schema-hop", "--json")

    first = issue_claim.main(
        _claim_argv("--scope", "src/a.py", *resource, issue=72, claim_id="hop-1")
    )
    first_payload = json.loads(capsys.readouterr().out)
    second = issue_claim.main(
        _claim_argv("--scope", "src/b.py", *resource, issue=73, claim_id="hop-2")
    )
    second_payload = json.loads(capsys.readouterr().out)
    holds = sorted(
        claim.resource.value
        for claim in store.fetch_state(worktree=Path("."), remote="origin").claims.values()
        if claim.resource is not None and claim.resource.name == "schema-hop"
    )

    assert (first, second) == (0, 0)
    assert (first_payload["resource_value"], second_payload["resource_value"]) == (1, 2)
    assert holds == [1, 2]


def test_next_names_an_old_ruling_when_the_item_is_pulled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    issue = board_issue(
        10,
        "Work",
        complete_contract("Claim #10.", expectation=[ruled_expectation("Name it.")]),
    )
    client = FakeForge()
    monkeypatch.setattr(client, "list_open_board_issues", lambda: (issue,))
    monkeypatch.setattr(client, "list_open_board_pull_requests", lambda: ())
    monkeypatch.setattr(client, "list_recent_merged_board_pull_requests", lambda _since: ())
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _fake_lane_worktree_git(monkeypatch, tmp_path)
    monkeypatch.setattr(
        checkout,
        "trunk_landings",
        lambda *_args, **_kwargs: tuple(
            checkout.TrunkLanding(f"sha{hour}", datetime(2026, 8, 29, hour, tzinfo=UTC), None, ())
            for hour in range(10)
        ),
    )
    _patch_store_write(monkeypatch)

    assert issue_claim.main(["--repo", REPOSITORY, "next"]) == 0
    assert capsys.readouterr().out == (
        "#10 score -10: Work\n"
        "Next: Claim #10.\n"
        "Run: aco claim 10 --scope <paths>\n"
        + _SCOPE_UNKNOWN_NOTE_LINE
        + "ruled 10 landings ago: refine again at the pull\n"
        + _PARALLEL_UNKNOWN_TAIL
    )

    assert issue_claim.main(["--repo", REPOSITORY, "next", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ruling_landings"] == 10
    assert payload["ruling_old"] is True
    assert payload["ruling_hint"] == "ruled 10 landings ago: refine again at the pull"


def test_no_path_class_list_is_read_or_written() -> None:
    assert not Path("src/aco").joinpath("single_writer.py").exists()
    text = Path("src/aco/protocol.py").read_text()
    assert "single-writer" not in text
    assert "single_writer" not in text


LANE_BRANCH = "docs/tidy-readme"


_MERGE_COMMIT_COMMITTED_AT = datetime(2026, 9, 1, tzinfo=UTC)


def _trunk_landing(
    sha: str, classification: workboard.TrunkClassification | workboard.ClassificationDefect | None
) -> checkout.TrunkLanding:
    """One walked trunk commit: the shape
    `merged_release_client`'s own `checkout.trunk_landings` stub returns,
    and every test proving a merge-commit defect builds its own variant
    from -- the same reader and grammar `storage = state-ref` already
    trusts (`checkout._trunk_landing_defect`)."""
    work_item_values = (
        tuple(f"#{number}" for number in classification.numbers)
        if isinstance(classification, TrunkWorkItemClassification)
        else ()
    )
    return checkout.TrunkLanding(sha, _MERGE_COMMIT_COMMITTED_AT, classification, work_item_values)


@dataclass(frozen=True)
class ReleaseMergeScenario:
    """The pull request body, merge facts, and walked trunk
    `merged_release_client` builds a landing from -- one parametrized case's
    worth, typed instead of a loose `dict[str, object]` so each keyword
    forwards to it honestly."""

    body: str
    merged: bool = True
    base_ref_name: str = "main"
    landings: tuple[checkout.TrunkLanding, ...] | None = None


def merged_release_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    body: str,
    merged: bool = True,
    base_ref_name: str = "main",
    lane: bool = False,
    merge_commit: str = MERGE_COMMIT_SHA,
    landings: tuple[checkout.TrunkLanding, ...] | None = None,
) -> FakeForge:
    """A session whose one claim can be released against pull request #12.

    `landings` stubs the walked first-parent trunk every release now
    verifies its merge commit against:
    `None` -- the default -- seeds the one trunk commit
    that authorizes closing `WORK_ITEM_ISSUE` at `merge_commit` for an
    issue release, or declaring the lane issue-less for a lane release,
    matching this fixture's own happy path either way; a test of a
    merge-commit defect passes its own tuple instead.
    """
    branch = LANE_BRANCH if lane else LANDING_BRANCH
    standing = request(
        "landing",
        "Ada",
        issue=None if lane else WORK_ITEM_ISSUE,
        branch=branch,
        scope=("src",),
    )
    client = FakeForge()
    client.landings[12] = landing_pull_request(
        body=body,
        merged=merged,
        base_ref_name=base_ref_name,
        head_ref_name=branch,
        merge_commit=merge_commit if merged else None,
    )
    _patch_release_session(monkeypatch, client, standing, branch=branch)
    default_classification = (
        NoItemClassification(NoItemKind.DOCS)
        if lane
        else TrunkWorkItemClassification((WORK_ITEM_ISSUE,))
    )
    resolved = (
        landings
        if landings is not None
        else (_trunk_landing(merge_commit, default_classification),)
    )
    monkeypatch.setattr(checkout, "trunk_landings", lambda *_args, **_kwargs: resolved)
    return client


def test_release_merged_records_the_pull_request_that_landed_the_item(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")
    client.closed_issues.add(WORK_ITEM_ISSUE)
    monkeypatch.setattr(board_read, "fetch_issue_reference", _LIVE_FETCH_ISSUE_REFERENCE)

    assert issue_claim.main(["--repo", REPOSITORY, "release", "72", "--merged", "12"]) == 0

    assert client.issue_reference_lookups == [WORK_ITEM_ISSUE]
    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


def _landed_dependency(
    closed_at: datetime = datetime(2026, 9, 10, tzinfo=UTC),
) -> IssueDependency:
    """The now-closed `blocked_by` relation a dependent of `WORK_ITEM_ISSUE`
    carries once GitHub has recorded the landing."""
    return block_dependency(WORK_ITEM_ISSUE, state=BlockerState.CLOSED, closed_at=closed_at)


def _two_dependants_freed_by_the_landing() -> tuple[
    tuple[Issue, ...], dict[int, tuple[IssueDependency, ...]]
]:
    """Two open items whose only blocker was `WORK_ITEM_ISSUE`, one of which
    also unblocks a third, still-waiting item, plus a fourth item a foreign
    repository still blocks even though its own local blocker just closed
    -- the fixture `release --merged`'s own `freed`/`next`
    tests share, so a lower- and a higher-scored freed pick differ only by
    which one unblocks something else, and a not-fully-freed item stays out
    of `freed` even once its local blocker is gone, and a fifth item freed
    by an earlier landing is not this landing's to report."""
    lower, lower_dependencies = blocked_issue(80, "Lower priority freed item", _landed_dependency())
    higher, higher_dependencies = blocked_issue(
        81, "Higher priority freed item", _landed_dependency()
    )
    waiting, waiting_dependencies = blocked_issue(82, "Still waiting", block_dependency(81))
    still_foreign_blocked, still_foreign_blocked_dependencies = blocked_issue(
        83,
        "Still foreign-blocked",
        _landed_dependency(),
        block_dependency(9, repository="other/repo"),
    )
    freed_earlier, freed_earlier_dependencies = blocked_issue(
        84,
        "Freed by an earlier landing",
        block_dependency(60, state=BlockerState.CLOSED, closed_at=datetime(2026, 9, 1, tzinfo=UTC)),
    )
    issues = (lower, higher, waiting, still_foreign_blocked, freed_earlier)
    dependencies = {
        **lower_dependencies,
        **higher_dependencies,
        **waiting_dependencies,
        **still_foreign_blocked_dependencies,
        **freed_earlier_dependencies,
    }
    return issues, dependencies


@dataclass(frozen=True)
class ReleaseFreedScenario:
    """One landing's currently open board and the `freed`/`next` release
    should report for it."""

    issues: tuple[Issue, ...]
    dependencies: dict[int, tuple[IssueDependency, ...]]
    freed: list[int]
    next_number: int | None


def _release_freed_scenarios() -> list[ReleaseFreedScenario]:
    freeing_issues, freeing_dependencies = _two_dependants_freed_by_the_landing()
    return [
        ReleaseFreedScenario(freeing_issues, freeing_dependencies, [80, 81], 81),
        ReleaseFreedScenario((), {}, [], None),
    ]


@pytest.mark.parametrize(
    "scenario", _release_freed_scenarios(), ids=["two-dependants-freed", "no-dependants"]
)
def test_release_merged_reports_the_json_freed_list_and_next_pick(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scenario: ReleaseFreedScenario,
) -> None:
    client = merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")
    client.closed_issues.add(WORK_ITEM_ISSUE)
    monkeypatch.setattr(board_read, "fetch_issue_reference", _LIVE_FETCH_ISSUE_REFERENCE)
    client.board_issues = scenario.issues
    client.board_dependencies = scenario.dependencies

    exit_code = issue_claim.main(
        ["--repo", REPOSITORY, "release", str(WORK_ITEM_ISSUE), "--merged", "12", "--json"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["freed"] == scenario.freed
    assert payload["next"] == scenario.next_number


def test_release_merged_json_reports_ok_reason_merged_and_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A `--merged` release's own `reason` is the stable token
    `merged`, distinct from `outcome`'s own prose sentence."""
    client = merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")
    client.closed_issues.add(WORK_ITEM_ISSUE)
    monkeypatch.setattr(board_read, "fetch_issue_reference", _LIVE_FETCH_ISSUE_REFERENCE)

    exit_code = issue_claim.main(
        ["--repo", REPOSITORY, "release", str(WORK_ITEM_ISSUE), "--merged", "12", "--json"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["reason"] == "merged"
    assert payload["outcome"] == "merged #12"


def test_release_merged_prints_the_freed_and_next_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")
    client.closed_issues.add(WORK_ITEM_ISSUE)
    monkeypatch.setattr(board_read, "fetch_issue_reference", _LIVE_FETCH_ISSUE_REFERENCE)
    client.board_issues, client.board_dependencies = _two_dependants_freed_by_the_landing()

    exit_code = issue_claim.main(
        ["--repo", REPOSITORY, "release", str(WORK_ITEM_ISSUE), "--merged", "12"]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert f"RELEASED issue #{WORK_ITEM_ISSUE}: landing\n" in out
    assert "freed: #80, #81\n" in out
    assert "next: #81 score" in out
    assert "Higher priority freed item" in out


PARENT_OF_WORK_ITEM = 79


def _released_last_child_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sibling_open: bool,
    parent_closed: bool = False,
    parent_next: str = "keiner",
    parent_slices: tuple[str, ...] = (),
) -> FakeForge:
    """`merged_release_client` plus a recorded parent relation:
    `WORK_ITEM_ISSUE` is `PARENT_OF_WORK_ITEM`'s only child when
    `sibling_open` is `False` -- its own close leaves the parent with no
    open children and no uncut `[[slice]]` row, exactly `next`'s own
    `workboard.CloseContainerAction` branch -- or one still-open sibling when `True`,
    the parent hint's own negative case. `parent_closed` (G2 review) covers
    the third negative case: the parent itself already closed (by some
    other landing) before this release even runs -- a childless, uncut
    parent that is not open must never be named closable, since a second
    close would only refuse. `parent_next` is the parent's own `Next` line:
    one still naming work is a container between two slices,
    never closable either; so is one still holding an
    uncut `[[slice]]` row (`parent_slices`)."""
    client = merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")
    client.closed_issues.add(WORK_ITEM_ISSUE)
    monkeypatch.setattr(board_read, "fetch_issue_reference", _LIVE_FETCH_ISSUE_REFERENCE)
    client.parents[WORK_ITEM_ISSUE] = workboard.ParentIssue(
        workboard.IssueReference(REPOSITORY, PARENT_OF_WORK_ITEM),
        complete_contract(parent_next, slice=slice_entries(*parent_slices)),
        body.ItemKind.CONTAINER,
    )
    children = [ChildItem(WORK_ITEM_ISSUE, ChildState.CLOSED)]
    if sibling_open:
        children.append(ChildItem(999, ChildState.OPEN))
    client.children[PARENT_OF_WORK_ITEM] = tuple(children)
    if parent_closed:
        client.closed_issues.add(PARENT_OF_WORK_ITEM)
    return client


@pytest.mark.parametrize(
    ("sibling_open", "parent_closed", "parent_next", "parent_slices", "hint_expected"),
    [
        pytest.param(False, False, "keiner", (), True, id="last_open_child_names_the_parent"),
        pytest.param(True, False, "keiner", (), False, id="a_sibling_still_open_omits_the_hint"),
        pytest.param(
            False, True, "keiner", (), False, id="an_already_closed_parent_omits_the_hint"
        ),
        pytest.param(
            False,
            False,
            "Cut slice 3.",
            (),
            False,
            id="a_parent_naming_further_work_omits_the_hint",
        ),
        pytest.param(
            False,
            False,
            "keiner",
            ("Scheibe 1",),
            False,
            id="a_parent_holding_an_uncut_row_omits_the_hint",
        ),
    ],
)
def test_release_merged_names_the_parent_hint_only_for_the_last_open_child(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sibling_open: bool,
    parent_closed: bool,
    parent_next: str,
    parent_slices: tuple[str, ...],
    hint_expected: bool,
) -> None:
    """Releasing a container's last open child names
    the parent as freshly closable, the same decision `next`'s own `close:`
    line makes for a childless, uncut container -- a still-open sibling
    keeps the container un-closable and the hint absent, and so does a
    parent that is already closed itself (G2 review)."""
    _released_last_child_client(
        monkeypatch,
        sibling_open=sibling_open,
        parent_closed=parent_closed,
        parent_next=parent_next,
        parent_slices=parent_slices,
    )

    exit_code = issue_claim.main(
        ["--repo", REPOSITORY, "release", str(WORK_ITEM_ISSUE), "--merged", "12"]
    )

    assert exit_code == 0
    hint = f"parent #{PARENT_OF_WORK_ITEM}: no open children — close it\n"
    assert (hint in capsys.readouterr().out) is hint_expected


def test_release_merged_beside_an_unreadable_parent_reports_freed_instead_of_a_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """BOARD-54: a landed child whose container went
    unreadable -- its kind unknown, its own state read refusing as the
    state-ref adapter's does -- keeps the release's `freed:`/`next` report;
    an unreadable parent is never named closable, so its refusal never
    stands in for the report."""
    client = _released_last_child_client(monkeypatch, sibling_open=False)
    unreadable = client.parents[WORK_ITEM_ISSUE]
    client.parents[WORK_ITEM_ISSUE] = workboard.ParentIssue(unreadable.reference, unreadable.body)
    readable_reference = client.item_reference

    def refusing_the_parent(number: int) -> forge.ItemReference:
        if number == PARENT_OF_WORK_ITEM:
            raise protocol.MalformedStateTreeError("item aco-000001 has a malformed aco block")
        return readable_reference(number)

    monkeypatch.setattr(client, "item_reference", refusing_the_parent)

    exit_code = issue_claim.main(
        ["--repo", REPOSITORY, "release", str(WORK_ITEM_ISSUE), "--merged", "12"]
    )

    out = capsys.readouterr().out
    assert (exit_code, "freed:" in out, "hint:" in out, "close it" in out) == (
        0,
        True,
        False,
        False,
    )


def test_release_merged_json_carries_the_parent_closable_number(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """JSON: `parent_closable` carries the same
    number the text form's parent hint names."""
    _released_last_child_client(monkeypatch, sibling_open=False)

    exit_code = issue_claim.main(
        ["--repo", REPOSITORY, "release", str(WORK_ITEM_ISSUE), "--merged", "12", "--json"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["parent_closable"] == PARENT_OF_WORK_ITEM


def test_release_merged_fetches_each_candidates_dependencies_only_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The `freed` report and the projected `next` pick share one dependency
    fetch: `board_read.build_board`'s own board build must not re-list
    the same blocked-by candidates `workboard.freed_item_numbers` already read."""
    client = merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")
    client.closed_issues.add(WORK_ITEM_ISSUE)
    monkeypatch.setattr(board_read, "fetch_issue_reference", _LIVE_FETCH_ISSUE_REFERENCE)
    client.board_issues, client.board_dependencies = _two_dependants_freed_by_the_landing()
    observed_dependency_calls: list[int] = []
    original_list_board_dependencies = client.list_board_dependencies

    def spy_list_board_dependencies(number: int) -> tuple[IssueDependency, ...]:
        observed_dependency_calls.append(number)
        return original_list_board_dependencies(number)

    monkeypatch.setattr(client, "list_board_dependencies", spy_list_board_dependencies)

    exit_code = issue_claim.main(
        ["--repo", REPOSITORY, "release", str(WORK_ITEM_ISSUE), "--merged", "12"]
    )

    assert exit_code == 0
    assert sorted(observed_dependency_calls) == [80, 81, 82, 83, 84]


@pytest.mark.parametrize(
    "board_error",
    [
        pytest.param(forge.ForgeTransientError("gh: connection reset"), id="forge-outage"),
        pytest.param(
            protocol.MalformedStateTreeError(
                "item aco-0a0a0a is referenced as a parent but does not exist"
            ),
            id="state-ref-item-names-a-missing-parent",
        ),
    ],
)
def test_release_merged_prints_a_hint_instead_of_failing_when_the_board_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    board_error: protocol.ClaimError,
) -> None:
    """A forge outage -- or a state-ref item naming a missing parent the board
    read refuses on (PIN-16, LAND-65) -- that only shows after the release itself already
    committed must not undo or fail it: the release's own
    exit code and store effect stay exactly what a readable board would
    have produced, with one hint line standing in for `freed`/`next`."""
    client = merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")
    client.closed_issues.add(WORK_ITEM_ISSUE)
    monkeypatch.setattr(board_read, "fetch_issue_reference", _LIVE_FETCH_ISSUE_REFERENCE)

    def unreachable() -> tuple[Issue, ...]:
        raise board_error

    monkeypatch.setattr(client, "list_open_board_issues", unreachable)

    exit_code = issue_claim.main(
        ["--repo", REPOSITORY, "release", str(WORK_ITEM_ISSUE), "--merged", "12"]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert out.startswith(f"RELEASED issue #{WORK_ITEM_ISSUE}: landing\n")
    assert "hint:" in out
    assert "freed:" not in out
    assert "next:" not in out
    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


def test_release_merged_json_omits_freed_and_next_when_the_board_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")
    client.closed_issues.add(WORK_ITEM_ISSUE)
    monkeypatch.setattr(board_read, "fetch_issue_reference", _LIVE_FETCH_ISSUE_REFERENCE)

    def unreachable() -> tuple[Issue, ...]:
        raise forge.ForgeTransientError("gh: connection reset")

    monkeypatch.setattr(client, "list_open_board_issues", unreachable)

    exit_code = issue_claim.main(
        ["--repo", REPOSITORY, "release", str(WORK_ITEM_ISSUE), "--merged", "12", "--json"]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "freed" not in payload
    assert "next" not in payload
    assert "hint:" in captured.err


@pytest.mark.parametrize("kind", ["docs", "fix", "deps"])
def test_release_merged_accepts_an_issueless_lane_that_landed_without_an_item(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    merged_release_client(
        monkeypatch,
        body=f"No-Item: {kind}",
        lane=True,
        landings=(
            _trunk_landing(MERGE_COMMIT_SHA, workboard.trunk_commit_classification((), (kind,))),
        ),
    )

    assert issue_claim.main(["--repo", REPOSITORY, "release", "--merged", "12"]) == 0

    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


def test_release_merged_refuses_an_issueless_lane_landing_off_trunk(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`checkout._trunk_no_item_landing_defect`'s
    own off-trunk branch, the `protocol.LaneIdentity` counterpart to
    `test_release_merged_refuses_a_landing_it_cannot_verify`'s `off-trunk`
    case -- an issue-less lane's merge commit missing from the walked
    trunk refuses exactly the same way."""
    merged_release_client(monkeypatch, body="No-Item: docs", lane=True, landings=())

    assert issue_claim.main(["--repo", REPOSITORY, "release", "--merged", "12"]) == 2

    assert capsys.readouterr().err == (
        f"ERROR: merge commit {MERGE_COMMIT_SHA} of pull request #12 "
        "is not on the first-parent trunk\n"
    )


def test_release_merged_refuses_an_issueless_lane_landing_with_a_classification_defect(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`checkout._trunk_no_item_landing_defect`
    surfaces the walked trunk's own `workboard.ClassificationDefect` message
    verbatim when the merge commit's own trailer is malformed, never a
    generic "no `No-Item:` trailer" refusal."""
    merged_release_client(
        monkeypatch,
        body="No-Item: docs",
        lane=True,
        landings=(
            _trunk_landing(
                MERGE_COMMIT_SHA, workboard.ClassificationDefect("names two conflicting issues")
            ),
        ),
    )

    assert issue_claim.main(["--repo", REPOSITORY, "release", "--merged", "12"]) == 2

    assert capsys.readouterr().err == (
        f"ERROR: merge commit {MERGE_COMMIT_SHA} of pull request #12 names two conflicting issues\n"
    )


@pytest.mark.parametrize(
    ("scenario", "reason"),
    [
        pytest.param(
            ReleaseMergeScenario(body="Work-Item: #72\n\nCloses #72", merged=False),
            "pull request #12 is not merged",
            id="not-merged",
        ),
        pytest.param(
            ReleaseMergeScenario(body="Work-Item: #72\n\nCloses #72", base_ref_name="release"),
            "pull request #12 merged into 'release', not the default branch 'main'",
            id="wrong-base",
        ),
        pytest.param(
            ReleaseMergeScenario(body="Work-Item: #72\n\nCloses #72", landings=()),
            f"merge commit {MERGE_COMMIT_SHA} of pull request #12 is not on the first-parent trunk",
            id="off-trunk",
        ),
        pytest.param(
            ReleaseMergeScenario(
                body="Work-Item: #72\n\nCloses #72",
                landings=(_trunk_landing(MERGE_COMMIT_SHA, None),),
            ),
            f"merge commit {MERGE_COMMIT_SHA} of pull request #12 carries no `Work-Item:` trailer; "
            'release it with --abandoned "landed as PR #12 without a Work-Item: trailer" '
            "and close #72 by hand",
            id="no-trailer",
        ),
        pytest.param(
            ReleaseMergeScenario(
                body="Work-Item: #72\n\nCloses #72",
                landings=(_trunk_landing(MERGE_COMMIT_SHA, TrunkWorkItemClassification((99,))),),
            ),
            f"merge commit {MERGE_COMMIT_SHA} of pull request #12 does not name work item #72",
            id="another-item",
        ),
        pytest.param(
            ReleaseMergeScenario(
                body="Work-Item: #72\n\nCloses #72",
                landings=(_trunk_landing(MERGE_COMMIT_SHA, NoItemClassification(NoItemKind.DOCS)),),
            ),
            f"merge commit {MERGE_COMMIT_SHA} of pull request #12 does not name work item #72",
            id="trunk-declares-no-item",
        ),
    ],
)
def test_release_merged_refuses_a_landing_it_cannot_verify(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scenario: ReleaseMergeScenario,
    reason: str,
) -> None:
    """A merge commit that is off-trunk,
    carries no `Work-Item:` trailer, or names a different item refuses
    before close/release, regardless of what the pull request's own --
    mutable -- body still says."""
    merged_release_client(
        monkeypatch,
        body=scenario.body,
        merged=scenario.merged,
        base_ref_name=scenario.base_ref_name,
        landings=scenario.landings,
    )
    _stub_issue_reference(monkeypatch, {WORK_ITEM_ISSUE: (forge.ItemState.CLOSED, "", "")})

    assert issue_claim.main(["--repo", REPOSITORY, "release", "72", "--merged", "12"]) == 2
    assert capsys.readouterr().err == f"ERROR: {reason}\n"
    assert store.fetch_state(worktree=Path("."), remote="origin").claims


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("", id="empty-body"),
        pytest.param("Advances #72", id="no-work-item-line"),
        pytest.param("Work-Item: #99\n\nCloses #99", id="wrong-numbered-work-item"),
    ],
)
def test_release_merged_ignores_the_pull_requests_own_body_for_an_issue(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], body: str
) -> None:
    """The merge commit's own `Work-Item: #72`
    trailer is the authority for an issue release, not the pull request's
    mutable `body` -- an edited, missing, or wrong-numbered body still
    lands the release the trailer already authorizes."""
    client = merged_release_client(monkeypatch, body=body)

    assert issue_claim.main(["--repo", REPOSITORY, "release", "72", "--merged", "12"]) == 0

    assert client.closed_issues == {WORK_ITEM_ISSUE}
    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


def test_release_merged_closes_the_still_open_work_item(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A merged release against a still-open
    work item closes it through the forge writer -- one comment naming the
    landing pull request, then the close -- instead of refusing, and still
    releases the claim."""
    client = merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")

    assert issue_claim.main(["--repo", REPOSITORY, "release", "72", "--merged", "12"]) == 0

    assert client.closed_issues == {WORK_ITEM_ISSUE}
    assert client.landing_comments == {WORK_ITEM_ISSUE: github.landing_comment(12)}
    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


@pytest.mark.parametrize(
    ("output", "stdout_for"),
    [
        pytest.param((), lambda _refusal: "", id="text"),
        pytest.param(
            ("--json",),
            lambda refusal: (
                json.dumps({"ok": False, "reason": "precondition_failed", "message": refusal})
                + "\n"
            ),
            id="json",
        ),
    ],
)
@pytest.mark.parametrize(
    "work_item_value",
    [pytest.param("#72", id="valid-reference"), pytest.param("fix/x", id="branch-name")],
)
def test_release_merged_refuses_a_lane_whose_merge_commit_names_a_work_item(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    work_item_value: str,
    output: tuple[str, ...],
    stdout_for: Callable[[str], str],
) -> None:
    """A lane release's authority is
    the merge commit's own trailer block, not the pull request's mutable
    `body` -- ignored here even though it declares `No-Item:` -- so a
    squash commit carrying `Work-Item:`, valid or malformed alike, refuses
    with the lane rule and the only way out, `--abandoned`."""
    trailer_values = (work_item_value,)
    squash_commit = checkout.TrunkLanding(
        MERGE_COMMIT_SHA,
        _MERGE_COMMIT_COMMITTED_AT,
        workboard.trunk_commit_classification(trailer_values, ()),
        trailer_values,
    )
    merged_release_client(monkeypatch, body="No-Item: docs", lane=True, landings=(squash_commit,))
    command = ["--repo", REPOSITORY, "release", "--merged", "12", *output]

    refusal = (
        f"merge commit {MERGE_COMMIT_SHA} of pull request #12 carries "
        f"`Work-Item: {work_item_value}`; an issue-less lane needs a "
        '`No-Item: <docs|fix|deps>` trailer; release it with --abandoned "landed as PR #12 '
        'with a malformed trailer"'
    )

    assert issue_claim.main(command) == 2
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == (stdout_for(refusal), f"ERROR: {refusal}\n")
    assert store.fetch_state(worktree=Path("."), remote="origin").claims


def test_release_merged_refuses_an_unclassified_lane_merge_commit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An issue-less lane's authority is its own merge commit's trailer
    block: a trunk commit carrying neither
    `Work-Item:` nor `No-Item:` refuses regardless of what the pull
    request's own mutable body says."""
    merged_release_client(
        monkeypatch,
        body="No-Item: docs",
        lane=True,
        landings=(_trunk_landing(MERGE_COMMIT_SHA, None),),
    )

    assert issue_claim.main(["--repo", REPOSITORY, "release", "--merged", "12"]) == 2
    assert capsys.readouterr().err == (
        f"ERROR: merge commit {MERGE_COMMIT_SHA} of pull request #12 carries no "
        "`Work-Item:` or `No-Item:` trailer\n"
    )


def test_release_merged_refuses_a_work_item_neither_open_nor_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`cmd_release._pending_landing_close`'s third `reference.state` branch: the named
    work item vanished between the pull request's own classification and
    this read (a real race, not reachable through the already-covered open/
    closed cases), so the release refuses rather than guessing either
    outcome."""
    merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")
    _stub_issue_reference(monkeypatch, {WORK_ITEM_ISSUE: (forge.ItemState.MISSING, "", "")})

    assert issue_claim.main(["--repo", REPOSITORY, "release", "72", "--merged", "12"]) == 2
    assert capsys.readouterr().err == (
        f"ERROR: work item #{WORK_ITEM_ISSUE} is missing, not closed\n"
    )
    assert store.fetch_state(worktree=Path("."), remote="origin").claims


_MERGED_NEEDS_A_PULL_REQUEST_NUMBER = (
    "--merged requires a pull request number under storage = github"
)


@pytest.mark.parametrize(
    "merged",
    [
        pytest.param("sha123", id="sha"),
        pytest.param("²", id="superscript-digit"),
        pytest.param("٧٢", id="non-ascii-digits"),
        pytest.param("7" * (protocol.MAXIMUM_ISSUE_NUMBER_DIGITS + 1), id="past-the-bound"),
        pytest.param("7" * 5000, id="past-the-int-digit-limit"),
    ],
)
@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_release_merged_refuses_a_non_numeric_pull_request_under_github(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    merged: str,
    as_json: bool,
) -> None:
    """Spec: REL-60. `github.pull_request_number`'s own guard:
    `--merged` under `storage = "github"` (the default here -- no board.toml
    pins state-ref) takes only a bare ASCII pull request number of at most
    18 digits, never the sha grammar that pin's own `<sha|empty>` form
    reads; the refusal reaches no forge and leaves the live claim, and the
    state ref it sits on, exactly as they were."""
    worktree, bare_remote = _reset_repository(monkeypatch, tmp_path)
    _use_real_store(monkeypatch)
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    claim = _land_real_claim(worktree, bare_remote, issue=72, claim_id="claim-72")
    tip_before = _state_ref_tip(worktree, bare_remote)
    monkeypatch.setattr(
        github, "GitHubForge", lambda _repository: pytest.fail("the refusal reached the forge")
    )
    arguments = ["release", "72", "--agent", "Codex Sol", "--claim-id", "claim-72"]
    json_flag = ["--json"] if as_json else []

    status = issue_claim.main([*arguments, "--merged", merged, *json_flag])

    assert status == 2
    captured = capsys.readouterr()
    if as_json:
        payload = json.loads(captured.out)
        assert (payload["ok"], payload["reason"], payload["message"]) == (
            False,
            "precondition_failed",
            _MERGED_NEEDS_A_PULL_REQUEST_NUMBER,
        )
    else:
        assert captured.err == f"ERROR: {_MERGED_NEEDS_A_PULL_REQUEST_NUMBER}\n"
    assert _state_ref_tip(worktree, bare_remote) == tip_before
    assert store.fetch_state(worktree=worktree, remote="origin").claims == {
        protocol.claim_key(claim.identity, claim.branch): claim
    }


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(("72", "--agent", "Other"), id="mismatched-claimant"),
        pytest.param(("72", "--claim-id", "no-such-claim"), id="no-matching-claim"),
    ],
)
def test_release_merged_unauthorized_makes_no_forge_call_close_or_comment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: tuple[str, ...],
) -> None:
    """Authorization gates every forge read and write on a
    `--merged` release -- a mismatched claimant or an explicit claim id that
    matches nothing never reaches the forge, so it can neither verify the
    pull request, comment on its issue, nor close it; the forge is never
    asked in the first place (`client.requests == 0`). An issue with no live
    claim at all has nothing to authorize; its landing still has to verify."""
    client = merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")

    status = issue_claim.main(["--repo", REPOSITORY, "release", *args, "--merged", "12"])

    assert status == 2
    assert "ERROR:" in capsys.readouterr().err
    assert client.requests == 0
    assert client.closed_issues == set()
    assert client.landing_comments == {}
    assert store.fetch_state(worktree=Path("."), remote="origin").claims


_OLD_LANE_BRANCH = "codex/issue-72-old"


_UNCLAIMED_LANE_BRANCH = "docs/unclaimed"


@pytest.mark.parametrize(
    ("args", "lane", "source_branch", "trunk_after_merge", "refusal"),
    [
        pytest.param(
            ("999",),
            False,
            LANDING_BRANCH,
            (),
            f"merge commit {MERGE_COMMIT_SHA} of pull request #12 does not name work item #999",
            id="no-claim-and-a-merge-naming-another-item",
        ),
        pytest.param(
            ("72", "--branch", _OLD_LANE_BRANCH),
            False,
            _OLD_LANE_BRANCH,
            (),
            f"issue #72 is claimed on '{LANDING_BRANCH}', not on pull request #12's branch "
            f"'{_OLD_LANE_BRANCH}'; release that claim by itself",
            id="claim-off-the-pull-requests-branch",
        ),
        pytest.param(
            ("72",),
            False,
            LANDING_BRANCH,
            (BASE,),
            f"issue #72 was claimed on '{LANDING_BRANCH}' after pull request #12 landed; "
            "release that claim by itself",
            id="claim-opened-again-on-the-pull-requests-branch-after-it-landed",
        ),
        pytest.param(
            ("--branch", _UNCLAIMED_LANE_BRANCH),
            True,
            LANE_BRANCH,
            (),
            f"lane '{_UNCLAIMED_LANE_BRANCH}' has no active build claim",
            id="unclaimed-lane-off-the-pull-requests-claimed-branch",
        ),
    ],
)
def test_release_merged_refuses_what_its_landing_does_not_back_and_keeps_every_claim(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: tuple[str, ...],
    lane: bool,
    source_branch: str,
    trunk_after_merge: tuple[str, ...],
    refusal: str,
) -> None:
    """An issue with no live claim skips the
    release only once its landing verifies -- a merge commit naming another
    item refuses (REL-47). An issue's claim is keyed by the issue alone, so
    an old pull request's release, `aco land`'s rerun included, meets a
    newer claim on that issue -- a lane on another branch, or one opened on
    the same branch from a trunk that already holds the landing: it refuses
    by name and that claim is neither released nor skipped (REL-48, REL-53,
    E-REL-25). An issue-less lane's claim is keyed by its branch, so an
    unclaimed lane says nothing about the claimed lane its pull request came
    from: REL-09 refuses as before."""
    landing = _trunk_landing(MERGE_COMMIT_SHA, TrunkWorkItemClassification((WORK_ITEM_ISSUE,)))
    client = merged_release_client(
        monkeypatch,
        body="No-Item: docs" if lane else "Work-Item: #72\n\nCloses #72",
        lane=lane,
        landings=(
            (landing, *(_trunk_landing(sha, None) for sha in trunk_after_merge))
            if trunk_after_merge
            else None
        ),
    )
    client.landings[12] = replace(client.landings[12], source_branch=source_branch)

    status = issue_claim.main(["--repo", REPOSITORY, "release", *args, "--merged", "12"])

    assert (status, capsys.readouterr().err) == (2, f"ERROR: {refusal}\n")
    assert (client.closed_issues, client.landing_comments) == (set(), {})
    assert store.fetch_state(worktree=Path("."), remote="origin").claims


def test_release_merged_close_failure_preserves_the_claim_and_prints_a_sentence(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A close failure (a transient forge error, most often)
    runs before the release transition -- it leaves the claim exactly as
    live as it was, reported as the one sentence `cli.main`'s own `protocol.ClaimError`
    handler already prints, never a partially released claim with a
    still-open, uncommented issue."""
    client = merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")

    def failing_close(number: int, *, pull_request: int) -> None:
        raise forge.ForgeTransientError("gh: connection reset")

    monkeypatch.setattr(client, "close_landed_item", failing_close)

    status = issue_claim.main(["--repo", REPOSITORY, "release", "72", "--merged", "12"])

    assert status == 2
    assert capsys.readouterr().err == "ERROR: gh: connection reset\n"
    assert store.fetch_state(worktree=Path("."), remote="origin").claims
    assert client.closed_issues == set()


def test_release_merged_retries_after_a_post_close_cas_failure_without_a_second_comment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unlike a close failure (above), a CAS failure on the
    release transition itself strikes *after* `close_landed_item` already
    ran -- the comment is posted and the issue closed on the forge before
    `store.commit_transition` ever raises. The retry's own
    `cmd_release._pending_landing_close` now finds the work item already closed and
    returns no pending close (the same branch the replay-refusal proof
    exercises under `storage = state-ref`), so `close_landed_item` never
    runs a second time -- one comment total -- and the retried transition
    releases the claim."""
    client = merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")
    monkeypatch.setattr(board_read, "fetch_issue_reference", _LIVE_FETCH_ISSUE_REFERENCE)
    close_calls: list[int] = []
    real_close_landed_item = client.close_landed_item

    def counting_close(number: int, *, pull_request: int) -> None:
        close_calls.append(number)
        real_close_landed_item(number, pull_request=pull_request)

    monkeypatch.setattr(client, "close_landed_item", counting_close)
    real_commit_transition = store.commit_transition
    attempts = 0

    def cas_failure_once(*args: object, **kwargs: object) -> protocol.ClaimState:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise protocol.ClaimUnavailableError(
                f"{store.STATE_REF} moved 5 times while retrying: another writer on "
                "origin keeps landing first; retry the command"
            )
        return real_commit_transition(*args, **kwargs)

    monkeypatch.setattr(store, "commit_transition", cas_failure_once)

    status = issue_claim.main(["--repo", REPOSITORY, "release", "72", "--merged", "12"])

    assert status == 2
    assert capsys.readouterr().err == (
        f"ERROR: {store.STATE_REF} moved 5 times while retrying: another writer on "
        "origin keeps landing first; retry the command\n"
    )
    assert close_calls == [WORK_ITEM_ISSUE]
    assert client.closed_issues == {WORK_ITEM_ISSUE}
    assert store.fetch_state(worktree=Path("."), remote="origin").claims

    retry_status = issue_claim.main(["--repo", REPOSITORY, "release", "72", "--merged", "12"])

    assert retry_status == 0
    assert close_calls == [WORK_ITEM_ISSUE]
    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


_CONTRADICTORY_TRAILERS = (
    pytest.param("Work-Item: #20\nNo-Item: docs", id="both"),
    pytest.param("No-Item: docs\nNo-Item: fix", id="repeated-no-item"),
)


def _refused_trailer_repository(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, trailer: str
) -> Path:
    """A real trunk repository (LAND-60/61, LAND-68) whose one
    commit carries a trailer block `check <sha>` refuses: shared arrangement
    for both `check <sha>`'s and `release --merged <sha>`'s own refusal
    proofs, which read the identical classification."""
    monkeypatch.setattr(checkout, "trunk_landings", _LIVE_TRUNK_LANDINGS)
    repo, _remote = real_repository_with_bare_remote(tmp_path)
    (repo / "work.txt").write_text("work\n")
    real_git(repo, "add", "work.txt")
    real_git(repo, "commit", "-q", "-m", "refused landing", "-m", trailer)
    push_repository_trunk(repo, "origin")
    redirect_toplevel(monkeypatch, repo)
    monkeypatch.chdir(repo)
    return repo


@pytest.mark.parametrize("trailer", _CONTRADICTORY_TRAILERS)
def test_release_merged_by_sha_refuses_a_contradictory_trailer(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    trailer: str,
) -> None:
    """LAND-61/CI: `release --merged <sha>` under state-ref
    reads the exact same classification `check <sha>` does (LAND-60) and
    refuses the same contradictory trailer by the same defect sentence,
    exit `2`, before any write -- `checkout._landed_commit_by_sha`'s own
    `workboard.ClassificationDefect` branch."""
    repo = _refused_trailer_repository(monkeypatch, tmp_path, trailer)
    _write_state_ref_pin(repo)
    sha = real_git(repo, "rev-parse", "main").stdout.strip()

    status = issue_claim.main(["release", "20", "--agent", "Codex Sol", "--merged", sha])

    assert status == 2
    err = capsys.readouterr().err
    assert err.startswith(f"ERROR: {sha} carries")


def test_release_merged_empty_refuses_when_no_trunk_commit_names_the_item(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """LAND-47/CI: the empty `--merged` form under state-ref
    refuses by name when no trunk commit's own trailer names this item at
    all -- `checkout._newest_landed_commit`'s own raise, reached before any claim or
    forge read, so every standing claim `_landing_scenario` seeded is still
    exactly as live afterward."""
    _landing_scenario(monkeypatch, tmp_path)

    status = issue_claim.main(["release", "99", "--agent", "Codex Sol", "--merged"])

    assert status == 2
    assert capsys.readouterr().err == (
        "ERROR: no trunk commit carries a Work-Item: trailer naming aco-000063\n"
    )
    remaining = store.fetch_state(worktree=Path("."), remote="origin").claims
    assert len(remaining) == len(_LANDING_ITEM_NUMBERS)


_CLEANUP_BRANCH = "codex/issue-72-cleanup"
_CLEANUP_WORKTREE_NAME = "issue-72-cleanup"


def _release_cleanup_repository(tmp_path: Path, *, merge_into_main: bool = True) -> Path:
    """A real bare-remote-backed repository with `_CLEANUP_BRANCH`
    diverged from `main` by one commit, merged into it through a real merge
    commit unless `merge_into_main` is `False` -- `release --merged`'s own
    cleanup walks real worktrees and a real merge-base ancestry check,
    unlike every other release test in this module, which never builds real
    git state at all."""
    repo, _remote = real_repository_with_bare_remote(tmp_path)
    (repo / "base.txt").write_text("base\n")
    real_git(repo, "add", "base.txt")
    real_git(repo, "commit", "-q", "-m", "initial")
    real_git(repo, "checkout", "-q", "-b", _CLEANUP_BRANCH)
    (repo / "feature.txt").write_text("feature\n")
    real_git(repo, "add", "feature.txt")
    real_git(repo, "commit", "-q", "-m", "feature work")
    real_git(repo, "checkout", "-q", "main")
    if merge_into_main:
        real_git(repo, "merge", "-q", "--no-ff", "-m", "Merge feature", _CLEANUP_BRANCH)
    push_repository_trunk(repo, "origin")
    return repo


def _release_cleanup_scenario(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    merge_into_main: bool = True,
    landed_elsewhere: bool = False,
) -> Path:
    """`repo`'s own would-be lane worktree path -- linked to `_CLEANUP_BRANCH`
    -- a claimed issue #72 on that branch,
    and a merged, closing pull request #12 ready for `release --merged` to
    verify. `landed_elsewhere` merges the branch on the remote alone, from
    another clone, and forgets the recorded `origin/HEAD`, so this checkout
    knows the landing only once it fetches; its trunk
    is then walked for real."""
    repo = _release_cleanup_repository(tmp_path, merge_into_main=merge_into_main)
    merge_commit = MERGE_COMMIT_SHA
    if landed_elsewhere:
        real_git(repo, "push", "-q", "origin", _CLEANUP_BRANCH)
        real_git(repo, "remote", "set-head", "origin", "--delete")
        merge_commit = landed_from_another_clone(
            tmp_path,
            *("merge", "-q", "--no-ff", f"origin/{_CLEANUP_BRANCH}", "-m", "Merge feature"),
            *("-m", f"Work-Item: #{WORK_ITEM_ISSUE}"),
        )
    worktree = repo.parent / f"{repo.name}-worktrees" / _CLEANUP_WORKTREE_NAME
    worktree.parent.mkdir(parents=True)
    real_git(repo, "worktree", "add", "-q", str(worktree), _CLEANUP_BRANCH)
    standing = request(
        "landing", "Ada", issue=WORK_ITEM_ISSUE, branch=_CLEANUP_BRANCH, scope=("src",)
    )
    client = FakeForge()
    client.landings[12] = landing_pull_request(
        body=f"Work-Item: #{WORK_ITEM_ISSUE}\n\nCloses #{WORK_ITEM_ISSUE}",
        merged=True,
        head_ref_name=_CLEANUP_BRANCH,
        merge_commit=merge_commit,
    )
    client.closed_issues.add(WORK_ITEM_ISSUE)
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(board_read, "fetch_issue_reference", _LIVE_FETCH_ISSUE_REFERENCE)
    # This module's own worktree/branch cleanup mechanics, not
    # the merge-commit trailer authority: every scenario below
    # but a landing elsewhere -- including one that never actually merges
    # `_CLEANUP_BRANCH` into `main` -- stubs the walked trunk to authorize
    # closing #72 regardless.
    monkeypatch.setattr(
        checkout,
        "trunk_landings",
        _LIVE_TRUNK_LANDINGS
        if landed_elsewhere
        else lambda *_args, **_kwargs: (
            _trunk_landing(MERGE_COMMIT_SHA, TrunkWorkItemClassification((WORK_ITEM_ISSUE,))),
        ),
    )
    _patch_store_write(monkeypatch, store_claim_from_request(standing))
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Ada"})
    redirect_toplevel(monkeypatch, repo)
    monkeypatch.chdir(repo)
    return worktree


def test_release_merged_survives_an_open_pull_request_with_a_reference_past_the_digit_bound(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    worktree = _release_cleanup_scenario(monkeypatch, tmp_path)
    number = "1" * 4301
    cast(
        FakeForge, github.GitHubForge(github.repository_id(REPOSITORY))
    ).board_open_pull_requests = (
        workboard.PullRequest(300, "Foreign", f"Refs #{number}\n\nsee #{number}", "foreign/branch"),
    )

    assert issue_claim.main(["--repo", REPOSITORY, "release", "72", "--merged", "12"]) == 0

    output = capsys.readouterr().out
    assert output.startswith("RELEASED ")
    assert "\nfreed: " in output
    assert "worktree: removed\n" in output
    assert not worktree.exists()


def _start_from_a_stale_checkout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> object:
    """`start` once the remote's `main` moved on from another clone: the
    exit code, and whether its worktree stands on that remote tip."""
    repo = _start_scenario(monkeypatch, tmp_path)
    real_git(repo, "remote", "set-head", "origin", "--delete")
    remote_tip = landed_from_another_clone(
        tmp_path, "commit", "-q", "--allow-empty", "-m", "landed elsewhere"
    )
    monkeypatch.chdir(repo)
    status = issue_claim.main(["--repo", REPOSITORY, "start", "314"])
    worktree = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    return status, real_git(worktree, "rev-parse", "HEAD").stdout.strip() == remote_tip


def _release_a_merge_the_remote_alone_holds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> object:
    """`release --merged` of a pull request merged on the remote alone: the
    exit code once it verified the new merge commit's trailer, and whether
    the lane worktree it merged is still there."""
    worktree = _release_cleanup_scenario(
        monkeypatch, tmp_path, merge_into_main=False, landed_elsewhere=True
    )
    status = issue_claim.main(["--repo", REPOSITORY, "release", "72", "--merged", "12"])
    return status, worktree.exists()


def _route_a_land_rerun_by_a_merge_the_remote_alone_holds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> object:
    """A rerun of `land` for a pull request merged on the remote alone: the
    item its release routes to, by the new merge commit's own trailer."""
    _release_cleanup_scenario(monkeypatch, tmp_path, merge_into_main=False, landed_elsewhere=True)
    merge_sha = real_git(tmp_path / "remote.git", "rev-parse", "main").stdout.strip()
    return cmd_land._land_release_routing(None, merge_sha, run_context_over(FakeForge()))


@pytest.mark.parametrize(
    ("run_against_a_stale_checkout", "expected"),
    [
        pytest.param(_start_from_a_stale_checkout, (0, True), id="start-builds-on-the-tip"),
        pytest.param(_release_a_merge_the_remote_alone_holds, (0, False), id="release-merged"),
        pytest.param(
            _route_a_land_rerun_by_a_merge_the_remote_alone_holds,
            WORK_ITEM_ISSUE,
            id="land-rerun-routing",
        ),
    ],
)
def test_a_landing_only_the_remote_holds_is_seen_by_every_fetching_trunk_reader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    run_against_a_stale_checkout: Callable[[pytest.MonkeyPatch, Path], object],
    expected: object,
) -> None:
    """Spec: LANDCMD-21, REL-37, REL-38, START-01.
    Against real git: no `origin/HEAD` is recorded
    and this checkout's `main` stands behind a remote that moved on from
    another clone; `start`, `release --merged` and a `land` rerun each read
    the trunk their context fetched, so each sees the remote's landing."""
    assert run_against_a_stale_checkout(monkeypatch, tmp_path) == expected


def _start_under_state_ref(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    _real_state_ref_start_scenario(monkeypatch, tmp_path)
    return ["start", "314", "--scope", "src/x.py"]


def _release_merged_with_cleanup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    _release_cleanup_scenario(monkeypatch, tmp_path)
    return ["--repo", REPOSITORY, "release", "72", "--merged", "12"]


def _release_merged_of_an_open_item(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """`release --merged` of the cleanup scenario with issue #72 still
    open, so a release that reached its forge writes would close it."""
    argv = _release_merged_with_cleanup(monkeypatch, tmp_path)
    client = github.GitHubForge(github.repository_id(REPOSITORY))
    assert isinstance(client, FakeForge)
    client.closed_issues.discard(WORK_ITEM_ISSUE)
    return argv


def _land(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    _land_scenario(monkeypatch, tmp_path)
    return ["--repo", REPOSITORY, "land", "12"]


def _land_rerun(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    _land_with_its_release_failing_once(monkeypatch, tmp_path)
    return ["--repo", REPOSITORY, "land", "12"]


def test_start_fetches_its_trunk_once_and_reads_the_recorded_head_after_the_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Counted at the git launcher: `start`'s claim
    check and build ask the same fetched trunk, so its directory fetches
    once and reads the recorded `HEAD` after that fetch."""
    argv = _start_under_state_ref(monkeypatch, tmp_path)
    trunk_calls = trunk_git_calls(monkeypatch, "origin")

    assert issue_claim.main(argv) == 0
    assert fetched_once_then_read(trunk_calls) == {(tmp_path / "repo").resolve(): True}


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(_release_merged_with_cleanup, id="release-merged-verification-and-cleanup"),
        pytest.param(_land, id="land-fast-forward-and-release"),
        pytest.param(_land_rerun, id="land-rerun-fast-forward-routing-and-release"),
    ],
)
def test_a_github_landing_fetches_once_and_never_asks_the_recorded_head(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    arrange: Callable[[pytest.MonkeyPatch, Path], list[str]],
) -> None:
    """Spec: LANDCMD-21, REL-37, REL-38.
    Counted at the git launcher: every reader of
    one github landing run -- `release --merged`'s merge-commit
    verification, board report and worktree cleanup, `land`'s fast-forward,
    a rerun's routing and its delegated release -- walks the forge's
    default branch on the one fetched canonical remote (LANDCMD-21, REL-37,
    REL-38), so its directory fetches once and never reads the recorded
    `HEAD`."""
    argv = arrange(monkeypatch, tmp_path)
    trunk_calls = trunk_git_calls(monkeypatch, "origin")

    assert issue_claim.main(argv) == 0
    assert trunk_calls == [("fetch", (tmp_path / "repo").resolve())]


def _start_on_github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    monkeypatch.chdir(_start_scenario(monkeypatch, tmp_path))
    return ["--repo", REPOSITORY, "start", "314"]


def _check_the_trunk_tip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    _repo, sha_of = _check_sha(monkeypatch, tmp_path)
    return ["check", sha_of("main")]


def _board_on_github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    monkeypatch.setattr(checkout, "trunk_landings", _LIVE_TRUNK_LANDINGS)
    monkeypatch.chdir(_start_scenario(monkeypatch, tmp_path))
    return ["--repo", REPOSITORY, "board", "--json"]


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(_start_on_github, id="start"),
        pytest.param(_check_the_trunk_tip, id="check"),
        pytest.param(_board_on_github, id="board"),
    ],
)
def test_a_command_resolves_origin_main_past_a_dangling_origin_head(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    arrange: Callable[[pytest.MonkeyPatch, Path], list[str]],
) -> None:
    """Against real git: the remote renamed `master` to
    `main` and `origin/master` is gone, while `origin/HEAD` still names it.
    `start`, `check` and `board` walk `origin/main` as their trunk instead
    of failing on git's own error for a ref it cannot resolve."""
    argv = arrange(monkeypatch, tmp_path)
    dangle_recorded_head(tmp_path / "repo", "origin")

    status = issue_claim.main(argv)

    assert (status, capsys.readouterr().err) == (0, "")


def _ask_git_which_remotes_are_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real git answers whether the checkout configures a remote, never
    `stub_every_remote_configured`'s fake, which says yes to any remote."""
    monkeypatch.setattr(checkout, "unconfigured_remote_refusal", _LIVE_UNCONFIGURED_REMOTE_REFUSAL)


def _name_hub_as_the_canonical_remote(repo: Path) -> None:
    """The board names `hub`, but this clone only ever added `origin`."""
    write_repository_config(repo, 'canonical_remote = "hub"\n')


def _leave_hub_unconfigured(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    _name_hub_as_the_canonical_remote(repo)
    _ask_git_which_remotes_are_configured(monkeypatch)


def _leave_hub_refs_without_a_url(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    """`hub` was fetched with its `HEAD` recorded, then lost its URL: its
    remote-tracking refs outlive it."""
    _leave_hub_unconfigured(monkeypatch, repo)
    real_git(repo, "remote", "add", "hub", str(repo.parent / "remote.git"))
    real_git(repo, "fetch", "-q", "hub")
    real_git(repo, "remote", "set-head", "hub", "main")
    real_git(repo, "config", "--remove-section", "remote.hub")


def _leave_hub_never_added(
    monkeypatch: pytest.MonkeyPatch, repo: Path, _isolated_global_config: Path
) -> None:
    _leave_hub_unconfigured(monkeypatch, repo)


def _leave_hub_a_global_prune_line(
    monkeypatch: pytest.MonkeyPatch, repo: Path, isolated_global_config: Path
) -> None:
    """A global `[remote "hub"] prune = true` makes git list `hub` though
    no configuration gives it a URL, written only into the file
    `isolated_global_git_config` returned -- never the operator's own."""
    _leave_hub_refs_without_a_url(monkeypatch, repo)
    isolated_global_config.write_text('[remote "hub"]\n\tprune = true\n')


def _leave_hub_a_local_fetch_line(
    monkeypatch: pytest.MonkeyPatch, repo: Path, _isolated_global_config: Path
) -> None:
    """A local `remote.hub.fetch` without `remote.hub.url`."""
    _leave_hub_refs_without_a_url(monkeypatch, repo)
    real_git(repo, "config", "remote.hub.fetch", "+refs/heads/*:refs/remotes/hub/*")


_UNCONFIGURED_HUB_SENTENCE = "cannot determine the trunk: canonical remote 'hub' is not configured"
_UNCONFIGURED_HUB = f"ERROR: {_UNCONFIGURED_HUB_SENTENCE}\n"


def _check_an_unpushed_commit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """`check` reads no forge; the served board only lets the scenario
    prove the forge closed nothing."""
    _serve_start_board(monkeypatch, _start_item())
    repo, sha_of = _check_sha(monkeypatch, tmp_path)
    real_git(repo, "commit", "-q", "--allow-empty", "-m", "unpushed", "-m", "Work-Item: #20")
    return ["check", sha_of("HEAD")]


def _claim_in_a_linked_worktree_on_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> list[str]:
    """CLM-01's case: a linked worktree sitting on `main`."""
    repo = _start_scenario(monkeypatch, tmp_path)
    worktree = tmp_path / "lane"
    real_git(repo, "checkout", "-q", "--detach")
    real_git(repo, "worktree", "add", "-q", str(worktree), "main")
    _name_hub_as_the_canonical_remote(worktree)
    redirect_toplevel(monkeypatch, worktree)
    monkeypatch.chdir(worktree)
    return ["--repo", REPOSITORY, "claim", "314", "--scope", "src/x.py"]


def _bootstrap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """`bootstrap` against the real store, which writes `refs/aco/state`
    once it reaches its remote."""
    _start_scenario(monkeypatch, tmp_path)
    return ["bootstrap"]


def _reset_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """`reset` against the real store, which reads its remote's state ref
    first."""
    _start_scenario(monkeypatch, tmp_path)
    return ["reset", "--export-dir", str(tmp_path)]


def _reset_confirmed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """`reset --confirm`, which would also export, delete and bootstrap."""
    return [*_reset_dry_run(monkeypatch, tmp_path), "--confirm"]


@pytest.mark.parametrize(
    ("arrange", "expected_out"),
    [
        pytest.param(_bootstrap, "", id="bootstrap"),
        pytest.param(_reset_dry_run, "", id="reset"),
        pytest.param(_reset_confirmed, "", id="reset-confirm"),
        pytest.param(_start_on_github, "", id="start"),
        pytest.param(_release_merged_of_an_open_item, "", id="release-merged"),
        pytest.param(
            _board_on_github,
            json.dumps(
                {"ok": False, "reason": "unavailable", "message": _UNCONFIGURED_HUB_SENTENCE}
            )
            + "\n",
            id="board-json",
        ),
        pytest.param(_check_an_unpushed_commit, "", id="check-unpushed"),
        pytest.param(_claim_in_a_linked_worktree_on_main, "", id="claim-on-main"),
    ],
)
@pytest.mark.parametrize(
    "unconfigure_hub",
    [
        pytest.param(_leave_hub_never_added, id="never-added"),
        pytest.param(_leave_hub_a_global_prune_line, id="global-prune-without-url"),
        pytest.param(_leave_hub_a_local_fetch_line, id="local-fetch-without-url"),
    ],
)
def test_every_command_names_a_canonical_remote_with_no_url_configured(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    isolated_global_git_config: Path,
    arrange: Callable[[pytest.MonkeyPatch, Path], list[str]],
    expected_out: str,
    unconfigure_hub: Callable[[pytest.MonkeyPatch, Path, Path], None],
) -> None:
    """Spec: BOARD-53, BOOT-04, CHECK-15, CLM-32, REL-39, RESET-18, START-28.

    Against real git: the board names `hub`, which
    this clone never added, so `start`, `release --merged`, `board`,
    `check` and `claim` refuse by naming it rather than fetching nothing or
    reading the local `main` as its trunk -- before any write: no ref
    moves, the claim still stands and the forge closed nothing (START-28,
    REL-39). A `hub` git lists only through a URL-less config line, its
    refs left behind, is not configured either, and `claim`
    names it before its checkout check (CHECK-15, BOARD-53, CLM-32).
    `bootstrap` and `reset`, confirmed or not, refuse in that same sentence rather
    than in git's own transport detail, writing no state ref (BOOT-04, RESET-18)."""
    argv = arrange(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    unconfigure_hub(monkeypatch, repo, isolated_global_git_config)
    refs_before = real_git(repo, "for-each-ref").stdout
    claims_before = store.fetch_state(worktree=repo, remote="hub").claims
    client = github.GitHubForge(github.repository_id(REPOSITORY))
    assert isinstance(client, FakeForge)
    closed_before = set(client.closed_issues)

    status = issue_claim.main(argv)

    printed = capsys.readouterr()
    assert (status, printed.out, printed.err) == (2, expected_out, _UNCONFIGURED_HUB)
    assert real_git(repo, "for-each-ref").stdout == refs_before
    assert store.fetch_state(worktree=repo, remote="hub").claims == claims_before
    assert (client.landing_comments, client.closed_issues) == ({}, closed_before)


def _rename_master_to_trunk(repo: Path, remote: Path, *, keep_recorded_head: bool) -> None:
    """The remote renames `master` to `trunk` after `repo` recorded
    `origin/HEAD` naming it: `fetch --prune` leaves that record dangling,
    or it is deleted when `keep_recorded_head` is false."""
    real_git(repo, "push", "-q", "origin", "master")
    real_git(repo, "remote", "set-head", "origin", "master")
    real_git(remote, "branch", "-m", "master", "trunk")
    real_git(repo, "fetch", "-q", "--prune", "origin")
    if not keep_recorded_head:
        real_git(repo, "remote", "set-head", "origin", "--delete")


def _push_nothing(_repo: Path, _remote: Path) -> None:
    """A fresh remote: it has no branch at all yet."""


_UNRECORDED_TRUNK = (
    "ERROR: cannot determine the trunk: no origin/HEAD, origin/main or origin/master "
    "resolves; run git remote set-head origin -a\n"
)


@pytest.mark.usefixtures("isolated_global_git_config")
@pytest.mark.parametrize(
    ("arrange_remote", "expected_status", "expected_out", "expected_err"),
    [
        pytest.param(
            lambda repo, remote: _rename_master_to_trunk(repo, remote, keep_recorded_head=True),
            2,
            "",
            _UNRECORDED_TRUNK,
            id="renamed-head-dangling",
        ),
        pytest.param(
            lambda repo, remote: _rename_master_to_trunk(repo, remote, keep_recorded_head=False),
            2,
            "",
            _UNRECORDED_TRUNK,
            id="renamed-head-missing",
        ),
        pytest.param(_push_nothing, 0, "{sha} declares No-Item: docs\n", "", id="fresh-remote"),
        pytest.param(
            lambda repo, _remote: _name_hub_as_the_canonical_remote(repo),
            2,
            "",
            _UNCONFIGURED_HUB,
            id="unconfigured-canonical-remote",
        ),
    ],
)
def test_check_never_takes_a_local_branch_for_the_trunk_of_a_remote_with_branches(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    arrange_remote: Callable[[Path, Path], None],
    expected_status: int,
    expected_out: str,
    expected_err: str,
) -> None:
    """Against real git: the remote renamed `master` to
    `trunk` and no resolvable `origin/HEAD` is left, so `check` refuses with
    the set-head repair instead of reporting an unpushed local `master`
    commit as landed; a remote with no branch at all still guesses `master`,
    while a canonical remote the clone never configured is named."""
    monkeypatch.setattr(checkout, "trunk_landings", _LIVE_TRUNK_LANDINGS)
    _ask_git_which_remotes_are_configured(monkeypatch)
    repo, remote = real_repository_with_bare_remote(tmp_path)
    real_git(repo, "commit", "-q", "--allow-empty", "-m", "initial")
    real_git(repo, "branch", "-m", "main", "master")
    arrange_remote(repo, remote)
    real_git(repo, "commit", "-q", "--allow-empty", "-m", "unpushed", "-m", "No-Item: docs")
    sha = real_git(repo, "rev-parse", "HEAD").stdout.strip()
    redirect_toplevel(monkeypatch, repo)
    monkeypatch.chdir(repo)

    status = issue_claim.main(["check", sha])

    printed = capsys.readouterr()
    assert (status, printed.out, printed.err) == (
        expected_status,
        expected_out.format(sha=sha),
        expected_err,
    )


def _land_repository(
    tmp_path: Path,
    *,
    set_head: bool = True,
    branch: str = LANDING_BRANCH,
    board_config: str | None = None,
) -> Path:
    """A real bare-remote-backed repository with `branch`
    diverged from `main` by one pushed commit and `main` itself checked out
    clean -- `aco land`'s own merge, branch deletion, and fast-forward run
    against real git here, the one proof a fake checkout cannot give.
    `set_head=False` skips recording `origin/HEAD`, a checkout where only
    the forge names the default branch. `branch`,
    when it names a lane branch instead of the default `LANDING_BRANCH`,
    stands the real checkout an issue-less (`No-Item:`) land proves against."""
    repo, _remote = real_repository_with_bare_remote(tmp_path)
    (repo / "base.txt").write_text("base\n")
    if board_config is not None:
        write_repository_config(repo, board_config)
        real_git(repo, "add", str(workboard.CONFIG_PATH))
    real_git(repo, "add", "base.txt")
    real_git(repo, "commit", "-q", "-m", "initial")
    if set_head:
        push_repository_trunk(repo, "origin")
    else:
        real_git(repo, "push", "-q", "origin", "main")
    real_git(repo, "checkout", "-q", "-b", branch)
    (repo / "feature.txt").write_text("feature\n")
    real_git(repo, "add", "feature.txt")
    real_git(repo, "commit", "-q", "-m", "feature work")
    real_git(repo, "push", "-q", "origin", branch)
    real_git(repo, "checkout", "-q", "main")
    return repo


def _land_scenario(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    set_head: bool = True,
    claim_agent: str = "Ada",
    branch: str = LANDING_BRANCH,
    issue: int | None = WORK_ITEM_ISSUE,
    body: str | None = None,
    board_config: str | None = None,
) -> tuple[Path, FakeForge]:
    """`claim_agent`, when it differs from the `Ada` session identity set
    below, stands a foreign claim against `land`'s real merge/checkout path, so a
    `--coordinator-override --role coordinator` land of it can be proven
    reaching the merge, not just proven refused without those flags.
    `branch`/`issue`/`body`, when they name an issue-less lane instead of
    the default `Work-Item:` scenario, stand `cmd_land._land_preflight`'s own
    `protocol.LaneIdentity` branch."""
    repo = _land_repository(tmp_path, set_head=set_head, branch=branch, board_config=board_config)
    standing = request("landing", claim_agent, issue=issue, branch=branch, scope=("src",))
    client = FakeForge()
    client.landings[12] = landing_pull_request(
        body=body or f"Work-Item: #{WORK_ITEM_ISSUE}\n\nCloses #{WORK_ITEM_ISSUE}",
        merged=False,
        head_ref_name=branch,
    )
    client.readiness_by_number[12] = landing_readiness()
    client.merge_remote = tmp_path / "remote.git"
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "trunk_landings", _LIVE_TRUNK_LANDINGS)
    _patch_store_write(monkeypatch, store_claim_from_request(standing))
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Ada"})
    redirect_toplevel(monkeypatch, repo)
    monkeypatch.chdir(repo)
    return repo, client


def _land_with_its_release_failing_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, FakeForge, int]:
    """One `aco land` of pull request 12 whose delegated `release --merged`
    a failing close blocked, and its exit code: the merge stands, and
    `close_landed_item` is restored to real so a rerun can succeed."""
    repo, client = _land_scenario(monkeypatch, tmp_path)
    real_close = client.close_landed_item

    def failing_close(number: int, *, pull_request: int) -> None:
        raise ClaimError("forge unreachable (simulated)")

    monkeypatch.setattr(client, "close_landed_item", failing_close)
    status = issue_claim.main(["--repo", REPOSITORY, "land", "12"])
    monkeypatch.setattr(client, "close_landed_item", real_close)
    return repo, client, status


def test_release_abandoned_records_why_the_lane_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")

    assert (
        issue_claim.main(["--repo", REPOSITORY, "release", "72", "--abandoned", "overtaken by #80"])
        == 0
    )

    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


def test_release_abandoned_prints_no_freed_or_next_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An abandoned release never resolves the forge, so it has
    nothing to report a landing freed: `RELEASED` stands alone."""
    merged_release_client(monkeypatch, body="Work-Item: #72\n\nCloses #72")

    exit_code = issue_claim.main(["--repo", REPOSITORY, "release", "72", "--abandoned", "stopped"])

    assert exit_code == 0
    assert capsys.readouterr().out == f"RELEASED issue #{WORK_ITEM_ISSUE}: landing\n"


@pytest.mark.parametrize(
    ("branch", "agent", "override", "explicit", "issue", "outcome_flags", "expected"),
    [
        pytest.param(
            LANE_BRANCH,
            "Ada",
            False,
            True,
            None,
            ("--abandoned", "stopped"),
            0,
            id="docs-abandoned",
        ),
        pytest.param(
            LANE_BRANCH, "Ada", False, True, None, ("--merged", "12"), 0, id="docs-merged"
        ),
        pytest.param("dependabot/x", "Ada", False, True, None, ("--abandoned", "R"), 0, id="1"),
        pytest.param("dependabot/x", "Bob", False, True, None, ("--abandoned", "R"), 2, id="2"),
        pytest.param("dependabot/x", "Bob", True, True, None, ("--abandoned", "R"), 0, id="3"),
        pytest.param("dependabot/x", "Ada", False, False, None, ("--abandoned", "R"), 0, id="4"),
        pytest.param("dependabot/x", "Ada", False, True, 42, ("--abandoned", "R"), 0, id="7"),
    ],
)
def test_release_branch_selects_a_lane_claim_without_checking_out_that_branch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    branch: str,
    agent: str,
    override: bool,
    explicit: bool,
    issue: int | None,
    outcome_flags: tuple[str, str],
    expected: int,
) -> None:
    """An explicit branch lets release proceed even from a deleted or foreign worktree."""
    standing = request("mine", "Ada", issue=issue, branch=branch, scope=("docs",))
    client = FakeForge()
    if outcome_flags[0] == "--merged":
        client.landings[12] = landing_pull_request(
            body="No-Item: docs", merged=True, base_ref_name="main", head_ref_name=branch
        )
        monkeypatch.setattr(
            checkout,
            "trunk_landings",
            lambda *_args, **_kwargs: (
                _trunk_landing(MERGE_COMMIT_SHA, NoItemClassification(NoItemKind.DOCS)),
            ),
        )
    _patch_release_session(
        monkeypatch, client, standing, agent=agent, branch=branch, forbid_git=explicit
    )
    flags = ["--branch", branch] if explicit else []
    if override:
        flags += ["--coordinator-override", "--role", "coordinator"]
    arguments = ["release", *([] if issue is None else [str(issue)]), *flags, *outcome_flags]
    released = issue_claim.main(["--repo", REPOSITORY, *arguments])

    captured = capsys.readouterr()
    assert released == expected
    if expected:
        assert "only the original claimant may release" in captured.err
        assert _live_store_claim().claim_id == "mine"
    else:
        subject = f"issue #{issue}" if issue else f"lane {branch}"
        assert captured.out.startswith(f"RELEASED {subject}: mine\n")
        assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}
        if outcome_flags[0] == "--abandoned":
            assert captured.out == f"RELEASED {subject}: mine\n"


def test_release_branch_selects_a_coordinator_override_from_another_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The headline scenario: naming the lane's own `--branch`
    alongside `--claim-id` for a coordinator-override abandon works from any
    checkout, not only one on the lane branch -- `forbid_git` fails the test
    the moment anything but `rev-parse --show-toplevel` or the trunk's
    recorded `HEAD` reaches git, so a checkout left on another branch
    entirely can never block this release."""
    standing = request(
        "mine", "Ada", issue=None, branch=LANE_BRANCH, role="reviewer", scope=("docs",)
    )
    client = FakeForge()
    _patch_release_session(monkeypatch, client, standing, forbid_git=True)

    released = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "release",
            "--branch",
            LANE_BRANCH,
            "--claim-id",
            "mine",
            "--coordinator-override",
            "--role",
            "coordinator",
            "--abandoned",
            "stopped",
        ]
    )

    assert released == 0
    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


def test_release_refuses_a_branch_and_claim_id_naming_different_claims(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    standing = request("mine", "Ada", issue=72, branch="codex/issue-72-x", scope=("src",))
    client = FakeForge()
    _patch_release_session(monkeypatch, client, standing, forbid_git=True)

    released = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "release",
            "72",
            "--branch",
            "codex/issue-99-other",
            "--claim-id",
            "mine",
            "--abandoned",
            "stopped",
        ]
    )

    assert released == 2
    assert capsys.readouterr().err == (
        "ERROR: --branch 'codex/issue-99-other' and --claim-id 'mine' disagree: the claim's "
        "own branch is 'codex/issue-72-x'; drop --branch or pass its own value\n"
    )
    assert store.fetch_state(worktree=Path("."), remote="origin").claims


@pytest.mark.parametrize(
    "arguments",
    [
        ["release", "42"],
        ["release", "42", "--merged", "12", "--abandoned", "stuck"],
    ],
)
def test_release_requires_exactly_one_landing_outcome(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        issue_claim.main(arguments)

    assert exited.value.code == 2


ARGPARSE_USAGE_REFUSALS = [
    pytest.param(
        ["release", "42"],
        "one of the arguments --merged --abandoned is required",
        id="release-naming-no-outcome",
    ),
    pytest.param(
        ["claim", "42", "--scope", "src", "--nope"],
        "unrecognized arguments: --nope",
        id="claim-carrying-an-unknown-flag",
    ),
    pytest.param(
        ["item", "new"],
        "the following arguments are required: --title",
        id="item-new-missing-its-own-required-flag",
    ),
    pytest.param(
        ["release", "42", "--abandon"],
        "one of the arguments --merged --abandoned is required",
        id="release-abbreviating-its-outcome",
    ),
    pytest.param(["status", "--js"], "unrecognized arguments: --js", id="status-abbreviating-json"),
    pytest.param(
        ["board", "--html"],
        "unrecognized arguments: --html",
        id="board-naming-the-retired-html-flag",
    ),
    pytest.param(
        ["release", "42", "--merged", "--jso"],
        "unrecognized arguments: --jso",
        id="release-abbreviating-json",
    ),
    pytest.param(
        ["item", "new", "--tit", "X"],
        "the following arguments are required: --title",
        id="item-new-abbreviating-its-title",
    ),
]
ABBREVIATED_RESET_FLAGS_REFUSAL = pytest.param(
    ["reset", "--conf", "--f"],
    "unrecognized arguments: --conf --f",
    id="reset-abbreviating-its-destructive-flags",
)
UNREADABLE_ITEM_REFERENCE_REFUSAL = pytest.param(
    ["status", "notanumber"],
    "'notanumber' is not an item reference; use aco-xxxxxx, #n, or the bare number n",
    id="status-naming-an-unreadable-item-reference",
)


@pytest.mark.parametrize(
    ("arguments", "message"), [*ARGPARSE_USAGE_REFUSALS, UNREADABLE_ITEM_REFERENCE_REFUSAL]
)
def test_a_refused_parse_under_json_prints_the_invalid_usage_envelope(
    arguments: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """OUT-06: a `--json` caller reads one object for every
    refusal its command's own parse raises before that command ever runs --
    an outcome flag it requires, a flag it does not know, and a positional
    value its own reader refuses."""
    status = issue_claim.main([*arguments, "--json"])

    captured = capsys.readouterr()
    assert status == 2
    assert json.loads(captured.out) == {
        "ok": False,
        "reason": "invalid_usage",
        "message": message,
    }
    assert captured.err == f"ERROR: {message}\n"


@pytest.mark.parametrize(
    ("arguments", "message"), [*ARGPARSE_USAGE_REFUSALS, ABBREVIATED_RESET_FLAGS_REFUSAL]
)
def test_a_refused_parse_without_json_keeps_the_usage_text(
    arguments: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """OUT-06's own Never clause: without `--json` the parser's refusal is
    still argparse's own usage block and sentence on stderr, exit `2`, with
    stdout untouched. An abbreviated option is one such refusal (OUT-09):
    `reset --conf --f` never stands for `--confirm --force-unreadable`, and
    `--jso` never asks for the envelope."""
    with pytest.raises(SystemExit) as exited:
        issue_claim.main(arguments)

    captured = capsys.readouterr()
    assert exited.value.code == 2
    assert captured.out == ""
    assert captured.err.startswith("usage: aco")
    assert captured.err.endswith(f"error: {message}\n")


def test_a_bad_choice_on_a_json_command_prints_the_invalid_usage_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A value outside an option's own `choices` is one more refusal the
    parser raises, and `brief` declares `--json`, so it reports
    through OUT-06 like every other one. The sentence is argparse's own,
    read back off stderr rather than spelled out here: its choice list is
    argparse's wording, not this contract's."""
    status = issue_claim.main(["brief", "42", "--step", "nope", "--json"])

    captured = capsys.readouterr()
    assert status == 2
    assert "argument --step: invalid choice:" in captured.err
    _assert_json_refusal_object(captured.err, captured.out, reason="invalid_usage")


@pytest.mark.parametrize(
    ("arguments", "envelope"),
    [
        pytest.param(
            ["status", "--json", "--", "--nope"], True, id="json-before-the-commands-own-dash-dash"
        ),
        pytest.param(
            ["status", "--", "--json"], False, id="json-behind-the-commands-own-dash-dash"
        ),
    ],
)
def test_a_dash_dash_ends_the_options_of_its_own_level_only(
    arguments: list[str], envelope: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    """A `--` ends the options of the parser level that reads it and of no
    other: `status --json -- --nope` still asked for the
    envelope, while behind `status`'s own `--` the very same spelling is
    just the item reference `status` refuses. Both refusals are `status`'s
    own item reader, so the tokens alone never decide the shape."""
    status = issue_claim.main(arguments)

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err.startswith("ERROR: ")
    if envelope:
        _assert_json_refusal_object(captured.err, captured.out, reason="invalid_usage")
    else:
        assert captured.out == ""


def _stock_argparse_reads_a_dash_dash_as_the_command_name() -> bool:
    """Ask this interpreter's own argparse what a leading `--` becomes before
    a subcommand action: the command name, or nothing at all. CPython changed
    that within a release series, so the answer is measured rather than read
    off a version number."""
    parser = argparse.ArgumentParser(prog="oracle", add_help=False)
    parser.add_subparsers(dest="command", required=True).add_parser("status")

    with contextlib.redirect_stderr(io.StringIO()):
        try:
            parser.parse_args(["--", "status"])
        except SystemExit:
            return True
    return False


def test_a_dash_dash_before_the_command_follows_the_parse_argparse_made(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The mode follows the parse argparse actually made, never the raw
    tokens. Where this interpreter's argparse drops a leading
    `--` before the subcommand action, `status` is chosen and reads the
    `--json` behind it -- the envelope; where that `--` reaches the action it
    is the command name nobody declares, so no command was ever chosen that
    could declare the flag. Which of the two a CPython release does is a
    change in argparse itself, so the oracle above measures it here."""
    arguments = ["--", "status", "--json", "--nope"]

    if _stock_argparse_reads_a_dash_dash_as_the_command_name():
        with pytest.raises(SystemExit) as refused:
            issue_claim.main(arguments)
        assert refused.value.code == 2
        assert capsys.readouterr().out == ""
        return

    status = issue_claim.main(arguments)

    captured = capsys.readouterr()
    assert status == 2
    _assert_json_refusal_object(captured.err, captured.out, reason="invalid_usage")


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param(["bootstrap", "--json"], id="bootstrap-declaring-no-json-mode"),
        pytest.param(["item", "--json"], id="item-naming-no-subcommand"),
        pytest.param(["nope", "--json"], id="a-command-name-the-parser-does-not-know"),
        pytest.param(["--json"], id="no-command-at-all"),
    ],
)
def test_a_json_flag_no_command_declares_never_reaches_the_envelope(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """OUT-06's envelope belongs to the commands that declare `--json`:
    `bootstrap` never offered the mode, and a
    missing subcommand, an unknown command name, or no command at all never
    chose one, so each keeps argparse's own usage block with stdout empty --
    no object a script could mistake for an answer."""
    with pytest.raises(SystemExit) as exited:
        issue_claim.main(arguments)

    captured = capsys.readouterr()
    assert exited.value.code == 2
    assert captured.out == ""
    assert captured.err.startswith("usage: aco")


def test_a_parse_without_arguments_reads_the_process_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parser handed no arguments parses `sys.argv[1:]`, as argparse does,
    so the refusal names the unknown flag rather than a missing command."""
    parser = issue_claim._parser()
    monkeypatch.setattr(sys, "argv", ["aco", "status", "--json", "--nope"])

    with pytest.raises(issue_claim.usage.UsageError) as refused:
        parser.parse_args()

    assert str(refused.value) == "unrecognized arguments: --nope"


@pytest.mark.parametrize(
    ("earlier", "later", "asked_for_json"),
    [
        pytest.param(
            ["bootstrap", "--json"],
            ["status", "--json", "--nope"],
            True,
            id="another-command",
        ),
        pytest.param(
            ["item", "show", "--json"],
            ["item", "--json"],
            False,
            id="a-command-whose-subcommand-is-missing",
        ),
    ],
)
def test_a_reused_parser_reports_only_the_command_of_its_latest_parse(
    earlier: list[str], later: list[str], asked_for_json: bool
) -> None:
    """Descendant state from an earlier refused parse must not leak into the
    next one, or its `--json` would be read off the wrong command."""
    parser = issue_claim._parser()
    with pytest.raises(issue_claim.usage.UsageError):
        parser.parse_args(earlier)
    with pytest.raises(issue_claim.usage.UsageError):
        parser.parse_args(later)

    assert issue_claim._asked_for_json(parser, later) is asked_for_json


def test_every_item_or_json_argument_is_recorded_as_declared() -> None:
    """A refused parse reads `--json` and item references only from
    `declared_actions`; an argument added through an argparse group bypasses
    it, so a future grouped one must fail here rather than go unseen."""
    unrecorded = [
        f"{each.prog} {action.dest}"
        for each in _every_parser(issue_claim._parser())
        for action in each._actions
        if (
            report.JSON_FLAG in action.option_strings
            or action.type in issue_claim._ITEM_ARGUMENT_TYPES
        )
        and action not in cast(issue_claim.usage.UsageErrorParser, each).declared_actions
    ]

    assert unrecorded == []


def test_next_names_a_recovery_item_before_the_item_it_recommends(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    landed = board_issue(90, "Landed but open", complete_contract("Close it."))
    ready = board_issue(91, "Waiting work", complete_contract("Claim #91."))
    client = _configured_board_client(monkeypatch, tmp_path, open_issues=(landed, ready))
    monkeypatch.setattr(
        client,
        "list_recent_merged_board_pull_requests",
        lambda _since: (
            workboard.PullRequest(
                140,
                "Lands it",
                "Work-Item: #90\n\nCloses #90",
                "branch",
                "2026-08-20T00:00:00Z",
            ),
        ),
    )

    assert issue_claim.main(["--repo", REPOSITORY, "next"]) == 0
    assert capsys.readouterr().out.startswith(f"RECOVERY\n#90: {workboard.RECOVERY_STEP}\n\n")


CHECKED_ISSUE = 81


def open_dependency(number: int, repository: str = REPOSITORY) -> IssueDependency:
    return IssueDependency(workboard.IssueReference(repository, number), BlockerState.OPEN, False)


def _check_trunk_repository(tmp_path: Path) -> Path:
    """Real classified trunk and a separate side branch for cross-command checks."""
    repo = bare_remote_repository_with_one_commit(tmp_path)
    (repo / "work.txt").write_text("work\n")
    real_git(repo, "add", "work.txt")
    real_git(repo, "commit", "-q", "-m", "work item change", "-m", "Work-Item: #20")
    (repo / "docs.txt").write_text("docs\n")
    real_git(repo, "add", "docs.txt")
    real_git(repo, "commit", "-q", "-m", "docs change", "-m", "No-Item: docs")
    real_git(
        repo, "commit", "-q", "--allow-empty", "-m", "dependency update", "-m", "No-Item: deps"
    )
    push_repository_trunk(repo, "origin")
    real_git(repo, "checkout", "-q", "-b", "side")
    (repo / "side.txt").write_text("side\n")
    real_git(repo, "add", "side.txt")
    real_git(repo, "commit", "-q", "-m", "side change", "-m", "Work-Item: #21")
    real_git(repo, "checkout", "-q", "main")
    return repo


def _check_sha(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Callable[[str], str]]:
    """Real history and its resolver for trunk-tip and unpushed-commit checks."""
    monkeypatch.setattr(checkout, "trunk_landings", _LIVE_TRUNK_LANDINGS)
    repo = _check_trunk_repository(tmp_path)
    redirect_toplevel(monkeypatch, repo)
    monkeypatch.chdir(repo)
    return repo, lambda ref: real_git(repo, "rev-parse", ref).stdout.strip()


def test_issue_check_labels_a_local_blocker_under_the_state_ref_pin() -> None:
    """`cmd_check._issue_check` reads the repository's
    own `storage` pin for a local blocker exactly as `claim`'s
    `cmd_claim._blocked_check` does -- a foreign one (`other/repo#9`) is unaffected,
    since it is never local to this repository's own storage pin
    (`workboard.open_blocker_label`)."""
    client = FakeForge(
        board_dependencies={CHECKED_ISSUE: (open_dependency(7), open_dependency(9, "other/repo"))}
    )

    outcome = cmd_check._issue_check(
        client,
        REPOSITORY,
        block_body(MINIMAL_BLOCK_TOML),
        CHECKED_ISSUE,
        storage=body.Storage.STATE_REF,
    )

    checked_label = workboard.item_label(CHECKED_ISSUE, body.Storage.STATE_REF)
    local_label = workboard.item_label(7, body.Storage.STATE_REF)
    assert outcome.line == f"ISSUE {checked_label} blocked by {local_label}, other/repo#9"


@pytest.mark.parametrize(
    "json_flag", [pytest.param(False, id="without-json"), pytest.param(True, id="with-json")]
)
def test_cli_claim_refuses_a_missing_state_ref(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], json_flag: bool
) -> None:
    """A missing `refs/aco/state`: with `--json`, the stdout
    envelope names the unchanged stderr sentence under `reason: unavailable`;
    without it, stdout stays exactly as empty as it always
    has."""
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    git_values = git_checkout()
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    _patch_store_write(monkeypatch, tip=None)

    arguments = [
        "--repo",
        REPOSITORY,
        "claim",
        "72",
        "--agent",
        "Ada",
        "--base",
        BASE,
        "--branch",
        "codex/issue-72",
        "--scope",
        "src",
        "--claim-id",
        "cli-claim",
    ]
    if json_flag:
        arguments.append("--json")

    status = issue_claim.main(arguments)

    captured = capsys.readouterr()
    assert status == 2
    assert protocol.MISSING_STATE_REF in captured.err
    if json_flag:
        _assert_json_refusal_object(captured.err, captured.out, reason="unavailable")
    else:
        assert captured.out == ""


def test_cli_claim_refuses_canonical_remote_mismatch_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    git_values = git_checkout()
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    fake = _patch_store_write(monkeypatch)
    monkeypatch.setattr(
        checkout, "remote_url", lambda remote, **_kwargs: "git@github.com:other/repo.git"
    )

    status = issue_claim.main(
        [
            "--repo",
            REPOSITORY,
            "claim",
            "72",
            "--agent",
            "Ada",
            "--base",
            BASE,
            "--branch",
            "codex/issue-72",
            "--scope",
            "src",
            "--claim-id",
            "cli-claim",
        ]
    )

    assert status == 2
    assert "forge target example/agent-coordination does not match canonical remote other/repo" in (
        capsys.readouterr().err
    )
    assert fake.transitions == []


def test_cli_rescope_refuses_a_missing_state_ref(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    git_values = git_checkout()
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
    _patch_store_write(monkeypatch, tip=None)

    status = issue_claim.main(["--repo", REPOSITORY, "rescope", "72", "--add", "/repo/src/new.py"])

    assert status == 2
    assert protocol.MISSING_STATE_REF in capsys.readouterr().err


def test_cli_release_refuses_a_missing_state_ref(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    standing = request("mine", "Ada", issue=72, branch="lane-72", scope=("src",))
    client = FakeForge()
    _patch_release_session(monkeypatch, client, standing)
    _patch_store_write(monkeypatch, tip=None)

    status = issue_claim.main(["--repo", REPOSITORY, "release", "72", "--abandoned", "stopped"])

    assert status == 2
    assert protocol.MISSING_STATE_REF in capsys.readouterr().err


# Lazy forge: a forge-free command never resolves a repository,
# reads a remote's own URL, or calls `gh` -- proven here against a bare
# `file://` canonical remote (the shape a repository with no forge adapter at
# all still uses for its state ref) with `discover_repository`/`GitHubForge`
# and `checkout.remote_url` all forbidden outright, never merely absent.


def test_cli_lane_claim_rescope_and_release_are_forge_free_against_a_non_github_remote(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A lane `claim`/`rescope`/`release` never resolves a forge target:
    the round trip below runs entirely against a `file://`
    canonical remote with the forge and the remote's own URL both forbidden,
    and still claims, rescopes, and releases."""
    set_agent_identity_env(monkeypatch, {"ACO_AGENT": "Codex Sol"})
    monkeypatch.setattr(
        checkout,
        "versioned_paths",
        lambda **_kwargs: (
            "LICENSE",
            "README.md",
            "pyproject.toml",
            "src/aco/__init__.py",
        ),
    )
    monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    # `rescope` fetches and commits real store state against its resolved
    # checkout's own toplevel -- unlike
    # `claim`'s cwd-based store observation above, still unaffected by this
    # fix, this fake toplevel must therefore be a real directory the test's
    # own real `store.fetch_state`/`commit_transition` calls can `-C` into,
    # not the placeholder `"/repo"` every other checkout fact below stays.
    real_toplevel = str(Path.cwd())
    git_values = {
        ("branch", "--show-current"): "docs/lane-cleanup",
        ("rev-parse", "--show-toplevel"): real_toplevel,
        ("rev-parse", "HEAD"): BASE,
        ("rev-parse", "--verify", "--quiet", "HEAD"): BASE,
        ("rev-parse", "--git-dir"): "/repo/.git/worktrees/lane-cleanup",
        ("rev-parse", "--git-common-dir"): "/repo/.git",
        # `rescope`'s path-based checkout resolution: the same
        # toplevel/git-dir/common-dir facts above, combined in the one call
        # `resolve_path_checkout` actually sends.
        (
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
            "--git-dir",
            "--git-common-dir",
        ): f"{real_toplevel}\n/repo/.git/worktrees/lane-cleanup\n/repo/.git",
        RECORDED_ORIGIN_HEAD_READ: "refs/remotes/origin/main",
    }
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    forbid_forge_resolution(monkeypatch)

    claimed = issue_claim.main(
        [
            "claim",
            "--role",
            "builder",
            "--base",
            BASE,
            "--branch",
            "docs/lane-cleanup",
            "--scope",
            "docs",
            "--claim-id",
            "cli-lane-claim",
        ]
    )
    assert claimed == 0
    capsys.readouterr()

    rescoped = issue_claim.main(["rescope", "--add", f"{real_toplevel}/README.md"])
    assert rescoped == 0
    lane_key = protocol.claim_key(protocol.LaneIdentity(), "docs/lane-cleanup")
    assert store.fetch_state(worktree=Path("."), remote="origin").claims[lane_key].scope == (
        "README.md",
        "docs",
    )
    capsys.readouterr()

    released = issue_claim.main(["release", "--abandoned", "stopped"])
    assert released == 0
    assert store.fetch_state(worktree=Path("."), remote="origin").claims == {}


def test_cli_board_refuses_a_non_github_canonical_remote_by_host(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`board` is a forge command: a canonical remote on any
    host but GitHub refuses by that host's own name, before ever calling
    `github.discover_repository`/`gh` -- never the store-blind path a forge-free
    command like `status` takes for the same remote, and never GitHub's own
    "does not name a GitHub repository" text."""
    monkeypatch.setattr(
        checkout, "remote_url", lambda remote, **_kwargs: "file:///srv/git/agent-coordination.git"
    )

    def unused(*_args: object, **_kwargs: object) -> forge.RepositoryId:
        pytest.fail("board must refuse the host before ever calling discover_repository")

    monkeypatch.setattr(github, "discover_repository", unused)

    status = issue_claim.main(["board", "--json"])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == "ERROR: no forge adapter for host file\n"


_UNTRACKED_BOARD_CONFIG_ERROR = (
    "ERROR: .aco/board.toml is not tracked in this checkout, so its "
    "storage pin cannot be trusted: git add -f .aco/board.toml\n"
)
_MISSING_BOARD_CONFIG_ERROR = (
    "ERROR: .aco/board.toml does not exist in this checkout; merge a pull request "
    "adding only .aco/board.toml into the default branch first, without aco "
    "(fetch first if the default branch may already carry it)\n"
)


def _write_untracked_board_config(toplevel: Path) -> None:
    write_repository_config(toplevel)


@pytest.mark.parametrize(
    ("config_on_disk", "refusal"),
    [
        pytest.param(False, _MISSING_BOARD_CONFIG_ERROR, id="missing"),
        pytest.param(True, _UNTRACKED_BOARD_CONFIG_ERROR, id="present-untracked"),
    ],
)
@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param(["bootstrap"], id="bootstrap"),
        pytest.param(["board", "--json"], id="board"),
        pytest.param(["claim", "1", "--scope", "README.md"], id="claim-ahead-of-clm-01"),
        pytest.param(["--repo", REPOSITORY, "land", "12"], id="land"),
    ],
)
def test_an_untrusted_board_config_refuses_every_store_command_by_name(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    arguments: list[str],
    config_on_disk: bool,
    refusal: str,
) -> None:
    """A `.aco/board.toml` that is not tracked
    never reads as `storage = "github"`'s silent default -- every store
    command, `land` included, refuses before any other work and writes
    nothing. A file present but untracked or ignored names the `git add -f`
    repair (PIN-01); a file absent altogether names the one-time adoption
    instead (PIN-32). `claim` in the main checkout on `main` refuses it
    ahead of CLM-01, since only the configuration names the canonical remote
    whose recorded default branch CLM-01 judges (CLM-30)."""
    repository, remote = real_repository_with_bare_remote(tmp_path)
    (repository / "README.md").write_text("hello\n")
    real_git(repository, "add", "README.md")
    real_git(repository, "commit", "-q", "-m", "initial")
    push_repository_trunk(repository, "origin")
    if config_on_disk:
        _write_untracked_board_config(repository)
    redirect_toplevel(monkeypatch, repository)
    monkeypatch.chdir(repository)
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Ada"})
    monkeypatch.setattr(checkout, "path_is_tracked", lambda _path, **_kwargs: False)

    status = issue_claim.main(arguments)

    assert (status, capsys.readouterr().err) == (2, refusal)
    assert real_git(remote, "for-each-ref", "refs/aco").stdout == ""


@dataclass(frozen=True)
class _AbsentPinLane:
    """How a lane worktree without `.aco/board.toml` came to be
    (PIN-32): whether `main` gained the adoption commit after `lane` was
    cut, how `origin` carries `main`, whether this clone's fetch of it
    predates the adoption, whether `lane` merged `origin/main` and then
    ran `git rm` on the file, and whether a newer `main` was fetched after
    that."""

    adopted: bool = True
    trunk_resolves: bool = True
    origin_kept: bool = True
    fetch_is_stale: bool = False
    merged_then_removed: bool = False
    trunk_moved_on: bool = False


_RESTORE_BOARD_CONFIG_ERROR = (
    "ERROR: .aco/board.toml was removed on this branch; restore it with "
    "git checkout origin/main -- :/.aco/board.toml\n"
)


def _run_printed_restore_from_a_subdirectory(refusal: str, lane: Path) -> None:
    """Runs the command PIN-32's removal sentence prints, verbatim, from a
    directory below the checkout's root."""
    subdirectory = lane / "docs"
    subdirectory.mkdir()
    printed_command = refusal.split("restore it with ", 1)[1]
    real_git(subdirectory, *shlex.split(printed_command)[1:])


def _advance_origin_main(repository: Path, lane: Path) -> None:
    (repository / "later.txt").write_text("later\n")
    real_git(repository, "add", "later.txt")
    real_git(repository, "commit", "-q", "-m", "later trunk work")
    push_repository_trunk(repository, "origin")
    real_git(lane, "fetch", "-q", "origin")


@pytest.mark.parametrize(
    ("lane_history", "refusal"),
    [
        pytest.param(
            _AbsentPinLane(),
            "ERROR: .aco/board.toml does not exist in this checkout, but origin/main "
            "tracks it; merge origin/main into this branch\n",
            id="trunk-adopted-after-the-cut",
        ),
        pytest.param(
            _AbsentPinLane(merged_then_removed=True),
            _RESTORE_BOARD_CONFIG_ERROR,
            id="removed-after-merging-the-trunk",
        ),
        pytest.param(
            _AbsentPinLane(merged_then_removed=True, trunk_moved_on=True),
            _RESTORE_BOARD_CONFIG_ERROR,
            id="removed-after-merging-then-a-newer-trunk-fetched",
        ),
        pytest.param(
            _AbsentPinLane(adopted=False), _MISSING_BOARD_CONFIG_ERROR, id="never-adopted"
        ),
        pytest.param(
            _AbsentPinLane(fetch_is_stale=True),
            _MISSING_BOARD_CONFIG_ERROR,
            id="adoption-not-fetched-yet",
        ),
        pytest.param(
            _AbsentPinLane(origin_kept=False),
            "ERROR: cannot determine the trunk: canonical remote 'origin' is not configured\n",
            id="origin-unconfigured",
        ),
        pytest.param(
            _AbsentPinLane(adopted=False, trunk_resolves=False),
            _MISSING_BOARD_CONFIG_ERROR,
            id="never-adopted-trunk-unresolved",
        ),
    ],
)
def test_a_checkout_without_the_pin_is_told_its_pin_32_repair(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    isolated_global_git_config: Path,
    lane_history: _AbsentPinLane,
    refusal: str,
) -> None:
    """A lane worktree whose branch was cut before the adoption
    commit lacks `.aco/board.toml` although the trunk tracks it, so
    PIN-32 refuses its merge sentence, never its adoption sentence; a lane
    that merged the trunk and then removed the file is told to restore it
    instead, also once a newer trunk is fetched, since the merge
    base still tracks the file, and following that sentence
    brings the file back, run from a subdirectory. With no
    ref tracking it the adoption sentence stands -- also when the trunk does
    not resolve, a `trunk` branch pushed without `origin/HEAD`, or when this
    clone's fetch predates the adoption, which the sentence's parenthesis
    names -- and an unconfigured canonical remote keeps
    CHECK-15's sentence. Nothing is written."""
    repository, remote = real_repository_with_bare_remote(tmp_path)
    (repository / "README.md").write_text("hello\n")
    real_git(repository, "add", "README.md")
    real_git(repository, "commit", "-q", "-m", "initial")
    real_git(repository, "branch", "lane")
    if lane_history.adopted:
        _write_untracked_board_config(repository)
        real_git(repository, "add", workboard.CONFIG_PATH.as_posix())
        real_git(repository, "commit", "-q", "-m", "adopt aco")
    if lane_history.trunk_resolves:
        push_repository_trunk(repository, "origin")
    else:
        real_git(repository, "push", "-q", "origin", "main:trunk")
    if lane_history.fetch_is_stale:
        real_git(repository, "update-ref", "refs/remotes/origin/main", "main~1")
    if not lane_history.origin_kept:
        real_git(repository, "remote", "remove", "origin")
    lane = tmp_path / "lane"
    real_git(repository, "worktree", "add", "-q", str(lane), "lane")
    if lane_history.merged_then_removed:
        real_git(lane, "merge", "-q", "origin/main")
        real_git(lane, "rm", "-q", workboard.CONFIG_PATH.as_posix())
        real_git(lane, "commit", "-q", "-m", "drop the pin")
    if lane_history.trunk_moved_on:
        _advance_origin_main(repository, lane)
    redirect_toplevel(monkeypatch, lane)
    monkeypatch.chdir(lane)
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Ada"})
    monkeypatch.setattr(checkout, "path_is_tracked", _LIVE_PATH_IS_TRACKED)
    _ask_git_which_remotes_are_configured(monkeypatch)

    status = issue_claim.main(["claim", "1", "--scope", "README.md"])

    assert (status, capsys.readouterr().err) == (2, refusal)
    assert real_git(remote, "for-each-ref", "refs/aco").stdout == ""
    if refusal == _RESTORE_BOARD_CONFIG_ERROR:
        _run_printed_restore_from_a_subdirectory(refusal, lane)
        tracked = real_git(lane, "ls-files", workboard.CONFIG_PATH.as_posix()).stdout
        assert tracked == f"{workboard.CONFIG_PATH.as_posix()}\n"


@pytest.mark.parametrize("item", ["5", "16777216"], ids=["in-the-id-space", "past-the-id-space"])
def test_untracked_board_config_refuses_item_show_in_its_own_json_envelope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    item: str,
) -> None:
    """ITEM-17: an untracked pin is `item show`'s own
    `precondition_failed` refusal under `--json` whatever number it names --
    PIN-31's guard reads no pin it cannot trust, so it never takes the
    refusal from the command."""
    _write_untracked_board_config(tmp_path)
    monkeypatch.setattr(checkout, "path_is_tracked", lambda _path, **_kwargs: False)

    status = issue_claim.main(["item", "show", item, "--json"])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == _UNTRACKED_BOARD_CONFIG_ERROR
    _assert_json_refusal_object(captured.err, captured.out, reason="precondition_failed")


def _scratch_lane_repository(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, board_config: str | None = None
) -> tuple[Path, str, str]:
    """A repository with a base commit on `main` and a lane branch one commit
    ahead of it -- `brief`'s own real reads (`rev-parse --verify`, `diff
    --name-only`) run against real git history here, never a hand-typed
    `git_output` fake. It is the isolated toplevel itself (`conftest.py`'s
    `_isolate_git_toplevel`), so the run's context resolves its trunk -- the
    local `main`, since its configured `origin` was never fetched -- in the
    lane's own repository. Given `board_config`, the
    base commit carries it as the trunk's `.aco/board.toml`."""
    monkeypatch.setattr(checkout, "trunk_ref_after", LIVE_TRUNK_REF_AFTER)
    repository = tmp_path
    real_git(repository, "init", "-q", "-b", "main")
    real_git(repository, "remote", "add", "origin", str(tmp_path / "origin.git"))
    real_git(repository, "config", "user.name", "Test")
    real_git(repository, "config", "user.email", "test@example.com")
    (repository / "README.md").write_text("hello\n")
    real_git(repository, "add", "README.md")
    if board_config is not None:
        write_repository_config(repository, board_config)
        real_git(repository, "add", "-f", workboard.CONFIG_PATH.as_posix())
    real_git(repository, "commit", "-q", "-m", "initial")
    base = real_git(repository, "rev-parse", "HEAD").stdout.strip()
    real_git(repository, "checkout", "-q", "-b", "codex/issue-258-brief")
    (repository / "README.md").write_text("hello\nbrief\n")
    real_git(repository, "add", "README.md")
    real_git(repository, "commit", "-q", "-m", "lane work")
    tip = real_git(repository, "rev-parse", "HEAD").stdout.strip()
    return repository, base, tip


def _brief_claim(
    base: str, *, branch: str = "codex/issue-258-brief", whole_reason: str | None = None
) -> protocol.ActiveClaim:
    return store_claim_from_request(
        replace(
            request(
                issue=258,
                claim_id="brief-claim",
                branch=branch,
                scope=("README.md",),
                whole_reason=whole_reason,
            ),
            base=base,
        )
    )


def test_cli_brief_prints_body_claim_lane_tip_and_touched_files(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    repository, base, tip = _scratch_lane_repository(
        monkeypatch, tmp_path, board_config='lane_shared = ["scripts/registry.txt"]\n'
    )
    (repository / workboard.CONFIG_PATH).write_text(
        'lane_shared = ["scripts/registry.txt", "src/x.py"]\n'
    )
    monkeypatch.setattr(checkout, "file_at_revision", _LIVE_FILE_AT_REVISION)
    client = FakeForge()
    client.issue_references[258] = forge.ItemReference(
        forge.ItemState.OPEN, "Brief", "The item's own body."
    )
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    claim = _brief_claim(base, whole_reason="lane touches too much to split")
    _patch_store_write(monkeypatch, claim, ages={claim.claim_id: datetime(2026, 8, 20, tzinfo=UTC)})
    monkeypatch.chdir(repository)

    status = issue_claim.main(["--repo", REPOSITORY, "brief", "258"])

    assert status == 0
    assert capsys.readouterr().out.splitlines() == [
        "The item's own body.",
        "",
        "CLAIM",
        f"Codex Sol (builder) branch=codex/issue-258-brief base={base} 24h 0m old",
        "  README.md",
        "  whole: lane touches too much to split",
        "  lane-shared: scripts/registry.txt (names no file)",
        "",
        "TIP",
        tip,
        "",
        "TOUCHED",
        "README.md",
    ]


@pytest.mark.parametrize(("inject", "message"), GIT_FAILURE_INJECTIONS)
def test_cli_brief_refuses_with_gits_text_when_reading_the_remote_head_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    inject: Callable[[pytest.MonkeyPatch, list[str]], list[list[str]]],
    message: str,
) -> None:
    """A failed read of `<remote>/HEAD` reaches the real reader and refuses
    with git's own text, never guessing a trunk or printing `cannot resolve
    the default branch`."""
    repository, _base, _tip = _scratch_lane_repository(monkeypatch, tmp_path)
    client = FakeForge()
    client.issue_references[258] = forge.ItemReference(forge.ItemState.OPEN, "Brief", "Body.")
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    monkeypatch.chdir(repository)
    injected = inject(monkeypatch, list(recorded_head_read("origin")))

    status = issue_claim.main(["--repo", REPOSITORY, "brief", "258"])

    assert injected
    assert status == 2
    assert capsys.readouterr().err.splitlines() == [f"ERROR: {message}"]


def test_cli_brief_reports_no_active_claim_with_empty_tip_and_touched_files(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    repository, _base, _tip = _scratch_lane_repository(monkeypatch, tmp_path)
    client = FakeForge()
    client.issue_references[258] = forge.ItemReference(
        forge.ItemState.OPEN, "Brief", "No claim yet."
    )
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    other_items_claim = store_claim_from_request(request(issue=259, claim_id="other-claim"))
    _patch_store_write(monkeypatch, other_items_claim)
    monkeypatch.chdir(repository)

    status = issue_claim.main(["--repo", REPOSITORY, "brief", "258"])

    assert status == 0
    assert capsys.readouterr().out.splitlines() == [
        "No claim yet.",
        "",
        "CLAIM",
        "no active claim",
        "",
        "TIP",
        "",
        "TOUCHED",
    ]


def test_cli_brief_reports_branch_not_found_when_the_claim_branch_is_gone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    repository, base, _tip = _scratch_lane_repository(monkeypatch, tmp_path)
    client = FakeForge()
    client.issue_references[258] = forge.ItemReference(forge.ItemState.OPEN, "Brief", "Gone lane.")
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    claim = _brief_claim(base, branch="codex/issue-258-gone")
    _patch_store_write(monkeypatch, claim, ages={claim.claim_id: datetime(2026, 8, 20, tzinfo=UTC)})
    monkeypatch.chdir(repository)

    status = issue_claim.main(["--repo", REPOSITORY, "brief", "258"])

    assert status == 0
    assert capsys.readouterr().out.splitlines() == [
        "Gone lane.",
        "",
        "CLAIM",
        f"Codex Sol (builder) branch=codex/issue-258-gone base={base} 24h 0m old",
        "  README.md",
        "",
        "TIP",
        "branch not found",
        "",
        "TOUCHED",
    ]


def _unreadable_item_reference(_number: int) -> forge.ItemReference:
    raise ClaimError("simulated forge read failure")


def test_cli_brief_refuses_when_the_lane_tip_read_fails_outright(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """`rev-parse --verify --quiet`'s exit `1` is the
    one documented "does not resolve" outcome; any other nonzero exit --
    here, a simulated broken git -- is a tool failure, not a missing
    branch, and must refuse instead of printing `branch not found`."""
    repository, base, _tip = _scratch_lane_repository(monkeypatch, tmp_path)
    client = FakeForge()
    client.issue_references[258] = forge.ItemReference(forge.ItemState.OPEN, "Brief", "Broken git.")
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    claim = _brief_claim(base)
    _patch_store_write(monkeypatch, claim, ages={claim.claim_id: datetime(2026, 8, 20, tzinfo=UTC)})
    monkeypatch.chdir(repository)
    stub_one_git_call(
        monkeypatch,
        ["rev-parse", "--verify", "--quiet", claim.branch],
        exit_status=128,
        stderr="simulated git failure",
    )

    status = issue_claim.main(["--repo", REPOSITORY, "brief", "258"])

    assert status == 2
    assert capsys.readouterr().err == "ERROR: simulated git failure\n"


def test_cli_brief_json_names_a_failing_item_read_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """BRIEF-19: the item read is a forge call like any other,
    so a failure there is this command's own `unavailable`. It used to escape
    the handler and leave a `--json` caller with an empty stdout."""
    repository, base, _tip = _scratch_lane_repository(monkeypatch, tmp_path)
    client = FakeForge()
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    monkeypatch.setattr(client, "item_reference", _unreadable_item_reference)
    claim = _brief_claim(base)
    _patch_store_write(monkeypatch, claim, ages={claim.claim_id: datetime(2026, 8, 20, tzinfo=UTC)})
    monkeypatch.chdir(repository)

    status = issue_claim.main(["--repo", REPOSITORY, "brief", "258", "--json"])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == "ERROR: simulated forge read failure\n"
    assert json.loads(captured.out) == {
        "ok": False,
        "reason": "unavailable",
        "message": "simulated forge read failure",
    }


def test_cli_brief_json_prints_one_object_with_body_claim_tip_and_touched(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    repository, base, tip = _scratch_lane_repository(monkeypatch, tmp_path)
    client = FakeForge()
    client.issue_references[258] = forge.ItemReference(
        forge.ItemState.OPEN, "Brief", "The item's own body."
    )
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    claim = _brief_claim(base)
    _patch_store_write(monkeypatch, claim, ages={claim.claim_id: datetime(2026, 8, 20, tzinfo=UTC)})
    monkeypatch.chdir(repository)

    status = issue_claim.main(["--repo", REPOSITORY, "brief", "258", "--json"])

    assert status == 0
    output = capsys.readouterr().out
    expected = {
        "ok": True,
        "reason": "composed",
        "body": "The item's own body.",
        "claim": {
            "agent": "Codex Sol",
            "role": "builder",
            "branch": "codex/issue-258-brief",
            "base": base,
            "scope": ["README.md"],
            "whole": None,
            "age": "24h 0m",
            **_no_lane_shared(),
        },
        "tip": tip,
        "touched": ["README.md"],
        "outside_claim": [],
    }
    assert output == json.dumps(expected) + "\n"
    assert json.loads(output) == expected


@pytest.mark.parametrize(
    ("claimed", "expected_outside_claim"), [(True, ["board.py"]), (False, None)]
)
def test_cli_brief_json_names_touched_paths_the_claim_scope_does_not_cover(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    claimed: bool,
    expected_outside_claim: list[str] | None,
) -> None:
    repository, base, _tip = _scratch_lane_repository(monkeypatch, tmp_path)
    (repository / "board.py").write_text("print()\n")
    real_git(repository, "add", "board.py")
    real_git(repository, "commit", "-q", "-m", "work outside the claim")
    client = FakeForge()
    client.issue_references[258] = forge.ItemReference(forge.ItemState.OPEN, "Brief", "Body.")
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    _patch_store_write(monkeypatch, *([_brief_claim(base)] if claimed else []))
    monkeypatch.chdir(repository)

    status = issue_claim.main(["--repo", REPOSITORY, "brief", "258", "--json"])

    assert status == 0
    assert json.loads(capsys.readouterr().out)["outside_claim"] == expected_outside_claim


_NO_TRUNK_SENTENCE = (
    "cannot determine the trunk: none of origin/HEAD, origin/main, origin/master,"
    " main or master resolves"
)


def _land_on_trunk_and_pull_into_lane(repository: Path, path: str) -> None:
    """Another lane lands `path` on `origin/main` while the local `main`
    stays at the base; the lane then merges `origin/main` in."""
    real_git(repository, "checkout", "-q", "--detach", "main")
    (repository / path).write_text("landed elsewhere\n")
    real_git(repository, "add", path)
    real_git(repository, "commit", "-q", "-m", "another lane lands")
    real_git(repository, "update-ref", "refs/remotes/origin/main", "HEAD")
    real_git(repository, "checkout", "-q", "codex/issue-258-brief")
    real_git(repository, "merge", "-q", "--no-edit", "origin/main")


def _text_touched(output: str) -> list[str]:
    lines = output.splitlines()
    return lines[lines.index("TOUCHED") + 1 :]


def _json_touched(output: str) -> list[str]:
    return json.loads(output)["touched"]


@pytest.mark.parametrize(
    ("output_flags", "read_touched"), [((), _text_touched), (("--json",), _json_touched)]
)
def test_cli_brief_touched_lists_only_the_lane_own_change_after_a_trunk_pull(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    output_flags: tuple[str, ...],
    read_touched: Callable[[str], list[str]],
) -> None:
    """A path another lane landed on trunk, pulled into this
    lane by a merge, is not this lane's change -- TOUCHED diffs from the
    merge base with trunk, never from the claim's base."""
    repository, base, _tip = _scratch_lane_repository(monkeypatch, tmp_path)
    _land_on_trunk_and_pull_into_lane(repository, "b.py")
    client = FakeForge()
    client.issue_references[258] = forge.ItemReference(forge.ItemState.OPEN, "Brief", "Pulled.")
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    claim = _brief_claim(base)
    _patch_store_write(monkeypatch, claim, ages={claim.claim_id: datetime(2026, 8, 20, tzinfo=UTC)})
    monkeypatch.chdir(repository)

    status = issue_claim.main(["--repo", REPOSITORY, "brief", "258", *output_flags])

    assert status == 0
    assert read_touched(capsys.readouterr().out) == ["README.md"]


def _rename_the_local_main(_monkeypatch: pytest.MonkeyPatch, repository: Path) -> None:
    real_git(repository, "branch", "-m", "main", "trunk")


@pytest.mark.usefixtures("isolated_global_git_config")
@pytest.mark.parametrize("output_flags", [(), ("--json",)], ids=["text", "json"])
@pytest.mark.parametrize(
    ("remove_the_trunk", "sentence"),
    [
        pytest.param(_rename_the_local_main, _NO_TRUNK_SENTENCE, id="no-candidate"),
        pytest.param(_leave_hub_unconfigured, _UNCONFIGURED_HUB_SENTENCE, id="unconfigured-remote"),
    ],
)
def test_cli_brief_refuses_naming_the_trunk_when_no_trunk_resolves(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    output_flags: tuple[str, ...],
    remove_the_trunk: Callable[[pytest.MonkeyPatch, Path], None],
    sentence: str,
) -> None:
    """BRIEF-20: with a branchless remote and no local `main` or
    `master`, TOUCHED has no trunk to diff from, so `brief` refuses by
    naming every trunk candidate it tried; a canonical remote the checkout
    never configured is named instead, local `main` or not (BRIEF-22)."""
    repository, base, _tip = _scratch_lane_repository(monkeypatch, tmp_path)
    client = FakeForge()
    client.issue_references[258] = forge.ItemReference(forge.ItemState.OPEN, "Brief", "No trunk.")
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    claim = _brief_claim(base)
    _patch_store_write(monkeypatch, claim, ages={claim.claim_id: datetime(2026, 8, 20, tzinfo=UTC)})
    remove_the_trunk(monkeypatch, repository)
    monkeypatch.chdir(repository)

    status = issue_claim.main(["--repo", REPOSITORY, "brief", "258", *output_flags])

    captured = capsys.readouterr()
    refusal = {"ok": False, "reason": "unavailable", "message": sentence}
    assert (status, captured.err) == (2, f"ERROR: {sentence}\n")
    assert captured.out == (f"{json.dumps(refusal)}\n" if output_flags else "")


_DEFAULT_BRIEF_TOML = '[build]\nrules = ["Stay in scope."]\nchecks = ["ruff check ."]\n'

# Captured at import time, before any test's monkeypatching runs.
_REAL_PATH_IS_TRACKED = checkout.path_is_tracked


def _write_repository_configs(
    toplevel: Path, *, brief_content: str = _DEFAULT_BRIEF_TOML, brief_tracked: bool = True
) -> None:
    """The board and the brief configuration file, both inside
    the scratch lane repository at `toplevel` (`_scratch_lane_repository`),
    the resolved checkout toplevel. `board.toml` is always tracked for real,
    the same proof `test_checkout.py`'s `_tracked_board_config` gives its own
    tracked-file gate: `RunContext.config` reads it (`session.board_config`) on every
    happy-path `--step` scenario below, so it must genuinely exist in the
    index rather than lean on the module's blanket `stub_board_config_tracked`.
    Staged, never committed, so the lane's own change
    since trunk stays exactly its one commit. `brief_tracked=False` leaves
    `brief.toml` on disk outside git's index, for the genuine untracked-file
    refusal."""
    write_repository_config(toplevel)
    real_git(toplevel, "add", workboard.CONFIG_PATH.as_posix())
    write_repository_config(toplevel, brief_content, path=workboard.BRIEF_CONFIG_PATH)
    if brief_tracked:
        real_git(toplevel, "add", workboard.BRIEF_CONFIG_PATH.as_posix())


def _brief_step_scenario(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, content: str = _DEFAULT_BRIEF_TOML
) -> tuple[str, str]:
    """The scratch lane repository, `.aco/board.toml` and
    `.aco/brief.toml` both genuinely `git add`-ed at the resolved
    toplevel, and issue #258's own live claim -- the one arrangement
    `--step`'s text, `--json`, and no-`--step` cases all share.
    Reads both configs' real tracked status instead of the file's blanket
    autouse stub, since `RunContext.config` reads `board.toml`'s own tracked-file
    gate once the brief.toml check passes. Returns
    `(base, tip)`; the repository itself is only `monkeypatch.chdir`-ed into,
    never asserted on."""
    repository, base, tip = _scratch_lane_repository(monkeypatch, tmp_path)
    _write_repository_configs(repository, brief_content=content)
    monkeypatch.setattr(checkout, "path_is_tracked", _REAL_PATH_IS_TRACKED)
    client = FakeForge()
    client.issue_references[258] = forge.ItemReference(
        forge.ItemState.OPEN, "Brief", "The item's own body."
    )
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    claim = _brief_claim(base)
    _patch_store_write(monkeypatch, claim, ages={claim.claim_id: datetime(2026, 8, 20, tzinfo=UTC)})
    monkeypatch.chdir(repository)
    return base, tip


def _brief_touched_lines(base: str, tip: str, *step_lines: str) -> list[str]:
    """The four sections `aco brief` always prints for issue #258's live
    claim scenario, plus whichever `RULES`/`CHECKS` lines a `--step` case
    appends -- the one shape `_brief_step_scenario`'s callers all assert."""
    return [
        "The item's own body.",
        "",
        "CLAIM",
        f"Codex Sol (builder) branch=codex/issue-258-brief base={base} 24h 0m old",
        "  README.md",
        "",
        "TIP",
        tip,
        "",
        "TOUCHED",
        "README.md",
        *step_lines,
    ]


_BRIEF_TOML_ALL_STEPS = (
    '[build]\nrules = ["Stay in scope."]\nchecks = ["ruff check ."]\n'
    "\n"
    '[review]\nrules = ["Mark every finding blocking or follow-up."]\nchecks = []\n'
    "\n"
    '[fix]\nrules = ["Resolve only what the review marked blocking."]\n'
    'checks = ["ruff check ."]\n'
    "\n"
    "[land]\nrules = []\nchecks = []\n"
)


@pytest.mark.parametrize(
    ("step", "step_lines"),
    [
        ("build", ("", "RULES", "Stay in scope.", "", "CHECKS", "ruff check .")),
        (
            "review",
            ("", "RULES", "Mark every finding blocking or follow-up.", "", "CHECKS"),
        ),
        (
            "fix",
            (
                "",
                "RULES",
                "Resolve only what the review marked blocking.",
                "",
                "CHECKS",
                "ruff check .",
            ),
        ),
        ("land", ("", "RULES", "", "CHECKS")),
    ],
    ids=["build", "review", "fix", "land-empty"],
)
def test_cli_brief_step_prints_this_repository_own_rules_and_checks_by_step(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    step: str,
    step_lines: tuple[str, ...],
) -> None:
    """`--step <step>` appends `.aco/brief.toml`'s own
    `RULES` and `CHECKS`, one line per that section's own entries, after the
    four sections a plain brief always prints -- for every step the file can
    name, including one (`[land]`) that names neither rules nor checks at
    all (BRIEF-12, BRIEF-13)."""
    base, tip = _brief_step_scenario(monkeypatch, tmp_path, content=_BRIEF_TOML_ALL_STEPS)
    arguments = ["--repo", REPOSITORY, "brief", "258", "--step", step]

    status = issue_claim.main(arguments)

    assert status == 0
    assert capsys.readouterr().out.splitlines() == _brief_touched_lines(base, tip, *step_lines)


def test_cli_brief_without_step_ignores_the_tracked_brief_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Without `--step`, a tracked `.aco/brief.toml`'s presence or
    content changes nothing: `brief` still prints exactly its own four
    sections (BRIEF-16)."""
    base, tip = _brief_step_scenario(monkeypatch, tmp_path)
    arguments = ["--repo", REPOSITORY, "brief", "258"]

    status = issue_claim.main(arguments)

    assert status == 0
    assert capsys.readouterr().out.splitlines() == _brief_touched_lines(base, tip)


def test_cli_brief_step_json_adds_rules_and_checks_to_the_existing_object(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    base, tip = _brief_step_scenario(monkeypatch, tmp_path)
    arguments = ["--repo", REPOSITORY, "brief", "258", "--step", "build"]

    status = issue_claim.main([*arguments, "--json"])

    assert status == 0
    assert json.loads(capsys.readouterr().out) == {
        "ok": True,
        "reason": "composed",
        "body": "The item's own body.",
        "claim": {
            "agent": "Codex Sol",
            "role": "builder",
            "branch": "codex/issue-258-brief",
            "base": base,
            "scope": ["README.md"],
            "whole": None,
            "age": "24h 0m",
            **_no_lane_shared(),
        },
        "tip": tip,
        "touched": ["README.md"],
        "outside_claim": [],
        "rules": ["Stay in scope."],
        "checks": ["ruff check ."],
    }


@pytest.mark.parametrize(
    "brief_toml_present",
    [False, True],
    ids=["missing", "untracked"],
)
def test_cli_brief_step_refuses_with_no_usable_brief_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    brief_toml_present: bool,
) -> None:
    """A `.aco/brief.toml` this repository cannot actually read from
    -- absent entirely, or genuinely present on disk but never `git add`-ed
    -- refuses the same way before ever reading the item's body (the same
    tracked-file requirement `session.board_config` enforces for `board.toml`'s
    storage pin), proven against the real `checkout.path_is_tracked` rather than a
    hand-rolled stub."""
    repository, _base, _tip = _scratch_lane_repository(monkeypatch, tmp_path)
    monkeypatch.setattr(checkout, "path_is_tracked", _REAL_PATH_IS_TRACKED)
    if brief_toml_present:
        _write_repository_configs(repository, brief_tracked=False)

    def unused(_self: FakeForge, _number: int) -> forge.ItemReference:
        pytest.fail("brief --step must refuse before reading the item's body")

    client = FakeForge()
    monkeypatch.setattr(FakeForge, "item_reference", unused)
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    monkeypatch.chdir(repository)
    arguments = ["--repo", REPOSITORY, "brief", "258", "--step", "build", "--json"]

    status = issue_claim.main(arguments)

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == "ERROR: no .aco/brief.toml in the repository\n"
    _assert_json_refusal_object(captured.err, captured.out, reason="unavailable")


def test_cli_brief_refuses_a_non_github_canonical_remote_by_host(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`brief` is a forge command through the same `RunContext.forge` gate `board`
    uses: a canonical remote on any host but GitHub refuses by
    that host's own name, before ever calling `github.discover_repository`/`gh` --
    the same refusal `board` gives for the same remote."""
    monkeypatch.setattr(
        checkout, "remote_url", lambda remote, **_kwargs: "file:///srv/git/agent-coordination.git"
    )

    def unused(*_args: object, **_kwargs: object) -> forge.RepositoryId:
        pytest.fail("brief must refuse the host before ever calling discover_repository")

    monkeypatch.setattr(github, "discover_repository", unused)

    status = issue_claim.main(["brief", "258", "--json"])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == "ERROR: no forge adapter for host file\n"
    _assert_json_refusal_object(captured.err, captured.out, reason="unavailable")


def test_cli_brief_reports_invalid_usage_when_repo_is_given_under_state_ref(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """BRIEF-09 cites `specs/storage-pin.spec.md`'s PIN-04: under `storage =
    state-ref`, `--repo` is the wrong flag for this run, reported through
    `--json` as `invalid_usage` -- brief's one refusal that is not this
    environment being generically `unavailable`."""
    _write_state_ref_pin(tmp_path)

    status = issue_claim.main(["--repo", "acme/items", "brief", "258", "--json"])

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == "ERROR: --repo is meaningless under storage = state-ref\n"
    _assert_json_refusal_object(captured.err, captured.out, reason="invalid_usage")


@pytest.mark.parametrize(
    ("value", "number"),
    [("aco-3f9a2c", 0x3F9A2C), ("#42", 42), ("42", 42)],
)
def test_rescope_parses_every_item_reference_syntax(value: str, number: int) -> None:
    """`rescope`'s `issue` argument is wired to
    `workboard.parse_item_reference` (its grammar proof lives in `tests/test_board.py`)."""
    rescoped = issue_claim._parser().parse_args(["rescope", value, "--add", "src"])

    assert rescoped.issue == number


def test_main_refuses_a_malformed_item_reference_before_ever_dispatching(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`workboard.parse_item_reference` runs as an argparse `type=` inside
    `parse_args`, so its refusal must reach `cli.main`'s own error rendering
    rather than an argparse usage error or an unhandled exception."""
    status = issue_claim.main(["claim", "not-an-item", "--scope", "README"])

    assert status == 2
    assert "is not an item reference" in capsys.readouterr().err


@pytest.fixture
def pipe_onto_stdin(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
    """Puts a text on stdin as a pipe would; each pipe closes at teardown."""
    with contextlib.ExitStack() as readers:

        def pipe(text: str) -> None:
            reader = readers.enter_context(read_end_of_a_pipe_carrying(text))
            monkeypatch.setattr(sys, "stdin", reader)

        yield pipe


def _item_new_github_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeForge:
    """A `storage = "github"` checkout whose forge holds container `#79`
    and a plain open issue `#951` titled `Ship it now` -- the arrangement
    every `item new` GitHub scenario shares; each pipes its own body. An
    issue it creates joins the open issues a later run reads."""
    look_alike = board_issue(951, "Ship it now", complete_contract("Ship it."))
    client = _configured_board_client(monkeypatch, tmp_path)
    client.board_issues = (container_issue(CUT_CONTAINER, MINIMAL_BLOCK_TOML), look_alike)
    monkeypatch.setattr(client, "list_open_board_issues", lambda: client.board_issues)
    return client


@pytest.mark.parametrize(
    ("arguments", "out", "created", "linked"),
    [
        pytest.param(
            ["item", "new", "--title", "Write the docs", "--kind", "feature"],
            "#900\n",
            [("Write the docs", ITEM_NEW_BODY, body.ItemKind.FEATURE)],
            [],
            id="typed_issue_without_parent",
        ),
        pytest.param(
            ["item", "new", "--title", "Write the docs", "--parent", "79", "--scope", "src/a.py"],
            "#900\n",
            [
                (
                    "Write the docs",
                    complete_contract("Ship it.", scope=["src/a.py"]),
                    body.ItemKind.TASK,
                )
            ],
            [(CUT_CONTAINER, 900)],
            id="sub_issue_of_an_open_container_with_scope",
        ),
        pytest.param(
            ["item", "new", "--title", "Ship it", "--not-a-twin", "--json"],
            '{"ok": true, "reason": "created", "item": "#900", "number": 900}\n',
            [("Ship it", ITEM_NEW_BODY, body.ItemKind.TASK)],
            [],
            id="not_a_twin_creates_past_a_look_alike",
        ),
        pytest.param(
            ["item", "new", "--title", "Ship it now", "--not-a-twin"],
            "#900\n",
            [("Ship it now", ITEM_NEW_BODY, body.ItemKind.TASK)],
            [],
            id="not_a_twin_creates_an_exact_duplicate",
        ),
    ],
)
def test_item_new_creates_a_github_issue_from_the_piped_body(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    pipe_onto_stdin: Callable[[str], None],
    arguments: list[str],
    out: str,
    created: list[tuple[str, str, body.ItemKind]],
    linked: list[tuple[int, int]],
) -> None:
    """Under `storage = "github"`, `item new` opens one
    issue of the organization's type for `--kind`, its body the piped one
    (plus `--scope`), recorded under `--parent` when given, and prints the
    issue number the way the state-ref path prints its id."""
    client = _item_new_github_client(monkeypatch, tmp_path)
    pipe_onto_stdin(ITEM_NEW_BODY)

    status = issue_claim.main(arguments)

    assert (status, capsys.readouterr().out) == (0, out)
    assert (client.created_issues, client.linked_children) == (created, linked)


_PROSE_ABOVE_BUILT_BLOCK = (
    "Ship the importer.\n\n```aco\nversion = 1\n"
    'now = "Ready."\nnext = "Build it."\ndone_when = "Merged."\n\nsize = "S"\n```\n'
)
# The same block as a person types it, not as aco renders it.
_PIPED_BLOCK_AS_TYPED = (
    "Ship the importer.\n\n```aco\nversion = 1\n"
    'now = "Ready."\nnext = "Build it."\ndone_when = "Merged."\nsize = "S"\n```\n'
)


@pytest.mark.parametrize(
    ("stdin_source", "flags", "stored"),
    [
        pytest.param(
            piping("Ship the importer.\n"),
            ("--now", "Ready.", "--next", "Build it.", "--done-when", "Merged.", "--size", "S"),
            ("Write the docs", _PROSE_ABOVE_BUILT_BLOCK, body.ItemKind.TASK),
            id="prose_above_a_block_built_from_the_flags",
        ),
        pytest.param(
            piping(_PIPED_BLOCK_AS_TYPED),
            ("--now", "Ready.", "--size", "S"),
            ("Write the docs", _PIPED_BLOCK_AS_TYPED, body.ItemKind.TASK),
            id="a_piped_block_matching_the_flags_kept_byte_for_byte",
        ),
        pytest.param(
            piping(
                f"Ship the importer.\n\n```{body.BLOCK_FENCE_INFO}\nversion = 1\n# typed by hand\n"
                'now   = "Ready."\nnext = "Build it."\ndone_when = "Merged."\n```\n'
            ),
            ("--size", "S"),
            ("Write the docs", _PROSE_ABOVE_BUILT_BLOCK, body.ItemKind.TASK),
            id="a_piped_block_a_flag_completes_stored_in_canonical_rendering",
        ),
        pytest.param(
            terminal_on_stdin,
            ("--kind", "container", "--now", "Ready.", "--next", "Cut it.", "--done-when", "Done."),
            (
                "Write the docs",
                "Blocked by: nichts\n\n```aco\nversion = 1\n"
                'now = "Ready."\nnext = "Cut it."\ndone_when = "Done."\n```\n',
                body.ItemKind.CONTAINER,
            ),
            id="a_terminal_pipes_nothing_and_a_container_keeps_its_skeleton_prose",
        ),
    ],
)
def test_item_new_on_github_builds_the_block_its_piped_body_lacks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stdin_source: Callable[[Path], contextlib.AbstractContextManager[TextIO]],
    flags: tuple[str, ...],
    stored: tuple[str, str, body.ItemKind],
) -> None:
    """`item new` builds the block from its flags below
    the piped prose, keeps a piped block the flags agree with byte for byte,
    stores one a flag completes in its canonical rendering (ITEM-62), and
    reads nothing from a terminal."""
    client = _item_new_github_client(monkeypatch, tmp_path)

    with stdin_source(tmp_path) as stdin:
        monkeypatch.setattr(sys, "stdin", stdin)
        status = issue_claim.main(["item", "new", "--title", "Write the docs", *flags])

    assert (status, client.created_issues) == (0, [stored])


@pytest.mark.parametrize(
    ("retype_dropped", "status", "out", "err", "retyped", "created"),
    [
        pytest.param(
            False,
            0,
            "#900\n",
            "retyped #484 to Container for its first child\n",
            [(484, body.ItemKind.CONTAINER)],
            [("Write the docs", ITEM_NEW_BODY, body.ItemKind.TASK)],
            id="retypes_and_says_so",
        ),
        pytest.param(
            True,
            2,
            "",
            "ERROR: retype dropped (simulated)\n",
            [],
            [],
            id="dropped_retype_refuses_before_creating_anything",
        ),
    ],
)
def test_item_new_retypes_a_task_parent_to_container_or_refuses(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    pipe_onto_stdin: Callable[[str], None],
    retype_dropped: bool,
    status: int,
    out: str,
    err: str,
    retyped: list[tuple[int, body.ItemKind]],
    created: list[tuple[str, str, body.ItemKind]],
) -> None:
    """The #484 shape: an item becomes a container exactly when
    it gets its first child, so `--parent` on an open Task retypes it to
    Container and names that on stderr, instead of refusing `is not a
    container`; stdout still carries only the created issue. A retype the
    forge drops refuses exit 2 before anything is created (ITEM-46)."""
    client = _item_new_github_client(monkeypatch, tmp_path)
    pipe_onto_stdin(ITEM_NEW_BODY)
    client.board_issues = (
        board_issue(484, "Task about to hold slices", ITEM_NEW_BODY, kind=body.ItemKind.TASK),
    )
    client.fail_set_item_kind = retype_dropped
    arguments = ["item", "new", "--title", "Write the docs", "--parent", "484"]

    exit_code = issue_claim.main(arguments)

    captured = capsys.readouterr()
    assert (exit_code, captured.out, captured.err) == (status, out, err)
    assert (client.retyped_items, client.created_issues) == (retyped, created)


@pytest.mark.parametrize(
    ("number", "flags", "stdin_source", "retype_dropped", "status", "out", "err", "retyped"),
    [
        pytest.param(
            "484",
            (),
            devnull_on_stdin,
            False,
            0,
            "EDITED #484 kind=container\n",
            "",
            [(484, body.ItemKind.CONTAINER)],
            id="retypes_through_the_forge",
        ),
        pytest.param(
            "484",
            ("--json",),
            devnull_on_stdin,
            False,
            0,
            '{"ok": true, "reason": "edited", "item": "#484", "number": 484, '
            '"kind": "container"}\n',
            "",
            [(484, body.ItemKind.CONTAINER)],
            id="retype_reports_the_json_envelope",
        ),
        pytest.param(
            "484",
            (),
            devnull_on_stdin,
            True,
            2,
            "",
            "ERROR: retype dropped (simulated)\n",
            [],
            id="dropped_retype_refuses",
        ),
        pytest.param(
            "485",
            (),
            devnull_on_stdin,
            False,
            2,
            "",
            "ERROR: #485 is not an open item\n",
            [],
            id="no_open_item",
        ),
        pytest.param(
            "484",
            ("--size", "S", "--json"),
            devnull_on_stdin,
            False,
            2,
            '{"ok": false, "reason": "invalid_usage", '
            '"message": "argument --size: not allowed with argument --kind"}\n',
            "ERROR: argument --size: not allowed with argument --kind\n",
            [],
            id="size_beside_kind_refuses",
        ),
        pytest.param(
            "484",
            ("--whole", "one PR", "--json"),
            devnull_on_stdin,
            False,
            2,
            '{"ok": false, "reason": "invalid_usage", '
            '"message": "argument --whole: not allowed with argument --kind"}\n',
            "ERROR: argument --whole: not allowed with argument --kind\n",
            [],
            id="whole_beside_kind_refuses",
        ),
    ],
)
def test_item_edit_kind_retypes_a_github_issue_or_refuses(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    number: str,
    flags: tuple[str, ...],
    stdin_source: Callable[[Path], contextlib.AbstractContextManager[TextIO | None]],
    retype_dropped: bool,
    status: int,
    out: str,
    err: str,
    retyped: list[tuple[int, body.ItemKind]],
) -> None:
    """ITEM-47: `item edit --kind` runs under
    `storage = "github"` too, through the same forge retype `item new
    --parent` uses, so `next`'s nested-container repair runs under both
    storages; a retype the forge drops, an item that is not open, or
    `--size`/`--whole` beside it (ITEM-50) refuses exit 2 before any retype;
    `--json` reports the `item` label, its `number` and new `kind`. Each
    case sets its own stdin; which stdin passes is
    `test_item_edit_of_one_field_refuses_a_body_on_stdin_and_passes_an_empty_one`."""
    client = _item_new_github_client(monkeypatch, tmp_path)
    client.board_issues = (
        board_issue(484, "Task about to hold slices", ITEM_NEW_BODY, kind=body.ItemKind.TASK),
    )
    client.fail_set_item_kind = retype_dropped

    with stdin_source(tmp_path) as stdin:
        monkeypatch.setattr(sys, "stdin", stdin)
        exit_code = issue_claim.main(["item", "edit", number, "--kind", "container", *flags])

    captured = capsys.readouterr()
    assert (exit_code, captured.out, captured.err) == (status, out, err)
    assert client.retyped_items == retyped


@pytest.mark.parametrize(
    ("flag", "value", "edited"),
    [
        pytest.param("--kind", "container", "kind=container", id="kind"),
        pytest.param("--size", "S", "size=S", id="size"),
        pytest.param("--whole", "one PR", "whole=one PR", id="whole"),
    ],
)
@pytest.mark.parametrize(
    ("stdin_source", "refused"),
    [
        pytest.param(body_file_on_stdin, True, id="redirected_file_refuses"),
        pytest.param(piped_body_on_stdin, True, id="fifo_refuses"),
        pytest.param(empty_harness_socket_on_stdin, False, id="harness_socket_passes"),
        pytest.param(devnull_on_stdin, False, id="devnull_passes"),
        pytest.param(closed_stdin, False, id="closed_stdin_passes"),
        pytest.param(terminal_on_stdin, False, id="terminal_passes"),
    ],
)
def test_item_edit_of_one_field_refuses_a_body_on_stdin_and_passes_an_empty_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    flag: str,
    value: str,
    edited: str,
    stdin_source: Callable[[Path], contextlib.AbstractContextManager[TextIO | None]],
    refused: bool,
) -> None:
    """ITEM-49, ITEM-51: `item edit --kind/--size/--whole` read
    no stdin, so a body a file or pipe carries there refuses before any
    write rather than being dropped; a terminal, the socket an agent harness
    hands over, `/dev/null` or a closed stdin carries none and the edit runs."""
    client = _item_new_github_client(monkeypatch, tmp_path)
    client.board_issues = (
        board_issue(484, "Task about to hold slices", ITEM_NEW_BODY, kind=body.ItemKind.TASK),
    )
    client.issue_references[484] = forge.ItemReference(
        forge.ItemState.OPEN, "Task about to hold slices", ITEM_NEW_BODY, False
    )
    command = ["item", "edit", "484", flag, value]

    with stdin_source(tmp_path) as stdin:
        monkeypatch.setattr(sys, "stdin", stdin)
        exit_code = issue_claim.main(command)

    captured = capsys.readouterr()
    wrote = bool(client.retyped_items or client.item_bodies)
    outcome = (exit_code, captured.out, captured.err, wrote)
    expected = (
        (2, "", f"ERROR: item edit {flag} reads no stdin; drop the redirect\n", False)
        if refused
        else (0, f"EDITED #484 {edited}\n", "", True)
    )
    assert outcome == expected


@pytest.mark.parametrize(
    ("piped_body", "flags", "closed", "err"),
    [
        pytest.param(
            "Prose only.\n",
            ("--title", "Write the docs", "--now", "Ready."),
            (),
            "ERROR: body incomplete: Next, Done when\n",
            id="prose_whose_flags_leave_the_block_incomplete",
        ),
        pytest.param(
            complete_contract("Ship it.", size="S"),
            ("--title", "Write the docs", "--size", "M"),
            (),
            """ERROR: --size "M" contradicts the piped block's size = "S"\n""",
            id="a_flag_contradicting_the_piped_block",
        ),
        pytest.param(
            complete_contract("Ship it.", scope=["src/b.py"]),
            ("--title", "Write the docs", "--scope", "src/a.py", "--next", "Ship it."),
            (),
            """ERROR: --scope ["src/a.py"] contradicts the piped block's scope = ["src/b.py"]\n""",
            id="a_scope_contradicting_the_piped_block",
        ),
        pytest.param(
            ITEM_NEW_BODY,
            ("--title", "Ship it"),
            (),
            "ERROR: possible twin #951; pass --not-a-twin\n",
            id="open_twin",
        ),
        pytest.param(
            ITEM_NEW_BODY,
            ("--title", "Write docs"),
            (forge.ClosedIssue(952, "write the docs"),),
            "ERROR: possible twin #952; pass --not-a-twin\n",
            id="recently_closed_twin",
        ),
        pytest.param(
            ITEM_NEW_BODY,
            ("--title", "!!!"),
            (forge.ClosedIssue(952, "!!!"),),
            "ERROR: possible twin #952; pass --not-a-twin\n",
            id="identical_title_without_words",
        ),
        pytest.param(
            ITEM_NEW_BODY,
            ("--title", "Write the docs", "--parent", "951"),
            (),
            "ERROR: #951 is not a container\n",
            id="parent_is_not_a_container",
        ),
        pytest.param(
            ITEM_NEW_BODY,
            ("--title", "Write the docs", "--parent", "81"),
            (),
            "ERROR: #81 is not an open container\n",
            id="parent_is_not_open",
        ),
        pytest.param(
            ITEM_NEW_BODY,
            ("--title", "Write the docs", "--origin", "gitlab#5"),
            (),
            'ERROR: --origin needs storage = "state-ref"\n',
            id="origin_under_github",
        ),
        *(
            pytest.param(
                ITEM_NEW_BODY,
                ("--title", title),
                (),
                "ERROR: --title must be a non-empty string\n",
                id=case,
            )
            for case, title in (("empty_title", ""), ("whitespace_title", "   "))
        ),
        *(
            pytest.param(
                complete_contract("Ship it.", slice=slice_entries(f"Flip{control}side")),
                ("--title", "Write the docs"),
                (),
                f"ERROR: body malformed: slice[0].title: slice[0].title of row 1 holds "
                f"{codepoint}; a slice title stays on one line\n",
                id=f"slice_title_{codepoint}",
            )
            for control, codepoint in BIDI_AND_ZERO_WIDTH_CONTROLS
        ),
    ],
)
def test_item_new_on_github_refuses_before_creating_anything(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    pipe_onto_stdin: Callable[[str], None],
    piped_body: str,
    flags: tuple[str, ...],
    closed: tuple[forge.ClosedIssue, ...],
    err: str,
) -> None:
    """An invalid body (the same
    check `aco check <n>` applies, a slice title holding a display control
    included), a possible twin, a parent that is no open container,
    `--origin`, or a blank `--title` refuses with exit 2 and creates no
    issue at all."""
    client = _item_new_github_client(monkeypatch, tmp_path)
    pipe_onto_stdin(piped_body)
    client.recently_closed_issues = closed

    status = issue_claim.main(["item", "new", *flags])

    assert (status, capsys.readouterr().err, client.created_issues) == (2, err, [])


@pytest.mark.parametrize(
    ("failure", "flags", "failed", "message"),
    [
        pytest.param(
            "fail_create_child_relation",
            ("--parent", "79"),
            "record #900 as a sub-issue of #79",
            "created #900 but failed to record #900 as a sub-issue of #79: "
            "relation POST failed (simulated); record that sub-issue relation on the forge by hand",
            id="parent_relation",
        ),
        pytest.param(
            "drop_created_issue_type",
            (),
            "set #900's type Task",
            "created #900 but GitHub did not set its type Task; set that type on the forge by hand",
            id="issue_type",
        ),
        pytest.param(
            "drop_created_issue_type",
            ("--parent", "79"),
            "set #900's type Task",
            "created #900 but GitHub did not set its type Task; "
            "set that type and record it under #79 on the forge by hand",
            id="issue_type_under_a_parent",
        ),
    ],
)
def test_item_new_json_reports_a_created_issue_it_could_not_finish(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    pipe_onto_stdin: Callable[[str], None],
    failure: str,
    flags: tuple[str, ...],
    failed: str,
    message: str,
) -> None:
    """The issue exists once its create returns, so a failed
    sub-issue relation or an issue type GitHub dropped reports
    `partial_write` naming it and what is left, never a plain refusal that
    would read as "nothing created" nor a success."""
    client = _item_new_github_client(monkeypatch, tmp_path)
    pipe_onto_stdin(ITEM_NEW_BODY)
    setattr(client, failure, True)
    command = ["item", "new", "--title", "Write the docs", *flags, "--json"]

    status = issue_claim.main(command)

    assert (status, json.loads(capsys.readouterr().out)) == (
        2,
        {
            "ok": False,
            "reason": "partial_write",
            "written": 900,
            "failed": failed,
            "message": message,
        },
    )


@pytest.mark.parametrize(
    "failure",
    [None, "fail_create_child_relation", "drop_created_issue_type"],
    ids=["after_a_success", "after_a_relation_failure", "after_a_dropped_type"],
)
def test_item_new_rerun_on_github_meets_its_own_issue_as_a_twin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    pipe_onto_stdin: Callable[[str], None],
    failure: str | None,
) -> None:
    """ITEM-35: nothing guesses whether an open issue is an
    earlier run's own. The same command again meets the issue it created in
    the twin search and creates nothing; `--not-a-twin` creates a second
    one anyway, as ruled."""
    client = _item_new_github_client(monkeypatch, tmp_path)
    pipe_onto_stdin(ITEM_NEW_BODY)
    if failure is not None:
        setattr(client, failure, True)
    command = ["item", "new", "--title", "Write the docs", "--parent", "79"]
    issue_claim.main(command)
    if failure is not None:
        setattr(client, failure, False)
    capsys.readouterr()
    pipe_onto_stdin(ITEM_NEW_BODY)

    refused = issue_claim.main(command)

    assert (refused, capsys.readouterr().err, len(client.created_issues)) == (
        2,
        "ERROR: possible twin #900; pass --not-a-twin\n",
        1,
    )
    pipe_onto_stdin(ITEM_NEW_BODY)
    assert issue_claim.main([*command, "--not-a-twin"]) == 0
    assert len(client.created_issues) == 2


def test_item_new_json_reports_ok_reason_created(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A fresh item's own `--json` success carries `reason:
    "created"` first, ahead of the minted `item`/`number` pair."""
    _write_state_ref_pin(tmp_path)
    client = FakeForge(repository=forge.RepositoryId("file", (), str(tmp_path)))
    item_id = items.format_item_id(42)
    monkeypatch.setattr(client, "compose_item", lambda **_kwargs: None, raising=False)
    monkeypatch.setattr(client, "create_item", lambda _write: item_id, raising=False)
    monkeypatch.setattr(client, "open_item_titles", tuple, raising=False)
    monkeypatch.setattr(session, "_state_ref_forge", lambda _context: client)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    status = issue_claim.main(["item", "new", "--title", "Fresh Item", "--json"])

    assert status == 0
    assert json.loads(capsys.readouterr().out) == {
        "ok": True,
        "reason": "created",
        "item": item_id,
        "number": 42,
    }


@pytest.mark.parametrize(
    ("command", "sentence"),
    [
        pytest.param(
            "edit",
            "ERROR: forge issues are edited on the forge; aco never governs them\n",
            id="edit",
        ),
        pytest.param(
            "close",
            "ERROR: the forge closes its issues; aco never governs them\n",
            id="close",
        ),
    ],
)
def test_item_mutation_refuses_under_github_storage(
    capsys: pytest.CaptureFixture[str], command: str, sentence: str
) -> None:
    """The forge owns whole-body edits and closing."""
    status = issue_claim.main(["item", command, "42"])

    observed = (status, capsys.readouterr().err)
    expected = (2, sentence)
    assert observed == expected


@dataclass(frozen=True)
class _ItemFieldEdit:
    """`item edit --size/--whole` write one top-level field of the item's block through the
    generic `ForgeWriter.update_item_body`: the flag and its value, the
    block key, and the `EDITED` line a person reads."""

    flag: str
    value: str
    key: str
    edited_line: str


_ITEM_FIELD_EDITS = {
    "size": _ItemFieldEdit("--size", "M", "size", f"EDITED #{RULE_ITEM} size=M\n"),
    "whole": _ItemFieldEdit(
        "--whole",
        "the four adapters share one lock",
        "whole",
        f"EDITED #{RULE_ITEM} whole=the four adapters share one lock\n",
    ),
}
_ITEM_FIELD_EDIT_CASES = pytest.mark.parametrize(
    "case", _ITEM_FIELD_EDITS.values(), ids=_ITEM_FIELD_EDITS.keys()
)


def _edit_item_field(case: _ItemFieldEdit, *flags: str) -> int:
    return issue_claim.main(
        ["--repo", REPOSITORY, "item", "edit", str(RULE_ITEM), case.flag, case.value, *flags]
    )


@_ITEM_FIELD_EDIT_CASES
def test_item_edit_writes_the_top_level_field_under_github_storage(
    case: _ItemFieldEdit,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Unlike the whole-body `item edit`, which refuses under `storage = "github"` by name."""
    client = _client_with_item(monkeypatch, tmp_path, RULE_ITEM, block_body(MINIMAL_BLOCK_TOML))

    exit_code = _edit_item_field(case)

    written = body.locate_block(client.item_bodies[RULE_ITEM]).data[case.key]
    assert (exit_code, capsys.readouterr().out, written) == (0, case.edited_line, case.value)


@_ITEM_FIELD_EDIT_CASES
def test_item_edit_json_reports_the_item_and_the_field(
    case: _ItemFieldEdit,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _client_with_item(monkeypatch, tmp_path, RULE_ITEM, block_body(MINIMAL_BLOCK_TOML))

    exit_code = _edit_item_field(case, "--json")

    assert (exit_code, json.loads(capsys.readouterr().out)) == (
        0,
        {"ok": True, "reason": "edited", "item": RULE_ITEM, case.key: case.value},
    )


@_ITEM_FIELD_EDIT_CASES
@pytest.mark.parametrize(
    ("reference", "sentence"),
    [
        (forge.ItemReference(forge.ItemState.MISSING), f"#{RULE_ITEM} does not exist"),
        (
            forge.ItemReference(forge.ItemState.OPEN, "T", block_body(MINIMAL_BLOCK_TOML), True),
            f"#{RULE_ITEM} is a pull request, not an issue; {{command}} needs an issue",
        ),
    ],
)
def test_item_edit_refuses_through_the_shared_precondition_failed_envelope(
    case: _ItemFieldEdit,
    reference: forge.ItemReference,
    sentence: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """A target `item edit --size`/`--whole` cannot write reports as `precondition_failed`.

    Spec: ITEM-17"""
    _configured_board_client(monkeypatch, tmp_path).issue_references[RULE_ITEM] = reference

    exit_code = _edit_item_field(case, "--json")

    captured = capsys.readouterr()
    refusal = sentence.format(command=f"item edit {case.flag}")
    assert (exit_code, refusal in captured.err) == (2, True)
    _assert_json_refusal_object(captured.err, captured.out, reason="precondition_failed")


def test_item_edit_size_refuses_an_invalid_value_before_any_write(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exited:
        issue_claim.main(["item", "edit", "42", "--size", "XL"])

    assert exited.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_item_close_prints_json_under_the_state_ref_pin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """`item close ITEM --json` under `storage = "state-ref"`
    prints the shared envelope, `reason: "closed"`, then `{"item", "number",
    "closed_at", "parent_closable"}`, and returns before the plain-text
    `CLOSED`/`freed:` lines, the branch
    `test_item_mutation_refuses_under_github_storage[close]`'s refusal never reaches.
    `parent_closable` is `null` here: `42` names no parent on
    this fake."""
    _write_state_ref_pin(tmp_path)
    client = FakeForge(repository=forge.RepositoryId("file", (), str(tmp_path)))
    client.issue_references[42] = forge.ItemReference(
        forge.ItemState.OPEN, "Title", "Body text.\n", False
    )
    monkeypatch.setattr(client, "close_item", lambda _number: "2026-09-16T12:00:00Z", raising=False)
    monkeypatch.setattr(client, "unplaced_child_numbers", lambda _number: (), raising=False)
    monkeypatch.setattr(session, "_state_ref_forge", lambda _context: client)

    status = issue_claim.main(["item", "close", "42", "--json"])

    assert status == 0
    assert json.loads(capsys.readouterr().out) == {
        "ok": True,
        "reason": "closed",
        "item": items.format_item_id(42),
        "number": 42,
        "closed_at": "2026-09-16T12:00:00Z",
        "parent_closable": None,
    }


@pytest.mark.parametrize("number", [42, 16777216], ids=["in-the-id-space", "past-the-id-space"])
def test_item_show_reads_the_fake_forge_body_under_github_storage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], number: int
) -> None:
    """Under `storage = "github"`, `item show` reads
    the issue body through the ordinary forge reader -- the same output
    shape `state-ref` prints, an id encoded from the plain issue number. A
    number past `aco-ffffff` is an ordinary forge number there: PIN-31
    refuses it only under `storage = "state-ref"`."""
    client = FakeForge()
    client.issue_references[number] = forge.ItemReference(
        forge.ItemState.OPEN, "Title", "Body text.\n", False
    )
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)

    status = issue_claim.main(["--repo", REPOSITORY, "item", "show", str(number)])

    assert status == 0
    expected_id = items.format_item_id(number)
    assert (
        capsys.readouterr().out
        == f"{expected_id} · #{number} · open · parent none · origin none\nBody text.\n"
    )


def test_item_show_as_json_reads_the_fake_forge_body_under_github_storage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeForge()
    client.issue_references[42] = forge.ItemReference(
        forge.ItemState.OPEN, "Title", "Body text.\n", False
    )
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)

    status = issue_claim.main(["--repo", REPOSITORY, "item", "show", "42", "--json"])

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "reason": "shown",
        "item": items.format_item_id(42),
        "number": 42,
        "state": "open",
        "parent": None,
        "origin": None,
        "body": "Body text.\n",
    }


def test_item_show_refuses_an_unknown_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeForge()
    client.issue_references[42] = forge.ItemReference(forge.ItemState.MISSING)
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)

    status = issue_claim.main(["--repo", REPOSITORY, "item", "show", "42"])

    assert status == 2
    assert capsys.readouterr().err == f"ERROR: #42 does not exist in {REPOSITORY}\n"


def test_item_show_refuses_when_the_parent_read_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The parent read the header needs is inside `item
    show`'s own refusal boundary, so a forge that fails it reports the same
    envelope, never an error escaping past every `--json` printer."""
    sentence = "GitHub returned a malformed parent issue"

    def prepare() -> FakeForge:
        client = FakeForge()
        client.issue_references[42] = forge.ItemReference(
            forge.ItemState.OPEN, "Title", "Body text.\n", False
        )

        def failing_parent_read(_number: int) -> int | None:
            raise forge.ForgeMalformedResponseError(sentence)

        monkeypatch.setattr(client, "parent_number", failing_parent_read)
        monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
        return client

    prepare()
    text_status = issue_claim.main(["--repo", REPOSITORY, "item", "show", "42"])
    text = capsys.readouterr()

    prepare()
    json_status = issue_claim.main(["--repo", REPOSITORY, "item", "show", "42", "--json"])
    envelope = capsys.readouterr()

    assert (text_status, json_status) == (2, 2)
    assert (text.out, text.err) == ("", f"ERROR: {sentence}\n")
    assert envelope.err == text.err
    _assert_json_refusal_object(envelope.err, envelope.out, reason="precondition_failed")


def _item_new_github_storage_refusal(
    _monkeypatch: pytest.MonkeyPatch, _tmp_path: Path
) -> list[str]:
    return ["item", "new", "--title", "X", "--origin", "gitlab#5", "--json"]


def _item_edit_github_storage_refusal(
    _monkeypatch: pytest.MonkeyPatch, _tmp_path: Path
) -> list[str]:
    return ["item", "edit", "42", "--json"]


def _item_close_github_storage_refusal(
    _monkeypatch: pytest.MonkeyPatch, _tmp_path: Path
) -> list[str]:
    return ["item", "close", "42", "--json"]


def _item_show_unknown_id_refusal(monkeypatch: pytest.MonkeyPatch, _tmp_path: Path) -> list[str]:
    client = FakeForge()
    client.issue_references[42] = forge.ItemReference(forge.ItemState.MISSING)
    monkeypatch.setattr(github, "GitHubForge", lambda _repository: client)
    return ["--repo", REPOSITORY, "item", "show", "42", "--json"]


@pytest.mark.parametrize(
    "build_arguments",
    [
        _item_new_github_storage_refusal,
        _item_edit_github_storage_refusal,
        _item_close_github_storage_refusal,
        _item_show_unknown_id_refusal,
    ],
    ids=["new", "edit", "close", "show"],
)
def test_item_refuses_through_the_shared_precondition_failed_envelope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    build_arguments: Callable[[pytest.MonkeyPatch, Path], list[str]],
) -> None:
    """Every runtime refusal from `item new`/`edit`/`close`/
    `show`, reached with `--json`, reports through the shared envelope as
    `precondition_failed` -- never a bare object."""
    arguments = build_arguments(monkeypatch, tmp_path)

    status = issue_claim.main(arguments)

    assert status == 2
    captured = capsys.readouterr()
    _assert_json_refusal_object(captured.err, captured.out, reason="precondition_failed")


def _github_item_new(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pipe: Callable[[str], None]
) -> tuple[FakeForge, list[str]]:
    client = _item_new_github_client(monkeypatch, tmp_path)
    pipe(ITEM_NEW_BODY)
    return client, ["item", "new", "--title", "Write the docs", "--kind", "feature"]


def _state_ref_item_client(tmp_path: Path) -> FakeForge:
    _write_state_ref_pin(tmp_path)
    client = FakeForge(repository=forge.RepositoryId("file", (), str(tmp_path)))
    client.issue_references[42] = forge.ItemReference(
        forge.ItemState.OPEN, "Title", "Body text.\n", False
    )
    return client


def _state_ref_item_new(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pipe: Callable[[str], None]
) -> tuple[FakeForge, list[str]]:
    client = _state_ref_item_client(tmp_path)
    monkeypatch.setattr(client, "compose_item", lambda **_kwargs: None, raising=False)
    monkeypatch.setattr(
        client, "create_item", lambda _write: items.format_item_id(43), raising=False
    )
    monkeypatch.setattr(client, "open_item_titles", tuple, raising=False)
    return client, ["item", "new", "--title", "Fresh Item"]


def _state_ref_item_edit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pipe: Callable[[str], None]
) -> tuple[FakeForge, list[str]]:
    client = _state_ref_item_client(tmp_path)
    monkeypatch.setattr(client, "holds", lambda _number: True, raising=False)
    monkeypatch.setattr(client, "item_oid", lambda _number: "a" * 40, raising=False)
    pipe(_state_ref_item_body("Edited Title"))
    return client, ["item", "edit", "42"]


def _state_ref_item_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pipe: Callable[[str], None]
) -> tuple[FakeForge, list[str]]:
    client = _state_ref_item_client(tmp_path)
    monkeypatch.setattr(client, "close_item", lambda _number: "2026-09-16T12:00:00Z", raising=False)
    monkeypatch.setattr(client, "unplaced_child_numbers", lambda _number: (), raising=False)
    return client, ["item", "close", "42"]


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(_github_item_new, id="github-new"),
        pytest.param(_state_ref_item_new, id="state-ref-new"),
        pytest.param(_state_ref_item_edit, id="state-ref-edit"),
        pytest.param(_state_ref_item_close, id="state-ref-close"),
    ],
)
def test_an_item_command_works_through_the_one_forge_its_run_context_builds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pipe_onto_stdin: Callable[[str], None],
    arrange: Callable[
        [pytest.MonkeyPatch, Path, Callable[[str], None]], tuple[FakeForge, list[str]]
    ],
) -> None:
    """`session._build_forge`, asked through `RunContext.forge`,
    is the one place a run's forge is constructed -- an item command never
    builds a `GitHubForge` or a state-ref board of its own beside it."""
    client, argv = arrange(monkeypatch, tmp_path, pipe_onto_stdin)
    built: list[RunContext] = []

    def build_forge(context: RunContext) -> forge.ForgeReader:
        built.append(context)
        return client

    def unused(*_args: object, **_kwargs: object) -> None:
        pytest.fail("an item command built a forge beside its run context")

    monkeypatch.setattr(session, "_build_forge", build_forge)
    monkeypatch.setattr(github, "GitHubForge", unused)
    monkeypatch.setattr(session, "_state_ref_forge", unused)

    assert (issue_claim.main(argv), len(built)) == (0, 1)


def test_item_edit_json_reports_body_invalid_with_defects(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """`item edit`'s own malformed piped body reports
    `reason: "body_invalid"`, with `check -`'s own `defects` list as a
    structured sibling, before any forge is ever resolved."""
    _write_state_ref_pin(tmp_path)
    result = run_cli(["item", "edit", "42", "--json"], capsys, stdin="no block")

    assert result.status == 2
    defect = "body malformed: aco: no aco block"
    assert result.stderr == f"ERROR: {defect}\n"
    expected = {
        "ok": False,
        "reason": "body_invalid",
        "defects": [defect],
        "message": defect,
    }
    assert result.stdout == json.dumps(expected) + "\n"


# Capture real store functions before the module-local fake replaces them.
_REAL_STORE_FETCH_STATE = store.fetch_state
_REAL_STORE_PEEK_STATE = store.peek_state
_REAL_STORE_COMMIT_TRANSITION = store.commit_transition
_REAL_STORE_CLAIM_AGES = store.claim_ages
_REAL_STORE_CLAIM_LIFECYCLE = store.claim_lifecycle


def _use_real_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore real store operations for the remaining CAS and item tests."""
    monkeypatch.setattr(store, "fetch_state", _REAL_STORE_FETCH_STATE)
    monkeypatch.setattr(store, "peek_state", _REAL_STORE_PEEK_STATE)
    monkeypatch.setattr(store, "commit_transition", _REAL_STORE_COMMIT_TRANSITION)
    monkeypatch.setattr(store, "claim_ages", _REAL_STORE_CLAIM_AGES)
    monkeypatch.setattr(store, "claim_lifecycle", _REAL_STORE_CLAIM_LIFECYCLE)


def _reset_repository(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    """A real checkout with a real `origin` remote pointing at a real bare
    repository, and the run's toplevel redirected onto it. `board.toml` is
    never written, so `workboard.load_config` falls back to its own default
    `canonical_remote = "origin"` -- exactly this remote's name."""
    bare_remote = tmp_path / "remote.git"
    init_bare_repository(bare_remote)
    repository = tmp_path / "repo"
    repository.mkdir()
    real_git(repository, "init", "-q", "-b", "main")
    real_git(repository, "config", "user.email", "test@example.com")
    real_git(repository, "config", "user.name", "Test")
    (repository / "README.md").write_text("hello\n")
    real_git(repository, "add", "README.md")
    real_git(repository, "commit", "-q", "-m", "initial")
    real_git(repository, "remote", "add", "origin", str(bare_remote))
    redirect_toplevel(monkeypatch, repository)
    return repository, bare_remote


@dataclass(frozen=True)
class _CountedRun:
    """One command's argv, its exit code, and the exact reads it makes:
    toplevel reads keyed by the directory git ran in (`None`: the process's
    own cwd), board configuration reads by the toplevel they read, and
    observations of `refs/aco/state`, a transition's own included, by the
    worktree they fetched into; `piped`, the body a
    command reading one gets on a pipe."""

    argv: list[str]
    toplevel_reads: dict[Path | None, int]
    config_reads: dict[Path | None, int]
    observations: dict[Path, int]
    exit_code: int = 0
    piped: str | None = None


def _read_once(
    argv: list[str], *, toplevel: Path, directory: Path | None = None, observes: bool = True
) -> _CountedRun:
    return _CountedRun(
        argv,
        toplevel_reads={directory: 1},
        config_reads={toplevel: 1},
        observations={toplevel: 1} if observes else {},
    )


def _status_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _CountedRun:
    _patch_status_store(monkeypatch)
    return _read_once(["--repo", REPOSITORY, "status"], toplevel=tmp_path)


def _next_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _CountedRun:
    _configured_board_client(
        monkeypatch, tmp_path, open_issues=_TOP_AND_BLOCKED, dependencies=_BLOCKED_BY_ELEVEN
    )
    return _read_once(["--repo", REPOSITORY, "next", "--json"], toplevel=tmp_path)


def _state_ref_command(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> _CountedRun:
    """Under `state-ref` the board a command builds and the
    checks it runs itself read one observation of the state ref, however
    many of them ask."""
    repo, _remote, _oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    return _read_once(argv, toplevel=repo)


def _state_ref_next_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _CountedRun:
    """`next` reads its checkout once more, resolved from the held toplevel
    as `start` resolves it, to tell whether `claim` runs there."""
    repo, _remote, _oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    return _CountedRun(
        ["next", "--json"],
        toplevel_reads={None: 1, repo: 1},
        config_reads={repo: 1},
        observations={repo: 1},
    )


def _state_ref_item_edit_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _CountedRun:
    run = _state_ref_command(["item", "edit", "314"], monkeypatch, tmp_path)
    return replace(run, piped=_state_ref_item_body("Edited Title"))


def _state_ref_release_merged_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> _CountedRun:
    """`release --merged` finds its claim and prepares its landing item
    from the same observation, and its landing transition
    writes onto that observation without reading the ref again."""
    repo, _remote, _oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    assert issue_claim.main(["start", "314", "--scope", "src/x.py"]) == 0
    landing_trailer = f"Work-Item: {items.format_item_id(314)}"
    real_git(repo, "commit", "-q", "--allow-empty", "-m", "Land", "-m", landing_trailer)
    push_repository_trunk(repo, "origin")
    monkeypatch.setattr(checkout, "trunk_landings", _LIVE_TRUNK_LANDINGS)
    return _read_once(["release", "314", "--merged", "--keep-worktree"], toplevel=repo)


def _github_item_close_refusal_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> _CountedRun:
    """`item close` refuses `storage = "github"` from the board
    configuration alone, before it ever needs the state ref."""
    argv = _item_close_github_storage_refusal(monkeypatch, tmp_path)
    return _CountedRun(argv, {None: 1}, {tmp_path: 1}, observations={}, exit_code=2)


def _claim_comma_scope_refusal_command(
    monkeypatch: pytest.MonkeyPatch, _tmp_path: Path
) -> _CountedRun:
    """A scope shape refusal reads nothing of the repository at all."""
    _arranged_claim_client(monkeypatch)
    return _CountedRun(_claim_argv("--scope", "a,b"), {}, {}, observations={}, exit_code=2)


def _check_stdin_command(_monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _CountedRun:
    """`check -` judges a piped body without the state ref."""
    run = _read_once(["check", "-"], toplevel=tmp_path, observes=False)
    return replace(run, piped=complete_contract("Check #10."))


def _rule_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _CountedRun:
    toml_text = f'{MINIMAL_BLOCK_TOML}[[expectation]]\ntext = "Ship it?"\ndefault = "later"\n'
    _client_with_item(monkeypatch, tmp_path, RULE_ITEM, block_body(toml_text))
    argv = ["--repo", REPOSITORY, "rule", str(RULE_ITEM), "--line", "1", "--yes"]
    return _read_once(argv, toplevel=tmp_path, observes=False)


def _claim_command(monkeypatch: pytest.MonkeyPatch, _tmp_path: Path) -> _CountedRun:
    _arranged_claim_client(monkeypatch)
    return _read_once(_claim_argv("--scope", "README.md"), toplevel=Path("/repo"))


def _claim_untracked_scope_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _CountedRun:
    """A scope entry that is no git tree sends the width
    gate to the run's own held toplevel, never to a second git read."""
    repo, _remote, _oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    worktree = tmp_path / "lane"
    real_git(repo, "worktree", "add", "-q", "-b", "codex/issue-314-lane", str(worktree))
    redirect_toplevel(monkeypatch, worktree)
    monkeypatch.chdir(worktree)
    return _read_once(["claim", "314", "--scope", "src/x.py"], toplevel=worktree)


def _rescope_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _CountedRun:
    """`rescope` reads the checkout its own `--add` path resolves to, never
    the process's cwd, and the toplevel that resolution already read is the
    one its store context uses, never read there a second time. The fake
    checkout sits in a `tmp_path` child that is never created, so the
    resolution reads from its nearest existing ancestor, `tmp_path` itself
    (RESC-18)."""
    _serve_rescoped_item(_arranged_claim_client(monkeypatch))
    repo = tmp_path / "repo"
    git_values = git_checkout(
        toplevel=str(repo),
        git_directory=str(repo / ".git" / "worktrees" / "issue-72"),
        common_directory=str(repo / ".git"),
    )
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    claimed = request(agent="Ada", issue=72, branch="codex/issue-72", scope=("src/widget.py",))
    _patch_store_write(monkeypatch, store_claim_from_request(claimed))
    argv = ["--repo", REPOSITORY, "rescope", "72", "--agent", "Ada", "--add", str(repo / "new.py")]
    return _read_once(argv, toplevel=repo, directory=tmp_path)


def _cut_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _CountedRun:
    toml_text = (
        f"{MINIMAL_BLOCK_TOML}"
        '[[slice]]\nindex = 1\ntitle = "Scheibe 1"\ndone_when = "D"\n'
        '[[slice]]\nindex = 2\ntitle = "Scheibe 2"\ndone_when = "D"\n'
    )
    _configured_board_client(
        monkeypatch, tmp_path, open_issues=(container_issue(CUT_CONTAINER, toml_text),)
    )
    _write_block_pin(tmp_path)
    argv = ["--repo", REPOSITORY, "cut", str(CUT_CONTAINER), "--title", "Scheibe 1"]
    return _read_once(argv, toplevel=tmp_path, observes=False)


def _release_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _CountedRun:
    repo = _start_scenario(monkeypatch, tmp_path)
    monkeypatch.chdir(repo)
    assert issue_claim.main(["--repo", REPOSITORY, "start", "314"]) == 0
    argv = ["--repo", REPOSITORY, "release", "314", "--abandoned", "stopped for the day"]
    return _read_once(argv, toplevel=repo)


def _land_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _CountedRun:
    """Both toplevel reads are of `repo`, the process's cwd, through the
    context. Proof 6: `land`'s fast-forward writes the landed trunk into
    this very checkout, so its release reads the toplevel and configuration
    once more, afterwards. Its worktree cleanup
    judges the main checkout from that held toplevel, never resolving it
    again. It observes the state ref only through that
    release's fresh context, after its own write (CAS-54)."""
    repo, _client = _land_scenario(monkeypatch, tmp_path)
    return _CountedRun(
        ["--repo", REPOSITORY, "land", "12"],
        toplevel_reads={None: 2},
        config_reads={repo: 2},
        observations={repo: 1},
    )


def _start_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _CountedRun:
    """Every read is of the caller's checkout, here the main one: once as
    the command's own, once resolved as the main checkout whose context the
    claim's checks run on once the trunk is fetched,
    which observes the state ref afresh (CAS-55) while holding
    that checkout's one board configuration read; the width gate
    measures the fetched trunk's own tree and asks no toplevel for a scope
    entry that is no tree in it."""
    repo, _remote, _oid = _real_state_ref_start_scenario(monkeypatch, tmp_path)
    lane = repo.parent / f"{repo.name}-worktrees" / _START_WORKTREE_NAME
    return _CountedRun(
        ["start", "314", "--scope", "src/x.py"],
        toplevel_reads={None: 1, repo: 1},
        config_reads={repo: 1},
        observations={repo: 2, lane: 1},
    )


def _start_lost_answer_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _CountedRun:
    """A `start` whose claim push lands but whose answer is lost reads
    exactly what a successful one does: the store alone answers that its
    push's outcome is unknown, so keeping the build observes the state ref
    no further time (CAS-53, CAS-55, START-25)."""
    run = _start_command(monkeypatch, tmp_path)
    real_push = store.GitPushTransport.push

    def answer_lost(
        transport: store.GitPushTransport,
        *,
        worktree: Path,
        remote: str,
        ref: str,
        new_oid: protocol.ObjectId,
    ) -> None:
        real_push(transport, worktree=worktree, remote=remote, ref=ref, new_oid=new_oid)
        raise protocol.ClaimError(_PUSH_TIMED_OUT)

    monkeypatch.setattr(store.GitPushTransport, "push", answer_lost)
    return replace(run, exit_code=2)


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(_status_command, id="forge-free-status"),
        pytest.param(_next_command, id="github-read-next"),
        pytest.param(_state_ref_next_command, id="state-ref-read-next"),
        pytest.param(partial(_state_ref_command, ["status"]), id="state-ref-status"),
        pytest.param(partial(_state_ref_command, ["board", "--json"]), id="state-ref-board"),
        pytest.param(partial(_state_ref_command, ["item", "close", "314"]), id="item-close"),
        pytest.param(_state_ref_item_edit_command, id="item-edit"),
        pytest.param(_state_ref_release_merged_command, id="state-ref-release-merged"),
        pytest.param(_rule_command, id="one-write-rule"),
        pytest.param(_claim_command, id="github-claim"),
        pytest.param(_claim_untracked_scope_command, id="claim-untracked-scope-entry"),
        pytest.param(_rescope_command, id="rescope"),
        pytest.param(_release_command, id="release"),
        pytest.param(_cut_command, id="two-write-cut"),
        pytest.param(_start_command, id="two-directory-state-ref-start"),
        pytest.param(_start_lost_answer_command, id="state-ref-start-lost-answer"),
        pytest.param(_land_command, id="land-rereads-after-its-fast-forward"),
        pytest.param(_github_item_close_refusal_command, id="item-close-github-refusal"),
        pytest.param(_claim_comma_scope_refusal_command, id="claim-scope-shape-refusal"),
        pytest.param(_check_stdin_command, id="check-stdin"),
    ],
)
def test_a_command_reads_its_static_facts_and_the_state_ref_once_per_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    pipe_onto_stdin: Callable[[str], None],
    arrange: Callable[[pytest.MonkeyPatch, Path], _CountedRun],
) -> None:
    """A run's static facts are read the first time a
    command asks and held after that -- one toplevel and one board
    configuration read per directory the command works in, however many of
    its steps ask again, unless the command itself wrote that directory's
    checkout in between (proof 6, `land`). No exception. The
    same holds for its observation of `refs/aco/state`, which its
    transitions write onto rather than read again and which a
    command refused before it needs the state ref never makes (CAS-53)."""
    run = arrange(monkeypatch, tmp_path)
    if run.piped is not None:
        pipe_onto_stdin(run.piped)
    reads = count_context_reads(monkeypatch)

    exit_code = run_cli(run.argv, capsys).status

    assert (exit_code, *reads.drain()) == (
        run.exit_code,
        run.toplevel_reads,
        run.config_reads,
        run.observations,
    )


@dataclass(frozen=True)
class _LaneLookupCase:
    cell: str
    command: str = "release"
    branch: str = "dependabot/x"
    holder: str = "lane"
    agent: str = "Ada"
    merged: bool = False
    trailer: str = "No-Item: fix"
    source: str = "dependabot/x"
    as_json: bool = False
    refusal: str | None = None
    reads_once: bool = False
    exact: bool = True
    claim_id: str | None = None
    merged_ref: str = "12"
    state_ref: bool = False
    landing_merged: bool = True
    issue_claim_lands_during_verification: bool = False
    no_forge_reads: bool = False
    nothing_left_worktree: str | None = None


def _lane_lookup_refusal(branch: str) -> str:
    return (
        f"branch '{branch}' is not an issueless lane; pass an issue number, or "
        "check out a branch prefixed 'docs/' or 'fix/'"
    )


_WORK_ITEM_TRAILER_REFUSAL = (
    f"merge commit {MERGE_COMMIT_SHA} of pull request #12 carries "
    "`Work-Item: #42`; an issue-less lane needs a "
    '`No-Item: <docs|fix|deps>` trailer; release it with --abandoned "landed as PR #12 '
    'with a malformed trailer"'
)

_LANE_LOOKUP_CASES = (
    _LaneLookupCase(
        "5", holder="none", refusal=_lane_lookup_refusal("dependabot/x"), reads_once=True
    ),
    _LaneLookupCase("6", holder="issue", refusal=_lane_lookup_refusal("dependabot/x")),
    _LaneLookupCase("8", merged=True),
    _LaneLookupCase(
        "9",
        merged=True,
        trailer="Work-Item: #42",
        refusal=_WORK_ITEM_TRAILER_REFUSAL,
    ),
    _LaneLookupCase(
        "10",
        merged=True,
        source="dependabot/y",
        refusal=(
            "lane 'dependabot/x' is claimed on 'dependabot/x', not on pull request #12's "
            "branch 'dependabot/y'; release that claim by itself"
        ),
    ),
    _LaneLookupCase(
        "11", holder="none", merged=True, nothing_left_worktree="kept -- release ran from inside it"
    ),
    _LaneLookupCase(
        "12",
        holder="none",
        merged=True,
        source="dependabot/y",
        refusal="lane 'dependabot/x' has no active build claim",
    ),
    _LaneLookupCase(
        "13",
        holder="none",
        merged=True,
        trailer="Work-Item: #42",
        refusal=_WORK_ITEM_TRAILER_REFUSAL,
    ),
    _LaneLookupCase(
        "14",
        holder="none",
        merged=True,
        landing_merged=False,
        refusal="pull request #12 is not merged",
    ),
    _LaneLookupCase(
        "15",
        holder="none",
        merged=True,
        claim_id="X",
        refusal=_lane_lookup_refusal("dependabot/x"),
    ),
    _LaneLookupCase(
        "16",
        holder="none",
        merged=True,
        merged_ref=MERGE_COMMIT_SHA,
        state_ref=True,
        refusal=_lane_lookup_refusal("dependabot/x"),
    ),
    _LaneLookupCase(
        "17",
        holder="issue",
        merged=True,
        refusal=_lane_lookup_refusal("dependabot/x"),
        no_forge_reads=True,
    ),
    _LaneLookupCase(
        "18",
        holder="none",
        merged=True,
        issue_claim_lands_during_verification=True,
        nothing_left_worktree="kept -- claimed again while this release ran",
    ),
    _LaneLookupCase("25", command="rescope"),
    _LaneLookupCase(
        "26", command="rescope", holder="none", refusal=_lane_lookup_refusal("dependabot/x")
    ),
    _LaneLookupCase(
        "27",
        command="rescope",
        agent="Bob",
        refusal="only the original claimant may rescope",
        exact=False,
    ),
    _LaneLookupCase(
        "28", command="claim", holder="none", refusal=_lane_lookup_refusal("dependabot/x")
    ),
    _LaneLookupCase("29", command="claim", refusal=_lane_lookup_refusal("dependabot/x")),
    _LaneLookupCase("30", branch="docs/x", reads_once=True),
    _LaneLookupCase(
        "32",
        branch="",
        holder="none",
        refusal=(
            "lane release requires a non-empty current branch; "
            "check out the docs/ or fix/ lane branch, or pass an issue number"
        ),
    ),
    _LaneLookupCase(
        "31",
        branch="docs/x",
        holder="none",
        merged=True,
        source="docs/x",
        nothing_left_worktree="kept -- release ran from inside it",
    ),
    _LaneLookupCase("33", as_json=True),
    _LaneLookupCase(
        "34",
        holder="none",
        merged=True,
        as_json=True,
        nothing_left_worktree="kept -- release ran from inside it",
    ),
    _LaneLookupCase(
        "38",
        branch="ada/issue-42",
        holder="none",
        merged=True,
        trailer="Work-Item: #42",
        source="ada/issue-42",
        refusal=_WORK_ITEM_TRAILER_REFUSAL,
    ),
    _LaneLookupCase("35", command="release-help"),
    _LaneLookupCase("36", command="rescope-help"),
    _LaneLookupCase("37", command="claim-help"),
)


def _arrange_lane_lookup_case(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: _LaneLookupCase
) -> FakeForge:
    standing = (
        ()
        if case.holder == "none"
        else (
            request(
                "mine",
                "Bob" if case.holder == "issue" else "Ada",
                issue=42 if case.holder == "issue" else None,
                branch=case.branch,
                scope=("a",),
            ),
        )
    )
    client = FakeForge()
    _patch_release_session(monkeypatch, client, *standing, agent=case.agent, branch=case.branch)
    toplevel = str(tmp_path) if case.state_ref else "/repo"
    if case.state_ref:
        _write_state_ref_pin(tmp_path)
    git_values = git_checkout(toplevel=toplevel, branch=case.branch)
    monkeypatch.setattr(
        checkout, "git_output", lambda arguments, **_kwargs: git_values[tuple(arguments)]
    )
    monkeypatch.setattr(checkout, "scope_directories", lambda paths, **_kwargs: ())
    if case.merged:
        monkeypatch.setattr(store, "list_worktrees", lambda _toplevel: (Path("/repo"),))
        client.landings[12] = landing_pull_request(
            body=case.trailer,
            merged=case.landing_merged,
            head_ref_name=case.source,
            base_ref_name="main",
        )
        work_items = ("#42",) if case.trailer == "Work-Item: #42" else ()
        classification = workboard.trunk_commit_classification(
            work_items, () if work_items else ("fix",)
        )
        monkeypatch.setattr(
            checkout,
            "trunk_landings",
            lambda *_args, **_kwargs: (_trunk_landing(MERGE_COMMIT_SHA, classification),),
        )
    else:
        forbid_forge_resolution(monkeypatch)
    if case.issue_claim_lands_during_verification:
        _claim_the_branch_while_the_landing_verifies(monkeypatch, client, case.branch)
    return client


def _claim_the_branch_while_the_landing_verifies(
    monkeypatch: pytest.MonkeyPatch, client: FakeForge, branch: str
) -> None:
    """Bob's issue claim #42 on `branch` appears in the claim state once the
    forge was asked about the landing: after the release's first read."""
    verified_landing = client.landing
    fetch_state = store.fetch_state
    verified = []
    holder = store_claim_from_request(request("bob", "Bob", issue=42, branch=branch, scope=("a",)))

    def landing_while_a_claim_lands(number: int) -> forge.Landing:
        verified.append(number)
        return verified_landing(number)

    def state_with_the_landed_claim(*, worktree: Path, remote: str) -> protocol.ClaimState:
        state = fetch_state(worktree=worktree, remote=remote)
        if not verified:
            return state
        return replace(state, claims={protocol.claim_key(holder.identity, branch): holder})

    monkeypatch.setattr(client, "landing", landing_while_a_claim_lands)
    monkeypatch.setattr(store, "fetch_state", state_with_the_landed_claim)


def _lane_lookup_arguments(case: _LaneLookupCase) -> list[str]:
    if case.command == "claim":
        return ["claim", "--scope", "a"]
    if case.command == "rescope":
        return ["rescope", "--add", "/repo/f"]
    branch_flags = ["--branch", case.branch] if case.branch else []
    outcome = ["--merged", case.merged_ref] if case.merged else ["--abandoned", "R"]
    return [
        "release",
        *branch_flags,
        *outcome,
        *(["--claim-id", case.claim_id] if case.claim_id else []),
        *(["--json"] if case.as_json else []),
    ]


def _nothing_left_output(case: _LaneLookupCase, output: str) -> tuple[str, str]:
    """REL-47's report as `(outcome, worktree)`, human lines or `--json` envelope."""
    if case.as_json:
        envelope = json.loads(output)
        assert (envelope["ok"], envelope["reason"], envelope["lane"], envelope["branch"]) == (
            True,
            "merged",
            True,
            case.branch,
        )
        return envelope["outcome"], envelope["worktree"]
    landed, worktree = output.splitlines()
    assert landed == "LANDED pull request #12 already; nothing left to release"
    return "nothing left to release", worktree.removeprefix("worktree: ")


def _assert_lane_lookup_help(case: _LaneLookupCase, capsys: pytest.CaptureFixture[str]) -> None:
    command = case.command.removesuffix("-help")
    with pytest.raises(SystemExit) as exited:
        issue_claim.main([command, "--help"])
    assert exited.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    expected = {
        "claim": "omit for lane mode, derived from a docs/ or fix/ checkout branch",
        "release": (
            "omit for lane mode: a docs/ or fix/ branch, one holding a live lane claim, or a "
            "github --merged rerun on a branch no claim holds"
        ),
        "rescope": "omit for lane mode: a docs/ or fix/ branch, or one holding a live lane claim",
    }[command]
    assert expected in help_text


@pytest.mark.parametrize("case", _LANE_LOOKUP_CASES, ids=lambda case: case.cell)
def test_lane_mode_outside_docs_and_fix_resolves_only_an_existing_claim(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    case: _LaneLookupCase,
) -> None:
    if case.command.endswith("-help"):
        _assert_lane_lookup_help(case, capsys)
        return
    client = _arrange_lane_lookup_case(monkeypatch, tmp_path, case)
    before = store.fetch_state(worktree=Path("."), remote="origin").claims
    reads = count_context_reads(monkeypatch)
    status = issue_claim.main(["--repo", REPOSITORY, *_lane_lookup_arguments(case)])
    captured = capsys.readouterr()
    if case.reads_once:
        assert sum(reads.observations.values()) == 1
    if case.no_forge_reads:
        assert client.requests == 0
    after = store.fetch_state(worktree=Path("."), remote="origin").claims
    assert status == (2 if case.refusal else 0)
    if case.refusal:
        if case.exact:
            assert captured.err == f"ERROR: {case.refusal}\n"
        else:
            assert case.refusal in captured.err
        assert after == before
    elif case.command == "rescope":
        assert _live_store_claim().scope == ("a", "f")
        assert captured.out.startswith("RESCOPED lane dependabot/x: mine")
    elif case.nothing_left_worktree:
        assert _nothing_left_output(case, captured.out) == (
            "nothing left to release",
            case.nothing_left_worktree,
        )
        assert bool(after) is case.issue_claim_lands_during_verification
    else:
        assert after == {}
        if case.as_json:
            envelope = json.loads(captured.out)
            assert envelope["ok"] is True
            assert envelope["reason"] == "abandoned"
            assert envelope["lane"] is True
        else:
            assert captured.out.startswith(f"RELEASED lane {case.branch}: mine\n")
            if case.merged:
                assert "worktree: kept -- release ran from inside it\n" in captured.out
