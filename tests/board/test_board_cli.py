"""`aco serve` driven in-process through its real entry point, `aco.cli.main`.

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
from aco_board_fixtures import BoardClient, HeldRuling, RecordedPort, board_checkout
from board_forge import BoardForge, item_body
from option_cards import open_option_entry

from aco import cli
from aco.board import cli as board_cli
from aco.board import static
from aco.board.board import Board, Boards
from aco.board.ports import DecisionPort
from aco.board.server import LOOPBACK_HOST

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
    """Run `aco serve` in `directory`, drive `scenario`, then press Ctrl-C."""
    printed = _PrintedLines()
    monkeypatch.chdir(directory)
    monkeypatch.setattr(sys, "stdout", printed)
    failures: list[BaseException] = []

    def drive() -> None:
        try:
            if not printed.first_line_printed.wait(_URL_WAIT_SECONDS):
                raise TimeoutError(f"aco serve printed no URL within {_URL_WAIT_SECONDS}s")
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


@pytest.fixture(autouse=True)
def board_token_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep every serve run off the operator's real token file."""
    state_home = tmp_path / "state-home"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    return state_home / "aco" / "board-token"


def _repository(directory: Path, item: int, title: str) -> BoardForge:
    """A board checkout at `directory` holding `item`, one open option card."""
    repository = board_checkout(directory)
    repository.put_item(item, item_body(open_option_entry()), title=title)
    return repository


def test_serve_shows_its_own_repository_on_a_tokened_loopback_url_until_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = _repository(tmp_path / "here", 1, "Here")
    _repository(tmp_path / "elsewhere", 2, "Elsewhere")
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


def test_serve_prints_the_same_token_after_a_restart_and_a_new_one_once_the_file_is_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, board_token_file: Path
) -> None:
    here = _repository(tmp_path / "here", 1, "Here")
    tokens: list[str] = []

    def remember(board: BoardClient) -> None:
        board.get_board_json()
        tokens.append(board.token)

    for _ in range(2):
        assert _serve_until_done(monkeypatch, here.directory, remember) == 0
    board_token_file.unlink()
    assert _serve_until_done(monkeypatch, here.directory, remember) == 0

    first, second, third = tokens
    assert second == first
    assert third != first


