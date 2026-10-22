"""The CLI runner restores the caller's input on every exit path."""

import sys
from typing import TextIO

import pytest
from cli_fixtures import run_cli

from aco import cli


@pytest.mark.parametrize(
    ("outcome", "argv"),
    [
        pytest.param("returned", ["body", "--check"], id="returned"),
        pytest.param("argparse exit", ["body", "--check", "--no-such-flag"], id="argparse-exit"),
        pytest.param("raised", ["body", "--check"], id="raised"),
    ],
)
def test_run_cli_restores_stdin_after_the_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: str,
    argv: list[str],
) -> None:
    """FB 4.2: restore previous stdin, close the pipe, and propagate exceptions."""
    previous_stdin = sys.stdin
    observed: list[TextIO] = []

    def raise_from_main(_argv: list[str]) -> int:
        observed.append(sys.stdin)
        raise RuntimeError("runner failure")

    if outcome == "raised":
        monkeypatch.setattr(cli, "main", raise_from_main)
        with pytest.raises(RuntimeError, match="runner failure"):
            run_cli(argv, capsys, stdin="body")
    else:
        assert run_cli(argv, capsys, stdin="body").status == 2

    assert sys.stdin is previous_stdin
    if outcome == "raised":
        assert observed[0].closed
