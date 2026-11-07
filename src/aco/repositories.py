"""The repositories aco serves: every checkout under the root aco's config
file names that tracks the board configuration, one per forge repository.

The root is `root = "<absolute path>"` in `$XDG_CONFIG_HOME/aco/config.toml`
(else `~/.config/aco/config.toml`). Every call to `discover` scans afresh, so a
checkout cloned or removed since the last call shows at once.
"""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from . import body, checkout, github, protocol, session, workboard

_GIT_DIRECTORY = ".git"
_CONFIG_FILE = Path("aco") / "config.toml"
_CONFIG_HOME_VARIABLE = "XDG_CONFIG_HOME"
_ROOT_KEY = "root"


class RootConfigError(protocol.ClaimError):
    """The config file does not name a usable root."""


class NoRepositoriesFoundError(protocol.ClaimError):
    """Nothing under the root tracks the board configuration."""

    def __init__(self, root: Path) -> None:
        super().__init__(f"no repository tracking {workboard.CONFIG_PATH.as_posix()} under {root}")


@dataclass(frozen=True)
class Repository:
    label: str
    """The forge repository, `owner/repo`."""
    directory: Path


@dataclass(frozen=True)
class UnavailableCheckout:
    directory: Path
    reason: str


@dataclass(frozen=True)
class Discovery:
    root: Path
    repositories: tuple[Repository, ...]
    """One per forge repository, in label order."""
    unavailable: tuple[UnavailableCheckout, ...]
    """Directories under the root that could not be read, in path order."""


def xdg_directory(
    environment: Mapping[str, str], variable: str, home: Path, *home_relative: str
) -> Path:
    """`$variable` when that is absolute, else `home` joined with `home_relative`."""
    base = environment.get(variable, "")
    return Path(base) if Path(base).is_absolute() else home.joinpath(*home_relative)


def config_path(environment: Mapping[str, str], home: Path) -> Path:
    return xdg_directory(environment, _CONFIG_HOME_VARIABLE, home, ".config") / _CONFIG_FILE


def configured_root(path: Path) -> Path:
    """The root `path` names, refused by name when it names none that exists."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise RootConfigError(
            f'{path} does not exist; create it with {_ROOT_KEY} = "<absolute path>"'
        ) from None
    except (OSError, UnicodeDecodeError) as error:
        raise RootConfigError(f"{path} cannot be read as UTF-8 text: {error}") from error
    try:
        root = tomllib.loads(text).get(_ROOT_KEY)
    except tomllib.TOMLDecodeError as error:
        raise RootConfigError(f"{path} is not valid TOML: {error}") from error
    if not isinstance(root, str):
        raise RootConfigError(f'{path} sets no {_ROOT_KEY} = "<absolute path>"')
    if not Path(root).is_absolute():
        raise RootConfigError(f"{path}: {_ROOT_KEY} {root} is not an absolute path")
    if not Path(root).is_dir():
        raise RootConfigError(f"{path}: {_ROOT_KEY} {root} is not a directory")
    return Path(root)


def discover(root: Path) -> Discovery:
    """Every checkout under `root`, scanned afresh; refused when it finds none.

    The walk stops at each checkout and follows no symlink. A checkout is a
    directory holding a `.git` directory, so linked worktrees and submodules
    drop out. Among clones of one repository the first sorted path wins.
    """
    directories, unreadable = _checkout_directories(root)
    winners: dict[str, Repository] = {}
    unavailable = list(unreadable)
    for directory in directories:
        try:
            repository = _tracking_repository(directory)
        except (protocol.ClaimError, OSError) as error:
            unavailable.append(UnavailableCheckout(directory, str(error)))
            continue
        if repository is not None:
            winners.setdefault(repository.label, repository)
    if not winners and not unavailable:
        raise NoRepositoriesFoundError(root)
    repositories = tuple(winners[label] for label in sorted(winners))
    return Discovery(
        root, repositories, tuple(sorted(unavailable, key=lambda entry: entry.directory))
    )


def _checkout_directories(root: Path) -> tuple[list[Path], list[UnavailableCheckout]]:
    checkouts: list[Path] = []
    unreadable: list[UnavailableCheckout] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        marker = directory / _GIT_DIRECTORY
        try:
            if marker.is_symlink() or marker.is_file():
                continue
            if marker.is_dir():
                checkouts.append(directory)
                continue
            pending.extend(
                Path(entry.path)
                for entry in os.scandir(directory)
                if entry.is_dir(follow_symlinks=False)
            )
        except OSError as error:
            unreadable.append(UnavailableCheckout(directory, error.strerror or str(error)))
    return sorted(checkouts), unreadable


def _tracking_repository(directory: Path) -> Repository | None:
    """The forge repository `directory` is a checkout of, read from its remote
    URL, or None when it does not track the board configuration."""
    if not checkout.path_is_tracked(workboard.CONFIG_PATH.as_posix(), directory=directory):
        return None
    # Looked up on the module at every call, so a replaced `run_context` (the
    # board's test forge) reaches every scan.
    context = session.run_context(None).for_directory(directory)
    # The remote URL alone names the repository: `repository_id` would ask `gh`
    # about a URL shape the GitHub pattern misses, a network call per scan.
    location = context.remote_location
    if context.config.storage is not body.Storage.STATE_REF:
        session.refuse_unsupported_forge_host(location)
        return Repository(github.repository_id(location.path).path, directory)
    return Repository(location.path, directory)
