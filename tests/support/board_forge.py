"""A file-backed forge for the decision board's tests.

`BoardForge` holds what a GitHub issue holds -- number, title and body -- in
one JSON file in the checkout it serves, replaced whole on every write, so a
reader in another thread never sees half a write. Every request is appended
to a log beside it. `run_context` is the one replacement for
`session.run_context`: the board tests' conftest and the E2E server install
it, so the board's aco source reaches this forge and never GitHub.
"""

import fcntl
import json
import os
import shutil
import subprocess
import threading
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn, cast

from board_fixtures import MINIMAL_BLOCK_TOML, NoBoardProbe, block_body, board_issue
from cli_fixtures import real_git, sealed_git_environment

from aco import body, expectation_grammar, forge, repositories, session, store, workboard
from aco.body import ItemKind
from aco.lane_record import LaneRecord

_STATE_FILE = "board-forge.json"
_SEARCH_INDEX = "board-forge-search.json"
_REQUEST_LOG = "board-forge-requests.jsonl"
_ITEMS = "items"
_LISTING_FAILURE = "listing_failure"
_ITEM_READ_FAILURE = "item_read_failure"
_PARENT_READ_FAILURE = "parent_read_failure"
_CHILD_READ_FAILURE = "child_read_failure"
_WRITE_FAILURE = "write_failure"
_WRITE_ANSWER = "write_answer"
_REPLACINGS = "replacings"
_CLOSED = "closed"
_LABEL_FAILURE = "label_failure"
RULING_DAY = date(2026, 10, 3)
"""The day aco rules on over this forge, so a page shows a date it can name."""


class ForgeOperation(StrEnum):
    LIST_OPEN_ISSUES = "list_open_board_issues"
    READ_PARENT = "parent_issue"
    LIST_CHILDREN = "list_children"
    READ_ITEM = "item_reference"
    WRITE_BODY = "update_item_body"
    CREATE_ISSUE = "create_issue"
    ADD_LABEL = "add_label"
    REMOVE_LABEL = "remove_label"


@dataclass(frozen=True)
class ForgeRequest:
    operation: ForgeOperation
    item: int | None = None


@dataclass
class StoredChild:
    number: int
    closed: bool = False
    title: str = ""
    """What the sub-issue list reports; empty reports `Child <number>`."""


def child_list(*, closed: Iterable[int] = (), open: Iterable[int] = ()) -> list[StoredChild]:
    """A container's sub-issues: the `open` numbers, then the `closed` ones."""
    return [*(StoredChild(number) for number in open), *(StoredChild(n, True) for n in closed)]


@dataclass
class StoredItem:
    title: str
    body: str
    author_is_member: bool = True
    labels: list[str] = field(default_factory=list[str])
    kind: str | None = None
    children: list[StoredChild] | None = None
    """The sub-issue list a container reports counts for; `None` reports none."""
    parent: int | None = None


type _CheckAnswer = forge.ForgeBodyOverwrittenError | forge.ForgeBodyNotVerifiedError


@dataclass
class _ForgeState:
    """Everything the forge file holds, keyed by item number."""

    items: dict[int, StoredItem] = field(default_factory=dict[int, StoredItem])
    listing_failure: str | None = None
    item_read_failure: str | None = None
    parent_read_failure: str | None = None
    child_read_failure: str | None = None
    write_failure: str | None = None
    write_answer: _CheckAnswer | None = None
    replacings: list[str] = field(default_factory=list[str])
    closed: set[int] = field(default_factory=set[int])
    label_failure: str | None = None

    @classmethod
    def from_json(cls, text: str) -> _ForgeState:
        stored = json.loads(text)
        return cls(
            {int(number): _stored_item(item) for number, item in stored[_ITEMS].items()},
            stored[_LISTING_FAILURE],
            stored[_ITEM_READ_FAILURE],
            stored[_PARENT_READ_FAILURE],
            stored[_CHILD_READ_FAILURE],
            stored[_WRITE_FAILURE],
            _answer_from_json(stored[_WRITE_ANSWER]),
            stored[_REPLACINGS],
            set(stored[_CLOSED]),
            stored[_LABEL_FAILURE],
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                _ITEMS: {number: asdict(item) for number, item in self.items.items()},
                _LISTING_FAILURE: self.listing_failure,
                _ITEM_READ_FAILURE: self.item_read_failure,
                _PARENT_READ_FAILURE: self.parent_read_failure,
                _CHILD_READ_FAILURE: self.child_read_failure,
                _WRITE_FAILURE: self.write_failure,
                _WRITE_ANSWER: _answer_to_json(self.write_answer),
                _REPLACINGS: self.replacings,
                _CLOSED: sorted(self.closed),
                _LABEL_FAILURE: self.label_failure,
            }
        )


