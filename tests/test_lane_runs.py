"""`lane_runs` behavior: the stored runs of a lane, their JSON file, whether a run follows the
run before it, and the merges a begin and an add make (`specs/lane-record.spec.md`, "Stored
runs"). Everything here is pure: the ancestry fact git answers is an argument."""

import json
from collections.abc import Callable

import pytest
from lane_record_fixtures import lane_record_object

from aco import lane_record, lane_runs
from aco.routing_line import RoutingStage

FIRST_TIP = "1" * 40
SECOND_TIP = "2" * 40
THIRD_TIP = "3" * 40
LABEL = "#42"


def the_record(**changes: object) -> lane_record.LaneRecordFile:
    return lane_record.parse_record_file(json.dumps(lane_record_object(**changes)).encode())


def an_added_run(
    *, end_tip: str = SECOND_TIP, ran: tuple[RoutingStage, ...] = (RoutingStage.BUILD,)
) -> lane_runs.RunAdded:
    return lane_runs.RunAdded(end_tip=end_tip, ran=ran, record=the_record())


def a_run(
    run: str = "run-1",
    *,
    start_tip: str | None = None,
    follows: bool = True,
    added: lane_runs.RunAdded | None = None,
) -> lane_runs.RunEntry:
    return lane_runs.RunEntry(run=run, start_tip=start_tip, follows=follows, added=added)


def runs_of(*entries: lane_runs.RunEntry) -> lane_runs.RunsFile:
    return lane_runs.RunsFile(entries)


def test_a_runs_file_reads_back_as_it_was_written() -> None:
    runs = runs_of(
        a_run("run-1", start_tip=FIRST_TIP, added=an_added_run(end_tip=SECOND_TIP)),
        a_run("run-2", follows=False),
    )

    read_back = lane_runs.parse_runs(lane_runs.serialize_runs(runs))

    assert read_back == runs


def test_a_runs_file_holds_the_version_and_each_run_in_begin_order() -> None:
    runs = runs_of(
        a_run("run-1", start_tip=FIRST_TIP, added=an_added_run(ran=(RoutingStage.BUILD,))),
        a_run("run-2", follows=False),
    )

    stored = json.loads(lane_runs.serialize_runs(runs))

    assert stored["version"] == 1
    assert [entry["run"] for entry in stored["runs"]] == ["run-1", "run-2"]
    assert stored["runs"][0]["start_tip"] == FIRST_TIP
    assert stored["runs"][0]["follows"] is True
    assert stored["runs"][0]["end_tip"] == SECOND_TIP
    assert stored["runs"][0]["ran"] == ["build"]
    assert stored["runs"][1]["start_tip"] is None
    assert stored["runs"][1]["follows"] is False


def test_a_begun_run_stores_no_end_tip_no_stages_and_no_record() -> None:
    stored = json.loads(lane_runs.serialize_runs(runs_of(a_run("run-1"))))

    assert sorted(stored["runs"][0]) == ["follows", "run", "start_tip"]


def test_an_added_run_stores_the_record_exactly_as_the_file_gave_it() -> None:
    stored = json.loads(lane_runs.serialize_runs(runs_of(a_run(added=an_added_run()))))

    assert stored["runs"][0]["record"] == lane_record_object()


def test_an_added_run_stores_no_key_the_file_left_out() -> None:
    bare = {key: value for key, value in lane_record_object().items() if key != "misses"}
    for key in ("risk", "experiment"):
        del bare[key]
    added = lane_runs.RunAdded(
        SECOND_TIP, (RoutingStage.REVIEW,), lane_record.parse_record_file(json.dumps(bare).encode())
    )

    stored = json.loads(lane_runs.serialize_runs(runs_of(a_run(added=added))))

    assert stored["runs"][0]["record"] == bare


