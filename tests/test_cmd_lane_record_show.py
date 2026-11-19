"""`aco lane-record show` through the CLI on real git, under both storages: the runs stored with a
claim, whether the lane is complete and the figures computed from them, as text and as JSON
(`specs/lane-record.spec.md`, LANREC-71..LANREC-88)."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import cast

import pytest
from claim_worktrees import assert_json_refusal_object
from cli_fixtures import real_git
from lane_record_fixtures import (
    UNKNOWN,
    four,
    lane_record_object,
    marked,
    write_lane_record_file,
)
from lane_record_runs_world import (
    END_TIP,
    FIRST_RUN,
    OTHER_AGENT,
    OTHER_TIP,
    SECOND_RUN,
    STAGES_RAN,
    World,
    add_arguments,
    begin_arguments,
    commit_on,
)

from aco import protocol, store, workboard
from aco.routing_line import RoutingStage

ENVELOPE_KEYS = ["ok", "reason", "item", "claim_id", "runs", "complete", "lane"]
NO_STAGES = dict.fromkeys(RoutingStage, UNKNOWN)


@pytest.fixture
def world(lane_record_runs_world: World) -> World:
    return lane_record_runs_world


class Start(StrEnum):
    """Where a run begins, relative to the commit every run ended at."""

    NOWHERE = "nowhere"
    AFTER_THE_EARLIER_RUN = "after-the-earlier-run"
    ELSEWHERE = "elsewhere"


@dataclass(frozen=True)
class Step:
    """One run a scenario begins and, with `ran`, adds with a record that states `changes` over a
    valid one and leaves out the fields in `omitted`."""

    run: str
    start: Start = Start.NOWHERE
    ran: tuple[RoutingStage, ...] | None = STAGES_RAN
    changes: dict[str, object] = field(default_factory=dict)
    omitted: tuple[str, ...] = ()


def head_of(world: World) -> str:
    return real_git(world.directory, "rev-parse", "HEAD").stdout.strip()


def play(world: World, capsys: pytest.CaptureFixture[str], *steps: Step) -> str:
    """Begin and add every step in order as the claim's holder; the commit all tips name."""
    head = head_of(world)
    start_flags = {
        Start.NOWHERE: (),
        Start.AFTER_THE_EARLIER_RUN: ("--start-tip", head),
        Start.ELSEWHERE: ("--start-tip", OTHER_TIP),
    }
    for step in steps:
        began = world.run(capsys, *begin_arguments(world, step.run, *start_flags[step.start]))
        assert began.status == 0, began.stderr
        if step.ran is not None:
            stated = lane_record_object(**step.changes)
            content = {name: value for name, value in stated.items() if name not in step.omitted}
            file = write_lane_record_file(world.scratch, content)
            added = world.run(
                capsys, *add_arguments(world, step.run, file=file, end_tip=head, stages=step.ran)
            )
            assert added.status == 0, added.stderr
    return head


def show(
    world: World, capsys: pytest.CaptureFixture[str], *flags: str
) -> tuple[int | str | None, str, str]:
    """The status, stdout and stderr of `aco lane-record show`."""
    shown = world.run(capsys, "lane-record", "show", world.item, *flags)
    return shown.status, shown.stdout, shown.stderr


