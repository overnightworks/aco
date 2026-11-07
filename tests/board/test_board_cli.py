"""`aco serve` driven in-process through its real entry point, `aco.cli.main`.

`main` serves until interrupted, so a helper thread drives the printed URL and
then interrupts the main thread the way Ctrl-C does.
"""

import _thread
import io
import shutil
import socket
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest
from aco_board_fixtures import BoardClient, HeldRuling, RecordedPort
from discovery_fixtures import (
    configure_root,
    isolate_config_file,
    isolated_xdg_file,
    repository_with_card,
    write_config,
)

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
    monkeypatch: pytest.MonkeyPatch, scenario: Callable[[BoardClient], None]
) -> int:
    """Run `aco serve`, drive `scenario`, then press Ctrl-C."""
    printed = _PrintedLines()
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
    exit_code = cli.main(["serve", "--port", "0"])
    driver.join()
    if failures:
        raise failures[0]
    return exit_code


@pytest.fixture(autouse=True)
def board_token_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep every serve run off the operator's real token file."""
    return isolated_xdg_file(tmp_path, monkeypatch, "XDG_STATE_HOME", "aco", "board-token")


@pytest.fixture(autouse=True)
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep every serve run off the operator's real config file; the file
    itself is absent until a test writes it."""
    return isolate_config_file(tmp_path, monkeypatch)


@pytest.fixture
def root(tmp_path: Path, config_file: Path) -> Path:
    """The configured root, an existing empty directory."""
    return configure_root(tmp_path, config_file)


def _repos_by_name(board: BoardClient) -> dict[str, dict[str, Any]]:
    repo_list = cast("list[dict[str, Any]]", board.get_board_json().json()["repos"])
    return {repo["name"]: repo for repo in repo_list}


def test_serve_shows_every_repository_under_the_root_on_a_tokened_loopback_url_until_interrupted(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = repository_with_card(root / "here", 1, "Here")
    elsewhere = repository_with_card(root / "group" / "elsewhere", 2, "Elsewhere")
    seen: list[BoardClient] = []

    def look(board: BoardClient) -> None:
        seen.append(board)
        shell = board.get_shell()
        assert shell.status == 200
        assert shell.headers["Content-Type"] == "text/html; charset=utf-8"
        answer = board.get_board_json().json()
        assert answer["root"] == str(root)
        repos = _repos_by_name(board)
        assert set(repos) == {str(here.repository), str(elsewhere.repository)}
        assert [item["number"] for item in repos[str(here.repository)]["items"]] == [1]
        assert [item["number"] for item in repos[str(elsewhere.repository)]["items"]] == [2]

    assert _serve_until_done(monkeypatch, look) == 0
    [board] = seen
    assert board.host == LOOPBACK_HOST
    assert board.token


def test_serve_prints_the_same_token_after_a_restart_and_a_new_one_once_the_file_is_deleted(
    root: Path, monkeypatch: pytest.MonkeyPatch, board_token_file: Path
) -> None:
    repository_with_card(root / "here", 1, "Here")
    tokens: list[str] = []

    def remember(board: BoardClient) -> None:
        board.get_board_json()
        tokens.append(board.token)

    for _ in range(2):
        assert _serve_until_done(monkeypatch, remember) == 0
    board_token_file.unlink()
    assert _serve_until_done(monkeypatch, remember) == 0

    first, second, third = tokens
    assert second == first
    assert third != first


def test_serve_refuses_to_start_when_the_token_file_holds_no_token(
    root: Path, board_token_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository_with_card(root / "here", 1, "Here")
    board_token_file.parent.mkdir(parents=True)
    board_token_file.write_text("not a token")

    exit_code = cli.main(["serve", "--port", "0"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == (
        f"ERROR: {board_token_file} holds no board token; delete it to start with a new one\n"
    )


def test_serve_decides_in_the_repository_a_card_names_and_touches_no_other(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_a = repository_with_card(root / "a", 1, "In a")
    repository_b = repository_with_card(root / "b", 2, "In b")
    label_a = str(repository_a.repository)

    def decide_only_in_a(board: BoardClient) -> None:
        repos = _repos_by_name(board)
        listed_line = repos[label_a]["items"][0]["lines"][0]
        answer = board.decide_card_through_api(1, [listed_line], ["A"], repo=label_a)
        assert answer.status_and_message() == {"status": "ruled", "message": None}

    assert _serve_until_done(monkeypatch, decide_only_in_a) == 0
    assert (repository_a.stored_entries(1)[0]["ruling"], repository_a.body_writes()) == ("A", [1])
    assert repository_b.item_requests() == ()


def test_serve_finds_a_repository_added_and_loses_one_removed_after_it_started(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kept = repository_with_card(root / "kept", 1, "Kept")
    removed = repository_with_card(root / "removed", 2, "Removed")
    seen: list[set[str]] = []
    added_labels: list[str] = []

    def watch_the_root_change(board: BoardClient) -> None:
        seen.append(set(_repos_by_name(board)))
        shutil.rmtree(removed.directory)
        added_labels.append(str(repository_with_card(root / "added", 3, "Added").repository))
        seen.append(set(_repos_by_name(board)))

    assert _serve_until_done(monkeypatch, watch_the_root_change) == 0
    before, after = seen
    assert before == {str(kept.repository), str(removed.repository)}
    assert after == {str(kept.repository), *added_labels}


def test_serve_answers_a_read_once_nothing_is_found_with_a_refusal_naming_the_root(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    only = repository_with_card(root / "only", 1, "Only")
    answers: list[tuple[int, dict[str, object]]] = []

    def read_after_the_repository_is_gone(board: BoardClient) -> None:
        shutil.rmtree(only.directory)
        answer = board.get_board_json()
        answers.append((answer.status, answer.json()))

    assert _serve_until_done(monkeypatch, read_after_the_repository_is_gone) == 0
    assert answers == [(502, {"error": f"no repository tracking .aco/board.toml under {root}"})]


def test_serve_shows_a_checkout_it_cannot_read_as_unavailable_with_its_path(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = repository_with_card(root / "good", 1, "Good")
    broken = root / "broken"
    (broken / ".git").mkdir(parents=True)
    seen: list[dict[str, Any]] = []

    def look(board: BoardClient) -> None:
        seen.append(_repos_by_name(board))

    assert _serve_until_done(monkeypatch, look) == 0
    [repos] = seen
    assert list(repos) == [str(good.repository), str(broken)]
    assert repos[str(broken)]["items"] == []
    assert repos[str(broken)]["error"]


def test_serve_answers_502_naming_each_unreadable_checkout_when_none_else_is_found(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = root / "broken"
    (broken / ".git").mkdir(parents=True)
    answers: list[tuple[int, str, list[str]]] = []

    def look(board: BoardClient) -> None:
        answer = board.get_board_json()
        body = answer.json()
        names = [repo["name"] for repo in cast("list[dict[str, Any]]", body["repos"])]
        answers.append((answer.status, str(body["root"]), names))

    assert _serve_until_done(monkeypatch, look) == 0
    assert answers == [(502, str(root), [str(broken)])]


def test_serve_refuses_a_decision_for_a_repository_the_scan_does_not_find(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = repository_with_card(root / "here", 1, "Here")
    answers: list[tuple[int, str]] = []

    def decide_in_another_repository(board: BoardClient) -> None:
        listed_line = _repos_by_name(board)[str(repository.repository)]["items"][0]["lines"][0]
        answer = board.decide_card_through_api(1, [listed_line], ["A"], repo="nobody/else")
        answers.append((answer.status, str(answer.json()["error"])))

    assert _serve_until_done(monkeypatch, decide_in_another_repository) == 0
    assert answers == [(400, "bad request: decision")]
    assert repository.item_requests() == ()


def _a_missing_config_file(config_file: Path, _tmp_path: Path) -> str:
    return f'{config_file} does not exist; create it with root = "<absolute path>"'


def _a_malformed_config_file(config_file: Path, _tmp_path: Path) -> str:
    write_config(config_file, "root = ")
    return f"{config_file} is not valid TOML: "


def _a_config_file_without_a_root(config_file: Path, _tmp_path: Path) -> str:
    write_config(config_file, 'directory = "/somewhere"\n')
    return f'{config_file} sets no root = "<absolute path>"'


def _a_relative_root(config_file: Path, _tmp_path: Path) -> str:
    write_config(config_file, 'root = "repositories"\n')
    return f"{config_file}: root repositories is not an absolute path"


def _a_root_that_is_no_directory(config_file: Path, tmp_path: Path) -> str:
    missing = tmp_path / "no-such-root"
    write_config(config_file, f'root = "{missing}"\n')
    return f"{config_file}: root {missing} is not a directory"


def _a_root_without_a_board_checkout(config_file: Path, tmp_path: Path) -> str:
    empty = tmp_path / "empty-root"
    empty.mkdir()
    write_config(config_file, f'root = "{empty}"\n')
    return f"no repository tracking .aco/board.toml under {empty}"


@pytest.mark.parametrize(
    "arrange",
    [
        _a_missing_config_file,
        _a_malformed_config_file,
        _a_config_file_without_a_root,
        _a_relative_root,
        _a_root_that_is_no_directory,
        _a_root_without_a_board_checkout,
    ],
    ids=["no-file", "malformed", "no-root", "relative-root", "no-directory", "none-found"],
)
def test_serve_refuses_to_start_without_a_usable_root_and_names_why(
    tmp_path: Path,
    config_file: Path,
    capsys: pytest.CaptureFixture[str],
    arrange: Callable[[Path, Path], str],
) -> None:
    refusal = arrange(config_file, tmp_path)

    exit_code = cli.main(["serve", "--port", "0"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err.startswith(f"ERROR: {refusal}")
    assert captured.err.count("\n") == 1


def test_interrupting_serve_during_a_ruling_waits_until_the_ruling_is_stored(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = repository_with_card(root / "here", 42, "Share page")
    shutdown_waits = threading.Event()
    holds: list[HeldRuling] = []
    ports: dict[DecisionPort, RecordedPort] = {}

    def board_holding_its_next_ruling(decisions: DecisionPort) -> Board:
        """The port `serve` built, wrapped so that its next `rule_card` is held;
        every scan builds its ports anew, so a repository keeps its one wrapper."""
        if decisions not in ports:
            ports[decisions] = RecordedPort(decisions)
            holds.append(ports[decisions].hold_next_rule_card(_URL_WAIT_SECONDS))
        return Board(ports[decisions])

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

        assert _serve_until_done(monkeypatch, click_then_interrupt) == 0
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
        pytest.param(
            ["--repo", "elsewhere"], "unrecognized arguments: --repo elsewhere", id="no-repo-flag"
        ),
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
        "ERROR: aco serve finds its repositories itself; --repo does not apply to it\n"
    )


def test_serve_refuses_a_port_already_in_use(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository_with_card(root / "here", 1, "Here")
    with socket.socket() as occupant:
        occupant.bind((LOOPBACK_HOST, 0))
        occupant.listen()
        busy_port = occupant.getsockname()[1]

        assert cli.main(["serve", "--port", str(busy_port)]) == 1

    assert f"cannot listen on {LOOPBACK_HOST}:{busy_port}" in capsys.readouterr().err


def test_serve_refuses_to_start_once_the_shell_is_missing(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ABRD-25: the check runs before any bind attempt (`start_board` calls
    `static.ensure_built` first), so a board that cannot start never holds the
    port it would have used. Proven by keeping the port occupied for the whole
    call: a bind-then-check implementation would instead fail trying to bind,
    surfacing the "cannot listen" / address-in-use message (see
    `test_serve_refuses_a_port_already_in_use`) rather than the asset-missing
    one asserted below."""
    repository_with_card(root / "here", 1, "Here")
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
