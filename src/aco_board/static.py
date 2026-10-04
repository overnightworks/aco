"""The board's SPA shell and its built assets -- `/` and `/assets/**`.

Every file this module can serve is a committed build output (`frontend/`,
built by `pnpm build`, tracked under `static/`), never request data, so
containment guards against a malformed request path, not an untrusted
upload: no `..` segment, no percent-encoded separator, no symlink anywhere
between `STATIC_ROOT` and the file, whichever of those a request tries.
`server.py` owns the token policy (none, here) and the guard headers; this
module owns only which file a path names and how to read it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

STATIC_ROOT = Path(__file__).resolve().parent / "static"
SHELL_FILENAME = "index.html"
ASSETS_PREFIX = "/assets/"
_ASSETS_DIRNAME = "assets"
"""`ASSETS_PREFIX` names a URL path; the files it serves sit one directory
level down from `STATIC_ROOT`, under this name."""

_SHELL_CONTENT_TYPE = "text/html; charset=utf-8"
_ASSET_CONTENT_TYPES = {".js": "text/javascript; charset=utf-8"}
"""Every extension `frontend/vite.config.ts` actually emits into `static/assets/`
(fixed filenames, no content hash -- see that file's own docstring); a request
for any other extension is refused rather than guessed."""


class StaticAssetsMissingError(Exception):
    """`STATIC_ROOT` holds no built shell: an editable checkout whose frontend
    was never built, or a package installed without its data."""


@dataclass(frozen=True)
class StaticFile:
    content: bytes
    content_type: str


def ensure_built(root: Path | None = None) -> None:
    """Raise with a clear sentence before the board starts if the frontend was
    never built, rather than let the first request fail unreadably."""
    shell_path = (STATIC_ROOT if root is None else root) / SHELL_FILENAME
    if not shell_path.is_file():
        raise StaticAssetsMissingError(
            f"{shell_path} is missing; build the frontend first "
            "(pnpm --dir frontend install --frozen-lockfile && "
            "pnpm --dir frontend build)"
        )


def shell(root: Path | None = None) -> StaticFile:
    """The SPA shell `GET /` answers with; call only after `ensure_built`."""
    shell_path = (STATIC_ROOT if root is None else root) / SHELL_FILENAME
    return StaticFile(content=shell_path.read_bytes(), content_type=_SHELL_CONTENT_TYPE)


def asset(request_path: str, root: Path | None = None) -> StaticFile | None:
    """The file `request_path` (beginning `ASSETS_PREFIX`) names under
    `root`'s `assets/` directory, or None unless it is a contained,
    recognized-type, regular file."""
    base = STATIC_ROOT if root is None else root
    resolved = resolve_contained(base / _ASSETS_DIRNAME, request_path.removeprefix(ASSETS_PREFIX))
    if resolved is None:
        return None
    content_type = _ASSET_CONTENT_TYPES.get(resolved.suffix)
    if content_type is None:
        return None
    return StaticFile(content=resolved.read_bytes(), content_type=content_type)


def resolve_contained(root: Path, relative_path: str) -> Path | None:
    """The real file `relative_path` names under `root`, or None if it would
    escape `root` -- directly with a literal or percent-encoded `..`, or by
    way of a symlink anywhere between `root` and the file.

    A path with no symlink in it resolves to exactly itself; `resolved !=
    candidate` below is what catches one, wherever it sits.
    """
    decoded = unquote(relative_path)
    if "\0" in decoded:
        return None
    segments = [segment for segment in decoded.split("/") if segment not in ("", ".")]
    if not segments or any(segment == ".." for segment in segments):
        return None
    try:
        resolved_root = root.resolve(strict=True)
    except OSError:
        return None
    candidate = resolved_root.joinpath(*segments)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    # `resolved_root == root` catches `root` itself -- or a directory above it,
    # up to `STATIC_ROOT` -- being a symlink: resolving it would otherwise move
    # the containment boundary to wherever that symlink points.
    contained = (
        resolved_root == root and resolved == candidate and resolved.is_relative_to(resolved_root)
    )
    if not contained or not resolved.is_file():
        return None
    return resolved
