"""`aco rescope`'s own checkout resolution against real repositories: which
checkout a `--add`/`--drop` path locates, and the sentence each path or
checkout no claim can ever cover is refused with (`specs/rescope.spec.md`).
Also owns the real-repository arrangements these tests build -- linked
worktrees, nested worktrees, and a canonical-remote repository."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from board_fixtures import (
    REPOSITORY,
    complete_contract,
    standing_active_claim,
    write_repository_config,
)
from cli_fixtures import (
    GIT_FAILURE_INJECTIONS,
    hub_canonical_worktree_file,
    init_bare_repository,
    inject_exit_128,
    real_git,
    recorded_head_read,
    set_agent_identity_env,
    store_must_not_be_read,
    stub_one_git_call,
)
from github_fixtures import FakeForge

from aco import body, checkout, forge, github, protocol, store, workboard
from aco import cli as issue_claim


def _real_repository_with_worktree(
    tmp_path: Path,
    *,
    slug: str = "issue-72-widget",
    board_config: str = "",
    trunk_files: tuple[str, ...] = (),
) -> tuple[Path, Path]:
    """A real repository (`main`, reused across worktrees) with one linked,
    isolated worktree on a feature branch -- the same `git worktree add`
    recipe `checkout.ISOLATED_WORKTREE_RECIPE` documents. `main` carries a
    real, tracked (`git add -f`) `.aco/board.toml` holding
    `board_config`, empty by default, beside the `trunk_files` it tracks: every worktree shares
    `main`'s history, so
    `path_is_tracked` reads a real "tracked" answer for it from any of them.
    `main` also carries a real, resolvable `origin/HEAD`: every
    worktree's own feature branch reads a real default-branch name through
    it, rather than refusing "default branch unknown" -- a repository with
    no recorded `origin/HEAD` at all is its own dedicated proof."""
    main = tmp_path / "repo"
    if not main.exists():
        main.mkdir()
        real_git(main, "init", "-q", "-b", "main")
        real_git(main, "config", "user.name", "Test")
        real_git(main, "config", "user.email", "test@example.com")
        (main / "README.md").write_text("hello\n")
        write_repository_config(main, board_config)
        for trunk_file in trunk_files:
            (main / trunk_file).parent.mkdir(parents=True, exist_ok=True)
            (main / trunk_file).write_text("tracked\n")
        real_git(main, "add", "-f", "README.md", workboard.CONFIG_PATH.as_posix(), *trunk_files)
        real_git(main, "commit", "-q", "-m", "initial")
        real_git(main, "remote", "add", "origin", "https://example.invalid/example/repo.git")
        real_git(main, "update-ref", "refs/remotes/origin/main", "HEAD")
        real_git(main, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    worktree = tmp_path / "repo-worktrees" / slug
    worktree.parent.mkdir(parents=True, exist_ok=True)
    real_git(main, "worktree", "add", "-q", str(worktree), "-b", f"codex/{slug}")
    (worktree / "src").mkdir()
    (worktree / "docs").mkdir()
    return main, worktree


def _real_repository_with_nested_worktree(
    tmp_path: Path, *, slug: str = "issue-1-x"
) -> tuple[Path, Path]:
    """A real repository (`outer`) with one linked worktree nested *inside*
    its own working tree (`outer/nested-worktrees/<slug>`), unlike
    `_real_repository_with_worktree`'s sibling layout: the nested root's
    own parent directory sits inside `outer`'s checkout, so `git -C parent`
    resolves to `outer` rather than to nothing -- the shape in which a
    parent-first lookup would let `outer`'s own checkout silently answer for
    a path that is itself a different, nested checkout's own root."""
    outer = tmp_path / "outer-repo"
    outer.mkdir()
    real_git(outer, "init", "-q", "-b", "main")
    real_git(outer, "config", "user.name", "Test")
    real_git(outer, "config", "user.email", "test@example.com")
    (outer / "README.md").write_text("hello\n")
    write_repository_config(outer)
    real_git(outer, "add", "-f", "README.md", workboard.CONFIG_PATH.as_posix())
    real_git(outer, "commit", "-q", "-m", "initial")
    real_git(outer, "remote", "add", "origin", "https://example.invalid/example/repo.git")
    real_git(outer, "update-ref", "refs/remotes/origin/main", "HEAD")
    real_git(outer, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    nested = outer / "nested-worktrees" / slug
    nested.parent.mkdir(parents=True, exist_ok=True)
    real_git(outer, "worktree", "add", "-q", str(nested), "-b", f"codex/{slug}")
    return outer, nested


def _checkout_root_reason(root: Path) -> str:
    return f"{root} is the checkout root itself"


def _hook_in_a_bare_repository(tmp_path: Path) -> Path:
    """The shape of a forge-free canonical remote (README, "A workflow
    without a forge"): a bare repository has no `.git` entry at all, yet a
    path into its hooks is a path in a repository."""
    served = tmp_path / "served.git"
    init_bare_repository(served)
    return served / "hooks" / "pre-receive"


def _path_below_a_file(_main: Path, worktree: Path) -> tuple[Path, str]:
    path = worktree / "README.md" / "x.py"
    return path, f"{path} cannot exist: {worktree / 'README.md'} is a file"


def _path_below_a_dangling_symlink(_main: Path, worktree: Path) -> tuple[Path, str]:
    link = worktree / "dangling"
    link.symlink_to(worktree.parent / "nowhere", target_is_directory=True)
    path = link / "deep" / "x.py"
    return path, f"{path} cannot exist: {link} is a dangling symlink"


def _the_checkout_root(_main: Path, worktree: Path) -> tuple[Path, str]:
    return worktree, _checkout_root_reason(worktree)


def _path_with_a_newline_in_its_name(_main: Path, worktree: Path) -> tuple[Path, str]:
    path = worktree / "a\nb"
    return path, f"--add path {str(path)!r} is outside the resolved checkout {worktree.resolve()}"


def _path_in_a_bare_repository(main: Path, _worktree: Path) -> tuple[Path, str]:
    hook = _hook_in_a_bare_repository(main.parent)
    return hook, f"not a checkout: {hook.parent.parent.resolve()} is a git directory"


def _path_in_a_checkouts_git_directory(main: Path, _worktree: Path) -> tuple[Path, str]:
    git_directory = main / ".git"
    return (
        git_directory / "info" / "x",
        f"not a checkout: {git_directory.resolve()} is a git directory",
    )


def _committed_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    repository.mkdir()
    real_git(repository, "init", "-q", "-b", "main")
    real_git(
        repository,
        "-c",
        "user.name=T",
        "-c",
        "user.email=t@e.c",
        "commit",
        "-q",
        "-m",
        "x",
        "--allow-empty",
    )
    return repository


def _select_git_directory_and_work_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path]:
    repository = _committed_repository(tmp_path)
    work_tree = tmp_path / "plain"
    work_tree.mkdir()
    monkeypatch.setenv("GIT_DIR", str(repository / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(work_tree))
    return repository / ".git", work_tree


def _select_external_objects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    repository = _committed_repository(tmp_path)
    external_objects = tmp_path / "objects-elsewhere"
    (repository / ".git" / "objects").rename(external_objects)
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(external_objects))
    return repository / ".git", repository


