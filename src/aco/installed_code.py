"""Whether the aco a process loaded is one complete install (`specs/mcp.spec.md`,
MCP-83, MCP-88). The installer rewrites the files of a running tool in place, so a process
that imports while it runs could hold modules of two installs. The standard library
alone is imported here, so this module loads before the rest of aco does."""

import base64
import hashlib
import importlib.metadata
import os
import sys
import sysconfig
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

DISTRIBUTION = "overnightworks-aco"
_PACKAGE = "aco"

type FileStamp = tuple[int, int, int, int]


@dataclass(frozen=True)
class Reading:
    """What the install looked like at one moment: the distribution's RECORD hash
    of each aco file (None when RECORD is missing), the stamp of each such file
    and the digest of the files asked for."""

    recorded: Mapping[Path, str | None] | None
    stamps: Mapping[Path, FileStamp] = field(default_factory=dict)
    digests: Mapping[Path, str] = field(default_factory=dict)


def installed_purelib() -> Path:
    """The purelib directory of the interpreter running this process."""
    return Path(sysconfig.get_path("purelib")).resolve()


def read(purelib: Path, digested: Iterable[Path] = ()) -> Reading:
    """The RECORD of the distribution in `purelib`, the stamps of its aco files and
    the digests of `digested` as RECORD writes them."""
    recorded = _recorded(purelib)
    stamps: dict[Path, FileStamp] = {}
    for path in (*(recorded or {}), *digested):
        stamp = _stamp(path)
        if stamp is not None:
            stamps[path] = stamp
    return Reading(recorded, stamps, {path: _digest(path) for path in digested})


def first_read(purelib: Path | None = None) -> Reading:
    """The reading taken before the rest of aco is imported."""
    return read(installed_purelib() if purelib is None else purelib)


def checked(
    first: Reading,
    main: Callable[[], int],
    *,
    purelib: Path | None = None,
    loaded: Sequence[Path] | None = None,
) -> int:
    """The exit status of `main` when the aco loaded since `first` is one complete
    install; else 1, with the file named on standard error and `main` not run."""
    purelib = installed_purelib() if purelib is None else purelib
    loaded = loaded_files() if loaded is None else loaded
    second = read(purelib, [path for path in loaded if path.is_relative_to(purelib)])
    changed = mismatch(first, second, loaded, purelib)
    if changed is None:
        return main()
    sys.stderr.write(f"the installed aco changed while this call loaded it: {changed}\n")
    return 1


def loaded_files() -> list[Path]:
    """The source file of every aco module loaded so far."""
    files: list[Path] = []
    for module in list(sys.modules.values()):
        spec = getattr(module, "__spec__", None)
        if spec is None or not spec.has_location or spec.origin is None:
            continue
        if spec.name == _PACKAGE or spec.name.startswith(f"{_PACKAGE}."):
            files.append(Path(spec.origin).resolve())
    return files


def mismatch(first: Reading, second: Reading, loaded: Sequence[Path], purelib: Path) -> str | None:
    """The file, or `RECORD`, that shows the aco loaded from `purelib` is no one
    complete install; None when it is one or no module came from `purelib`."""
    installed = [path for path in loaded if path.is_relative_to(purelib)]
    if not installed:
        return None
    if first.recorded is None or first.recorded != second.recorded:
        return "RECORD"
    for path in installed:
        expected = first.recorded.get(path)
        unchanged = path in first.stamps and first.stamps[path] == second.stamps.get(path)
        if expected is None or second.digests.get(path) != expected or not unchanged:
            return str(path)
    return None


def _recorded(purelib: Path) -> dict[Path, str | None] | None:
    distribution = next(
        iter(importlib.metadata.Distribution.discover(name=DISTRIBUTION, path=[str(purelib)])),
        None,
    )
    files = None if distribution is None else distribution.files
    if distribution is None or files is None:
        return None
    return {
        Path(str(distribution.locate_file(entry))).resolve(): (
            None if entry.hash is None or entry.hash.mode != "sha256" else entry.hash.value
        )
        for entry in files
        if entry.parts[0] == _PACKAGE
    }


def _stamp(path: Path) -> FileStamp | None:
    try:
        status = os.stat(path)
    except OSError:
        return None
    return (status.st_ino, status.st_size, status.st_mtime_ns, status.st_ctime_ns)


def _digest(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError:
        return ""
    return base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
