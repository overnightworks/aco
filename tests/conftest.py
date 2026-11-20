"""Shared test isolation.

Only isolation fixtures live here -- the autouse ones and the isolation more
than one module asks for by name -- plus `git_call_spy`, the git call counter two store
modules share, and `github_world`, the GitHub-checkout
world check many modules share; everything else stays local to its test
module. The one exception is registration: `cli_fixtures`, `adoption_world`,
`release_cleanup_world`, `check_pull_request_fixtures`, `lane_record_runs_world`,
`discovery_fixtures`, `wait_fixtures` and `audit_world` are loaded as pytest plugins
(`pytest_plugins` below).
`cli_fixtures` gives every test module its `bare_remote` and `worktree` fixtures
by name, and its autouse `_isolate_agent_identity` applies to every test;
`adoption_world` gives every module its `world` fixture, and
`release_cleanup_world` gives the release cleanup modules their `cleanup_check`;
`check_pull_request_fixtures` gives the `aco check <pr>` tests their `check_pull_request`;
`lane_record_runs_world` gives the `aco lane-record begin` and `add` tests their world;
`discovery_fixtures` gives the modules that run aco over a configured root their
`config_file`, `root` and `here`; `wait_fixtures` gives the `aco wait` board tests their
`frozen_wait_world`.
"""

from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest

from aco import process, store

# Registers `cli_fixtures` (`bare_remote`, `worktree`, the autouse identity
# isolation), `adoption_world` (`world`) and `release_cleanup_world`
# (`cleanup_check`) for every module by name: an import
# of a fixture only to receive it as a parameter reads as unused to ruff.
pytest_plugins = [
    "cli_fixtures",
    "adoption_world",
    "release_cleanup_world",
    "check_pull_request_fixtures",
    "lane_record_runs_world",
    "discovery_fixtures",
    "wait_fixtures",
    "audit_world",
]


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


@pytest.fixture(autouse=True)
def _isolate_state_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """aco's state directory (item locks, the board token) is the test's own,
    never the operator's."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


@pytest.fixture
def git_call_spy(monkeypatch: pytest.MonkeyPatch) -> Counter[str]:
    """Counts real git subprocess invocations by subcommand, patched at the
    `process` chokepoint both of `store`'s call shapes go through --
    `run_git` (`process.run_captured`) and `_run_git_with_input`
    (`process.run_bounded_captured`) -- the proof that a transition's or a read's
    git-invocation count is independent of how many claims the state tree
    holds.
    """
    counts: Counter[str] = Counter()

    def record(command: list[str]) -> None:
        if command[0] == "git":
            counts[command[3]] += 1

    def spy(real: Callable[..., object]) -> Callable[..., object]:
        def wrapped(command: list[str], **kwargs: object) -> object:
            record(command)
            return real(command, **kwargs)

        return wrapped

    monkeypatch.setattr(store.process, "run_captured", spy(process.run_captured))
    monkeypatch.setattr(store.process, "run_bounded_captured", spy(process.run_bounded_captured))
    return counts
