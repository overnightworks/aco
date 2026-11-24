"""`aco lane-record begin` and `aco lane-record add` through the CLI on real git, under both
storages: a begin marks a run under the claim and an add stores its record, both as the claim's
holder, in the state ref's `runs/<claim-id>.json` (`specs/lane-record.spec.md`, "Stored runs")."""

import json
from pathlib import Path

import pytest
from claim_worktrees import assert_json_refusal_object
from cli_fixtures import real_git, run_cli
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
    race_before_the_push,
    stale_runs_sentence,
)

from aco import lane_runs, protocol, store
from aco.routing_line import RoutingStage


@pytest.fixture
def world(lane_record_runs_world: World) -> World:
    return lane_record_runs_world


def test_a_begin_then_an_add_store_the_run_under_the_claims_id_and_say_so(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-52, LANREC-55, LANREC-60. Example: E-LANREC-12."""
    began = world.run(capsys, *begin_arguments(world))
    added = world.run(capsys, *add_arguments(world))

    assert (began.status, began.stdout, began.stderr) == (
        0,
        f"BEGAN run {FIRST_RUN} of {world.label}\n",
        "",
    )
    assert (added.status, added.stdout, added.stderr) == (
        0,
        f"ADDED run {FIRST_RUN} to {world.label}: 1 stored\n",
        "",
    )
    stored = world.stored_runs()
    assert stored is not None
    [entry] = stored.runs
    assert (entry.run, entry.start_tip, entry.follows) == (FIRST_RUN, None, True)
    assert entry.added is not None
    assert (entry.added.end_tip, entry.added.ran) == (END_TIP, STAGES_RAN)
    assert world.runs_files() == [f"runs/{world.claim().claim_id}.json"]


def test_two_runs_are_stored_in_begin_order_and_the_add_count_counts_added_runs(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-52, LANREC-55. Example: E-LANREC-12."""
    world.run(capsys, *begin_arguments(world, FIRST_RUN))
    world.run(capsys, *add_arguments(world, FIRST_RUN))
    world.run(capsys, *begin_arguments(world, SECOND_RUN, "--start-tip", END_TIP))

    second = world.run(capsys, *add_arguments(world, SECOND_RUN, end_tip=OTHER_TIP))

    stored = world.stored_runs()
    assert stored is not None
    assert [entry.run for entry in stored.runs] == [FIRST_RUN, SECOND_RUN]
    assert second.stdout == f"ADDED run {SECOND_RUN} to {world.label}: 2 stored\n"


def test_the_commits_name_the_run_and_carry_no_lane_trailer_so_stats_counts_no_lane(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-60."""
    begun = world.run(capsys, *begin_arguments(world))
    begin_message = world.commit_message()
    added = world.run(capsys, *add_arguments(world))
    add_message = world.commit_message()
    stats = run_cli(["stats", "2000-01-01..2100-01-01", "tag:unused", "--json"], capsys)

    assert (begun.status, added.status) == (0, 0)
    for message in (begin_message, add_message):
        assert message.startswith("lane-record issue ")
        assert f"intent: lane_record\nrun: {FIRST_RUN}\n" in message
        assert "\nlane_" not in message
    assert json.loads(stats.stdout)["a"]["lanes"] == 0


def test_a_repeated_begin_changes_nothing_and_says_so(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-53."""
    world.run(capsys, *begin_arguments(world, FIRST_RUN, "--start-tip", END_TIP))
    tip = world.state_tip()

    again = world.run(capsys, *begin_arguments(world, FIRST_RUN, "--start-tip", END_TIP))

    assert (again.status, again.stdout) == (0, f"ALREADY BEGUN run {FIRST_RUN} of {world.label}\n")
    assert world.state_tip() == tip


def test_a_repeated_begin_keeps_the_follows_judged_at_its_first_begin(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-53, LANREC-54."""
    world.run(capsys, *begin_arguments(world, FIRST_RUN))
    world.run(capsys, *begin_arguments(world, SECOND_RUN))
    tip = world.state_tip()

    again = world.run(capsys, *begin_arguments(world, FIRST_RUN, "--json"))

    stored = world.stored_runs()
    assert stored is not None
    assert stored.runs[0].follows is True
    assert json.loads(again.stdout)["follows"] is True
    assert json.loads(again.stdout)["reason"] == "already_begun"
    assert world.state_tip() == tip


@pytest.mark.parametrize(
    "later",
    [
        pytest.param(("--start-tip", OTHER_TIP), id="another-start-tip"),
        pytest.param((), id="no-start-tip"),
    ],
)
def test_a_begin_of_a_begun_run_with_another_start_tip_refuses_and_writes_nothing(
    world: World, capsys: pytest.CaptureFixture[str], later: tuple[str, ...]
) -> None:
    """Spec: LANREC-53."""
    world.run(capsys, *begin_arguments(world, FIRST_RUN, "--start-tip", END_TIP))
    tip = world.state_tip()

    refused = world.run(capsys, *begin_arguments(world, FIRST_RUN, *later))

    assert refused.status == 2
    assert refused.stderr.startswith(f"ERROR: run {FIRST_RUN} of {world.label} was begun")
    assert world.state_tip() == tip


def test_a_begin_after_the_runs_add_refuses(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-64."""
    world.run(capsys, *begin_arguments(world))
    world.run(capsys, *add_arguments(world))
    tip = world.state_tip()

    refused = world.run(capsys, *begin_arguments(world))

    assert refused.status == 2
    assert f"run {FIRST_RUN} of {world.label}" in refused.stderr
    assert world.state_tip() == tip


def test_a_repeated_add_changes_nothing_and_says_so(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-56."""
    world.run(capsys, *begin_arguments(world))
    world.run(capsys, *add_arguments(world))
    tip = world.state_tip()

    again = world.run(capsys, *add_arguments(world))

    assert (again.status, again.stdout) == (
        0,
        f"ALREADY ADDED run {FIRST_RUN} to {world.label}: 1 stored\n",
    )
    assert world.state_tip() == tip


@pytest.mark.parametrize(
    ("end_tip", "stages", "file_changes"),
    [
        pytest.param(OTHER_TIP, STAGES_RAN, {}, id="end-tip"),
        pytest.param(END_TIP, (RoutingStage.BUILD,), {}, id="stages"),
        pytest.param(END_TIP, STAGES_RAN, {"risk": "material"}, id="record"),
    ],
)
def test_another_entry_under_an_added_run_id_refuses_and_writes_nothing(
    world: World,
    capsys: pytest.CaptureFixture[str],
    end_tip: str,
    stages: tuple[RoutingStage, ...],
    file_changes: dict[str, object],
) -> None:
    """Spec: LANREC-56."""
    world.run(capsys, *begin_arguments(world))
    world.run(capsys, *add_arguments(world))
    tip = world.state_tip()
    file = world.record_file(**file_changes)

    refused = world.run(capsys, *add_arguments(world, file=file, end_tip=end_tip, stages=stages))

    assert refused.status == 2
    assert f"run {FIRST_RUN} of {world.label}" in refused.stderr
    assert world.state_tip() == tip


def test_an_add_of_a_run_that_was_not_begun_refuses_naming_the_begin_command(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-57. Example: E-LANREC-14."""
    refused = world.run(capsys, *add_arguments(world))

    assert (refused.status, refused.stdout) == (2, "")
    assert refused.stderr == (
        f"ERROR: run {FIRST_RUN} of {world.label} was not begun; run aco lane-record begin first\n"
    )
    assert world.runs_files() == []


def test_an_add_whose_ran_stage_is_none_in_the_file_refuses_contradicting_it(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-66."""
    world.run(capsys, *begin_arguments(world))

    refused = world.run(
        capsys, *add_arguments(world, stages=(RoutingStage.BUILD, RoutingStage.GATE))
    )

    assert refused.status == 2
    assert refused.stderr == "ERROR: the record's stage gate is none, which --ran contradicts\n"


def test_an_add_of_a_file_that_check_refuses_refuses_with_the_same_sentence(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-66, LANREC-31."""
    world.run(capsys, *begin_arguments(world))
    file = world.record_file(version=2)
    checked = run_cli(["lane-record", "check", str(file)], capsys)

    refused = world.run(capsys, *add_arguments(world, file=file))

    assert refused.status == checked.status == 2
    assert refused.stderr == checked.stderr


def test_a_non_holder_is_refused_a_begin_and_an_add_naming_the_holder_and_itself(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-63. Example: E-LANREC-13."""
    world.run(capsys, *begin_arguments(world))
    tip = world.state_tip()

    begin = world.run(capsys, *begin_arguments(world, SECOND_RUN, "--agent", OTHER_AGENT))
    add = world.run(capsys, *add_arguments(world, flags=("--agent", OTHER_AGENT)))

    assert begin.stderr == (
        f"ERROR: only the holder may begin a run of {world.label} "
        f"(holder='Ada', this session='{OTHER_AGENT}')\n"
    )
    assert add.stderr == (
        f"ERROR: only the holder may add a run to {world.label} "
        f"(holder='Ada', this session='{OTHER_AGENT}')\n"
    )
    assert (begin.status, add.status) == (2, 2)
    assert world.state_tip() == tip


def test_an_unclaimed_item_refuses_with_the_release_commands_sentence(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-68."""
    claim = world.claim()
    world.commit_state(
        protocol.ReleaseIntent(
            claim_id=claim.claim_id,
            agent="Ada",
            role=claim.role,
            outcome=protocol.AbandonedRelease("done"),
            operation_id="op-release",
        )
    )

    begin = world.run(capsys, *begin_arguments(world))
    add = world.run(capsys, *add_arguments(world))

    assert (begin.status, add.status) == (2, 2)
    assert begin.stderr == f"ERROR: issue {world.label} has no active build claim\n"
    assert add.stderr == begin.stderr


def test_stored_runs_survive_a_handover_and_only_the_new_holder_may_add(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-61, HANDOVER-15."""
    world.run(capsys, *begin_arguments(world))
    claim = world.claim()
    before = world.stored_runs()
    world.commit_state(
        protocol.HandoverIntent(
            claim_id=claim.claim_id,
            previous_agent="Ada",
            agent=OTHER_AGENT,
            operation_id="op-handover",
        )
    )

    late = world.run(capsys, *add_arguments(world))
    added = world.run(capsys, *add_arguments(world, flags=("--agent", OTHER_AGENT)))
    begun = world.run(capsys, *begin_arguments(world, SECOND_RUN, "--agent", OTHER_AGENT))

    assert world.stored_runs() != before
    assert late.status == 2
    assert f"holder='{OTHER_AGENT}', this session='Ada'" in late.stderr
    assert (added.status, begun.status) == (0, 0)
    stored = world.stored_runs()
    assert stored is not None
    assert [entry.run for entry in stored.runs] == [FIRST_RUN, SECOND_RUN]
    assert stored.runs[0].added is not None


def test_stored_runs_survive_a_rescope(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Spec: LANREC-61."""
    world.run(capsys, *begin_arguments(world))
    claim = world.claim()
    before = world.stored_runs()
    world.commit_state(
        protocol.RescopeIntent(
            claim_id=claim.claim_id,
            agent="Ada",
            role=claim.role,
            scope=(*claim.scope, "src/extra.py"),
            operation_id="op-rescope",
        )
    )

    after = world.stored_runs()
    added = world.run(capsys, *add_arguments(world))

    assert after == before
    assert added.status == 0


def test_a_release_removes_the_runs_file_in_its_own_commit_and_a_reclaim_starts_empty(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-67, REL-68."""
    world.run(capsys, *begin_arguments(world))
    world.run(capsys, *add_arguments(world))
    claim = world.claim()
    assert world.runs_files() == [f"runs/{claim.claim_id}.json"]

    released = world.run(capsys, "release", world.item, "--abandoned", "stopped for the day")
    assert released.status == 0, released.stderr
    assert world.runs_files() == []
    assert world.commit_message().startswith("release issue ")

    reclaimed = reclaim(world, claim, "claim-2")
    world.run(capsys, *begin_arguments(world, SECOND_RUN))

    stored = world.stored_runs(reclaimed.claim_id)
    assert stored is not None
    assert [entry.run for entry in stored.runs] == [SECOND_RUN]
    assert world.runs_files() == [f"runs/{reclaimed.claim_id}.json"]


def reclaim(world: World, released: protocol.ActiveClaim, claim_id: str) -> protocol.ActiveClaim:
    """The claim of the same item taken again under `claim_id`, by the same agent."""
    world.commit_state(
        protocol.ClaimIntent(
            identity=released.identity,
            agent=released.agent,
            role=released.role,
            base=released.base,
            branch=released.branch,
            scope=released.scope,
            claim_id=protocol.ClaimId(claim_id),
            operation_id=f"op-{claim_id}",
        )
    )
    return world.claim()


def test_a_start_tip_that_merges_trunk_onto_the_earlier_end_tip_follows(
    world: World, capsys: pytest.CaptureFixture[str], github_clone: Path
) -> None:
    """Spec: LANREC-54. Example: E-LANREC-12."""
    earlier_end = commit_on(world.directory, "lane.txt")
    world.run(capsys, *begin_arguments(world, FIRST_RUN))
    world.run(capsys, *add_arguments(world, FIRST_RUN, end_tip=earlier_end))
    commit_on(github_clone, "trunk.txt")
    real_git(world.directory, "merge", "-q", "--no-edit", "main")
    merged = real_git(world.directory, "rev-parse", "HEAD").stdout.strip()

    begun = world.run(capsys, *begin_arguments(world, SECOND_RUN, "--start-tip", merged, "--json"))

    stored = world.stored_runs()
    assert stored is not None
    assert stored.runs[1].follows is True
    assert json.loads(begun.stdout)["follows"] is True


def test_a_start_tip_that_does_not_descend_from_the_earlier_end_tip_does_not_follow(
    world: World, capsys: pytest.CaptureFixture[str], github_clone: Path
) -> None:
    """Spec: LANREC-54."""
    commit_on(world.directory, "lane.txt")
    earlier_end = real_git(world.directory, "rev-parse", "HEAD").stdout.strip()
    world.run(capsys, *begin_arguments(world, FIRST_RUN))
    world.run(capsys, *add_arguments(world, FIRST_RUN, end_tip=earlier_end))
    elsewhere = commit_on(github_clone, "trunk.txt")

    begun = world.run(
        capsys, *begin_arguments(world, SECOND_RUN, "--start-tip", elsewhere, "--json")
    )

    stored = world.stored_runs()
    assert stored is not None
    assert stored.runs[1].follows is False
    assert json.loads(begun.stdout)["follows"] is False


@pytest.mark.parametrize(
    "first_flags, first_follows",
    [
        pytest.param((), True, id="first-run-without-a-start-tip"),
        pytest.param(("--start-tip", END_TIP), False, id="first-run-with-a-start-tip"),
        pytest.param(("--start-tip", "f" * 40), False, id="first-run-with-an-unreadable-tip"),
    ],
)
def test_the_first_run_follows_only_without_a_start_tip(
    world: World,
    capsys: pytest.CaptureFixture[str],
    first_flags: tuple[str, ...],
    first_follows: bool,
) -> None:
    """Spec: LANREC-54, LANREC-65."""
    world.run(capsys, *begin_arguments(world, FIRST_RUN, *first_flags))

    stored = world.stored_runs()

    assert stored is not None
    assert stored.runs[0].follows is first_follows


def test_a_run_after_one_that_has_no_end_tip_yet_does_not_follow(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-65."""
    world.run(capsys, *begin_arguments(world, FIRST_RUN))
    head = real_git(world.directory, "rev-parse", "HEAD").stdout.strip()

    world.run(capsys, *begin_arguments(world, SECOND_RUN, "--start-tip", head))

    stored = world.stored_runs()
    assert stored is not None
    assert stored.runs[1].follows is False


def test_a_run_after_an_unreadable_end_tip_does_not_follow(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-65."""
    world.run(capsys, *begin_arguments(world, FIRST_RUN))
    world.run(capsys, *add_arguments(world, FIRST_RUN, end_tip="e" * 40))
    head = real_git(world.directory, "rev-parse", "HEAD").stdout.strip()

    world.run(capsys, *begin_arguments(world, SECOND_RUN, "--start-tip", head))

    stored = world.stored_runs()
    assert stored is not None
    assert stored.runs[1].follows is False


def test_json_begin_reports_a_fresh_run_as_begun_and_a_repeat_as_already_begun(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-52, LANREC-53, LANREC-69."""
    fresh = world.run(capsys, *begin_arguments(world), "--json")
    repeated = world.run(capsys, *begin_arguments(world), "--json")

    assert [json.loads(fresh.stdout)["reason"], json.loads(repeated.stdout)["reason"]] == [
        "begun",
        "already_begun",
    ]
    assert json.loads(fresh.stdout)["ok"] is True
    assert json.loads(fresh.stdout)["run"] == FIRST_RUN


def test_json_add_reports_a_fresh_entry_as_added_and_a_repeat_as_already_added(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-55, LANREC-56, LANREC-69."""
    world.run(capsys, *begin_arguments(world))

    fresh = world.run(capsys, *add_arguments(world), "--json")
    repeated = world.run(capsys, *add_arguments(world), "--json")

    assert [json.loads(fresh.stdout)["reason"], json.loads(repeated.stdout)["reason"]] == [
        "added",
        "already_added",
    ]
    assert json.loads(fresh.stdout)["stored"] == 1


def test_json_refusals_name_their_reason(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Spec: LANREC-57, LANREC-63, LANREC-66, LANREC-89."""
    unbegun = world.run(capsys, *add_arguments(world), "--json")
    stranger = world.run(
        capsys, *begin_arguments(world, FIRST_RUN, "--agent", OTHER_AGENT, "--json")
    )
    refused_file = world.record_file(version=2)
    unreadable = world.run(capsys, *add_arguments(world, file=refused_file), "--json")

    assert_json_refusal_object(unbegun.stderr, unbegun.stdout, reason="precondition_failed")
    assert_json_refusal_object(stranger.stderr, stranger.stdout, reason="precondition_failed")
    assert_json_refusal_object(unreadable.stderr, unreadable.stdout, reason="precondition_failed")


def test_stored_runs_that_changed_since_the_command_read_them_refuse_as_a_transient_refusal(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: LANREC-59, LANREC-89."""
    world.run(capsys, *begin_arguments(world, FIRST_RUN))
    competing = lane_runs.RunsFile((lane_runs.RunEntry("run-x", None, True),))
    race_before_the_push(
        monkeypatch, lambda: world.store_runs_file(lane_runs.serialize_runs(competing))
    )

    refused = world.run(capsys, *begin_arguments(world, SECOND_RUN, "--json"))

    assert refused.status == 2
    assert_json_refusal_object(refused.stderr, refused.stdout, reason="unavailable")
    assert refused.stderr == f"ERROR: {stale_runs_sentence(world.label)}\n"
    stored = world.stored_runs()
    assert stored is not None
    assert [entry.run for entry in stored.runs] == ["run-x"]


@pytest.mark.parametrize("command", ["begin", "add"])
def test_stored_runs_that_are_not_the_stored_shape_refuse_and_write_nothing(
    world: World, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    """Spec: LANREC-62."""
    claim = world.claim()
    world.commit_state(
        protocol.RunsWriteIntent(
            claim_id=claim.claim_id,
            agent="Ada",
            expected=None,
            new_oid=store.hash_blob(world.directory, b"not json"),
            operation_id="op-malformed",
            holder_refusal="{}".format,
            stale_refusal="never reached",
        )
    )
    tip = world.state_tip()
    arguments = begin_arguments(world) if command == "begin" else add_arguments(world)

    refused = world.run(capsys, *arguments)

    assert refused.status == 2
    assert refused.stderr == (
        f"ERROR: the stored runs of {world.label} cannot be used: not valid JSON\n"
    )
    assert world.state_tip() == tip


@pytest.mark.parametrize("command", ["begin", "add"])
def test_a_non_holder_is_refused_as_one_before_the_stored_runs_are_read(
    world: World, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    """Spec: LANREC-63, LANREC-89."""
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
    arguments = (
        begin_arguments(world, FIRST_RUN, "--agent", OTHER_AGENT, "--json")
        if command == "begin"
        else add_arguments(world, flags=("--agent", OTHER_AGENT, "--json"))
    )

    refused = world.run(capsys, *arguments)

    assert refused.status == 2
    assert f"holder='Ada', this session='{OTHER_AGENT}'" in refused.stderr
    assert_json_refusal_object(refused.stderr, refused.stdout, reason="precondition_failed")
