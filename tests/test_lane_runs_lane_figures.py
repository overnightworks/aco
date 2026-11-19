"""The figures `aco lane-record show` computes from the runs a claim stored, and whether the lane
is complete (`specs/lane-record.spec.md`, "Stored runs"): pure rules over `RunsFile`."""

import json
from collections.abc import Mapping

import pytest
from lane_record_fixtures import lane_record_object

from aco import lane_record, lane_runs
from aco.lane_record import FindingStage
from aco.routing_line import RoutingStage

END_TIP = "b" * 40
START_TIP = "a" * 40
UNKNOWN = None
ALL_STAGES = ("build", "fix", "review", "test", "gate")


def marked(marker: str) -> dict[str, str]:
    """The stage slots of one stated record, every choice carrying `marker`."""
    return {stage: f"{stage}-{marker}/low" for stage in (*ALL_STAGES, "land")}


def four(review: int, gate: int, ci: int, test: int) -> dict[str, int]:
    return {"review": review, "gate": gate, "ci": ci, "test": test}


def begun(run: str, *, follows: bool = True, start_tip: str | None = None) -> lane_runs.RunEntry:
    """A run begun and not added."""
    return lane_runs.RunEntry(run, start_tip, follows)


def added(
    run: str,
    *ran: str,
    marker: str = "m",
    follows: bool = True,
    start_tip: str | None = None,
    **changes: object,
) -> lane_runs.RunEntry:
    """A run that ran `ran`, added with a record that states `changes` over a valid one whose
    stage choices carry `marker`; a change to `None` leaves the field out."""
    content = lane_record_object(
        **{"stages": marked(marker), "misses": four(0, 0, 0, 0), **changes}
    )
    stated = {name: value for name, value in content.items() if value is not None}
    record = lane_record.parse_record_file(json.dumps(stated).encode())
    stored = lane_runs.RunAdded(END_TIP, tuple(RoutingStage(stage) for stage in ran), record)
    return lane_runs.RunEntry(run, start_tip, follows, stored)


def not_following(run: str, *ran: str, marker: str = "m", **changes: object) -> lane_runs.RunEntry:
    """A run added that does not follow the run before it."""
    return added(run, *ran, marker=marker, follows=False, start_tip=START_TIP, **changes)


def figures_of(*entries: lane_runs.RunEntry) -> lane_record.LaneFigures:
    return lane_runs.lane_figures(lane_runs.RunsFile(entries))


def counts_of(figures: lane_record.LaneFigures, kind: str) -> tuple[int | None, ...]:
    """What `figures` holds for `fix_rounds`, `blocking` or `misses`, per finding stage."""
    return tuple(getattr(figures.counts[stage], kind) for stage in FindingStage)


@pytest.mark.parametrize(
    ("entries", "expected"),
    [
        pytest.param((added("one", "build", "review", marker="x"),), "build-x/low", id="one-run"),
        pytest.param(
            (added("one", "build", marker="x"), added("two", "build", "review", marker="y")),
            "build-x/low",
            id="the-first-run-that-ran-build",
        ),
        pytest.param(
            (added("one", "review", marker="x"), added("two", "build", marker="y")),
            "build-y/low",
            id="a-later-run-that-ran-build",
        ),
        pytest.param(
            (not_following("one", "build", marker="x"),),
            UNKNOWN,
            id="a-first-run-with-a-start-tip-is-lost-before-it",
        ),
        pytest.param(
            (begun("one"), added("two", "build", marker="y")), UNKNOWN, id="a-run-without-a-record"
        ),
        pytest.param(
            (added("one", "build", marker="x"), begun("two")),
            "build-x/low",
            id="a-lost-run-after-the-run-that-ran-build",
        ),
        pytest.param(
            (added("one", "review"), added("two", "review")), UNKNOWN, id="no-run-ran-build"
        ),
        pytest.param(
            (added("one", "review"), not_following("two", "build", marker="y")),
            UNKNOWN,
            id="a-lost-run-before-the-run-that-ran-build",
        ),
    ],
)
def test_the_build_stage_is_the_choice_of_the_first_lost_or_build_running_element(
    entries: tuple[lane_runs.RunEntry, ...], expected: str | None
) -> None:
    """Spec: LANREC-74."""
    figures = figures_of(*entries)

    assert figures.stages[RoutingStage.BUILD] == expected


