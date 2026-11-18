"""`aco item edit` (`specs/item.spec.md`): the whole-body replacement against `--base` and
the narrow `--size`, `--whole` and `--kind` writes."""
# ruff: noqa: T201 - the item command writes its result lines to stdout

import argparse
import os
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

from . import board_read, body, decide, forge, protocol, report, state_board, workboard
from .cmd_item_common import (
    ItemReason,
    body_shape_defects,
    refuse_an_unreadable_relative,
    refuse_item_body_invalid,
    state_ref_board,
)
from .session import RunContext


def _refuse_a_body_on_stdin(command: str) -> None:
    """Refuses, before any write, a body `command` would otherwise drop
    unread: it reads no stdin, so a file or pipe there carrying
    one (`report.stdin_carries_a_body`) is a mistake the person must see."""
    if report.stdin_carries_a_body():
        raise protocol.ClaimUnavailableError(f"{command} reads no stdin; drop the redirect")


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item edit ITEM`: with `--size`, `--whole`, or `--kind`, a narrow write of
    only that one field (both storages); with none, the item's whole body replaced
    from stdin against `--base`, the hash `item show --json` printed. Every refusal is
    `precondition_failed` except a malformed piped body (`body_invalid`, with `check -`'s
    own `defects`), a stale base (`stale`) and a write the forge's check answers (ITEM-76)."""
    for value, narrow_edit in (
        (parsed.size, _cmd_item_edit_size),
        (parsed.whole, _cmd_item_edit_whole),
        (parsed.kind, _cmd_item_edit_kind),
    ):
        if value is not None:
            return narrow_edit(parsed, context)
    as_json = parsed.json
    try:
        number = parsed.item
        storage = context.config.storage
        new_body = _read_item_edit_body(number, storage, base=parsed.base)
        defects = body_shape_defects(new_body, storage=storage)
        if defects:
            return refuse_item_body_invalid(defects, as_json=as_json)
        replaced = _replace_whole_body(context, number, new_body, base=parsed.base)
        item_id = workboard.item_label(number, storage)
        _print_item_edit_result(item_id, number, replaced, as_json=as_json)
        return 0
    except decide.StaleBodyError as error:
        return report.refuse(ItemReason.STALE, error, as_json=as_json)
    except forge.ForgeBodyWrittenError as error:
        return report.refuse_checked_write(error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _read_item_edit_body(number: int, storage: body.Storage, *, base: str | None) -> str:
    """`item edit`'s new body: refused, unread, without a `--base` (ITEM-73), and
    read only when stdin carries one (`report.stdin_carries_a_body`) -- an idle
    socket, a terminal, `/dev/null` or a closed stdin refuses at once, naming the
    redirect, rather than hanging on a read or replacing the body with nothing."""
    item_id = workboard.item_label(number, storage)
    item_argument = workboard.item_argument(number, storage)
    if base is None:
        raise protocol.ClaimUnavailableError(
            f"item edit {item_id} needs --base <hash>; "
            f"aco item show {item_argument} --json prints it"
        )
    if not report.stdin_carries_a_body():
        raise protocol.ClaimUnavailableError(
            f"item edit {item_id} needs the new body on stdin: "
            f"aco item edit {item_argument} --base <hash> < body.md"
        )
    return report.read_piped_body()


@dataclass(frozen=True)
class _WholeBodyEdit:
    """What a whole-body `item edit` left: `outcome` (`EDITED` or `UNCHANGED`), the hash
    of the body now stored and, under state-ref, the written blob's `oid`."""

    outcome: ItemReason
    body_hash: str
    oid: protocol.ObjectId | None = None


def _replace_whole_body(
    context: RunContext, number: int, new_body: str, *, base: str
) -> _WholeBodyEdit:
    """Replaces item `number`'s body with `new_body` if it still has the body `base` hashes,
    read afresh under the item's lock (ITEM-72), else refuses `StaleBodyError` and writes
    nothing. The state-ref board is built inside the lock, so the snapshot hashed is the
    one written against, and its write always lands (ITEM-13)."""
    storage = context.config.storage
    item_id = workboard.item_label(number, storage)
    item_argument = workboard.item_argument(number, storage)
    with decide.item_lock(context, number, environment=os.environ, home=Path.home()):
        if storage is body.Storage.STATE_REF:
            board = state_ref_board(context)
            if not board.holds(number):
                raise protocol.ClaimUnavailableError(
                    board_read.missing_item_refusal(number, board, storage)
                )
            decide.require_current(
                base, board.stored_body_hash(number), item_id=item_id, item_argument=item_argument
            )
            try:
                board.update_item_body(number, new_body, replacing="")
            except protocol.ItemWrittenSinceReadError as error:
                raise decide.StaleBodyError(str(error)) from error
            stored = board.item_reference(number).body or ""
            return _WholeBodyEdit(
                ItemReason.EDITED, decide.body_hash(stored), board.item_oid(number)
            )
        client = context.forge_writer
        reference = board_read.item_or_refuse(client, number, command="item edit", storage=storage)
        current = reference.body or ""
        decide.require_current(
            base, decide.body_hash(current), item_id=item_id, item_argument=item_argument
        )
        written = decide.write_item_body(client, number, new_body, replacing=current)
        outcome = ItemReason.EDITED if written else ItemReason.UNCHANGED
        return _WholeBodyEdit(outcome, decide.body_hash(new_body))


_ITEM_EDIT_SIZE_COMMAND = "item edit --size"


def _cmd_item_edit_size(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item edit ITEM --size S|M|L`: the one item-size
    write, over the generic `ForgeWriter.update_item_body` both `github`
    and `state-ref` already implement -- unlike the whole-body `item edit`
    above, this works under `storage = "github"` too, since it patches only
    the block's own top-level `size` key (never `[record]`, a
    `state-ref`-only table BODY-15 refuses under `github`) and leaves every
    other byte untouched. Every refusal reports through the shared envelope
    as `precondition_failed`, except a write the forge's check answers (ITEM-66), which
    reports `overwritten` or `not_verified`."""
    as_json = parsed.json
    try:
        _refuse_a_body_on_stdin(_ITEM_EDIT_SIZE_COMMAND)
        number = parsed.item
        with _item_turn(context, number, _ITEM_EDIT_SIZE_COMMAND) as fresh:
            new_data = {**fresh.located.data, "size": parsed.size}
            outcome = write_block_data(context.forge_writer, fresh, new_data)
        _print_item_edit_size_result(number, parsed.size, fresh.storage, outcome, as_json=as_json)
        return 0
    except forge.ForgeBodyWrittenError as error:
        return report.refuse_checked_write(error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _item_turn(
    context: RunContext, number: int, command: str
) -> AbstractContextManager[decide.FreshItem]:
    """The item's turn (ITEM-65) for a narrow `item edit`, refusing as `command`."""
    return decide.turn(context, number, command=command, environment=os.environ, home=Path.home())


