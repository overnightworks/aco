"""The arrangement of the repositories aco finds under its configured root:
the config file, the root and one board checkout holding one open card."""

from pathlib import Path

import pytest
from aco_board_fixtures import board_checkout
from board_forge import BoardForge, item_body
from option_cards import open_option_entry


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
