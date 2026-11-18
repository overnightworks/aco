"""The `item` command (`specs/item.spec.md`)."""
# ruff: noqa: T201 - the item command writes its result lines to stdout

import argparse
import os
import sys
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from . import (
    board_read,
    body,
    cmd_cut,
    decide,
    forge,
    inbox,
    items,
    protocol,
    report,
    state_board,
    workboard,
)
from .session import RunContext

# `item new`'s own projection flags, keyed by the block key
# each one writes.
ITEM_NEW_PROJECTION_FLAGS = (
    ("now", "the block's now: where the item stands"),
    ("next", "the block's next: the one concrete next step"),
    ("done_when", "the block's done_when: the checkable finish"),
)


def _body_shape_defects(
    raw_body: str, *, storage: body.Storage = body.Storage.GITHUB
) -> tuple[str, ...]:
    """`item edit`'s own accessor onto `body.body_shape_check`:
    only the defect sentences, never the verdict `check
    <item>` and `check -` read for their own `--json` `reason`."""
    return body.body_shape_check(raw_body, storage=storage).defects


def _refuse_a_body_on_stdin(command: str) -> None:
    """Refuses, before any write, a body `command` would otherwise drop
    unread: it reads no stdin, so a file or pipe there carrying
    one (`report.stdin_carries_a_body`) is a mistake the person must see."""
    if report.stdin_carries_a_body():
        raise protocol.ClaimUnavailableError(f"{command} reads no stdin; drop the redirect")


def _state_ref_board(context: RunContext) -> state_board.StateRefBoard:
    """`context`'s own forge as the state-ref board, for an item command
    that has already refused every other storage pin: under `state-ref`
    `session._build_forge` builds exactly `session._state_ref_forge`'s board, so the cast is
    honest, not a suppression -- the same narrowing `RunContext.forge_writer`
    performs for the generic writing surface."""
    return cast(state_board.StateRefBoard, context.forge)


_ITEM_NEW_ORIGIN_ON_GITHUB_REFUSAL = '--origin needs storage = "state-ref"'


class _ItemReason(StrEnum):
    """`aco item`'s own `--json` `reason` vocabulary, shared across its four
    subcommands (`specs/item.spec.md`): `created`/`edited`/
    `closed`/`shown` name each subcommand's own success; `unchanged`, an
    `item edit` whose value or body is already stored, which writes nothing;
    `stale`, a whole-body `item edit` whose `--base` is no longer the item's
    body hash. `body_invalid` covers only `item new`'s and `item edit`'s own piped-body shape check
    (`_body_shape_defects`, the same check `check -` runs), carrying
    `defects` the same way (`cmd_check._CheckReason`); `partial_write`
    only a GitHub issue `item new` created but could not type or record under
    its `--parent`, `cut`'s own shape. Every other refusal -- a
    `storage = "github"` command, a missing item or parent, a possible twin,
    a pull request target, or a live claim still
    on the item -- is `precondition_failed`, this command family's single
    generic bucket."""

    CREATED = "created"
    EDITED = "edited"
    UNCHANGED = "unchanged"
    CLOSED = "closed"
    SHOWN = "shown"
    PRECONDITION_FAILED = "precondition_failed"
    STALE = "stale"
    BODY_INVALID = "body_invalid"
    PARTIAL_WRITE = "partial_write"


def _refuse_item_body_invalid(defects: tuple[str, ...], *, as_json: bool) -> int:
    return report.refuse(
        _ItemReason.BODY_INVALID, defects[0], as_json=as_json, defects=list(defects)
    )


def _context_of_item_new(context: RunContext) -> RunContext:
    """Where `item new` creates its item: this checkout, or, when `--repo` names
    another repository, that repository's checkout on this machine, found by
    the discovery the MCP tools use, under its own storage and rules."""
    if context.repo is None or context.repo.path == context.remote_repository_id.path:
        return context
    return inbox.context_in_checkout_of(inbox.discovered(), context.repo.path)


