"""`aco land` of a claim that stores no run needs a lane record file, whatever the claim's kind
(`specs/lane-record.spec.md`, "What a landing needs")."""

from dataclasses import replace
from pathlib import Path

import pytest
from adoption_world import AdoptionWorld, adopt, adopted_claim, the_forge_reads_the_branch_ready
from cli_fixtures import ADOPTED_PULL_REQUEST, run_cli
from github_fixtures import (
    LaneLandingWorld,
    arrange_follow_up_failures,
    landed_world,
    serve_forge,
)
from landing_refusals import refusal_observations
from lane_record_fixtures import land_arguments_with_record
from queue_forge import LANDS, QueueForge

from aco import cmd_land_queue, forge, protocol

NUMBER = 12
LANE_BRANCH = "fix/lane"
FOREIGN_BODY = "No-Item: fix"


def no_lane_record(label: str, reviewed: str) -> str:
    return (
        f"{label} has no lane record (no stored runs, no --record), "
        f"so no review is known to have judged {reviewed}"
    )


@pytest.fixture
def lane(
    github_clone: Path, bare_remote: Path, monkeypatch: pytest.MonkeyPatch
) -> LaneLandingWorld:
    return landed_world(github_clone, bare_remote, monkeypatch, stored_run=False).landing


def test_a_landing_of_a_claim_with_no_stored_run_and_no_record_file_refuses_before_any_write(
    lane: LaneLandingWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-100, LANDCMD-78. Example: E-LANREC-22."""
    capsys.readouterr()

    result = run_cli(["land", str(NUMBER), "--head", lane.head], capsys)

    observed, expected = refusal_observations(lane, result, no_lane_record("#72", lane.head))
    assert observed == expected


def test_the_same_landing_with_a_record_file_merges(
    lane: LaneLandingWorld, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-100. Example: E-LANREC-22."""
    result = run_cli(["land", *land_arguments_with_record(tmp_path, lane.head, NUMBER)], capsys)

    assert (result.status, result.stderr, lane.forge.landings[NUMBER].merged) == (0, "", True)


def test_a_rerun_of_a_merged_pull_request_needs_no_record_file(
    lane: LaneLandingWorld, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-101, LANDCMD-78 -- the rerun judges the claim nowhere."""
    arrange_follow_up_failures(lane.forge, None, "branch deletion failed")
    merged = run_cli(["land", *land_arguments_with_record(tmp_path, lane.head, NUMBER)], capsys)
    lane.forge.delete_error = None

    rerun = run_cli(["land", str(NUMBER), "--head", lane.head], capsys)

    assert (merged.status, rerun.status, rerun.stderr) == (2, 0, "")


def test_a_rerun_of_a_queued_pull_request_needs_no_record_file(
    lane: LaneLandingWorld, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-101, LANDCMD-78 -- the queue merges the pull request, the rerun waits."""
    monkeypatch.setattr(cmd_land_queue, "pause_between_queue_reads", [].append)
    queue = QueueForge.over(lane.forge)
    queue.closes_on_merge = True
    queue.queue_branches = {"main"}
    queue.queue_states[NUMBER] = forge.QueuedPullRequest()
    queue.queue_reads = {NUMBER: [forge.QueuedPullRequest(), LANDS]}
    queue.landings[NUMBER] = replace(queue.landings[NUMBER], body="Closes #72\n\nWork-Item: #72\n")
    serve_forge(monkeypatch, queue)

    result = run_cli(["land", str(NUMBER), "--head", lane.head], capsys)

    assert (result.status, queue.landings[NUMBER].merged) == (0, True)


def test_a_claim_held_by_another_agent_refuses_for_its_holder_not_for_the_missing_record(
    lane: LaneLandingWorld, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANDCMD-78, LANDCMD-10, LANREC-100 -- the holder is judged first."""
    monkeypatch.setenv("ACO_AGENT", "Bea")

    result = run_cli(["land", str(NUMBER), "--head", lane.head], capsys)

    assert (result.status, result.stderr.startswith("ERROR: only the original claimant")) == (
        2,
        True,
    )


@pytest.fixture
def issue_less_lane(
    github_clone: Path, bare_remote: Path, monkeypatch: pytest.MonkeyPatch
) -> LaneLandingWorld:
    return landed_world(
        github_clone,
        bare_remote,
        monkeypatch,
        identity=protocol.LaneIdentity(),
        branch=LANE_BRANCH,
        body=FOREIGN_BODY,
        stored_run=False,
    ).landing


def test_an_issue_less_lane_lands_with_a_record_file(
    issue_less_lane: LaneLandingWorld, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-102."""
    result = run_cli(
        ["land", *land_arguments_with_record(tmp_path, issue_less_lane.head, NUMBER)], capsys
    )

    assert (result.status, result.stderr) == (0, "")


def test_an_issue_less_lane_without_a_record_file_refuses_and_names_its_claim_id(
    issue_less_lane: LaneLandingWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-102, LANREC-100."""
    result = run_cli(["land", str(NUMBER), "--head", issue_less_lane.head], capsys)

    assert result.stderr == f"ERROR: {no_lane_record('landing', issue_less_lane.head)}\n"


def test_an_adopted_lane_without_a_record_file_refuses_before_any_write(
    world: AdoptionWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-102, LANREC-100 -- `aco adopt --no-item` stores no run."""
    world.forge.merge_remote = world.remote
    adopt(capsys).expect_success()
    the_forge_reads_the_branch_ready(world)
    claim = adopted_claim(world)
    before = world.effects()

    result = run_cli(["land", str(ADOPTED_PULL_REQUEST), "--head", world.head], capsys)

    sentence = no_lane_record(str(claim.claim_id), world.head)
    assert (result.status, result.stderr, world.effects()) == (2, f"ERROR: {sentence}\n", before)