@pytest.mark.parametrize("stage", ["review", "fix", "test", "gate"])
@pytest.mark.parametrize(
    ("entries", "marker"),
    [
        pytest.param((added("one", *ALL_STAGES, marker="x"),), "x", id="one-run"),
        pytest.param(
            (added("one", *ALL_STAGES, marker="x"), added("two", *ALL_STAGES, marker="y")),
            "y",
            id="the-last-run-that-ran-it",
        ),
        pytest.param(
            (added("one", *ALL_STAGES, marker="x"), added("two", "build", marker="y")),
            "x",
            id="an-earlier-run-when-the-last-did-not-run-it",
        ),
        pytest.param(
            (added("one", *ALL_STAGES, marker="x"), begun("two")),
            UNKNOWN,
            id="a-lost-run-after-the-run-that-ran-it",
        ),
        pytest.param(
            (added("one", *ALL_STAGES, marker="x"), not_following("two", "build", marker="y")),
            UNKNOWN,
            id="a-lost-run-before-a-run-that-did-not-run-it",
        ),
        pytest.param(
            (added("one", "build", marker="x"), not_following("two", *ALL_STAGES, marker="y")),
            "y",
            id="a-lost-run-before-the-run-that-ran-it",
        ),
    ],
)
def test_a_later_stage_is_the_choice_of_the_last_lost_or_stage_running_element(
    entries: tuple[lane_runs.RunEntry, ...], marker: str | None, stage: str
) -> None:
    """Spec: LANREC-75."""
    figures = figures_of(*entries)

    expected = None if marker is None else f"{stage}-{marker}/low"
    assert figures.stages[RoutingStage(stage)] == expected


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        pytest.param("review", UNKNOWN, id="review-is-unknown"),
        pytest.param("fix", "none", id="fix-is-none"),
        pytest.param("test", "none", id="test-is-none"),
        pytest.param("gate", "none", id="gate-is-none"),
    ],
)
def test_a_stage_no_run_ran_is_none_for_fix_test_and_gate_and_unknown_for_review(
    stage: str, expected: str | None
) -> None:
    """Spec: LANREC-75."""
    figures = figures_of(added("one", "build"))

    assert figures.stages[RoutingStage(stage)] == expected


@pytest.mark.parametrize(
    ("entries", "land", "risk"),
    [
        pytest.param(
            (added("one", "build", marker="x", risk="first"), added("two", "review", marker="y")),
            "land-y/low",
            "routine",
            id="the-newest-entrys-record",
        ),
        pytest.param(
            (added("one", "build"), begun("two")), UNKNOWN, UNKNOWN, id="the-newest-has-no-record"
        ),
        pytest.param(
            (added("one", "build", risk=None),), "land-m/low", UNKNOWN, id="the-record-has-no-risk"
        ),
    ],
)
def test_land_and_risk_are_the_newest_entrys_or_unknown(
    entries: tuple[lane_runs.RunEntry, ...], land: str | None, risk: str | None
) -> None:
    """Spec: LANREC-76."""
    figures = figures_of(*entries)

    assert (figures.stages[RoutingStage.LAND], figures.risk) == (land, risk)


@pytest.mark.parametrize(
    ("entries", "kind", "expected"),
    [
        pytest.param(
            (added("one", "build", fix_rounds=four(1, 0, 2, 0)),),
            "fix_rounds",
            (1, 0, 2, 0),
            id="one-record-gives-its-own-counts",
        ),
        pytest.param(
            (
                added("one", "build", blocking=four(3, 0, 1, 0)),
                added("two", "review", blocking=four(1, 2, 0, 5)),
            ),
            "blocking",
            (4, 2, 1, 5),
            id="two-records-are-summed",
        ),
        pytest.param(
            (
                added("one", "build", fix_rounds=four(600, 0, 0, 0)),
                added("two", "review", fix_rounds=four(600, 0, 0, 0)),
            ),
            "fix_rounds",
            (999, 0, 0, 0),
            id="a-sum-above-999-is-clamped",
        ),
        pytest.param(
            (added("one", "build"), begun("two")),
            "blocking",
            (UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN),
            id="a-lost-run-makes-blocking-unknown",
        ),
        pytest.param(
            (added("one", "build"), not_following("two", "review")),
            "fix_rounds",
            (UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN),
            id="a-run-that-does-not-follow-makes-fix-rounds-unknown",
        ),
        pytest.param(
            (added("one", "build"), begun("two")),
            "misses",
            (UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN),
            id="a-lost-run-makes-misses-unknown",
        ),
        pytest.param(
            (
                added("one", "build", misses=four(0, 0, 1, 0)),
                added("two", "review", misses=four(1, 0, 0, 0)),
            ),
            "misses",
            (1, 0, 1, 0),
            id="misses-are-summed",
        ),
    ],
)
def test_the_counts_are_the_sums_clamped_and_unknown_with_a_lost_run(
    entries: tuple[lane_runs.RunEntry, ...], kind: str, expected: tuple[int | None, ...]
) -> None:
    """Spec: LANREC-77."""
    figures = figures_of(*entries)

    assert counts_of(figures, kind) == expected


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        pytest.param("fix_rounds", (2, 0, 4, 0), id="fix-rounds-are-summed"),
        pytest.param("blocking", (6, 0, 2, 0), id="blocking-is-summed"),
        pytest.param("misses", (UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN), id="misses-are-unknown"),
    ],
)
def test_a_known_record_without_misses_makes_misses_unknown_alone(
    kind: str, expected: tuple[int | None, ...]
) -> None:
    """Spec: LANREC-77."""
    figures = figures_of(added("one", "build"), added("two", "review", misses=None))

    assert counts_of(figures, kind) == expected


