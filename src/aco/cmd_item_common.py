"""What the `item` subcommands share (`specs/item.spec.md`): the `--json` `reason`
vocabulary and the refusals and reads more than one subcommand makes."""

from enum import StrEnum
from typing import cast

from . import body, report, state_board
from .session import RunContext


class ItemReason(StrEnum):
    """`aco item`'s own `--json` `reason` vocabulary, shared across its four
    subcommands (`specs/item.spec.md`): `created`/`edited`/
    `closed`/`shown` name each subcommand's own success; `unchanged`, an
    `item edit` whose value or body is already stored, which writes nothing;
    `stale`, a whole-body `item edit` whose `--base` is no longer the item's
    body hash. `body_invalid` covers only `item new`'s and `item edit`'s own piped-body shape check
    (`body_shape_defects`, the same check `check -` runs), carrying
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


def refuse_item_body_invalid(defects: tuple[str, ...], *, as_json: bool) -> int:
    return report.refuse(
        ItemReason.BODY_INVALID, defects[0], as_json=as_json, defects=list(defects)
    )


def body_shape_defects(
    raw_body: str, *, storage: body.Storage = body.Storage.GITHUB
) -> tuple[str, ...]:
    """`item edit`'s own accessor onto `body.body_shape_check`:
    only the defect sentences, never the verdict `check
    <item>` and `check -` read for their own `--json` `reason`."""
    return body.body_shape_check(raw_body, storage=storage).defects


def state_ref_board(context: RunContext) -> state_board.StateRefBoard:
    """`context`'s own forge as the state-ref board, for an item command
    that has already refused every other storage pin: under `state-ref`
    `session._build_forge` builds exactly `session._state_ref_forge`'s board, so the cast is
    honest, not a suppression -- the same narrowing `RunContext.forge_writer`
    performs for the generic writing surface."""
    return cast(state_board.StateRefBoard, context.forge)


def refuse_an_unreadable_relative(
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