def _select_common_directory_layout(
    _monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path]:
    repository = _committed_repository(tmp_path)
    git_directory = repository / ".git"
    common_directory = tmp_path / "common"
    common_directory.mkdir()
    for name in ("objects", "refs"):
        (git_directory / name).rename(common_directory / name)
    (git_directory / "commondir").write_text("../../common\n")
    return git_directory, repository


def _select_unborn_symlinked_head(
    _monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path]:
    repository = tmp_path / "repo"
    repository.mkdir()
    real_git(repository, "init", "-q", "-b", "main")
    (repository / ".git" / "HEAD").unlink()
    (repository / ".git" / "HEAD").symlink_to("refs/heads/main")
    return repository / ".git", repository


@pytest.fixture(
    params=[
        _select_git_directory_and_work_tree,
        _select_external_objects,
        _select_common_directory_layout,
        _select_unborn_symlinked_head,
    ]
)
def _environment_selected_repository(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path]:
    """A repository only git's own recognition rules see -- no complete
    `.git` of plain files and directories sits above the work tree: `GIT_DIR`
    with `GIT_WORK_TREE`, `GIT_OBJECT_DIRECTORY` with the objects moved out of
    `.git`, a `commondir` file naming the directory holding `objects/` and
    `refs/`, or a `HEAD` symlink naming an unborn branch. Returns
    `(git_directory, work_tree)`."""
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
    return request.param(monkeypatch, tmp_path)


def _git_directory_layout(directory: Path) -> Path:
    for name in ("objects", "refs"):
        (directory / name).mkdir(parents=True)
    (directory / "HEAD").write_text("ref: refs/heads/main\n")
    return directory


def _move_common_files_into(directory: Path, name: str) -> None:
    """Moves `objects/` and `refs/` into `directory/name`, where a `commondir`
    file naming `name` makes git look for them."""
    (directory / name).mkdir()
    for moved in ("objects", "refs"):
        (directory / moved).rename(directory / name / moved)


def _write_commondir(directory: Path, content: bytes, *, moved_into: bytes | None = None) -> None:
    if moved_into is not None:
        _move_common_files_into(directory, os.fsdecode(moved_into))
    (directory / "commondir").write_bytes(content)


def _write_head(directory: Path, content: bytes) -> None:
    (directory / "HEAD").write_bytes(content)


def _link_head_to(directory: Path, target: str) -> None:
    (directory / "HEAD").unlink()
    (directory / "HEAD").symlink_to(target)


def _link_head_to_existing_file(directory: Path) -> None:
    (directory / "elsewhere").write_text("content")
    _link_head_to(directory, str(directory / "elsewhere"))


def _make_objects_an_executable_file(directory: Path) -> None:
    (directory / "objects").rmdir()
    (directory / "objects").write_text("#!/bin/sh\n")
    (directory / "objects").chmod(0o755)


