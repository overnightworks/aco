"""The figures a release states and the runs file it expects (`specs/lane-record.spec.md`,
"Stored runs"): the stored runs when the claim has any, else the record file, else the routing
line, against a real repository that holds the runs blobs."""

import json
from pathlib import Path

import pytest
from board_fixtures import standing_active_claim
from cli_fixtures import FROZEN_CLI_NOW, real_repository_with_bare_remote
from lane_record_fixtures import (
    LANE_RECORD_TRAILERS,
    ROUTING,
    four,
    lane_record_object,
    release_written_of,
)
from lane_run_entries import added, begun, not_following

from aco import lane_record, lane_runs, protocol, store, workboard

OUTCOME = "lane_outcome: abandoned"
REASON_ROUTING_TRAILERS = (
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
TWO_CHAINED_RUNS_TRAILERS = (
    "lane_build: build-x/low",
    "lane_fix: none",
    "lane_review: review-y/low",
    "lane_test: none",
    "lane_gate: none",
    "lane_land: land-y/low",
    "lane_fix_rounds: 6",
    "lane_blocking: 8",
    "lane_experiment: builder-sonnet",
    "lane_risk: routine",
    "lane_fix_rounds_review: 2",
    "lane_fix_rounds_gate: 0",
    "lane_fix_rounds_ci: 4",
    "lane_fix_rounds_test: 0",
    "lane_blocking_review: 6",
    "lane_blocking_gate: 0",
    "lane_blocking_ci: 2",
    "lane_blocking_test: 0",
    "lane_misses_review: 0",
    "lane_misses_gate: 0",
    "lane_misses_ci: 0",
    "lane_misses_test: 0",
)
BOTH_REFUSED = "{label} has stored runs, so aco computes its record from them; drop --record"


def two_chained_runs() -> tuple[lane_runs.RunEntry, ...]:
    return (
        added("run-1", "build", "review", marker="x"),
        added("run-2", "build", "review", marker="y"),
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    return real_repository_with_bare_remote(tmp_path)[0]


def blob_of(repository: Path, content: bytes) -> protocol.ObjectId:
    return store.hash_blob(repository, content)


def runs_blob(repository: Path, entries: tuple[lane_runs.RunEntry, ...]) -> protocol.ObjectId:
    return blob_of(repository, lane_runs.serialize_runs(lane_runs.RunsFile(entries)))


def record_file(**changes: object) -> lane_record.LaneRecordFile:
    return lane_record.parse_record_file(json.dumps(lane_record_object(**changes)).encode())


def release(
    repository: Path,
    stored: protocol.ObjectId | None,
    *,
    record: lane_record.LaneRecordFile | None = None,
    lane: bool = False,
) -> tuple[tuple[str, ...], protocol.ObjectId | None]:
    """The trailers and the expected runs blob of an abandoned release, with the routing line in
    its reason, of a claim whose runs file in the observation is `stored`."""
    claim = standing_active_claim(lane=lane)
    written = release_written_of(
        toplevel=repository,
        config=workboard.BoardConfig(),
        tip=None,
        now=FROZEN_CLI_NOW,
        claim=claim,
        outcome=protocol.AbandonedRelease(ROUTING),
        record_file=record,
        stored_runs={} if stored is None else {claim.claim_id: stored},
    )
    assert isinstance(written.intent, protocol.ReleaseIntent)
    return written.subject.trailers, written.intent.expected_runs


@pytest.mark.parametrize(
    ("entries", "record", "expected"),
    [
        pytest.param(
            two_chained_runs(), None, TWO_CHAINED_RUNS_TRAILERS, id="stored-runs-beat-the-reason"
        ),
        pytest.param((), None, REASON_ROUTING_TRAILERS, id="a-runs-file-with-no-entry-is-none"),
        pytest.param(
            (), record_file(), LANE_RECORD_TRAILERS, id="a-runs-file-with-no-entry-and-a-file"
        ),
        pytest.param(
            (begun("run-1"),), None, (), id="a-begun-run-without-a-record-states-no-figure"
        ),
        pytest.param(
            (added("run-1", "build", "review", marker="x"), begun("run-2")),
            None,
            ("lane_build: build-x/low",),
            id="a-run-begun-after-an-added-one-leaves-its-build-stage",
        ),
        pytest.param(
            (
                added("run-1", "build", "review", marker="x"),
                not_following("run-2", "build", "review", marker="y"),
            ),
            None,
            (
                "lane_build: build-x/low",
                "lane_review: review-y/low",
                "lane_land: land-y/low",
                "lane_risk: routine",
            ),
            id="a-run-that-does-not-follow-leaves-no-count-total-or-experiment",
        ),
    ],
)
def test_a_release_states_the_figures_of_the_stored_runs_and_expects_their_blob(
    repository: Path,
    entries: tuple[lane_runs.RunEntry, ...],
    record: lane_record.LaneRecordFile | None,
    expected: tuple[str, ...],
) -> None:
    """Spec: LANREC-90, LANREC-94."""
    stored = runs_blob(repository, entries)

    trailers, expected_runs = release(repository, stored, record=record)

    assert trailers == (OUTCOME, *expected)
    assert expected_runs == stored


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        pytest.param(None, REASON_ROUTING_TRAILERS, id="the-routing-line"),
        pytest.param(record_file(), LANE_RECORD_TRAILERS, id="the-record-file"),
    ],
)
def test_a_release_of_a_claim_without_a_runs_file_states_the_record_file_else_the_reason(
    repository: Path,
    record: lane_record.LaneRecordFile | None,
    expected: tuple[str, ...],
) -> None:
    """Spec: LANREC-13, LANREC-42, LANREC-50."""
    trailers, expected_runs = release(repository, None, record=record)

    assert trailers == (OUTCOME, *expected)
    assert expected_runs is None


