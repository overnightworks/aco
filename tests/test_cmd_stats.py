"""`aco stats` (`specs/stats.spec.md`) through the real CLI over a real state ref that holds
recorded releases; no forge is built."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cli_fixtures import (
    forbid_forge_resolution,
    real_git,
    run_cli,
    track_board_config,
)
from store_fixtures import (
    lineage_observation,
    publish_claims_from_a_second_clone,
    state_ref_tip,
)

from aco import lane_measure, store, workboard
from aco.lane_record import FindingStage, LaneOutcome, LaneRecord, ProductionSize, StageCounts
from aco.routing_line import RoutingLine, RoutingStage

UNUSED_TAG = "tag:unused"
FINDING_STAGES = ("review", "gate", "ci", "test")
UNKNOWN_STAGE_FIGURES = {
    "fix_rounds": {"total": None, "n": 0, "unknown": 1},
    "misses": {"total": None, "n": 0, "unknown": 1},
}


def unknown_risk_block(lanes: int) -> list[str]:
    """The `(none)` block of `lanes` landed lanes that state no per-stage figure."""
    lines = [f"  risk (none): lanes {lanes} (landed {lanes}, abandoned 0)"]
    for stage in FINDING_STAGES:
        lines.append(f"    fix_rounds_{stage}: total unknown, n 0, unknown {lanes}")
        lines.append(f"    misses_{stage}: total unknown, n 0, unknown {lanes}")
    return lines


def at(moment: str) -> int:
    return int(datetime.fromisoformat(moment).replace(tzinfo=UTC).timestamp())


def push_release_commit(
    monkeypatch: pytest.MonkeyPatch, worktree: Path, remote: Path, message: str, committed_at: int
) -> None:
    """Append a commit of `message`, dated `committed_at` (Unix seconds), to the state ref of
    `remote`, on the tree its tip already holds."""
    tip = state_ref_tip(remote)
    assert tip is not None
    real_git(worktree, "fetch", "-q", str(remote), store.STATE_REF)
    monkeypatch.setenv("GIT_COMMITTER_DATE", f"@{committed_at} +0000")
    commit = real_git(
        worktree, "commit-tree", f"{tip}^{{tree}}", "-p", tip, "-m", message
    ).stdout.strip()
    real_git(worktree, "push", "-q", str(remote), f"{commit}:{store.STATE_REF}")


def release_message(trailers: tuple[str, ...]) -> str:
    return "\n".join(["release lane", "", *trailers])


def routing(
    stages: dict[RoutingStage, str], fix_rounds: int, blocking: int | None, experiment: str
) -> RoutingLine:
    return RoutingLine(stages, fix_rounds, blocking, experiment)


def released_commits() -> tuple[tuple[int, tuple[str, ...]], ...]:
    """The commits pushed to the state ref: four recorded lanes and two commits that are none."""
    return (
        (
            at("2026-11-02T12:00:00"),
            LaneRecord(
                LaneOutcome.LANDED,
                merge_commit="a" * 40,
                wall_seconds=1800,
                size=ProductionSize(files=2, added=40, deleted=5),
                routing=routing(
                    {
                        RoutingStage.BUILD: "sonnet-5.5/high",
                        RoutingStage.FIX: "none",
                        RoutingStage.REVIEW: "opus-5.5/medium",
                        RoutingStage.LAND: "haiku-5.5/low",
                    },
                    fix_rounds=1,
                    blocking=2,
                    experiment="builder-sonnet",
                ),
            ).trailers(),
        ),
        (
            at("2026-11-03T23:59:59"),
            LaneRecord(
                LaneOutcome.LANDED,
                wall_seconds=3000,
                size=ProductionSize(files=4, added=100, deleted=20),
                routing=routing(
                    {RoutingStage.BUILD: "sonnet-5.5/high", RoutingStage.REVIEW: "opus-5.5/medium"},
                    fix_rounds=2,
                    blocking=None,
                    experiment="builder-sonnet",
                ),
            ).trailers(),
        ),
        (
            at("2026-11-09T00:00:00"),
            LaneRecord(
                LaneOutcome.LANDED,
                wall_seconds=1200,
                routing=routing(
                    {RoutingStage.BUILD: "opus-5.5/high"},
                    fix_rounds=0,
                    blocking=0,
                    experiment="builder-opus",
                ),
            ).trailers(),
        ),
        (
            at("2026-11-10T12:00:00"),
            LaneRecord(LaneOutcome.ABANDONED, wall_seconds=60).trailers(),
        ),
        (at("2026-11-04T12:00:00"), ()),
        (at("2026-11-05T12:00:00"), ("lane_outcome: paused", "lane_wall_seconds: 5")),
    )


@pytest.fixture(autouse=True)
def _no_forge(monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_forge_resolution(monkeypatch)


@pytest.fixture
def recorded(clone: Path, bare_remote: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A bootstrapped state ref that holds four recorded lanes and two commits that are none."""
    publish_claims_from_a_second_clone(clone, bare_remote, ())
    for released_at, trailers in released_commits():
        push_release_commit(monkeypatch, clone, bare_remote, release_message(trailers), released_at)
    return clone


