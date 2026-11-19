"""`aco lane-record begin` and `aco lane-record add` through the CLI on real git, under both
storages: a begin marks a run under the claim and an add stores its record, both as the claim's
holder, in the state ref's `runs/<claim-id>.json` (`specs/lane-record.spec.md`, "Stored runs")."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, complete_contract
from claim_worktrees import (
    ISSUE,
    StandIn,
    assert_json_refusal_object,
    held_by_ada,
    make_stand_in,
)
from cli_fixtures import CliRun, real_git, run_cli
from lane_record_fixtures import lane_record_object, write_lane_record_file

from aco import body, lane_runs, protocol, store
from aco.routing_line import RoutingStage

TRUNK_FILES = ("src/widget.py",)
HELD_SCOPE = ("src/widget.py",)
FIRST_RUN = "run-1"
SECOND_RUN = "run-2"
OTHER_AGENT = "Bea"
END_TIP = "b" * 40
OTHER_TIP = "c" * 40
STAGES_RAN = (RoutingStage.BUILD, RoutingStage.REVIEW)


@dataclass(frozen=True)
class World:
    """A claimed item under one storage, the checkout a command runs in and its bare remote."""

    storage: body.Storage
    item: str
    label: str
    arguments_before_command: tuple[str, ...]
    directory: Path
    remote: Path
    scratch: Path

    def claim(self) -> protocol.ActiveClaim:
        [claim] = standing_claims_of(self)
        return claim

    def run(self, capsys: pytest.CaptureFixture[str], *command: str) -> CliRun:
        return run_cli([*self.arguments_before_command, *command], capsys)

    def commit_state(self, intent: protocol.ClaimTransitionIntent, subject: str = "test") -> None:
        observed = store.fetch_state(worktree=self.directory, remote="origin")
        store.commit_transition(
            observed=store.Observation(self.directory, "origin", observed),
            subject=store.TransitionSubject(subject),
            intent=intent,
        )

    def state_tip(self) -> str:
        return real_git(self.remote, "rev-parse", store.STATE_REF).stdout.strip()

    def stored_runs(self, claim_id: str | None = None) -> lane_runs.RunsFile | None:
        name = claim_id if claim_id is not None else self.claim().claim_id
        shown = real_git(self.remote, "show", f"{store.STATE_REF}:runs/{name}.json", check=False)
        return None if shown.returncode != 0 else lane_runs.parse_runs(shown.stdout.encode())

    def runs_files(self) -> list[str]:
        listing = real_git(self.remote, "ls-tree", "-r", "--name-only", store.STATE_REF).stdout
        return [path for path in listing.splitlines() if path.startswith("runs/")]

    def commit_message(self) -> str:
        return real_git(self.remote, "log", "-1", "--format=%B", store.STATE_REF).stdout

    def record_file(self, **changes: object) -> Path:
        return write_lane_record_file(self.scratch, lane_record_object(**changes))


def standing_claims_of(world: World) -> list[protocol.ActiveClaim]:
    state = store.fetch_state(worktree=world.directory, remote="origin")
    return list(state.claims.values())


@pytest.fixture(params=[body.Storage.GITHUB, body.Storage.STATE_REF], ids=["github", "state-ref"])
def world(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    github_clone: Path,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> World:
    stand_in: StandIn = make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    if request.param is body.Storage.GITHUB:
        standpoint = stand_in(standing=held_by_ada(HELD_SCOPE))
        return World(
            body.Storage.GITHUB,
            str(ISSUE),
            f"#{ISSUE}",
            ("--repo", REPOSITORY),
            standpoint.directory,
            bare_remote,
            scratch,
        )
    standpoint = stand_in(board_config=f'storage = "{body.Storage.STATE_REF.value}"\n')
    minted = run_cli(
        ["item", "new", "--title", "Runs"],
        capsys,
        stdin=complete_contract("Build it.", scope=["src"], whole="the scenario claims it as one"),
    )
    item = minted.stdout.strip()
    claimed = run_cli(["claim", item, "--agent", "Ada", "--scope", "src"], capsys)
    assert claimed.status == 0, claimed.stderr
    return World(body.Storage.STATE_REF, item, item, (), standpoint.directory, bare_remote, scratch)


def begin_arguments(world: World, run: str = FIRST_RUN, *flags: str) -> tuple[str, ...]:
    return ("lane-record", "begin", world.item, "--run", run, *flags)


def add_arguments(
    world: World,
    run: str = FIRST_RUN,
    *,
    file: Path | None = None,
    end_tip: str = END_TIP,
    stages: tuple[RoutingStage, ...] = STAGES_RAN,
    flags: tuple[str, ...] = (),
) -> tuple[str, ...]:
    record = file if file is not None else world.record_file()
    return (
        "lane-record",
        "add",
        world.item,
        str(record),
        "--run",
        run,
        "--end-tip",
        end_tip,
        "--ran",
        *stages,
        *flags,
    )


def commit_on(directory: Path, name: str) -> str:
    """One commit adding `name` to the checkout at `directory`; its sha."""
    (directory / name).write_text(f"{name}\n")
    real_git(directory, "add", name)
    real_git(directory, "commit", "-q", "-m", f"add {name}")
    return real_git(directory, "rev-parse", "HEAD").stdout.strip()


def test_a_begin_then_an_add_store_the_run_under_the_claims_id_and_say_so(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-52, LANREC-55, LANREC-60, E-LANREC-12."""
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
    """Spec: LANREC-52, LANREC-55, E-LANREC-12."""
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
    """Spec: LANREC-53."""
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
    "other",
    [
        pytest.param({"end_tip": OTHER_TIP}, id="end-tip"),
        pytest.param({"stages": (RoutingStage.BUILD,)}, id="stages"),
        pytest.param({"file_changes": {"risk": "other"}}, id="record"),
    ],
)
def test_another_entry_under_an_added_run_id_refuses_and_writes_nothing(
    world: World, capsys: pytest.CaptureFixture[str], other: dict[str, object]
) -> None:
    """Spec: LANREC-56."""
    world.run(capsys, *begin_arguments(world))
    world.run(capsys, *add_arguments(world))
    tip = world.state_tip()
    changes = other.get("file_changes")
    file = world.record_file(**changes) if isinstance(changes, dict) else None
    keywords = {key: value for key, value in other.items() if key != "file_changes"}

    refused = world.run(capsys, *add_arguments(world, file=file, **keywords))  # type: ignore[arg-type]

    assert refused.status == 2
    assert f"run {FIRST_RUN} of {world.label}" in refused.stderr
    assert world.state_tip() == tip


