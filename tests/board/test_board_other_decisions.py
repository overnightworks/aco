"""The board answers an option card with the operator's own words (ABRD-09,
ABRD-42, ABRD-63 to ABRD-66): the post's shape and refusals, the exact `aco rule
--other` it runs, and that real `aco rule` accepts and stores that call."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from aco_board_fixtures import BoardClient, FakeAcoRepository, Response, line, row
from cli_fixtures import run_cli
from github_fixtures import assert_github_world
from option_cards import GOLDEN_CARD_HASH, card, item_body, serve_item
from test_board_option_lines import option_line

from aco import body
from aco.board.board import LINE_CHANGED

_BAD_REQUEST = "bad request: decision"
_ANSWER = "Nur auf dem Desktop offen lassen."


def _listed_option_line(board: BoardClient) -> dict[str, Any]:
    [repo] = cast(list[dict[str, Any]], board.get_board_json().json()["repos"])
    return repo["items"][0]["lines"][0]


def _post_other(board: BoardClient, listed: dict[str, Any], **fields: object) -> Response:
    payload = {
        "repo": board.repo,
        "item": 12,
        "line": listed["index"],
        "fingerprint": listed["fingerprint"],
        **fields,
    }
    return board.post_rule(payload)


@pytest.fixture
def listed(repository: FakeAcoRepository, board: BoardClient) -> dict[str, Any]:
    repository.set_rulings(row(12, "Song jump", option_line()))
    return _listed_option_line(board)


def test_an_other_post_rules_the_line_with_the_stripped_answer(
    repository: FakeAcoRepository, board: BoardClient, listed: dict[str, Any]
) -> None:
    """ABRD-63, ABRD-64."""
    answer = _post_other(board, listed, other=f"  {_ANSWER}\n")

    assert answer.json() == {"status": "ruled", "message": None}
    stored = repository.stored_line(12, 1)
    assert (stored["ruling"], stored["other"], stored["via"]) == ("other", _ANSWER, "board")
    assert "note" not in stored


@pytest.mark.parametrize(
    "text", ["-n starts like an option", "two  spaces", "a\nb", 'quote " here', "Ärger ä"]
)
def test_an_other_post_runs_aco_rule_with_the_answer_as_one_argument(
    repository: FakeAcoRepository, board: BoardClient, listed: dict[str, Any], text: str
) -> None:
    """ABRD-64."""
    _post_other(board, listed, other=text)

    assert repository.rule_calls() == [
        [
            "rule",
            "12",
            "--line",
            "1",
            f"--other={text.strip()}",
            "--via",
            "board",
            f"--card-hash={listed_card_hash()}",
            "--json",
        ]
    ]


def listed_card_hash() -> str:
    return cast(str, option_line()["card_hash"])


@pytest.mark.parametrize(
    "fields",
    [
        {"other": ""},
        {"other": "   \n"},
        {"other": 5},
        {"other": ["x"]},
        {"other": "x" * 281},
        {"other": "a\0b"},
        {"other": "\ud800"},
        {"other": "x", "outcome": "yes"},
        {"other": "x", "option": "A"},
        {"other": "x", "note": "n"},
        {"other": "x", "note": ""},
    ],
    ids=lambda fields: ",".join(f"{key}={str(value)[:12]!r}" for key, value in fields.items()),
)
def test_an_other_post_breaking_the_shape_or_the_bound_is_refused_before_any_aco_write(
    repository: FakeAcoRepository,
    board: BoardClient,
    listed: dict[str, Any],
    fields: dict[str, object],
) -> None:
    """ABRD-05, ABRD-42, ABRD-65."""
    answer = _post_other(board, listed, **fields)

    assert (answer.status, answer.json()) == (400, {"error": _BAD_REQUEST})
    assert repository.rule_calls() == []


def test_an_other_of_exactly_the_bound_after_trimming_is_accepted(
    repository: FakeAcoRepository, board: BoardClient, listed: dict[str, Any]
) -> None:
    """ABRD-05, ABRD-65."""
    answer = _post_other(board, listed, other=f" {'x' * 280} ")

    assert answer.json() == {"status": "ruled", "message": None}
    assert repository.stored_line(12, 1)["other"] == "x" * 280


def test_a_null_other_names_nothing_so_the_option_beside_it_decides(
    repository: FakeAcoRepository, board: BoardClient, listed: dict[str, Any]
) -> None:
    """ABRD-42."""
    answer = _post_other(board, listed, other=None, option="A")

    assert answer.json() == {"status": "ruled", "message": None}
    assert repository.stored_line(12, 1)["ruling"] == "A"


def test_an_other_post_after_the_card_changed_is_refused_without_a_write(
    repository: FakeAcoRepository, board: BoardClient, listed: dict[str, Any]
) -> None:
    """ABRD-02, ABRD-64."""
    repository.set_rulings(row(12, "Song jump", option_line(card_hash="sha256:other")))

    answer = _post_other(board, listed, other=_ANSWER)

    assert answer.json() == {"status": "failed", "message": LINE_CHANGED}
    assert repository.rule_calls() == []


@pytest.mark.parametrize("index", [1, 9], ids=["yes-no-line", "missing-line"])
def test_an_other_post_for_no_option_line_is_refused_as_changed(
    repository: FakeAcoRepository, board: BoardClient, index: int
) -> None:
    """ABRD-40, ABRD-64."""
    repository.set_rulings(row(12, "Song jump", line(1, "Guests?", default="yes")))
    [repo] = cast(list[dict[str, Any]], board.get_board_json().json()["repos"])
    yes_no = repo["items"][0]["lines"][0]

    answer = board.post_rule(
        {
            "repo": board.repo,
            "item": 12,
            "line": index,
            "fingerprint": yes_no["fingerprint"],
            "other": _ANSWER,
        }
    )

    assert answer.json() == {"status": "failed", "message": LINE_CHANGED}
    assert repository.rule_calls() == []


@pytest.fixture
def github_world(github_clone: Path, bare_remote: Path) -> None:
    assert_github_world(github_clone, bare_remote)


@pytest.mark.usefixtures("github_world")
@pytest.mark.parametrize("text", ["-n first", "a\nb", 'say "hi" ä'])
def test_the_real_aco_rule_stores_what_the_board_sent(
    repository: FakeAcoRepository,
    board: BoardClient,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    text: str,
) -> None:
    """ABRD-64, RULE-15, RULE-21: the board's argv is lawful for the real command."""
    repository.set_rulings(
        row(7, "Karte", option_line(index=2, card_hash=GOLDEN_CARD_HASH, topic="Sprung"))
    )
    [repo] = cast(list[dict[str, Any]], board.get_board_json().json()["repos"])
    shown = repo["items"][0]["lines"][0]
    board.post_rule(
        {
            "repo": board.repo,
            "item": 7,
            "line": 2,
            "fingerprint": shown["fingerprint"],
            "other": f" {text} ",
        }
    )
    [sent] = repository.rule_calls()
    forge = serve_item(monkeypatch, item_body(card()))

    ruled = run_cli(sent, capsys)

    assert ruled.status == 0
    entry = body.block_expectation_dicts(body.locate_block(forge.item_bodies[7]).data)[1]
    assert (entry["ruling"], entry["other"], entry["via"]) == ("other", text, "board")
    assert "note" not in entry
