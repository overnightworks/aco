"""The claimed item, checkout and bare remote the `aco lane-record begin` and `add` tests run
against under both storages, registered as the pytest plugin that gives those modules their
`lane_record_runs_world` fixture (`tests/conftest.py`)."""

import dataclasses
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, complete_contract
from claim_worktrees import ISSUE, StandIn, held_by_ada, make_stand_in
from cli_fixtures import CliRun, real_git, run_cli
from lane_record_fixtures import lane_record_object, write_lane_record_file
from store_fixtures import lane_trailers

from aco import body, lane_record, lane_runs, protocol, state_runs, store
from aco.routing_line import RoutingStage

TRUNK_FILES = ("src/widget.py",)
HELD_SCOPE = ("src/widget.py",)
FIRST_RUN = "run-1"
SECOND_RUN = "run-2"
OTHER_AGENT = "Bea"
LANDING_CLAIM_ID = protocol.ClaimId("landing")
END_TIP = "b" * 40
OTHER_TIP = "c" * 40
STAGES_RAN = (RoutingStage.BUILD, RoutingStage.REVIEW)
MEASURED = (
    "lane_outcome:",
    "lane_merge:",
    "lane_wall_seconds:",
    "lane_files:",
    "lane_added:",
    "lane_deleted:",
    "lane_size:",
)
SUMMED_TRAILERS = (
    "lane_build: sonnet-5.5/high",
    "lane_fix: none",
    "lane_review: opus-5.5/medium",
    "lane_test: none",
    "lane_gate: none",
    "lane_land: haiku-5.5/low",
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
    "lane_misses_ci: 2",
    "lane_misses_test: 0",
)


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

    def store_runs_file(self, content: bytes) -> None:
        """The claim's runs file replaced by `content`, whatever it holds."""
        claim = self.claim()
        commit_runs_file(self.directory, "origin", claim.claim_id, content, agent=claim.agent)

    def commit_message(self) -> str:
        return real_git(self.remote, "log", "-1", "--format=%B", store.STATE_REF).stdout

    def record_file(self, **changes: object) -> Path:
        return write_lane_record_file(self.scratch, lane_record_object(**changes))


def standing_claims_of(world: World) -> list[protocol.ActiveClaim]:
    state = store.fetch_state(worktree=world.directory, remote="origin")
    return list(state.claims.values())


@pytest.fixture(params=[body.Storage.GITHUB, body.Storage.STATE_REF], ids=["github", "state-ref"])
def lane_record_runs_world(
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


def stale_runs_sentence(label: str) -> str:
    """The refusal of a command whose claim's runs file changed after the command read it."""
    return (
        f"the stored runs of {label} were written since this command read them; "
        "run the same command again"
    )


def routing_trailers_of(remote: Path) -> tuple[str, ...]:
    """The figures the release commit at the tip of `remote`'s state ref states beyond the
    measured lines."""
    return tuple(line for line in lane_trailers(remote) if not line.startswith(MEASURED))


def commit_runs_file(
    directory: Path,
    remote: Path | str,
    claim_id: protocol.ClaimId,
    content: bytes,
    *,
    agent: str = "Ada",
) -> None:
    """The runs file of `claim_id` in `remote`'s state ref replaced by `content`, as `agent`
    holding the claim, over the file the state holds now."""
    observed = store.fetch_state(worktree=directory, remote=str(remote))
    store.commit_transition(
        observed=store.Observation(directory, str(remote), observed),
        subject=store.TransitionSubject("lane-record lane"),
        intent=protocol.RunsWriteIntent(
            claim_id=claim_id,
            agent=agent,
            expected=observed.runs.get(claim_id),
            new_oid=store.hash_blob(directory, content),
            operation_id=f"op-runs-{len(content)}",
            holder_refusal="{}".format,
            stale_refusal="never reached",
        ),
    )


def two_chained_runs() -> lane_runs.RunsFile:
    """Two runs that ran `STAGES_RAN` with the record of `lane_record_object`, the second
    following the first."""
    record = lane_record.parse_record_file(json.dumps(lane_record_object()).encode())
    first = lane_runs.RunEntry(
        FIRST_RUN, None, True, lane_runs.RunAdded(END_TIP, STAGES_RAN, record)
    )
    second = lane_runs.RunEntry(
        SECOND_RUN, END_TIP, True, lane_runs.RunAdded(OTHER_TIP, STAGES_RAN, record)
    )
    return lane_runs.RunsFile((first, second))


def a_run_stored_late(
    directory: Path, remote: Path | str, claim_id: protocol.ClaimId, run: str
) -> Callable[[], None]:
    """A write that adds a copy of the stored first run as the run `run`."""

    def write() -> None:
        observed = store.fetch_state(worktree=directory, remote=str(remote))
        stored = lane_runs.parse_runs(state_runs.read_runs_file(directory, observed.runs[claim_id]))
        late = dataclasses.replace(stored.runs[0], run=run)
        content = lane_runs.serialize_runs(lane_runs.RunsFile((*stored.runs, late)))
        commit_runs_file(directory, remote, claim_id, content)

    return write


def race_before_the_push(monkeypatch: pytest.MonkeyPatch, competing: Callable[[], None]) -> None:
    """`competing` lands between the command's read of the state and its next push."""
    real_commit_transition = store.commit_transition

    def commit_after_a_competing_write(
        *,
        observed: store.Observation,
        subject: store.TransitionSubject,
        intent: protocol.ClaimTransitionIntent,
    ) -> protocol.ClaimState:
        monkeypatch.setattr(store, "commit_transition", real_commit_transition)
        competing()
        return real_commit_transition(observed=observed, subject=subject, intent=intent)

    monkeypatch.setattr(store, "commit_transition", commit_after_a_competing_write)


def commit_on(directory: Path, name: str) -> str:
    """One commit adding `name` to the checkout at `directory`; its sha."""
    (directory / name).write_text(f"{name}\n")
    real_git(directory, "add", name)
    real_git(directory, "commit", "-q", "-m", f"add {name}")
    return real_git(directory, "rev-parse", "HEAD").stdout.strip()


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
