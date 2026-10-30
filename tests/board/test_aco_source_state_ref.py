"""The board's aco source over a real `storage = "state-ref"` checkout and a
bare `file://` remote (specs/serve.spec.md, ABRD-02, ABRD-06, ABRD-03,
ABRD-78, ABRD-80): every read and write builds its own context, so a decision
reads the state ref afresh, and a write after a stale read refuses with
CAS-20 and loses nothing."""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from aco_board_fixtures import BoardClient, Lister, serving
from board_fixtures import MINIMAL_BLOCK_TOML, block_body, write_repository_config
from cli_fixtures import real_git, run_cli, set_git_identity, stub_board_config_tracked
from option_cards import open_option_entry
from store_fixtures import item_record, path_without_gh, push_item_tree

from aco import body, cli, decide, expectation_grammar, items, protocol, session, store
from aco.board.aco_source import AcoSource
from aco.board.board import LINE_CHANGED

_REAL_RUN_CONTEXT = session.run_context
"""Taken before the board conftest's seam replaces it with the test forge."""
_FIRST_ID, _SECOND_ID = "aco-000001", "aco-000002"
_FIRST, _SECOND = items.item_number(_FIRST_ID), items.item_number(_SECOND_ID)
_QUESTION = "Bleibt der Song offen?"


def _two_open_lines() -> tuple[dict[str, object], ...]:
    return (open_option_entry(), open_option_entry(_QUESTION))


def _item_file(*entries: dict[str, object], title: str = "Karte") -> bytes:
    """A state-ref item body: `entries` as its lines and its `[record]` table."""
    data = {
        **tomllib.loads(MINIMAL_BLOCK_TOML),
        "expectation": list(entries),
        "record": item_record(title=title, state="open", kind="task"),
    }
    return block_body(body.render_block(data).removesuffix("\n")).encode()


@dataclass(frozen=True)
class _StateRefCheckout:
    worktree: Path
    remote: Path

    def seed(self, item_files: dict[str, bytes]) -> None:
        """The state ref holds exactly `item_files`; only before anything read it."""
        push_item_tree(self.remote, self.worktree, item_files)

    def tip(self) -> protocol.ObjectId | None:
        return store.fetch_state(worktree=self.worktree, remote=f"file://{self.remote}").tip

    def commits(self) -> int:
        """How many commits the state ref's history holds."""
        count = real_git(self.remote, "rev-list", "--count", store.STATE_REF).stdout
        return int(count)

    def entries(self, item_id: str) -> list[dict[str, object]]:
        tip = self.tip()
        assert tip is not None
        stored = store.read_item_files(self.worktree, tip)[f"{item_id}.md"].decode()
        return body.block_expectation_dicts(body.locate_block(stored).data)


@pytest.fixture(autouse=True)
def commit_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    set_git_identity(monkeypatch)


@pytest.fixture
def checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bare_remote: Path, worktree: Path
) -> _StateRefCheckout:
    """A checkout pinned to `storage = "state-ref"` whose `origin` is
    `bare_remote`, read by aco's real context builder with no `gh` on `PATH`."""
    push_item_tree(bare_remote, worktree, {f"{_FIRST_ID}.md": _item_file(*_two_open_lines())})
    real_git(worktree, "remote", "add", "origin", f"file://{bare_remote}")
    real_git(worktree, "push", "origin", "main")
    real_git(worktree, "remote", "set-head", "origin", "main")
    write_repository_config(worktree, 'storage = "state-ref"\ncanonical_remote = "origin"\n')
    stub_board_config_tracked(monkeypatch)
    monkeypatch.setenv("PATH", path_without_gh(tmp_path))
    monkeypatch.setattr(session, "run_context", _REAL_RUN_CONTEXT)
    monkeypatch.chdir(worktree)
    return _StateRefCheckout(worktree, bare_remote)


@pytest.fixture
def state_ref_board(checkout: _StateRefCheckout) -> Iterator[BoardClient]:
    with serving(AcoSource(directory=checkout.worktree)) as client:
        yield client


