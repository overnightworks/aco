"""The board's access token, kept in a user-only file so it survives restarts.

Deleting the file rotates the token. The file is the user's own state: it is
created user-only and not policed afterwards, but its content may come from a
file this process did not write, so it is validated before use (ABRD-96).
"""

from __future__ import annotations

import os
import re
import secrets
import tempfile
from collections.abc import Mapping
from pathlib import Path

_TOKEN_BYTES = 32
_TOKEN_SHAPE = re.compile(rb"[A-Za-z0-9_-]{43,}\n?")
_DIRECTORY_MODE = 0o700


class MalformedTokenFileError(Exception):
    """The token file holds something other than one token."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path} holds no board token")
        self.path = path


def token_path(environment: Mapping[str, str], home: Path) -> Path:
    """`$XDG_STATE_HOME/aco/board-token` when that is absolute, else under `home`."""
    state_home = environment.get("XDG_STATE_HOME", "")
    base = Path(state_home) if Path(state_home).is_absolute() else home / ".local" / "state"
    return base / "aco" / "board-token"


def board_token(path: Path) -> str:
    """The token `path` holds; a missing file is created with a fresh token first.

    The file appears only through an exclusive link of a fully written temporary
    file, so a concurrent first start reads the winner's token.
    """
    try:
        return _read(path)
    except FileNotFoundError:
        pass
    _make_missing_directories(path.parent)
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    # mkstemp creates the file 0600 and the write lands before the link, so no
    # reader ever sees a partial token.
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".board-token-")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(token)
        os.link(temporary, path)
    except FileExistsError:
        return _read(path)
    finally:
        temporary.unlink()
    return token


def _make_missing_directories(directory: Path) -> None:
    """Create each missing directory `0700`; `Path.mkdir` would not for ancestors."""
    missing = [candidate for candidate in (directory, *directory.parents) if not candidate.exists()]
    for candidate in reversed(missing):
        candidate.mkdir(mode=_DIRECTORY_MODE, exist_ok=True)


def _read(path: Path) -> str:
    content = path.read_bytes()
    if _TOKEN_SHAPE.fullmatch(content) is None:
        raise MalformedTokenFileError(path)
    return content.decode("ascii").removesuffix("\n")
