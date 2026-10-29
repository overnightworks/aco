"""The decision board's shared arrangement: a repository with a fake `aco`
on PATH, and the real board server running against it."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from aco_board_fixtures import (
    BoardClient,
    FakeAcoRepository,
    empty_repository_with_fake_aco,
    first_listed_line,
    install_fake_aco,
    named_repository,
    option_line,
    path_with,
    row,
    serving,
)

from aco.board.aco_cli import AcoCli


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeAcoRepository:
    return empty_repository_with_fake_aco(tmp_path, monkeypatch)


@pytest.fixture
def board(repository: FakeAcoRepository) -> Iterator[BoardClient]:
    with serving(AcoCli(directory=repository.directory)) as client:
        yield client


@pytest.fixture
def listed_items() -> Callable[[BoardClient], list[dict[str, Any]]]:
    """Reads the items one board lists for its single repository, checking the listing succeeded."""

    def read(board: BoardClient) -> list[dict[str, Any]]:
        response = board.get_board_json()
        assert response.status == 200
        [repo] = cast(list[dict[str, Any]], response.json()["repos"])
        assert repo["name"] == board.repo
        assert repo["error"] is None
        return cast(list[dict[str, Any]], repo["items"])

    return read


@pytest.fixture
def two_repositories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[FakeAcoRepository, FakeAcoRepository]:
    """Two labelled repositories, `a` and `b`, sharing one fake `aco` on PATH."""
    install_fake_aco(tmp_path / "bin")
    monkeypatch.setenv("PATH", path_with(tmp_path / "bin"))
    return named_repository(tmp_path, "a"), named_repository(tmp_path, "b")


@pytest.fixture
def listed(repository: FakeAcoRepository, board: BoardClient) -> dict[str, Any]:
    """The post payload naming item 12's first listed line, without a decision."""
    repository.set_rulings(row(12, "Song jump", option_line()))
    shown = first_listed_line(board)
    return {
        "repo": board.repo,
        "item": 12,
        "line": shown["index"],
        "fingerprint": shown["fingerprint"],
    }
