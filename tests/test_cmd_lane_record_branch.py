"""`aco lane-record begin`, `add` and `show` name a claim by `--branch` for every claim kind
(`specs/lane-record.spec.md`, "Stored runs")."""

import json
from dataclasses import replace

import pytest
from claim_worktrees import assert_json_refusal_object
from lane_record_runs_world import (
    FIRST_RUN,
    LANE_RECORD_BRANCH,
    World,
    add_arguments,
    begin_arguments,
)

from aco import usage, workboard


def command_line(
    world: World, command: str, *, item: str | None, branch: str | None, flags: tuple[str, ...] = ()
) -> tuple[str, ...]:
    """`command` naming `item` positionally and `branch` by `--branch`, each when given."""
    operands = () if item is None else (item,)
    named = () if branch is None else ("--branch", branch)
    if command == "show":
        return ("lane-record", "show", *operands, *named, *flags)
    targeted = replace(world, claim_target=operands)
    builder = begin_arguments if command == "begin" else add_arguments
    return (*builder(targeted), *named, *flags)


def test_a_lane_claim_stores_and_shows_its_runs_by_branch(
    lane_record_lane_world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-52, LANREC-55, LANREC-60, LANREC-71. Example: E-LANREC-24."""
    began = lane_record_lane_world.run(capsys, *begin_arguments(lane_record_lane_world))
    added = lane_record_lane_world.run(capsys, *add_arguments(lane_record_lane_world))
    shown = lane_record_lane_world.run(
        capsys, "lane-record", "show", "--branch", LANE_RECORD_BRANCH
    )

    label = lane_record_lane_world.label
    assert began.stdout == f"BEGAN run {FIRST_RUN} of {label}\n"
    assert added.stdout == f"ADDED run {FIRST_RUN} to {label}: 1 stored\n"
    assert shown.stdout.splitlines()[0].startswith(f"run {FIRST_RUN} of {label}: start none, end ")
    assert (began.status, added.status, shown.status) == (0, 0, 0)
    assert lane_record_lane_world.runs_files() == [
        f"runs/{lane_record_lane_world.claim().claim_id}.json"
    ]
    assert (
        lane_record_lane_world.commit_message().splitlines()[0]
        == f"lane-record lane {LANE_RECORD_BRANCH}"
    )


def reported_branches(
    world: World, capsys: pytest.CaptureFixture[str]
) -> list[tuple[object, object]]:
    """The `item` and `branch` each `--json` success of begin, add and show reports."""
    reported = [
        json.loads(world.run(capsys, *arguments, "--json").stdout)
        for arguments in (
            begin_arguments(world),
            add_arguments(world),
            ("lane-record", "show", *world.claim_target),
        )
    ]
    return [(shown["item"], shown["branch"]) for shown in reported]


def test_every_json_success_of_a_lane_claim_names_its_branch_and_no_item(
    lane_record_lane_world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-69, LANREC-84, LANREC-89."""
    assert reported_branches(lane_record_lane_world, capsys) == [(None, LANE_RECORD_BRANCH)] * 3


def test_every_json_success_of_an_issue_claim_names_its_item_and_branch(
    lane_record_runs_world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-69, LANREC-84, LANREC-89."""
    world = lane_record_runs_world
    item = workboard.parse_item_reference(world.item)

    assert reported_branches(world, capsys) == [(item, world.claim().branch)] * 3


@pytest.mark.parametrize("command", ["begin", "add", "show"])
@pytest.mark.parametrize(
    ("item", "branch", "reason", "sentence"),
    [
        pytest.param(
            "7",
            LANE_RECORD_BRANCH,
            "invalid_usage",
            usage.ITEM_OR_BRANCH_SENTENCE,
            id="an-item-and-a-branch",
        ),
        pytest.param(
            None,
            None,
            "invalid_usage",
            usage.ITEM_OR_BRANCH_SENTENCE,
            id="neither-an-item-nor-a-branch",
        ),
        pytest.param(
            None,
            "docs/other",
            "precondition_failed",
            "lane 'docs/other' has no active build claim",
            id="a-branch-without-a-lane-claim",
        ),
    ],
)
def test_a_target_off_the_grammar_refuses_with_exit_two_and_writes_nothing(
    lane_record_lane_world: World,
    capsys: pytest.CaptureFixture[str],
    command: str,
    item: str | None,
    branch: str | None,
    reason: str,
    sentence: str,
) -> None:
    """Spec: LANREC-68, LANREC-87, LANREC-89, LANREC-106. Example: E-LANREC-25."""
    tip = lane_record_lane_world.state_tip()
    arguments = command_line(lane_record_lane_world, command, item=item, branch=branch)

    refused = lane_record_lane_world.run(capsys, *arguments)
    refused_as_json = lane_record_lane_world.run(capsys, *arguments, "--json")

    assert (refused.status, refused.stdout, refused.stderr) == (2, "", f"ERROR: {sentence}\n")
    assert refused_as_json.status == 2
    assert_json_refusal_object(refused_as_json.stderr, refused_as_json.stdout, reason=reason)
    assert lane_record_lane_world.state_tip() == tip


@pytest.mark.parametrize("command", ["begin", "add", "show"])
def test_a_branch_of_an_issue_claim_refuses_like_a_branch_without_a_lane_claim(
    lane_record_runs_world: World, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    """Spec: LANREC-68, LANREC-87. Example: E-LANREC-25."""
    world = lane_record_runs_world
    branch = world.claim().branch
    arguments = command_line(world, command, item=None, branch=branch)

    refused = world.run(capsys, *arguments)

    assert (refused.status, refused.stderr) == (
        2,
        f"ERROR: lane '{branch}' has no active build claim\n",
    )