def _stored_item(stored: dict[str, object]) -> StoredItem:
    children = stored["children"]
    return StoredItem(
        **{
            **stored,
            "children": None
            if children is None
            else [StoredChild(**child) for child in cast(list[dict[str, Any]], children)],
        }
    )


def _answer_to_json(answer: _CheckAnswer | None) -> dict[str, object] | None:
    if answer is None:
        return None
    if isinstance(answer, forge.ForgeBodyOverwrittenError):
        return {
            "number": answer.number,
            "edited_at": answer.edited_at,
            "editor": answer.editor,
            "kept": answer.kept,
        }
    return {"number": answer.number, "cause": answer.cause}


def _answer_from_json(stored: dict[str, object] | None) -> _CheckAnswer | None:
    if stored is None:
        return None
    if "kept" in stored:
        return forge.ForgeBodyOverwrittenError(
            int(str(stored["number"])),
            str(stored["edited_at"]),
            str(stored["editor"]),
            kept=bool(stored["kept"]),
        )
    return forge.ForgeBodyNotVerifiedError(int(str(stored["number"])), str(stored["cause"]))


@dataclass(frozen=True)
class BoardForge:
    """The forge of the checkout at `directory`."""

    directory: Path

    def put_item(
        self,
        number: int,
        raw_body: str,
        *,
        title: str = "Karte",
        author_is_member: bool = True,
        labels: Iterable[str] = (),
        kind: ItemKind | None = None,
        children: list[StoredChild] | None = None,
        parent: int | None = None,
    ) -> None:
        """Item `number`; a container's `children` are its sub-issues, whose
        list its counts derive from, and `parent` the item it is a child of."""
        state = self._state()
        state.items[number] = StoredItem(
            title,
            raw_body,
            author_is_member,
            list(labels),
            None if kind is None else kind.value,
            children,
            parent,
        )
        self._replace_state(state)

    def replace_items(self, items: Mapping[int, StoredItem]) -> None:
        """The forge holds exactly `items`, open, with no listing or item-read
        failure and no pending write failure, in one write."""
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

    def fail_parent_reads(self, message: str) -> None:
        """Every later read of an item's parent raises a forge failure carrying `message`."""
        state = self._state()
        state.parent_read_failure = message
        self._replace_state(state)

    def fail_child_reads(self, message: str) -> None:
        """Every later read of a container's sub-issues raises a failure carrying `message`."""
        state = self._state()
        state.child_read_failure = message
        self._replace_state(state)

    def close_item(self, number: int) -> None:
        """Item `number` is closed: the listing leaves it out, and a read of
        it answers closed with its title and body."""
        state = self._state()
        state.closed.add(number)
        self._replace_state(state)

    def break_next_write(self, message: str) -> None:
        """The next body write is logged, then raises `RuntimeError(message)`
        and stores nothing; the write after it stores again."""
        state = self._state()
        state.write_failure = message
        self._replace_state(state)

    def fail_label_removals(self, message: str) -> None:
        """Every later label removal is logged, then raises a forge failure carrying `message`."""
        state = self._state()
        state.label_failure = message
        self._replace_state(state)

    def answer_next_write(self, answer: _CheckAnswer) -> None:
        """The next body write is logged and stored, then raises `answer`, the
        forge's check of a write that landed; the write after it answers nothing."""
        state = self._state()
        state.write_answer = answer
        self._replace_state(state)

    def body_replacings(self) -> list[str]:
        """The `replacing` text of every body write, in order."""
        return self._state().replacings

    def stored_body(self, number: int) -> str:
        return self._state().items[number].body

    def stored_item(self, number: int) -> StoredItem:
        return self._state().items[number]

    def ruling_items(self) -> tuple[forge.RulingItem, ...]:
        """Every item the forge holds, closed ones included, as a search finds it."""
        return tuple(
            forge.RulingItem(
                str(self.repository), number, item.title, item.body, item.author_is_member
            )
            for number, item in self._state().items.items()
        )

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
            board_issue(
                number,
                item.title,
                item.body,
                labels=tuple(item.labels),
                kind=None if item.kind is None else ItemKind(item.kind),
                author_is_member=item.author_is_member,
                children_closed=_closed_count(item),
                children_total=None if item.children is None else len(item.children),
            )
            for number, item in state.items.items()
            if number not in state.closed
        )

    def item_reference(self, number: int) -> forge.ItemReference:
        self._log(ForgeRequest(ForgeOperation.READ_ITEM, number))
        state = self._state()
        if state.item_read_failure is not None:
            raise forge.ForgeError(state.item_read_failure)
        item = state.items.get(number)
        if item is None:
            return forge.ItemReference(forge.ItemState.MISSING)
        item_state = forge.ItemState.CLOSED if number in state.closed else forge.ItemState.OPEN
        return forge.ItemReference(
            item_state, item.title, item.body, author_is_member=item.author_is_member
        )

    def update_item_body(self, number: int, body: str, *, replacing: str) -> None:
        self._log(ForgeRequest(ForgeOperation.WRITE_BODY, number))
        state = self._state()
        failure = state.write_failure
        if failure is not None:
            state.write_failure = None
            self._replace_state(state)
            raise RuntimeError(failure)
        state.items[number].body = body
        state.replacings.append(replacing)
        answer = state.write_answer
        state.write_answer = None
        self._replace_state(state)
        if answer is not None:
            raise answer

    def list_board_dependencies(self, number: int) -> tuple[workboard.IssueDependency, ...]:
        _unsupported("list_board_dependencies")

    def list_open_board_pull_requests(self) -> tuple[workboard.PullRequest, ...]:
        _unsupported("list_open_board_pull_requests")

    def list_recent_merged_board_pull_requests(
        self, since: datetime
    ) -> tuple[workboard.PullRequest, ...]:
        _unsupported("list_recent_merged_board_pull_requests")

    def list_children(self, number: int) -> workboard.ChildList:
        self._log(ForgeRequest(ForgeOperation.LIST_CHILDREN, number))
        state = self._state()
        if state.child_read_failure is not None:
            raise forge.ForgeTransientError(state.child_read_failure)
        return tuple(
            workboard.ChildItem(
                child.number,
                workboard.ChildState.CLOSED if child.closed else workboard.ChildState.OPEN,
                child.title or f"Child {child.number}",
            )
            for child in state.items[number].children or ()
        )

    def reopened_at(self, numbers: Iterable[int]) -> Mapping[int, datetime | None]:
        _unsupported("reopened_at")

    def landing(self, number: int) -> forge.Landing:
        _unsupported("landing")

    def pull_request_changes(self, number: int) -> forge.PullRequestChanges:
        _unsupported("pull_request_changes")

    def parent_issue(self, number: int) -> workboard.ParentIssue | None:
        self._log(ForgeRequest(ForgeOperation.READ_PARENT, number))
        state = self._state()
        if state.parent_read_failure is not None:
            raise forge.ForgeTransientError(state.parent_read_failure)
        parent = state.items[number].parent
        if parent is None:
            return None
        return workboard.ParentIssue(
            workboard.IssueReference(str(self.repository), parent), state.items[parent].body
        )

    def parent_number(self, number: int) -> int | None:
        _unsupported("parent_number")

    def default_branch(self) -> str:
        _unsupported("default_branch")

    def list_recently_closed_issues(self, since: datetime) -> tuple[forge.ClosedIssue, ...]:
        _unsupported("list_recently_closed_issues")

    def newest_labelled_issues(self, label: str) -> tuple[workboard.Issue, ...]:
        _unsupported("newest_labelled_issues")

    def link_child(self, parent: int, child: int) -> None:
        _unsupported("link_child")

    def create_issue(self, *, title: str, body: str, kind: ItemKind) -> int:
        """An open item a member wrote, numbered after the highest the forge holds."""
        state = self._state()
        number = max(state.items, default=0) + 1
        state.items[number] = StoredItem(title, body, kind=kind.value)
        self._replace_state(state)
        self._log(ForgeRequest(ForgeOperation.CREATE_ISSUE, number))
        return number

    def add_label(self, number: int, label: str) -> None:
        self._log(ForgeRequest(ForgeOperation.ADD_LABEL, number))
        state = self._state()
        if label not in state.items[number].labels:
            state.items[number].labels.append(label)
        self._replace_state(state)

    def remove_label(self, number: int, label: str) -> None:
        self._log(ForgeRequest(ForgeOperation.REMOVE_LABEL, number))
        state = self._state()
        if state.label_failure is not None:
            raise forge.ForgeError(state.label_failure)
        if label in state.items[number].labels:
            state.items[number].labels.remove(label)
        self._replace_state(state)

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


