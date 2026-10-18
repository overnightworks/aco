"""Land entry and readiness through a real GitHub checkout, before any claim exists."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from cli_fixtures import CliRun, real_git, run_cli, track_board_config, worktrees_and_branches
from github_fixtures import (
    MERGE_COMMIT_SHA,
    FakeForge,
    LandingWorld,
    assert_github_world,
    landing_effects,
    landing_pull_request,
    landing_readiness,
    refusal_observations,
    serve_forge,
)

from agent_coordination import cli, forge


@dataclass(frozen=True)
class LandingCase:
    readiness: forge.LandingReadiness
    sentence: str
    arguments: tuple[str, ...] = ()
    state_ref: bool = False
    merged: bool = False
    body: str = "Work-Item: #72\n\nCloses #72"
    quality_config: str | None = None
    head_config: str | None = None
    default_branch: str = "main"
    default_branch_error: forge.ForgeError | None = None
    quality_config_error: forge.ForgeError | None = None
    bounded: bool = False
    exact_length: bool = False
    requests: int | None = None
    requests_positive: bool = False
    quality_reads: tuple[str, ...] | None = None
    parser_exit: bool = False
    usage_prefix: str = "usage: aco land "


@dataclass
class LandingScenario(LandingWorld):
    case: LandingCase


@pytest.fixture
def world(
    request: pytest.FixtureRequest,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> LandingScenario:
    case: LandingCase = request.param
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("GIT_DISCOVERY_ACROSS_FILESYSTEM", "1")
    assert_github_world(github_clone, bare_remote)
    if case.state_ref:
        track_board_config(github_clone, 'storage = "state-ref"\n')
    client = serve_forge(
        monkeypatch,
        FakeForge(
            landings={12: landing_pull_request(body=case.body, merged=case.merged)},
            readiness_by_number={12: case.readiness},
            quality_config=case.quality_config,
            quality_config_at_other_refs=case.head_config,
            default_branch_name=case.default_branch,
            default_branch_error=case.default_branch_error,
            quality_config_error=case.quality_config_error,
        ),
    )
    worktrees, branches = worktrees_and_branches(github_clone)
    unchanged = {
        "merge": [],
        "delete": [],
        "close": set(),
        "body": [],
        "remote": None,
        "local": None,
        "worktrees": worktrees,
        "branches": branches,
        "trunk": real_git(github_clone, "rev-parse", "main").stdout,
        "stamp": None,
        "anchor": None,
    }
    result = LandingScenario(github_clone, bare_remote, client, unchanged, case)
    observed = landing_effects(result)
    assert observed == unchanged
    return result


def land(world: LandingScenario, capsys: pytest.CaptureFixture[str]) -> CliRun:
    return run_cli(["land", "12", *world.case.arguments], capsys)


class TestLandReadiness:
    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                LandingCase(
                    replace(landing_readiness(checks=()), open=False),
                    "pull request #12 is not open; it cannot be landed",
                    bounded=True,
                ),
                id="not-open",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(mergeable_state="dirty", checks=()),
                    "pull request #12 is not mergeable (dirty)",
                    bounded=True,
                ),
                id="not-mergeable-dirty",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(checks=()),
                    "pull request #12 exposes no CI checks; cannot verify green CI",
                    bounded=True,
                ),
                id="no-checks",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(checks=(forge.CheckRun("build", None),)),
                    "pull request #12 has checks still running: build; wait for every check to "
                    "succeed",
                    bounded=True,
                ),
                id="check-running",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(checks=(forge.CheckRun("build", "failure"),)),
                    "pull request #12 has non-successful checks: build (failure); land only "
                    "after every check succeeds",
                    bounded=True,
                ),
                id="check-failed",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(
                        checks=tuple(forge.CheckRun(f"check-{index}", None) for index in range(5))
                    ),
                    "pull request #12 has checks still running: check-0, check-1, check-2, and "
                    "2 more; wait for every check to succeed",
                    bounded=True,
                ),
                id="running-list-capped",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(checks=(forge.CheckRun("x" * 300, None),)),
                    "pull request #12 has checks still running: "
                    + "x" * 39
                    + "…; wait for every check to succeed",
                    bounded=True,
                ),
                id="running-name-truncated",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(
                        checks=tuple(forge.CheckRun("x" * 300, None) for _ in range(5))
                    ),
                    "pull request #12 has checks still running: "
                    + ", ".join(["x" * 39 + "…"] * 3)
                    + ", and 2 more; wait for ev…",
                    bounded=True,
                    exact_length=True,
                ),
                id="running-many-long-names-bounded",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(mergeable_state="behind"),
                    "pull request #12 is not mergeable (behind)",
                ),
                id="not-mergeable-behind",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(checks=(forge.CheckRun("build\n\x1b[31m", None),)),
                    "pull request #12 has checks still running: build\\n\\x1b[31m; wait for "
                    "every check to succeed",
                ),
                id="running-name-display-controls",
            ),
            pytest.param(
                LandingCase(
                    replace(landing_readiness(mergeable_state="dirty"), open=False),
                    "pull request #12 is not open; it cannot be landed",
                ),
                id="not-open-and-dirty",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(mergeable_state="dirty", checks=()),
                    "pull request #12 is not mergeable (dirty)",
                ),
                id="dirty-and-no-checks",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(
                        checks=(forge.CheckRun("build", None), forge.CheckRun("lint", "failure"))
                    ),
                    "pull request #12 has checks still running: build; wait for every check to "
                    "succeed",
                ),
                id="running-and-failed",
            ),
        ],
        indirect=True,
    )
    def test_refusal(self, world: LandingScenario, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-02, LANDCMD-03, LANDCMD-04, LANDCMD-05, LANDCMD-06.
        Exact refusal and no writes.
        """
        capsys.readouterr()
        observed, expected = refusal_observations(
            world,
            land(world, capsys),
            world.case.sentence,
            bounded=world.case.bounded,
            exact_length=world.case.exact_length,
        )
        assert observed == expected


