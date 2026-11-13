"""The record every released lane leaves on its release commit of the state ref.

The figures come from real git history in a temporary repository; releases run through the
real CLI against the real state ref, with the forge as the only fake."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from board_fixtures import REPOSITORY, standing_active_claim
from claim_worktrees import lane_held_by_ada, make_stand_in
from cli_fixtures import (
    push_repository_trunk,
    real_git,
    real_repository_with_bare_remote,
    run_cli,
    set_git_identity,
    track_board_config,
)
from github_fixtures import FakeForge
from merged_release import arrange_merged_pull_request
from store_fixtures import claim_intent

from aco import protocol, store, workboard
from aco.lane_record import (
    LaneOutcome,
    LaneRecord,
    ProductionSize,
    ReleasedLane,
    compute_record,
    parse_record,
    release_subject,
)
from aco.routing_line import parse_routing_line
from aco.session import RunContext

LANE_BRANCH = "docs/tidy-readme"
ROUTING = (
    "Routing: build sonnet-5.5/high; fix none; review opus-5.5/medium; test sonnet-5.5/medium; "
    "gate none; land haiku-5.5/low. Fix rounds: 1. Experiment: builder-sonnet. "
    "Blocking: a red check → ci"
)
ROUTING_TRAILERS = (
    "lane_build: sonnet-5.5/high",
    "lane_fix: none",
    "lane_review: opus-5.5/medium",
    "lane_test: sonnet-5.5/medium",
    "lane_gate: none",
    "lane_land: haiku-5.5/low",
    "lane_fix_rounds: 1",
    "lane_blocking: 1",
    "lane_experiment: builder-sonnet",
)
MERGE_SHA = "a" * 40
CLAIMED_AT = 1_700_000_000
IDLE_SECONDS = 3600
MERGED_AT = CLAIMED_AT + 600
RELEASED_AT = CLAIMED_AT + 90


def lane_trailers(message: str) -> tuple[str, ...]:
    return tuple(line for line in message.splitlines() if line.startswith("lane_"))


def release_commit_message(remote: Path) -> str:
    return real_git(remote, "log", "-1", "--format=%B", store.STATE_REF).stdout


def test_a_record_renders_its_known_figures_in_order_and_leaves_unknown_ones_out() -> None:
    """Spec: LANREC-04, LANREC-06, LANREC-07, LANREC-08, LANREC-09, LANREC-11, LANREC-12."""
    routing = parse_routing_line(ROUTING)
    record = LaneRecord(
        outcome=LaneOutcome.LANDED,
        merge_commit=MERGE_SHA,
        wall_seconds=0,
        size=ProductionSize(files=2, added=0, deleted=7),
        routing=routing,
    )

    assert record.trailers() == (
        "lane_outcome: landed",
        f"lane_merge: {MERGE_SHA}",
        "lane_wall_seconds: 0",
        "lane_files: 2",
        "lane_added: 0",
        "lane_deleted: 7",
        *ROUTING_TRAILERS,
    )


def test_a_record_with_nothing_measured_is_only_its_outcome() -> None:
    """Spec: LANREC-04, LANREC-06."""
    assert LaneRecord(outcome=LaneOutcome.ABANDONED).trailers() == ("lane_outcome: abandoned",)


def test_a_record_read_back_from_its_message_renders_the_same_trailers() -> None:
    """Spec: STATS-01, STATS-08."""
    record = LaneRecord(
        outcome=LaneOutcome.LANDED,
        merge_commit=MERGE_SHA,
        wall_seconds=0,
        size=ProductionSize(files=2, added=0, deleted=7),
        routing=parse_routing_line(ROUTING),
    )
    message = "\n".join(["release lane", "", *record.trailers()])

    read_back = parse_record(message)

    assert read_back is not None
    assert read_back.trailers() == record.trailers()


@pytest.mark.parametrize(
    ("lines", "expected_trailers"),
    [
        pytest.param(
            ("lane_wall_seconds: 5", "lane_wall_seconds: 6"),
            ("lane_outcome: landed",),
            id="a-repeated-line",
        ),
        pytest.param(
            ("lane_wall_seconds: five", "lane_fix_rounds: -1"),
            ("lane_outcome: landed",),
            id="a-value-that-is-no-whole-number",
        ),
        pytest.param(
            ("lane_files: 1", "lane_added: 2"),
            ("lane_outcome: landed",),
            id="a-size-missing-a-line",
        ),
        pytest.param(
            ("lane_build: Sonnet/High", "lane_fix: none", "lane_build: x/y"),
            ("lane_outcome: landed", "lane_fix: none"),
            id="a-stage-that-does-not-fit-or-repeats",
        ),
        pytest.param(
            ("lane_review: opus-5.5/medium", "lane_wall_seconds: 7"),
            ("lane_outcome: landed", "lane_wall_seconds: 7", "lane_review: opus-5.5/medium"),
            id="the-lines-that-stand",
        ),
    ],
)
def test_a_figure_whose_line_is_repeated_or_malformed_is_unknown(
    lines: tuple[str, ...], expected_trailers: tuple[str, ...]
) -> None:
    """Spec: STATS-08."""
    message = "\n".join(["release lane", "", "lane_outcome: landed", *lines])

    record = parse_record(message)

    assert record is not None
    assert record.trailers() == expected_trailers


@pytest.mark.parametrize(
    "message",
    [
        pytest.param("release lane", id="no-record"),
        pytest.param("lane_outcome: paused", id="an-outcome-that-is-none-of-the-two"),
        pytest.param("lane_outcome: landed\nlane_outcome: abandoned", id="a-repeated-outcome"),
    ],
)
def test_a_message_without_exactly_one_valid_outcome_records_no_lane(message: str) -> None:
    """Spec: STATS-12."""
    assert parse_record(message) is None


class LaneHistory:
    """A repository whose `main` holds the commit before a claim, the claim commit and then a
    landing commit, each dated; the claim was opened on the first of them."""

    def __init__(self, path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.path = path
        self.monkeypatch = monkeypatch
        (path / "src").mkdir()
        (path / "src" / "gen").mkdir()
        (path / "tests").mkdir()
        (path / "src" / "a.py").write_text("one\ntwo\n")
        (path / "src" / "gen" / "x.py").write_text("x\n")
        self.opened_commit = self.commit("before the claim", CLAIMED_AT - IDLE_SECONDS)
        self.claim_commit = self.commit("claim", CLAIMED_AT)

    @property
    def tip(self) -> str:
        return real_git(self.path, "rev-parse", "HEAD").stdout.strip()

    def commit(self, message: str, moment: int) -> str:
        self.monkeypatch.setenv("GIT_COMMITTER_DATE", f"@{moment} +0000")
        real_git(self.path, "add", "-A")
        real_git(self.path, "commit", "-q", "--allow-empty", "-m", message)
        return real_git(self.path, "rev-parse", "HEAD").stdout.strip()

    def land(self, message: str, moment: int = MERGED_AT) -> str:
        """A landing that changes two production files, one dependency file, one test file
        and one binary file."""
        (self.path / "src" / "a.py").write_text("one\nTWO\nthree\nfour\n")
        (self.path / "src" / "gen" / "x.py").write_text("x\n1\n2\n3\n4\n5\n")
        (self.path / "tests" / "t.py").write_text("t\nt\n")
        (self.path / "src" / "img.bin").write_bytes(b"\x00\x01\x02")
        return self.commit(message, moment)


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    set_git_identity(monkeypatch)


@pytest.fixture
def history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LaneHistory:
    repository, _remote = real_repository_with_bare_remote(tmp_path)
    return LaneHistory(repository, monkeypatch)


CONFIG = workboard.BoardConfig(production_paths=("src/",), dependency_paths=("src/gen/",))
LANDED_TRAILERS = (
    "lane_outcome: landed",
    "lane_wall_seconds: 600",
    "lane_files: 2",
    "lane_added: 3",
    "lane_deleted: 1",
)


def compute_for(
    history: LaneHistory,
    outcome: protocol.ReleaseOutcome,
    *,
    merge_commit: str | None,
    config: workboard.BoardConfig = CONFIG,
    opened_commit: str | None = None,
    state_tip_known: bool = True,
) -> tuple[str, ...]:
    claim = standing_active_claim(
        lane=True, opened_commit=opened_commit or history.opened_commit, base=history.claim_commit
    )
    state_tip = history.tip if state_tip_known else None
    released = ReleasedLane(claim, outcome, merge_commit, RELEASED_AT, state_tip)
    return compute_record(history.path, config, released).trailers()


def landed_outcome(merge_commit: str) -> protocol.LandedRelease:
    return protocol.LandedRelease(commit=protocol.ObjectId(merge_commit))


def test_a_landed_lane_counts_production_files_and_lines_minus_dependency_paths(
    history: LaneHistory,
) -> None:
    """Spec: LANREC-07, LANREC-08, LANREC-09, LANREC-10, LANREC-13."""
    merge = history.land(f"Landing\n\n{ROUTING}\n\nNo-Item: docs")

    assert compute_for(history, landed_outcome(merge), merge_commit=merge) == (
        LANDED_TRAILERS[0],
        f"lane_merge: {merge}",
        *LANDED_TRAILERS[1:],
        *ROUTING_TRAILERS,
    )


@pytest.mark.parametrize(
    ("renamed_content", "line_trailers"),
    [
        pytest.param("one\ntwo\n", ["lane_added: 0", "lane_deleted: 0"], id="unchanged"),
        pytest.param("one\ntwo\nthree\n", ["lane_added: 1", "lane_deleted: 0"], id="one-line-more"),
    ],
)
def test_a_renamed_production_file_is_one_file_with_only_its_changed_lines(
    history: LaneHistory, renamed_content: str, line_trailers: list[str]
) -> None:
    """Spec: LANREC-09, LANREC-10."""
    real_git(history.path, "config", "diff.renames", "false")
    real_git(history.path, "mv", "src/a.py", "src/b.py")
    (history.path / "src" / "b.py").write_text(renamed_content)
    merge = history.commit("Renaming", MERGED_AT)

    figures = compute_for(history, landed_outcome(merge), merge_commit=merge)

    assert [line for line in figures if line.startswith("lane_files")] == ["lane_files: 1"]
    assert [line for line in figures if line.startswith(("lane_added", "lane_deleted"))] == (
        line_trailers
    )


@pytest.mark.parametrize(
    ("config", "size_trailers"),
    [
        pytest.param(
            workboard.parse_config("production_paths = []", Path("board.toml")),
            [],
            id="an-empty-list",
        ),
        pytest.param(workboard.BoardConfig(), [], id="no-production-paths"),
        pytest.param(
            workboard.BoardConfig(production_paths=("src/",), dependency_paths=("src/",)),
            ["lane_files: 0", "lane_added: 0", "lane_deleted: 0"],
            id="every-production-path-is-a-dependency-path",
        ),
    ],
)
def test_size_is_unknown_without_production_paths_and_zero_when_measured_empty(
    history: LaneHistory, config: workboard.BoardConfig, size_trailers: list[str]
) -> None:
    """Spec: LANREC-04, LANREC-10, LANREC-25."""
    merge = history.land("Landing")

    figures = compute_for(history, landed_outcome(merge), merge_commit=merge, config=config)

    assert [
        line for line in figures if line.startswith(("lane_files", "lane_added", "lane_deleted"))
    ] == size_trailers


def test_a_landing_without_a_routing_line_still_records_outcome_wall_time_and_size(
    history: LaneHistory,
) -> None:
    """Spec: LANREC-14."""
    merge = history.land("Landing\n\nNo-Item: docs")

    assert compute_for(history, landed_outcome(merge), merge_commit=merge) == (
        LANDED_TRAILERS[0],
        f"lane_merge: {merge}",
        *LANDED_TRAILERS[1:],
    )


@pytest.mark.parametrize(
    "merge_commit",
    [
        pytest.param(None, id="the-forge-named-no-merge-commit"),
        pytest.param("not-a-sha", id="a-merge-commit-that-is-no-sha"),
        pytest.param(MERGE_SHA, id="a-merge-commit-the-checkout-does-not-hold"),
    ],
)
def test_a_merge_commit_that_cannot_be_read_leaves_only_what_is_known(
    history: LaneHistory, merge_commit: str | None
) -> None:
    """Spec: LANREC-07, LANREC-21."""
    outcome = protocol.MergedRelease(12)

    figures = compute_for(history, outcome, merge_commit=merge_commit)

    expected_merge = [f"lane_merge: {merge_commit}"] if merge_commit == MERGE_SHA else []
    assert figures == ("lane_outcome: landed", *expected_merge)


def test_a_merge_older_than_its_claim_has_no_wall_time(history: LaneHistory) -> None:
    """Spec: LANREC-08."""
    merge = history.land("Landing", CLAIMED_AT - 5)

    figures = compute_for(history, landed_outcome(merge), merge_commit=merge)

    assert [line for line in figures if line.startswith("lane_wall")] == []


def test_a_claim_commit_the_checkout_does_not_hold_has_no_wall_time(history: LaneHistory) -> None:
    """Spec: LANREC-08, LANREC-21."""
    merge = history.land("Landing")

    figures = compute_for(
        history, landed_outcome(merge), merge_commit=merge, opened_commit=MERGE_SHA
    )

    assert [line for line in figures if line.startswith("lane_wall")] == []


def test_a_release_read_from_no_state_tip_has_no_wall_time(history: LaneHistory) -> None:
    """Spec: LANREC-08, LANREC-21."""
    merge = history.land("Landing")

    figures = compute_for(history, landed_outcome(merge), merge_commit=merge, state_tip_known=False)

    assert [line for line in figures if line.startswith("lane_wall")] == []


def test_an_abandoned_lane_counts_to_the_release_and_reads_its_routing_from_the_reason(
    history: LaneHistory,
) -> None:
    """Spec: LANREC-08, LANREC-10, LANREC-15."""
    outcome = protocol.AbandonedRelease(ROUTING)

    figures = compute_for(history, outcome, merge_commit=None)

    assert figures == ("lane_outcome: abandoned", "lane_wall_seconds: 90", *ROUTING_TRAILERS)


def release_trailers(
    history: LaneHistory, outcome: protocol.ReleaseOutcome, verified_merge: str | None = None
) -> tuple[str, ...]:
    """The trailers `release_subject` puts on the release of a lane claimed in `history`; its
    context holds no forge, so a read of one fails the test."""
    observation = SimpleNamespace(tip=history.tip)
    context = SimpleNamespace(toplevel=history.path, config=CONFIG, observation=observation)
    claim = standing_active_claim(lane=True, opened_commit=history.opened_commit)

    return release_subject(cast(RunContext, context), claim, outcome, verified_merge).trailers


def test_a_trunk_landing_names_its_commit_as_the_merge_without_asking_a_forge(
    history: LaneHistory,
) -> None:
    """Spec: LANREC-07."""
    merge = history.land("Landing")

    trailers = release_trailers(history, landed_outcome(merge))

    assert trailers[:2] == ("lane_outcome: landed", f"lane_merge: {merge}")


def test_a_merged_pull_request_names_the_merge_commit_its_release_verified(
    history: LaneHistory,
) -> None:
    """Spec: LANREC-07, LANREC-21."""
    merge = history.land("Landing")

    trailers = release_trailers(history, protocol.MergedRelease(12), merge)

    assert trailers[:2] == ("lane_outcome: landed", f"lane_merge: {merge}")


@pytest.mark.parametrize(
    ("entries", "reason"),
    [
        pytest.param("production_paths = 'src/'", "must be a list of unique", id="not-a-list"),
        pytest.param(
            "production_paths = ['src/', 'src/']", "must be a list of unique", id="repeated"
        ),
        pytest.param(
            "production_paths = ['/src/']",
            "entry '/src/' is not a canonical path inside the repository",
            id="absolute",
        ),
        pytest.param(
            "production_paths = ['../src/']",
            "entry '../src/' is not a canonical path inside the repository",
            id="climbing",
        ),
    ],
)
def test_a_malformed_production_paths_refuses_when_the_configuration_is_read(
    entries: str, reason: str
) -> None:
    """Spec: PIN-55, PIN-56, LANREC-22."""
    path = Path(".aco/board.toml")

    with pytest.raises(protocol.ClaimError) as refusal:
        workboard.parse_config(entries, path)

    assert str(refusal.value).startswith(f"board configuration {path} production_paths ")
    assert reason in str(refusal.value)


def test_production_paths_parse_like_dependency_paths() -> None:
    """Spec: PIN-54."""
    parsed = workboard.parse_config("production_paths = ['src/', 'pyproject.toml']", Path("x"))

    assert parsed.production_paths == ("src/", "pyproject.toml")


@pytest.fixture
def pinned_clone(github_clone: Path, bare_remote: Path) -> Path:
    track_board_config(
        github_clone, 'production_paths = ["feature.txt"]\ndependency_paths = ["other/"]\n'
    )
    push_repository_trunk(github_clone, "origin")
    return github_clone


def land_and_release(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clone: Path,
    remote: Path,
    *,
    message_lines: tuple[str, ...],
) -> tuple[str, FakeForge]:
    """Release pull request #12, landed with `message_lines` on its merge commit, as its
    lane; the release commit's message comes back with the forge that served the pull request."""
    monkeypatch.setenv("GIT_COMMITTER_DATE", f"@{CLAIMED_AT} +0000")
    merged = arrange_merged_pull_request(
        monkeypatch,
        clone,
        remote,
        identity=protocol.LaneIdentity(),
        trailers=message_lines,
        pull_request_body="No-Item: docs",
        branch=LANE_BRANCH,
    )
    real_git(clone, "checkout", "-q", LANE_BRANCH)

    result = run_cli(["--repo", REPOSITORY, "release", "--merged", "12"], capsys)

    assert (result.status, result.stderr) == (0, "")
    return release_commit_message(remote), merged.forge


