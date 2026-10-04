"""`aco-board serve` driven in-process through its real entry point, `cli.main`.

`main` serves until interrupted, so a helper thread drives the printed URL and
then interrupts the main thread the way Ctrl-C does.
"""

from __future__ import annotations

import _thread
import io
import socket
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest
from aco_board_fixtures import (
    BoardClient,
    BoardPage,
    FakeAcoRepository,
    install_fake_aco,
    line,
    path_with,
    row,
)

from aco_board import cli
from aco_board.aco_cli import AcoCli
from aco_board.board import Boards
from aco_board.ports import Decision, DecisionResult
from aco_board.server import LOOPBACK_HOST

_URL_WAIT_SECONDS = 30


class _PrintedLines(io.StringIO):
    """Standard output that tells a waiting thread when the first line is out."""

    def __init__(self) -> None:
        super().__init__()
        self.first_line_printed = threading.Event()

    def write(self, text: str) -> int:
        written = super().write(text)
        if "\n" in self.getvalue():
            self.first_line_printed.set()
        return written

    def first_line(self) -> str:
        return self.getvalue().splitlines()[0]


def _serve_until_done(
    monkeypatch: pytest.MonkeyPatch,
    directory: Path,
    scenario: Callable[[BoardClient], None],
    *extra_arguments: str,
) -> int:
    """Run `aco-board serve` in `directory`, drive `scenario`, then press Ctrl-C."""
    printed = _PrintedLines()
    monkeypatch.chdir(directory)
    monkeypatch.setattr(sys, "stdout", printed)
    failures: list[BaseException] = []

    def drive() -> None:
        try:
            if not printed.first_line_printed.wait(_URL_WAIT_SECONDS):
                raise TimeoutError(f"aco-board serve printed no URL within {_URL_WAIT_SECONDS}s")
            # Every scenario requests at least once, so serving has begun
            # before the interrupt arrives.
            scenario(BoardClient.from_url(printed.first_line()))
        except BaseException as failure:
            failures.append(failure)
        finally:
            _thread.interrupt_main()

    driver = threading.Thread(target=drive)
    driver.start()
    exit_code = cli.main(["serve", "--port", "0", *extra_arguments])
    driver.join()
    if failures:
        raise failures[0]
    return exit_code


@pytest.fixture
def fake_aco_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_aco(tmp_path / "bin")
    monkeypatch.setenv("PATH", path_with(tmp_path / "bin"))


def _repository(directory: Path, *rows: dict[str, object]) -> FakeAcoRepository:
    directory.mkdir(parents=True)
    repository = FakeAcoRepository(directory)
    repository.set_rulings(*rows)
    return repository


@pytest.mark.usefixtures("fake_aco_on_path")
def test_serve_shows_its_own_repository_on_a_tokened_loopback_url_until_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = _repository(tmp_path / "here", row(1, "Here", line(1, "Ours?")))
    _repository(tmp_path / "elsewhere", row(2, "Elsewhere", line(1, "Theirs?")))
    seen: list[BoardClient] = []

    def look(board: BoardClient) -> None:
        seen.append(board)
        assert BoardPage(board.get_page().body).card_keys() == [(1, 1)]
        assert board.get_page_without_token().status == 403

    assert _serve_until_done(monkeypatch, here.directory, look) == 0
    [board] = seen
    assert board.host == LOOPBACK_HOST
    assert board.token


@pytest.mark.usefixtures("fake_aco_on_path")
def test_serve_with_repeated_repo_lists_both_repositories_under_one_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_a = _repository(tmp_path / "a", row(1, "In a", line(1, "A?")))
    repository_b = _repository(tmp_path / "b", row(2, "In b", line(1, "B?")))

    def decide_only_in_a(board: BoardClient) -> None:
        payload = board.get_board_json().json()
        repo_list = cast("list[dict[str, Any]]", payload["repos"])
        repos = {repo["name"]: repo for repo in repo_list}
        assert set(repos) == {"a", "b"}
        assert [item["number"] for item in repos["a"]["items"]] == [1]
        assert [item["number"] for item in repos["b"]["items"]] == [2]

        listed_line = repos["a"]["items"][0]["lines"][0]
        answer = board.decide_through_api(listed_line, 1, "yes", repo="a")
        assert answer.json() == {"status": "ruled", "message": None}

    exit_code = _serve_until_done(
        monkeypatch,
        tmp_path,
        decide_only_in_a,
        "--repo",
        str(repository_a.directory),
        "--repo",
        str(repository_b.directory),
    )

    assert exit_code == 0
    assert repository_a.rule_calls() == [["rule", "1", "--line", "1", "--yes", "--json"]]
    assert repository_b.rule_calls() == []


