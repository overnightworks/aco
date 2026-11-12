"""`aco mcp`'s ask answer shows the earlier rulings of the card's area
(`specs/mcp.spec.md`) through `cli.main(["mcp"])` over the board's test forge."""

import io
import json
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import board_forge
import pytest
from aco_board_fixtures import board_checkout
from discovery_fixtures import configure_root, isolate_config_file, repository_with_card
from mcp_lines import Script, call_line
from option_cards import ask_card, open_option_entry

from aco import cli, forge, session


@pytest.fixture(autouse=True)
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return isolate_config_file(tmp_path, monkeypatch)


@pytest.fixture
def root(tmp_path: Path, config_file: Path) -> Path:
    return configure_root(tmp_path, config_file)


@pytest.fixture(autouse=True)
def _empty_global_git_config(isolated_global_git_config: Path) -> None:
    """Real git reads an empty global configuration."""


@pytest.fixture
def here(root: Path) -> board_forge.BoardForge:
    return repository_with_card(root / "here", 1, "Here")


def _ask_line(request_id: int) -> str:
    card = ask_card(question="Soll der Take danach markiert bleiben?")
    return call_line(request_id, "ask", {"repository": "board-forge/here", "item": 1, **card})


def _serve(monkeypatch: pytest.MonkeyPatch, *lines: str) -> list[dict[str, Any]]:
    """Every answer line `aco mcp` writes."""
    replies = io.StringIO()
    with monkeypatch.context() as served:
        served.setattr(session, "run_context", board_forge.run_context)
        served.setattr(sys, "stdin", Script(*lines))
        served.setattr(sys, "stdout", replies)
        assert cli.main(["mcp"]) == 0
    return [json.loads(line) for line in replies.getvalue().splitlines()]


def _ruled_entry(**changes: object) -> dict[str, object]:
    ruled = {"ruling": "A", "ruled_on": date(2026, 10, 28), "via": "board"}
    return {**open_option_entry(), **ruled, **changes}


def _earlier(answer: dict[str, Any]) -> list[tuple[object, ...]]:
    return [
        (line["repository"], line["item"], line["answer"], line["ruled_on"], line["via"])
        for line in answer["result"]["structuredContent"]["earlier"]
    ]


