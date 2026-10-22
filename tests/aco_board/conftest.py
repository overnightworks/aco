"""The decision board's shared arrangement: a repository with a fake `aco`
on PATH, and the real board server running against it."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from aco_board_fixtures import (
    BoardClient,
    FakeAcoRepository,
    empty_repository_with_fake_aco,
    install_fake_aco,
    named_repository,
    path_with,
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
def two_repositories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[FakeAcoRepository, FakeAcoRepository]:
    """Two labelled repositories, `a` and `b`, sharing one fake `aco` on PATH."""
    install_fake_aco(tmp_path / "bin")
    monkeypatch.setenv("PATH", path_with(tmp_path / "bin"))
    return named_repository(tmp_path, "a"), named_repository(tmp_path, "b")