@pytest.mark.usefixtures("fake_aco_on_path")
def test_serve_refuses_two_repositories_with_the_same_label(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _repository(tmp_path / "left" / "shared", row(1, "A", line(1, "A?")))
    second = _repository(tmp_path / "right" / "shared", row(2, "B", line(1, "B?")))

    exit_code = cli.main(
        ["serve", "--port", "0", "--repo", str(first.directory), "--repo", str(second.directory)]
    )

    assert exit_code == 1
    error = capsys.readouterr().err
    assert "two repositories named shared" in error
    assert str(first.directory.resolve()) in error
    assert str(second.directory.resolve()) in error


def test_serve_refuses_a_missing_repository_as_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as refused:
        cli.main(["serve", "--repo", str(tmp_path / "no-such-directory")])

    assert refused.value.code == 2
    assert "is not a directory" in capsys.readouterr().err


@pytest.mark.usefixtures("fake_aco_on_path")
def test_interrupting_serve_during_a_ruling_waits_until_the_ruling_is_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path / "here", row(42, "Share page", line(1, "Guests?")))
    ruling_entered = threading.Event()
    ruling_may_finish = threading.Event()
    shutdown_waits = threading.Event()

    class HeldRuling(AcoCli):
        def rule(self, decision: Decision) -> DecisionResult:
            ruling_entered.set()
            assert ruling_may_finish.wait(_URL_WAIT_SECONDS)
            return super().rule(decision)

    class ShutdownWatchedBoards(Boards):
        def close_writes(self) -> None:
            shutdown_waits.set()
            super().close_writes()

    monkeypatch.setattr(cli, "AcoCli", HeldRuling)
    monkeypatch.setattr(cli, "Boards", ShutdownWatchedBoards)
    seen_while_shutdown_waited: list[list[list[str]]] = []

    def release_once_shutdown_waits() -> None:
        if shutdown_waits.wait(_URL_WAIT_SECONDS):
            seen_while_shutdown_waited.append(repository.rule_calls())
        ruling_may_finish.set()

    releaser = threading.Thread(target=release_once_shutdown_waits)
    with ThreadPoolExecutor(max_workers=1) as clicks:

        def click_then_interrupt(board: BoardClient) -> None:
            card = BoardPage(board.get_page().body).card(42, 1)
            clicks.submit(board.decide, card, "yes")
            assert ruling_entered.wait(_URL_WAIT_SECONDS)
            releaser.start()

        assert _serve_until_done(monkeypatch, repository.directory, click_then_interrupt) == 0
        # Checked before the click's own answer is awaited: `main` returning
        # must already mean the ruling is stored.
        assert repository.stored_line(42, 1)["ruling"] == "yes"
    releaser.join(_URL_WAIT_SECONDS)
    # Shutdown was already waiting while the held ruling had not yet called `aco rule`.
    assert seen_while_shutdown_waited == [[]]


_NOT_A_PORT = "is not a port between 0 and 65535"


@pytest.mark.parametrize(
    ("arguments", "refusal"),
    [
        pytest.param(["--host", "0.0.0.0"], "--host", id="no-way-to-listen-beyond-loopback"),
        pytest.param(["--port", "65536"], _NOT_A_PORT, id="port-above-65535"),
        pytest.param(["--port", "-1"], _NOT_A_PORT, id="negative-port"),
        pytest.param(["--port", "eighty"], _NOT_A_PORT, id="port-not-a-number"),
    ],
)
def test_serve_refuses_an_argument_outside_its_contract_as_a_usage_error(
    capsys: pytest.CaptureFixture[str], arguments: list[str], refusal: str
) -> None:
    with pytest.raises(SystemExit) as refused:
        cli.main(["serve", *arguments])

    assert refused.value.code == 2
    assert refusal in capsys.readouterr().err


def test_serve_refuses_a_port_already_in_use(capsys: pytest.CaptureFixture[str]) -> None:
    with socket.socket() as occupant:
        occupant.bind((LOOPBACK_HOST, 0))
        occupant.listen()
        busy_port = occupant.getsockname()[1]

        assert cli.main(["serve", "--port", str(busy_port)]) == 1

    assert f"cannot listen on {LOOPBACK_HOST}:{busy_port}" in capsys.readouterr().err
