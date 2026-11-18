"""`StateRefBoard.add_label` and `remove_label` (`specs/mcp.spec.md`): a state-ref
item carries no forge labels, so each write is refused by name."""

from collections.abc import Callable, Mapping
from typing import cast

import pytest

from aco import forge, protocol
from aco.state_board import ItemWriter, StateRefBoard


@pytest.mark.parametrize("write", ["add_label", "remove_label"])
def test_a_state_ref_board_refuses_to_write_a_label(write: str) -> None:
    no_items: Mapping[str, bytes] = {}
    no_oids: dict[str, protocol.ObjectId] = {}
    board = StateRefBoard(
        repository=forge.RepositoryId("file", ("acme",), "items"),
        default_branch="main",
        item_files=no_items,
        item_oids=no_oids,
        writer=cast(ItemWriter, None),
    )
    refused = cast(Callable[[int, str], None], getattr(board, write))

    with pytest.raises(forge.ForgeUnsupportedError):
        refused(1, "needs-operator")
