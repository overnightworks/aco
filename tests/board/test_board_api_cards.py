"""The board's JSON API deciding option cards through the real server, wire form and
`aco` adapter against a fake `aco` on PATH (specs/serve.spec.md): reading fresh on every
listing, keeping no copy of a decision, the repos a card is written to, and what a broken,
missing or hung `aco` does to a card post."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest
from aco_board_fixtures import (
    BoardClient,
    FakeAcoRepository,
    Lister,
    first_listed_line,
    option_line,
    row,
    serving,
    serving_two,
)

from aco.board.aco_cli import AcoCli
from aco.board.board import LINE_CHANGED

_ITEM = 42


def _rule_call(item: int, index: int, letter: str) -> list[str]:
    card_hash = option_line()["card_hash"]
    return [
        "rule",
        str(item),
        "--line",
        str(index),
        "--option",
        letter,
        f"--card-hash={card_hash}",
        "--via",
        "board",
        "--json",
    ]


@pytest.mark.parametrize(
    ("rows", "listed"),
    [
        ((), []),
        (
            (
                row(
                    42,
                    "Share page",
                    option_line(index=1),
                    option_line(index=2, ruling="A"),
                ),
                row(7, "Login", option_line()),
            ),
            [(42, "Share page", [(1, None), (2, "A")]), (7, "Login", [(1, None)])],
        ),
    ],
    ids=["nothing", "open-and-ruled-in-acos-order"],
)
def test_the_board_lists_every_option_line_under_its_item_in_acos_order(
    repository: FakeAcoRepository,
    board: BoardClient,
    rows: tuple[dict[str, object], ...],
    listed: list[tuple[int, str, list[tuple[int, str | None]]]],
    listed_items: Lister,
) -> None:
    repository.set_rulings(*rows)

    items = listed_items(board)

    assert [
        (
            item["number"],
            item["title"],
            [(entry["index"], entry["ruling"]) for entry in item["lines"]],
        )
        for item in items
    ] == listed
    assert repository.rule_calls() == []


def test_the_board_reads_fresh_on_every_listing(
    repository: FakeAcoRepository,
    board: BoardClient,
    listed_items: Lister,
) -> None:
    for item, index in [(1, 1), (2, 4)]:
        repository.set_rulings(row(item, "Changed between loads", option_line(index=index)))

        [listed_item] = listed_items(board)
        [listed_line] = listed_item["lines"]
        assert (listed_item["number"], listed_line["index"]) == (item, index)


def test_the_board_keeps_no_copy_of_a_decision(
    repository: FakeAcoRepository,
    board: BoardClient,
    listed_items: Lister,
) -> None:
    repository.set_rulings(row(_ITEM, "Share page", option_line()))
    board.decide_card_through_api(_ITEM, [first_listed_line(board)], ["A"])

    repository.set_rulings(row(_ITEM, "Share page", option_line()))

    assert [item["number"] for item in listed_items(board)] == [_ITEM]


def test_card_posts_on_two_items_at_once_are_both_stored_one_at_a_time(
    repository: FakeAcoRepository,
    board: BoardClient,
    listed_items: Lister,
) -> None:
    """ABRD-03, ABRD-17."""
    repository.set_rulings(row(_ITEM, "Share page", option_line()), row(7, "Login", option_line()))
    items = listed_items(board)
    # Each `aco rule` waits between reading and rewriting the listing, so two
    # unserialized writes would overlap and the later one would drop the first.
    repository.delay("rule", 0.3)

    with ThreadPoolExecutor(max_workers=2) as clicks:
        answers = list(
            clicks.map(
                lambda item: board.decide_card_through_api(item["number"], item["lines"], ["A"]),
                items,
            )
        )

    assert [answer.json()["status"] for answer in answers] == ["ruled", "ruled"]
    assert [repository.stored_line(item, 1)["ruling"] for item in (_ITEM, 7)] == ["A", "A"]


def _aco_missing_from_path(
    repository: FakeAcoRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del repository
    monkeypatch.setenv("PATH", str(tmp_path / "no-aco-here"))


def _aco_rulings_unreadable(
    repository: FakeAcoRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del tmp_path, monkeypatch
    repository.fail_rulings("ERROR: no forge adapter for host")


@pytest.mark.parametrize(
    ("arrange", "message"),
    [
        (_aco_missing_from_path, "aco is not installed on PATH"),
        (_aco_rulings_unreadable, "aco rulings failed: ERROR: no forge adapter for host"),
    ],
    ids=["aco-missing-from-path", "aco-rulings-unreadable"],
)
def test_a_broken_aco_during_a_card_post_keeps_the_line_undecided(
    repository: FakeAcoRepository,
    board: BoardClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arrange: Callable[[FakeAcoRepository, Path, pytest.MonkeyPatch], None],
    message: str,
) -> None:
    repository.set_rulings(row(_ITEM, "Share page", option_line()))
    shown = first_listed_line(board)
    arrange(repository, tmp_path, monkeypatch)

    answer = board.decide_card_through_api(_ITEM, [shown], ["A"])

    assert answer.json() == {"status": "failed", "message": message}
    assert repository.rule_calls() == []


def test_a_hung_aco_rule_keeps_the_line_undecided(
    repository: FakeAcoRepository, listed_items: Lister
) -> None:
    repository.set_rulings(row(_ITEM, "Share page", option_line()))
    repository.delay("rule", 30)

    with serving(AcoCli(directory=repository.directory, timeout_seconds=5)) as board:
        answer = board.decide_card_through_api(_ITEM, [first_listed_line(board)], ["A"])
        numbers_after = [item["number"] for item in listed_items(board)]

    assert answer.json() == {
        "status": "failed",
        "message": "aco rule did not answer within 5 seconds",
    }
    assert numbers_after == [_ITEM]


@pytest.mark.parametrize(
    ("target_repo", "expected_status", "expected_message"),
    [("a", "ruled", None), ("b", "failed", LINE_CHANGED)],
    ids=["its-own-repo", "a-different-repo-with-an-identical-card"],
)
def test_a_card_only_writes_the_repo_its_fingerprint_was_read_from(
    two_repositories: tuple[FakeAcoRepository, FakeAcoRepository],
    target_repo: str,
    expected_status: str,
    expected_message: str | None,
) -> None:
    """ABRD-16/21: a card decided against its own repo writes there; posted
    against another configured repo instead -- even one holding an identical
    card -- it is refused like a changed line, no write in either repo."""
    repository_a, repository_b = two_repositories
    identical_card = row(_ITEM, "Share page", option_line())
    repository_a.set_rulings(identical_card)
    repository_b.set_rulings(identical_card)

    with serving_two(two_repositories) as board:
        [listed_repo_a, _] = cast(list[dict[str, Any]], board.get_board_json().json()["repos"])
        listed_in_a = listed_repo_a["items"][0]["lines"][0]

        answer = board.decide_card_through_api(_ITEM, [listed_in_a], ["A"], repo=target_repo)

    assert answer.json() == {"status": expected_status, "message": expected_message}
    assert repository_a.rule_calls() == ([_rule_call(_ITEM, 1, "A")] if target_repo == "a" else [])
    assert repository_b.rule_calls() == []
