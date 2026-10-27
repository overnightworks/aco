"""`aco next` names the open option lines an operator sent back to their head
(NEXT-45, NEXT-46)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from board_fixtures import board_issue
from cli_fixtures import freeze_cli_now, run_cli
from github_fixtures import FakeForge, assert_github_world, serve_forge
from test_option_lines import RETURNED_ON, card_body
from test_rule_option import item_body, returned_today

from aco import workboard

NOT_RETURNED_LINE = '[[expectation]]\ntext = "T"\ndefault = "yes"\n'


@pytest.fixture
def github_world(github_clone: Path, bare_remote: Path) -> None:
    assert_github_world(github_clone, bare_remote)


def serve_board(monkeypatch: pytest.MonkeyPatch, *issues: workboard.Issue) -> None:
    freeze_cli_now(monkeypatch)
    serve_forge(monkeypatch, FakeForge(board_issues=issues))


@pytest.mark.usefixtures(github_world.__name__)
class TestNextWithHead:
    def test_a_returned_line_is_named_after_waiting_on_operator(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-45 -- the item and the line index, in text."""
        serve_board(
            monkeypatch,
            board_issue(7, "Karte", item_body(returned_today())),
            board_issue(8, "Wartet", item_body(returned_today()), labels=("needs-operator",)),
        )

        lines = run_cli(["next"], capsys).stdout.splitlines()

        assert (
            lines[lines.index("waiting on operator: #8") + 1] == "with head: #7 line 2, #8 line 2"
        )

    def test_json_carries_each_item_with_its_returned_line_indexes(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-46 -- `with_head` is `{number, lines}` per item."""
        serve_board(monkeypatch, board_issue(7, "Karte", item_body(returned_today())))

        payload = json.loads(run_cli(["next", "--json"], capsys).stdout)

        assert payload["with_head"] == [{"number": 7, "lines": [2]}]

    def test_no_returned_line_prints_no_text_line_and_an_empty_json_array(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-45, NEXT-46 -- an open line that was never sent back is not with its head."""
        serve_board(monkeypatch, board_issue(7, "Karte", card_body(NOT_RETURNED_LINE)))

        text = run_cli(["next"], capsys).stdout
        payload = json.loads(run_cli(["next", "--json"], capsys).stdout)

        assert "with head" not in text
        assert payload["with_head"] == []

    def test_a_malformed_item_is_named_only_under_skipped(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-45 -- a body that does not read has no addressable line."""
        serve_board(
            monkeypatch,
            board_issue(7, "Karte", card_body(NOT_RETURNED_LINE + RETURNED_ON)),
        )

        text = run_cli(["next"], capsys).stdout
        payload = json.loads(run_cli(["next", "--json"], capsys).stdout)

        assert "with head" not in text
        assert [skipped["number"] for skipped in payload["skipped"]] == [7]
        assert payload["with_head"] == []
