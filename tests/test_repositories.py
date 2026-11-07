"""Repository discovery over temporary directories and real git checkouts."""

import os
from collections.abc import Callable
from pathlib import Path

import pytest
from aco_board_fixtures import board_checkout
from cli_fixtures import real_git

from aco import repositories

pytestmark = pytest.mark.usefixtures("isolated_global_git_config")


def _labels(discovery: repositories.Discovery) -> list[str]:
    return [repository.label for repository in discovery.repositories]


def _directories(discovery: repositories.Discovery) -> list[Path]:
    return [repository.directory for repository in discovery.repositories]


def _checkout_without_board_configuration(directory: Path) -> None:
    directory.mkdir(parents=True)
    real_git(directory, "init", "--quiet")
    real_git(directory, "remote", "add", "origin", "https://github.com/owner/plain")


def _untracked_board_configuration(directory: Path) -> None:
    _checkout_without_board_configuration(directory)
    board_file = directory / ".aco" / "board.toml"
    board_file.parent.mkdir()
    board_file.write_text("", encoding="utf-8")


def test_a_checkout_tracking_the_board_configuration_is_found_under_its_forge_name(
    tmp_path: Path,
) -> None:
    found = board_checkout(tmp_path / "group" / "deep" / "project")

    discovery = repositories.discover(tmp_path)

    assert discovery.root == tmp_path
    assert _labels(discovery) == [str(found.repository)]
    assert _directories(discovery) == [found.directory]
    assert discovery.unavailable == ()


@pytest.mark.parametrize(
    "arrange",
    [_checkout_without_board_configuration, _untracked_board_configuration],
    ids=["no-board-file", "untracked-board-file"],
)
def test_a_checkout_not_tracking_the_board_configuration_is_not_found(
    tmp_path: Path, arrange: Callable[[Path], None]
) -> None:
    kept = board_checkout(tmp_path / "kept")
    arrange(tmp_path / "other")

    discovery = repositories.discover(tmp_path)

    assert _labels(discovery) == [str(kept.repository)]


def test_a_linked_worktree_is_not_found_beside_its_checkout(tmp_path: Path) -> None:
    main = board_checkout(tmp_path / "main")
    real_git(
        main.directory,
        *("-c", "user.name=test", "-c", "user.email=test@example.com"),
        *("commit", "--quiet", "-m", "board"),
    )
    real_git(main.directory, "worktree", "add", "--quiet", str(tmp_path / "linked"))

    discovery = repositories.discover(tmp_path)

    assert _directories(discovery) == [main.directory]


def test_the_walk_follows_no_symlink_and_stops_at_each_checkout(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    board_checkout(outside / "linked-to")
    root = tmp_path / "root"
    root.mkdir()
    (root / "alias").symlink_to(outside, target_is_directory=True)
    kept = board_checkout(root / "kept")
    nested = kept.directory / "vendor" / "nested"
    board_checkout(nested)

    discovery = repositories.discover(root)

    assert _directories(discovery) == [kept.directory]


def test_among_clones_of_one_repository_the_first_sorted_path_wins(tmp_path: Path) -> None:
    second = board_checkout(tmp_path / "b" / "project")
    first = board_checkout(tmp_path / "a" / "project")

    discovery = repositories.discover(tmp_path)

    assert _directories(discovery) == [first.directory]
    assert second.repository == first.repository


def test_repositories_are_listed_in_label_order(tmp_path: Path) -> None:
    board_checkout(tmp_path / "zebra")
    board_checkout(tmp_path / "apple")

    discovery = repositories.discover(tmp_path)

    assert _labels(discovery) == sorted(_labels(discovery))
    assert len(discovery.repositories) == 2


def test_a_checkout_git_cannot_read_is_unavailable_with_its_path(tmp_path: Path) -> None:
    kept = board_checkout(tmp_path / "kept")
    broken = tmp_path / "broken"
    (broken / ".git").mkdir(parents=True)

    discovery = repositories.discover(tmp_path)

    assert _directories(discovery) == [kept.directory]
    [unavailable] = discovery.unavailable
    assert unavailable.directory == broken
    assert unavailable.reason


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every directory")
def test_a_directory_the_walk_cannot_open_is_unavailable_with_its_path(tmp_path: Path) -> None:
    kept = board_checkout(tmp_path / "kept")
    closed = tmp_path / "closed"
    closed.mkdir()
    closed.chmod(0)
    try:
        discovery = repositories.discover(tmp_path)
    finally:
        closed.chmod(0o700)

    assert _directories(discovery) == [kept.directory]
    assert [entry.directory for entry in discovery.unavailable] == [closed]


def test_a_root_holding_no_checkout_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(repositories.NoRepositoriesFoundError, match=str(tmp_path)):
        repositories.discover(tmp_path)


def test_a_root_holding_only_an_unreadable_checkout_is_not_refused(tmp_path: Path) -> None:
    (tmp_path / "broken" / ".git").mkdir(parents=True)

    discovery = repositories.discover(tmp_path)

    assert discovery.repositories == ()
    assert [entry.directory for entry in discovery.unavailable] == [tmp_path / "broken"]


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        pytest.param({"XDG_CONFIG_HOME": "/xdg"}, Path("/xdg/aco/config.toml"), id="absolute-xdg"),
        pytest.param(
            {"XDG_CONFIG_HOME": "relative"},
            Path("/home/me/.config/aco/config.toml"),
            id="relative-xdg",
        ),
        pytest.param({}, Path("/home/me/.config/aco/config.toml"), id="no-xdg"),
    ],
)
def test_the_config_file_is_under_an_absolute_xdg_config_home_else_under_home(
    environment: dict[str, str], expected: Path
) -> None:
    assert repositories.config_path(environment, Path("/home/me")) == expected


def test_a_config_file_names_its_root(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(f'root = "{tmp_path}"\n', encoding="utf-8")

    assert repositories.configured_root(config) == tmp_path
