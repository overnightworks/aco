"""The arrangement of the repositories aco finds under its configured root:
the config file, the root and one board checkout holding one open card."""

from pathlib import Path

import pytest
from aco_board_fixtures import board_checkout
from board_forge import BoardForge, item_body
from option_cards import open_option_entry


def isolate_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the run off the operator's real config file; the returned file is
    absent until a test writes it."""
    config_home = tmp_path / "config-home"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    return config_home / "aco" / "config.toml"


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