def test_a_merged_release_leaves_its_record_on_the_release_commit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    pinned_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: LANREC-01, LANREC-06, LANREC-07, LANREC-08, LANREC-09, LANREC-11, LANREC-12,
    LANREC-13, REL-64."""
    message, _forge = land_and_release(
        monkeypatch,
        capsys,
        pinned_clone,
        bare_remote,
        message_lines=(ROUTING, "No-Item: docs"),
    )

    merge = real_git(bare_remote, "rev-parse", "main").stdout.strip()
    assert lane_trailers(message) == (
        "lane_outcome: landed",
        f"lane_merge: {merge}",
        "lane_wall_seconds: 0",
        "lane_files: 1",
        "lane_added: 1",
        "lane_deleted: 0",
        *ROUTING_TRAILERS,
    )
    assert message.index("intent: release") < message.index("lane_outcome")


def test_a_merged_release_reads_the_pull_request_from_the_forge_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    pinned_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: LANREC-21."""
    _message, forge = land_and_release(
        monkeypatch, capsys, pinned_clone, bare_remote, message_lines=("No-Item: docs",)
    )

    assert forge.landing_reads == [12]


def test_a_merged_release_whose_merge_lost_the_routing_line_still_releases_with_the_rest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    pinned_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: LANREC-14, LANREC-21, REL-64."""
    message, _forge = land_and_release(
        monkeypatch, capsys, pinned_clone, bare_remote, message_lines=("No-Item: docs",)
    )

    merge = real_git(bare_remote, "rev-parse", "main").stdout.strip()
    assert lane_trailers(message) == (
        "lane_outcome: landed",
        f"lane_merge: {merge}",
        "lane_wall_seconds: 0",
        "lane_files: 1",
        "lane_added: 1",
        "lane_deleted: 0",
    )


def test_an_abandoned_release_leaves_a_record_from_its_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    github_clone: Path,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: LANREC-01, LANREC-08, LANREC-15, REL-64."""
    stand_in = make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, ("src/widget.py",))
    stand_in(branch=LANE_BRANCH, standing=lane_held_by_ada(LANE_BRANCH, ("src/widget.py",)))
    monkeypatch.setenv("GIT_COMMITTER_DATE", f"@{CLAIMED_AT} +0000")

    result = run_cli(
        ["--repo", REPOSITORY, "release", "--agent", "Ada", "--abandoned", ROUTING], capsys
    )

    release_date, claim_date = (
        int(moment)
        for moment in real_git(
            bare_remote, "log", "-2", "--first-parent", "--format=%ct", store.STATE_REF
        ).stdout.split()
    )
    lines = lane_trailers(release_commit_message(bare_remote))
    assert (result.status, result.stderr) == (0, "")
    assert lines[:2] == (
        "lane_outcome: abandoned",
        f"lane_wall_seconds: {release_date - claim_date}",
    )
    assert lines[2:] == ROUTING_TRAILERS


