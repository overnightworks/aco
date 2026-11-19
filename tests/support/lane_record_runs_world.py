"""The claimed item, checkout and bare remote the `aco lane-record begin` and `add` tests run
against under both storages, registered as the pytest plugin that gives those modules their
`lane_record_runs_world` fixture (`tests/conftest.py`)."""

from dataclasses import dataclass
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, complete_contract
from claim_worktrees import ISSUE, StandIn, held_by_ada, make_stand_in
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
