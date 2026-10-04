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
    serving,
)

from aco_board.aco_cli import AcoCli


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeAcoRepository:
    return empty_repository_with_fake_aco(tmp_path, monkeypatch)


@pytest.fixture
def board(repository: FakeAcoRepository) -> Iterator[BoardClient]:
    with serving(AcoCli(directory=repository.directory)) as client:
        yield client
