"""`aco release` of a claim that holds stored runs, through the CLI on real git under both
storages: the trailers come from the runs, `--record` beside them refuses, and a runs file that
changed after the release read it refuses (`specs/lane-record.spec.md`, "Stored runs")."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, write_repository_config
from claim_worktrees import assert_json_refusal_object
from cli_fixtures import real_git, run_cli
from github_fixtures import WORK_ITEM_ISSUE
from lane_record_fixtures import LANE_BRANCH, LANE_RECORD_TRAILERS, ROUTING
from lane_record_runs_world import (
    FIRST_RUN,
    LANDING_CLAIM_ID,
    OTHER_AGENT,
    SECOND_RUN,
    SUMMED_TRAILERS,
    World,
    a_run_stored_late,
    add_arguments,
    begin_arguments,
    commit_on,
    commit_runs_file,
    race_before_the_push,
    routing_trailers_of,
    stale_runs_sentence,
    standing_claims_of,
    two_chained_runs,
)
from merged_release import arrange_merged_pull_request, seed_open_item
from store_fixtures import state_ref_tip

from aco import lane_runs, protocol, store
from aco.routing_line import RoutingStage

ROUTING_LINE_TRAILERS = (
    "lane_build: sonnet-5.5/high",
    "lane_fix: none",
    "lane_review: opus-5.5/medium",
    "lane_test: sonnet-5.5/medium",
    "lane_gate: none",
    "lane_land: haiku-5.5/low",
    "lane_fix_rounds: 1",
    "lane_blocking: 1",
    "lane_experiment: builder-sonnet",
)


@pytest.fixture
def world(lane_record_runs_world: World) -> World:
    return lane_record_runs_world


def store_one_run(world: World, capsys: pytest.CaptureFixture[str]) -> str:
    """Run one stored with the claim, ending at a real commit; its end tip."""
    end_tip = commit_on(world.directory, "one.txt")
    world.run(capsys, *begin_arguments(world, FIRST_RUN))
    world.run(capsys, *add_arguments(world, FIRST_RUN, end_tip=end_tip))
    return end_tip


def store_two_runs(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Two runs with the same record, the second following the first."""
    first_end = store_one_run(world, capsys)
    second_end = commit_on(world.directory, "two.txt")
    world.run(capsys, *begin_arguments(world, SECOND_RUN, "--start-tip", first_end))
    world.run(capsys, *add_arguments(world, SECOND_RUN, end_tip=second_end))


def abandon(
    world: World, capsys: pytest.CaptureFixture[str], reason: str, *flags: str
) -> tuple[int | str | None, str, str]:
    result = world.run(capsys, "release", world.item, "--abandoned", reason, *flags)
    return result.status, result.stdout, result.stderr


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param("stopped for the day", id="a-reason-without-a-routing-line"),
        pytest.param(ROUTING, id="a-routing-line-in-the-reason"),
    ],
)
def test_two_stored_runs_write_the_summed_trailers_and_the_runs_file_goes(
    world: World, capsys: pytest.CaptureFixture[str], reason: str
) -> None:
    """Spec: LANREC-90, REL-67. Example: E-LANREC-17."""
    store_two_runs(world, capsys)

    status, _stdout, stderr = abandon(world, capsys, reason)

    assert (status, stderr) == (0, "")
    assert routing_trailers_of(world.remote) == SUMMED_TRAILERS
    assert world.runs_files() == []


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        pytest.param(None, ROUTING_LINE_TRAILERS, id="the-routing-line"),
        pytest.param("file", LANE_RECORD_TRAILERS, id="the-record-file"),
    ],
)
def test_a_release_without_a_runs_file_writes_the_record_files_trailers_else_the_routing_lines(
    world: World,
    capsys: pytest.CaptureFixture[str],
    record: str | None,
    expected: tuple[str, ...],
) -> None:
    """Spec: LANREC-42, LANREC-50."""
    flags = () if record is None else ("--record", str(world.record_file()))

    status, _stdout, stderr = abandon(world, capsys, ROUTING, *flags)

    assert (status, stderr) == (0, "")
    assert routing_trailers_of(world.remote) == expected


