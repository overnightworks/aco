"""Behavioral tests for the CI rewrite and family-move gates in `scripts/test_inventory.py`.

The CI gate cases drive the gate against a real, freshly initialized git repository under
`tmp_path`. Git itself is the boundary the gate queries, so faking its output would test
the wrong layer. Other cases pin discovery parity with `test_budget` and the decider's mark forms.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest
import test_budget
import test_inventory
from test_inventory import family_move_modules, rewritten_modules, run_ci


def _path(module: str) -> str:
    return f"tests/test_{module}.py"


def _numbered_lines(count: int) -> str:
    return "".join(f"assert {number} == {number}\n" for number in range(count))


def _test(name: str, *literals: str | int) -> str:
    """A test module fragment asserting each of *literals* (default: the name's own)."""
    asserted = literals or (f"{name}-literal",)
    body = "".join(f"    assert value == {literal!r}\n" for literal in asserted)
    return f"def test_{name}():\n{body}"


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
        (_numbered_lines(10), None, []),
        (None, _numbered_lines(10), []),
        (_numbered_lines(10), _numbered_lines(2), [_path("example")]),
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
    base = _commit_modules(repo, {_path("example"): base_content})
    _commit_modules(repo, {_path("example"): head_content})

    assert rewritten_modules(base) == expected


@pytest.mark.parametrize(
    ("base_modules", "head_modules", "expected"),
    [
        (
            {_path("alpha"): _test("alpha") + _test("beta")},
            {_path("alpha"): _test("alpha"), _path("beta"): _test("beta")},
            [_path("alpha"), _path("beta")],
        ),
        (
            {_path("alpha"): _test("alpha") + _test("beta")},
            {_path("alpha"): None, _path("beta"): _test("alpha") + _test("beta")},
            [_path("alpha"), _path("beta")],
        ),
        (
            {_path("alpha"): _test("alpha")},
            {_path("alpha"): _test("alpha"), _path("beta"): _test("beta")},
            [],
        ),
        (
            {_path("alpha"): _test("alpha") + _test("beta")},
            {_path("alpha"): _test("alpha")},
            [],
        ),
        (
            {_path("alpha"): _test("alpha") + _test("beta")},
            {_path("alpha"): _test("alpha") + _test("gamma")},
            [],
        ),
        (
            {_path("alpha"): _test("alpha") + _test("beta")},
            {_path("alpha"): _test("alpha") + _test("gamma"), _path("beta"): _test("delta")},
            [],
        ),
        (
            {_path("alpha"): _test("alpha", 0, "")},
            {_path("alpha"): _test("gamma", 0, ""), _path("beta"): _test("delta", 0, "")},
            [],
        ),
        (
            {_path("alpha"): _test("alpha", 0, "old-only")},
            {_path("alpha"): _test("gamma"), _path("beta"): _test("delta", 0)},
            [],
        ),
    ],
    ids=[
        "tests-moved-to-a-new-module",
        "module-deleted-while-another-gains-its-tests",
        "tests-added-without-any-leaving",
        "tests-removed-without-any-appearing",
        "tests-renamed-within-one-module",
        "rename-in-one-module-plus-an-unrelated-new-test-elsewhere",
        "rename-plus-an-unrelated-new-test-sharing-only-generic-literals",
        "a-lost-test-and-a-new-test-sharing-only-a-number-is-no-move",
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


def _moved_beta(*beta_literals: str) -> dict[str, str | None]:
    """The alpha module keeps two tests (it shrinks short of the rewrite threshold) while
    the beta test, with *beta_literals*, appears in a second module."""
    return {
        _path("alpha"): _test("alpha") + _test("gamma"),
        _path("beta"): _test("beta", *beta_literals),
    }


@pytest.mark.parametrize(
    ("head_modules", "ledger", "expected_exit", "expected_stdout", "expected_stderr"),
    [
        (_moved_beta("kept", "also-kept"), None, 0, "family move", ""),
        (_moved_beta("kept"), None, 1, "", "'also-kept'"),
        (
            _moved_beta("kept"),
            f"{_path('beta')}\t'also-kept'\treworded on purpose\n",
            0,
            "family move",
            "",
        ),
        (
            {
                _path("alpha"): _test("alpha"),
                _path("beta"): _test("beta", "kept", "also-kept") + _test("gamma"),
            },
            None,
            0,
            "family move",
            "",
        ),
    ],
    ids=[
        "move-keeping-every-literal-passes",
        "move-losing-a-literal-fails",
        "move-losing-a-ledgered-literal-passes",
        "module-rewritten-and-moved-gets-only-the-union-verdict",
    ],
)
def test_run_ci_judges_a_family_move_by_the_literal_union(
    repo: Path,
    capsys: pytest.CaptureFixture[str],
    head_modules: dict[str, str | None],
    ledger: str | None,
    expected_exit: int,
    expected_stdout: str,
    expected_stderr: str,
) -> None:
    base = _commit_modules(
        repo, {_path("alpha"): _test("alpha") + _test("beta", "kept", "also-kept") + _test("gamma")}
    )
    _commit_modules(repo, head_modules)
    if ledger is not None:
        (repo / test_inventory.DROPPED_REL).parent.mkdir()
        (repo / test_inventory.DROPPED_REL).write_text(ledger, encoding="utf-8")

    exit_code = run_ci(base)

    captured = capsys.readouterr()
    assert (exit_code, expected_stdout in captured.out, expected_stderr in captured.err) == (
        expected_exit,
        True,
        True,
    )
    assert "rewrite" not in captured.out + captured.err


def test_run_ci_still_judges_a_rewrite_when_an_unrelated_test_shares_only_a_generic_literal(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _commit_modules(
        repo,
        {
            _path("alpha"): _test("alpha", "must-preserve", 0),
            _path("beta"): _test("beta", "must-preserve"),
        },
    )
    _commit_modules(
        repo,
        {
            _path("alpha"): _test("renamed", "reworded"),
            _path("beta"): _test("beta", "must-preserve") + _test("gamma", 0),
        },
    )

    exit_code = run_ci(base)

    assert (exit_code, "'must-preserve'" in capsys.readouterr().err) == (1, True)


def test_run_ci_skips_a_change_without_rewrite_or_family_move(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _commit_modules(repo, {_path("alpha"): _test("alpha")})
    _commit_modules(repo, {_path("alpha"): _test("alpha") + _test("beta")})

    exit_code = run_ci(base)

    assert (exit_code, "skipping" in capsys.readouterr().out) == (0, True)


@pytest.mark.parametrize(
    ("source", "expected_qualname"),
    [
        ("def test_flat():\n    pass\n", "test_flat"),
        ("class TestGroup:\n    def test_member(self):\n        pass\n", "TestGroup::test_member"),
        (
            "class TestOuter:\n    class TestInner:\n        def test_deep(self): pass\n",
            "TestOuter::TestInner::test_deep",
        ),
    ],
)
def test_both_gates_find_the_same_tests_at_any_class_depth(
    tmp_path: Path, source: str, expected_qualname: str
) -> None:
    module = tmp_path / "tests" / "test_example.py"
    module.parent.mkdir()
    module.write_text(source, encoding="utf-8")
    tree = ast.parse(source)

    inventory_cases, _classes, _single = test_inventory.iter_tests(
        tree, test_inventory.module_scope(tree)
    )
    budget_tests = test_budget.measure(tmp_path)["tests"].tests

    assert ([case.qualname for case in inventory_cases], budget_tests) == ([expected_qualname], 1)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("@pytest.mark.parametrize('value', [1])\ndef test_value(value): pass", True),
        ("@parametrize('value', [1])\ndef test_value(value): pass", True),
        (
            "pytestmark = [pytest.mark.parametrize('value', [1])]\ndef test_value(value): pass",
            True,
        ),
        (
            "@pytest.mark.parametrize('value', [1])\n"
            "class TestValues:\n    def test_value(self, value): pass",
            True,
        ),
        ("def test_value(): pass", False),
    ],
    ids=["attribute", "bare", "pytestmark", "enclosing-class", "unparametrized"],
)
def test_inventory_recognizes_parametrized_tests(source: str, expected: bool) -> None:
    tree = ast.parse(source)

    cases, _classes, _single = test_inventory.iter_tests(tree, test_inventory.module_scope(tree))

    assert [case.parametrized for case in cases] == [expected]
    assert [
        test_inventory.is_parametrized(func, owners, tree)
        for owners, func in test_inventory.iter_test_functions(tree.body)
    ] == [expected]
