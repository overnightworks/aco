"""CLI-boundary scaffolding: real and faked git process helpers, agent-identity
environment setup, stdin sources, pipe helpers, and boundary-forbid helpers."""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import TextIO

import pytest
from board_fixtures import BASE, complete_contract

from agent_coordination import board, checkout, cli, forge, github, process, store
from agent_coordination.protocol import ClaimState
from agent_coordination.session import RunContext

# Captured at import, before any test's stub replaces it.
_REAL_PATH_IS_TRACKED = checkout.path_is_tracked


def stub_one_git_call(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str], *, exit_status: int, stderr: str
) -> None:
    """Force exactly one `checkout._git_run` argv to a chosen failure exit,
    every other call reaching the real launcher -- shared by
    `test_checkout.py` and `test_cli.py` (issue #322): a git-level failure
    (an unreachable remote, a colliding worktree path, an unmerged branch
    `git branch -d` itself refuses, ...) is cheaper to force this way than
    to reproduce with real git state."""
    real_git_run = checkout._git_run

    def fake(call_arguments: list[str], *, directory: Path | None = None) -> process.CapturedResult:
        if call_arguments == arguments:
            return process.CapturedResult(exit_status, b"", stderr.encode())
        return real_git_run(call_arguments, directory=directory)

    monkeypatch.setattr(checkout, "_git_run", fake)


def recorded_head_read(remote: str) -> tuple[str, ...]:
    """The one git read `checkout.recorded_head_ref` sends for `remote`: a
    fake keyed by it answers every reader of that remote's recorded `HEAD`."""
    return (
        "rev-parse",
        "--verify",
        "--quiet",
        "--symbolic-full-name",
        f"refs/remotes/{remote}/HEAD",
    )


RECORDED_ORIGIN_HEAD_READ = recorded_head_read("origin")


def trunk_git_calls(monkeypatch: pytest.MonkeyPatch, remote: str) -> list[tuple[str, Path]]:
    """Every `fetch <remote>` and every read of `<remote>`'s recorded `HEAD`
    the one git launcher runs from here on, in order, each keyed by the
    directory git ran in (issue #488): a count at the launcher sees every
    trunk reader, whichever function asked."""
    watched = {("fetch", remote): "fetch", recorded_head_read(remote): "recorded head"}
    calls: list[tuple[str, Path]] = []
    launch = checkout._git_run

    def counting(arguments: list[str], *, directory: Path | None = None) -> process.CapturedResult:
        kind = watched.get(tuple(arguments))
        if kind is not None:
            calls.append((kind, (directory or Path.cwd()).resolve()))
        return launch(arguments, directory=directory)

    monkeypatch.setattr(checkout, "_git_run", counting)
    return calls


def landed_from_another_clone(tmp_path: Path, *git_step: str) -> str:
    """The tip a second clone of `tmp_path`'s bare `remote.git`
    (`real_repository_with_bare_remote`) pushes to its `main` after running
    `git_step` -- a commit or a merge -- so a checkout that has not fetched
    since stands behind the remote (issue #488)."""
    other = tmp_path / "other"
    real_git(tmp_path, "clone", "-q", str(tmp_path / "remote.git"), str(other))
    real_git(other, "config", "user.name", "Other")
    real_git(other, "config", "user.email", "other@example.com")
    real_git(other, "config", "commit.gpgsign", "false")
    real_git(other, *git_step)
    real_git(other, "push", "-q", "origin", "HEAD:main")
    return real_git(other, "rev-parse", "HEAD").stdout.strip()


def fetched_once_then_read(calls: list[tuple[str, Path]]) -> dict[Path, bool]:
    """Per directory that fetched in `calls` (`trunk_git_calls`): whether it
    fetched exactly once and read the recorded `HEAD` after that fetch."""
    fetched = {directory for kind, directory in calls if kind == "fetch"}
    return {
        directory: calls.count(("fetch", directory)) == 1
        and ("recorded head", directory) in calls[calls.index(("fetch", directory)) :]
        for directory in fetched
    }


_OPERATOR_GIT_ROUTES = ("GIT_PROXY_COMMAND", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_SSH_VARIANT")


@cache
def _repository_selecting_git_variables() -> frozenset[str]:
    """Git's own list of the variables that select a repository (`GIT_DIR`,
    `GIT_WORK_TREE`, ...), whose local configuration could rewrite a URL or
    set a proxy."""
    local_variables = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True, check=True
    )
    return frozenset(local_variables.stdout.split())


