"""The figures a release states and the runs file it expects (`specs/lane-record.spec.md`,
"Stored runs"): the stored runs when the claim has any, else the record file, else the routing
line, against a real repository that holds the runs blobs."""

import dataclasses
import json
from pathlib import Path

import pytest
from board_fixtures import standing_active_claim
from cli_fixtures import FROZEN_CLI_NOW, real_repository_with_bare_remote
from lane_record_fixtures import (
    ROUTING,
    four,
    lane_record_object,
    release_written_of,
)
from lane_run_entries import added, begun

from aco import lane_record, lane_runs, protocol, release_record, store, workboard

OUTCOME = "lane_outcome: abandoned"
REVIEWED = "a" * 40
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


def test_a_run_begun_after_an_added_one_leaves_the_build_stage_of_the_added_one(
    repository: Path,
) -> None:
    """Spec: LANREC-94."""
    entries = (added("run-1", "build", "review", marker="x"), begun("run-2"))
    stored = runs_blob(repository, entries)

    trailers, expected_runs = release(repository, stored)

    assert trailers == (OUTCOME, "lane_build: build-x/low", "lane_risk: normal")
    assert expected_runs == stored


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


def test_the_refusal_of_both_names_an_issue_less_lane_by_its_claim_id(repository: Path) -> None:
    """Spec: LANREC-91."""
    blob = runs_blob(repository, two_chained_runs())
    record = record_file()

    with pytest.raises(protocol.ClaimUnavailableError) as refusal:
        release(repository, blob, record=record, lane=True)

    assert str(refusal.value) == BOTH_REFUSED.format(label="cli-claim")


@pytest.mark.parametrize(
    "unreadable",
    [
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


NO_LANE_RECORD = (
    "{label} has no lane record (no stored runs, no --record), "
    f"so no review is known to have judged {REVIEWED}"
)


def refusal_of_landing(
    repository: Path,
    stored: protocol.ObjectId | None,
    *,
    record: lane_record.LaneRecordFile | None = None,
    lane: bool = False,
) -> str | None:
    """The refusal of a landing of a claim whose runs file in the observation is `stored`, or
    `None` when it needs none."""
    claim = standing_active_claim(lane=lane)
    runs = {} if stored is None else {claim.claim_id: stored}
    observed = dataclasses.replace(protocol.EMPTY_STATE, runs=runs)
    try:
        release_record.require_lane_record(repository, observed, claim, record, REVIEWED)
    except protocol.ClaimUnavailableError as refusal:
        return str(refusal)
    return None


def test_a_claim_without_a_runs_file_and_without_a_record_file_has_no_lane_record(
    repository: Path,
) -> None:
    """Spec: LANREC-100."""
    refusal = refusal_of_landing(repository, None)

    assert refusal == NO_LANE_RECORD.format(label="#72")


def test_a_runs_file_without_an_entry_counts_as_no_stored_runs(repository: Path) -> None:
    """Spec: LANREC-100."""
    refusal = refusal_of_landing(repository, runs_blob(repository, ()))

    assert refusal == NO_LANE_RECORD.format(label="#72")


def test_an_issue_less_lane_is_named_by_its_claim_id(repository: Path) -> None:
    """Spec: LANREC-102."""
    refusal = refusal_of_landing(repository, None, lane=True)

    assert refusal == NO_LANE_RECORD.format(label="cli-claim")


@pytest.mark.parametrize("stored", [True, False], ids=["a-run-is-stored", "a-record-file"])
def test_a_claim_with_stored_runs_or_a_record_file_has_a_lane_record(
    repository: Path, stored: bool
) -> None:
    """Spec: LANREC-100."""
    blob = runs_blob(repository, two_chained_runs()) if stored else None
    record = None if stored else record_file()

    refusal = refusal_of_landing(repository, blob, record=record)

    assert refusal is None
