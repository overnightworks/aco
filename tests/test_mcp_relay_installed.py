"""`aco mcp` running from the site-packages of a venv (`specs/mcp.spec.md`,
MCP-82, MCP-83, MCP-88): an install caught half written is answered loudly and the same
relay answers from the finished install on its next call."""

import os
import subprocess
import sys
from pathlib import Path

import install_world
import relay_world

import aco


def _venv_with_aco(directory: Path) -> tuple[Path, Path, dict[str, bytes]]:
    """A venv whose purelib holds aco as an installer leaves it: the interpreter,
    the purelib and the files by name under `aco/`."""
    subprocess.run(  # noqa: S603 - the interpreter running these tests
        [sys.executable, "-m", "venv", "--without-pip", str(directory)], check=True
    )
    python = directory / "bin" / "python"
    purelib = Path(
        subprocess.run(  # noqa: S603 - the interpreter just created
            [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    package = relay_world.copy_package(purelib)
    files = {
        str(path.relative_to(package)): path.read_bytes()
        for path in package.rglob("*")
        if path.is_file()
    }
    install_world.write_record(purelib, files)
    return python, purelib, files


def test_an_install_caught_half_written_is_refused_and_the_finished_one_is_served(
    tmp_path: Path,
) -> None:
    python, purelib, files = _venv_with_aco(tmp_path / "venv")
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    version_file = purelib / "aco" / "__init__.py"
    installed_version = aco.__version__

    with relay_world.started([str(python), "-P", "-m", "aco", "mcp"], environment) as relay:
        first = relay.ask(1, "initialize")
        version_file.write_text('__version__ = "99.0.0"\n', encoding="utf-8")
        refused = relay.ask(2, "initialize")
        install_world.write_record(purelib, {**files, "__init__.py": version_file.read_bytes()})
        finished = relay.ask(3, "initialize")
        relay.finish()

    assert first["result"]["serverInfo"]["version"] == installed_version
    assert "the installed aco changed while this call loaded it" in refused["error"]["message"]
    assert finished["result"]["serverInfo"]["version"] == "99.0.0"