def _closed_count(item: StoredItem) -> int | None:
    return None if item.children is None else sum(child.closed for child in item.children)


def item_lock_is_held(state_home: Path) -> bool:
    """Whether another holder has an item lock under the state home a test set."""
    directory = state_home / "state" / "aco" / "item-locks"
    for lock in directory.iterdir() if directory.is_dir() else ():
        with lock.open("rb") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(probe, fcntl.LOCK_UN)
    return False


def item_signals(state_home: Path) -> list[str]:
    """The item signals, by file name, under the state home a test set."""
    directory = state_home / "state" / "aco" / "item-signals"
    return sorted(signal.name for signal in directory.iterdir()) if directory.is_dir() else []


def _unsupported(operation: str) -> NoReturn:
    raise forge.ForgeUnsupportedError(f"the board's test forge has no {operation}")


def _append_line(log: Path, line: str) -> None:
    with log.open("a", encoding="utf-8") as appended:
        appended.write(line + "\n")


def _forge_of(context: session.RunContext) -> forge.ForgeWriter:
    return BoardForge(context.toplevel)


@dataclass(frozen=True)
class _SearchState:
    directories: tuple[str, ...] = ()
    failure: str | None = None
    incomplete: bool = False
    queries: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchIndex:
    """The forge's search index, a file beside aco's config file: it finds every
    item, closed ones included, of the board forges a test `include`s, whatever
    the query, records the queries it receives, and can be made to fail or to
    answer an incomplete result."""

    path: Path

    def include(self, *forges: BoardForge) -> None:
        state = self._state()
        directories = (*state.directories, *(str(each.directory) for each in forges))
        self._replace_state(replace(state, directories=directories))

    def fail(self, message: str) -> None:
        """Every later search raises a forge failure carrying `message`."""
        self._replace_state(replace(self._state(), failure=message))

    def mark_incomplete(self) -> None:
        """Every later search answers an incomplete result."""
        self._replace_state(replace(self._state(), incomplete=True))

    def queries(self) -> tuple[str, ...]:
        """Every query searched so far, in order."""
        return self._state().queries

    def search(self, query: str) -> forge.RulingSearchResult:
        state = self._state()
        self._replace_state(replace(state, queries=(*state.queries, query)))
        if state.failure is not None:
            raise forge.ForgeError(state.failure)
        items = tuple(
            item
            for directory in state.directories
            for item in BoardForge(Path(directory)).ruling_items()
        )
        return forge.RulingSearchResult(items, complete=not state.incomplete)

    def _state(self) -> _SearchState:
        if not self.path.exists():
            return _SearchState()
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        return _SearchState(
            directories=tuple(stored["directories"]),
            failure=stored["failure"],
            incomplete=stored["incomplete"],
            queries=tuple(stored["queries"]),
        )

    def _replace_state(self, state: _SearchState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(state)), encoding="utf-8")