def test_one_run_that_ran_the_stages_its_record_states_writes_the_trailers_of_that_file(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-90, REL-67."""
    ran = (RoutingStage.BUILD, RoutingStage.REVIEW, RoutingStage.TEST)
    world.run(capsys, *begin_arguments(world, FIRST_RUN))
    world.run(capsys, *add_arguments(world, FIRST_RUN, stages=ran))

    status, _stdout, stderr = abandon(world, capsys, "stopped")

    assert (status, stderr) == (0, "")
    assert routing_trailers_of(world.remote) == LANE_RECORD_TRAILERS


def store_unreadable_runs(world: World, _capsys: pytest.CaptureFixture[str]) -> None:
    world.store_runs_file(b"not json")


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(store_one_run, id="runs"),
        pytest.param(store_unreadable_runs, id="a-runs-file-that-is-not-the-stored-shape"),
    ],
)
def test_stored_runs_beside_a_record_file_refuse_before_anything_is_written(
    world: World,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[[World, pytest.CaptureFixture[str]], object],
) -> None:
    """Spec: LANREC-91, LANREC-93. Example: E-LANREC-18."""
    arrange(world, capsys)
    tip = world.state_tip()
    flags = ("--record", str(world.record_file()), "--json")

    status, stdout, stderr = abandon(world, capsys, "stopped", *flags)

    assert status == 2
    assert_json_refusal_object(stderr, stdout, reason="precondition_failed")
    assert stderr.splitlines()[0] == (
        f"ERROR: {world.label} has stored runs, so aco computes its record from them; drop --record"
    )
    assert world.state_tip() == tip
    assert len(standing_claims_of(world)) == 1
    assert len(world.runs_files()) == 1


def store_a_begun_run(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.run(capsys, *begin_arguments(world, FIRST_RUN))


def store_a_second_run_that_does_not_follow(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    store_one_run(world, capsys)
    world.run(capsys, *begin_arguments(world, SECOND_RUN, "--start-tip", "f" * 40))
    world.run(capsys, *add_arguments(world, SECOND_RUN))


@pytest.mark.parametrize(
    ("arrange", "expected"),
    [
        pytest.param(store_a_begun_run, (), id="a-run-begun-and-never-added"),
        pytest.param(
            store_a_second_run_that_does_not_follow,
            (
                "lane_build: sonnet-5.5/high",
                "lane_review: opus-5.5/medium",
                "lane_land: haiku-5.5/low",
                "lane_risk: normal",
            ),
            id="a-second-run-that-does-not-follow",
        ),
    ],
)
def test_a_lane_with_a_lost_run_writes_the_stage_lines_the_rules_know_and_no_counted_line(
    world: World,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[[World, pytest.CaptureFixture[str]], object],
    expected: tuple[str, ...],
) -> None:
    """Spec: LANREC-94. Example: E-LANREC-19."""
    arrange(world, capsys)

    status, _stdout, stderr = abandon(world, capsys, ROUTING)

    assert (status, stderr) == (0, "")
    assert routing_trailers_of(world.remote) == expected


def test_a_runs_file_that_is_not_the_stored_shape_releases_with_every_routing_figure_unknown(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-93."""
    world.store_runs_file(b"not json")

    status, _stdout, stderr = abandon(world, capsys, ROUTING)

    assert (status, stderr) == (0, "")
    assert routing_trailers_of(world.remote) == ()
    assert world.runs_files() == []


def test_a_runs_file_with_no_entry_leaves_the_record_files_figures_and_goes(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-90."""
    world.store_runs_file(lane_runs.serialize_runs(lane_runs.RunsFile()))

    status, _stdout, stderr = abandon(
        world, capsys, "stopped", "--record", str(world.record_file())
    )

    assert (status, stderr) == (0, "")
    assert routing_trailers_of(world.remote) == LANE_RECORD_TRAILERS
    assert world.runs_files() == []


def test_a_run_added_between_the_read_and_the_push_refuses_and_the_rerun_sums_it(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: LANREC-92."""
    store_one_run(world, capsys)
    race_before_the_push(
        monkeypatch,
        a_run_stored_late(world.directory, "origin", world.claim().claim_id, SECOND_RUN),
    )

    status, stdout, stderr = abandon(world, capsys, "stopped", "--json")

    assert status == 2
    assert_json_refusal_object(stderr, stdout, reason="precondition_failed")
    assert stderr.splitlines()[0] == f"ERROR: {stale_runs_sentence(world.label)}"
    assert len(standing_claims_of(world)) == 1
    assert len(world.runs_files()) == 1

    rerun_status, _stdout, rerun_stderr = abandon(world, capsys, "stopped")

    assert (rerun_status, rerun_stderr) == (0, "")
    assert routing_trailers_of(world.remote) == SUMMED_TRAILERS


def test_a_run_begun_on_a_claim_that_had_none_between_the_read_and_the_push_refuses(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: LANREC-92."""
    race_before_the_push(
        monkeypatch,
        lambda: world.store_runs_file(
            lane_runs.serialize_runs(lane_runs.RunsFile((lane_runs.RunEntry("late", None, True),))),
        ),
    )

    status, _stdout, stderr = abandon(world, capsys, "stopped")

    assert status == 2
    assert stderr == f"ERROR: {stale_runs_sentence(world.label)}\n"
    assert len(world.runs_files()) == 1


def test_a_write_to_another_claim_between_the_read_and_the_push_is_applied_over(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: LANREC-92."""
    store_two_runs(world, capsys)
    other = protocol.ClaimIntent(
        identity=protocol.IssueIdentity(7),
        agent="Cleo",
        role="builder",
        base=world.claim().base,
        branch="claude/issue-7-cut",
        scope=("docs",),
        claim_id=protocol.ClaimId("other"),
        operation_id="op-other",
    )
    race_before_the_push(monkeypatch, lambda: world.commit_state(other))

    status, _stdout, stderr = abandon(world, capsys, "stopped")

    assert (status, stderr) == (0, "")
    assert routing_trailers_of(world.remote) == SUMMED_TRAILERS


def test_the_new_holder_after_a_handover_releases_with_the_summed_trailers(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-90."""
    store_two_runs(world, capsys)
    world.commit_state(
        protocol.HandoverIntent(
            claim_id=world.claim().claim_id,
            previous_agent="Ada",
            agent=OTHER_AGENT,
            operation_id="op-handover",
        )
    )

    status, _stdout, stderr = abandon(world, capsys, "stopped", "--agent", OTHER_AGENT)

    assert (status, stderr) == (0, "")
    assert routing_trailers_of(world.remote) == SUMMED_TRAILERS


def test_a_coordinator_override_releases_with_the_summed_trailers(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-90."""
    store_two_runs(world, capsys)
    override = ("--coordinator-override", "--role", "coordinator", "--agent", "Fleet Coordinator")

    status, _stdout, stderr = abandon(world, capsys, "verified abandoned", *override)

    assert (status, stderr) == (0, "")
    assert routing_trailers_of(world.remote) == SUMMED_TRAILERS


def test_the_run_commits_and_the_release_commit_count_one_lane(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-60."""
    store_two_runs(world, capsys)
    abandon(world, capsys, "stopped")

    stats = run_cli(["stats", "2000-01-01..2100-01-01", "tag:builder-sonnet", "--json"], capsys)

    assert json.loads(stats.stdout)["a"]["lanes"] == 1


def a_merged_lane_with_two_stored_runs(
    monkeypatch: pytest.MonkeyPatch,
    github_clone: Path,
    bare_remote: Path,
    *,
    identity: protocol.ClaimIdentity,
    trailers: tuple[str, ...],
) -> str:
    """The lane's pull request merged on the forge, its claim and two stored runs on the state
    ref, the checkout on the lane's branch; the merge commit."""
    merged = arrange_merged_pull_request(
        monkeypatch,
        github_clone,
        bare_remote,
        identity=identity,
        trailers=trailers,
        pull_request_body="",
        branch=LANE_BRANCH,
    )
    content = lane_runs.serialize_runs(two_chained_runs())
    commit_runs_file(github_clone, bare_remote, LANDING_CLAIM_ID, content)
    return merged.merge_commit


def test_a_merged_release_after_a_merge_made_elsewhere_writes_the_summed_trailers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: LANREC-90, REL-64."""
    a_merged_lane_with_two_stored_runs(
        monkeypatch,
        github_clone,
        bare_remote,
        identity=protocol.LaneIdentity(),
        trailers=("No-Item: docs",),
    )
    real_git(github_clone, "checkout", "-q", LANE_BRANCH)

    released = run_cli(["--repo", REPOSITORY, "release", "--merged", "12"], capsys)

    assert (released.status, released.stderr) == (0, "")
    assert routing_trailers_of(bare_remote) == SUMMED_TRAILERS
    assert real_git(bare_remote, "ls-tree", "-r", store.STATE_REF).stdout.count("runs/") == 0


def test_a_state_ref_release_of_a_merged_commit_closes_the_item_and_drops_the_runs_in_one_commit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: LANREC-90, REL-64."""
    merge_commit = a_merged_lane_with_two_stored_runs(
        monkeypatch,
        github_clone,
        bare_remote,
        identity=protocol.IssueIdentity(WORK_ITEM_ISSUE),
        trailers=(f"Work-Item: #{WORK_ITEM_ISSUE}",),
    )
    seed_open_item(github_clone, bare_remote)
    real_git(github_clone, "pull", "-q", "--ff-only", "origin", "main")
    write_repository_config(github_clone, 'storage = "state-ref"\n')
    real_git(github_clone, "checkout", "-q", LANE_BRANCH)
    tip_before = state_ref_tip(bare_remote)

    released = run_cli(
        ["release", str(WORK_ITEM_ISSUE), "--agent", "Ada", "--merged", merge_commit], capsys
    )

    assert (released.status, released.stderr) == (0, "")
    shown = run_cli(["item", "show", str(WORK_ITEM_ISSUE)], capsys)
    assert " · closed · " in shown.stdout.splitlines()[0]
    assert routing_trailers_of(bare_remote) == SUMMED_TRAILERS
    assert real_git(bare_remote, "ls-tree", "-r", store.STATE_REF).stdout.count("runs/") == 0
    assert (
        real_git(bare_remote, "rev-list", "--count", f"{tip_before}..{store.STATE_REF}").stdout
        == "1\n"
    )