def test_a_record_survives_a_push_that_loses_its_race(bare_remote: Path, worktree: Path) -> None:
    """Spec: LANREC-03."""
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    claim = claim_intent(identity=protocol.LaneIdentity(), branch=LANE_BRANCH)
    observed = store.Observation(
        worktree, str(bare_remote), store.fetch_state(worktree=worktree, remote=str(bare_remote))
    )
    claimed = store.commit_transition(
        observed=observed, subject=store.TransitionSubject("claim lane"), intent=claim
    )
    release = protocol.ReleaseIntent(
        claim_id=claim.claim_id,
        agent="Ada",
        role="builder",
        outcome=protocol.AbandonedRelease("stopped"),
        operation_id="op-release",
    )
    subject = store.TransitionSubject("release lane", trailers=("lane_outcome: abandoned",))
    transport = RejectsOnce()

    store.commit_transition(
        observed=store.Observation(worktree, str(bare_remote), claimed),
        subject=subject,
        intent=release,
        transport=transport,
    )

    assert lane_trailers(release_commit_message(bare_remote)) == ("lane_outcome: abandoned",)


class RejectsOnce:
    """A push transport that loses its first push to a rival and pushes for real after."""

    def __init__(self) -> None:
        self._rejected = False
        self._real = store.GitPushTransport()

    def push(self, *, worktree: Path, remote: str, ref: str, new_oid: protocol.ObjectId) -> None:
        if not self._rejected:
            self._rejected = True
            raise protocol.PushRejectedError("simulated rejection")
        self._real.push(worktree=worktree, remote=remote, ref=ref, new_oid=new_oid)