def _first_card(board: BoardClient, listed_items: Lister) -> list[dict[str, Any]]:
    [item] = [item for item in listed_items(board) if item["number"] == _FIRST]
    return item["lines"]


def _stored_hash(entry: dict[str, object]) -> str:
    return expectation_grammar.card_hash(entry)


def _chat_ruling() -> list[str]:
    """A head rules line 2 of the first item `A` through `aco rule --via chat`."""
    shown = _stored_hash(_two_open_lines()[1])
    return [
        "rule",
        _FIRST_ID,
        "--line",
        "2",
        "--option",
        "A",
        "--via",
        "chat",
        f"--card-hash={shown}",
    ]


def test_items_with_a_record_are_listed_in_the_rulings_order(
    checkout: _StateRefCheckout, state_ref_board: BoardClient, listed_items: Lister
) -> None:
    """ABRD-06, RUL-03: the item asked on the newer day comes first, whatever its number."""
    newer = {**open_option_entry(), "asked_on": date(2026, 10, 29)}
    checkout.seed(
        {f"{_FIRST_ID}.md": _item_file(newer), f"{_SECOND_ID}.md": _item_file(open_option_entry())}
    )

    assert [item["number"] for item in listed_items(state_ref_board)] == [_FIRST, _SECOND]


@pytest.mark.parametrize(
    ("answer", "options", "stored"),
    [
        ({}, ["A", "B"], [("A", "board", True), ("B", "board", True)]),
        ({"other": "Nur am Desktop."}, None, [("other", "board", True)] * 2),
        ({"unclear": True}, None, [(None, None, False)] * 2),
    ],
    ids=["picks", "other", "unclear"],
)
def test_a_decision_is_stored_with_via_board_and_the_card_hash_it_read(
    checkout: _StateRefCheckout,
    state_ref_board: BoardClient,
    listed_items: Lister,
    answer: dict[str, object],
    options: list[str] | None,
    stored: list[tuple[object, ...]],
) -> None:
    """ABRD-78: one state-ref commit; picks and Other store `via board` and
    the fresh read's card hash, an Unclear stores neither."""
    commits = checkout.commits()

    state_ref_board.decide_card_through_api(
        _FIRST, _first_card(state_ref_board, listed_items), options, answer
    )

    entries = checkout.entries(_FIRST_ID)
    assert [
        (entry.get("ruling"), entry.get("via"), entry.get("card_hash") == _stored_hash(shown))
        for entry, shown in zip(entries, _two_open_lines(), strict=True)
    ] == stored
    assert checkout.commits() == commits + 1


def _card_edited(capsys: pytest.CaptureFixture[str]) -> None:
    """The head rewrites line 1's question through `aco item edit`."""
    edited = _item_file(
        {**open_option_entry(), "question": "Anders gefragt?"}, _two_open_lines()[1]
    )
    assert run_cli(["item", "edit", _FIRST_ID], capsys, stdin=edited).status == 0


