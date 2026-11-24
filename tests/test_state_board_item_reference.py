"""The state-ref adapter's single-item read."""

import hashlib

from board_fixtures import block_body
from store_fixtures import item_record

from aco import forge, items, protocol, workboard
from aco.body import render_block
from aco.state_board import StateRefBoard

_ITEM_ID = "aco-000002"


class _ReadOnlyWriter:
    """An `ItemWriter` for a test that only reads: any write is the test's defect."""

    def write_item(self, item_id: str, **_arguments: object) -> protocol.ObjectId:
        raise AssertionError(f"unexpected write to item {item_id}")

    def close_item(self, item_id: str, **_arguments: object) -> protocol.ObjectId:
        raise AssertionError(f"unexpected close of item {item_id}")


def _item_file(title: str, parent: str | None = None) -> bytes:
    block = {
        "version": 1,
        "now": "Build it.",
        "next": "Ship it.",
        "done_when": "It is shipped.",
        "record": item_record(title=title, state="open", kind="task", parent=parent),
    }
    body = block_body(render_block(block).removesuffix("\n"), before="Prose.\n\n", after="")
    return body.encode()


def _board(item_files: dict[str, bytes]) -> StateRefBoard:
    return StateRefBoard(
        repository=forge.RepositoryId("file", ("acme",), "items"),
        default_branch="main",
        item_files=item_files,
        item_oids={
            name.removesuffix(".md"): protocol.ObjectId(hashlib.sha1(b"item").hexdigest())  # noqa: S324 - a git object id is SHA-1 by definition
            for name in item_files
        },
        writer=_ReadOnlyWriter(),
    )


def _board_with_one_open_task() -> StateRefBoard:
    return _board({f"{_ITEM_ID}.md": _item_file("Slice")})


def test_a_state_ref_item_reads_as_a_members_item() -> None:
    board = _board_with_one_open_task()

    reference = board.item_reference(items.item_number(_ITEM_ID))

    assert reference.author_is_member is True


def test_a_child_of_an_unreadable_item_reads_its_parent_with_the_kind_unknown() -> None:
    """A blank-title parent is unreadable; its child still reads as nested."""
    child_id = "aco-000003"
    board = _board(
        {f"{_ITEM_ID}.md": _item_file(""), f"{child_id}.md": _item_file("Child", _ITEM_ID)}
    )

    parent = board.parent_issue(items.item_number(child_id))

    assert parent is not None
    assert (parent.reference.number, parent.kind) == (items.item_number(_ITEM_ID), None)


def test_a_childs_item_reference_carries_its_parent_number() -> None:
    """ITEM-82."""
    child_id = "aco-000003"
    board = _board(
        {f"{_ITEM_ID}.md": _item_file("Slice"), f"{child_id}.md": _item_file("Child", _ITEM_ID)}
    )

    references = board.item_references([items.item_number(_ITEM_ID), items.item_number(child_id)])

    assert [reference.parent for reference in references.values()] == [
        None,
        items.item_number(_ITEM_ID),
    ]


def test_an_item_reference_of_a_child_whose_parent_is_missing_still_reads() -> None:
    """ITEM-82."""
    board = _board({f"{_ITEM_ID}.md": _item_file("Slice", "aco-ffffff")})

    reference = board.item_reference(items.item_number(_ITEM_ID))

    assert reference.parent == items.item_number("aco-ffffff")


def test_a_listed_child_names_its_parent_without_reading_it() -> None:
    """ABRD-194."""
    child_id = "aco-000003"
    board = _board(
        {f"{_ITEM_ID}.md": _item_file("Slice"), f"{child_id}.md": _item_file("Child", _ITEM_ID)}
    )

    listed = {issue.number: issue.parent for issue in board.list_open_board_issues()}

    assert listed == {
        items.item_number(_ITEM_ID): None,
        items.item_number(child_id): workboard.IssueReference(
            board.repository.path, items.item_number(_ITEM_ID)
        ),
    }