def test_serve_refuses_to_start_when_the_token_file_holds_no_token(
    board_token_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    board_token_file.parent.mkdir(parents=True)
    board_token_file.write_text("not a token")

    exit_code = cli.main(["serve", "--port", "0"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == (
        f"ERROR: {board_token_file} holds no board token; delete it to start with a new one\n"
    )


def test_serve_with_repeated_repo_lists_both_repositories_under_one_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_a = _repository(tmp_path / "a", 1, "In a")
    repository_b = _repository(tmp_path / "b", 2, "In b")

    def decide_only_in_a(board: BoardClient) -> None:
        payload = board.get_board_json().json()
        repo_list = cast("list[dict[str, Any]]", payload["repos"])
        repos = {repo["name"]: repo for repo in repo_list}
        assert set(repos) == {"a", "b"}
        assert [item["number"] for item in repos["a"]["items"]] == [1]
        assert [item["number"] for item in repos["b"]["items"]] == [2]

        listed_line = repos["a"]["items"][0]["lines"][0]
        answer = board.decide_card_through_api(1, [listed_line], ["A"], repo="a")
        assert answer.status_and_message() == {"status": "ruled", "message": None}

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
    assert (repository_a.stored_entries(1)[0]["ruling"], repository_a.body_writes()) == ("A", [1])
    assert repository_b.item_requests() == ()


def _two_directories_named_the_same(tmp_path: Path) -> list[str]:
    first = _repository(tmp_path / "left" / "shared", 1, "A")
    second = _repository(tmp_path / "right" / "shared", 2, "B")
    return ["--repo", str(first.directory), "--repo", str(second.directory)]


def _a_symlink_resolving_to_a_configured_directory(tmp_path: Path) -> list[str]:
    """A second `--repo` spelling that resolves to the same directory as the
    first: `ABRD-19`'s own-directory check must read
    the resolved path, not the string a symlink was given as."""
    real = _repository(tmp_path / "shared", 1, "A")
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


def test_interrupting_serve_during_a_ruling_waits_until_the_ruling_is_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path / "here", 42, "Share page")
    shutdown_waits = threading.Event()
    holds: list[HeldRuling] = []

    def board_holding_its_next_ruling(decisions: DecisionPort) -> Board:
        """The port `serve` built, wrapped so that its next `rule_card` is held."""
        port = RecordedPort(decisions)
        holds.append(port.hold_next_rule_card(_URL_WAIT_SECONDS))
        return Board(port)

    class ShutdownWatchedBoards(Boards):
        def close_writes(self) -> None:
            shutdown_waits.set()
            super().close_writes()

    monkeypatch.setattr(board_cli, "Board", board_holding_its_next_ruling)
    monkeypatch.setattr(board_cli, "Boards", ShutdownWatchedBoards)
    written_while_shutdown_waited: list[list[int | None]] = []

    def release_once_shutdown_waits(held: HeldRuling) -> None:
        if shutdown_waits.wait(_URL_WAIT_SECONDS):
            written_while_shutdown_waited.append(repository.body_writes())
        held.release.set()

    releasers: list[threading.Thread] = []
    with ThreadPoolExecutor(max_workers=1) as clicks:

        def click_then_interrupt(board: BoardClient) -> None:
            repos = cast("list[dict[str, Any]]", board.get_board_json().json()["repos"])
            repo_name, listed_line = repos[0]["name"], repos[0]["items"][0]["lines"][0]
            clicks.submit(board.decide_card_through_api, 42, [listed_line], ["A"], repo=repo_name)
            [held] = holds
            assert held.entered.wait(_URL_WAIT_SECONDS)
            releasers.append(threading.Thread(target=release_once_shutdown_waits, args=(held,)))
            releasers[0].start()

        assert _serve_until_done(monkeypatch, repository.directory, click_then_interrupt) == 0
        # Checked before the click's own answer is awaited: `main` returning
        # must already mean the ruling is stored.
        assert repository.stored_entries(42)[0]["ruling"] == "A"
    releasers[0].join(_URL_WAIT_SECONDS)
    # Shutdown was already waiting while the held ruling had not yet written its item.
    assert written_while_shutdown_waited == [[]]


_NOT_A_PORT = "is not a port between 0 and 65535"


@pytest.mark.parametrize(
    ("arguments", "refusal"),
    [
        pytest.param(["--host", "0.0.0.0"], "--host", id="no-way-to-listen-beyond-loopback"),  # noqa: S104 - the case proves the refusal of a non-loopback host
        pytest.param(["--json"], "unrecognized arguments: --json", id="no-json-mode"),
        pytest.param(["--po", "1"], "unrecognized arguments: --po 1", id="no-abbreviated-flag"),
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
    captured = capsys.readouterr()
    assert captured.out == ""
    assert refusal in captured.err


def test_serve_refuses_the_global_repo_naming_a_forge_repository(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--repo", "overnightworks/aco", "serve"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "ERROR: aco serve reads checkout directories; pass them as aco serve --repo PATH\n"
    )


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
    port it would have used. Proven by keeping the port occupied for the whole
    call: a bind-then-check implementation would instead fail trying to bind,
    surfacing the "cannot listen" / address-in-use message (see
    `test_serve_refuses_a_port_already_in_use`) rather than the asset-missing
    one asserted below."""
    missing_root = tmp_path / "unbuilt"
    monkeypatch.setattr(static, "STATIC_ROOT", missing_root)
    with socket.socket() as occupant:
        occupant.bind((LOOPBACK_HOST, 0))
        occupant.listen()
        occupied_port = occupant.getsockname()[1]

        exit_code = cli.main(["serve", "--port", str(occupied_port)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"ERROR: {missing_root / 'index.html'} is missing; build the frontend first "
        "(pnpm --dir frontend install --frozen-lockfile && pnpm --dir frontend build)\n"
    )