def test_a_ruled_line_of_the_same_area_from_another_repository_and_a_closed_item_is_shown(
    here: board_forge.BoardForge, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: MCP-57, MCP-58."""
    elsewhere = repository_with_card(root / "elsewhere", 2, "Elsewhere")
    ruled_there = _ruled_entry(ruled_on=date(2026, 10, 29), via="chat")
    elsewhere.put_item(3, board_forge.item_body(ruled_there), title="Dort")
    here.put_item(4, board_forge.item_body(_ruled_entry()), title="Zu")
    here.close_item(4)
    index = board_forge.search_index()
    index.include(here, elsewhere)

    [answer] = _serve(monkeypatch, _ask_line(1))

    structured = answer["result"]["structuredContent"]
    assert (answer["result"]["isError"], structured["written"]) == (False, True)
    [query] = index.queries()
    assert '"area song seite"' in query
    assert query.count("user:board-forge") == 1
    assert _earlier(answer) == [
        ("board-forge/elsewhere", 3, "Song bleibt offen", "2026-10-29", "chat"),
        ("board-forge/here", 4, "Song bleibt offen", "2026-10-28", "board"),
    ]
    assert (structured["earlier"][0]["title"], structured["earlier_more"]) == ("Dort", 0)


def test_an_area_without_a_ruling_shows_no_earlier_line(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: MCP-59."""
    here.put_item(4, board_forge.item_body(_ruled_entry(area="Andere")), title="Anders")
    board_forge.search_index().include(here)

    [answer] = _serve(monkeypatch, _ask_line(1))

    structured = answer["result"]["structuredContent"]
    assert (structured["earlier"], structured["earlier_more"]) == ([], 0)


def _non_members_item(root: Path, outside: Path) -> board_forge.BoardForge:
    elsewhere = repository_with_card(root / "elsewhere", 2, "Elsewhere")
    elsewhere.put_item(3, board_forge.item_body(_ruled_entry()), author_is_member=False)
    return elsewhere


def _untracked_repository(root: Path, outside: Path) -> board_forge.BoardForge:
    stranger = board_checkout(outside / "stranger")
    stranger.put_item(3, board_forge.item_body(_ruled_entry()), title="Fremd")
    return stranger


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(_non_members_item, id="non-members-item"),
        pytest.param(_untracked_repository, id="untracked-repository"),
    ],
)
def test_a_ruled_line_of_a_non_member_or_of_an_untracked_repository_is_left_out(
    arrange: Callable[[Path, Path], board_forge.BoardForge],
    here: board_forge.BoardForge,
    root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec: MCP-60."""
    board_forge.search_index().include(arrange(root, tmp_path / "outside"))

    [answer] = _serve(monkeypatch, _ask_line(1))

    assert _earlier(answer) == []


def test_the_asked_line_itself_is_left_out_when_the_same_card_stands_ruled(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: MCP-60."""
    here = board_checkout(root / "here")
    here.put_item(1, board_forge.item_body(_ruled_entry()), title="Here")
    board_forge.search_index().include(here)
    same_card = call_line(1, "ask", {"repository": "board-forge/here", "item": 1, **ask_card()})

    [answer] = _serve(monkeypatch, same_card)

    structured = answer["result"]["structuredContent"]
    assert (structured["written"], structured["line"]["ruling"], _earlier(answer)) == (
        False,
        "A",
        [],
    )


def test_the_same_card_asked_again_shows_the_same_earlier_lines(
    here: board_forge.BoardForge, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: MCP-61."""
    elsewhere = repository_with_card(root / "elsewhere", 2, "Elsewhere")
    elsewhere.put_item(3, board_forge.item_body(_ruled_entry()), title="Dort")
    board_forge.search_index().include(elsewhere)

    [asked, again] = _serve(monkeypatch, _ask_line(1), _ask_line(2))

    assert asked["result"]["structuredContent"]["written"] is True
    assert again["result"]["structuredContent"]["written"] is False
    assert _earlier(again) == _earlier(asked) != []


def _fail_search(index: board_forge.SearchIndex) -> None:
    index.fail("the forge is down")


def _incomplete_search(index: board_forge.SearchIndex) -> None:
    index.mark_incomplete()


def _nothing_to_set_up(index: board_forge.SearchIndex) -> None:
    """The search itself works; the area is what it cannot search."""


@pytest.mark.parametrize(
    ("arrange", "area", "sentence"),
    [
        pytest.param(_fail_search, "Song-Seite", "the forge is down", id="forge-error"),
        pytest.param(_incomplete_search, "Song-Seite", "incomplete", id="incomplete"),
        pytest.param(_nothing_to_set_up, "???", "no letter or digit", id="no-searchable-word"),
    ],
)
def test_a_search_that_cannot_answer_leaves_the_card_written_and_says_why(
    arrange: Callable[[board_forge.SearchIndex], None],
    area: str,
    sentence: str,
    here: board_forge.BoardForge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec: MCP-62, MCP-65."""
    index = board_forge.search_index()
    index.include(here)
    arrange(index)
    card = ask_card(area=area, question="Soll der Take danach markiert bleiben?")
    asked = call_line(1, "ask", {"repository": "board-forge/here", "item": 1, **card})

    [answer] = _serve(monkeypatch, asked)

    result = answer["result"]
    structured = result["structuredContent"]
    assert (result["isError"], structured["written"], here.body_writes()) == (False, True, [1])
    assert sentence in structured["earlier_unavailable"]
    assert "earlier" not in structured
    assert "earlier_more" not in structured


def test_the_search_runs_after_the_items_lock_is_released(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Spec: MCP-63."""
    board_forge.search_index().include(here)
    lock_held_at_searches: list[bool] = []
    search = board_forge.SearchIndex.search

    def witnessed(self: board_forge.SearchIndex, query: str) -> forge.RulingSearchResult:
        lock_held_at_searches.append(board_forge.item_lock_is_held(tmp_path))
        return search(self, query)

    monkeypatch.setattr(board_forge.SearchIndex, "search", witnessed)

    _serve(monkeypatch, _ask_line(1))

    assert lock_held_at_searches == [False]