class TestLandQualityGate:
    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                LandingCase(
                    landing_readiness(),
                    "pull request #12 has no quality / verdict check; main adopts the quality "
                    "gate (quality/config.toml)",
                    quality_config="",
                    quality_reads=("main",),
                    body="Advances #72",
                ),
                id="adopted-without-verdict",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(checks=()),
                    "pull request #12 has no quality / verdict check; main adopts the quality "
                    "gate (quality/config.toml)",
                    quality_config="",
                    quality_reads=("main",),
                    body="Advances #72",
                ),
                id="adopted-without-any-check",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(
                        checks=(forge.CheckRun("quality / verdict (push)", "success"),)
                    ),
                    "pull request #12 has no quality / verdict check; main adopts the quality "
                    "gate (quality/config.toml)",
                    quality_config="",
                    quality_reads=("main",),
                    body="Advances #72",
                ),
                id="adopted-with-a-differently-named-verdict",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(mergeable_state="blocked", checks=()),
                    "pull request #12 has no quality / verdict check; main adopts the quality "
                    "gate (quality/config.toml)",
                    quality_config="",
                    quality_reads=("main",),
                    body="Advances #72",
                ),
                id="adopted-blocked-without-verdict",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(
                        mergeable_state="blocked",
                        checks=(forge.CheckRun("quality / verdict", "success"),),
                    ),
                    "pull request #12 is not mergeable (blocked)",
                    quality_config="",
                    quality_reads=("main",),
                    body="Advances #72",
                ),
                id="adopted-blocked-with-verdict",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(mergeable_state="blocked", checks=()),
                    "pull request #12 is not mergeable (blocked)",
                    quality_config=None,
                    quality_reads=("main",),
                    body="Advances #72",
                ),
                id="unadopted-blocked-without-verdict",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(checks=(forge.CheckRun("build", None),)),
                    "pull request #12 has checks still running: build; wait for every check to "
                    "succeed",
                    quality_config="",
                    quality_reads=("main",),
                    body="Advances #72",
                ),
                id="running-defers",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(checks=(forge.CheckRun("quality / verdict", "failure"),)),
                    "pull request #12 has non-successful checks: quality / verdict (failure); "
                    "land only after every check succeeds",
                    quality_config="",
                    quality_reads=("main",),
                    body="Advances #72",
                ),
                id="red-verdict",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(checks=(forge.CheckRun("quality / verdict", "success"),)),
                    "pull request #12 carries no `Work-Item:` or `No-Item:` line",
                    quality_config="",
                    quality_reads=("main",),
                    body="Advances #72",
                ),
                id="verdict-passes-to-classification",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(),
                    "pull request #12 has no quality / verdict check; " + "b" * 143 + "…",
                    quality_config="",
                    default_branch="b" * 255,
                    bounded=True,
                    exact_length=True,
                    quality_reads=("b" * 255,),
                ),
                id="long-default-branch-name",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(mergeable_state="blocked", checks=()),
                    "pull request #12 has no quality / verdict check; main adopts the quality "
                    "gate (quality/config.toml)",
                    quality_config="",
                    head_config=None,
                    quality_reads=("main",),
                ),
                id="head-deleting-the-config",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(mergeable_state="blocked", checks=()),
                    "pull request #12 is not mergeable (blocked)",
                    quality_config=None,
                    head_config="",
                    quality_reads=("main",),
                ),
                id="adoption-pull-request-adding-the-config",
            ),
            pytest.param(
                LandingCase(
                    replace(landing_readiness(checks=()), open=False),
                    "pull request #12 is not open; it cannot be landed",
                    quality_config="",
                    quality_reads=(),
                ),
                id="closed-reads-nothing",
            ),
            pytest.param(
                LandingCase(
                    replace(landing_readiness(checks=()), open=False),
                    "pull request #12 is not open; it cannot be landed",
                    default_branch_error=forge.ForgeError("GitHub returned HTTP 500"),
                    quality_reads=(),
                ),
                id="closed-default-branch-unreadable",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(),
                    "GitHub returned HTTP 500",
                    quality_config_error=forge.ForgeError("GitHub returned HTTP 500"),
                    quality_reads=("main",),
                ),
                id="config-unreadable",
            ),
        ],
        indirect=True,
    )
    def test_refusal(self, world: LandingScenario, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-02, LANDCMD-43 -- exact refusal and no writes."""
        capsys.readouterr()
        observed, expected = refusal_observations(
            world,
            land(world, capsys),
            world.case.sentence,
            bounded=world.case.bounded,
            exact_length=world.case.exact_length,
        )
        observed["quality reads"] = tuple(world.forge.quality_config_reads)
        expected["quality reads"] = world.case.quality_reads
        assert observed == expected


class TestLandEntry:
    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                LandingCase(
                    landing_readiness(),
                    "aco land is a github command; storage = state-ref has no pull requests to "
                    "land",
                    state_ref=True,
                    requests=0,
                ),
                id="state-ref",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(),
                    "a coordinator override requires --role coordinator",
                    arguments=("--coordinator-override",),
                    requests=0,
                ),
                id="override-omitted-role",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(),
                    "a coordinator override requires --role coordinator",
                    arguments=("--coordinator-override", "--role", "builder"),
                    requests=0,
                ),
                id="override-wrong-role",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(),
                    "a coordinator override requires --role coordinator",
                    arguments=("--coordinator-override",),
                    merged=True,
                    requests=0,
                ),
                id="rerun-override-omitted-role",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(),
                    "a coordinator override requires --role coordinator",
                    arguments=("--coordinator-override", "--role", "builder"),
                    merged=True,
                    requests=0,
                ),
                id="rerun-override-wrong-role",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(),
                    "pull request #12 head is "
                    + MERGE_COMMIT_SHA
                    + ", not the reviewed 0000000; review the new head before landing",
                    arguments=("--head", "0000000"),
                    requests_positive=True,
                ),
                id="moved-head",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(),
                    "pull request #12 head is "
                    + MERGE_COMMIT_SHA
                    + ", not the reviewed d4e5f6a; review the new head before landing",
                    arguments=("--head", "d4e5f6a"),
                ),
                id="reviewed-inside-but-not-a-prefix",
            ),
            pytest.param(
                LandingCase(
                    replace(landing_readiness(checks=()), open=False),
                    "pull request #12 head is "
                    + MERGE_COMMIT_SHA
                    + ", not the reviewed 0000000; review the new head before landing",
                    arguments=("--head", "0000000"),
                ),
                id="moved-head-and-not-open",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(),
                    "aco land is a github command; storage = state-ref has no pull requests to "
                    "land",
                    state_ref=True,
                    arguments=("--coordinator-override",),
                    requests=0,
                ),
                id="state-ref-and-override",
            ),
            pytest.param(
                LandingCase(
                    landing_readiness(),
                    "a coordinator override requires --role coordinator",
                    arguments=("--coordinator-override", "--head", "0000000"),
                    requests=0,
                ),
                id="override-and-moved-head",
            ),
        ],
        indirect=True,
    )
    def test_refusal(self, world: LandingScenario, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-01, LANDCMD-19, LANDCMD-31 -- exact refusal and no writes."""
        capsys.readouterr()
        observed, expected = refusal_observations(
            world,
            land(world, capsys),
            world.case.sentence,
            bounded=world.case.bounded,
            exact_length=world.case.exact_length,
        )
        if world.case.requests is not None:
            observed["requests"] = world.forge.requests
            expected["requests"] = world.case.requests
        if world.case.requests_positive:
            observed["requests-positive"] = world.forge.requests > 0
            expected["requests-positive"] = True
        assert observed == expected


@pytest.mark.parametrize(
    "world",
    [
        pytest.param(
            LandingCase(
                landing_readiness(),
                "--head must be 7 to 40 hex digits",
                arguments=("--head", "main"),
            ),
            id="head-not-hex",
        ),
        pytest.param(
            LandingCase(
                landing_readiness(),
                "--head must be 7 to 40 hex digits",
                arguments=("--head", "a1b2c3"),
            ),
            id="head-shorter-than-7",
        ),
        pytest.param(
            LandingCase(
                landing_readiness(),
                "--head must be 7 to 40 hex digits",
                arguments=("--head", MERGE_COMMIT_SHA + "0"),
            ),
            id="head-longer-than-40",
        ),
        pytest.param(
            LandingCase(
                landing_readiness(),
                "--head must be 7 to 40 hex digits",
                arguments=("--head", "main"),
                state_ref=True,
            ),
            id="head-state-ref-pin",
        ),
        pytest.param(
            LandingCase(
                landing_readiness(),
                "--head must be 7 to 40 hex digits",
                arguments=("--head", "main"),
                merged=True,
            ),
            id="head-on-a-rerun",
        ),
        pytest.param(
            LandingCase(
                landing_readiness(),
                "aco land: error: argument pull_request: 0 is not a positive number",
                arguments=("0",),
                merged=True,
                parser_exit=True,
            ),
            id="number-zero",
        ),
        pytest.param(
            LandingCase(
                landing_readiness(),
                "aco land: error: argument pull_request: -1 is not a positive number",
                arguments=("-1",),
                merged=True,
                parser_exit=True,
            ),
            id="number-negative",
        ),
        pytest.param(
            LandingCase(
                landing_readiness(),
                "aco land: error: argument pull_request: invalid int value: 'abc'",
                arguments=("abc",),
                merged=True,
                parser_exit=True,
            ),
            id="number-text",
        ),
        pytest.param(
            LandingCase(
                landing_readiness(),
                "aco land: error: argument pull_request: invalid int value: '1.5'",
                arguments=("1.5",),
                merged=True,
                parser_exit=True,
            ),
            id="number-fraction",
        ),
        pytest.param(
            LandingCase(
                landing_readiness(),
                "aco: error: unrecognized arguments: --json",
                arguments=("12", "--json"),
                parser_exit=True,
                usage_prefix="usage: aco ",
            ),
            id="no-json-flag",
        ),
    ],
    indirect=True,
)
def test_parser_refusal(
    world: LandingScenario, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANDCMD-33, LANDCMD-44 -- parser refusal, no command entry or forge request."""

    def forbidden(*_args: object, **_kwargs: object) -> int:
        pytest.fail("land command dispatched despite parser refusal")

    monkeypatch.setitem(cli._COMMANDS, "land", replace(cli._COMMANDS["land"], run=forbidden))
    arguments = (
        ["land", *world.case.arguments]
        if world.case.parser_exit
        else ["land", "12", *world.case.arguments]
    )
    capsys.readouterr()
    exited = False
    try:
        status = cli.main(arguments)
    except SystemExit as error:
        status = error.code
        exited = True
    captured = capsys.readouterr()
    observed, expected = refusal_observations(
        world,
        CliRun(status, captured.out, captured.err),
        world.case.sentence,
        parser_exit=world.case.parser_exit,
        exited=exited,
        usage_prefix=world.case.usage_prefix,
    )
    observed["requests"] = world.forge.requests
    expected["requests"] = 0
    assert observed == expected
