"""Whether a process loaded one complete install of aco (`specs/mcp.spec.md`,
MCP-83, MCP-88), driven over a purelib directory the test writes."""

import runpy
import sys
from collections.abc import Callable
from pathlib import Path

import install_world
import pytest

from aco import installed_code

_OLD = {"__init__.py": b"VERSION = 1\n", "cli.py": b"OLD = 1\n"}
_NEW = {"__init__.py": b"VERSION = 1\n", "cli.py": b"NEW = 2\n"}
_MAIN_RESULT = 7


def _rewrite(path: Path, content: bytes) -> None:
    path.unlink()
    path.write_bytes(content)


def _install_finishes(purelib: Path, paths: list[Path]) -> None:
    """The record is written first, then the module it lists is replaced."""
    install_world.write_record(purelib, _NEW)
    _rewrite(paths[1], _NEW["cli.py"])


@pytest.mark.parametrize(
    ("change", "refused"),
    [
        (lambda purelib, paths: None, None),
        (lambda purelib, paths: _rewrite(paths[1], b"OTHER = 3\n"), "cli.py"),
        (lambda purelib, paths: paths[1].write_bytes(b"NEW = 2\n"), "cli.py"),
        (
            lambda purelib, paths: install_world.write_record(purelib, {"cli.py": b"OLD = 1\n"}),
            "RECORD",
        ),
        (lambda purelib, paths: install_world.write_record(purelib, _NEW), "RECORD"),
        (_install_finishes, "RECORD"),
        (
            lambda purelib, paths: (
                purelib / install_world.DISTRIBUTION_DIRECTORY / "RECORD"
            ).unlink(),
            "RECORD",
        ),
        (lambda purelib, paths: paths[1].unlink(), "RECORD"),
        (lambda purelib, paths: _rewrite(paths[1], _OLD["cli.py"]), "cli.py"),
    ],
    ids=[
        "an install nothing touched",
        "a module replaced with other bytes",
        "a module rewritten in place",
        "a module the record no longer lists",
        "a record replaced by another install's",
        "a record written first and a module replaced after it",
        "a record that went missing",
        "a module that was deleted",
        "a module replaced with the same bytes",
    ],
)
def test_the_loaded_aco_is_refused_unless_it_is_one_complete_install(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    change: Callable[[Path, list[Path]], None],
    refused: str | None,
) -> None:
    purelib = tmp_path / "purelib"
    paths = install_world.install(purelib, _OLD)
    first = installed_code.first_read(purelib)
    change(purelib, paths)

    exit_code = installed_code.checked(first, lambda: _MAIN_RESULT, purelib=purelib, loaded=paths)

    error = capsys.readouterr().err
    if refused is None:
        assert (exit_code, error) == (_MAIN_RESULT, "")
    else:
        assert exit_code == 1
        assert error.startswith("the installed aco changed while this call loaded it: ")
        assert error.strip().endswith(refused)


def test_a_loaded_module_with_no_stamp_from_the_first_read_is_refused_though_its_bytes_match(
    tmp_path: Path,
) -> None:
    purelib = tmp_path / "purelib"
    [_, module] = install_world.install(purelib, _OLD)
    reading = installed_code.read(purelib, [module])
    unstamped = installed_code.Reading(reading.recorded, {}, {})

    refused = installed_code.mismatch(unstamped, reading, [module], purelib)

    assert refused == str(module)


def test_a_loaded_module_is_refused_when_no_record_was_there_from_the_start(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    purelib = tmp_path / "purelib"
    [_, module] = install_world.install(purelib, _OLD)
    (purelib / install_world.DISTRIBUTION_DIRECTORY / "RECORD").unlink()
    first = installed_code.first_read(purelib)

    exit_code = installed_code.checked(
        first, lambda: _MAIN_RESULT, purelib=purelib, loaded=[module]
    )

    assert exit_code == 1
    assert capsys.readouterr().err.strip().endswith("RECORD")


def test_a_module_the_record_does_not_list_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    purelib = tmp_path / "purelib"
    paths = install_world.install(purelib, _OLD)
    extra = purelib / "aco" / "extra.py"
    extra.write_bytes(b"EXTRA = 1\n")
    first = installed_code.first_read(purelib)

    exit_code = installed_code.checked(
        first, lambda: _MAIN_RESULT, purelib=purelib, loaded=[*paths, extra.resolve()]
    )

    assert exit_code == 1
    assert capsys.readouterr().err.strip().endswith("extra.py")


@pytest.mark.parametrize("with_record", [True, False], ids=["with a record", "without one"])
def test_a_source_run_that_loaded_nothing_from_purelib_is_never_refused(
    tmp_path: Path, with_record: bool
) -> None:
    purelib = tmp_path / "purelib"
    if with_record:
        install_world.install(purelib, _OLD)
    else:
        purelib.mkdir()
    source = tmp_path / "src" / "aco" / "cli.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"SOURCE = 1\n")
    first = installed_code.first_read(purelib)

    exit_code = installed_code.checked(
        first, lambda: _MAIN_RESULT, purelib=purelib, loaded=[source.resolve()]
    )

    assert exit_code == _MAIN_RESULT


def test_the_loaded_files_are_the_sources_of_the_aco_modules_of_this_process() -> None:
    loaded = installed_code.loaded_files()

    assert Path(installed_code.__file__).resolve() in loaded
    assert all(path.suffix == ".py" for path in loaded)


def test_checked_asks_the_interpreters_own_purelib_by_default() -> None:
    first = installed_code.first_read()

    exit_code = installed_code.checked(first, lambda: _MAIN_RESULT)

    assert exit_code == _MAIN_RESULT


def test_running_the_package_prints_its_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["aco", "--version"])

    with pytest.raises(SystemExit) as ended:
        runpy.run_module("aco", run_name="__main__")

    assert ended.value.code == 0
    assert capsys.readouterr().out.startswith("aco ")
