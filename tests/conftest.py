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

# Registers `bare_remote` and `worktree` for every module by name: an import
# of a fixture only to receive it as a parameter reads as unused to ruff.
pytest_plugins = ["cli_fixtures"]


@pytest.fixture(autouse=True)
def _start_outside_every_checkout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every test starts in its own empty directory. A command started from the
    checkout pytest runs in reads and writes that checkout's board
    configuration, remotes and object store, so a test that needs a checkout
    builds one and stands in it."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def isolated_global_git_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Real git reads an empty global configuration, never the operator's
    own: an operator's `remote.hub.url` or
    `[remote "hub"]` line would otherwise answer whether a test's checkout
    configures its canonical remote. A test that needs a global line
    writes it into the returned file."""
    global_config = tmp_path / "global.gitconfig"
    global_config.touch()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    return global_config


@pytest.fixture
def github_world(github_clone: Path, bare_remote: Path) -> Path:
    """The checkout and bare remote of a GitHub-hosted board, asserted to be
    a consistent world; a module that only needs the check ignores the path."""
    # Imported here: at module level it would import `cli_fixtures` before the
    # plugin registration above rewrites its asserts.
    from github_fixtures import assert_github_world  # noqa: PLC0415

    assert_github_world(github_clone, bare_remote)
    return github_clone
