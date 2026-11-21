"""The arrangement of the repositories aco finds under its configured root:
the config file, the root and one board checkout holding one open card."""

from dataclasses import dataclass
from pathlib import Path

import pytest
from aco_board_fixtures import board_checkout
from board_fixtures import write_repository_config
from board_forge import BoardForge, item_body
from cli_fixtures import push_repository_trunk, real_git, track_board_config
from option_cards import open_option_entry

from aco import workboard


def isolated_xdg_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variable: str, *relative: str
) -> Path:
    """`relative` under a home `variable` names, a directory of this test: the run
    stays off the operator's own file, which is absent until a test writes it."""
    home = tmp_path / variable.lower()
    monkeypatch.setenv(variable, str(home))
    return home.joinpath(*relative)


def isolate_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """aco's config file, which a test writes itself."""
    return isolated_xdg_file(tmp_path, monkeypatch, "XDG_CONFIG_HOME", "aco", "config.toml")


def write_config(config_file: Path, content: str) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(content, encoding="utf-8")


def configure_root(tmp_path: Path, config_file: Path) -> Path:
    """The configured root, an existing empty directory."""
    directory = tmp_path / "root"
    directory.mkdir()
    write_config(config_file, f'root = "{directory}"\n')
    return directory


def repository_with_card(directory: Path, item: int, title: str) -> BoardForge:
    """A board checkout at `directory` holding `item`, one open option card."""
    checkout = board_checkout(directory)
    checkout.put_item(item, item_body(open_option_entry()), title=title)
    return checkout


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return isolate_config_file(tmp_path, monkeypatch)


@dataclass(frozen=True)
class BoardUnit:
    """What a started board leaves for `aco board --url`: its port and token."""

    port: int
    token: str
    token_file: Path


@pytest.fixture
def board_unit(config_file: Path, tmp_path: Path) -> BoardUnit:
    """The config file names a `board_port` beside whatever else a test writes
    to it, and the token file exists, both in this test's own homes."""
    unit = BoardUnit(8765, "t" * 43, tmp_path / "state" / "aco" / "board-token")
    unit.token_file.parent.mkdir(parents=True)
    unit.token_file.write_text(unit.token, encoding="utf-8")
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with config_file.open("a", encoding="utf-8") as handle:
        handle.write(f"board_port = {unit.port}\n")
    return unit


@pytest.fixture
def root(tmp_path: Path, config_file: Path) -> Path:
    return configure_root(tmp_path, config_file)


@pytest.fixture
def here(root: Path) -> BoardForge:
    return repository_with_card(root / "here", 1, "Here")


def discovered_checkout(
    directory: Path, remote_url: str, bare_remote: Path, board_config: str
) -> Path:
    """A real checkout at `directory` whose `origin` is `remote_url`, routed to
    `bare_remote` for transport, tracking `board_config` with its trunk pushed,
    so a scan under the root finds it as the repository `remote_url` names."""
    directory.mkdir(parents=True)
    real_git(directory, "init", "-q", "-b", "main")
    real_git(directory, "config", f"url.{bare_remote}.insteadOf", remote_url)
    real_git(directory, "remote", "add", "origin", remote_url)
    track_board_config(directory, board_config)
    push_repository_trunk(directory, "origin")
    return directory


def unreadable_checkout(directory: Path, remote_url: str) -> Path:
    """A checkout at `directory` whose `origin` is `remote_url` and whose tracked
    board configuration holds an unknown key, so a scan lists it as unavailable."""
    directory.mkdir(parents=True)
    real_git(directory, "init", "--quiet")
    real_git(directory, "remote", "add", "origin", remote_url)
    write_repository_config(directory, 'unknown_key = "x"\n')
    real_git(directory, "add", workboard.CONFIG_PATH.as_posix())
    return directory