def _line_ruled_in_chat(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_cli(_chat_ruling(), capsys).status == 0


def _line_withdrawn(capsys: pytest.CaptureFixture[str]) -> None:
    """The head takes line 1 back through `aco withdraw` (BODY-104, ABRD-60)."""
    assert run_cli(["withdraw", _FIRST_ID, "--line", "1"], capsys).status == 0


@pytest.mark.parametrize(
    ("change", "status", "message"),
    [
        (_card_edited, "failed", LINE_CHANGED),
        (_line_withdrawn, "failed", LINE_CHANGED),
        (
            _line_ruled_in_chat,
            "already_ruled",
            "line 2 is already ruled; a changed ruling is a new line",
        ),
    ],
    ids=["card-changed", "line-withdrawn", "line-ruled-in-chat"],
)
def test_a_card_changed_on_the_state_ref_since_the_page_read_writes_nothing(
    checkout: _StateRefCheckout,
    state_ref_board: BoardClient,
    listed_items: Lister,
    change: Callable[[pytest.CaptureFixture[str]], None],
    status: str,
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ABRD-02, ABRD-80: refused on the item's fresh read; the state ref is unchanged."""
    shown = _first_card(state_ref_board, listed_items)
    change(capsys)
    tip = checkout.tip()

    answered = state_ref_board.decide_card_through_api(_FIRST, shown, ["A", "B"])

    assert answered.json() == {"status": status, "message": message}
    assert checkout.tip() == tip


def test_after_a_withdrawal_a_fresh_read_lists_the_rest_of_the_card_and_it_posts(
    checkout: _StateRefCheckout,
    state_ref_board: BoardClient,
    listed_items: Lister,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ABRD-60, ABRD-78: the withdrawn line is not listed, the survivor keeps
    its index, and the remaining card is stored in one state-ref commit."""
    _line_withdrawn(capsys)
    shown = _first_card(state_ref_board, listed_items)
    commits = checkout.commits()

    answered = state_ref_board.decide_card_through_api(_FIRST, shown, ["B"])

    assert [(line["index"], line["text"]) for line in shown] == [(2, _QUESTION)]
    assert answered.json() == {"status": "ruled", "message": None}
    assert [entry.get("ruling") for entry in checkout.entries(_FIRST_ID)] == [None, "B"]
    assert checkout.commits() == commits + 1


def test_a_write_after_a_stale_read_refuses_and_keeps_the_other_writers_ruling(
    checkout: _StateRefCheckout,
    state_ref_board: BoardClient,
    listed_items: Lister,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CAS-20: a chat ruling lands after the board read the item and before it
    writes; the board's write is refused and the chat ruling stays."""
    shown = _first_card(state_ref_board, listed_items)
    read = decide.fresh_item

    def read_then_ruled_in_chat(
        context: session.RunContext, number: int, *, command: str
    ) -> decide.FreshItem:
        fresh = read(context, number, command=command)
        monkeypatch.setattr(decide, "fresh_item", read)
        assert cli.main(_chat_ruling()) == 0
        return fresh

    monkeypatch.setattr(decide, "fresh_item", read_then_ruled_in_chat)

    answered = state_ref_board.decide_card_through_api(_FIRST, shown, ["B", "B"])

    assert answered.json()["status"] == "failed"
    assert "written since it was read" in str(answered.json()["message"])
    entries = checkout.entries(_FIRST_ID)
    assert [(entry.get("ruling"), entry.get("via")) for entry in entries] == [
        (None, None),
        ("A", "chat"),
    ]


def test_two_decisions_on_two_items_back_to_back_are_both_stored(
    checkout: _StateRefCheckout, state_ref_board: BoardClient, listed_items: Lister
) -> None:
    """ABRD-03, ABRD-17: a fresh context per write, so the second write
    starts from the first one's commit."""
    one_line = _item_file(open_option_entry())
    checkout.seed({f"{_FIRST_ID}.md": one_line, f"{_SECOND_ID}.md": one_line})
    listed = {item["number"]: item["lines"] for item in listed_items(state_ref_board)}
    commits = checkout.commits()

    answers = [
        state_ref_board.decide_card_through_api(number, listed[number], ["A"]).json()["status"]
        for number in (_FIRST, _SECOND)
    ]

    assert answers == ["ruled", "ruled"]
    assert [checkout.entries(item_id)[0]["ruling"] for item_id in (_FIRST_ID, _SECOND_ID)] == [
        "A",
        "A",
    ]
    assert checkout.commits() == commits + 2


def test_two_decisions_on_one_item_at_once_store_it_once(
    checkout: _StateRefCheckout, state_ref_board: BoardClient, listed_items: Lister
) -> None:
    """ABRD-03, ABRD-80."""
    shown = _first_card(state_ref_board, listed_items)
    commits = checkout.commits()

    with ThreadPoolExecutor(max_workers=2) as threads:
        posts = [
            threads.submit(state_ref_board.decide_card_through_api, _FIRST, shown, ["A", "B"])
            for _ in range(2)
        ]
        statuses = sorted(str(post.result().json()["status"]) for post in posts)

    assert statuses == ["already_ruled", "ruled"]
    assert checkout.commits() == commits + 1