def stats(capsys: pytest.CaptureFixture[str], *arguments: str) -> tuple[int | str | None, str, str]:
    result = run_cli(["stats", *arguments], capsys)
    return result.status, result.stdout, result.stderr


def test_the_text_compares_two_groups_figure_by_figure(
    recorded: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STATS-01, STATS-02, STATS-03, STATS-06, STATS-07, STATS-08, STATS-09, STATS-10."""
    status, stdout, stderr = stats(capsys, "2026-11-01..2026-11-07", "tag:builder-opus")

    assert (status, stderr) == (0, "")
    assert stdout.splitlines() == [
        "A 2026-11-01..2026-11-07: lanes 2 (landed 2, abandoned 0)",
        "  wall_seconds: median 2400, n 2, unknown 0",
        "  fix_rounds: median 1.5, n 2, unknown 0",
        "  blocking: median 2, n 1, unknown 1",
        "  files: median 3, n 2, unknown 0",
        "  added: median 70, n 2, unknown 0",
        "  deleted: median 12.5, n 2, unknown 0",
        "  build: sonnet-5.5/high 2, unknown 0",
        "  fix: none 1, unknown 1",
        "  review: opus-5.5/medium 2, unknown 0",
        "  test: unknown 2",
        "  gate: unknown 2",
        "  land: haiku-5.5/low 1, unknown 1",
        *unknown_risk_block(2),
        "B tag:builder-opus: lanes 1 (landed 1, abandoned 0)",
        "  wall_seconds: median 1200, n 1, unknown 0",
        "  fix_rounds: median 0, n 1, unknown 0",
        "  blocking: median 0, n 1, unknown 0",
        "  files: median unknown, n 0, unknown 1",
        "  added: median unknown, n 0, unknown 1",
        "  deleted: median unknown, n 0, unknown 1",
        "  build: opus-5.5/high 1, unknown 0",
        "  fix: unknown 1",
        "  review: unknown 1",
        "  test: unknown 1",
        "  gate: unknown 1",
        "  land: unknown 1",
        *unknown_risk_block(1),
    ]


def test_json_carries_the_same_figures_under_the_shared_envelope(
    recorded: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STATS-11, STATS-12."""
    status, stdout, stderr = stats(capsys, "2026-11-01..2026-11-07", "tag:builder-opus", "--json")

    payload = json.loads(stdout)
    assert (status, stderr) == (0, "")
    assert list(payload) == ["ok", "reason", "a", "b"]
    assert (payload["ok"], payload["reason"]) == (True, "compared")
    assert payload["a"]["figures"]["fix_rounds"] == {"median": 1.5, "n": 2, "unknown": 0}
    assert payload["a"]["stages"]["land"] == {"choices": {"haiku-5.5/low": 1}, "unknown": 1}
    assert payload["b"] == {
        "group": "tag:builder-opus",
        "lanes": 1,
        "outcomes": {"landed": 1, "abandoned": 0},
        "figures": {
            "wall_seconds": {"median": 1200, "n": 1, "unknown": 0},
            "fix_rounds": {"median": 0, "n": 1, "unknown": 0},
            "blocking": {"median": 0, "n": 1, "unknown": 0},
            "files": {"median": None, "n": 0, "unknown": 1},
            "added": {"median": None, "n": 0, "unknown": 1},
            "deleted": {"median": None, "n": 0, "unknown": 1},
        },
        "stages": {
            "build": {"choices": {"opus-5.5/high": 1}, "unknown": 0},
            "fix": {"choices": {}, "unknown": 1},
            "review": {"choices": {}, "unknown": 1},
            "test": {"choices": {}, "unknown": 1},
            "gate": {"choices": {}, "unknown": 1},
            "land": {"choices": {}, "unknown": 1},
        },
        "risks": [
            {
                "risk": None,
                "lanes": 1,
                "outcomes": {"landed": 1, "abandoned": 0},
                "stages": {stage: UNKNOWN_STAGE_FIGURES for stage in FINDING_STAGES},
            }
        ],
    }


def stage_counts(
    fix_rounds: tuple[int, int, int, int],
    blocking: tuple[int, int, int, int],
    misses: tuple[int, int, int, int] | None,
) -> dict[FindingStage, StageCounts]:
    return {
        stage: StageCounts(
            fix_rounds[position], blocking[position], misses[position] if misses else None
        )
        for position, stage in enumerate(FindingStage)
    }


@pytest.fixture
def recorded_with_risks(recorded: Path, bare_remote: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`recorded` plus a material lane, a normal lane that states no misses and a lane whose
    record states no risk, all released in December."""
    december = (
        (
            at("2026-12-01T12:00:00"),
            LaneRecord(
                LaneOutcome.LANDED,
                wall_seconds=100,
                risk="material",
                counts=stage_counts((2, 0, 1, 0), (3, 0, 1, 0), (0, 0, 1, 0)),
            ),
        ),
        (
            at("2026-12-02T12:00:00"),
            LaneRecord(
                LaneOutcome.ABANDONED,
                wall_seconds=50,
                risk="normal",
                counts=stage_counts((1, 0, 0, 0), (1, 0, 0, 0), None),
            ),
        ),
        (at("2026-12-03T12:00:00"), LaneRecord(LaneOutcome.LANDED, wall_seconds=70)),
    )
    for released_at, lane in december:
        message = release_message(lane.trailers())
        push_release_commit(monkeypatch, recorded, bare_remote, message, released_at)
    return recorded


def test_a_group_prints_one_block_per_risk_class_with_totals_per_stage(
    recorded_with_risks: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STATS-23, STATS-24, STATS-25."""
    status, stdout, stderr = stats(capsys, "2026-12-01..2026-12-31", UNUSED_TAG)

    blocks = stdout.partition("\nB ")[0].splitlines()
    assert (status, stderr) == (0, "")
    assert [line for line in blocks if line.startswith("  risk ")] == [
        "  risk material: lanes 1 (landed 1, abandoned 0)",
        "  risk normal: lanes 1 (landed 0, abandoned 1)",
        "  risk (none): lanes 1 (landed 1, abandoned 0)",
    ]
    assert [line for line in blocks if line.startswith("    ") and "_ci:" in line] == [
        "    fix_rounds_ci: total 1, n 1, unknown 0",
        "    misses_ci: total 1, n 1, unknown 0",
        "    fix_rounds_ci: total 0, n 1, unknown 0",
        "    misses_ci: total unknown, n 0, unknown 1",
        "    fix_rounds_ci: total unknown, n 0, unknown 1",
        "    misses_ci: total unknown, n 0, unknown 1",
    ]


def test_json_lists_the_risk_blocks_with_their_stage_totals(
    recorded_with_risks: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STATS-26."""
    _status, stdout, _stderr = stats(capsys, "2026-12-01..2026-12-31", UNUSED_TAG, "--json")

    risks = json.loads(stdout)["a"]["risks"]
    assert [(block["risk"], block["lanes"], block["outcomes"]) for block in risks] == [
        ("material", 1, {"landed": 1, "abandoned": 0}),
        ("normal", 1, {"landed": 0, "abandoned": 1}),
        (None, 1, {"landed": 1, "abandoned": 0}),
    ]
    assert list(risks[0]["stages"]) == list(FINDING_STAGES)
    assert risks[0]["stages"]["ci"] == {
        "fix_rounds": {"total": 1, "n": 1, "unknown": 0},
        "misses": {"total": 1, "n": 1, "unknown": 0},
    }
    assert risks[1]["stages"]["ci"]["misses"] == {"total": None, "n": 0, "unknown": 1}


def test_a_group_no_lane_selects_prints_no_risk_block(
    recorded: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STATS-25, STATS-26."""
    _status, text, _stderr = stats(capsys, "2026-11-04..2026-11-08", UNUSED_TAG)
    _status, stdout, _stderr = stats(capsys, "2026-11-04..2026-11-08", UNUSED_TAG, "--json")

    payload = json.loads(stdout)
    assert (payload["a"]["risks"], payload["b"]["risks"]) == ([], [])
    assert "risk " not in text


@pytest.mark.parametrize(
    ("group", "lanes"),
    [
        pytest.param("2026-11-02..2026-11-03", 2, id="a-last-day-is-inclusive-to-its-last-second"),
        pytest.param("2026-11-03..2026-11-03", 1, id="one-day"),
        pytest.param("2026-11-09..2026-11-09", 1, id="a-first-second-of-the-day"),
        pytest.param("2026-11-10..2026-11-10", 1, id="an-abandoned-lane-counts"),
        pytest.param("2026-11-04..2026-11-08", 0, id="no-lane-in-the-range"),
        pytest.param("2026-11-01..2026-11-30", 4, id="a-commit-with-no-record-is-no-lane"),
        pytest.param("tag:builder-sonnet", 2, id="a-tag"),
        pytest.param(UNUSED_TAG, 0, id="a-tag-no-lane-states"),
    ],
)
def test_a_group_selects_the_lanes_its_range_or_tag_names(
    recorded: Path, capsys: pytest.CaptureFixture[str], group: str, lanes: int
) -> None:
    """Spec: STATS-02, STATS-03, STATS-04, STATS-12."""
    _status, stdout, _stderr = stats(capsys, group, UNUSED_TAG, "--json")

    assert json.loads(stdout)["a"]["lanes"] == lanes


def test_a_lane_in_both_groups_counts_in_both(
    recorded: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STATS-04."""
    _status, stdout, _stderr = stats(
        capsys, "tag:builder-sonnet", "2026-11-02..2026-11-02", "--json"
    )

    payload = json.loads(stdout)
    assert (payload["a"]["lanes"], payload["b"]["lanes"]) == (2, 1)


def test_a_state_ref_nothing_has_released_into_has_no_lane(
    clone: Path, bare_remote: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STATS-15."""
    publish_claims_from_a_second_clone(clone, bare_remote, ())

    _status, stdout, _stderr = stats(capsys, "2026-11-01..2026-11-30", UNUSED_TAG, "--json")

    payload = json.loads(stdout)
    assert (payload["a"]["lanes"], payload["b"]["lanes"]) == (0, 0)


def test_a_repository_never_bootstrapped_has_no_lane(
    clone: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STATS-15."""
    status, stdout, stderr = stats(capsys, "2026-11-01..2026-11-30", UNUSED_TAG)

    assert (status, stderr) == (0, "")
    assert stdout.splitlines()[0] == "A 2026-11-01..2026-11-30: lanes 0 (landed 0, abandoned 0)"


@pytest.mark.parametrize(
    ("group", "sentence"),
    [
        pytest.param(
            "yesterday",
            "group 'yesterday' must be FROM..TO as YYYY-MM-DD days or tag:NAME",
            id="neither-form",
        ),
        pytest.param(
            "2026-11-1..2026-11-07",
            "group '2026-11-1..2026-11-07' must be FROM..TO as YYYY-MM-DD days or tag:NAME",
            id="a-day-not-in-iso-form",
        ),
        pytest.param(
            "2026-02-30..2026-03-01",
            "group '2026-02-30..2026-03-01' holds an impossible day",
            id="an-impossible-day",
        ),
        pytest.param(
            "2026-11-05..2026-11-01",
            "group '2026-11-05..2026-11-01' ends before it starts",
            id="a-range-that-ends-first",
        ),
        pytest.param(
            "tag:Builder",
            "group 'tag:Builder' names no tag: a tag is 1 to 40 lowercase letters, digits or '-'",
            id="a-tag-with-capitals",
        ),
        pytest.param(
            "tag:",
            "group 'tag:' names no tag: a tag is 1 to 40 lowercase letters, digits or '-'",
            id="an-empty-tag",
        ),
    ],
)
def test_a_group_that_is_no_range_and_no_tag_is_refused_by_name(
    recorded: Path, capsys: pytest.CaptureFixture[str], group: str, sentence: str
) -> None:
    """Spec: STATS-05, STATS-16, STATS-17."""
    status, stdout, stderr = stats(capsys, group, UNUSED_TAG, "--json")

    assert (status, stderr) == (2, f"ERROR: {sentence}\n")
    assert json.loads(stdout) == {"ok": False, "reason": "invalid_usage", "message": sentence}


@pytest.mark.parametrize("as_json", [False, True])
def test_the_global_repo_option_is_refused(
    recorded: Path, capsys: pytest.CaptureFixture[str], as_json: bool
) -> None:
    """Spec: STATS-13."""
    sentence = "aco stats reads this checkout's own state ref; --repo does not apply to it"
    command = ["--repo", "acme/here", "stats", "2026-11-01..2026-11-07", UNUSED_TAG]

    result = run_cli([*command, "--json"] if as_json else command, capsys)

    assert (result.status, result.stderr) == (2, f"ERROR: {sentence}\n")
    expected_stdout = (
        {"ok": False, "reason": "invalid_usage", "message": sentence} if as_json else None
    )
    assert (json.loads(result.stdout) if as_json else None) == expected_stdout


def test_a_checkout_that_cannot_read_its_state_ref_is_refused(
    recorded: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STATS-14."""
    real_git(recorded, "remote", "remove", "origin")

    status, stdout, stderr = stats(capsys, "2026-11-01..2026-11-07", UNUSED_TAG, "--json")

    payload = json.loads(stdout)
    assert (status, payload["ok"], payload["reason"]) == (2, False, "unavailable")
    assert stderr == f"ERROR: {payload['message']}\n"


def test_reading_the_lanes_changes_nothing_on_the_state_ref_or_the_checkout(
    recorded: Path, bare_remote: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STATS-01."""
    tip_before = state_ref_tip(bare_remote)
    bookkeeping_before = lineage_observation(recorded)

    status, _stdout, _stderr = stats(capsys, "2026-11-01..2026-11-07", UNUSED_TAG)

    assert (status, state_ref_tip(bare_remote), lineage_observation(recorded)) == (
        0,
        tip_before,
        bookkeeping_before,
    )


def test_a_group_with_a_newline_is_refused_on_one_line(
    recorded: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STATS-22."""
    status, _stdout, stderr = stats(capsys, "2026-11-01\n..2026-11-07", UNUSED_TAG)

    assert (status, stderr.count("\n")) == (2, 1)
    assert stderr.startswith("ERROR: group ")


def test_a_checkout_without_a_tracked_configuration_is_refused(
    recorded: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STATS-18, PIN-32."""
    real_git(recorded, "rm", "-q", str(workboard.CONFIG_PATH))
    real_git(recorded, "commit", "-q", "-m", "drop the board configuration")

    status, stdout, stderr = stats(capsys, "2026-11-01..2026-11-07", UNUSED_TAG, "--json")

    payload = json.loads(stdout)
    assert (status, payload["reason"]) == (2, "unavailable")
    assert stderr == f"ERROR: {payload['message']}\n"
    assert payload["message"].startswith(f"{workboard.CONFIG_PATH} was removed on this branch")


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param("production_paths = 'src/'", id="no-list"),
        pytest.param("production_paths = ['/src/']", id="an-absolute-entry"),
    ],
)
def test_a_malformed_production_paths_is_refused_although_stats_reads_no_size(
    recorded: Path, capsys: pytest.CaptureFixture[str], entry: str
) -> None:
    """Spec: STATS-18, PIN-55, PIN-56."""
    track_board_config(recorded, f"{entry}\n")

    status, stdout, stderr = stats(capsys, "2026-11-01..2026-11-07", UNUSED_TAG, "--json")

    payload = json.loads(stdout)
    assert (status, payload["reason"]) == (2, "unavailable")
    assert stderr == f"ERROR: {payload['message']}\n"
    assert payload["message"].startswith("board configuration ")
    assert " production_paths " in payload["message"]


def test_stats_outside_a_checkout_says_it_reads_the_configuration(
    outside_a_checkout: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STATS-19."""
    status, _stdout, stderr = stats(capsys, "2026-11-01..2026-11-07", UNUSED_TAG)

    assert status == 2
    assert stderr.startswith(
        f"ERROR: this command reads the repository's configuration from {workboard.CONFIG_PATH} "
        "and needs a checkout (a shallow one is enough): "
    )
    assert "body contract" not in stderr


def test_the_help_says_a_day_is_a_utc_day_and_gives_the_tag_grammar(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: STATS-20."""
    status, stdout, _stderr = stats(capsys, "--help")

    flat = " ".join(stdout.split())
    assert status == 0
    assert "UTC calendar day" in flat
    assert f"tag:NAME where NAME is {lane_measure.TAG_GRAMMAR}" in flat