def _provide_executable_file(directory: Path) -> None:
    (directory / "executable").write_text("#!/bin/sh\n")
    (directory / "executable").chmod(0o755)


def _move_common_files_away(directory: Path) -> None:
    _move_common_files_into(directory, "c")


def _make_commondir_unreadable(directory: Path) -> None:
    _move_common_files_away(directory)
    (directory / "commondir").mkdir()


def _write_head_beside_commondir_without_local_objects(directory: Path, head: bytes) -> None:
    _write_commondir(directory, b"c", moved_into=b"c")
    _write_head(directory, head)


def _write_commondir_naming_a_symlink_loop(directory: Path) -> None:
    (directory / "loop").symlink_to("loop")
    _write_commondir(directory, b"loop")


_NON_UTF8_NAME = b"c\xff"

# Each row's answer is what git 2.43 itself measured for the layout
# (`git --git-dir=D rev-parse --git-dir`); a `commondir` git dies reading
# counts as recognized, so rescope refuses it as a git directory (RESC-31).
# Where a row's layout keeps `HEAD`, `objects/` and `refs/` in the directory
# itself, the plain layout rule (`checkout._has_plain_git_directory_layout`,
# kept from before the port of git's recognition) recognizes it whatever git
# says.
_GIT_DIRECTORY_RECOGNITION_ROWS = [
    pytest.param(lambda directory: None, {}, True, id="head-names-a-ref"),
    pytest.param(
        lambda directory: _link_head_to(directory, "refs/heads/unborn"),
        {},
        True,
        id="head-symlink-to-a-dangling-ref",
    ),
    pytest.param(
        _link_head_to_existing_file, {}, True, id="head-symlink-to-a-non-ref-file-mains-rule"
    ),
    pytest.param(
        lambda directory: _write_head(directory, b"ref:   \trefs/x"),
        {},
        True,
        id="head-ref-after-whitespace",
    ),
    pytest.param(
        lambda directory: _write_head(directory, b"ref: other/x"),
        {},
        True,
        id="head-ref-outside-refs-mains-rule",
    ),
    pytest.param(
        lambda directory: _write_head(directory, b"0123456789abcdef0123456789abcdef01234567\n"),
        {},
        True,
        id="head-sha1-object-id",
    ),
    pytest.param(
        lambda directory: _write_head(directory, b"0123456789abcdef" * 4),
        {},
        True,
        id="head-sha256-object-id",
    ),
    pytest.param(
        lambda directory: _write_head(directory, b"garbage"),
        {},
        True,
        id="head-garbage-mains-rule",
    ),
    pytest.param(
        lambda directory: _write_head(directory, b""), {}, True, id="head-empty-mains-rule"
    ),
    pytest.param(lambda directory: (directory / "HEAD").unlink(), {}, False, id="head-missing"),
    pytest.param(_make_objects_an_executable_file, {}, True, id="objects-an-executable-file"),
    pytest.param(lambda directory: (directory / "objects").rmdir(), {}, False, id="no-objects"),
    pytest.param(lambda directory: (directory / "refs").rmdir(), {}, False, id="no-refs"),
    pytest.param(
        lambda directory: None, {"GIT_OBJECT_DIRECTORY": ""}, True, id="empty-objects-mains-rule"
    ),
    pytest.param(
        _provide_executable_file,
        {"GIT_OBJECT_DIRECTORY": "{directory}/executable"},
        True,
        id="object-directory-an-executable-file",
    ),
    pytest.param(
        lambda directory: None, {"GIT_COMMON_DIR": ""}, True, id="empty-common-dir-mains-rule"
    ),
    pytest.param(_move_common_files_away, {"GIT_COMMON_DIR": ""}, False, id="empty-common-dir"),
    pytest.param(_move_common_files_away, {"GIT_OBJECT_DIRECTORY": ""}, False, id="empty-objects"),
    pytest.param(
        lambda directory: _write_commondir(directory, b"c ", moved_into=b"c "),
        {},
        True,
        id="commondir-name-with-trailing-space",
    ),
    pytest.param(
        lambda directory: _write_commondir(directory, b"c\r\n", moved_into=b"c"),
        {},
        True,
        id="commondir-with-crlf",
    ),
    pytest.param(
        lambda directory: _write_commondir(directory, _NON_UTF8_NAME, moved_into=_NON_UTF8_NAME),
        {},
        True,
        id="commondir-non-utf8-name",
    ),
    pytest.param(
        lambda directory: _write_commondir(directory, b"\n"), {}, True, id="commondir-line-break"
    ),
    pytest.param(
        lambda directory: _write_commondir(directory, b"nowhere"),
        {},
        True,
        id="commondir-to-a-missing-directory-mains-rule",
    ),
    pytest.param(
        lambda directory: _write_commondir(directory, b"nowhere", moved_into=b"c"),
        {},
        False,
        id="commondir-to-a-missing-directory",
    ),
    pytest.param(
        lambda directory: _write_commondir(directory, b"", moved_into=b"c"),
        {},
        True,
        id="commondir-empty-fails-closed",
    ),
    pytest.param(
        _make_commondir_unreadable,
        {},
        True,
        id="commondir-unreadable-fails-closed",
    ),
    pytest.param(
        lambda directory: _write_commondir(directory, b"nowhere/below", moved_into=b"c"),
        {},
        True,
        id="commondir-below-a-missing-directory-fails-closed",
    ),
    pytest.param(
        lambda directory: _write_commondir(directory, b"missing/"),
        {},
        True,
        id="commondir-naming-a-missing-directory-with-a-slash-mains-rule",
    ),
    pytest.param(
        _write_commondir_naming_a_symlink_loop,
        {},
        True,
        id="commondir-naming-a-symlink-loop-mains-rule",
    ),
    pytest.param(
        lambda directory: _write_head_beside_commondir_without_local_objects(
            directory, b"ref:\vrefs/heads/main"
        ),
        {},
        False,
        id="head-ref-after-a-vertical-tab",
    ),
    pytest.param(
        lambda directory: _write_head_beside_commondir_without_local_objects(
            directory, b"ref:\frefs/heads/main"
        ),
        {},
        False,
        id="head-ref-after-a-form-feed",
    ),
    pytest.param(
        lambda directory: _write_head_beside_commondir_without_local_objects(directory, b"garbage"),
        {},
        False,
        id="head-garbage-without-local-objects",
    ),
    pytest.param(
        lambda directory: _write_commondir(directory, b"missing\0ignored", moved_into=b"c"),
        {},
        False,
        id="commondir-cut-at-a-null-byte",
    ),
]