def shown_json(world: World, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    status, stdout, stderr = show(world, capsys, "--json")
    assert (status, stderr) == (0, "")
    return json.loads(stdout)


def pick(shown: Mapping[str, object], path: str) -> object:
    """The value at the dotted `path` of the shown object."""
    value: object = shown
    for key in path.split("."):
        value = cast(Mapping[str, object], value)[key]
    return value


def shown_runs(shown: Mapping[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], shown["runs"])


def test_a_claim_without_runs_shows_none_and_a_null_lane(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-71, LANREC-88."""
    as_text = show(world, capsys)
    as_json = show(world, capsys, "--json")

    assert as_text == (0, f"{world.label} has no stored runs\n", "")
    assert as_json[0] == 0
    assert json.loads(as_json[1]) == {
        "ok": True,
        "reason": "shown",
        "item": workboard.parse_item_reference(world.item),
        "claim_id": world.claim().claim_id,
        "runs": [],
        "complete": None,
        "lane": None,
    }


def test_one_run_that_ran_build_and_review_shows_its_record_and_the_lane_computed_from_it(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-71, LANREC-84..LANREC-86."""
    head = play(world, capsys, Step(FIRST_RUN))

    shown = shown_json(world, capsys)

    stated = lane_record_object()
    assert shown == {
        "ok": True,
        "reason": "shown",
        "item": workboard.parse_item_reference(world.item),
        "claim_id": world.claim().claim_id,
        "runs": [
            {
                "run": FIRST_RUN,
                "start_tip": None,
                "follows": True,
                "end_tip": head,
                "ran": ["build", "review"],
                "record": stated,
            }
        ],
        "complete": True,
        "lane": {
            "stages": {
                "build": "sonnet-5.5/high",
                "fix": "none",
                "review": "opus-5.5/medium",
                "test": "none",
                "gate": "none",
                "land": "haiku-5.5/low",
            },
            "fix_rounds": four(1, 0, 2, 0),
            "blocking": four(3, 0, 1, 0),
            "misses": four(0, 0, 1, 0),
            "verdicts": stated["verdicts"],
            "risk": "routine",
            "experiment": "builder-sonnet",
        },
    }
    assert list(shown) == ENVELOPE_KEYS


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        pytest.param(
            (Step(FIRST_RUN, ran=None),),
            {
                "complete": False,
                "runs": [
                    {
                        "run": FIRST_RUN,
                        "start_tip": None,
                        "follows": True,
                        "end_tip": None,
                        "ran": None,
                        "record": None,
                    }
                ],
                "lane.stages": NO_STAGES,
                "lane.fix_rounds": None,
                "lane.blocking": None,
                "lane.misses": None,
                "lane.risk": None,
                "lane.experiment": None,
                "lane.verdicts": [],
            },
            id="3-one-run-begun-without-a-record",
        ),
        pytest.param(
            (
                Step(
                    FIRST_RUN,
                    ran=(RoutingStage.BUILD,),
                    changes={
                        "stages": marked("one"),
                        "fix_rounds": four(1, 0, 0, 0),
                        "blocking": four(2, 0, 0, 0),
                        "misses": four(1, 0, 0, 0),
                        "verdicts": [{"stage": "review", "verdict": "revise", "sha": "1" * 40}],
                    },
                ),
                Step(
                    SECOND_RUN,
                    Start.AFTER_THE_EARLIER_RUN,
                    ran=(RoutingStage.BUILD, RoutingStage.REVIEW),
                    changes={
                        "stages": marked("two"),
                        "fix_rounds": four(0, 0, 3, 0),
                        "blocking": four(1, 0, 4, 0),
                        "misses": four(0, 0, 1, 0),
                        "verdicts": [{"stage": "review", "verdict": "approve", "sha": "2" * 40}],
                    },
                ),
            ),
            {
                "complete": True,
                "lane.stages.build": "build-one/low",
                "lane.stages.review": "review-two/low",
                "lane.stages.fix": "none",
                "lane.stages.land": "land-two/low",
                "lane.fix_rounds": four(1, 0, 3, 0),
                "lane.blocking": four(3, 0, 4, 0),
                "lane.misses": four(1, 0, 1, 0),
                "lane.verdicts": [
                    {"stage": "review", "verdict": "revise", "sha": "1" * 40},
                    {"stage": "review", "verdict": "approve", "sha": "2" * 40},
                ],
            },
            id="5-two-chained-runs",
        ),
        pytest.param(
            (
                Step(FIRST_RUN),
                Step(
                    SECOND_RUN,
                    Start.ELSEWHERE,
                    ran=(RoutingStage.REVIEW,),
                    changes={"stages": marked("two")},
                ),
            ),
            {
                "complete": False,
                "lane.fix_rounds": None,
                "lane.blocking": None,
                "lane.misses": None,
                "lane.stages.review": "review-two/low",
                "lane.stages.build": "sonnet-5.5/high",
            },
            id="7-a-run-that-does-not-follow",
        ),
        pytest.param(
            (Step(FIRST_RUN), Step(SECOND_RUN, Start.AFTER_THE_EARLIER_RUN, ran=None)),
            {
                "complete": False,
                "lane.stages.review": None,
                "lane.stages.land": None,
                "lane.risk": None,
                "lane.fix_rounds": None,
            },
            id="8-a-second-run-begun-without-a-record",
        ),
        pytest.param(
            (Step(FIRST_RUN, Start.ELSEWHERE),),
            {"complete": False, "lane.stages.build": None, "lane.fix_rounds": None},
            id="9-the-first-run-has-a-start-tip",
        ),
        pytest.param(
            (
                Step(FIRST_RUN),
                Step(SECOND_RUN, Start.AFTER_THE_EARLIER_RUN, omitted=("misses",)),
            ),
            {
                "complete": True,
                "lane.misses": None,
                "lane.fix_rounds": four(2, 0, 4, 0),
                "lane.blocking": four(6, 0, 2, 0),
            },
            id="10-one-record-lacks-misses",
        ),
        pytest.param(
            (Step(FIRST_RUN), Step(SECOND_RUN, Start.AFTER_THE_EARLIER_RUN)),
            {"complete": True, "lane.experiment": "builder-sonnet"},
            id="11-the-same-experiment-tag-in-every-run",
        ),
        pytest.param(
            (
                Step(FIRST_RUN),
                Step(SECOND_RUN, Start.AFTER_THE_EARLIER_RUN, changes={"experiment": "other-tag"}),
            ),
            {"complete": True, "lane.experiment": None},
            id="11-differing-experiment-tags",
        ),
        pytest.param(
            (
                Step(
                    FIRST_RUN,
                    changes={"fix_rounds": four(600, 0, 0, 0), "misses": four(0, 0, 0, 0)},
                ),
                Step(
                    SECOND_RUN,
                    Start.AFTER_THE_EARLIER_RUN,
                    changes={"fix_rounds": four(600, 0, 0, 0), "misses": four(0, 0, 0, 0)},
                ),
            ),
            {"complete": True, "lane.fix_rounds": four(999, 0, 0, 0)},
            id="12-600-and-600-in-one-stage",
        ),
        pytest.param(
            (Step(FIRST_RUN, ran=(RoutingStage.BUILD,)),),
            {
                "complete": True,
                "lane.stages.review": None,
                "lane.stages.fix": "none",
                "lane.stages.test": "none",
                "lane.stages.gate": "none",
            },
            id="13-no-run-ran-review",
        ),
    ],
)
def test_the_lane_is_computed_from_the_stored_runs_as_the_matrix_states(
    world: World,
    capsys: pytest.CaptureFixture[str],
    steps: tuple[Step, ...],
    expected: dict[str, object],
) -> None:
    """Spec: LANREC-75..LANREC-86, E-LANREC-15."""
    play(world, capsys, *steps)

    shown = shown_json(world, capsys)

    assert {path: pick(shown, path) for path in expected} == expected


