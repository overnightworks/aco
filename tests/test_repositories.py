"""Repository discovery over temporary directories and real git checkouts."""

import os
from collections.abc import Callable
from pathlib import Path

import pytest
from aco_board_fixtures import board_checkout
from board_fixtures import write_repository_config
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


def _tracked_checkout(directory: Path, *, remote: str | None, board_toml: str = "") -> None:
    directory.mkdir(parents=True)
    real_git(directory, "init", "--quiet")
    if remote is not None:
        real_git(directory, "remote", "add", "origin", remote)
    write_repository_config(directory, board_toml)
    real_git(directory, "add", ".aco/board.toml")


def _git_directory_only(directory: Path) -> None:
    (directory / ".git").mkdir(parents=True)


def _without_remote(directory: Path) -> None:
    _tracked_checkout(directory, remote=None)


def _with_non_github_remote(directory: Path) -> None:
    _tracked_checkout(directory, remote="https://gitlab.com/owner/repo")


def _with_malformed_board_configuration(directory: Path) -> None:
    _tracked_checkout(directory, remote="https://github.com/owner/repo", board_toml="= nope")


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


def test_repositories_are_listed_in_label_order_not_path_order(tmp_path: Path) -> None:
    board_checkout(tmp_path / "a" / "zebra")
    board_checkout(tmp_path / "b" / "apple")

    discovery = repositories.discover(tmp_path)

    assert _labels(discovery) == ["board-forge/apple", "board-forge/zebra"]


@pytest.mark.parametrize(
    "arrange",
    [
        _git_directory_only,
        _without_remote,
        _with_non_github_remote,
        _with_malformed_board_configuration,
    ],
    ids=["git-directory-only", "no-remote", "non-github-remote", "malformed-board-file"],
)
def test_a_checkout_that_cannot_be_read_is_unavailable_with_its_path(
    tmp_path: Path, arrange: Callable[[Path], None]
) -> None:
    kept = board_checkout(tmp_path / "kept")
    broken = tmp_path / "broken"
    arrange(broken)

    discovery = repositories.discover(tmp_path)

    assert _directories(discovery) == [kept.directory]
    [unavailable] = discovery.unavailable
    assert unavailable.directory == broken
    assert unavailable.reason


def test_a_remote_url_the_github_pattern_misses_is_read_without_asking_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refusing_gh = tmp_path / "bin" / "gh"
    refusing_gh.parent.mkdir()
    refusing_gh.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    refusing_gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{refusing_gh.parent}{os.pathsep}{os.environ['PATH']}")
    _tracked_checkout(
        tmp_path / "root" / "project", remote="ssh://git@github.com:22/owner/repo.git"
    )

    discovery = repositories.discover(tmp_path / "root")

    assert _labels(discovery) == ["owner/repo"]


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


def _unreadable_config(config: Path) -> None:
    config.write_bytes(b'root = "\xff\xfe"\n')


def _config_that_is_a_directory(config: Path) -> None:
    config.mkdir()


@pytest.mark.parametrize(
    "arrange",
    [_unreadable_config, _config_that_is_a_directory],
    ids=["not-utf-8", "directory"],
)
def test_a_config_file_that_cannot_be_read_is_refused_by_name(
    tmp_path: Path, arrange: Callable[[Path], None]
) -> None:
    config = tmp_path / "config.toml"
    arrange(config)

    with pytest.raises(repositories.RootConfigError, match=str(config)):
        repositories.configured_root(config)