def test_the_verdicts_are_those_of_the_known_records_in_run_order() -> None:
    """Spec: LANREC-78."""
    first = {"stage": "review", "verdict": "revise", "sha": "1" * 40}
    second = {"stage": "gate", "verdict": "approve", "sha": "2" * 40}
    third = {"stage": "review", "verdict": "approve", "sha": "3" * 40}

    figures = figures_of(
        added("one", "build", verdicts=[first, second]),
        begun("two"),
        added("three", "review", verdicts=[third]),
    )

    assert [(judged.stage, judged.verdict, judged.sha) for judged in figures.verdicts] == [
        ("review", "revise", "1" * 40),
        ("gate", "approve", "2" * 40),
        ("review", "approve", "3" * 40),
    ]


@pytest.mark.parametrize(
    ("entries", "expected"),
    [
        pytest.param(
            (added("one", "build", experiment="tag-a"), added("two", "review", experiment="tag-a")),
            "tag-a",
            id="the-same-tag-in-every-run",
        ),
        pytest.param(
            (added("one", "build", experiment="tag-a"), added("two", "review", experiment="tag-b")),
            UNKNOWN,
            id="differing-tags",
        ),
        pytest.param(
            (added("one", "build", experiment="tag-a"), added("two", "review", experiment=None)),
            UNKNOWN,
            id="a-record-without-a-tag",
        ),
        pytest.param(
            (added("one", "build", experiment="tag-a"), begun("two")),
            UNKNOWN,
            id="a-lost-run",
        ),
    ],
)
def test_the_experiment_is_the_tag_every_known_record_states_when_no_run_is_lost(
    entries: tuple[lane_runs.RunEntry, ...], expected: str | None
) -> None:
    """Spec: LANREC-78."""
    figures = figures_of(*entries)

    assert figures.experiment == expected


@pytest.mark.parametrize(
    ("entries", "expected"),
    [
        pytest.param((added("one", "build"),), True, id="one-run-with-a-record"),
        pytest.param((begun("one"),), False, id="a-run-without-a-record"),
        pytest.param((added("one", "build"), added("two", "review")), True, id="two-chained-runs"),
        pytest.param(
            (added("one", "build"), not_following("two", "review")),
            False,
            id="a-run-that-does-not-follow",
        ),
        pytest.param(
            (added("one", "build", follows=False, start_tip=START_TIP),),
            False,
            id="a-first-run-with-a-start-tip",
        ),
        pytest.param(
            (added("one", "build"), begun("two")), False, id="a-second-run-without-a-record"
        ),
    ],
)
def test_a_lane_is_complete_when_no_run_is_lost(
    entries: tuple[lane_runs.RunEntry, ...], expected: bool
) -> None:
    """Spec: LANREC-73."""
    assert lane_runs.is_complete(lane_runs.RunsFile(entries)) is expected


def test_the_stages_come_from_what_a_run_ran_never_from_its_records_slots() -> None:
    """Spec: LANREC-75."""
    figures = figures_of(added("one", "build", marker="x"))

    assert figures.stages == {
        RoutingStage.BUILD: "build-x/low",
        RoutingStage.FIX: "none",
        RoutingStage.REVIEW: UNKNOWN,
        RoutingStage.TEST: "none",
        RoutingStage.GATE: "none",
        RoutingStage.LAND: "land-x/low",
    }


def test_the_figures_hold_every_stage_and_every_finding_stage() -> None:
    """Spec: LANREC-74."""
    figures = figures_of(added("one", "build"))

    stages: Mapping[RoutingStage, str | None] = figures.stages
    assert (list(stages), list(figures.counts)) == (list(RoutingStage), list(FindingStage))