def test_an_add_of_a_run_that_was_not_begun_refuses_naming_the_begin_command(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-57, E-LANREC-14."""
    refused = world.run(capsys, *add_arguments(world))

    assert (refused.status, refused.stdout) == (2, "")
    assert refused.stderr == (
        f"ERROR: run {FIRST_RUN} of {world.label} was not begun; run aco lane-record begin first\n"
    )
    assert world.runs_files() == []


def test_an_add_whose_ran_stage_is_none_in_the_file_refuses_contradicting_it(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-55."""
    world.run(capsys, *begin_arguments(world))

    refused = world.run(
        capsys, *add_arguments(world, stages=(RoutingStage.BUILD, RoutingStage.GATE))
    )

    assert refused.status == 2
    assert refused.stderr == "ERROR: the record's stage gate is none, which --ran contradicts\n"


def test_an_add_of_a_file_that_check_refuses_refuses_with_the_same_sentence(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-55, LANREC-31."""
    world.run(capsys, *begin_arguments(world))
    file = world.record_file(version=2)
    checked = run_cli(["lane-record", "check", str(file)], capsys)

    refused = world.run(capsys, *add_arguments(world, file=file))

    assert refused.status == checked.status == 2
    assert refused.stderr == checked.stderr


def test_a_non_holder_is_refused_a_begin_and_an_add_naming_the_holder_and_itself(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-52, LANREC-55, E-LANREC-13."""
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
    """Spec: LANREC-52, LANREC-55."""
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
    """Spec: LANREC-61, HANDOVER-02."""
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
    """Spec: LANREC-61, REL-04."""
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
    """Spec: LANREC-54, E-LANREC-12."""
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
    """Spec: LANREC-54."""
    world.run(capsys, *begin_arguments(world, FIRST_RUN, *first_flags))

    stored = world.stored_runs()

    assert stored is not None
    assert stored.runs[0].follows is first_follows


def test_a_run_after_one_that_has_no_end_tip_yet_does_not_follow(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-54."""
    world.run(capsys, *begin_arguments(world, FIRST_RUN))
    head = real_git(world.directory, "rev-parse", "HEAD").stdout.strip()

    world.run(capsys, *begin_arguments(world, SECOND_RUN, "--start-tip", head))

    stored = world.stored_runs()
    assert stored is not None
    assert stored.runs[1].follows is False


def test_a_run_after_an_unreadable_end_tip_does_not_follow(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-54."""
    world.run(capsys, *begin_arguments(world, FIRST_RUN))
    world.run(capsys, *add_arguments(world, FIRST_RUN, end_tip="e" * 40))
    head = real_git(world.directory, "rev-parse", "HEAD").stdout.strip()

    world.run(capsys, *begin_arguments(world, SECOND_RUN, "--start-tip", head))

    stored = world.stored_runs()
    assert stored is not None
    assert stored.runs[1].follows is False


@pytest.mark.parametrize(
    "flags",
    [
        pytest.param(("--run", "has space"), id="run-id-with-a-space"),
        pytest.param(("--run", "-leading-dash"), id="run-id-starting-with-a-dash"),
        pytest.param(("--run", "r" * 129), id="run-id-past-128-characters"),
        pytest.param(("--run", FIRST_RUN, "--start-tip", "abc"), id="start-tip-too-short"),
        pytest.param(("--run", FIRST_RUN, "--start-tip", "A" * 40), id="start-tip-upper-case"),
    ],
)
def test_a_begin_flag_off_the_grammar_is_a_usage_refusal(
    world: World, capsys: pytest.CaptureFixture[str], flags: tuple[str, ...]
) -> None:
    """Spec: LANREC-58."""
    refused = world.run(capsys, "lane-record", "begin", world.item, *flags)

    assert refused.status == 2
    assert refused.stdout == ""
    assert "usage:" in refused.stderr
    assert world.runs_files() == []


@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param({"end_tip": "abc"}, id="end-tip-too-short"),
        pytest.param({"end_tip": "G" * 40}, id="end-tip-not-hexadecimal"),
    ],
)
def test_an_add_tip_off_the_grammar_is_a_usage_refusal(
    world: World, capsys: pytest.CaptureFixture[str], replacement: dict[str, str]
) -> None:
    """Spec: LANREC-58."""
    world.run(capsys, *begin_arguments(world))

    refused = world.run(capsys, *add_arguments(world, **replacement))

    assert refused.status == 2
    assert "usage:" in refused.stderr


def test_an_add_without_a_stage_or_with_an_unknown_stage_is_a_usage_refusal(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-58."""
    world.run(capsys, *begin_arguments(world))
    file = str(world.record_file())
    common = ("lane-record", "add", world.item, file, "--run", FIRST_RUN, "--end-tip", END_TIP)

    without = world.run(capsys, *common)
    unknown = world.run(capsys, *common, "--ran", "land")

    assert (without.status, unknown.status) == (2, 2)
    assert "usage:" in without.stderr
    assert "usage:" in unknown.stderr


def test_a_stage_named_twice_is_a_usage_refusal(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-58."""
    world.run(capsys, *begin_arguments(world))

    refused = world.run(
        capsys, *add_arguments(world, stages=(RoutingStage.BUILD, RoutingStage.BUILD))
    )

    assert refused.status == 2
    assert "build" in refused.stderr


@pytest.mark.parametrize("command", ["begin", "add"])
def test_a_missing_agent_identity_refuses_before_any_write(
    world: World,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    """Spec: LANREC-52, LANREC-55."""
    monkeypatch.delenv("ACO_AGENT")
    tip = world.state_tip()
    arguments = begin_arguments(world) if command == "begin" else add_arguments(world)

    refused = world.run(capsys, *arguments)

    assert refused.status == 2
    assert "agent identity is required" in refused.stderr
    assert world.state_tip() == tip


def test_json_begin_reports_a_fresh_run_as_begun_and_a_repeat_as_already_begun(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-52, LANREC-53."""
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
    """Spec: LANREC-55, LANREC-56."""
    world.run(capsys, *begin_arguments(world))

    fresh = world.run(capsys, *add_arguments(world), "--json")
    repeated = world.run(capsys, *add_arguments(world), "--json")

    assert [json.loads(fresh.stdout)["reason"], json.loads(repeated.stdout)["reason"]] == [
        "added",
        "already_added",
    ]
    assert json.loads(fresh.stdout)["stored"] == 1


def test_json_refusals_name_their_reason(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Spec: LANREC-52, LANREC-57."""
    unbegun = world.run(capsys, *add_arguments(world), "--json")
    stranger = world.run(
        capsys, *begin_arguments(world, FIRST_RUN, "--agent", OTHER_AGENT, "--json")
    )

    assert_json_refusal_object(unbegun.stderr, unbegun.stdout, reason="precondition_failed")
    assert_json_refusal_object(stranger.stderr, stranger.stdout, reason="precondition_failed")


def test_stored_runs_that_changed_since_the_command_read_them_refuse_as_a_transient_refusal(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: LANREC-59."""
    world.run(capsys, *begin_arguments(world, FIRST_RUN))
    claim = world.claim()
    stored_before = store.fetch_state(worktree=world.directory, remote="origin").runs[
        claim.claim_id
    ]
    competing = lane_runs.RunsFile((lane_runs.RunEntry("run-x", None, True),))
    real_commit_transition = store.commit_transition

    def commit_after_a_competing_write(
        *,
        observed: store.Observation,
        subject: store.TransitionSubject,
        intent: protocol.ClaimTransitionIntent,
    ) -> protocol.ClaimState:
        monkeypatch.setattr(store, "commit_transition", real_commit_transition)
        world.commit_state(
            protocol.RunsWriteIntent(
                claim_id=claim.claim_id,
                agent="Ada",
                expected=stored_before,
                new_oid=store.hash_blob(world.directory, lane_runs.serialize_runs(competing)),
                operation_id="op-competing",
                holder_refusal="{}".format,
                stale_refusal="never reached",
            )
        )
        return real_commit_transition(observed=observed, subject=subject, intent=intent)

    monkeypatch.setattr(store, "commit_transition", commit_after_a_competing_write)

    refused = world.run(capsys, *begin_arguments(world, SECOND_RUN, "--json"))

    assert refused.status == 2
    assert_json_refusal_object(refused.stderr, refused.stdout, reason="unavailable")
    assert refused.stderr == (
        f"ERROR: the stored runs of {world.label} were written since this command read them; "
        "run the same command again\n"
    )
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