def _cmd_item_new(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item new`: one fresh item under
    either storage pin, each through its own adapter's write
    (`_item_new_on_github`, `_item_new_on_state_ref`), both behind the same
    twin search `cut` runs (`cmd_cut.refuse_possible_twin`). Every refusal but a
    malformed piped body or a partial GitHub write reports through the
    shared envelope as `precondition_failed`."""
    as_json = parsed.json
    try:
        context = _context_of_item_new(context)
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
    carries none (`report.stdin_carries_a_body`)."""
    return report.read_piped_body() if report.stdin_carries_a_body() else ""


def _item_new_block_fields(parsed: argparse.Namespace) -> dict[str, object]:
    """Every block field `item new`'s own flags name, keyed as the block
    writes it -- only the flags given."""
    scope = cmd_cut.requested_body_scope(parsed.scope)
    requested: dict[str, object | None] = {
        **{key: getattr(parsed, key) for key, _meaning in ITEM_NEW_PROJECTION_FLAGS},
        "scope": None if scope is None else list(scope),
        "size": parsed.size,
        "whole": None if parsed.whole is None else body.bounded_whole_reason(parsed.whole),
    }
    return {key: value for key, value in requested.items() if value is not None}


def _item_new_body(parsed: argparse.Namespace, storage: body.Storage) -> str:
    """The body `item new` stores under either storage: the
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
    """`item new` under `storage = "github"`: the body it
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
        workboard.item_label(number, body.Storage.GITHUB), number, as_json=parsed.json
    )
    return 0


def _retype_task_parent(
    client: forge.ForgeWriter, parent: workboard.Issue | None, storage: body.Storage
) -> None:
    """Retype an open Task `--parent` to Container before it gets its first
    child, under either storage, and say so on stderr, leaving
    stdout and `--json` the created item's alone; any other parent keeps
    its kind."""
    if parent is None or parent.kind is not body.ItemKind.TASK:
        return
    client.set_item_kind(parent.number, body.ItemKind.CONTAINER)
    label = workboard.item_label(parent.number, storage)
    print(f"retyped {label} to Container for its first child", file=sys.stderr)


def _item_new_on_state_ref(parsed: argparse.Namespace, context: RunContext) -> int:
    """`item new` under `storage = "state-ref"`: the one
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
    missing section named on stderr."""
    client = _state_ref_board(context)
    parent = parsed.parent
    storage = context.config.storage
    new_body = _item_new_body(parsed, storage)
    if parent is not None and client.item_reference(parent).state is forge.ItemState.MISSING:
        raise protocol.ClaimUnavailableError(
            f"{workboard.item_label(parent, storage)} does not exist"
        )
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


def _cmd_item_edit(parsed: argparse.Namespace, context: RunContext) -> int:
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
        defects = _body_shape_defects(new_body, storage=storage)
        if defects:
            return _refuse_item_body_invalid(defects, as_json=as_json)
        replaced = _replace_whole_body(context, number, new_body, base=parsed.base)
        item_id = workboard.item_label(number, storage)
        _print_item_edit_result(item_id, number, replaced, as_json=as_json)
        return 0
    except decide.StaleBodyError as error:
        return report.refuse(_ItemReason.STALE, error, as_json=as_json)
    except forge.ForgeBodyWrittenError as error:
        return report.refuse_checked_write(error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _read_item_edit_body(number: int, storage: body.Storage, *, base: str | None) -> str:
    """`item edit`'s new body: refused, unread, without a `--base` (ITEM-73), and
    read only when stdin carries one (`report.stdin_carries_a_body`) -- an idle
    socket, a terminal, `/dev/null` or a closed stdin refuses at once, naming the
    redirect, rather than hanging on a read or replacing the body with nothing."""
    item_id = workboard.item_label(number, storage)
    if base is None:
        raise protocol.ClaimUnavailableError(
            f"item edit {item_id} needs --base <hash>; aco item show {item_id} --json prints it"
        )
    if not report.stdin_carries_a_body():
        raise protocol.ClaimUnavailableError(
            f"item edit {item_id} needs the new body on stdin: "
            f"aco item edit {item_id} --base <hash> < body.md"
        )
    return report.read_piped_body()


@dataclass(frozen=True)
class _WholeBodyEdit:
    """What a whole-body `item edit` left: `outcome` (`EDITED` or `UNCHANGED`), the hash
    of the body now stored and, under state-ref, the written blob's `oid`."""

    outcome: _ItemReason
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
    with decide.item_lock(context, number, environment=os.environ, home=Path.home()):
        if storage is body.Storage.STATE_REF:
            board = _state_ref_board(context)
            if not board.holds(number):
                raise protocol.ClaimUnavailableError(
                    board_read.missing_item_refusal(number, board, storage)
                )
            decide.require_current(base, board.stored_body_hash(number), item_id=item_id)
            try:
                board.update_item_body(number, new_body, replacing="")
            except protocol.ItemWrittenSinceReadError as error:
                raise decide.StaleBodyError(str(error)) from error
            stored = board.item_reference(number).body or ""
            return _WholeBodyEdit(
                _ItemReason.EDITED, decide.body_hash(stored), board.item_oid(number)
            )
        client = context.forge_writer
        reference = board_read.item_or_refuse(client, number, command="item edit", storage=storage)
        current = reference.body or ""
        decide.require_current(base, decide.body_hash(current), item_id=item_id)
        written = decide.write_item_body(client, number, new_body, replacing=current)
        outcome = _ItemReason.EDITED if written else _ItemReason.UNCHANGED
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
            outcome = _write_block_data(context.forge_writer, fresh, new_data)
        _print_item_edit_size_result(number, parsed.size, fresh.storage, outcome, as_json=as_json)
        return 0
    except forge.ForgeBodyWrittenError as error:
        return report.refuse_checked_write(error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _item_turn(
    context: RunContext, number: int, command: str
) -> AbstractContextManager[decide.FreshItem]:
    """The item's turn (ITEM-65) for a narrow `item edit`, refusing as `command`."""
    return decide.turn(context, number, command=command, environment=os.environ, home=Path.home())


def _write_block_data(
    client: forge.ForgeWriter, fresh: decide.FreshItem, new_data: dict[str, object]
) -> _ItemReason:
    """Writes `new_data` as item `number`'s block, every other byte
    untouched, or nothing at all when the block already carries it,
    so a repeated narrow edit leaves no empty write behind."""
    if new_data == fresh.located.data:
        return _ItemReason.UNCHANGED
    new_body = body.replace_block(fresh.body, fresh.located, new_data)
    decide.write_item_body(client, fresh.number, new_body, replacing=fresh.body)
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
            outcome = _write_block_data(context.forge_writer, fresh, new_data)
        _print_item_edit_whole_result(number, reason, fresh.storage, outcome, as_json=as_json)
        return 0
    except forge.ForgeBodyWrittenError as error:
        return report.refuse_checked_write(error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_ItemReason.PRECONDITION_FAILED, error, as_json=as_json)


def _print_item_edit_whole_result(
    number: int, reason: str, storage: body.Storage, outcome: _ItemReason, *, as_json: bool
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


_ITEM_CLOSE_GITHUB_REFUSAL = "the forge closes its issues; aco never governs them"


def _cmd_item_close(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item close ITEM`: the state-ref item's own record,
    closed -- `state` to `CLOSED`, `closed_at`/`updated_at` to now, the item
    file and every other byte untouched (`StateRefBoard.close_item`'s one
    CAS write over this process's own already-read oid, extending the
    record-owner rule by one field rather than composing a record here).
    Refuses under `storage = "github"` by name -- the forge closes its own
    issues, aco never governs them -- and, once the state ref is readable,
    refuses a live claim on the item before every item-state refusal
    (missing, malformed, already closed), then again on every write
    attempt, retries included (`protocol.ItemCloseIntent`), so
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
    into a hint. Prints one line, `CLOSED aco-xxxxxx` (`--json`:
    `{"item", "number", "closed_at", "parent_closable"}`), then `release
    --merged`'s own `freed:` line -- open items whose only open local
    blocker was this one (`workboard.freed_item_numbers`) --
    and, when this close was its parent's last open child, `release
    --merged`'s own parent hint. Every refusal reports through
    the shared envelope as `precondition_failed`."""
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
        named = workboard.named_refusal(error, body.Storage.STATE_REF)
        return report.refuse(_ItemReason.PRECONDITION_FAILED, named, as_json=as_json)


def _refuse_an_unreadable_relative(
    client: state_board.StateRefBoard, number: int, *, with_parent: bool
) -> None:
    """Refuses by the lowest id while one of `number`'s children -- the same
    children the board counts, an unreadable item that may be one included
    (ITEM-54) -- or, `with_parent`, its parent does not read
    (ITEM-53): a single-item write decides with those alone, so
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
    own `item close` would refuse by an unreadable relative (
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
    """Every open item `number`'s own close just freed -- the existing
    derivation, reused rather than reinvented, the same base-issues-plus-
    dependency-fetch wave `cmd_release._release_landing` runs for a merged release, read
    fresh off `client`'s own already-closed view so `number` itself never
    appears among its own candidates."""
    issues = client.list_open_board_issues()
    dependencies = board_read.fetch_validated_dependencies(client, issues)
    landed = workboard.IssueReference(client.repository.path, number)
    return workboard.freed_item_numbers(dependencies, landed)


@dataclass(frozen=True)
class _ItemCloseResult:
    """Everything `_print_item_close_result` needs for one `item close`,
    bundled so the printer itself takes one argument instead
    of PLR0913's five-scalar ceiling. `freed` is the freed numbers, or
    a hint when that read refused."""

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
        print(workboard.release_freed_line(result.freed, body.Storage.STATE_REF))
    parent_line = workboard.parent_closable_line(result.parent_closable, body.Storage.STATE_REF)
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
    per-adapter fact. `reference.origin` stays `None` for a
    GitHub-stored item, so this prints `origin none` there exactly like an
    unset parent prints `parent none`."""
    return (
        f"{items.format_item_id(number)} · #{number} · "
        f"{_item_state_text(reference.state)} · parent {_item_parent_id(parent) or 'none'} · "
        f"origin {reference.origin or 'none'}"
    )


def _cmd_item_show(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco item show`: the stored body behind one header
    line, its display controls escaped in text, byte-exact
    under `--json` -- read through the ordinary forge port, so it works
    identically under `storage = "github"` (the forge's own issue body) and
    `storage = "state-ref"` (the item file's own body); closing an item
    never deletes it, so a closed item is shown exactly like an open one.
    A missing id -- or a forge that fails either read this header needs --
    reports through the shared envelope as `precondition_failed`."""
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
    except items.MalformedItemError as error:
        return report.refuse(
            _ItemReason.PRECONDITION_FAILED, error, as_json=as_json, body_hash=error.body_hash
        )
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
            body_hash=decide.body_hash(body),
        )
        return 0
    print(_item_header(number, reference, parent))
    print(protocol.terminal_block(body), end="")
    return 0


# `item new --parent` also takes a Task: an item becomes a container exactly
# when it gets its first child, so that write retypes it.
_ITEM_PARENT_KINDS = frozenset({body.ItemKind.CONTAINER, body.ItemKind.TASK})


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`item`'s own four subcommands, reached through `cli._COMMANDS`,
    keep their routing independent of every other command."""
    if parsed.item_command == "new":
        return _cmd_item_new(parsed, context)
    if parsed.item_command == "edit":
        return _cmd_item_edit(parsed, context)
    if parsed.item_command == "close":
        return _cmd_item_close(parsed, context)
    return _cmd_item_show(parsed, context)
