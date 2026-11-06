"""The list of code built ahead of its caller (`specs/ahead-of-caller.spec.md`):
its record, the pure parser of the trunk's file and the red verdict."""

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from . import forge, github, protocol, workboard

LIST_PATH = ".aco/ahead-of-caller.toml"

_ENTRY_KEYS = ("path", "item", "reason")


class ItemState(StrEnum):
    """What the forge answered for an entry's item."""

    OPEN = "open"
    CLOSED = "closed"
    MISSING = "missing"
    PULL_REQUEST = "pull_request"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class ItemTarget:
    """The item an entry names: a number in this repository
    (`repository` is `None`) or in another one."""

    repository: forge.RepositoryId | None
    number: int


@dataclass(frozen=True)
class Entry:
    path: str
    item: ItemTarget
    reason: str


@dataclass(frozen=True)
class JudgedEntry:
    """An entry beside the state its item was read in; `error` holds the
    forge's text only for `ItemState.UNREADABLE`."""

    entry: Entry
    state: ItemState
    error: str | None = None


@dataclass(frozen=True)
class Unavailable:
    """The list cannot be read: one sentence names why."""

    sentence: str


def is_red(state: ItemState) -> bool:
    return state is not ItemState.OPEN


def state_of(reference: forge.ItemReference) -> ItemState:
    if reference.state is forge.ItemState.MISSING:
        return ItemState.MISSING
    if reference.is_landing:
        return ItemState.PULL_REQUEST
    return ItemState.OPEN if reference.state is forge.ItemState.OPEN else ItemState.CLOSED


def _item_target(item: str) -> ItemTarget:
    repository_text, separator, number_text = item.rpartition("#")
    if "/" not in repository_text:
        return ItemTarget(None, workboard.parse_item_reference(item))
    number = protocol.decimal_number_or_none(number_text)
    if not separator or number is None:
        raise protocol.ClaimError(f"{item!r} is not OWNER/REPO#n")
    return ItemTarget(github.repository_id(repository_text), number)


def _path_defect(path: str) -> str | None:
    if not path or path.startswith("/") or "\\" in path:
        return "is not repository-relative with forward slashes"
    if ".." in PurePosixPath(path).parts:
        return "holds a '..' segment"
    return None


def _key_defect(table: dict[str, object]) -> str | None:
    for key in _ENTRY_KEYS:
        if key not in table:
            return f"lacks '{key}'"
        if not isinstance(table[key], str):
            return f"has '{key}' that is not a string"
    extra = sorted(set(table) - set(_ENTRY_KEYS))
    return f"has the unknown key '{extra[0]}'" if extra else None


def _text_defect(path: str, reason: str) -> str | None:
    path_defect = _path_defect(path)
    if path_defect is not None:
        return f"has a path that {path_defect}"
    if not reason.strip() or "\n" in reason or "\r" in reason:
        return "has a reason that is not one non-empty line"
    return None


def _entry_or_sentence(position: int, table: dict[str, object]) -> Entry | str:
    where = f"{LIST_PATH}: code entry {position}"
    defect = _key_defect(table)
    if defect is not None:
        return f"{where} {defect}"
    path, item, reason = (str(table[key]) for key in _ENTRY_KEYS)
    defect = _text_defect(path, reason)
    if defect is not None:
        return f"{where} {defect}"
    try:
        target = _item_target(item)
    except protocol.ClaimError:
        return f"{where} has an item {item!r} that is not aco-xxxxxx, #n, n or OWNER/REPO#n"
    return Entry(path, target, reason)


def parse(text: str) -> tuple[Entry, ...] | Unavailable:
    """The entries `text` lists, or the one sentence that names why the file
    is malformed."""
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        return Unavailable(f"{LIST_PATH} is not valid TOML: {error}")
    unknown = sorted(set(document) - {"code"})
    if unknown:
        return Unavailable(f"{LIST_PATH} has the unknown top-level key '{unknown[0]}'")
    tables = document.get("code", [])
    if not isinstance(tables, list) or not all(isinstance(table, dict) for table in tables):
        return Unavailable(f"{LIST_PATH}: 'code' must be an array of tables")
    entries: list[Entry] = []
    seen: set[tuple[str, ItemTarget]] = set()
    for position, table in enumerate(tables, start=1):
        parsed = _entry_or_sentence(position, table)
        if isinstance(parsed, str):
            return Unavailable(parsed)
        if (parsed.path, parsed.item) in seen:
            return Unavailable(
                f"{LIST_PATH}: code entry {position} repeats the path and item of an earlier entry"
            )
        seen.add((parsed.path, parsed.item))
        entries.append(parsed)
    return tuple(entries)
