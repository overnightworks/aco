"""`aco release --abandoned --record FILE` releases with the record file's figures, or refuses
before it writes."""

import json
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY
from claim_worktrees import lane_held_by_ada, make_stand_in
from cli_fixtures import real_git, run_cli
from lane_record_fixtures import (
    LANE_BRANCH,
    LANE_RECORD_TRAILERS,
    ROUTING,
    lane_record_object,
    write_lane_record_file,
)

from aco import store


def state_ref_tip(remote: Path) -> str:
    return real_git(remote, "rev-parse", store.STATE_REF).stdout


def lane_trailers(remote: Path) -> tuple[str, ...]:
    message = real_git(remote, "log", "-1", "--format=%B", store.STATE_REF).stdout
    return tuple(line for line in message.splitlines() if line.startswith("lane_"))


def test_an_abandoned_release_with_a_record_file_leaves_the_files_figures_not_the_reasons(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    github_clone: Path,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: LANREC-41, LANREC-42, LANREC-43 -- the reason's routing line is not read."""
    stand_in = make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, ("src/widget.py",))
    stand_in(branch=LANE_BRANCH, standing=lane_held_by_ada(LANE_BRANCH, ("src/widget.py",)))
    record = write_lane_record_file(tmp_path, lane_record_object())

    release = ["--repo", REPOSITORY, "release", "--agent", "Ada", "--abandoned", ROUTING]

    result = run_cli([*release, "--record", str(record)], capsys)

    lines = lane_trailers(bare_remote)
    assert (result.status, result.stderr) == (0, "")
    assert lines[0] == "lane_outcome: abandoned"
    assert lines[2:] == LANE_RECORD_TRAILERS


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