def search_index() -> SearchIndex:
    """The search index of the config home the run sees."""
    config_file = repositories.config_path(os.environ, Path.home())
    return SearchIndex(config_file.with_name(_SEARCH_INDEX))


def run_context(repo: forge.RepositoryId | None) -> session.RunContext:
    """`session.run_context` over the checkout's own `BoardForge`, ruling on
    `RULING_DAY`, searching rulings in `search_index`."""
    return session.RunContext(
        repo,
        build_forge=_forge_of,
        today=lambda: RULING_DAY,
        ruling_search=search_index(),
        board_probe=NoBoardProbe(),
    )


def item_body(*entries: Mapping[str, object], next_step: str | None = None) -> str:
    """An item body whose block carries `entries` as its `[[expectation]]`
    lines, rendered by aco itself, and `next_step` as its `next` when given. A
    ruled option line without a `card_hash` gets the hash of its own card."""
    minimal = tomllib.loads(MINIMAL_BLOCK_TOML)
    data = {
        **minimal,
        "next": minimal["next"] if next_step is None else next_step,
        "expectation": [_with_card_hash(entry) for entry in entries],
    }
    return block_body(body.render_block(data).removesuffix("\n"))


def _with_card_hash(entry: Mapping[str, object]) -> dict[str, object]:
    if "ruling" in entry and "card_hash" not in entry and expectation_grammar.is_option_line(entry):
        return {**entry, "card_hash": expectation_grammar.card_hash(entry)}
    return dict(entry)


