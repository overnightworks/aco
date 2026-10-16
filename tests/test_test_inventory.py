"""Behavioral tests for the CI rewrite and family-move gates in `scripts/test_inventory.py`.

Each case drives the gate against a real, freshly initialized git repository under
`tmp_path`. Git itself is the boundary the gate queries, so faking its output would test
the wrong layer.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from script_fixtures import load_script

test_inventory = load_script("test_inventory")
rewritten_modules = test_inventory.rewritten_modules
family_move_modules = test_inventory.family_move_modules
run_ci = test_inventory.run_ci

_MODULE = "tests/test_example.py"
_ALPHA_MODULE = "tests/test_alpha.py"
_BETA_MODULE = "tests/test_beta.py"
_LEDGER = "scripts/test_inventory_dropped.txt"
_TEN_LINES = "".join(f"assert {number} == {number}\n" for number in range(10))
_TWO_LINES = "assert 0 == 0\nassert 1 == 1\n"


def _test_source(name: str, literal: str) -> str:
    return f"def test_{name}():\n    assert value == {literal!r}\n"


_ALPHA_TEST = _test_source("alpha", "alpha-literal")
_BETA_TEST = _test_source("beta", "beta-literal")
_BETA_REWORDED_TEST = _test_source("beta", "reworded-literal")
_GAMMA_TEST = _test_source("gamma", "gamma-literal")


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit_modules(repo_root: Path, modules: dict[str, str | None]) -> str:
    """Commit *modules* (``None`` removes one); return the commit."""
    for relative_path, content in modules.items():
        module = repo_root / relative_path
        if content is None:
            module.unlink(missing_ok=True)
        else:
            module.parent.mkdir(exist_ok=True)
            module.write_text(content, encoding="utf-8")
    _git(repo_root, "add", "--all")
    _git(repo_root, "commit", "--quiet", "--allow-empty", "--message", "step")
    return _git(repo_root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _git(tmp_path, "init", "--quiet")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    ("base_content", "head_content", "expected"),
    [
        (_TEN_LINES, None, []),
        (None, _TEN_LINES, []),
        (_TEN_LINES, _TWO_LINES, [_MODULE]),
    ],
    ids=[
        "deleted-module-is-not-a-rewrite",
        "new-module-is-not-a-rewrite",
        "shrunk-past-half-is-a-rewrite",
    ],
)
def test_rewritten_modules_names_only_a_module_shrunk_past_the_threshold(
    repo: Path,
    base_content: str | None,
    head_content: str | None,
    expected: list[str],
) -> None:
    base = _commit_modules(repo, {_MODULE: base_content})
    _commit_modules(repo, {_MODULE: head_content})

    assert rewritten_modules(base) == expected


@pytest.mark.parametrize(
    ("base_modules", "head_modules", "expected"),
    [
        (
            {_ALPHA_MODULE: _ALPHA_TEST + _BETA_TEST},
            {_ALPHA_MODULE: _ALPHA_TEST, _BETA_MODULE: _BETA_TEST},
            [_ALPHA_MODULE, _BETA_MODULE],
        ),
        (
            {_ALPHA_MODULE: _ALPHA_TEST + _BETA_TEST},
            {_ALPHA_MODULE: None, _BETA_MODULE: _ALPHA_TEST + _BETA_TEST},
            [_ALPHA_MODULE, _BETA_MODULE],
        ),
        (
            {_ALPHA_MODULE: _ALPHA_TEST},
            {_ALPHA_MODULE: _ALPHA_TEST, _BETA_MODULE: _BETA_TEST},
            [],
        ),
        (
            {_ALPHA_MODULE: _ALPHA_TEST + _BETA_TEST},
            {_ALPHA_MODULE: _ALPHA_TEST},
            [],
        ),
        (
            {_ALPHA_MODULE: _ALPHA_TEST + _BETA_TEST},
            {_ALPHA_MODULE: _ALPHA_TEST + _GAMMA_TEST},
            [],
        ),
    ],
    ids=[
        "tests-moved-to-a-new-module",
        "module-deleted-while-another-gains-its-tests",
        "tests-added-without-any-leaving",
        "tests-removed-without-any-appearing",
        "tests-renamed-within-one-module",
    ],
)
def test_family_move_modules_names_the_modules_a_move_involves(
    repo: Path,
    base_modules: dict[str, str | None],
    head_modules: dict[str, str | None],
    expected: list[str],
) -> None:
    base = _commit_modules(repo, base_modules)
    _commit_modules(repo, head_modules)

    assert family_move_modules(base) == expected


# The source keeps its gamma test so it shrinks by a third, short of the rewrite threshold.
_MOVED_BETA = {_ALPHA_MODULE: _ALPHA_TEST + _GAMMA_TEST, _BETA_MODULE: _BETA_TEST}
_MOVED_REWORDED_BETA = {
    _ALPHA_MODULE: _ALPHA_TEST + _GAMMA_TEST,
    _BETA_MODULE: _BETA_REWORDED_TEST,
}
_REWORDED_LEDGER = f"{_BETA_MODULE}\t'beta-literal'\treworded on purpose\n"


@pytest.mark.parametrize(
    ("head_modules", "ledger", "expected_exit", "expected_stderr"),
    [
        (_MOVED_BETA, None, 0, ""),
        (_MOVED_REWORDED_BETA, None, 1, "'beta-literal'"),
        (_MOVED_REWORDED_BETA, _REWORDED_LEDGER, 0, ""),
    ],
    ids=[
        "move-keeping-every-literal-passes",
        "move-losing-a-literal-fails",
        "move-losing-a-ledgered-literal-passes",
    ],
)
def test_run_ci_judges_a_family_move_by_the_literal_union(
    repo: Path,
    capsys: pytest.CaptureFixture[str],
    head_modules: dict[str, str | None],
    ledger: str | None,
    expected_exit: int,
    expected_stderr: str,
) -> None:
    base = _commit_modules(repo, {_ALPHA_MODULE: _ALPHA_TEST + _BETA_TEST + _GAMMA_TEST})
    _commit_modules(repo, head_modules)
    if ledger is not None:
        (repo / _LEDGER).parent.mkdir()
        (repo / _LEDGER).write_text(ledger, encoding="utf-8")

    exit_code = run_ci(base)

    assert (exit_code, expected_stderr in capsys.readouterr().err) == (expected_exit, True)


def test_run_ci_skips_a_change_without_rewrite_or_family_move(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _commit_modules(repo, {_ALPHA_MODULE: _ALPHA_TEST})
    _commit_modules(repo, {_ALPHA_MODULE: _ALPHA_TEST + _BETA_TEST})

    exit_code = run_ci(base)

    assert (exit_code, "skipping" in capsys.readouterr().out) == (0, True)
