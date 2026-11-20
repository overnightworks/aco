"""`aco next` lists an item whose open option lines all wait on the operator apart
from its actions (NEXT-70), as it lists an item with an operator `wait`."""

import json

import pytest
from board_fixtures import board_issue, complete_contract
from cli_fixtures import freeze_cli_now, run_cli
from github_fixtures import FakeForge, serve_forge
from option_cards import card, item_body, returned_today

from aco import workboard

FREE_ITEM = 8
WAITING_LINE = "waiting on operator: #7"


def serve_board(monkeypatch: pytest.MonkeyPatch, *issues: workboard.Issue) -> None:
    freeze_cli_now(monkeypatch)
    serve_forge(monkeypatch, FakeForge(board_issues=issues))


def free_item() -> workboard.Issue:
    return board_issue(FREE_ITEM, "Frei", complete_contract(f"Claim #{FREE_ITEM}."))


@pytest.mark.usefixtures("github_world")
class TestNextWithOpenCards:
    def test_an_item_with_only_open_unreturned_lines_stands_under_waiting_on_operator(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-70 -- a free item comes first, the card item waits on the operator."""
        serve_board(monkeypatch, board_issue(7, "Karte", item_body(card())), free_item())

        lines = run_cli(["next"], capsys).stdout.splitlines()

        assert (lines[0].startswith(f"#{FREE_ITEM} "), WAITING_LINE in lines) == (True, True)

    def test_the_card_item_alone_names_no_action(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-70 -- --json carries the item as waiting and names no first action."""
        serve_board(monkeypatch, board_issue(7, "Karte", item_body(card())))

        payload = json.loads(run_cli(["next", "--json"], capsys).stdout)

        assert (payload["reason"], payload["waiting_on_operator"]) == ("nothing_actionable", [7])

    def test_an_item_with_a_returned_line_stays_with_the_head(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-45, NEXT-70 -- a returned line keeps the item off the operator's list."""
        serve_board(monkeypatch, board_issue(7, "Karte", item_body(returned_today())))

        payload = json.loads(run_cli(["next", "--json"], capsys).stdout)

        assert (payload["number"], payload["waiting_on_operator"]) == (7, [])