def valid_runs_object() -> dict[str, object]:
    return {
        "version": 1,
        "runs": [
            {"run": "run-1", "start_tip": None, "follows": True},
            {
                "run": "run-2",
                "start_tip": FIRST_TIP,
                "follows": False,
                "end_tip": SECOND_TIP,
                "ran": ["build", "review"],
                "record": lane_record_object(),
            },
        ],
    }


def with_run_changed(index: int, **changes: object) -> Callable[[dict[str, object]], None]:
    def change(content: dict[str, object]) -> None:
        runs = content["runs"]
        assert isinstance(runs, list)
        runs[index] = {**runs[index], **changes}

    return change


def without_run_key(index: int, key: str) -> Callable[[dict[str, object]], None]:
    def drop(content: dict[str, object]) -> None:
        runs = content["runs"]
        assert isinstance(runs, list)
        del runs[index][key]

    return drop


def appended_run(entry: dict[str, object]) -> Callable[[dict[str, object]], None]:
    def append(content: dict[str, object]) -> None:
        runs = content["runs"]
        assert isinstance(runs, list)
        runs.append(entry)

    return append


def with_key(key: str, value: object) -> Callable[[dict[str, object]], None]:
    def change(content: dict[str, object]) -> None:
        content[key] = value

    return change


@pytest.mark.parametrize(
    "damage",
    [
        pytest.param(with_key("version", 2), id="another-version"),
        pytest.param(with_key("version", "1"), id="version-as-text"),
        pytest.param(with_key("extra", 1), id="extra-key"),
        pytest.param(with_key("runs", {}), id="runs-not-a-list"),
        pytest.param(with_run_changed(0, run="not a run id"), id="run-id-off-the-grammar"),
        pytest.param(with_run_changed(0, run="r" * 129), id="run-id-too-long"),
        pytest.param(with_run_changed(0, start_tip="abc"), id="start-tip-too-short"),
        pytest.param(with_run_changed(0, start_tip="A" * 40), id="start-tip-upper-case"),
        pytest.param(with_run_changed(0, follows="yes"), id="follows-not-a-boolean"),
        pytest.param(with_run_changed(0, extra=1), id="extra-run-key"),
        pytest.param(without_run_key(0, "follows"), id="missing-follows"),
        pytest.param(with_run_changed(1, end_tip="x"), id="end-tip-off-the-grammar"),
        pytest.param(with_run_changed(1, ran=[]), id="no-stage-ran"),
        pytest.param(with_run_changed(1, ran=["build", "build"]), id="a-stage-twice"),
        pytest.param(with_run_changed(1, ran=["land"]), id="land-did-not-run"),
        pytest.param(with_run_changed(1, ran="build"), id="ran-not-a-list"),
        pytest.param(without_run_key(1, "record"), id="added-without-record"),
        pytest.param(without_run_key(1, "end_tip"), id="added-without-end-tip"),
        pytest.param(with_run_changed(0, end_tip=SECOND_TIP), id="end-tip-without-the-rest"),
        pytest.param(
            with_run_changed(1, record={**lane_record_object(), "version": 2}),
            id="record-another-version",
        ),
        pytest.param(
            with_run_changed(1, record={**lane_record_object(), "fix_rounds": {}}),
            id="record-invalid",
        ),
        pytest.param(
            appended_run({"run": "run-1", "start_tip": None, "follows": True}),
            id="a-run-id-twice",
        ),
    ],
)
def test_a_runs_file_that_is_not_exactly_the_stored_shape_is_refused(
    damage: Callable[[dict[str, object]], None],
) -> None:
    content = valid_runs_object()
    damage(content)

    with pytest.raises(lane_runs.RunsFileError):
        lane_runs.parse_runs(json.dumps(content).encode())


@pytest.mark.parametrize(
    "content",
    [b"", b"not json", b"[]", b'{"version": 1}', b'{"version": 1, "runs": [], "version": 1}'],
)
def test_bytes_that_are_no_runs_object_are_refused(content: bytes) -> None:
    with pytest.raises(lane_runs.RunsFileError):
        lane_runs.parse_runs(content)


