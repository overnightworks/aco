"""`aco fleet-plans` (`specs/fleet-plans.spec.md`) through the real CLI over the
board's test forge, with several repositories under one configured root."""

import json
from pathlib import Path

import board_forge
import pytest
from aco_board_fixtures import board_checkout
from board_forge import BoardForge
from cli_fixtures import CliRun, run_cli
from discovery_fixtures import configure_root, isolate_config_file
from option_cards import open_option_entry

from aco import session, workboard

_MARK = workboard.FLEET_PLAN_LABEL


@pytest.fixture(autouse=True)
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return isolate_config_file(tmp_path, monkeypatch)


@pytest.fixture
def root(tmp_path: Path, config_file: Path) -> Path:
    return configure_root(tmp_path, config_file)


@pytest.fixture(autouse=True)
def board_forge_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session, "run_context", board_forge.run_context)


@pytest.fixture(autouse=True)
def _empty_global_git_config(isolated_global_git_config: Path) -> None:
    """Real git reads an empty global configuration."""


def _put(
    repository: BoardForge,
    number: int,
    title: str,
    *,
    labels: tuple[str, ...] = (_MARK,),
    author_is_member: bool = True,
) -> None:
    repository.put_item(
        number,
        board_forge.item_body(open_option_entry()),
        title=title,
        labels=labels,
        author_is_member=author_is_member,
    )


def _fleet(root: Path) -> BoardForge:
    """Two repositories: `here` holds nothing marked, `elsewhere` holds the one plan
    that counts among an unmarked, a closed and a stranger's marked item."""
    board_checkout(root / "here")
    elsewhere = board_checkout(root / "elsewhere")
    _put(elsewhere, 2, "Rename every repository")
    _put(elsewhere, 3, "Unmarked", labels=())
    _put(elsewhere, 4, "Closed plan")
    elsewhere.close_item(4)
    _put(elsewhere, 5, "A stranger's plan", author_is_member=False)
    return elsewhere


def _answer(run: CliRun) -> dict[str, object]:
    assert run.stderr == ""
    return json.loads(run.stdout)


def test_the_read_returns_the_open_marked_plan_of_another_repository_and_nothing_else(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _fleet(root)
    command = ["fleet-plans", "--json"]

    run = run_cli(command, capsys)

    assert run.status == 0
    assert _answer(run) == {
        "ok": True,
        "reason": "listed",
        "plans": [
            {
                "repository": "board-forge/elsewhere",
                "number": 2,
                "title": "Rename every repository",
                "url": "https://github.com/board-forge/elsewhere/issues/2",
                "updated_on": "2026-08-20",
            }
        ],
        "unavailable": [],
    }


def test_plans_are_ordered_by_repository_then_number(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    second = board_checkout(root / "second")
    first = board_checkout(root / "first")
    _put(second, 1, "Second one")
    _put(first, 9, "First nine")
    _put(first, 3, "First three")
    command = ["fleet-plans", "--json"]

    answer = _answer(run_cli(command, capsys))

    plans = answer["plans"]
    assert isinstance(plans, list)
    assert [(plan["repository"], plan["number"]) for plan in plans] == [
        ("board-forge/first", 3),
        ("board-forge/first", 9),
        ("board-forge/second", 1),
    ]


def test_the_text_form_prints_one_line_per_plan(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _fleet(root)
    command = ["fleet-plans"]

    run = run_cli(command, capsys)

    assert (run.status, run.stderr) == (0, "")
    assert run.stdout == (
        "board-forge/elsewhere#2 2026-08-20: Rename every repository "
        "https://github.com/board-forge/elsewhere/issues/2\n"
    )


def test_the_text_form_of_no_plan_says_so(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    board_checkout(root / "here")
    command = ["fleet-plans"]

    run = run_cli(command, capsys)

    assert (run.status, run.stdout, run.stderr) == (0, "No fleet-wide plans.\n", "")


def test_a_title_with_a_display_control_is_escaped_in_text_and_kept_in_json(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = board_checkout(root / "here")
    _put(repository, 1, "Rename\x1b[2J")

    text = run_cli(["fleet-plans"], capsys)
    as_json = _answer(run_cli(["fleet-plans", "--json"], capsys))

    assert text.stdout.startswith("board-forge/here#1 2026-08-20: Rename\\x1b[2J ")
    plans = as_json["plans"]
    assert isinstance(plans, list)
    assert plans[0]["title"] == "Rename\x1b[2J"


def test_an_unreadable_repository_is_listed_while_the_others_answer(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = _fleet(root)
    broken = board_checkout(root / "broken")
    broken.fail_listing("rate limited")
    json_command = ["fleet-plans", "--json"]
    text_command = ["fleet-plans"]

    as_json = run_cli(json_command, capsys)
    as_text = run_cli(text_command, capsys)

    assert as_json.status == 0
    answer = _answer(as_json)
    plans = answer["plans"]
    assert isinstance(plans, list)
    assert [plan["repository"] for plan in plans] == [str(elsewhere.repository)]
    assert answer["unavailable"] == [{"repository": "board-forge/broken", "reason": "rate limited"}]
    assert as_text.status == 0
    assert as_text.stdout.splitlines()[-1] == "unavailable board-forge/broken: rate limited"


def test_no_readable_repository_refuses(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    board_checkout(root / "broken").fail_listing("rate limited")
    json_command = ["fleet-plans", "--json"]
    text_command = ["fleet-plans"]

    as_json = run_cli(json_command, capsys)
    as_text = run_cli(text_command, capsys)

    assert (as_json.status, as_text.status) == (2, 2)
    refusal = json.loads(as_json.stdout)
    assert (refusal["ok"], refusal["reason"]) == (False, "unavailable")
    assert refusal["message"].endswith("(board-forge/broken: rate limited)")
    assert as_text.stderr.startswith("ERROR: no repository could be read under ")


def test_no_configured_root_refuses(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    command = ["fleet-plans", "--json"]

    run = run_cli(command, capsys)

    assert run.status == 2
    refusal = json.loads(run.stdout)
    assert (refusal["ok"], refusal["reason"]) == (False, "unavailable")
    assert str(config_file) in refusal["message"]


def test_repo_does_not_apply_because_the_command_finds_its_repositories(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _fleet(root)
    command = ["--repo", "board-forge/elsewhere", "fleet-plans", "--json"]

    run = run_cli(command, capsys)

    assert run.status == 2
    refusal = json.loads(run.stdout)
    assert (refusal["ok"], refusal["reason"]) == (False, "invalid_usage")


def test_a_state_ref_plan_carries_no_link(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repository = board_checkout(root / "here")
    (repository.directory / workboard.CONFIG_PATH).write_text(
        'storage = "state-ref"\ncanonical_remote = "origin"\n', encoding="utf-8"
    )
    _put(repository, 1, "Rename every repository")
    command = ["fleet-plans", "--json"]

    answer = _answer(run_cli(command, capsys))

    plans = answer["plans"]
    assert isinstance(plans, list)
    assert plans[0]["url"] is None


def test_help_names_the_mark_the_command_reads(capsys: pytest.CaptureFixture[str]) -> None:
    command = ["fleet-plans", "--help"]

    run = run_cli(command, capsys)

    assert run.status == 0
    assert f"labelled {_MARK} " in run.stdout
