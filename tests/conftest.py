"""Shared test isolation.

Only isolation fixtures live here -- the autouse ones and the isolation more
than one module asks for by name; everything else stays local to its test
module. The one exception is registration: `cli_fixtures` is loaded as a
pytest plugin (`pytest_plugins` below), so its `bare_remote` and `worktree`
fixtures resolve by name in every test module, and its autouse
`_isolate_agent_identity` applies to every test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_coordination import checkout, process, protect

# Registers `bare_remote` and `worktree` for every module by name: an import
# of a fixture only to receive it as a parameter reads as unused to ruff.
pytest_plugins = ["cli_fixtures"]


@pytest.fixture(autouse=True)
def _isolate_protect_unguarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test inherits the session's own `ACO_PROTECT_UNGUARDED`: a
    developer's scratchpad exemption would otherwise let a protect test
    allow what it means to prove denied."""
    monkeypatch.delenv(protect.PROTECT_UNGUARDED_ENV, raising=False)


_SHOW_TOPLEVEL_ARGUMENTS = ["rev-parse", "--show-toplevel"]
_RECORDED_HEAD_READ_PREFIX = ["rev-parse", "--verify", "--quiet", "--symbolic-full-name"]


def _is_recorded_head_read(arguments: list[str]) -> bool:
    return arguments[:4] == _RECORDED_HEAD_READ_PREFIX and arguments[4].endswith("/HEAD")


@pytest.fixture(autouse=True)
def _isolate_git_toplevel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No test may resolve this repository's own board configuration.

    `board.CONFIG_PATH` is read relative to `rev-parse --show-toplevel`, so a
    test that never overrides it would otherwise load and be governed by this
    checkout's own `board.CONFIG_PATH`. A test that needs a specific
    toplevel keeps its own `monkeypatch.setattr(checkout, "git_output", ...)`,
    which takes precedence over this default.

    The world is synthetic exactly while that toplevel is no repository (no
    `.git` entry, file or directory, checked at call time): there a remote
    never recorded a `HEAD`, which a real git answers with exit 1. As soon
    as a test makes the toplevel a repository, the read reaches real git.
    """
    real_git_output = checkout.git_output

    def fake_git_output(
        arguments: list[str], *, directory: Path | None = None, **options: bool
    ) -> str:
        if arguments == _SHOW_TOPLEVEL_ARGUMENTS and directory is None:
            return str(tmp_path)
        if (
            _is_recorded_head_read(arguments)
            and directory in (None, tmp_path)
            and not (tmp_path / ".git").exists()
        ):
            raise checkout.GitExitError(process.CapturedResult(1, b"", b""))
        return real_git_output(arguments, directory=directory, **options)

    monkeypatch.setattr(checkout, "git_output", fake_git_output)


@pytest.fixture
def isolated_global_git_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Real git reads an empty global configuration, never the operator's
    own (#310 finding 184): an operator's `remote.hub.url` or
    `[remote "hub"]` line would otherwise answer whether a test's checkout
    configures its canonical remote. A test that needs a global line
    writes it into the returned file."""
    global_config = tmp_path / "global.gitconfig"
    global_config.touch()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    return global_config
