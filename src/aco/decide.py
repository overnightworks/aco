"""The one read-modify-write of expectation lines (`specs/rule.spec.md`,
`specs/withdraw.spec.md`): `aco rule`, `aco withdraw` and the decision board
read an item through the target gate and write its folded body once, here,
so every ruling and every withdrawal takes the same path. A writer reads and
writes inside `turn`, which serializes the writers of one item on this machine."""

import hashlib
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import board_read, body, expectations, file_lock, forge, protocol, repositories, workboard
from .session import RunContext

type Outcome = expectations.OptionChoice | expectations.HeadReturn


class InvalidTargetError(protocol.ClaimError):
    """The target gate's own "no such writable item" refusal -- missing, a pull request,
    or a malformed body -- so a command can choose its `invalid_item` without parsing
    prose."""


@dataclass(frozen=True)
class LineOutcome:
    """The outcome decided for one 1-based expectation line."""

    index: int
    outcome: Outcome


@dataclass(frozen=True)
class FreshItem:
    """One item as the target gate read it from the forge. `state` is open or
    closed as that read saw it; `aco rule` and `aco withdraw` write either, and
    the decision board refuses a card whose item was closed since its page
    read it."""

    number: int
    title: str
    body: str
    storage: body.Storage
    state: forge.ItemState


@dataclass(frozen=True)
class Committed:
    """The item as written: `lines` are every expectation line of the written body."""

    number: int
    title: str
    lines: tuple[expectations.ExpectationLine, ...]
    open_remaining: int


def fresh_item(context: RunContext, number: int, *, command: str) -> FreshItem:
    """The target gate (RULE-07, RULE-08, WITHDRAW-10, WITHDRAW-11): one forge
    read of the item, which must exist and not be a pull request, and whose
    body must parse; its refusals name `command`. A failed forge read stays a
    `forge.ForgeError`, never a refused target (RULE-11, WITHDRAW-13)."""
    client = context.forge_writer
    storage = context.config.storage
    try:
        reference = board_read.item_or_refuse(client, number, command=command, storage=storage)
        current_body = reference.body or ""
        workboard.located_block_or_refuse(number, current_body, command=command, storage=storage)
    except forge.ForgeError:
        raise
    except protocol.ClaimError as error:
        raise InvalidTargetError(str(error)) from error
    return FreshItem(number, reference.title or "", current_body, storage, reference.state)


class ItemLockUnavailableError(protocol.ClaimUnavailableError):
    """The per-item lock file could not be created or locked, so nothing was read or written."""


def _item_lock_path(
    context: RunContext, number: int, environment: Mapping[str, str], home: Path
) -> Path:
    """One flat file per item of a forge repository under aco's state directory,
    named by a digest so no remote path can place it elsewhere."""
    repository = context.remote_repository_id
    key = f"{repository.host}\0{repository.path}\0{number}"
    state = repositories.xdg_directory(environment, "XDG_STATE_HOME", home, ".local", "state")
    return state / "aco" / "item-locks" / hashlib.sha256(key.encode()).hexdigest()


@contextmanager
def turn(
    context: RunContext,
    number: int,
    *,
    command: str,
    environment: Mapping[str, str],
    home: Path,
) -> Iterator[FreshItem]:
    """The per-item turn: holds the item's lock, reads it fresh through the target
    gate and yields that read; the caller writes at most once before the turn
    ends. Not re-entrant. An unwritable lock directory refuses with
    `ItemLockUnavailableError` before any read or write."""
    # The context refuses what it refuses (`--repo` under `state-ref`, no
    # recognised host) when it builds its forge, before any lock is taken.
    _ = context.forge_writer
    lock_path = _item_lock_path(context, number, environment, home)
    with ExitStack() as held:
        try:
            held.enter_context(file_lock.held(lock_path))
        except OSError as error:
            raise ItemLockUnavailableError(f"cannot lock the item at {lock_path}: {error}") from error
        yield fresh_item(context, number, command=command)


def _written_body(current_body: str, line: int, outcome: Outcome, today: date) -> str:
    if isinstance(outcome, expectations.HeadReturn):
        return expectations.return_to_head(current_body, line, outcome, today)
    return expectations.rule_option(current_body, line, outcome, today)


def _committed(context: RunContext, fresh: FreshItem, new_body: str) -> Committed:
    """Writes `new_body` once and reads back the lines it holds."""
    context.forge_writer.update_item_body(fresh.number, new_body)
    lines = tuple(expectations.expectation_lines(new_body, storage=fresh.storage))
    open_remaining = sum(map(expectations.is_open, lines))
    return Committed(fresh.number, fresh.title, lines, open_remaining)


def rule(
    context: RunContext, fresh: FreshItem, named: Sequence[LineOutcome], today: date
) -> Committed:
    """Folds every named line over the fresh body with the one date `today` and
    writes it once. Raises `protocol.ClaimError` by name for every refusal
    (already ruled, out of range, a changed card, a bad outcome) before the
    write, so none of the lines is stored (RULE-29)."""
    new_body = fresh.body
    for line in named:
        new_body = _written_body(new_body, line.index, line.outcome, today)
    return _committed(context, fresh, new_body)


def withdraw(
    context: RunContext, fresh: FreshItem, indexes: Sequence[int], today: date
) -> Committed:
    """Withdraws every named line of the fresh body with the one date `today`
    and writes it once. Raises `protocol.ClaimError` by name for every refusal
    (out of range, already withdrawn, ruled) before the write, so none of the
    lines is stored (WITHDRAW-04)."""
    new_body = fresh.body
    for index in indexes:
        new_body = expectations.withdraw_line(new_body, index, today)
    return _committed(context, fresh, new_body)
