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
from datetime import UTC, datetime
from enum import Enum
from functools import cache
from pathlib import Path
from typing import TextIO

import pytest
from board_fixtures import BASE, REPOSITORY, complete_contract, write_repository_config

from aco import (
    board_read,
    checkout,
    cli,
    cmd_brief,
    cmd_cut,
    cmd_reset,
    cmd_status,
    forge,
    github,
    process,
    session,
    store,
    workboard,
)
from aco.protocol import ClaimState
from aco.session import RunContext

# Captured at import, before any test's stub replaces it.
_REAL_PATH_IS_TRACKED = checkout.path_is_tracked


FROZEN_CLI_NOW = datetime(2026, 8, 21, tzinfo=UTC)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromtimestamp(FROZEN_CLI_NOW.timestamp(), tz=UTC)


def freeze_cli_now(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin CLI dates without installing a global autouse fixture."""
    for owner in (board_read, cmd_reset, cmd_status, cmd_brief, cmd_cut):
        monkeypatch.setattr(owner, "datetime", FixedDateTime)
    real_run_context = session.run_context

    def frozen_run_context(repo: forge.RepositoryId | None) -> RunContext:
        context = real_run_context(repo)
        context.today = FROZEN_CLI_NOW.date
        return context

    monkeypatch.setattr(session, "run_context", frozen_run_context)


def stub_one_git_call(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    *,
    exit_status: int,
    stderr: str,
    directory: Path | None = None,
) -> list[list[str]]:
    """Force exactly one `checkout._git_run` argv -- in `directory` only,
    when given -- to a chosen failure exit,
    every other call reaching the real launcher -- shared by
    checkout and CLI test families: a git-level failure
    (an unreachable remote, a colliding worktree path, an unmerged branch
    `git branch -d` itself refuses, ...) is cheaper to force this way than
    to reproduce with real git state.

    Returns the calls it answered: a test asserts it is non-empty, because
    a read that never reaches `_git_run` would otherwise pass without the
    injection ever firing."""
    real_git_run = checkout._git_run
    stubbed_directory = directory
    answered: list[list[str]] = []

    def fake(
        call_arguments: list[str], *, directory: Path | None = None, **options: bool
    ) -> process.CapturedResult:
        if call_arguments == arguments and stubbed_directory in (None, directory):
            answered.append(list(call_arguments))
            return process.CapturedResult(exit_status, b"", stderr.encode())
        return real_git_run(call_arguments, directory=directory, **options)

    monkeypatch.setattr(checkout, "_git_run", fake)
    return answered


def fail_git_launch(
    monkeypatch: pytest.MonkeyPatch, leading_arguments: list[str], failure: Exception
) -> list[list[str]]:
    """Record matching Git launches and raise the supplied boundary failure;
    the list is empty when none matched (see `stub_one_git_call`)."""
    run_git = process.run_git
    matched: list[list[str]] = []

    def fail(
        arguments: list[str], *, directory: Path | None = None, **options: bool
    ) -> process.CapturedResult:
        if arguments[: len(leading_arguments)] == leading_arguments:
            matched.append(list(arguments))
            raise failure
        return run_git(arguments, directory=directory, **options)

    monkeypatch.setattr(process, "run_git", fail)
    return matched


def inject_exit_128(monkeypatch: pytest.MonkeyPatch, arguments: list[str]) -> list[list[str]]:
    return stub_one_git_call(monkeypatch, arguments, exit_status=128, stderr="fatal: broken")


def inject_launch_failure(monkeypatch: pytest.MonkeyPatch, arguments: list[str]) -> list[list[str]]:
    return fail_git_launch(monkeypatch, arguments, OSError("denied"))


def inject_timeout(monkeypatch: pytest.MonkeyPatch, arguments: list[str]) -> list[list[str]]:
    return fail_git_launch(monkeypatch, arguments, process.ProcessTimedOutError("slow"))


GIT_FAILURE_INJECTIONS = [
    pytest.param(inject_exit_128, "fatal: broken", id="exit-128"),
    pytest.param(inject_launch_failure, "git failed to launch: denied", id="launch-failure"),
    pytest.param(inject_timeout, "git rev-parse timed out", id="timeout"),
]
"""Each way a git read can fail, with the detail every refusal carries:
`(inject(monkeypatch, arguments), detail)`, `inject` returning the calls it
answered. The timeout detail names `rev-parse`: use these for its reads."""


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
    directory git ran in: a count at the launcher sees every
    trunk reader, whichever function asked."""
    watched = {("fetch", remote): "fetch", recorded_head_read(remote): "recorded head"}
    calls: list[tuple[str, Path]] = []
    launch = checkout._git_run

    def counting(
        arguments: list[str], *, directory: Path | None = None, **options: bool
    ) -> process.CapturedResult:
        kind = watched.get(tuple(arguments))
        if kind is not None:
            calls.append((kind, (directory or Path.cwd()).resolve()))
        return launch(arguments, directory=directory, **options)

    monkeypatch.setattr(checkout, "_git_run", counting)
    return calls


def landed_from_another_clone(tmp_path: Path, *git_step: str) -> str:
    """The tip a second clone of `tmp_path`'s bare `remote.git`
    (`real_repository_with_bare_remote`) pushes to its `main` after running
    `git_step` -- a commit or a merge -- so a checkout that has not fetched
    since stands behind the remote."""
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
    configured: no proxy, no operator repository, git
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


def local_branches(clone: Path) -> frozenset[str]:
    return frozenset(
        real_git(
            clone, "for-each-ref", "--format=%(refname:short)", "refs/heads"
        ).stdout.splitlines()
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
    and `test_cli.py`'s own real-repository proofs), instead
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
    `user.email` at all. Modules may wrap this in an autouse fixture;
    `clone` calls it directly before creating any commit."""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


def without_git_identity(monkeypatch: pytest.MonkeyPatch, checkout_path: Path) -> None:
    """`checkout_path` with no git identity git may use or guess: none
    configured locally, in the environment or the system configuration (the
    caller isolates the global configuration)."""
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    real_git(checkout_path, "config", "user.useConfigOnly", "true")
    real_git(checkout_path, "config", "--unset-all", "user.name", check=False)
    real_git(checkout_path, "config", "--unset-all", "user.email", check=False)
    for variable in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "EMAIL",
    ):
        monkeypatch.delenv(variable, raising=False)


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


def track_board_config(repo: Path, text: str) -> None:
    config = repo / workboard.CONFIG_PATH
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(text)
    real_git(repo, "add", str(workboard.CONFIG_PATH))
    real_git(repo, "commit", "-q", "-m", "track board configuration")


@pytest.fixture
def clone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    bare_remote: Path,
    isolated_global_git_config: Path,
) -> Path:
    """The spec world: tracked config, pushed main, and an isolated identity."""
    set_git_identity(monkeypatch)
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Ada"})
    repo = tmp_path / "clone"
    repo.mkdir()
    real_git(repo, "init", "-q", "-b", "main")
    real_git(repo, "remote", "add", "origin", str(bare_remote))
    track_board_config(repo, "")
    push_repository_trunk(repo, "origin")
    redirect_toplevel(monkeypatch, repo)
    monkeypatch.chdir(repo)
    return repo


GITHUB_REMOTE_URL = "git@github.com:example/agent-coordination.git"


def configure_github_remote(clone: Path, bare_remote: Path) -> None:
    """Route GitHub discovery's remote through the scenario's local bare repository."""
    real_git(clone, "config", f"url.{bare_remote}.insteadOf", GITHUB_REMOTE_URL)
    real_git(clone, "remote", "set-url", "origin", GITHUB_REMOTE_URL)


@pytest.fixture
def github_clone(clone: Path, bare_remote: Path) -> Path:
    """Real GitHub discovery with all git transport routed to the local bare remote."""
    configure_github_remote(clone, bare_remote)
    return clone


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
    fixture repeats once its own commits are built."""
    real_git(repo, "push", "-q", remote_name, "main")
    real_git(repo, "remote", "set-head", remote_name, "main")


@pytest.fixture
def empty_checkout(tmp_path: Path) -> Path:
    """`tmp_path` as a repository with no commit and no remote, the toplevel
    a command started there resolves."""
    real_git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path


@pytest.fixture
def outside_a_checkout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A working directory no git repository holds, answered by the real
    `git rev-parse --show-toplevel` in git's untranslated words."""
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.chdir(nowhere)
    return nowhere


def push_lane_branch(clone: Path, branch: str) -> str:
    """Publish a nonempty lane commit and return to the trunk checkout."""
    default_branch = real_git(clone, "branch", "--show-current").stdout.strip()
    real_git(clone, "checkout", "-q", "-b", branch)
    (clone / "feature.txt").write_text("lane feature\n")
    real_git(clone, "add", "feature.txt")
    real_git(clone, "commit", "-q", "-m", "lane feature")
    head = real_git(clone, "rev-parse", "HEAD").stdout.strip()
    real_git(clone, "push", "-q", "origin", branch)
    real_git(clone, "checkout", "-q", default_branch)
    return head


def add_lane_worktree(clone: Path, lane: Path, branch: str) -> None:
    """Add the lane checkout and verify its branch and upstream remote."""
    real_git(clone, "worktree", "add", "-q", str(lane), branch)
    real_git(clone, "branch", "--set-upstream-to", f"origin/{branch}", branch)
    observed = (
        real_git(lane, "branch", "--show-current").stdout,
        real_git(clone, "config", f"branch.{branch}.remote").stdout,
    )
    expected = (branch + "\n", "origin\n")
    assert observed == expected


class MainBranchState(Enum):
    ABSENT = "absent"
    REMOTE_LEFTOVER = "remote-leftover"


def move_trunk(clone: Path, remote: Path, *, main_state: MainBranchState) -> None:
    """Rename the default branch, retaining main remotely only for a deliberate decoy."""
    tip = real_git(clone, "rev-parse", "main").stdout
    real_git(clone, "branch", "-m", "main", "trunk")
    real_git(clone, "push", "-q", "origin", "trunk")
    real_git(remote, "symbolic-ref", "HEAD", "refs/heads/trunk")
    real_git(clone, "remote", "set-head", "origin", "trunk")
    if main_state is MainBranchState.ABSENT:
        real_git(clone, "push", "-q", "origin", "--delete", "main")
    observed = (
        real_git(remote, "symbolic-ref", "HEAD").stdout,
        real_git(clone, "symbolic-ref", "refs/remotes/origin/HEAD").stdout,
        real_git(clone, "branch", "--show-current").stdout,
        real_git(
            clone, "show-ref", "--verify", "--quiet", "refs/heads/main", check=False
        ).returncode,
        real_git(
            remote, "show-ref", "--verify", "--quiet", "refs/heads/main", check=False
        ).returncode,
    )
    expected = (
        "refs/heads/trunk\n",
        "refs/remotes/origin/trunk\n",
        "trunk\n",
        1,
        1 if main_state is MainBranchState.ABSENT else 0,
    )
    assert observed == expected
    if main_state is MainBranchState.REMOTE_LEFTOVER:
        observed = (
            real_git(remote, "rev-parse", "main").stdout,
            real_git(remote, "rev-parse", "trunk").stdout,
        )
        expected = (tip, tip)
        assert observed == expected


def dangle_recorded_head(repo: Path, remote_name: str) -> None:
    """`<remote_name>/HEAD` left naming `master` once the remote renamed
    that branch `main` and `<remote_name>/master` is gone from `repo`:
    the recorded `HEAD` dangles, while `<remote_name>/main`
    stands at `repo`'s `main`."""
    real_git(repo, "push", "-q", remote_name, "main", "main:master")
    real_git(repo, "remote", "set-head", remote_name, "master")
    real_git(repo, "push", "-q", "--delete", remote_name, "master")


def stub_board_config_tracked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every store-command test reads a tracked `board.toml` by default,
    whichever of `test_cli.py`'s faked worktree or `test_store.py`'s real
    scratch checkout it runs against -- neither `git add`s the file, so a real
    `git ls-files` check would read "not tracked". The untracked/ignored
    refusal is proven by `checkout.path_is_tracked`'s own tests in
    `test_checkout.py` and by `test_cli.py`'s
    `test_an_untrusted_board_config_refuses_every_store_command_by_name`, which
    overrides this stub back to `False`. Each caller wraps this in its own
    `@pytest.fixture(autouse=True)` (matching `conftest.py`'s "everything but
    isolation stays local to its test module"). Only the index
    question is stubbed: whether a revision's tree holds a file stays with the
    real helper, so a test's faked `ls-tree` answer or real repository decides it."""

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
    proving a remote with no URL configured restores
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
        ("rev-parse", "--verify", "--quiet", "HEAD"): head,
        ("rev-parse", "--show-toplevel"): toplevel,
        ("branch", "--show-current"): branch,
        ("rev-parse", "--git-dir"): git_directory,
        ("rev-parse", "--git-common-dir"): common_directory,
        # `resolve_path_checkout`'s one combined call: the same
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


def hub_canonical_worktree_file(
    tmp_path: Path, *, canonical: str, canonical_head: str | None, branch: str
) -> Path:
    """A file in a linked worktree on `branch` of a repository with the
    remotes `origin` and `hub` whose tracked `board.toml` makes `canonical`
    canonical, with `origin/HEAD` naming `main` and `<canonical>/HEAD` naming
    `canonical_head` -- or never recorded. A recorded `HEAD` of a canonical
    remote the repository never configured is one a removed remote left behind."""
    main = tmp_path / "repo"
    main.mkdir()
    real_git(main, "init", "-q", "-b", "main")
    real_git(main, "config", "user.name", "Test")
    real_git(main, "config", "user.email", "test@example.com")
    write_repository_config(main, f'canonical_remote = "{canonical}"\n')
    real_git(main, "add", "-f", workboard.CONFIG_PATH.as_posix())
    real_git(main, "commit", "-q", "-m", "initial")
    real_git(main, "branch", "trunk")
    for remote in ("origin", "hub"):
        real_git(main, "remote", "add", remote, f"https://example.invalid/{remote}/repo.git")
        real_git(main, "update-ref", f"refs/remotes/{remote}/main", "HEAD")
        real_git(main, "update-ref", f"refs/remotes/{remote}/trunk", "HEAD")
    real_git(main, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    if canonical_head is not None:
        recorded = f"refs/remotes/{canonical}/{canonical_head}"
        real_git(main, "update-ref", recorded, "HEAD")
        real_git(main, "symbolic-ref", f"refs/remotes/{canonical}/HEAD", recorded)
    worktree = tmp_path / "repo-worktrees" / "lane"
    worktree.parent.mkdir()
    real_git(main, "worktree", "add", "-q", str(worktree), "-B", branch)
    return worktree / "widget.py"


def store_must_not_be_read(*, worktree: Path, remote: str) -> ClaimState:
    raise AssertionError(f"store read for {worktree} on {remote}")


def _forbid_remote_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def unused(remote: str, **_kwargs: object) -> str:
        pytest.fail("a forge-free command must never read a remote's own URL")

    monkeypatch.setattr(checkout, "remote_url", unused)


def forbid_forge_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_github_construction(monkeypatch)
    _forbid_remote_url(monkeypatch)


ADOPTED_PULL_REQUEST = 45
ADOPTED_BRANCH = "dependabot/uv/x"


def dependabot_pull_request(head_sha: str) -> forge.Landing:
    """Open pull request #45 of `REPOSITORY` from the bot's own branch, aimed
    at `main` and carrying no classification line, whose head is `head_sha`."""
    return forge.Landing(
        number=ADOPTED_PULL_REQUEST,
        author="app/dependabot",
        body="Bump x",
        source_repository=github.repository_id(REPOSITORY),
        source_branch=ADOPTED_BRANCH,
        target_branch="main",
        merged=False,
        merge_commit=None,
        title="Bump x",
        head_sha=head_sha,
    )


def pull_request_listing(
    head_sha: str, *files: forge.ChangedFile, reported: int | None = None
) -> forge.PullRequestChanges:
    """What the forge lists for a pull request at `head_sha`, twice the same;
    `reported` is the file count it claims when that is not `len(files)`."""
    reading = forge.ListingReading(head_sha, len(files) if reported is None else reported)
    return forge.PullRequestChanges(reading, reading, files)


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


def run_cli(
    argv: list[str], capsys: pytest.CaptureFixture[str], *, stdin: str | bytes | None = None
) -> CliRun:
    """Run `argv` through `main`, whether it returns its exit status or
    argparse exits with it, and drain everything printed since the last run.

    Strings are encoded as UTF-8; bytes are piped unchanged. None inherits stdin.
    The previous stdin is restored and the pipe closed even when main raises.
    """
    previous_stdin = sys.stdin
    pipe = read_end_of_a_pipe_carrying(stdin) if stdin is not None else None
    if pipe is not None:
        sys.stdin = pipe
    try:
        status = cli.main(argv)
    except SystemExit as exit_request:
        status = exit_request.code
    finally:
        if pipe is not None:
            sys.stdin = previous_stdin
            pipe.close()
    captured = capsys.readouterr()
    return CliRun(status, captured.out, captured.err)


CountedReads = tuple[dict[Path | None, int], dict[Path | None, int], dict[Path, int]]


@dataclass
class ContextReads:
    """Every toplevel and board-configuration read one command made, keyed
    by the directory it was read from, and every observation of
    `refs/aco/state`, a transition's own included, keyed by the worktree it
    was fetched into."""

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
    transition's own included, through whatever git and store
    fakes the test already installed, so it is called after the arrangement
    and before the command."""
    reads = ContextReads()
    git_output = checkout.git_output
    path_is_tracked = checkout.path_is_tracked
    fetch_state = store.fetch_state

    def counting_fetch_state(*, worktree: Path, remote: str) -> ClaimState:
        reads.observations[worktree] += 1
        return fetch_state(worktree=worktree, remote=remote)

    def counting_git_output(
        arguments: list[str], *, directory: Path | None = None, **options: bool
    ) -> str:
        if arguments[0] == "rev-parse" and "--show-toplevel" in arguments:
            reads.toplevels[directory] += 1
        return git_output(arguments, directory=directory, **options)

    def counting_path_is_tracked(
        path: str, *, directory: Path | None = None, revision: str | None = None
    ) -> bool:
        if path == workboard.CONFIG_PATH.as_posix():
            reads.configs[directory] += 1
        return path_is_tracked(path, directory=directory, revision=revision)

    monkeypatch.setattr(checkout, "git_output", counting_git_output)
    monkeypatch.setattr(checkout, "path_is_tracked", counting_path_is_tracked)
    monkeypatch.setattr(store, "fetch_state", counting_fetch_state)
    return reads


def fresh_observation(worktree: Path, remote: Path | str) -> store.Observation:
    """`worktree`'s own fresh read of the state ref over `remote`, the
    observation a command hands its transition."""
    return store.Observation(
        worktree, str(remote), store.fetch_state(worktree=worktree, remote=str(remote))
    )


# Captured at import, before `_stub_trunk` replaces them.
LIVE_TRUNK_REF_AFTER = checkout.trunk_ref_after
LIVE_FETCH_REMOTE = checkout.fetch_remote

ITEM_NEW_BODY = complete_contract("Ship it.")


def redirect_toplevel(monkeypatch: pytest.MonkeyPatch, toplevel: Path) -> None:
    """Stand in `toplevel`, a real repository this test built, so `RunContext.toplevel`
    (`rev-parse --show-toplevel`) names it. Every git call, including `start`'s
    worktree creation, reaches real git, and the trunk is resolved and fetched
    for real, undoing `test_cli.py`'s autouse `_stub_trunk`."""
    monkeypatch.chdir(toplevel)
    monkeypatch.setattr(checkout, "trunk_ref_after", LIVE_TRUNK_REF_AFTER)
    monkeypatch.setattr(checkout, "fetch_remote", LIVE_FETCH_REMOTE)


def arguments_bash_hands_aco(advice: str, tmp_path: Path) -> tuple[int, list[str]]:
    """Bash's exit code and the argv it hands `aco` when the printed
    `advice` command runs verbatim in a throwaway git repository, `aco`
    standing in as a recorder of its own arguments -- so the caller runs
    exactly those arguments through the real entry point. A
    scenario may run several pieces of advice in turn."""
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


def read_end_of_a_pipe_carrying(text: str | bytes) -> TextIO:
    """`printf ... | aco ...`: the read end of a pipe whose writer already
    wrote `text` -- a scenario body, well inside a pipe's buffer -- and
    closed. Read as `sys.stdin` reads a pipe: line endings untranslated."""
    read_end, write_end = os.pipe()
    with os.fdopen(write_end, "wb") as writer:
        writer.write(text.encode("utf-8") if isinstance(text, str) else text)
    return os.fdopen(read_end, encoding="utf-8", newline="")


def piping(text: str) -> Callable[[Path], contextlib.AbstractContextManager[TextIO]]:
    """A stdin source piping `text`, for a family whose cases each set their
    own stdin."""

    @contextlib.contextmanager
    def piped(_tmp_path: Path) -> Iterator[TextIO]:
        with read_end_of_a_pipe_carrying(text) as stdin:
            yield stdin

    return piped


piped_body_on_stdin = piping(ITEM_NEW_BODY)


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
