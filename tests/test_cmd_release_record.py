"""`aco release --abandoned --record FILE` releases with the record file's figures, or refuses
before it writes."""

import json
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY
from claim_worktrees import lane_held_by_ada, make_stand_in
from cli_fixtures import run_cli
from lane_record_fixtures import (
    LANE_BRANCH,
    LANE_RECORD_TRAILERS,
    ROUTING,
    lane_record_object,
    write_lane_record_file,
)
from store_fixtures import lane_trailers, state_ref_tip

LANE_RECORD_TRAILERS_WITHOUT_MISSES = tuple(
    line for line in LANE_RECORD_TRAILERS if not line.startswith("lane_misses_")
)


def record_without_misses() -> dict[str, object]:
    record = lane_record_object()
    del record["misses"]
    return record


@pytest.mark.parametrize(
    ("content", "expected_trailers"),
    [
        pytest.param(lane_record_object(), LANE_RECORD_TRAILERS, id="a-file-that-states-misses"),
        pytest.param(
            record_without_misses(),
            LANE_RECORD_TRAILERS_WITHOUT_MISSES,
            id="a-file-without-misses-writes-no-misses-line",
        ),
    ],
)
def test_an_abandoned_release_with_a_record_file_leaves_the_files_figures_not_the_reasons(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    github_clone: Path,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
    content: dict[str, object],
    expected_trailers: tuple[str, ...],
) -> None:
    """Spec: LANREC-41, LANREC-42, LANREC-43, LANREC-50 -- the reason's routing line is not
    read."""
    stand_in = make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, ("src/widget.py",))
    stand_in(branch=LANE_BRANCH, standing=lane_held_by_ada(LANE_BRANCH, ("src/widget.py",)))
    record = write_lane_record_file(tmp_path, content)

    release = ["--repo", REPOSITORY, "release", "--agent", "Ada", "--abandoned", ROUTING]

    result = run_cli([*release, "--record", str(record)], capsys)

    lines = lane_trailers(bare_remote)
    assert (result.status, result.stderr) == (0, "")
    assert lines[0] == "lane_outcome: abandoned"
    assert lines[2:] == expected_trailers


@pytest.mark.parametrize(
    ("record_text", "extra", "sentence"),
    [
        pytest.param(
            json.dumps(lane_record_object(version=2)),
            (),
            "lane record {record} is invalid: version 2 is unknown; this aco reads version 1",
            id="a-malformed-record",
        ),
        pytest.param(
            json.dumps(lane_record_object()),
            ("--merged", "12"),
            "--record applies to --abandoned only",
            id="a-record-for-a-landing",
        ),
    ],
)
def test_a_release_refuses_a_record_it_cannot_use_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    github_clone: Path,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
    record_text: str,
    extra: tuple[str, ...],
    sentence: str,
) -> None:
    """Spec: LANREC-31, LANREC-41."""
    stand_in = make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, ("src/widget.py",))
    stand_in(branch=LANE_BRANCH, standing=lane_held_by_ada(LANE_BRANCH, ("src/widget.py",)))
    record = tmp_path / "record.json"
    record.write_text(record_text, encoding="utf-8")
    tip_before = state_ref_tip(bare_remote)
    outcome = extra or ("--abandoned", "stopped")

    result = run_cli(
        ["--repo", REPOSITORY, "release", "--agent", "Ada", *outcome, "--record", str(record)],
        capsys,
    )

    tip_after = state_ref_tip(bare_remote)
    assert (result.status, result.stderr, tip_after) == (
        2,
        f"ERROR: {sentence.format(record=record)}\n",
        tip_before,
    )


def test_an_abandoned_release_accepts_a_record_whose_last_verdict_asks_for_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    github_clone: Path,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: LANREC-44 -- an abandoned lane rarely ends approved."""
    stand_in = make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, ("src/widget.py",))
    stand_in(branch=LANE_BRANCH, standing=lane_held_by_ada(LANE_BRANCH, ("src/widget.py",)))
    verdicts = [{"stage": "gate", "verdict": "revise", "sha": "c" * 40}]
    record = write_lane_record_file(tmp_path, lane_record_object(verdicts=verdicts))

    release = ["--repo", REPOSITORY, "release", "--agent", "Ada", "--abandoned", "stopped"]

    result = run_cli([*release, "--record", str(record)], capsys)

    assert (result.status, result.stderr) == (0, "")
