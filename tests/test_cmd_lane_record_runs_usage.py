"""`aco lane-record begin` and `aco lane-record add` refuse an argument off their grammar and a
missing agent identity with a usage refusal that writes nothing (`specs/lane-record.spec.md`,
"Stored runs")."""

import pytest
from lane_record_runs_world import END_TIP, FIRST_RUN, World, add_arguments, begin_arguments

from aco.routing_line import RoutingStage


@pytest.fixture
def world(lane_record_runs_world: World) -> World:
    return lane_record_runs_world


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
    "end_tip",
    [
        pytest.param("abc", id="end-tip-too-short"),
        pytest.param("G" * 40, id="end-tip-not-hexadecimal"),
    ],
)
def test_an_add_tip_off_the_grammar_is_a_usage_refusal(
    world: World, capsys: pytest.CaptureFixture[str], end_tip: str
) -> None:
    """Spec: LANREC-58."""
    world.run(capsys, *begin_arguments(world))

    refused = world.run(capsys, *add_arguments(world, end_tip=end_tip))

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


@pytest.mark.parametrize(
    ("stages", "flags"),
    [
        pytest.param((RoutingStage.BUILD, RoutingStage.BUILD), (), id="a-stage-twice-in-one-ran"),
        pytest.param((RoutingStage.BUILD,), ("--ran", "build"), id="a-stage-in-two-rans"),
        pytest.param((RoutingStage.BUILD,), ("--ran", "review"), id="two-rans-naming-two-stages"),
    ],
)
def test_a_stage_named_twice_or_a_second_ran_is_a_usage_refusal_and_writes_nothing(
    world: World,
    capsys: pytest.CaptureFixture[str],
    stages: tuple[RoutingStage, ...],
    flags: tuple[str, ...],
) -> None:
    """Spec: LANREC-58."""
    world.run(capsys, *begin_arguments(world))
    tip = world.state_tip()

    refused = world.run(capsys, *add_arguments(world, stages=stages, flags=flags))

    assert refused.status == 2
    assert "usage:" in refused.stderr
    assert world.state_tip() == tip


@pytest.mark.parametrize("command", ["begin", "add"])
def test_a_missing_agent_identity_refuses_before_the_record_file_is_read_and_writes_nothing(
    world: World,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    """Spec: LANREC-70."""
    monkeypatch.delenv("ACO_AGENT")
    tip = world.state_tip()
    unreadable = world.scratch / "absent.json"
    arguments = (
        begin_arguments(world) if command == "begin" else add_arguments(world, file=unreadable)
    )

    refused = world.run(capsys, *arguments)

    assert refused.status == 2
    assert "agent identity is required" in refused.stderr
    assert world.state_tip() == tip


@pytest.mark.parametrize(
    ("operands", "stderr_part"),
    [
        pytest.param(("7", "{file}", "extra"), "usage:", id="a-third-operand"),
        pytest.param(
            ("notanumber", "{file}"), "is not an item reference", id="an-item-off-the-grammar"
        ),
    ],
)
def test_an_add_operand_off_the_grammar_is_a_refusal_and_writes_nothing(
    world: World,
    capsys: pytest.CaptureFixture[str],
    operands: tuple[str, ...],
    stderr_part: str,
) -> None:
    """Spec: LANREC-55, LANREC-58."""
    tip = world.state_tip()
    file = str(world.record_file())
    stated = tuple(operand.format(file=file) for operand in operands)
    flags = ("--run", FIRST_RUN, "--end-tip", END_TIP, "--ran", "build")

    refused = world.run(capsys, "lane-record", "add", *stated, *flags)

    assert refused.status == 2
    assert stderr_part in refused.stderr
    assert world.state_tip() == tip