def sealed_git_environment() -> dict[str, str]:
    """The inherited environment without any route or seed the operator
    configured (#530, #534): no proxy, no operator repository, git
    configuration or template, and an ssh that reads no config file, so a
    remote a test names is the remote git dials and a repository it
    initializes carries no operator hook or URL rewrite."""
    operator_git_variables = _repository_selecting_git_variables() | set(_OPERATOR_GIT_ROUTES)
    inherited = {
        name: value
        for name, value in os.environ.items()
        if not name.lower().endswith("_proxy")
        and not name.startswith("GIT_CONFIG")
        and name not in operator_git_variables
    }
    return inherited | {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_SSH_COMMAND": f"ssh -F {os.devnull} -o BatchMode=yes",
        # An empty value is git's empty template, which `init.templateDir` cannot override.
        "GIT_TEMPLATE_DIR": "",
        "LC_ALL": "C",
    }


def real_git(
    repository: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        env=sealed_git_environment(),
        check=check,
        capture_output=True,
        text=True,
    )


def worktrees_and_branches(repository: Path) -> tuple[str, str]:
    return (
        real_git(repository, "worktree", "list", "--porcelain").stdout,
        real_git(repository, "branch", "--list").stdout,
    )


def init_bare_repository(path: Path) -> Path:
    """A real bare repository on `main` at `path`; a path another builder
    already took fails loudly instead of sharing its remote."""
    path.mkdir()
    real_git(path, "init", "-q", "--bare", "-b", "main")
    return path


def real_repository_with_bare_remote(
    tmp_path: Path, *, remote_name: str = "origin"
) -> tuple[Path, Path]:
    """A real `git init`-ed worktree, commit identity configured, with a
    real bare `remote_name` remote pointing at a sibling bare repository --
    the one raw-git skeleton every trunk-history or trailer-classification
    fixture in this suite builds its own commits onto (`test_checkout.py`'s
    and `test_cli.py`'s own real-repository proofs, issue #359 CI), instead
    of each hand-rolling the same `init`/`config`/`remote add` sequence."""
    remote = init_bare_repository(tmp_path / "remote.git")
    repo = tmp_path / "repo"
    repo.mkdir()
    real_git(repo, "init", "-q", "-b", "main")
    real_git(repo, "config", "user.name", "Test")
    real_git(repo, "config", "user.email", "test@example.com")
    real_git(repo, "config", "commit.gpgsign", "false")
    real_git(repo, "remote", "add", remote_name, str(remote))
    return repo, remote


def bare_remote_repository_with_one_commit(tmp_path: Path) -> Path:
    """`real_repository_with_bare_remote`'s worktree with one `base.txt`
    commit on `main`, pushed to `origin` with `origin/HEAD` resolved."""
    repo, _remote = real_repository_with_bare_remote(tmp_path)
    (repo / "base.txt").write_text("base\n")
    real_git(repo, "add", "base.txt")
    real_git(repo, "commit", "-q", "-m", "initial")
    push_repository_trunk(repo, "origin")
    return repo


def set_git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """A commit identity for every git subprocess a test spawns, including
    the ones the code under test runs (they inherit the process environment,
    never overriding it) -- this machine may carry no git `user.name` or
    `user.email` at all. Each caller wraps this in its own
    `@pytest.fixture(autouse=True)`, like `stub_board_config_tracked`."""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


