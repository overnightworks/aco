"""`aco --help` as a reader sees it."""

from __future__ import annotations

import re

import pytest
from cli_fixtures import run_cli

from aco import cli

# A command's own row in argparse's listing: four spaces, then its name.
_COMMAND_ROW = re.compile(r"^ {4}([a-z]+)\b")


def test_help_lists_commands_in_their_stable_registration_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`aco --help` lists exactly the registered commands, each once, in the
    order they are registered, so the order is part of the CLI's contract."""
    shown = run_cli(["--help"], capsys).expect_success()
    listed = [row.group(1) for line in shown.splitlines() if (row := _COMMAND_ROW.match(line))]
    assert listed == list(cli._COMMANDS)