def test_a_run_that_starts_at_a_merge_of_trunk_onto_the_earlier_end_tip_follows(
    world: World, capsys: pytest.CaptureFixture[str], github_clone: Path
) -> None:
    """Spec: LANREC-75, LANREC-54."""
    earlier_end = commit_on(world.directory, "lane.txt")
    world.run(capsys, *begin_arguments(world, FIRST_RUN))
    world.run(capsys, *add_arguments(world, FIRST_RUN, end_tip=earlier_end))
    commit_on(github_clone, "trunk.txt")
    real_git(world.directory, "merge", "-q", "--no-edit", "main")
    merged = head_of(world)
    world.run(capsys, *begin_arguments(world, SECOND_RUN, "--start-tip", merged))
    world.run(capsys, *add_arguments(world, SECOND_RUN, end_tip=merged))

    shown = shown_json(world, capsys)

    assert (shown["complete"], [run["follows"] for run in shown_runs(shown)]) == (
        True,
        [True, True],
    )


def test_a_session_that_does_not_hold_the_claim_may_show_it(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: LANREC-72."""
    play(world, capsys, Step(FIRST_RUN))
    monkeypatch.setenv("ACO_AGENT", OTHER_AGENT)

    status, stdout, stderr = show(world, capsys, "--json")

    assert (status, stderr, json.loads(stdout)["reason"]) == (0, "", "shown")


def test_the_old_holders_begun_run_is_shown_without_a_record_after_a_handover(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-75, LANREC-61."""
    play(world, capsys, Step(FIRST_RUN, ran=None))
    world.commit_state(
        protocol.HandoverIntent(
            claim_id=world.claim().claim_id,
            previous_agent="Ada",
            agent=OTHER_AGENT,
            operation_id="op-handover",
        )
    )

    shown = shown_json(world, capsys)

    assert (shown["complete"], shown_runs(shown)[0]["record"]) == (False, None)


def test_showing_writes_nothing(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Spec: LANREC-72."""
    play(world, capsys, Step(FIRST_RUN))
    tip = world.state_tip()

    show(world, capsys)
    show(world, capsys, "--json")

    assert world.state_tip() == tip


@pytest.mark.parametrize(
    ("steps", "lines"),
    [
        pytest.param(
            (Step(FIRST_RUN),),
            [
                "run {first} of {label}: start none, end {head}, ran build review, follows",
                "lane {label}: complete",
            ],
            id="one-run-with-a-record",
        ),
        pytest.param(
            (Step(FIRST_RUN), Step(SECOND_RUN, Start.ELSEWHERE, ran=None)),
            [
                "run {first} of {label}: start none, end {head}, ran build review, follows",
                "run {second} of {label}: start {elsewhere}, no record, does not follow",
                "lane {label}: incomplete",
            ],
            id="a-run-without-a-record-that-does-not-follow",
        ),
        pytest.param(
            (Step(FIRST_RUN), Step(SECOND_RUN, Start.AFTER_THE_EARLIER_RUN, ran=None)),
            [
                "run {first} of {label}: start none, end {head}, ran build review, follows",
                "run {second} of {label}: start {head}, no record, follows",
                "lane {label}: incomplete",
            ],
            id="a-run-without-a-record",
        ),
    ],
)
def test_the_text_prints_a_line_per_run_then_the_lane_and_each_record_as_compact_json(
    world: World,
    capsys: pytest.CaptureFixture[str],
    steps: tuple[Step, ...],
    lines: list[str],
) -> None:
    """Spec: LANREC-73, LANREC-74, E-LANREC-16."""
    head = play(world, capsys, *steps)
    shown = shown_json(world, capsys)

    status, stdout, stderr = show(world, capsys)

    printed = stdout.splitlines()
    record_lines = [line for line in printed if line.startswith("  record ")]
    records = [json.loads(line.removeprefix("  record ")) for line in record_lines]
    recorded = [run["record"] for run in shown_runs(shown) if run["record"] is not None]
    assert (status, stderr) == (0, "")
    assert [line for line in printed if line not in record_lines] == [
        line.format(
            first=FIRST_RUN, second=SECOND_RUN, label=world.label, head=head, elsewhere=OTHER_TIP
        )
        for line in lines
    ]
    assert records == [*recorded, shown["lane"]]
    assert [line.removeprefix("  record ") for line in record_lines] == [
        json.dumps(record, separators=(",", ":")) for record in records
    ]


def test_each_record_line_stands_under_its_run_and_the_lane_record_closes_the_text(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-74."""
    play(world, capsys, Step(FIRST_RUN))

    stdout = show(world, capsys)[1]

    assert [(line.startswith("  "), line.split()[0]) for line in stdout.splitlines()] == [
        (False, "run"),
        (True, "record"),
        (False, "lane"),
        (True, "record"),
    ]


def test_an_item_without_a_live_claim_refuses_as_a_release_does(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-87, REL-09."""
    released = world.run(capsys, "release", world.item, "--abandoned", "stopped for the day")
    assert released.status == 0, released.stderr

    as_text = show(world, capsys)
    as_json = show(world, capsys, "--json")

    sentence = f"ERROR: issue {world.label} has no active build claim\n"
    assert as_text == (2, "", sentence)
    assert as_json[0] == 2
    assert as_json[2] == sentence
    assert_json_refusal_object(as_json[2], as_json[1], reason="precondition_failed")


@pytest.mark.parametrize("flags", [(), ("--json",)], ids=["text", "json"])
def test_stored_runs_that_are_not_the_stored_shape_refuse_as_unavailable(
    world: World, capsys: pytest.CaptureFixture[str], flags: tuple[str, ...]
) -> None:
    """Spec: LANREC-87, LANREC-62."""
    world.commit_state(
        protocol.RunsWriteIntent(
            claim_id=world.claim().claim_id,
            agent="Ada",
            expected=None,
            new_oid=store.hash_blob(world.directory, b"not json"),
            operation_id="op-malformed",
            holder_refusal="{}".format,
            stale_refusal="never reached",
        )
    )

    status, stdout, stderr = show(world, capsys, *flags)

    assert status == 2
    assert stderr == f"ERROR: the stored runs of {world.label} cannot be used: not valid JSON\n"
    if flags:
        assert_json_refusal_object(stderr, stdout, reason="unavailable")
    else:
        assert stdout == ""


def test_the_end_tip_a_run_states_is_shown_as_stated(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-85."""
    world.run(capsys, *begin_arguments(world, FIRST_RUN))
    world.run(capsys, *add_arguments(world, FIRST_RUN, end_tip=END_TIP))

    shown = shown_json(world, capsys)

    assert shown_runs(shown)[0]["end_tip"] == END_TIP
