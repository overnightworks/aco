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
    FakeAcoRepository,
    install_fake_aco,
    line,
    path_with,
    row,
)

from aco_board import cli, static
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
        shell = board.get_shell()
        assert shell.status == 200
        assert shell.headers["Content-Type"] == "text/html; charset=utf-8"
        [repo] = cast("list[dict[str, Any]]", board.get_board_json().json()["repos"])
        assert [item["number"] for item in repo["items"]] == [1]

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


def _two_directories_named_the_same(tmp_path: Path) -> list[str]:
    first = _repository(tmp_path / "left" / "shared", row(1, "A", line(1, "A?")))
    second = _repository(tmp_path / "right" / "shared", row(2, "B", line(1, "B?")))
    return ["--repo", str(first.directory), "--repo", str(second.directory)]


def _a_symlink_resolving_to_a_configured_directory(tmp_path: Path) -> list[str]:
    """A second `--repo` spelling that resolves to the same directory as the
    first (issue #637 follow-up): `ABRD-19`'s own-directory check must read
    the resolved path, not the string a symlink was given as."""
    real = _repository(tmp_path / "shared", row(1, "A", line(1, "A?")))
    alias = tmp_path / "alias"
    alias.symlink_to(real.directory, target_is_directory=True)
    return ["--repo", str(real.directory), "--repo", str(alias)]


def _a_missing_directory(tmp_path: Path) -> list[str]:
    return ["--repo", str(tmp_path / "no-such-directory")]


def _exit_code(arguments: list[str]) -> int:
    """`cli.main`'s own exit code, whether it returns one or raises the
    `SystemExit` argparse's own usage-error path (a bad `--repo` directory)."""
    try:
        return cli.main(["serve", "--port", "0", *arguments])
    except SystemExit as refused:
        return cast(int, refused.code)


@pytest.mark.usefixtures("fake_aco_on_path")
@pytest.mark.parametrize(
    ("build_arguments", "expected_code", "expected_message"),
    [
        (_two_directories_named_the_same, 1, "two repositories named shared"),
        (_a_symlink_resolving_to_a_configured_directory, 1, "two repositories named shared"),
        (_a_missing_directory, 2, "is not a directory"),
    ],
    ids=["duplicate-label", "symlink-resolves-to-a-configured-repo", "missing-directory"],
)
def test_serve_refuses_a_bad_repo_argument_as_a_usage_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    build_arguments: Callable[[Path], list[str]],
    expected_code: int,
    expected_message: str,
) -> None:
    exit_code = _exit_code(build_arguments(tmp_path))

    assert exit_code == expected_code
    assert expected_message in capsys.readouterr().err


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
            repos = cast("list[dict[str, Any]]", board.get_board_json().json()["repos"])
            repo_name, listed_line = repos[0]["name"], repos[0]["items"][0]["lines"][0]
            clicks.submit(board.decide_through_api, listed_line, 42, "yes", repo=repo_name)
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


def test_serve_refuses_to_start_once_the_shell_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ABRD-25: the check runs before any bind attempt (`start_board` calls
    `static.ensure_built` first), so a board that cannot start never holds the
    port it would have used."""
    missing_root = tmp_path / "unbuilt"
    monkeypatch.setattr(static, "STATIC_ROOT", missing_root)
    with socket.socket() as probe:
        probe.bind((LOOPBACK_HOST, 0))
        free_port = probe.getsockname()[1]

    exit_code = cli.main(["serve", "--port", str(free_port)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"ERROR: {missing_root / 'index.html'} is missing; build the frontend first "
        "(pnpm --dir frontend install --frozen-lockfile && pnpm --dir frontend build)\n"
    )
    with socket.socket() as still_free:
        still_free.bind((LOOPBACK_HOST, free_port))
