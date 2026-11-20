"""`aco land` of a lane whose claim holds stored runs: its release writes the trailers from the
runs, refuses `--record` beside them and refuses when the runs changed after it read them
(`specs/lane-record.spec.md`, "Stored runs")."""

import re
from pathlib import Path

import pytest
from cli_fixtures import real_git, run_cli
from github_fixtures import LaneLandingWorld, landed_world
from lane_record_fixtures import lane_record_object, write_lane_record_file
from lane_record_runs_world import (
    LANDING_CLAIM_ID,
    SUMMED_TRAILERS,
    a_run_stored_late,
    commit_runs_file,
    race_before_the_push,
    routing_trailers_of,
    stale_runs_sentence,
    two_chained_runs,
)

from aco import lane_runs, store

RELEASE_AGAIN = ["release", "72", "--merged", "12", "--branch", "codex/issue-72-claims"]


@pytest.fixture
def lane(
    github_clone: Path, bare_remote: Path, monkeypatch: pytest.MonkeyPatch
) -> LaneLandingWorld:
    landing = landed_world(github_clone, bare_remote, monkeypatch).landing
    content = lane_runs.serialize_runs(two_chained_runs())
    commit_runs_file(landing.clone, landing.remote, LANDING_CLAIM_ID, content)
    return landing


def runs_files_in_state(lane: LaneLandingWorld) -> int:
    return real_git(lane.remote, "ls-tree", "-r", store.STATE_REF).stdout.count("runs/")


def follow_up_incomplete(release_refusal: str) -> str:
    """What `aco land` prints when the merge landed and its release refused with
    `release_refusal`."""
    return (
        "ERROR: MERGED pull request #12 as <sha>; follow-up incomplete: "
        f"release ({release_refusal}); re-run aco land 12 --head <sha>\n"
    )


def printed_without_the_merge_sha(stderr: str) -> str:
    return re.sub(r"as [0-9a-f]{40};", "as <sha>;", stderr)


def test_a_landing_of_a_claim_with_stored_runs_writes_the_summed_trailers_and_drops_the_runs(
    lane: LaneLandingWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-90, REL-64."""
    result = run_cli(["land", "12", "--head", lane.head], capsys)

    assert (result.status, result.stderr) == (0, "")
    assert routing_trailers_of(lane.remote) == SUMMED_TRAILERS
    assert runs_files_in_state(lane) == 0


def test_a_run_added_between_the_releases_read_and_its_push_ends_the_landing_and_the_rerun_sums_it(
    lane: LaneLandingWorld, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: LANREC-92 -- the merge stands; the claim and its runs stay until the rerun."""
    race_before_the_push(
        monkeypatch, a_run_stored_late(lane.clone, lane.remote, LANDING_CLAIM_ID, "run-3")
    )

    refused = run_cli(["land", "12", "--head", lane.head], capsys)

    assert (refused.status, printed_without_the_merge_sha(refused.stderr)) == (
        2,
        follow_up_incomplete(stale_runs_sentence("#72")),
    )
    assert runs_files_in_state(lane) == 1

    rerun = run_cli(["land", "12", "--head", lane.head], capsys)

    assert (rerun.status, rerun.stderr) == (0, "")
    assert {"lane_fix_rounds: 9", "lane_blocking: 12"} <= set(routing_trailers_of(lane.remote))
    assert runs_files_in_state(lane) == 0


def test_a_landing_with_stored_runs_and_a_record_file_merges_then_a_plain_release_completes(
    lane: LaneLandingWorld, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-91 -- the refusal comes after the merge; a release without `--record`
    completes."""
    verdicts = [{"stage": "gate", "verdict": "approve", "sha": lane.head}]
    record = write_lane_record_file(tmp_path, lane_record_object(verdicts=verdicts))

    refused = run_cli(["land", "12", "--head", lane.head, "--record", str(record)], capsys)

    sentence = "#72 has stored runs, so aco computes its record from them; drop --record"
    assert (refused.status, printed_without_the_merge_sha(refused.stderr)) == (
        2,
        follow_up_incomplete(sentence),
    )
    assert runs_files_in_state(lane) == 1

    released = run_cli(RELEASE_AGAIN, capsys)

    assert (released.status, released.stderr) == (0, "")
    assert routing_trailers_of(lane.remote) == SUMMED_TRAILERS
    assert runs_files_in_state(lane) == 0