def _serve_item_72_body(monkeypatch: pytest.MonkeyPatch) -> FakeForge:
    """Issue #72's own body, with the `aco` block a rescope keeps in
    step with its claim, on a GitHub fake the checkout's
    canonical remote names -- so no rescope here ever reaches a real forge."""
    client = FakeForge()
    client.issue_references[72] = forge.ItemReference(
        forge.ItemState.OPEN, "Widget", complete_contract("Build it.")
    )
    monkeypatch.setattr(github, "GitHubForge", lambda repository: client)
    monkeypatch.setattr(
        checkout, "remote_url", lambda remote, **_kwargs: f"https://github.com/{REPOSITORY}.git"
    )
    return client


def _serve_the_claim_on_the_widget_branch(monkeypatch: pytest.MonkeyPatch) -> protocol.ActiveClaim:
    """A live builder claim of `Codex Sol` on issue #72 scoping `src/widget.py`,
    served as the store's state; a commit applies its transition in memory."""
    claimed = standing_active_claim(
        "Codex Sol", scope=("src/widget.py",), branch="codex/issue-72-widget"
    )
    state = protocol.ClaimState(
        tip=protocol.ObjectId(claimed.base),
        claims={protocol.claim_key(claimed.identity, claimed.branch): claimed},
    )
    monkeypatch.setattr(store, "fetch_state", lambda *, worktree, remote: state)
    monkeypatch.setattr(
        store,
        "commit_transition",
        lambda *, observed, subject, intent: protocol.apply(observed.state, intent),
    )
    return claimed


def _rescope_refusal(capsys: pytest.CaptureFixture[str], path: Path) -> tuple[int, str]:
    status = issue_claim.main(["rescope", "72", "--add", str(path)])
    return status, capsys.readouterr().err.removeprefix("ERROR: ").removesuffix("\n")


def _rescope_json_refusal(
    capsys: pytest.CaptureFixture[str], path: Path
) -> tuple[int, str, str, str]:
    """`rescope --add <path> --json`: its status, its `reason`, its `message`
    and what stderr printed beside the envelope."""
    status = issue_claim.main(["rescope", "72", "--add", str(path), "--json"])
    captured = capsys.readouterr()
    refusal = json.loads(captured.out)
    assert refusal["ok"] is False
    return status, refusal["reason"], refusal["message"], captured.err


def _isolate_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})


@pytest.mark.parametrize(
    "cwd_kind", ["claimed_worktree", "foreign_tmp_dir", "foreign_main_checkout"]
)
def test_rescope_succeeds_from_every_cwd_when_the_add_path_is_absolute(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    cwd_kind: str,
) -> None:
    """Spec: RESC-12, RESC-22. The same
    absolute `--add` path locates the claimed worktree's own checkout from
    the worktree itself, an unrelated tmp directory outside every
    repository, and the shared main checkout alike -- the one location
    signal a dispatcher in the head's own shared environment (editing a
    linked worktree through a subagent) can give without knowing its cwd.
    The item body's scope moves with the claim."""
    _isolate_home(monkeypatch, tmp_path)
    main, worktree = _real_repository_with_worktree(tmp_path)
    add = str(worktree / "docs" / "widget.md")
    if cwd_kind == "claimed_worktree":
        cwd = worktree
    elif cwd_kind == "foreign_main_checkout":
        cwd = main
    else:
        cwd = tmp_path / "elsewhere"
        cwd.mkdir()
    monkeypatch.chdir(cwd)
    client = _serve_item_72_body(monkeypatch)
    claimed = _serve_the_claim_on_the_widget_branch(monkeypatch)

    status = issue_claim.main(["rescope", "72", "--add", add])

    assert status == 0
    assert capsys.readouterr().out == f"RESCOPED issue #72: {claimed.claim_id}\n"
    assert body.parse_body(client.item_bodies[72]).scope == ("docs/widget.md", "src/widget.py")


