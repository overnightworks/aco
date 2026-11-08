"""The state-ref adapter's single-item read."""

import hashlib

from board_fixtures import block_body
from store_fixtures import item_record

from aco import forge, items, protocol
from aco.body import render_block
from aco.state_board import StateRefBoard

_ITEM_ID = "aco-000002"


class _ReadOnlyWriter:
    """An `ItemWriter` for a test that only reads: any write is the test's defect."""

    def write_item(self, item_id: str, **_arguments: object) -> protocol.ObjectId:
        raise AssertionError(f"unexpected write to item {item_id}")

    def close_item(self, item_id: str, **_arguments: object) -> protocol.ObjectId:
        raise AssertionError(f"unexpected close of item {item_id}")


def _board_with_one_open_task() -> StateRefBoard:
    block = {
        "version": 1,
        "now": "Build it.",
        "next": "Ship it.",
        "done_when": "It is shipped.",
        "record": item_record(title="Slice", state="open", kind="task"),
    }
    body = block_body(render_block(block).removesuffix("\n"), before="Prose.\n\n", after="")
    return StateRefBoard(
        repository=forge.RepositoryId("file", ("acme",), "items"),
        default_branch="main",
        item_files={f"{_ITEM_ID}.md": body.encode()},
        item_oids={_ITEM_ID: protocol.ObjectId(hashlib.sha1(b"item").hexdigest())},  # noqa: S324 - a git object id is SHA-1 by definition
        writer=_ReadOnlyWriter(),
    )


def test_a_state_ref_item_reads_as_a_members_item() -> None:
    board = _board_with_one_open_task()

    reference = board.item_reference(items.item_number(_ITEM_ID))

    assert reference.author_is_member is True
