"""`aco board --json` projects a container's sub-issues from other repositories."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from aco_board_fixtures import board_checkout
from board_fixtures import (
    board_issue,
    complete_contract,
    container_with_children,
    projected_board,
)
from cli_fixtures import run_cli
from discovery_fixtures import BoardUnit

from aco import cmd_board, workboard
from aco.workboard import BoardConfig

CONTAINER = 120
LOCAL_CHILD = 121
FOREIGN_CHILD = workboard.IssueReference("overnightworks/other-repo", 954)


@pytest.mark.parametrize(
    ("foreign_state", "expected_closed", "expected_foreign_children"),
    [
        pytest.param(workboard.ChildState.OPEN, 1, [str(FOREIGN_CHILD)], id="open"),
        pytest.param(workboard.ChildState.CLOSED, 2, [], id="closed"),
    ],
)
def test_board_json_counts_a_child_in_another_repository_and_names_it_only_while_open(
    foreign_state: workboard.ChildState,
    expected_closed: int,
    expected_foreign_children: list[str],
) -> None:
    """Spec: BOARD-59"""
    listed, children = container_with_children(
        CONTAINER, closed=1, open_children=(LOCAL_CHILD,), body=complete_contract("Cut it.")
    )
    container = replace(listed, children_closed=expected_closed, children_total=3)
    open_child = board_issue(LOCAL_CHILD, "Open child", complete_contract("Ship it."))
    projected = projected_board(
        (container, open_child),
        (),
        (),
        (),
        BoardConfig(),
        now=datetime(2026, 8, 21, tzinfo=UTC),
        children={CONTAINER: (*children, workboard.ForeignChild(FOREIGN_CHILD, foreign_state))},
    )

    payload = cmd_board.board_payload(projected)

    items = cast("list[dict[str, object]]", payload["items"])
    shown = cast(
        "dict[str, object]", next(i for i in items if i["number"] == CONTAINER)["container"]
    )
    open_children = cast("list[dict[str, object]]", shown["open_children"])
    assert (
        shown["closed"],
        shown["total"],
        [child["number"] for child in open_children],
        shown["foreign_children"],
    ) == (expected_closed, 3, [LOCAL_CHILD], expected_foreign_children)


def test_board_json_reads_a_container_with_only_a_foreign_open_child_as_waiting_on_it() -> None:
    """Spec: BOARD-61"""
    listed, _ = container_with_children(CONTAINER, closed=1, body=complete_contract("Cut it."))
    projected = projected_board(
        (listed,),
        (),
        (),
        (),
        BoardConfig(),
        now=datetime(2026, 8, 21, tzinfo=UTC),
        children={CONTAINER: (workboard.ForeignChild(FOREIGN_CHILD, workboard.ChildState.OPEN),)},
    )

    payload = cmd_board.board_payload(projected)

    items = cast("list[dict[str, object]]", payload["items"])
    container = next(item for item in items if item["number"] == CONTAINER)
    assert (container["actionable"], container["actionable_reason"]) == (
        False,
        f"container; waiting on {FOREIGN_CHILD}",
    )


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """The current directory is a board checkout; returns its forge repository."""
    forge = board_checkout(tmp_path / "checkout")
    monkeypatch.chdir(forge.directory)
    return str(forge.repository)


@pytest.mark.parametrize(
    ("arguments", "suffix"),
    [
        pytest.param([], "", id="board"),
        pytest.param(["7"], "&s={repository}/7", id="step"),
        pytest.param(["#7", "--line", "3"], "&c={repository}/7/3", id="card"),
    ],
)
def test_board_url_prints_the_link_and_nothing_else(
    capsys: pytest.CaptureFixture[str],
    board_unit: BoardUnit,
    checkout: str,
    arguments: list[str],
    suffix: str,
) -> None:
    """Spec: BOARD-62, BOARD-64"""
    run = run_cli(["board", "--url", *arguments], capsys)

    assert (run.status, run.stderr) == (0, "")
    assert run.stdout == (
        f"http://127.0.0.1:{board_unit.port}/#t={board_unit.token}"
        f"{suffix.format(repository=checkout)}\n"
    )


def test_board_url_without_a_board_port_refuses_naming_the_config_file(
    capsys: pytest.CaptureFixture[str], config_file: Path, checkout: str
) -> None:
    """Spec: BOARD-63"""
    config_file.parent.mkdir(parents=True)
    config_file.write_text("", encoding="utf-8")

    run = run_cli(["board", "--url"], capsys)

    assert run.stdout == ""
    assert run.expect_refusal() == f"ERROR: board_port is not set in {config_file}\n"


def test_board_url_without_a_token_file_refuses_naming_it(
    capsys: pytest.CaptureFixture[str], board_unit: BoardUnit, checkout: str
) -> None:
    """Spec: BOARD-63"""
    token = board_unit.token_file
    token.unlink()

    run = run_cli(["board", "--url"], capsys)

    assert run.stdout == ""
    assert run.expect_refusal().startswith(f"ERROR: {token} does not exist")
    assert not token.exists()


@pytest.mark.parametrize(
    ("arguments", "sentence"),
    [
        pytest.param([], "aco board requires --json or --url", id="no-mode"),
        pytest.param(["--json", "--url"], "aco board takes --json or --url, not both", id="both"),
        pytest.param(["--json", "7"], "an item and --line belong to --url", id="item-without-url"),
        pytest.param(
            ["--url", "--line", "3"],
            "--line names a card of an item; give the item",
            id="line-alone",
        ),
    ],
)
def test_board_refuses_flags_that_name_no_one_mode(
    capsys: pytest.CaptureFixture[str], arguments: list[str], sentence: str
) -> None:
    """Spec: BOARD-44, BOARD-65"""
    run = run_cli(["board", *arguments], capsys)

    assert run.expect_refusal() == f"ERROR: {sentence}\n"