def test_the_valid_runs_file_these_cases_damage_is_accepted() -> None:
    parsed = lane_runs.parse_runs(json.dumps(valid_runs_object()).encode())

    assert [entry.run for entry in parsed.runs] == ["run-1", "run-2"]


@pytest.mark.parametrize(
    "earlier, start_tip, descends, expected",
    [
        pytest.param(None, None, False, True, id="first-run-without-a-start-tip"),
        pytest.param(None, FIRST_TIP, True, False, id="first-run-with-a-start-tip"),
        pytest.param(
            a_run(added=an_added_run(end_tip=FIRST_TIP)),
            FIRST_TIP,
            True,
            True,
            id="start-tip-is-the-earlier-end-tip",
        ),
        pytest.param(
            a_run(added=an_added_run(end_tip=FIRST_TIP)),
            SECOND_TIP,
            True,
            True,
            id="start-tip-descends-from-the-earlier-end-tip",
        ),
        pytest.param(
            a_run(added=an_added_run(end_tip=FIRST_TIP)),
            SECOND_TIP,
            False,
            False,
            id="start-tip-does-not-descend",
        ),
        pytest.param(
            a_run(added=an_added_run(end_tip=FIRST_TIP)),
            None,
            False,
            False,
            id="no-start-tip-after-an-earlier-run",
        ),
        pytest.param(
            a_run(added=None), SECOND_TIP, True, False, id="the-earlier-run-has-no-end-tip-yet"
        ),
    ],
)
def test_a_run_follows_when_it_starts_the_lane_or_descends_from_the_run_before(
    earlier: lane_runs.RunEntry | None,
    start_tip: str | None,
    descends: bool,
    expected: bool,
) -> None:
    follows = lane_runs.follows(earlier, start_tip, descends=descends)

    assert follows is expected


def test_the_end_tip_the_next_run_must_descend_from_is_the_newest_runs() -> None:
    older = a_run("run-1", added=an_added_run(end_tip=FIRST_TIP))
    newest = a_run("run-2", added=an_added_run(end_tip=SECOND_TIP))

    assert lane_runs.end_tip_to_follow(runs_of(older, newest)) == SECOND_TIP
    assert lane_runs.end_tip_to_follow(runs_of(older, a_run("run-3"))) is None
    assert lane_runs.end_tip_to_follow(runs_of()) is None


def test_a_begin_appends_the_run_after_the_runs_before_it() -> None:
    before = runs_of(a_run("run-1", added=an_added_run()))

    merged = lane_runs.begin(before, run="run-2", start_tip=SECOND_TIP, follows=True, label=LABEL)

    assert merged.changed is True
    assert merged.runs.runs == (*before.runs, a_run("run-2", start_tip=SECOND_TIP, follows=True))


def test_the_same_begin_again_changes_nothing_and_keeps_the_stored_decision() -> None:
    before = runs_of(a_run("run-1", start_tip=FIRST_TIP, follows=False))

    merged = lane_runs.begin(before, run="run-1", start_tip=FIRST_TIP, follows=True, label=LABEL)

    assert (merged.runs, merged.changed) == (before, False)


def test_a_begin_with_another_start_tip_is_refused() -> None:
    before = runs_of(a_run("run-1", start_tip=FIRST_TIP))

    with pytest.raises(lane_runs.RunsRefusedError, match=r"run-1 of #42 was begun with start tip"):
        lane_runs.begin(before, run="run-1", start_tip=SECOND_TIP, follows=True, label=LABEL)


def test_a_begin_with_a_start_tip_after_one_without_is_refused() -> None:
    before = runs_of(a_run("run-1", start_tip=None))

    with pytest.raises(lane_runs.RunsRefusedError, match="start tip none"):
        lane_runs.begin(before, run="run-1", start_tip=FIRST_TIP, follows=True, label=LABEL)


