"""The one read-modify-write of expectation lines (`specs/rule.spec.md`,
`specs/withdraw.spec.md`): `aco rule`, `aco withdraw` and the decision board
read an item through the target gate and write its folded body once, here,
so every ruling and every withdrawal takes the same path. `item_lock` serializes
the writers of one item on this machine; `turn` is that lock plus the fresh read,
and a writer that judges from another read (`aco cut`) holds `item_lock` alone."""

import hashlib
import sys
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
    located: body.LocatedBlock


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
        located = workboard.located_block_or_refuse(
            number, current_body, command=command, storage=storage
        )
    except forge.ForgeError:
        raise
    except protocol.ClaimError as error:
        raise InvalidTargetError(str(error)) from error
    return FreshItem(number, reference.title or "", current_body, storage, reference.state, located)


class ItemLockUnavailableError(protocol.ClaimUnavailableError):
    """The per-item lock file could not be created or locked, so nothing was read or written."""


def _item_lock_path(
    context: RunContext, number: int, environment: Mapping[str, str], home: Path
) -> Path:
    """One flat file per item of a forge repository under aco's state directory,
    named by a digest so no remote path can place it elsewhere."""
    repository = context.remote_repository_id
    key = f"{repository.host}\0{repository.path}\0{number}"
    state = repositories.state_directory(environment, home)
    return state / "item-locks" / hashlib.sha256(key.encode()).hexdigest()


@contextmanager
def item_lock(
    context: RunContext, number: int, *, environment: Mapping[str, str], home: Path
) -> Iterator[None]:
    """The item's lock, the one every item-body write holds (RULE-40): a holder
    already running makes this say so once on stderr (RULE-42) and wait. Not
    re-entrant. An unwritable lock directory refuses with `ItemLockUnavailableError`
    before anything is read or written."""
    # The target's own refusals (`--repo` under `state-ref`, no recognised host)
    # come first; the forge, which reads and caches items, is built after the lock.
    _ = context.repository_id
    lock_path = _item_lock_path(context, number, environment, home)

    def say_waiting() -> None:
        sys.stderr.write(f"waiting for the item lock at {lock_path}\n")
        sys.stderr.flush()

    with ExitStack() as held:
        try:
            held.enter_context(file_lock.held(lock_path, say_waiting))
        except OSError as error:
            raise ItemLockUnavailableError(
                f"cannot lock the item at {lock_path}: {error.strerror or str(error)}"
            ) from error
        yield


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
    ends. Not re-entrant."""
    with item_lock(context, number, environment=environment, home=home):
        yield fresh_item(context, number, command=command)


def _written_body(current_body: str, line: int, outcome: Outcome, today: date) -> str:
    if isinstance(outcome, expectations.HeadReturn):
        return expectations.return_to_head(current_body, line, outcome, today)
    return expectations.rule_option(current_body, line, outcome, today)


def write_item_body(
    client: forge.ForgeWriter, number: int, new_body: str, *, replacing: str
) -> bool:
    """The one owner of an item-body write: `replacing` is the text the caller
    read under the item's lock. A body equal to it writes nothing and returns
    False, since a write that repeats the current body leaves no revision for
    the port's check to find."""
    if new_body == replacing:
        return False
    client.update_item_body(number, new_body, replacing=replacing)
    return True


def _committed(context: RunContext, fresh: FreshItem, new_body: str) -> Committed:
    """Writes `new_body` once and reads back the lines it holds."""
    write_item_body(context.forge_writer, fresh.number, new_body, replacing=fresh.body)
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
