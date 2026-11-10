"""The one read-modify-write of an item's block (`specs/rule.spec.md`,
`specs/withdraw.spec.md`, `specs/mcp.spec.md`): `aco rule`, `aco withdraw`, the
decision board and the MCP `ask`, `record_answer` and `step` read an item through the
target gate and write its folded body once, here, so every ruling, withdrawal, card and
step takes the same path, and a ruling or withdrawal touches the item's signal
(`specs/wait.spec.md`). `item_lock` serializes the writers of one item on this
machine; `turn` is that lock plus the fresh read, and a writer that judges from
another read (`aco cut`) holds `item_lock` alone."""

import hashlib
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

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
    read it. `author_is_member` says whether a member wrote it, as the inbox
    and the board decide whom they list."""

    number: int
    title: str
    body: str
    storage: body.Storage
    state: forge.ItemState
    located: body.LocatedBlock
    author_is_member: bool


@dataclass(frozen=True)
class Asked:
    """The answer to an ask: the option line the card stands as, and whether
    this call wrote it (False when the same card already stood)."""

    line: expectations.OptionLine
    written: bool


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
    return FreshItem(
        number,
        reference.title or "",
        current_body,
        storage,
        reference.state,
        located,
        reference.author_is_member,
    )


class ItemLockUnavailableError(protocol.ClaimUnavailableError):
    """The per-item lock file could not be created or locked, so nothing was read or written."""


def _item_state_file(context: RunContext, number: int, state: Path, *, directory: str) -> Path:
    """One flat file per item of a forge repository in `directory` under aco's
    state directory `state`, named by a digest so no remote path can place it
    elsewhere. The lock and the signal of one item share the digest."""
    repository = context.remote_repository_id
    key = f"{repository.host}\0{repository.path}\0{number}"
    return state / directory / hashlib.sha256(key.encode()).hexdigest()


def _item_lock_path(
    context: RunContext, number: int, environment: Mapping[str, str], home: Path
) -> Path:
    state = repositories.state_directory(environment, home)
    return _item_state_file(context, number, state, directory="item-locks")


def item_signal_path(context: RunContext, number: int, state: Path) -> Path:
    """The file `rule` and `withdraw` touch after a verified write of a ruled,
    returned or withdrawn line (WAIT-12) and `aco wait` watches, under aco's
    state directory `state` (`repositories.state_directory`)."""
    return _item_state_file(context, number, state, directory="item-signals")


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


def _committed_and_signalled(
    context: RunContext,
    fresh: FreshItem,
    new_body: str,
    state: Path,
) -> Committed:
    """`_committed`, then the item's signal touched (WAIT-12). A signal that
    cannot be touched never fails the write that stands: one warning goes to
    stderr and a waiting command learns the change by its slow read (WAIT-13)."""
    committed = _committed(context, fresh, new_body)
    signal = item_signal_path(context, fresh.number, state)
    try:
        signal.parent.mkdir(parents=True, exist_ok=True)
        signal.touch()
    except OSError as error:
        sys.stderr.write(
            f"WARNING: the ruling stands, but its signal at {signal} "
            f"could not be touched: {error.strerror or str(error)}\n"
        )
        sys.stderr.flush()
    return committed


def rule(
    context: RunContext,
    fresh: FreshItem,
    named: Sequence[LineOutcome],
    today: date,
    *,
    state: Path,
) -> Committed:
    """Folds every named line over the fresh body with the one date `today` and
    writes it once, then touches the item's signal. Raises `protocol.ClaimError`
    by name for every refusal (already ruled, out of range, a changed card, a
    bad outcome) before the write, so none of the lines is stored (RULE-29)."""
    new_body = fresh.body
    for line in named:
        new_body = _written_body(new_body, line.index, line.outcome, today)
    return _committed_and_signalled(context, fresh, new_body, state)


def withdraw(
    context: RunContext,
    fresh: FreshItem,
    indexes: Sequence[int],
    today: date,
    *,
    state: Path,
) -> Committed:
    """Withdraws every named line of the fresh body with the one date `today`
    and writes it once, then touches the item's signal. Raises
    `protocol.ClaimError` by name for every refusal (out of range, already
    withdrawn, ruled) before the write, so none of the lines is stored
    (WITHDRAW-04)."""
    new_body = fresh.body
    for index in indexes:
        new_body = expectations.withdraw_line(new_body, index, today)
    return _committed_and_signalled(context, fresh, new_body, state)


def _refuse_a_shape_verdict(check: body.BodyShapeCheck, verdict: body.BodyShapeVerdict) -> None:
    if check.verdict is verdict:
        raise protocol.ClaimError("; ".join(check.defects))


def _refuse_an_item_the_inbox_omits(fresh: FreshItem, noun: str) -> None:
    """Refuses a closed item and one a non-member wrote: the inbox and the board
    list neither, so a `noun` written on it would show nowhere."""
    if fresh.state is not forge.ItemState.OPEN:
        raise protocol.ClaimError(
            f"item {fresh.number} is closed; a {noun} on it would show nowhere"
        )
    if not fresh.author_is_member:
        raise protocol.ClaimError(
            f"item {fresh.number} was not written by a member; its {noun}s are not listed"
        )


def ask(context: RunContext, fresh: FreshItem, card: Mapping[str, object]) -> Asked:
    """Puts the option line `card` on the fresh item, dated by the run's clock
    and written once. It refuses a closed item and one a non-member wrote (the
    inbox and the board list neither), a card the grammar refuses, and a body
    that would not read back; the same card already on the item answers that
    line, the first by index, and writes nothing; only then an incomplete
    body refuses. Raises `protocol.ClaimError` by name for every refusal,
    before the write."""
    _refuse_an_item_the_inbox_omits(fresh, "card")
    new_body = expectations.ask_line(fresh.body, card, context.today())
    shape = body.body_shape_check(new_body, storage=fresh.storage)
    _refuse_a_shape_verdict(shape, body.BodyShapeVerdict.MALFORMED)
    *standing, asked = expectations.expectation_lines(new_body, storage=fresh.storage)
    asked = cast(expectations.OptionLine, asked)
    for line in standing:
        if isinstance(line, expectations.OptionLine) and line.card_hash == asked.card_hash:
            return Asked(line, written=False)
    _refuse_a_shape_verdict(shape, body.BodyShapeVerdict.INCOMPLETE)
    _committed(context, fresh, new_body)
    return Asked(asked, written=True)


def _label_as_a_step(client: forge.ForgeWriter, number: int, *, standing: str) -> None:
    """Sets the label of an operator-only step on item `number`. A refusal says what
    `standing` already holds and that repeating the same call sets the label."""
    try:
        client.add_label(number, workboard.NEEDS_OPERATOR_LABEL)
    except protocol.ClaimError as error:
        raise protocol.ClaimError(
            f"{standing}, but the label {workboard.NEEDS_OPERATOR_LABEL} was not set: {error}; "
            "repeat the same call to set it once that cause is gone"
        ) from error


def mark_step(context: RunContext, fresh: FreshItem, step: str) -> None:
    """Writes `step` as the `next` of the fresh item, every other field and byte
    kept, then sets the label of an operator-only step. A body equal to the
    fresh one writes nothing and the label is set all the same, so a repeat
    finishes a call whose label failed. Raises `protocol.ClaimError` by name for
    a closed item and one a non-member wrote, before the write."""
    _refuse_an_item_the_inbox_omits(fresh, "step")
    folded = {**fresh.located.data, "next": step}
    new_body = body.replace_block(fresh.body, fresh.located, folded)
    write_item_body(context.forge_writer, fresh.number, new_body, replacing=fresh.body)
    _label_as_a_step(context.forge_writer, fresh.number, standing=f"#{fresh.number} holds the step")


def open_step_item(context: RunContext, title: str, step: str) -> int:
    """Opens a task named `title` whose body names `step` as its `next`, sets the
    label of an operator-only step on it and answers its number. A failure after
    the item exists names it and says repeating the same call finishes it."""
    client = context.forge_writer
    fields = {
        "now": f"Opened by the step tool on {context.today().isoformat()}.",
        "next": step,
        "done_when": (
            "The operator has taken the step and the head has removed the label "
            f"{workboard.NEEDS_OPERATOR_LABEL}."
        ),
    }
    opened = body.prose_above_fresh_block(
        "This item waits on a step only the operator can take.", fields
    )
    try:
        number = client.create_issue(title=title, body=opened, kind=body.ItemKind.TASK)
    except forge.ForgeIssueTypeNotSetError as error:
        raise protocol.ClaimError(
            f"{error}; repeat the same call to set the label {workboard.NEEDS_OPERATOR_LABEL}, "
            "then set the issue type on the forge by hand"
        ) from error
    _label_as_a_step(client, number, standing=f"#{number} was opened with the step")
    return number