def test_a_begin_after_the_runs_add_is_refused_even_with_its_own_start_tip() -> None:
    before = runs_of(a_run("run-1", start_tip=FIRST_TIP, added=an_added_run()))

    with pytest.raises(lane_runs.RunsRefusedError, match="run-1 of #42"):
        lane_runs.begin(before, run="run-1", start_tip=FIRST_TIP, follows=True, label=LABEL)


def test_an_add_stores_the_record_on_the_begun_entry() -> None:
    before = runs_of(a_run("run-1", start_tip=FIRST_TIP), a_run("run-2"))
    added = an_added_run()

    merged = lane_runs.add(before, run="run-1", added=added, label=LABEL)

    assert merged.changed is True
    assert merged.runs.runs == (a_run("run-1", start_tip=FIRST_TIP, added=added), a_run("run-2"))


def test_an_add_of_a_run_that_was_not_begun_is_refused_naming_the_begin_command() -> None:
    with pytest.raises(lane_runs.RunsRefusedError) as refusal:
        lane_runs.add(runs_of(a_run("run-1")), run="run-2", added=an_added_run(), label=LABEL)

    assert str(refusal.value) == ("run run-2 of #42 was not begun; run aco lane-record begin first")


def test_the_same_entry_added_again_changes_nothing() -> None:
    before = runs_of(a_run("run-1", added=an_added_run()))

    merged = lane_runs.add(before, run="run-1", added=an_added_run(), label=LABEL)

    assert (merged.runs, merged.changed) == (before, False)


@pytest.mark.parametrize(
    "other",
    [
        pytest.param(lane_runs.RunAdded(THIRD_TIP, (RoutingStage.BUILD,), the_record()), id="tip"),
        pytest.param(
            lane_runs.RunAdded(SECOND_TIP, (RoutingStage.REVIEW,), the_record()), id="stages"
        ),
        pytest.param(
            lane_runs.RunAdded(SECOND_TIP, (RoutingStage.BUILD,), the_record(risk="risky")),
            id="record",
        ),
    ],
)
def test_another_entry_under_an_added_run_id_is_refused(other: lane_runs.RunAdded) -> None:
    before = runs_of(a_run("run-1", added=an_added_run()))

    with pytest.raises(lane_runs.RunsRefusedError, match="run-1 of #42"):
        lane_runs.add(before, run="run-1", added=other, label=LABEL)


def test_a_ran_stage_whose_slot_in_the_record_is_none_contradicts_the_record() -> None:
    record = the_record()
    assert record.stages[RoutingStage.GATE] == "none"

    with pytest.raises(lane_runs.RunsRefusedError) as refusal:
        lane_runs.require_ran_stages_run(record, (RoutingStage.BUILD, RoutingStage.GATE))

    assert str(refusal.value) == "the record's stage gate is none, which --ran contradicts"


def test_ran_stages_that_the_record_fills_are_accepted() -> None:
    lane_runs.require_ran_stages_run(
        the_record(), (RoutingStage.BUILD, RoutingStage.REVIEW, RoutingStage.TEST)
    )


def test_the_holder_refusal_names_the_action_the_item_and_both_agents() -> None:
    begin = lane_runs.holder_refusal(lane_runs.RunsAction.BEGIN, LABEL, session="Bea")("Ada")
    add = lane_runs.holder_refusal(lane_runs.RunsAction.ADD, LABEL, session="Bea")("Ada")

    assert begin == "only the holder may begin a run of #42 (holder='Ada', this session='Bea')"
    assert add == "only the holder may add a run to #42 (holder='Ada', this session='Bea')"


def test_the_stale_refusal_names_the_item_and_the_command_to_run_again() -> None:
    assert lane_runs.stale_refusal(LABEL) == (
        "the stored runs of #42 were written since this command read them; "
        "run the same command again"
    )
