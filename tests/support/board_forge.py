"""A file-backed forge for the decision board's tests.

`BoardForge` holds what a GitHub issue holds -- number, title and body -- in
one JSON file in the checkout it serves, replaced whole on every write, so a
reader in another thread never sees half a write. Every request is appended
to a log beside it. `run_context` is the one replacement for
`session.run_context`: the board tests' conftest and the E2E server install
it, so the board's aco source reaches this forge and never GitHub.
"""

from __future__ import annotations

import json
import os
import threading
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import NoReturn

from board_fixtures import MINIMAL_BLOCK_TOML, block_body, board_issue

from aco import body, expectation_grammar, forge, session, workboard
from aco.body import ItemKind

_STATE_FILE = "board-forge.json"
_REQUEST_LOG = "board-forge-requests.jsonl"
_ITEMS = "items"
_LISTING_FAILURE = "listing_failure"
_EDITS_BEFORE_READ = "edits_before_read"
_ITEM_READ_FAILURE = "item_read_failure"
_CLOSED = "closed"
RULING_DAY = date(2026, 10, 3)
"""The day aco rules on over this forge, so a page shows a date it can name."""


class ForgeOperation(StrEnum):
    LIST_OPEN_ISSUES = "list_open_board_issues"
    READ_ITEM = "item_reference"
    WRITE_BODY = "update_item_body"


@dataclass(frozen=True)
class ForgeRequest:
    operation: ForgeOperation
    item: int | None = None


@dataclass
class StoredItem:
    title: str
    body: str


@dataclass
class _ForgeState:
    """Everything the forge file holds, keyed by item number."""

    items: dict[int, StoredItem] = field(default_factory=dict[int, StoredItem])
    listing_failure: str | None = None
    edits_before_read: dict[int, str] = field(default_factory=dict[int, str])
    item_read_failure: str | None = None
    closed: set[int] = field(default_factory=set[int])

    @classmethod
    def from_json(cls, text: str) -> _ForgeState:
        stored = json.loads(text)
        return cls(
            {int(number): StoredItem(**item) for number, item in stored[_ITEMS].items()},
            stored[_LISTING_FAILURE],
            {int(number): edit for number, edit in stored[_EDITS_BEFORE_READ].items()},
            stored[_ITEM_READ_FAILURE],
            set(stored[_CLOSED]),
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                _ITEMS: {number: asdict(item) for number, item in self.items.items()},
                _LISTING_FAILURE: self.listing_failure,
                _EDITS_BEFORE_READ: self.edits_before_read,
                _ITEM_READ_FAILURE: self.item_read_failure,
                _CLOSED: sorted(self.closed),
            }
        )


