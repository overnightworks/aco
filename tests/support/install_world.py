"""A purelib directory holding an installed aco with its RECORD, as an installer
writes them."""

import base64
import hashlib
from pathlib import Path

DISTRIBUTION_DIRECTORY = "overnightworks_aco-1.dist-info"


def record_row(relative: str, content: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
    return f"{relative},sha256={digest},{len(content)}"


def install(purelib: Path, files: dict[str, bytes]) -> list[Path]:
    """Writes `files` (names under `aco/`) and a RECORD listing them; the files' paths."""
    purelib.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, content in files.items():
        path = purelib / "aco" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        paths.append(path.resolve())
    write_record(purelib, files)
    return paths


def write_record(purelib: Path, files: dict[str, bytes]) -> None:
    metadata = purelib / DISTRIBUTION_DIRECTORY
    metadata.mkdir(exist_ok=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: overnightworks-aco\nVersion: 1\n", encoding="utf-8"
    )
    rows = [record_row(f"aco/{name}", content) for name, content in files.items()]
    (metadata / "RECORD").write_text("\n".join([*rows, ""]), encoding="utf-8")
