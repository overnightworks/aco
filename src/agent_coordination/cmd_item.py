"""The `item` command (`specs/item.spec.md`)."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from . import (
    board,
    board_read,
    body,
    cmd_body,
    cmd_cut,
    forge,
    items,
    policy,
    protocol,
    report,
    state_board,
)
from .session import RunContext

# `item new`'s own projection flags (issue #555), keyed by the block key
# each one writes.
ITEM_NEW_PROJECTION_FLAGS = (
    ("now", "the block's now: where the item stands"),
    ("next", "the block's next: the one concrete next step"),
    ("done_when", "the block's done_when: the checkable finish"),
)


def _body_shape_defects(
    raw_body: str, *, storage: body.Storage = body.Storage.GITHUB
) -> tuple[str, ...]:
    """`item edit`'s own accessor (issue #287) onto `body.body_shape_check`
    (issue #404): only the defect sentences, never the verdict `check
    <item>` and `body --check` read for their own `--json` `reason`."""
    return body.body_shape_check(raw_body, storage=storage).defects


def _stdin_file_mode() -> int | None:
    """The type bits of the descriptor on stdin, told without reading, since
    an idle pipe or socket a harness holds open would block a read forever;
    `None` for a closed stdin."""
    try:
        return os.fstat(sys.stdin.fileno()).st_mode
    except (AttributeError, OSError, ValueError):
        return None


def _stdin_carries_a_body() -> bool:
    """Whether stdin carries a body a command reads (head ruling of
    01.10.2026 on issue #555): a redirected file (`< body.md`) or a pipe
    (`printf ... |`). A socket -- what Claude Code's Bash tool hands a
    command -- a terminal, `/dev/null` or a closed stdin carry none, so the
    command never waits on an idle harness stdin."""
    mode = _stdin_file_mode()
    return mode is not None and (stat.S_ISREG(mode) or stat.S_ISFIFO(mode))


def _refuse_a_body_on_stdin(command: str) -> None:
    """Refuses, before any write, a body `command` would otherwise drop
    unread (issue #567): it reads no stdin, so a file or pipe there carrying
    one (`_stdin_carries_a_body`) is a mistake the person must see."""
    if _stdin_carries_a_body():
        raise protocol.ClaimUnavailableError(f"{command} reads no stdin; drop the redirect")


def _state_ref_board(context: RunContext) -> state_board.StateRefBoard:
    """`context`'s own forge as the state-ref board, for an item command
    that has already refused every other storage pin: under `state-ref`
    `cli._build_forge` builds exactly `cli._state_ref_forge`'s board, so the cast is
    honest, not a suppression -- the same narrowing `RunContext.forge_writer`
    performs for the generic writing surface."""
    return cast(state_board.StateRefBoard, context.forge)


_ITEM_NEW_ORIGIN_ON_GITHUB_REFUSAL = '--origin needs storage = "state-ref"'


class _ItemReason(StrEnum):
    """`aco item`'s own `--json` `reason` vocabulary, shared across its four
    subcommands (issue #425, `specs/item.spec.md`): `created`/`edited`/
    `closed`/`shown` name each subcommand's own success; `unchanged`, an
    `item edit --size/--whole/--kind` whose value is already set, which
    writes nothing (issue #572). `body_invalid`
    covers only `item new`'s and `item edit`'s own piped-body shape check
    (`_body_shape_defects`, the same check `body --check` runs), carrying
    `defects` the same way (`cmd_body._BodyCheckReason`, issue #404); `partial_write`
    only a GitHub issue `item new` created but could not type or record under
    its `--parent` (issue #444), `cut`'s own shape. Every other refusal -- a
    `storage = "github"` command, a missing item or parent, a possible twin,
    a pull request target, a forge write capability, or a live claim still
    on the item -- is `precondition_failed`, this command family's single
    generic bucket."""

    CREATED = "created"
    EDITED = "edited"
    UNCHANGED = "unchanged"
    CLOSED = "closed"
    SHOWN = "shown"
    PRECONDITION_FAILED = "precondition_failed"
    BODY_INVALID = "body_invalid"
    PARTIAL_WRITE = "partial_write"


def _refuse_item_body_invalid(defects: tuple[str, ...], *, as_json: bool) -> int:
    return report.refuse(
        _ItemReason.BODY_INVALID, defects[0], as_json=as_json, defects=list(defects)
    )


def _cmd_item_new(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item new` (issues #285, #316, #444): one fresh item under
    either storage pin, each through its own adapter's write
    (`_item_new_on_github`, `_item_new_on_state_ref`), both behind the same
    twin search `cut` runs (`cmd_cut.refuse_possible_twin`). Every refusal but a
    malformed piped body or a partial GitHub write reports through the
    shared envelope as `precondition_failed` (issue #425)."""
    as_json = parsed.json
    try:
        if context.config.storage is body.Storage.GITHUB:
            return _item_new_on_github(parsed, context)
        return _item_new_on_state_ref(parsed, context)
    except _ItemBodyInvalidError as error:
        return _refuse_item_body_invalid(error.defects, as_json=as_json)
    except cmd_cut.PartialWriteError as error:
        return cmd_cut.refuse_partial_write(error, _ItemReason.PARTIAL_WRITE, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


class _ItemBodyInvalidError(protocol.ClaimError):
    """`item new`'s piped body refused before anything is created, carrying
    every defect sentence for `body_invalid`'s own `defects` list."""

    def __init__(self, defects: tuple[str, ...]) -> None:
        self.defects = defects
        super().__init__(defects[0])


def _read_item_new_input() -> str:
    """`item new`'s piped body under either storage, or `""` when stdin
    carries none (`_stdin_carries_a_body`)."""
    return cmd_body.read_body_check_input() if _stdin_carries_a_body() else ""


def _item_new_block_fields(parsed: argparse.Namespace) -> dict[str, object]:
    """Every block field `item new`'s own flags name, keyed as the block
    writes it -- only the flags given."""
    scope = cmd_cut.requested_body_scope(parsed.scope)
    requested: dict[str, object | None] = {
        **{key: getattr(parsed, key) for key, _meaning in ITEM_NEW_PROJECTION_FLAGS},
        "scope": None if scope is None else list(scope),
        "size": parsed.size,
        "whole": _requested_whole_reason(parsed.whole),
    }
    return {key: value for key, value in requested.items() if value is not None}


def _item_new_body(parsed: argparse.Namespace, storage: body.Storage) -> str:
    """The body `item new` stores under either storage (issue #555): the
    piped one, its block given each flag it lacks and refused when a flag
    contradicts it; or, piped without a block, the prose above a block the
    flags build -- a container's own skeleton prose when nothing was piped."""
    piped = _read_item_new_input()
    fields = _item_new_block_fields(parsed)
    if not body.carries_block(piped):
        default_prose = (
            body.CONTAINER_SKELETON_PROSE if parsed.kind == body.ItemKind.CONTAINER else ""
        )
        return body.prose_above_fresh_block(piped if piped.strip() else default_prose, fields)
    shape = body.body_shape_check(piped, storage=storage)
    if shape.verdict is body.BodyShapeVerdict.MALFORMED:
        raise _ItemBodyInvalidError(shape.defects)
    conflicts = body.block_field_conflicts(piped, fields)
    if conflicts:
        raise _ItemBodyInvalidError(conflicts)
    return body.body_with_block_fields(piped, fields)


def _item_new_on_github(parsed: argparse.Namespace, context: RunContext) -> int:
    """`item new` under `storage = "github"` (issue #444): the body it
    stores (`_item_new_body`) passes the same shape check `aco check <n>`
    applies before
    anything else is read or written, so an invalid body creates nothing;
    `--parent` must name an open container or Task (a Task is retyped once
    the twin search passes, `_retype_task_parent`); then the twin search, the only
    guard against a second run: the issue an earlier run created carries
    the same title, so the search names it. Then one issue of the
    organization's type for `--kind`, recorded under `--parent` when given
    (`create_child`, else `create_issue`); a type or relation write that
    fails after the create refuses naming the issue and what is left to do
    by hand, never a re-run. `--origin` binds a state-ref item only: a
    GitHub issue binds to no foreign one."""
    if parsed.origin is not None:
        raise protocol.ClaimUnavailableError(_ITEM_NEW_ORIGIN_ON_GITHUB_REFUSAL)
    new_body = _item_new_body(parsed, body.Storage.GITHUB)
    defects = _body_shape_defects(new_body)
    if defects:
        raise _ItemBodyInvalidError(defects)
    client = context.forge_writer
    open_issues = client.list_open_board_issues()
    storage = context.config.storage
    parent = (
        None
        if parsed.parent is None
        else cmd_cut.open_container(open_issues, parsed.parent, storage, _ITEM_PARENT_KINDS)
    )
    if not parsed.not_a_twin:
        cmd_cut.refuse_possible_twin(
            client,
            parsed.title,
            cmd_cut.numbered_titles(open_issues),
            parent=parsed.parent,
            storage=storage,
        )
    _retype_task_parent(client, parent, storage)
    kind = body.ItemKind(parsed.kind)
    try:
        number = (
            client.create_issue(title=parsed.title, body=new_body, kind=kind)
            if parsed.parent is None
            else client.create_child(
                parent=parsed.parent, title=parsed.title, body=new_body, kind=kind
            )
        )
    except forge.ForgeIssueTypeNotSetError as error:
        relation = "" if parsed.parent is None else f" and record it under #{parsed.parent}"
        raise cmd_cut.PartialWriteError(
            error, recovery=f"set that type{relation} on the forge by hand"
        ) from error
    except forge.ForgePartialChildCreationError as error:
        raise cmd_cut.PartialWriteError(
            error, recovery="record that sub-issue relation on the forge by hand"
        ) from error
    _print_item_new_result(
        board.item_label(number, body.Storage.GITHUB), number, as_json=parsed.json
    )
    return 0


def _retype_task_parent(
    client: forge.ForgeWriter, parent: board.Issue | None, storage: body.Storage
) -> None:
    """Retype an open Task `--parent` to Container before it gets its first
    child (issue #503), under either storage, and say so on stderr, leaving
    stdout and `--json` the created item's alone; any other parent keeps
    its kind."""
    if parent is None or parent.kind is not body.ItemKind.TASK:
        return
    client.set_item_kind(parent.number, body.ItemKind.CONTAINER)
    label = board.item_label(parent.number, storage)
    print(f"retyped {label} to Container for its first child", file=sys.stderr)


def _item_new_on_state_ref(parsed: argparse.Namespace, context: RunContext) -> int:
    """`item new` under `storage = "state-ref"` (issues #285, #316): the one
    write path for a fresh state-ref item -- `StateRefBoard.compose_item`
    then `create_item`, the same CAS write `cut`'s own `create_child`
    performs, generalized to an optional parent and origin -- so this
    module never grows a second way to create one. `--origin` binds the
    fresh item to a foreign forge issue (`items.parse_origin`'s own grammar,
    refused by `argparse` before this ever runs) without aco governing that
    forge at all. An open Task parent turns Container
    (`_retype_task_parent`) once the item is composed and before it is
    written, so an item the read would refuse retypes nothing. Narrows the
    context's forge to the state-ref board (`_state_ref_board`), since
    `create_item` is not part of the generic `ForgeWriter` port every other
    write command narrows to. The body is `_item_new_body`'s, the piped one
    stored as under github; one left incomplete is still written, each
    missing section named on stderr (issue #555)."""
    client = _state_ref_board(context)
    parent = parsed.parent
    storage = context.config.storage
    new_body = _item_new_body(parsed, storage)
    if parent is not None and client.item_reference(parent).state is forge.ItemState.MISSING:
        raise protocol.ClaimUnavailableError(f"{board.item_label(parent, storage)} does not exist")
    if not parsed.not_a_twin:
        cmd_cut.refuse_possible_twin(
            client, parsed.title, client.open_item_titles(), parent=parsed.parent, storage=storage
        )
    new_item = client.compose_item(
        title=parsed.title,
        body=new_body,
        kind=body.ItemKind(parsed.kind),
        parent=parsed.parent,
        origin=parsed.origin,
    )
    if parent is not None:
        _retype_task_parent(client, client.open_issue(parent), storage)
    item_id = client.create_item(new_item)
    _print_item_new_result(item_id, items.item_number(item_id), as_json=parsed.json)
    for section in body.missing_or_empty_sections(body.parse_body(new_body).contract):
        print(f"{item_id} misses {section}; aco item edit {item_id} fills it", file=sys.stderr)
    return 0


def _print_item_new_result(item_id: str, number: int, *, as_json: bool) -> None:
    if as_json:
        report.emit_json(True, _ItemReason.CREATED, item=item_id, number=number)
    else:
        print(item_id)


_ITEM_EDIT_GITHUB_REFUSAL = "forge issues are edited on the forge; aco never governs them"


def _cmd_item_edit(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item edit ITEM` (issue #287; `--size`, issue #357; `--whole`,
    issue #399; `--kind`, issue #503): with `--size`, `--whole`, or `--kind`,
    a narrow write of only that one field (`_cmd_item_edit_size`/
    `_cmd_item_edit_whole`/`_cmd_item_edit_kind`, both storages); with none,
    the state-ref item's own body, replaced from
    stdin only -- refused before any write when the piped body carries no
    valid `aco` block (`body --check`'s own sentences,
    `_body_shape_defects`). The CAS `expected` oid is this process's own
    already-read snapshot (`StateRefBoard.update_item_body`'s
    `current.oid`, set once at `cli._state_ref_forge` construction): a second
    process writing from that same snapshot refuses with issue #279's own
    sentence, never merged, never silently overwritten. `parent`, `state`,
    `origin`, `created_at`, and `closed_at` stay this item's own stored
    values regardless of what the piped body's `[record]` names for them --
    `update_item_body`'s own owner rule; `updated_at` always moves to now;
    `title`, `labels`, `blocked_by` come from the piped record when it
    carries one -- except a malformed item (ITEM-39), which takes the piped
    record whole and refuses a body without one; a delivered `blocked_by`
    naming one blocker twice, or a blocker the item does not already carry
    that names no item, a malformed item or the item itself, refuses before
    any write (ITEM-43, ITEM-44). Refuses under
    `storage = "github"`: forge issues are edited on the forge, never
    governed by aco. Narrows the context's forge to the state-ref board,
    as `item new`'s state-ref path does. A malformed piped body reports through
    the shared envelope as `body_invalid`, with `body --check`'s own
    `defects`; every other refusal is `precondition_failed` (issue #425)."""
    if parsed.size is not None:
        return _cmd_item_edit_size(parsed, context)
    if parsed.whole is not None:
        return _cmd_item_edit_whole(parsed, context)
    if parsed.kind is not None:
        return _cmd_item_edit_kind(parsed, context)
    as_json = parsed.json
    try:
        if context.config.storage is not body.Storage.STATE_REF:
            raise protocol.ClaimUnavailableError(_ITEM_EDIT_GITHUB_REFUSAL)
        new_body = _read_item_edit_body(parsed.item)
        defects = _body_shape_defects(new_body, storage=body.Storage.STATE_REF)
        if defects:
            return _refuse_item_body_invalid(defects, as_json=as_json)
        client = _state_ref_board(context)
        number = parsed.item
        if not client.holds(number):
            raise protocol.ClaimUnavailableError(
                board_read.missing_item_refusal(number, client, context.config.storage)
            )
        client.update_item_body(number, new_body)
        _print_item_edit_result(
            items.format_item_id(number), number, client.item_oid(number), as_json=as_json
        )
        return 0
    except protocol.ClaimError as error:
        return report.refuse(_ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _read_item_edit_body(number: int) -> str:
    """`item edit`'s new body, read only when stdin carries one
    (`_stdin_carries_a_body`, issue #572): an idle socket, a terminal,
    `/dev/null` or a closed stdin refuses at once, naming the redirect,
    rather than hanging on a read or replacing the body with nothing."""
    if not _stdin_carries_a_body():
        item_id = items.format_item_id(number)
        raise protocol.ClaimUnavailableError(
            f"item edit {item_id} needs the new body on stdin: aco item edit {item_id} < body.md"
        )
    return cmd_body.read_body_check_input()


_ITEM_EDIT_SIZE_COMMAND = "item edit --size"


def _cmd_item_edit_size(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item edit ITEM --size S|M|L` (issue #357): the one item-size
    write, over the generic `ForgeWriter.update_item_body` both `github`
    and `state-ref` already implement -- unlike the whole-body `item edit`
    above, this works under `storage = "github"` too, since it patches only
    the block's own top-level `size` key (never `[record]`, a
    `state-ref`-only table BODY-15 refuses under `github`) and leaves every
    other byte untouched. Every refusal reports through the shared envelope
    as `precondition_failed` (issue #425)."""
    as_json = parsed.json
    try:
        _refuse_a_body_on_stdin(_ITEM_EDIT_SIZE_COMMAND)
        client = context.forge_writer
        board_read.require_update_item_body(client, command=_ITEM_EDIT_SIZE_COMMAND)
        number = parsed.item
        storage = context.config.storage
        current_body = board_read.item_body_or_refuse(
            client, number, command=_ITEM_EDIT_SIZE_COMMAND, storage=storage
        )
        located = board.located_block_or_refuse(
            number, current_body, command=_ITEM_EDIT_SIZE_COMMAND, storage=storage
        )
        new_data = {**located.data, "size": parsed.size}
        outcome = _write_block_data(client, number, current_body, located, new_data)
        _print_item_edit_size_result(number, parsed.size, storage, outcome, as_json=as_json)
        return 0
    except protocol.ClaimError as error:
        return report.refuse(_ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _write_block_data(
    client: forge.ForgeWriter,
    number: int,
    current_body: str,
    located: body.LocatedBlock,
    new_data: dict[str, object],
) -> _ItemReason:
    """Writes `new_data` as item `number`'s block, every other byte
    untouched, or nothing at all when the block already carries it (issue
    #572), so a repeated narrow edit leaves no empty write behind."""
    if new_data == located.data:
        return _ItemReason.UNCHANGED
    client.update_item_body(number, body.replace_block(current_body, located, new_data))
    return _ItemReason.EDITED


def _narrow_edit_word(outcome: _ItemReason) -> str:
    """The first word a narrow `item edit` prints: `EDITED` or `UNCHANGED`."""
    return outcome.value.upper()


def _print_item_edit_size_result(
    number: int, size: str, storage: body.Storage, outcome: _ItemReason, *, as_json: bool
) -> None:
    if as_json:
        report.emit_json(True, outcome, item=number, size=size)
    else:
        print(f"{_narrow_edit_word(outcome)} {board.item_label(number, storage)} size={size}")


_ITEM_EDIT_WHOLE_COMMAND = "item edit --whole"


def _cmd_item_edit_whole(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item edit ITEM --whole REASON` (issue #399): the one item-whole
    write, mirroring `_cmd_item_edit_size` over the same generic
    `ForgeWriter.update_item_body` -- works under `storage = "github"` too,
    since it patches only the block's own top-level `whole` key and leaves
    every other byte untouched. Every refusal reports through the shared
    envelope as `precondition_failed` (issue #425)."""
    as_json = parsed.json
    try:
        _refuse_a_body_on_stdin(_ITEM_EDIT_WHOLE_COMMAND)
        client = context.forge_writer
        board_read.require_update_item_body(client, command=_ITEM_EDIT_WHOLE_COMMAND)
        number = parsed.item
        storage = context.config.storage
        current_body = board_read.item_body_or_refuse(
            client, number, command=_ITEM_EDIT_WHOLE_COMMAND, storage=storage
        )
        located = board.located_block_or_refuse(
            number, current_body, command=_ITEM_EDIT_WHOLE_COMMAND, storage=storage
        )
        reason = cast(str, policy.bounded_whole_reason(parsed.whole))
        new_data = {**located.data, "whole": reason}
        outcome = _write_block_data(client, number, current_body, located, new_data)
        _print_item_edit_whole_result(number, reason, storage, outcome, as_json=as_json)
        return 0
    except protocol.ClaimError as error:
        return report.refuse(_ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _print_item_edit_whole_result(
    number: int, reason: str, storage: body.Storage, outcome: _ItemReason, *, as_json: bool
) -> None:
    if as_json:
        report.emit_json(True, outcome, item=number, whole=reason)
    else:
        print(f"{_narrow_edit_word(outcome)} {board.item_label(number, storage)} whole={reason}")


_ITEM_EDIT_KIND_COMMAND = "item edit --kind"


def _cmd_item_edit_kind(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item edit ITEM --kind task|container` (issue #503): the one
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
        # Under state-ref the retype reads its item alone (ITEM-37/38, issue
        # #536); the forge answers only through its open-issue list.
        if isinstance(client, state_board.StateRefBoard):
            target = client.open_issue(number)
        else:
            target = next(
                (issue for issue in client.list_open_board_issues() if issue.number == number),
                None,
            )
        label = board.item_label(number, storage)
        if target is None:
            raise protocol.ClaimUnavailableError(f"{label} is not an open item")
        # The retype decides with the item and its children alone (issue
        # #536), and holds the store it read through its write, so a child
        # written since refuses it rather than being guessed past (#447).
        if isinstance(client, state_board.StateRefBoard):
            _refuse_an_unreadable_relative(client, number, with_parent=False)
            client.hold_items()
        if kind is body.ItemKind.TASK and target.has_open_child:
            raise protocol.ClaimUnavailableError(
                f"{label} has an open child; a container with open children stays a container"
            )
        outcome = _ItemReason.UNCHANGED if target.kind is kind else _ItemReason.EDITED
        if outcome is _ItemReason.EDITED:
            client.set_item_kind(number, kind)
        _print_item_edit_kind_result(number, kind, storage, outcome, as_json=as_json)
        return 0
    except protocol.ClaimError as error:
        return report.refuse(_ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _print_item_edit_kind_result(
    number: int, kind: body.ItemKind, storage: body.Storage, outcome: _ItemReason, *, as_json: bool
) -> None:
    label = board.item_label(number, storage)
    if as_json:
        report.emit_json(True, outcome, item=label, number=number, kind=kind.value)
    else:
        print(f"{_narrow_edit_word(outcome)} {label} kind={kind.value}")


def _print_item_edit_result(
    item_id: str, number: int, oid: protocol.ObjectId, *, as_json: bool
) -> None:
    if as_json:
        report.emit_json(True, _ItemReason.EDITED, item=item_id, number=number, oid=oid)
    else:
        print(f"EDITED {item_id}")


_ITEM_CLOSE_GITHUB_REFUSAL = "the forge closes its issues; aco never governs them"


def _cmd_item_close(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item close ITEM` (issue #289): the state-ref item's own record,
    closed -- `state` to `CLOSED`, `closed_at`/`updated_at` to now, the item
    file and every other byte untouched (`StateRefBoard.close_item`'s one
    CAS write over this process's own already-read oid, extending #287's
    record-owner rule by one field rather than composing a record here).
    Refuses under `storage = "github"` by name -- the forge closes its own
    issues, aco never governs them -- and, once the state ref is readable,
    refuses a live claim on the item before every item-state refusal
    (missing, malformed, already closed), then again on every write
    attempt, retries included (`protocol.ItemCloseIntent`, issue #459), so
    a concurrent claim cannot slip past the first check.
    Existence is checked through the ordinary
    `item_reference` read before `close_item` is ever called, so an unknown
    id gets this command's own "does not exist" sentence rather than
    `close_item`'s internal `_by_number` lookup failing with the wrong
    shape; `close_item` itself refuses a second close on an already-closed
    item, naming its date. An unreadable item refuses at its own read; an
    unreadable parent or child, or a parent `items/` lacks, refuses before
    the write (`_refuse_an_unreadable_relative`); any other malformed item only goes
    unfreed, and one failing the `freed:` read after the write turns that line
    into a hint (issue #541). Prints one line, `CLOSED aco-xxxxxx` (`--json`:
    `{"item", "number", "closed_at", "parent_closable"}`), then `release
    --merged`'s own `freed:` line -- open items whose only open local
    blocker was this one (`board.freed_item_numbers`, issue #256; nothing new) --
    and, when this close was its parent's last open child, `release
    --merged`'s own parent hint (issue #348). Every refusal reports through
    the shared envelope as `precondition_failed` (issue #425)."""
    as_json = parsed.json
    try:
        if context.config.storage is not body.Storage.STATE_REF:
            raise protocol.ClaimUnavailableError(_ITEM_CLOSE_GITHUB_REFUSAL)
        number = parsed.item
        observed = context.observation
        protocol.require_state_ref(observed)
        protocol.require_no_live_claim(observed, protocol.IssueIdentity(number))
        client = _state_ref_board(context)
        if client.item_reference(number).state is forge.ItemState.MISSING:
            raise protocol.ClaimUnavailableError(
                board_read.missing_item_refusal(number, client, context.config.storage)
            )
        _refuse_an_unreadable_relative(client, number, with_parent=True)
        closed_at = client.close_item(number)
        result = _ItemCloseResult(
            item_id=items.format_item_id(number),
            number=number,
            closed_at=closed_at,
            freed=board_read.board_read_after_write(lambda: _item_close_freed(client, number)),
            parent_closable=_closable_parent_of_a_closed_item(client, number),
        )
        _print_item_close_result(result, as_json=as_json)
        return 0
    except protocol.ClaimError as error:
        named = board.named_refusal(error, body.Storage.STATE_REF)
        return report.refuse(_ItemReason.PRECONDITION_FAILED, named, as_json=as_json)


def _refuse_an_unreadable_relative(
    client: state_board.StateRefBoard, number: int, *, with_parent: bool
) -> None:
    """Refuses by the lowest id while one of `number`'s children -- the same
    children the board counts, an unreadable item that may be one included
    (issue #550, ITEM-54) -- or, `with_parent`, its parent does not read
    (issue #536, ITEM-53): a single-item write decides with those alone, so
    each is read through the one narrow `item_references` read, and an
    unrelated malformed item never blocks the write. `parent_number` refuses
    a parent `items/` lacks (PIN-16) here too, before the write rather than
    after it."""
    relatives = {child.number for child in client.list_children(number)}
    parent = client.parent_number(number) if with_parent else None
    if parent is not None:
        relatives.add(parent)
    client.item_references(sorted(relatives))


def _closable_parent_of_a_closed_item(
    client: state_board.StateRefBoard, closed_item: int
) -> int | None:
    """`board_read.parent_closable_number`'s parent hint, withheld while the parent's
    own `item close` would refuse by an unreadable relative (issue #536,
    ITEM-54): the hint recommends that close, so it asks the very check
    that close runs rather than contradicting it."""
    closable = board_read.parent_closable_number(client, closed_item, body.Storage.STATE_REF)
    if closable is None:
        return None
    try:
        _refuse_an_unreadable_relative(client, closable, with_parent=True)
    except protocol.MalformedStateTreeError:
        return None
    return closable


def _item_close_freed(client: forge.ForgeReader, number: int) -> tuple[int, ...]:
    """Every open item `number`'s own close just freed -- issue #256's own
    derivation, reused rather than reinvented, the same base-issues-plus-
    dependency-fetch wave `cmd_release._release_landing` runs for a merged release, read
    fresh off `client`'s own already-closed view so `number` itself never
    appears among its own candidates."""
    issues = client.list_open_board_issues()
    candidates = tuple(issue.number for issue in issues if issue.blocked_by_count > 0)
    dependencies = board_read.validated_dependencies(
        issues, board_read.fetch_dependencies(client, candidates)
    )
    landed = board.IssueReference(client.repository.path, number)
    return board.freed_item_numbers(dependencies, landed)


@dataclass(frozen=True)
class _ItemCloseResult:
    """Everything `_print_item_close_result` needs for one `item close`
    (issue #348), bundled so the printer itself takes one argument instead
    of PLR0913's five-scalar ceiling. `freed` is the freed numbers, or
    the hint that replaced them when that read refused (issue #541)."""

    item_id: str
    number: int
    closed_at: str
    freed: tuple[int, ...] | str
    parent_closable: int | None


def _print_item_close_result(result: _ItemCloseResult, *, as_json: bool) -> None:
    if as_json:
        report.emit_json(
            True,
            _ItemReason.CLOSED,
            item=result.item_id,
            number=result.number,
            closed_at=result.closed_at,
            parent_closable=result.parent_closable,
        )
        if isinstance(result.freed, str):
            board_read.print_board_read_hint(result.freed, as_json=True)
        return
    print(f"CLOSED {result.item_id}")
    if isinstance(result.freed, str):
        board_read.print_board_read_hint(result.freed, as_json=False)
    else:
        # `item close` only ever runs under `storage = "state-ref"`
        # (`_cmd_item_close`'s own refusal otherwise), so `freed:`'s own id
        # chooser is fixed here rather than threaded as a further field.
        print(board.release_freed_line(result.freed, body.Storage.STATE_REF))
    parent_line = board.parent_closable_line(result.parent_closable, body.Storage.STATE_REF)
    if parent_line is not None:
        print(parent_line)


def _item_state_text(state: forge.ItemState) -> str:
    return "open" if state is forge.ItemState.OPEN else "closed"


def _item_parent_id(parent: int | None) -> str | None:
    return None if parent is None else items.format_item_id(parent)


def _item_header(number: int, reference: forge.ItemReference, parent: int | None) -> str:
    """`item show`'s one header line: id, number, state, parent, and origin
    -- the same shape regardless of which forge answered the reads, since an
    id (`items.format_item_id`) is a pure encoding of `number`, never a
    per-adapter fact. `reference.origin` (issue #316) stays `None` for a
    GitHub-stored item, so this prints `origin none` there exactly like an
    unset parent prints `parent none`."""
    return (
        f"{items.format_item_id(number)} · #{number} · "
        f"{_item_state_text(reference.state)} · parent {_item_parent_id(parent) or 'none'} · "
        f"origin {reference.origin or 'none'}"
    )


def _cmd_item_show(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item show` (issue #285): the stored body behind one header
    line, its display controls escaped in text (issue #544), byte-exact
    under `--json` -- read through the ordinary forge port, so it works
    identically under `storage = "github"` (the forge's own issue body) and
    `storage = "state-ref"` (the item file's own body); closing an item
    never deletes it, so a closed item is shown exactly like an open one.
    A missing id -- or a forge that fails either read this header needs --
    reports through the shared envelope as `precondition_failed` (issue
    #425)."""
    as_json = parsed.json
    try:
        client = context.forge
        number = parsed.item
        reference = client.item_reference(number)
        if reference.state is forge.ItemState.MISSING:
            storage = context.config.storage
            raise protocol.ClaimUnavailableError(
                board_read.missing_item_refusal(number, client, storage)
            )
        parent = client.parent_number(number)
    except protocol.ClaimError as error:
        return report.refuse(_ItemReason.PRECONDITION_FAILED, error, as_json=as_json)
    body = reference.body or ""
    if as_json:
        report.emit_json(
            True,
            _ItemReason.SHOWN,
            item=items.format_item_id(number),
            number=number,
            state=_item_state_text(reference.state),
            parent=_item_parent_id(parent),
            origin=reference.origin,
            body=body,
        )
        return 0
    print(_item_header(number, reference, parent))
    print(board.terminal_block(body), end="")
    return 0


# `item new --parent` also takes a Task: an item becomes a container exactly
# when it gets its first child, so that write retypes it (issue #503).
_ITEM_PARENT_KINDS = frozenset({body.ItemKind.CONTAINER, body.ItemKind.TASK})


def _requested_whole_reason(raw: str | None) -> str | None:
    """A `--whole` flag's own bounded text (issue #399), or `None` when it
    was never given -- `item new`'s own entry point into the same
    `protocol.outbound_text` bound `claim`'s own `--whole` already enforces
    (`policy.bounded_whole_reason`), so the two never drift on what a legal
    reason looks like."""
    return policy.bounded_whole_reason(raw)


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`item`'s own four subcommands, pulled out of `cli._dispatch` (issue #372
    S1) so their nesting stops counting against every other command's
    cognitive complexity."""
    if parsed.item_command == "new":
        return _cmd_item_new(parsed, context)
    if parsed.item_command == "edit":
        return _cmd_item_edit(parsed, context)
    if parsed.item_command == "close":
        return _cmd_item_close(parsed, context)
    return _cmd_item_show(parsed, context)
