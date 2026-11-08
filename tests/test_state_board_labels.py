"""`StateRefBoard.add_label` (`specs/mcp.spec.md`): a state-ref item carries no
forge labels, so the write is refused by name."""

from collections.abc import Mapping
from typing import cast

import pytest

from aco import forge, protocol
from aco.state_board import ItemWriter, StateRefBoard


def test_a_state_ref_board_refuses_to_add_a_label() -> None:
    no_items: Mapping[str, bytes] = {}
    no_oids: dict[str, protocol.ObjectId] = {}
    board = StateRefBoard(
        repository=forge.RepositoryId("file", ("acme",), "items"),
        default_branch="main",
        item_files=no_items,
        item_oids=no_oids,
        writer=cast(ItemWriter, None),
    )

    with pytest.raises(forge.ForgeUnsupportedError):
        board.add_label(1, "needs-operator")
