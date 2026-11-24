"""`aco land --record FILE` lands with the record file's figures, or refuses before it merges."""

from dataclasses import replace
from pathlib import Path

import pytest
from cli_fixtures import run_cli
from github_fixtures import MERGE_COMMIT_SHA, LaneLandingWorld, landed_world
from landing_refusals import refusal_observations
from lane_record_fixtures import (
    LANE_RECORD_TRAILERS,
    lane_record_object,
    write_lane_record_file,
)
from store_fixtures import lane_trailers


@pytest.fixture
def lane(
    github_clone: Path, bare_remote: Path, monkeypatch: pytest.MonkeyPatch
) -> LaneLandingWorld:
    return landed_world(github_clone, bare_remote, monkeypatch, stored_run=False).landing


def verdict_on(sha: str) -> list[dict[str, str]]:
    return [{"stage": "gate", "verdict": "approve", "sha": sha}]


def test_a_landing_with_a_record_writes_the_record_s_trailers(
    lane: LaneLandingWorld, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-42, LANREC-43."""
    record = write_lane_record_file(tmp_path, lane_record_object(verdicts=verdict_on(lane.head)))

    result = run_cli(["land", "12", "--head", lane.head, "--record", str(record)], capsys)

    trailers = lane_trailers(lane.remote)
    assert (result.status, result.stderr) == (0, "")
    assert trailers[:1] == ("lane_outcome: landed",)
    assert trailers[-len(LANE_RECORD_TRAILERS) :] == LANE_RECORD_TRAILERS


def test_a_landing_with_a_record_accepts_a_prefix_of_the_judged_head(
    lane: LaneLandingWorld, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-38 -- `--head` is a full sha or a prefix of at least 7 digits."""
    record = write_lane_record_file(tmp_path, lane_record_object(verdicts=verdict_on(lane.head)))

    result = run_cli(["land", "12", "--head", lane.head[:8], "--record", str(record)], capsys)

    assert (result.status, result.stderr) == (0, "")


@pytest.mark.parametrize("merged", [False, True], ids=["first-run", "rerun"])
def test_a_landing_whose_record_judged_another_head_refuses_before_any_write(
    lane: LaneLandingWorld,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    merged: bool,
) -> None:
    """Spec: LANREC-38, LANREC-40 -- nothing is merged, deleted or written."""
    other = "d" * 40
    record = write_lane_record_file(tmp_path, lane_record_object(verdicts=verdict_on(other)))
    if merged:
        landing = lane.forge.landings[12]
        lane.forge.landings[12] = replace(landing, merged=True, merge_commit=MERGE_COMMIT_SHA)
    capsys.readouterr()

    result = run_cli(["land", "12", "--head", lane.head, "--record", str(record)], capsys)

    sentence = f"the lane record's last verdict judged {other}, not the reviewed {lane.head}"
    observed, expected = refusal_observations(lane, result, sentence)
    assert observed == expected


def test_a_landing_whose_record_holds_no_verdict_refuses_before_any_write(
    lane: LaneLandingWorld, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-39, LANREC-40."""
    record = write_lane_record_file(tmp_path, lane_record_object(verdicts=[]))

    result = run_cli(["land", "12", "--head", lane.head, "--record", str(record)], capsys)

    sentence = "the lane record states no review or gate verdict, so it judged no head to land"
    observed, expected = refusal_observations(lane, result, sentence)
    assert observed == expected


def test_a_landing_whose_record_is_malformed_refuses_before_any_write(
    lane: LaneLandingWorld, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-31, LANREC-40."""
    record = write_lane_record_file(tmp_path, lane_record_object(version=2))

    result = run_cli(["land", "12", "--head", lane.head, "--record", str(record)], capsys)

    sentence = f"lane record {record} is invalid: version 2 is unknown; this aco reads version 1"
    observed, expected = refusal_observations(lane, result, sentence)
    assert observed == expected


@pytest.mark.parametrize("merged", [False, True], ids=["first-run", "rerun"])
@pytest.mark.parametrize("stage", ["review", "gate"])
def test_a_landing_whose_record_ends_in_a_revise_verdict_refuses_before_any_write(
    lane: LaneLandingWorld,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    stage: str,
    merged: bool,
) -> None:
    """Spec: LANREC-44, LANREC-40 -- nothing is merged, deleted or written."""
    verdicts = [
        {"stage": "review", "verdict": "approve", "sha": "d" * 40},
        {"stage": stage, "verdict": "revise", "sha": lane.head},
    ]
    record = write_lane_record_file(tmp_path, lane_record_object(verdicts=verdicts))
    if merged:
        landing = lane.forge.landings[12]
        lane.forge.landings[12] = replace(landing, merged=True, merge_commit=MERGE_COMMIT_SHA)
    capsys.readouterr()

    result = run_cli(["land", "12", "--head", lane.head, "--record", str(record)], capsys)

    sentence = f"the lane record's last verdict is revise at {stage}, not approve"
    observed, expected = refusal_observations(lane, result, sentence)
    assert observed == expected
