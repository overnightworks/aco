"""The decision board's shared arrangement: the launcher first on PATH running
the real `aco` over each checkout's own forge, board checkouts, and the real
board server serving one of them."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import board_forge
import pytest
from aco_board_fixtures import (
    BoardClient,
    Lister,
    RecordedPort,
    board_checkout,
    decision_port,
    path_with,
    serving,
)
from board_forge import BoardForge

from aco import session


@pytest.fixture(autouse=True)
def board_forge_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_global_git_config: Path
) -> Path:
    """The launcher runs `aco` over the forge of the checkout it runs in, and
    `aco` run in this process (`aco serve`) builds that same forge; aco's own
    git reads the empty global configuration it returns."""
    board_forge.install_launcher(tmp_path / "bin")
    monkeypatch.setenv("PATH", path_with(tmp_path / "bin"))
    monkeypatch.setattr(session, "run_context", board_forge.run_context)
    return isolated_global_git_config


@pytest.fixture
def repository(tmp_path: Path) -> BoardForge:
    return board_checkout(tmp_path / "repository")


@pytest.fixture
def port(repository: BoardForge) -> RecordedPort:
    """The board's port over `repository`, every call to it recorded."""
    return decision_port(repository)


@pytest.fixture
def board(port: RecordedPort) -> Iterator[BoardClient]:
    with serving(port) as client:
        yield client


@pytest.fixture
def listed_items() -> Lister:
    """The one listing reader: the items a board lists for one of its repos."""

    def read(board: BoardClient, repo: str | None = None) -> list[dict[str, Any]]:
        response = board.get_board_json()
        assert response.status == 200
        repos = cast(list[dict[str, Any]], response.json()["repos"])
        [shown] = [entry for entry in repos if entry["name"] == (repo or board.repo)]
        assert shown["error"] is None
        return cast(list[dict[str, Any]], shown["items"])

    return read


@pytest.fixture
def two_repositories(tmp_path: Path) -> tuple[BoardForge, BoardForge]:
    """Two labelled board checkouts, `a` and `b`."""
    return board_checkout(tmp_path / "a"), board_checkout(tmp_path / "b")