def test_rescope_admits_a_file_in_a_directory_not_created_yet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: RESC-18. `rescope --add` of a file whose directories
    do not exist yet resolves the worktree from their nearest existing
    ancestor, so the claim can grow before the file is written."""
    _isolate_home(monkeypatch, tmp_path)
    _main, worktree = _real_repository_with_worktree(tmp_path)
    new_file = worktree / "neu" / "tief" / "x.py"
    client = _serve_item_72_body(monkeypatch)
    claimed = _serve_the_claim_on_the_widget_branch(monkeypatch)

    status = issue_claim.main(["rescope", "72", "--add", str(new_file)])

    assert status == 0
    assert capsys.readouterr().out == f"RESCOPED issue #72: {claimed.claim_id}\n"
    assert body.parse_body(client.item_bodies[72]).scope == ("neu/tief/x.py", "src/widget.py")


def test_rescope_rejects_a_wide_scope_from_a_foreign_cwd_via_the_resolved_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: RESC-10. The width guard's own
    directory classifier (`checkout.scope_directories`) must read the
    resolved checkout's own directory, never the calling process's cwd. From
    a foreign cwd -- which has no `docs` directory at all, and is not even a
    git checkout -- an absolute `--add` naming the claimed worktree's own
    `docs` directory still trips the same `--whole` refusal it would from
    inside that worktree, because `docs` is classified against the worktree
    via `-C`, not against the foreign cwd."""
    _isolate_home(monkeypatch, tmp_path)
    _main, worktree = _real_repository_with_worktree(tmp_path)
    foreign_cwd = tmp_path / "elsewhere"
    foreign_cwd.mkdir()
    monkeypatch.chdir(foreign_cwd)
    _serve_item_72_body(monkeypatch)
    _serve_the_claim_on_the_widget_branch(monkeypatch)

    status = issue_claim.main(["rescope", "72", "--add", str(worktree / "docs")])

    assert status == 2
    err = capsys.readouterr().err
    assert "scope is wide" in err
    assert "--whole" in err


def _rescope_args_mixed_absolute_and_relative(tmp_path: Path) -> list[str]:
    _main, worktree = _real_repository_with_worktree(tmp_path)
    return [
        "rescope",
        "72",
        "--add",
        str(worktree / "docs" / "widget.md"),
        "--drop",
        "src/widget.py",
    ]


def _rescope_args_add_path_outside_the_first_paths_checkout(tmp_path: Path) -> list[str]:
    _main, worktree = _real_repository_with_worktree(tmp_path)
    _main2, other_worktree = _real_repository_with_worktree(tmp_path, slug="issue-90-other")
    return [
        "rescope",
        "72",
        "--add",
        str(worktree / "docs" / "widget.md"),
        "--add",
        str(other_worktree / "src" / "other.py"),
    ]


def _rescope_args_add_path_outside_any_repository(tmp_path: Path) -> list[str]:
    outside = tmp_path / "outside"
    outside.mkdir()
    return ["rescope", "72", "--add", str(outside / "file.py")]


def _rescope_args_add_path_in_a_new_directory_outside_any_repository(
    tmp_path: Path,
) -> list[str]:
    return ["rescope", "72", "--add", str(tmp_path / "outside" / "neu" / "x.py")]


def _rescope_args_add_dotdot_path_through_a_missing_directory_out_of_the_worktree(
    tmp_path: Path,
) -> list[str]:
    _main, worktree = _real_repository_with_worktree(tmp_path)
    escape_to_outside = os.path.relpath(tmp_path / "outside", worktree)
    return ["rescope", "72", "--add", f"{worktree}/missing/../{escape_to_outside}/new/q.py"]


def _rescope_args_add_path_in_an_unborn_checkout(tmp_path: Path) -> list[str]:
    unborn = tmp_path / "unborn"
    unborn.mkdir()
    real_git(unborn, "init", "-q", "-b", "codex/issue-72-widget")
    return ["rescope", "72", "--add", str(unborn / "widget.py")]