@dataclass(frozen=True)
class ReleasedItem:
    """One finished work item's release commit on the state ref: `record` is what its lane left."""

    issue: int
    record: LaneRecord
    released_at: int

    @property
    def message(self) -> str:
        return "\n".join([f"release issue {self.issue}", "", *self.record.trailers()])


def seed_lane_records(repository: BoardForge, releases: Sequence[ReleasedItem]) -> None:
    """Give the checkout a state ref holding exactly `releases`, oldest first, replacing any
    earlier one. The ref lives in a bare repository the checkout's GitHub origin is rewritten
    to for git's own reads, so the board reads it through the real store while the forge
    identity stays the GitHub one; a scratch clone writes it, so the checkout keeps no lineage
    of a ref that is replaced."""
    directory = repository.directory
    bare = directory.parent / f"{directory.name}.state.git"
    scratch = directory.parent / f"{directory.name}.state-writer"
    for stale in (bare, scratch):
        shutil.rmtree(stale, ignore_errors=True)
    real_git(directory.parent, "init", "--bare", "--quiet", str(bare))
    real_git(directory.parent, "init", "--quiet", str(scratch))
    real_git(scratch, "config", "user.name", "Board")
    real_git(scratch, "config", "user.email", "board@example.com")
    real_git(
        directory, "config", f"url.{bare}.insteadOf", f"https://github.com/{repository.repository}"
    )
    tip = str(store.bootstrap(worktree=scratch, remote=str(bare)))
    for release in releases:
        committed = subprocess.run(
            ["git", "commit-tree", f"{tip}^{{tree}}", "-p", tip, "-m", release.message],
            cwd=scratch,
            env=sealed_git_environment() | {"GIT_COMMITTER_DATE": f"@{release.released_at} +0000"},
            check=True,
            capture_output=True,
            text=True,
        )
        tip = committed.stdout.strip()
    real_git(scratch, "push", "--quiet", str(bare), f"{tip}:{store.STATE_REF}", "--force")