@dataclass(frozen=True)
class BoardForge:
    """The forge of the checkout at `directory`."""

    directory: Path

    def put_item(self, number: int, raw_body: str, *, title: str = "Karte") -> None:
        state = self._state()
        state.items[number] = StoredItem(title, raw_body)
        self._replace_state(state)

    def replace_items(self, items: Mapping[int, StoredItem]) -> None:
        """The forge holds exactly `items`, open, with no listing or item-read
        failure and no pending edit, in one write."""
        self._replace_state(_ForgeState(dict(items)))

    def remove_item(self, number: int) -> None:
        """Item `number` leaves the open listing, as a closed issue does."""
        state = self._state()
        del state.items[number]
        self._replace_state(state)

    def fail_listing(self, message: str) -> None:
        """Every later listing raises a forge failure carrying `message`."""
        state = self._state()
        state.listing_failure = message
        self._replace_state(state)

    def fail_item_reads(self, message: str) -> None:
        """Every later read of one item raises a forge failure carrying `message`."""
        state = self._state()
        state.item_read_failure = message
        self._replace_state(state)

    def close_item(self, number: int) -> None:
        """Item `number` is closed: the listing leaves it out, and a read of
        it answers closed with its title and body."""
        state = self._state()
        state.closed.add(number)
        self._replace_state(state)

    def edit_before_next_read(self, number: int, raw_body: str) -> None:
        """Item `number` holds `raw_body` from its next read on: a card changed
        after the page read, first seen by the decision's one read of it."""
        state = self._state()
        state.edits_before_read[number] = raw_body
        self._replace_state(state)

    def stored_body(self, number: int) -> str:
        return self._state().items[number].body

    def stored_entries(self, number: int) -> list[dict[str, object]]:
        """Item `number`'s `[[expectation]]` entries as its stored body holds them."""
        return body.block_expectation_dicts(body.locate_block(self.stored_body(number)).data)

    def request_log(self) -> tuple[ForgeRequest, ...]:
        log = self.directory / _REQUEST_LOG
        if not log.exists():
            return ()
        return tuple(
            ForgeRequest(ForgeOperation(entry["operation"]), entry["item"])
            for entry in map(json.loads, log.read_text(encoding="utf-8").splitlines())
        )

    def item_requests(self) -> tuple[ForgeRequest, ...]:
        """Every read or write of one item, leaving out the listings."""
        return tuple(request for request in self.request_log() if request.item is not None)

    def body_writes(self) -> list[int | None]:
        """The item of every body write, in order."""
        return [
            request.item
            for request in self.request_log()
            if request.operation is ForgeOperation.WRITE_BODY
        ]

    @property
    def repository(self) -> forge.RepositoryId:
        return forge.RepositoryId("github.com", ("board-forge",), self.directory.name)

    @property
    def requests(self) -> int:
        return len(self.request_log())

    @property
    def lists_pull_requests(self) -> bool:
        return False

    def list_open_board_issues(self) -> tuple[workboard.Issue, ...]:
        self._log(ForgeRequest(ForgeOperation.LIST_OPEN_ISSUES))
        state = self._state()
        if state.listing_failure is not None:
            raise forge.ForgeError(state.listing_failure)
        return tuple(
            board_issue(number, item.title, item.body)
            for number, item in state.items.items()
            if number not in state.closed
        )

    def item_reference(self, number: int) -> forge.ItemReference:
        self._log(ForgeRequest(ForgeOperation.READ_ITEM, number))
        state = self._state()
        if state.item_read_failure is not None:
            raise forge.ForgeError(state.item_read_failure)
        edit = state.edits_before_read.pop(number, None)
        if edit is not None:
            state.items[number].body = edit
            self._replace_state(state)
        item = state.items.get(number)
        if item is None:
            return forge.ItemReference(forge.ItemState.MISSING)
        item_state = forge.ItemState.CLOSED if number in state.closed else forge.ItemState.OPEN
        return forge.ItemReference(item_state, item.title, item.body)

    def update_item_body(self, number: int, body: str) -> None:
        self._log(ForgeRequest(ForgeOperation.WRITE_BODY, number))
        state = self._state()
        state.items[number].body = body
        self._replace_state(state)

    def item_references(self, numbers: Iterable[int]) -> Mapping[int, forge.ItemReference]:
        _unsupported("item_references")

    def list_board_dependencies(self, number: int) -> tuple[workboard.IssueDependency, ...]:
        _unsupported("list_board_dependencies")

    def list_open_board_pull_requests(self) -> tuple[workboard.PullRequest, ...]:
        _unsupported("list_open_board_pull_requests")

    def list_recent_merged_board_pull_requests(
        self, since: datetime
    ) -> tuple[workboard.PullRequest, ...]:
        _unsupported("list_recent_merged_board_pull_requests")

    def list_children(self, number: int) -> tuple[workboard.ChildItem, ...]:
        _unsupported("list_children")

    def reopened_at(self, numbers: Iterable[int]) -> Mapping[int, datetime | None]:
        _unsupported("reopened_at")

    def landing(self, number: int) -> forge.Landing:
        _unsupported("landing")

    def pull_request_changes(self, number: int) -> forge.PullRequestChanges:
        _unsupported("pull_request_changes")

    def parent_issue(self, number: int) -> workboard.ParentIssue | None:
        _unsupported("parent_issue")

    def parent_number(self, number: int) -> int | None:
        _unsupported("parent_number")

    def default_branch(self) -> str:
        _unsupported("default_branch")

    def list_recently_closed_issues(self, since: datetime) -> tuple[forge.ClosedIssue, ...]:
        _unsupported("list_recently_closed_issues")

    def link_child(self, parent: int, child: int) -> None:
        _unsupported("link_child")

    def create_issue(self, *, title: str, body: str, kind: ItemKind) -> int:
        _unsupported("create_issue")

    def create_child(self, *, parent: int, title: str, body: str, kind: ItemKind) -> int:
        _unsupported("create_child")

    def set_item_kind(self, number: int, kind: ItemKind) -> None:
        _unsupported("set_item_kind")

    def _log(self, request: ForgeRequest) -> None:
        _append_line(self.directory / _REQUEST_LOG, json.dumps(asdict(request)))

    def _state(self) -> _ForgeState:
        stored = self.directory / _STATE_FILE
        if not stored.exists():
            return _ForgeState()
        return _ForgeState.from_json(stored.read_text(encoding="utf-8"))

    def _replace_state(self, state: _ForgeState) -> None:
        stored = self.directory / _STATE_FILE
        written = stored.with_name(f"{stored.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        written.write_text(state.to_json(), encoding="utf-8")
        written.replace(stored)


def _unsupported(operation: str) -> NoReturn:
    raise forge.ForgeUnsupportedError(f"the board's test forge has no {operation}")


def _append_line(log: Path, line: str) -> None:
    with log.open("a", encoding="utf-8") as appended:
        appended.write(line + "\n")


def _forge_of(context: session.RunContext) -> forge.ForgeWriter:
    return BoardForge(context.toplevel)


def run_context(repo: forge.RepositoryId | None) -> session.RunContext:
    """`session.run_context` over the checkout's own `BoardForge`, ruling on
    `RULING_DAY`."""
    return session.RunContext(repo, build_forge=_forge_of, today=lambda: RULING_DAY)


def item_body(*entries: Mapping[str, object]) -> str:
    """An item body whose block carries `entries` as its `[[expectation]]`
    lines, rendered by aco itself. A ruled option line without a
    `card_hash` gets the hash of its own card."""
    data = {
        **tomllib.loads(MINIMAL_BLOCK_TOML),
        "expectation": [_with_card_hash(entry) for entry in entries],
    }
    return block_body(body.render_block(data).removesuffix("\n"))


def _with_card_hash(entry: Mapping[str, object]) -> dict[str, object]:
    if "ruling" in entry and "card_hash" not in entry and expectation_grammar.is_option_line(entry):
        return {**entry, "card_hash": expectation_grammar.card_hash(entry)}
    return dict(entry)