@pytest.mark.parametrize(
    ("build_args", "expected_error_fragment"),
    [
        (
            _rescope_args_add_path_outside_the_first_paths_checkout,
            "is outside the resolved checkout",
        ),
        (_rescope_args_add_path_outside_any_repository, "not in a repository"),
        (
            _rescope_args_add_path_in_a_new_directory_outside_any_repository,
            "not in a repository",
        ),
        (
            _rescope_args_add_dotdot_path_through_a_missing_directory_out_of_the_worktree,
            "not in a repository",
        ),
        (_rescope_args_add_path_in_an_unborn_checkout, "no commit on this branch"),
        (
            _rescope_args_mixed_absolute_and_relative,
            "--drop path 'src/widget.py' is relative and {tmp_path} is not in a repository; "
            "pass it as an absolute path",
        ),
    ],
    ids=[
        "second-add-path-outside-checkout",
        "outside-any-repository",
        "new-directory-outside-any-repository",
        "dotdot-through-missing-directory-outside-any-repository",
        "checkout-has-no-commit",
        "mixed-absolute-and-relative",
    ],
)
def test_rescope_denies_before_touching_the_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    build_args: Callable[[Path], list[str]],
    expected_error_fragment: str,
) -> None:
    """Spec: RESC-01, RESC-05, RESC-26, RESC-28. `rescope`'s own
    checkout-resolution paths:
    a second `--add`/`--drop` path outside the first path's own checkout
    (`cmd_rescope._rescope_scope_entries`) refuses rather than silently
    mis-scoping; a location outside every repository, and a no-commit
    checkout (`cmd_rescope._rescope_checkout`); and a relative `--drop` entry
    beside an absolute `--add` that names a real checkout, run from a cwd
    outside every repository, which has no checkout to read it against --
    all refuse before the store is ever touched."""
    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(store, "fetch_state", store_must_not_be_read)
    args = build_args(tmp_path)

    status = issue_claim.main(args)

    assert status == 2
    assert expected_error_fragment.format(tmp_path=tmp_path) in capsys.readouterr().err


def test_rescope_json_reports_a_dotdot_path_through_a_missing_directory_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: RESC-17. A `..` path that leaves the worktree through a missing
    directory is an unresolved checkout, so `--json` reports `unavailable`
    with the sentence stderr printed."""
    _isolate_home(monkeypatch, tmp_path)
    args = _rescope_args_add_dotdot_path_through_a_missing_directory_out_of_the_worktree(tmp_path)

    status = issue_claim.main([*args, "--json"])

    captured = capsys.readouterr()
    refusal = json.loads(captured.out)
    assert status == 2
    assert (refusal["ok"], refusal["reason"]) == (False, "unavailable")
    assert "not in a repository" in refusal["message"]
    assert captured.err == f"ERROR: {refusal['message']}\n"


@pytest.mark.parametrize(
    ("build_case", "reason"),
    [
        pytest.param(_path_below_a_file, "invalid_usage", id="below-a-file"),
        pytest.param(
            _path_below_a_dangling_symlink, "invalid_usage", id="below-a-dangling-symlink"
        ),
        pytest.param(_the_checkout_root, "invalid_usage", id="checkout-root"),
        pytest.param(_path_with_a_newline_in_its_name, "invalid_usage", id="newline-in-name"),
        pytest.param(_path_in_a_bare_repository, "unavailable", id="bare-repository"),
        pytest.param(_path_in_a_checkouts_git_directory, "unavailable", id="dot-git"),
    ],
)
@pytest.mark.parametrize("output_mode", ["text", "json"])
def test_rescope_refuses_a_path_no_claim_can_cover_with_one_sentence_and_its_json_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    build_case: Callable[[Path, Path], tuple[Path, str]],
    reason: str,
    output_mode: str,
) -> None:
    """Spec: RESC-15, RESC-17, RESC-19, RESC-31. A path below a file or a
    dangling symlink, the checkout root itself, and a path no scope entry can
    spell (a newline in its name) are refused as a malformed `--add`; a path
    inside a git directory as an unresolved checkout -- each with one
    sentence before the store is read, in text and under `--json`."""
    _isolate_home(monkeypatch, tmp_path)
    main, worktree = _real_repository_with_worktree(tmp_path)
    path, sentence = build_case(main, worktree)
    monkeypatch.setattr(store, "fetch_state", store_must_not_be_read)

    if output_mode == "text":
        assert _rescope_refusal(capsys, path) == (2, sentence)
    else:
        assert _rescope_json_refusal(capsys, path) == (2, reason, sentence, f"ERROR: {sentence}\n")


@pytest.mark.parametrize(
    "root_form",
    [lambda root: root, lambda root: root / ".." / root.name, lambda root: root / "."],
    ids=["exact", "dot-dot", "dot"],
)
def test_rescope_judges_a_nested_checkouts_root_by_that_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    root_form: Callable[[Path], Path],
) -> None:
    """Spec: RESC-30. A linked worktree whose own root's *parent* directory
    sits inside another, outer git checkout is judged by its own checkout,
    resolved from the root itself before the outer checkout's parent-first
    lookup gets a say -- so adding it names that root rather than the outer
    checkout's scope judging it -- also for a lexically equivalent but
    unnormalized spelling of the same root."""
    _isolate_home(monkeypatch, tmp_path)
    outer, nested = _real_repository_with_nested_worktree(tmp_path)
    monkeypatch.chdir(outer)
    monkeypatch.setattr(store, "fetch_state", store_must_not_be_read)

    assert _rescope_refusal(capsys, root_form(nested)) == (2, _checkout_root_reason(nested))
    assert _rescope_json_refusal(capsys, root_form(nested))[:3] == (
        2,
        "invalid_usage",
        _checkout_root_reason(nested),
    )


@pytest.mark.usefixtures("isolated_global_git_config")
@pytest.mark.parametrize(
    ("canonical_head", "branch", "sentence"),
    [
        pytest.param(
            "trunk",
            "trunk",
            "build claims require an isolated non-main worktree branch; "
            "run this command from this claim's own worktree, not the primary checkout",
            id="rescope-hub-default",
        ),
        pytest.param(
            None,
            "codex/issue-72-widget",
            "default branch unknown; run git remote set-head hub --auto",
            id="rescope-hub-unrecorded",
        ),
    ],
)
def test_rescope_judges_the_canonical_remotes_recorded_default_branch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    canonical_head: str | None,
    branch: str,
    sentence: str,
) -> None:
    """Spec: RESC-20, RESC-29. With `hub` canonical and
    `origin/HEAD` naming `main`, a worktree on `hub`'s default branch is
    refused; without a recorded `hub/HEAD`, `rescope` refuses `default branch
    unknown` -- `origin/HEAD` never answers for `hub`."""
    _isolate_home(monkeypatch, tmp_path)
    path = hub_canonical_worktree_file(
        tmp_path, canonical="hub", canonical_head=canonical_head, branch=branch
    )
    monkeypatch.setattr(store, "fetch_state", store_must_not_be_read)

    assert _rescope_refusal(capsys, path) == (2, sentence)


_UNCONFIGURED_UPSTREAM = "cannot determine the trunk: canonical remote 'upstream' is not configured"


@pytest.mark.usefixtures("isolated_global_git_config")
@pytest.mark.parametrize(
    "canonical_head",
    [
        pytest.param(None, id="rescope-canonical-remote-not-configured"),
        pytest.param("trunk", id="rescope-unconfigured-remote-left-a-recorded-head"),
    ],
)
def test_rescope_names_a_canonical_remote_the_clone_never_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    canonical_head: str | None,
) -> None:
    """Spec: RESC-21. A canonical remote the clone never added is named in
    every command's own sentence, even where a `HEAD` it left behind still
    resolves."""
    _isolate_home(monkeypatch, tmp_path)
    path = hub_canonical_worktree_file(
        tmp_path,
        canonical="upstream",
        canonical_head=canonical_head,
        branch="codex/issue-72-widget",
    )
    monkeypatch.setattr(store, "fetch_state", store_must_not_be_read)

    assert _rescope_refusal(capsys, path) == (2, _UNCONFIGURED_UPSTREAM)


@pytest.mark.usefixtures("isolated_global_git_config")
def test_rescope_names_a_canonical_remote_that_has_config_lines_but_no_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: RESC-21. A
    `remote.upstream.fetch` line without a URL, beside a `HEAD` the remote
    left behind, is still no configured canonical remote -- `rescope` names
    it rather than judging its branch."""
    _isolate_home(monkeypatch, tmp_path)
    path = hub_canonical_worktree_file(
        tmp_path, canonical="upstream", canonical_head="trunk", branch="codex/issue-72-widget"
    )
    real_git(
        path.parent, "config", "remote.upstream.fetch", "+refs/heads/*:refs/remotes/upstream/*"
    )
    monkeypatch.setattr(store, "fetch_state", store_must_not_be_read)

    assert _rescope_refusal(capsys, path) == (2, _UNCONFIGURED_UPSTREAM)