def test_the_per_stage_sums_clamp_at_999_before_the_total_which_does_not(
    repository: Path,
) -> None:
    """Spec: LANREC-90."""
    entries = (
        added("run-1", "build", "review", fix_rounds=four(600, 600, 600, 600)),
        added("run-2", "build", "review", fix_rounds=four(600, 600, 600, 600)),
    )

    trailers, _expected_runs = release(repository, runs_blob(repository, entries))

    assert "lane_fix_rounds_review: 999" in trailers
    assert "lane_fix_rounds: 3996" in trailers


@pytest.mark.parametrize(
    ("lane", "label"),
    [
        pytest.param(False, "#72", id="an-issue-claim"),
        pytest.param(True, "cli-claim", id="an-issue-less-lane-names-its-claim-id"),
    ],
)
@pytest.mark.parametrize(
    "content",
    [
        pytest.param(lane_runs.serialize_runs(lane_runs.RunsFile(two_chained_runs())), id="runs"),
        pytest.param(b"not json", id="an-unreadable-file"),
    ],
)
def test_stored_runs_and_a_record_file_together_refuse_naming_the_claim(
    repository: Path, lane: bool, label: str, content: bytes
) -> None:
    """Spec: LANREC-91, LANREC-93."""
    blob = blob_of(repository, content)
    record = record_file()

    with pytest.raises(protocol.ClaimUnavailableError) as refusal:
        release(repository, blob, record=record, lane=lane)

    assert str(refusal.value) == BOTH_REFUSED.format(label=label)


def test_the_refusal_of_both_names_the_item_in_the_form_the_storage_asks_for(
    repository: Path,
) -> None:
    """Spec: LANREC-91."""
    blob = runs_blob(repository, two_chained_runs())

    with pytest.raises(protocol.ClaimUnavailableError) as refusal:
        release(repository, blob, record=record_file())

    assert refusal.value.named(lambda number: f"aco-{number:06d}") == BOTH_REFUSED.format(
        label="aco-000072"
    )


@pytest.mark.parametrize(
    "unreadable",
    [
        pytest.param(b"not json", id="not-json"),
        pytest.param(b'{"version": 1, "runs": "none"}', id="not-the-stored-shape"),
        pytest.param(None, id="a-blob-git-cannot-read"),
    ],
)
def test_a_runs_file_that_cannot_be_read_leaves_every_routing_figure_unknown_and_refuses_nothing(
    repository: Path, unreadable: bytes | None
) -> None:
    """Spec: LANREC-93."""
    stored = protocol.ObjectId("f" * 40) if unreadable is None else blob_of(repository, unreadable)

    trailers, expected_runs = release(repository, stored)

    assert trailers == (OUTCOME,)
    assert expected_runs == stored
