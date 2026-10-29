"""The board token's file: path, creation, reuse and refusal of a foreign shape."""

from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from aco.board.token_store import MalformedTokenFileError, board_token, token_path


@pytest.mark.parametrize(
    ("environment", "expected_relative_to_tmp"),
    [
        ({"XDG_STATE_HOME": "{tmp}/state"}, "state/aco/board-token"),
        ({}, "home/.local/state/aco/board-token"),
        ({"XDG_STATE_HOME": ""}, "home/.local/state/aco/board-token"),
        ({"XDG_STATE_HOME": "relative/state"}, "home/.local/state/aco/board-token"),
    ],
    ids=["absolute-xdg", "xdg-unset", "xdg-empty", "xdg-relative"],
)
def test_token_path_follows_the_xdg_state_rule(
    tmp_path: Path, environment: dict[str, str], expected_relative_to_tmp: str
) -> None:
    resolved_environment = {name: value.format(tmp=tmp_path) for name, value in environment.items()}

    assert (
        token_path(resolved_environment, tmp_path / "home") == tmp_path / expected_relative_to_tmp
    )


def test_board_token_creates_a_user_only_file_with_user_only_directories(tmp_path: Path) -> None:
    path = tmp_path / "state" / "aco" / "board-token"
    previous_umask = os.umask(0o002)

    try:
        token = board_token(path)
    finally:
        os.umask(previous_umask)

    assert path.read_text() == token
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.parent.parent.stat().st_mode) == 0o700
    assert len(token) >= 43


def test_board_token_reuses_the_token_the_file_holds(tmp_path: Path) -> None:
    path = tmp_path / "aco" / "board-token"
    first = board_token(path)

    second = board_token(path)

    assert second == first


def test_board_token_keeps_an_existing_directory_mode(tmp_path: Path) -> None:
    existing = tmp_path / "aco"
    existing.mkdir(mode=0o755)
    existing.chmod(0o755)

    board_token(existing / "board-token")

    assert stat.S_IMODE(existing.stat().st_mode) == 0o755


def test_concurrent_first_starts_all_receive_the_stored_token(tmp_path: Path) -> None:
    path = tmp_path / "aco" / "board-token"

    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(board_token, [path] * 8))

    assert set(tokens) == {path.read_text()}


def test_board_token_is_new_once_the_file_is_deleted(tmp_path: Path) -> None:
    path = tmp_path / "aco" / "board-token"
    first = board_token(path)
    path.unlink()

    second = board_token(path)

    assert second != first


def test_board_token_accepts_a_trailing_newline(tmp_path: Path) -> None:
    path = tmp_path / "board-token"
    held = "a" * 43
    path.write_text(f"{held}\n")

    token = board_token(path)

    assert token == held


def test_board_token_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    path = tmp_path / "aco" / "board-token"

    board_token(path)

    assert [entry.name for entry in path.parent.iterdir()] == ["board-token"]


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\n",
        b"short",
        b"a" * 43 + b"\n\n",
        b"a" * 20 + b" " + b"b" * 22,
        b"a" * 42 + b"!",
        b"a" * 43 + b"\nb",
        b"\xff" * 50,
    ],
    ids=[
        "empty",
        "newline-only",
        "too-short",
        "two-newlines",
        "inner-space",
        "bad-character",
        "two-lines",
        "not-utf8",
    ],
)
def test_board_token_refuses_content_that_is_not_one_token(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "board-token"
    path.write_bytes(content)

    with pytest.raises(MalformedTokenFileError) as refusal:
        board_token(path)

    assert refusal.value.path == path
    assert path.read_bytes() == content