@pytest.mark.usefixtures("isolated_global_git_config")
@pytest.mark.parametrize(
    "failing_read",
    [
        pytest.param(list(recorded_head_read("hub")), id="remote-head"),
        pytest.param(["rev-parse", "--verify", "--quiet", "HEAD"], id="commit"),
    ],
)
def test_rescope_refuses_with_gits_text_when_a_checkout_read_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failing_read: list[str],
) -> None:
    """Spec: RESC-17. A git failure reading the canonical remote's `HEAD` or
    the checkout's commit, run against a real worktree, is neither a remote
    that recorded none nor a branch with no commit: it refuses with git's own
    text."""
    _isolate_home(monkeypatch, tmp_path)
    path = hub_canonical_worktree_file(
        tmp_path, canonical="hub", canonical_head="trunk", branch="codex/issue-72-widget"
    )
    monkeypatch.setattr(store, "fetch_state", store_must_not_be_read)
    stub_one_git_call(monkeypatch, failing_read, exit_status=128, stderr="fatal: broken")

    assert _rescope_refusal(capsys, path) == (2, "fatal: broken")


@pytest.mark.usefixtures("isolated_global_git_config")
@pytest.mark.parametrize("variable", checkout.REPOSITORY_SELECTING_ENVIRONMENT_VARIABLES)
@pytest.mark.parametrize("value", ["", "{nowhere}"], ids=["empty", "set"])
def test_rescope_never_reads_a_git_failure_as_outside_while_the_environment_selects_a_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    variable: str,
    value: str,
) -> None:
    """Spec: RESC-32. While `GIT_DIR`, `GIT_COMMON_DIR` or
    `GIT_OBJECT_DIRECTORY` is present, even empty, a failed git read in a
    directory outside every repository refuses with git's own text, never
    `not in a repository`."""
    _isolate_home(monkeypatch, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv(variable, value.format(nowhere=tmp_path / "nowhere"))

    status, reason, message, _stderr = _rescope_json_refusal(capsys, outside / "x.py")

    assert (status, reason) == (2, "unavailable")
    assert checkout.NOT_IN_A_REPOSITORY_REASON not in message


@pytest.mark.usefixtures("isolated_global_git_config")
@pytest.mark.parametrize(
    "failing_read",
    [
        pytest.param(
            [
                "rev-parse",
                "--path-format=absolute",
                "--show-toplevel",
                "--git-dir",
                "--git-common-dir",
            ],
            id="discovery",
        ),
        pytest.param(["rev-parse", "--verify", "--quiet", "HEAD"], id="commit"),
    ],
)
@pytest.mark.parametrize(("inject", "detail"), GIT_FAILURE_INJECTIONS)
def test_rescope_refuses_a_failed_read_in_a_checkout_gits_own_recognition_sees(
    monkeypatch: pytest.MonkeyPatch,
    _environment_selected_repository: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    failing_read: list[str],
    inject: Callable[[pytest.MonkeyPatch, list[str]], list[list[str]]],
    detail: str,
) -> None:
    """Spec: RESC-32. A checkout only git's own recognition sees -- a local
    git variable, a `commondir` file, a symlinked `HEAD` -- has no plain
    `.git` marker above it. A failed read of its discovery or its commit
    refuses with git's own text, never reads as a path outside every
    repository."""
    _, work_tree = _environment_selected_repository
    injected = inject(monkeypatch, failing_read)

    outcome = _rescope_refusal(capsys, work_tree / "widget.py")

    assert injected
    assert outcome == (2, detail)


@pytest.mark.usefixtures("isolated_global_git_config")
def test_rescope_names_a_git_directory_when_a_branch_read_fails_in_an_environment_selected_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: RESC-31. A path inside the git directory refuses with `not a
    checkout: ...`, never git's own error text, even when the read after
    discovery fails."""
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
    git_directory, _ = _select_git_directory_and_work_tree(monkeypatch, tmp_path)
    injected = inject_exit_128(monkeypatch, ["branch", "--show-current"])

    outcome = _rescope_refusal(capsys, git_directory / "objects" / "widget")

    assert injected
    assert outcome == (2, f"not a checkout: {git_directory.resolve()} is a git directory")


@pytest.mark.usefixtures("isolated_global_git_config")
def test_rescope_judges_a_git_directory_the_environment_selects_when_no_git_read_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: RESC-31, RESC-32. The git-directory sentence names a refusal
    only: where every git read succeeds in a valid `GIT_DIR` with its
    `GIT_WORK_TREE`, `rescope` judges the path as it does any other."""
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
    git_directory, _ = _select_git_directory_and_work_tree(monkeypatch, tmp_path)

    outcome = _rescope_json_refusal(capsys, git_directory / "objects" / "widget")

    assert outcome == (
        2,
        "unavailable",
        "cannot determine the trunk: canonical remote 'origin' is not configured",
        "ERROR: cannot determine the trunk: canonical remote 'origin' is not configured\n",
    )


@pytest.mark.usefixtures("isolated_global_git_config")
@pytest.mark.parametrize("rescope_directory", ["", "elsewhere"])
def test_rescope_resolves_a_relative_object_directory_from_the_directory_git_runs_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    rescope_directory: str,
) -> None:
    """Spec: RESC-31. A relative `GIT_OBJECT_DIRECTORY` is relative to the
    directory `git -C` runs in -- the path's -- whichever directory rescope
    runs in."""
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
    git_directory, _ = _select_external_objects(monkeypatch, tmp_path)
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / rescope_directory)
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", "../../../objects-elsewhere")

    outcome = _rescope_refusal(capsys, git_directory / "refs" / "widget")

    assert outcome == (2, f"not a checkout: {git_directory.resolve()} is a git directory")


@pytest.mark.usefixtures("isolated_global_git_config")
@pytest.mark.parametrize(
    ("arrange_layout", "environment", "recognized"), _GIT_DIRECTORY_RECOGNITION_ROWS
)
def test_rescope_names_a_directory_a_git_directory_when_git_or_plain_layout_takes_it_for_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    arrange_layout: Callable[[Path], None],
    environment: dict[str, str],
    recognized: bool,
) -> None:
    """Spec: RESC-31, RESC-32. A path in a directory refuses with the
    git-directory sentence when git 2.43 (setup.c `is_git_directory`) or
    the plain layout rule (`HEAD` file beside `objects/` and `refs/`) takes that
    directory for a git directory; where neither does, the path is outside
    every repository or the environment's own variable makes git's text the
    refusal."""
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Codex Sol"})
    directory = _git_directory_layout(tmp_path / "git-directory")
    arrange_layout(directory)
    for name, value in environment.items():
        monkeypatch.setenv(name, value.format(directory=directory))
    sentence = f"not a checkout: {directory.resolve()} is a git directory"

    status, reason, message, _stderr = _rescope_json_refusal(capsys, directory / "widget")

    assert (status, reason) == (2, "unavailable")
    assert (sentence in message) is recognized