def head_sha(repository: Path) -> str:
    return real_git(repository, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """An empty bare repository standing in for the canonical remote.

    `maintenance.auto=false` keeps `receive-pack` from starting maintenance
    here, so a client-side maintenance assertion sees only its own fetch."""
    remote = init_bare_repository(tmp_path / "remote.git")
    real_git(remote, "config", "maintenance.auto", "false")
    return remote


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """An ordinary git checkout used as this test's client worktree, its
    commit made under the identity `set_git_identity` set.

    Independent of `bare_remote`: store operations reach the remote by path,
    never by a configured `origin`, so this repo's own history is unrelated
    to the state ref it reads and writes.
    """
    checkout = tmp_path / "worktree"
    checkout.mkdir()
    real_git(checkout, "init", "-b", "main")
    (checkout / "README").write_text("placeholder\n")
    real_git(checkout, "add", "README")
    real_git(checkout, "commit", "-m", "initial")
    return checkout


def push_repository_trunk(repo: Path, remote_name: str) -> None:
    """`repo`'s current `main` pushed to `remote_name`, with `<remote_name>/HEAD`
    resolved -- the trailing half of the skeleton every trunk-history
    fixture repeats once its own commits are built (issue #359 CI)."""
    real_git(repo, "push", "-q", remote_name, "main")
    real_git(repo, "remote", "set-head", remote_name, "main")


def dangle_recorded_head(repo: Path, remote_name: str) -> None:
    """`<remote_name>/HEAD` left naming `master` once the remote renamed
    that branch `main` and `<remote_name>/master` is gone from `repo`
    (issue #490): the recorded `HEAD` dangles, while `<remote_name>/main`
    stands at `repo`'s `main`."""
    real_git(repo, "push", "-q", remote_name, "main", "main:master")
    real_git(repo, "remote", "set-head", remote_name, "master")
    real_git(repo, "push", "-q", "--delete", remote_name, "master")


def stub_board_config_tracked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every store-command test reads a tracked `board.toml` by default
    (issue #315), whichever of `test_cli.py`'s faked worktree, `test_protect.py`'s
    non-git `_isolate_protect_home` directory, or `test_store.py`'s real
    scratch checkout it runs against -- none of them actually `git add`s the
    file, so a real `git ls-files` check would otherwise always read "not
    tracked" here. The untracked/ignored refusal is its own axis, proven by
    `checkout.path_is_tracked`'s own tests in `test_checkout.py` and by
    `test_cli.py`'s `test_an_untrusted_board_config_refuses_every_store_command_by_name`,
    which overrides this stub back to `False`. Each caller wraps this in its
    own `@pytest.fixture(autouse=True)` (never placed here itself, matching
    `conftest.py`'s "everything but git-toplevel isolation stays local to its
    test module") so every test file states in its own body that it reads a
    tracked board.toml by default. Only that index question is stubbed:
    whether a revision's tree holds a file (the trunk's committed
    `lane_shared`, issue #575) stays with the real helper, so a test's faked
    `ls-tree` answer or its real repository decides it."""

    def tracked_in_the_index(
        path: str, *, directory: Path | None = None, revision: str | None = None
    ) -> bool:
        if revision is None:
            return True
        return _REAL_PATH_IS_TRACKED(path, directory=directory, revision=revision)

    monkeypatch.setattr(checkout, "path_is_tracked", tracked_in_the_index)


def stub_every_remote_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """An in-memory store's checkout configures whichever canonical remote
    its board names, the way its faked URL stands for that remote. A test
    proving a remote with no URL configured (issues #508, #516) restores
    `checkout.unconfigured_remote_refusal`, so real git answers it."""
    monkeypatch.setattr(checkout, "unconfigured_remote_refusal", lambda _remote, **_kwargs: None)


def git_checkout(
    *,
    toplevel: str = "/repo",
    head: str = BASE,
    branch: str = "codex/issue-72",
    git_directory: str = "/repo/.git/worktrees/issue-72",
    common_directory: str = "/repo/.git",
    dirty: str = "",
) -> dict[tuple[str, ...], str]:
    return {
        ("rev-parse", "HEAD"): head,
        ("rev-parse", "--verify", "HEAD"): head,
        ("rev-parse", "--show-toplevel"): toplevel,
        ("branch", "--show-current"): branch,
        ("rev-parse", "--git-dir"): git_directory,
        ("rev-parse", "--git-common-dir"): common_directory,
        # `resolve_path_checkout`'s one combined call (issue #314): the same
        # three facts above, in the order it requests them via
        # `-C`/`--path-format=absolute`, so `rescope`'s path-based checkout
        # resolution reads the identical fixture the separate keys above
        # already describe.
        (
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
            "--git-dir",
            "--git-common-dir",
        ): "\n".join((toplevel, git_directory, common_directory)),
        ("status", "--porcelain"): dirty,
        RECORDED_ORIGIN_HEAD_READ: "refs/remotes/origin/main",
    }


AGENT_IDENTITY_ENV_NAMES = (
    checkout.ACO_AGENT_ENV,
    checkout.GROK_SESSION_ID_ENV,
    checkout.CLAUDE_CODE_SESSION_ID_ENV,
)


@pytest.fixture(autouse=True)
def _isolate_agent_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test inherits the session's own agent identity: run inside an agent
    session, a test that omits `--agent` would otherwise resolve to the real
    session's `ACO_AGENT`, `GROK_SESSION_ID` or `CLAUDE_CODE_SESSION_ID`. A
    test that needs an identity sets it itself."""
    for name in AGENT_IDENTITY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def set_agent_identity_env(monkeypatch: pytest.MonkeyPatch, environ: dict[str, str]) -> None:
    """Set the test's agent identity; the autouse `_isolate_agent_identity`
    above has already cleared the session's own."""
    for name, value in environ.items():
        monkeypatch.setenv(name, value)


def forbid_github_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    def unused(*args, **kwargs):
        pytest.fail("agent identity must be resolved before GitHub")

    monkeypatch.setattr(github, "GitHubForge", unused)
    monkeypatch.setattr(github, "discover_repository", unused)


def forbid_git_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    def unused(arguments: list[str]) -> str:
        pytest.fail("agent identity must be resolved before git fill")

    monkeypatch.setattr(checkout, "git_output", unused)


def assert_missing_identity_message(message: str) -> None:
    assert "--agent" in message
    assert checkout.ACO_AGENT_ENV in message
    assert checkout.GROK_SESSION_ID_ENV in message
    assert checkout.CLAUDE_CODE_SESSION_ID_ENV in message
    assert "GROK_AGENT" not in message


def forbid_protect_git_github_and_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    def unused(*args, **kwargs):
        pytest.fail("this protect path must not use identity, git, GitHub, or the store")

    monkeypatch.setattr(checkout, "session_agent", unused)
    monkeypatch.setattr(checkout, "git_output", unused)
    monkeypatch.setattr(github, "GitHubForge", unused)
    monkeypatch.setattr(github, "discover_repository", unused)
    monkeypatch.setattr(store, "fetch_state", unused)


def patch_command(*lines: str) -> str:
    """Wrap Codex's `apply_patch` file-line grammar in its `Begin`/`End Patch`
    envelope, the way `command` actually arrives in the hook payload."""
    return "\n".join(("*** Begin Patch", *lines, "*** End Patch"))


def _forbid_remote_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def unused(remote: str, **_kwargs: object) -> str:
        pytest.fail("a forge-free command must never read a remote's own URL")

    monkeypatch.setattr(checkout, "remote_url", unused)


def forbid_forge_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_github_construction(monkeypatch)
    _forbid_remote_url(monkeypatch)


def arrange_scope_width(
    monkeypatch: pytest.MonkeyPatch,
    client: object,
    *,
    directories: frozenset[str] = frozenset(),
    versioned: tuple[str, ...] | None = None,
    validate_checkout: bool = True,
) -> None:
    """The monkeypatch quadruple every scope-width `claim`/`rescope` case in
    `test_cli.py`'s wide-scope tables shares: a GitHub forge, a directory
    classifier, an optional versioned-file listing, and -- for a fresh
    `claim` -- a no-op checkout validator (`rescope` patches the store and
    git output for its own standing claim instead, so it passes
    `validate_checkout=False`)."""
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(
        checkout,
        "scope_directories",
        lambda paths, **_kwargs: tuple(path for path in paths if path in directories),
    )
    monkeypatch.setattr(checkout, "versioned_paths", lambda **_kwargs: versioned or ())
    if validate_checkout:
        monkeypatch.setattr(checkout, "validate_checkout", lambda request, **_where: None)


def run_context_over(client: forge.ForgeReader) -> RunContext:
    """A cwd-rooted `RunContext` whose forge is `client`: a test driving a
    helper that takes a context reads the same toplevel and tracked
    `board.toml` a command would, with its own fake forge behind them."""
    return RunContext(None, build_forge=lambda _context: client)


@dataclass(frozen=True)
class CliRun:
    """One `main` run: its exit status and everything it printed."""

    status: int | str | None
    stdout: str
    stderr: str

    def expect_success(self) -> str:
        """The stdout of a run that exited 0; a failure shows that stdout."""
        assert self.status == 0, self.stdout
        return self.stdout

    def expect_refusal(self) -> str:
        """The stderr of a run the CLI refused with exit 2; a failure shows
        that stderr."""
        assert self.status == 2, self.stderr
        return self.stderr


def run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> CliRun:
    """Run `argv` through `main`, whether it returns its exit status or
    argparse exits with it, and read back what it printed."""
    try:
        status = cli.main(argv)
    except SystemExit as exit_request:
        status = exit_request.code
    captured = capsys.readouterr()
    return CliRun(status, captured.out, captured.err)


CountedReads = tuple[dict[Path | None, int], dict[Path | None, int], dict[Path, int]]


@dataclass
class ContextReads:
    """Every toplevel and board-configuration read one command made, keyed
    by the directory it was read from (issue #457), and every observation of
    `refs/aco/state`, a transition's own included, keyed by the worktree it
    was fetched into (issues #477, #494)."""

    toplevels: Counter[Path | None] = field(default_factory=Counter)
    configs: Counter[Path | None] = field(default_factory=Counter)
    observations: Counter[Path] = field(default_factory=Counter)

    def drain(self) -> CountedReads:
        """The reads counted since the last drain, forgotten after: one step
        of a longer sequence (a multi-step command such as `land`) counted
        alone."""
        taken = dict(self.toplevels), dict(self.configs), dict(self.observations)
        self.toplevels.clear()
        self.configs.clear()
        self.observations.clear()
        return taken


def count_context_reads(monkeypatch: pytest.MonkeyPatch) -> ContextReads:
    """Counts every `rev-parse` that asks `--show-toplevel` -- alone, or
    combined with other queries as `resolve_path_checkout` asks it -- the
    `board.toml` tracked check, and every `store.fetch_state`, a
    transition's own included (issue #494), through whatever git and store
    fakes the test already installed, so it is called after the arrangement
    and before the command."""
    reads = ContextReads()
    git_output = checkout.git_output
    path_is_tracked = checkout.path_is_tracked
    fetch_state = store.fetch_state

    def counting_fetch_state(*, worktree: Path, remote: str) -> ClaimState:
        reads.observations[worktree] += 1
        return fetch_state(worktree=worktree, remote=remote)

    def counting_git_output(arguments: list[str], *, directory: Path | None = None) -> str:
        if arguments[0] == "rev-parse" and "--show-toplevel" in arguments:
            reads.toplevels[directory] += 1
        return git_output(arguments, directory=directory)

    def counting_path_is_tracked(
        path: str, *, directory: Path | None = None, revision: str | None = None
    ) -> bool:
        if path == board.CONFIG_PATH.as_posix():
            reads.configs[directory] += 1
        return path_is_tracked(path, directory=directory, revision=revision)

    monkeypatch.setattr(checkout, "git_output", counting_git_output)
    monkeypatch.setattr(checkout, "path_is_tracked", counting_path_is_tracked)
    monkeypatch.setattr(store, "fetch_state", counting_fetch_state)
    return reads


def fresh_observation(worktree: Path, remote: Path | str) -> store.Observation:
    """`worktree`'s own fresh read of the state ref over `remote`, the
    observation a command hands its transition (issue #494)."""
    return store.Observation(
        worktree, str(remote), store.fetch_state(worktree=worktree, remote=str(remote))
    )


# Captured at import, before `_stub_trunk` replaces them (issue #488).
LIVE_TRUNK_REF_AFTER = checkout.trunk_ref_after
LIVE_FETCH_REMOTE = checkout.fetch_remote

ITEM_NEW_BODY = complete_contract("Ship it.")


def redirect_toplevel(monkeypatch: pytest.MonkeyPatch, toplevel: Path) -> None:
    """Point `RunContext.toplevel` (`rev-parse --show-toplevel`) at a real
    repository this test built itself (issue #322), taking precedence over
    `conftest.py`'s autouse `_isolate_git_toplevel` fake -- every other real
    git call `start`'s own worktree creation runs still reaches real git,
    unlike a fully faked `checkout.git_output`, and the trunk is resolved
    and fetched for real there, undoing `test_cli.py`'s autouse
    `_stub_trunk` (issue #488)."""
    real_git_output = checkout.git_output

    def fake(arguments: list[str], *, directory: Path | None = None) -> str:
        if arguments == ["rev-parse", "--show-toplevel"] and directory is None:
            return str(toplevel)
        return real_git_output(arguments, directory=directory)

    monkeypatch.setattr(checkout, "git_output", fake)
    monkeypatch.setattr(checkout, "trunk_ref_after", LIVE_TRUNK_REF_AFTER)
    monkeypatch.setattr(checkout, "fetch_remote", LIVE_FETCH_REMOTE)


def arguments_bash_hands_aco(advice: str, tmp_path: Path) -> tuple[int, list[str]]:
    """Bash's exit code and the argv it hands `aco` when the printed
    `advice` command runs verbatim in a throwaway git repository, `aco`
    standing in as a recorder of its own arguments -- so the caller runs
    exactly those arguments through the real entry point (issue #510). A
    scenario may run several pieces of advice in turn (issue #513)."""
    shim_directory = tmp_path / "shell-bin"
    shim_directory.mkdir(exist_ok=True)
    recorder = shim_directory / "aco"
    recorder.write_text("#!/bin/sh\nprintf '%s\\0' \"$@\"\n")
    recorder.chmod(0o755)
    repository = tmp_path / "throwaway"
    repository.mkdir(exist_ok=True)
    real_git(repository, "init", "--quiet")
    environment = {**os.environ, "PATH": f"{shim_directory}{os.pathsep}{os.environ['PATH']}"}
    ran = subprocess.run(
        ["bash", "-c", advice], cwd=repository, env=environment, capture_output=True, check=False
    )
    return ran.returncode, ran.stdout.decode().split("\0")[:-1]


@contextlib.contextmanager
def devnull_on_stdin(_tmp_path: Path) -> Iterator[TextIO]:
    with Path(os.devnull).open() as stdin:
        yield stdin


@contextlib.contextmanager
def body_file_on_stdin(tmp_path: Path) -> Iterator[TextIO]:
    body_file = tmp_path / "body.md"
    body_file.write_text(ITEM_NEW_BODY)
    with body_file.open() as stdin:
        yield stdin


def read_end_of_a_pipe_carrying(text: str) -> TextIO:
    """`printf ... | aco ...`: the read end of a pipe whose writer already
    wrote `text` -- a scenario body, well inside a pipe's buffer -- and
    closed. Read as `sys.stdin` reads a pipe: line endings untranslated."""
    read_end, write_end = os.pipe()
    with os.fdopen(write_end, "w") as writer:
        writer.write(text)
    return os.fdopen(read_end, newline="")


def piping(text: str) -> Callable[[Path], contextlib.AbstractContextManager[TextIO]]:
    """A stdin source piping `text`, for a family whose cases each set their
    own stdin."""

    @contextlib.contextmanager
    def piped(_tmp_path: Path) -> Iterator[TextIO]:
        with read_end_of_a_pipe_carrying(text) as stdin:
            yield stdin

    return piped


piped_body_on_stdin = piping(ITEM_NEW_BODY)


def main_with_piped_stdin(monkeypatch: pytest.MonkeyPatch, text: str, argv: list[str]) -> int:
    """`printf ... | aco <argv>`: one run with `text` on a pipe as its
    stdin, the pipe closed once the run returns."""
    with read_end_of_a_pipe_carrying(text) as stdin:
        monkeypatch.setattr(sys, "stdin", stdin)
        return cli.main(argv)


@contextlib.contextmanager
def terminal_on_stdin(_tmp_path: Path) -> Iterator[TextIO]:
    """A stdin a person types into, holding a line nobody piped."""
    controller, terminal = os.openpty()
    with os.fdopen(controller, "w") as typist, os.fdopen(terminal) as stdin:
        typist.write("never read\n")
        typist.flush()
        yield stdin


@contextlib.contextmanager
def closed_stdin(_tmp_path: Path) -> Iterator[None]:
    """`aco ... <&-`: Python leaves `sys.stdin` as `None`."""
    yield None


@contextlib.contextmanager
def empty_harness_socket_on_stdin(_tmp_path: Path) -> Iterator[TextIO]:
    """The stdin an agent harness such as Claude Code's Bash tool hands a
    command: one end of a socket that never delivers a body."""
    harness_end, other_end = socket.socketpair()
    # The other end stays open, so a read would wait forever; the timeout
    # turns a command that reads this stdin into a failure, not a hang.
    harness_end.settimeout(1)
    with harness_end, other_end, harness_end.makefile("r") as stdin:
        yield stdin
