"""A forge whose write operations fail the test: the enforcement that a read-only
command never writes."""

import pytest
from github_fixtures import FakeForge

from aco import body
from aco.workboard import MergeMethod


class ReaderOnlyForge(FakeForge):
    """A `FakeForge` whose write operations fail the test instead of quietly succeeding --
    the enforcement that a read-only command never writes, independent of the
    `ForgeReader`/`ForgeWriter` annotations (documentation only)."""

    def create_issue(self, *, title: str, body: str, kind: body.ItemKind) -> int:
        pytest.fail("a read-only command must never create an issue")

    def link_child(self, parent: int, child: int) -> None:
        pytest.fail("a read-only command must never link a child")

    def create_child(self, *, parent: int, title: str, body: str, kind: body.ItemKind) -> int:
        pytest.fail("a read-only command must never create a child")

    def update_item_body(self, number: int, body: str, *, replacing: str) -> None:
        pytest.fail("a read-only command must never update an item body")

    def set_item_kind(self, number: int, kind: body.ItemKind) -> None:
        pytest.fail("a read-only command must never retype an item")

    def add_label(self, number: int, label: str) -> None:
        pytest.fail("a read-only command must never add a label")

    def remove_label(self, number: int, label: str) -> None:
        pytest.fail("a read-only command must never remove a label")

    def close_landed_item(self, number: int, *, pull_request: int) -> None:
        pytest.fail("a read-only command must never close a landed item")

    def merge_landing(
        self, number: int, *, head_sha: str, method: MergeMethod, title: str, body: str
    ) -> str:
        pytest.fail("a read-only command must never merge a pull request")

    def delete_branch(self, branch: str) -> None:
        pytest.fail("a read-only command must never delete a branch")