def write_block_data(
    client: forge.ForgeWriter, fresh: decide.FreshItem, new_data: dict[str, object]
) -> ItemReason:
    """Writes `new_data` as item `number`'s block, every other byte
    untouched, or nothing at all when the block already carries it,
    so a repeated narrow edit leaves no empty write behind."""
    if new_data == fresh.located.data:
        return ItemReason.UNCHANGED
    new_body = body.replace_block(fresh.body, fresh.located, new_data)
    decide.write_item_body(client, fresh.number, new_body, replacing=fresh.body)
    return ItemReason.EDITED


def _narrow_edit_word(outcome: ItemReason) -> str:
    """The first word a narrow `item edit` prints: `EDITED` or `UNCHANGED`."""
    return outcome.value.upper()


def _print_item_edit_size_result(
    number: int, size: str, storage: body.Storage, outcome: ItemReason, *, as_json: bool
) -> None:
    if as_json:
        report.emit_json(True, outcome, item=number, size=size)
    else:
        print(f"{_narrow_edit_word(outcome)} {workboard.item_label(number, storage)} size={size}")


_ITEM_EDIT_WHOLE_COMMAND = "item edit --whole"


def _cmd_item_edit_whole(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item edit ITEM --whole REASON`: the one item-whole
    write, mirroring `_cmd_item_edit_size` over the same generic
    `ForgeWriter.update_item_body` -- works under `storage = "github"` too,
    since it patches only the block's own top-level `whole` key and leaves
    every other byte untouched. Every refusal reports through the shared
    envelope as `precondition_failed`, except a write the forge's check answers (ITEM-66),
    which reports `overwritten` or `not_verified`."""
    as_json = parsed.json
    try:
        _refuse_a_body_on_stdin(_ITEM_EDIT_WHOLE_COMMAND)
        number = parsed.item
        with _item_turn(context, number, _ITEM_EDIT_WHOLE_COMMAND) as fresh:
            reason = body.bounded_whole_reason(parsed.whole)
            new_data = {**fresh.located.data, "whole": reason}
            outcome = write_block_data(context.forge_writer, fresh, new_data)
        _print_item_edit_whole_result(number, reason, fresh.storage, outcome, as_json=as_json)
        return 0
    except forge.ForgeBodyWrittenError as error:
        return report.refuse_checked_write(error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _print_item_edit_whole_result(
    number: int, reason: str, storage: body.Storage, outcome: ItemReason, *, as_json: bool
) -> None:
    if as_json:
        report.emit_json(True, outcome, item=number, whole=reason)
    else:
        print(
            f"{_narrow_edit_word(outcome)} {workboard.item_label(number, storage)} whole={reason}"
        )


_ITEM_EDIT_KIND_COMMAND = "item edit --kind"


def _cmd_item_edit_kind(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item edit ITEM --kind task|container`: the one
    retype a person runs, over the `ForgeWriter.set_item_kind` both storages
    implement -- the repair `next` names for a nested container with one
    uncut row. Reads no stdin, and refuses a body piped or redirected there
    before any write, so it is never silently dropped.
    A container with an open child stays one, since a Task never has
    children to claim through. Every refusal reports through the shared
    envelope as `precondition_failed`."""
    as_json = parsed.json
    try:
        _refuse_a_body_on_stdin(_ITEM_EDIT_KIND_COMMAND)
        client = context.forge_writer
        storage = context.config.storage
        number = parsed.item
        kind = body.ItemKind(parsed.kind)
        # Under state-ref the retype reads its item alone (ITEM-37/38);
        # the forge answers only through its open-issue list.
        if isinstance(client, state_board.StateRefBoard):
            target = client.open_issue(number)
        else:
            target = next(
                (issue for issue in client.list_open_board_issues() if issue.number == number),
                None,
            )
        label = workboard.item_label(number, storage)
        if target is None:
            raise protocol.ClaimUnavailableError(f"{label} is not an open item")
        # The retype decides with the item and its children alone,
        # and holds the store it read through its write, so a child
        # written since refuses it rather than being guessed past.
        if isinstance(client, state_board.StateRefBoard):
            refuse_an_unreadable_relative(client, number, with_parent=False)
            client.hold_items()
        if kind is body.ItemKind.TASK and target.has_open_child:
            raise protocol.ClaimUnavailableError(
                f"{label} has an open child; a container with open children stays a container"
            )
        outcome = ItemReason.UNCHANGED if target.kind is kind else ItemReason.EDITED
        if outcome is ItemReason.EDITED:
            client.set_item_kind(number, kind)
        _print_item_edit_kind_result(number, kind, storage, outcome, as_json=as_json)
        return 0
    except protocol.ClaimError as error:
        return report.refuse(ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _print_item_edit_kind_result(
    number: int, kind: body.ItemKind, storage: body.Storage, outcome: ItemReason, *, as_json: bool
) -> None:
    label = workboard.item_label(number, storage)
    if as_json:
        report.emit_json(True, outcome, item=label, number=number, kind=kind.value)
    else:
        print(f"{_narrow_edit_word(outcome)} {label} kind={kind.value}")


def _print_item_edit_result(
    item_id: str, number: int, replaced: _WholeBodyEdit, *, as_json: bool
) -> None:
    if as_json:
        oid = {} if replaced.oid is None else {"oid": replaced.oid}
        report.emit_json(
            True, replaced.outcome, item=item_id, number=number, body_hash=replaced.body_hash, **oid
        )
    else:
        print(f"{_narrow_edit_word(replaced.outcome)} {item_id}")
