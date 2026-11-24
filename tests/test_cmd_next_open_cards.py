"""`aco next` lists an item whose open option lines all wait on the operator apart
from its actions (NEXT-70), as it lists an item with an operator `wait`, and never
cuts such a container (E-NEXT-24)."""

import json

import pytest
from board_fixtures import (
    OPERATOR_WAIT,
    board_issue,
    complete_contract,
    container_with_children,
    ruled_expectation,
    slice_entries,
)
from cli_fixtures import freeze_cli_now, run_cli
from github_fixtures import FakeForge, serve_forge
from option_cards import card, item_body, open_option_entry, returned_option_entry, returned_today

from aco import workboard

FREE_ITEM = 8
WAITING_LINE = "waiting on operator: #7"


def serve_board(monkeypatch: pytest.MonkeyPatch, *issues: workboard.Issue) -> None:
    freeze_cli_now(monkeypatch)
    serve_forge(monkeypatch, FakeForge(board_issues=issues))


def free_item() -> workboard.Issue:
    return board_issue(FREE_ITEM, "Frei", complete_contract(f"Claim #{FREE_ITEM}."))


def serve_container_with_open_card_and_free_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """Container `#7`: no open child, one uncut row, one open option line; beside `free_item`."""
    container, children = container_with_children(
        7,
        closed=1,
        body=complete_contract(
            "Cut A.", slice=slice_entries("Scheibe A"), expectation=[open_option_entry()]
        ),
    )
    freeze_cli_now(monkeypatch)
    serve_forge(
        monkeypatch,
        FakeForge(board_issues=(container, free_item()), children={7: children}),
    )


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

    def test_text_cuts_no_container_that_waits_on_its_card(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-70 -- the free item comes first, the container waits. Example: E-NEXT-24."""
        serve_container_with_open_card_and_free_item(monkeypatch)

        lines = run_cli(["next"], capsys).stdout.splitlines()

        assert (lines[0].startswith(f"#{FREE_ITEM} "), WAITING_LINE in lines) == (True, True)

    def test_json_cuts_no_container_that_waits_on_its_card(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-70 -- --json names the free item, not a cut. Example: E-NEXT-24."""
        serve_container_with_open_card_and_free_item(monkeypatch)

        payload = json.loads(run_cli(["next", "--json"], capsys).stdout)

        assert (payload["number"], payload["waiting_on_operator"]) == (FREE_ITEM, [7])


def serve_childless_container(monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    """Container `#7` with `body`: every child closed, no uncut row."""
    container, children = container_with_children(7, closed=2, body=body)
    freeze_cli_now(monkeypatch)
    serve_forge(monkeypatch, FakeForge(board_issues=(container,), children={7: children}))


@pytest.mark.usefixtures("github_world")
class TestNextWithAHeldContainer:
    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            pytest.param(
                complete_contract("keiner", expectation=[open_option_entry()]),
                ([], [7]),
                id="open-card",
            ),
            pytest.param(
                complete_contract("keiner", wait=OPERATOR_WAIT), ([], [7]), id="operator-wait"
            ),
            pytest.param(
                complete_contract("keiner", expectation=[ruled_expectation("Alt")]),
                ([7], []),
                id="ruled-line",
            ),
        ],
    )
    def test_a_closed_out_container_is_closable_unless_a_card_or_wait_holds_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        body: str,
        expected: tuple[list[int], list[int]],
    ) -> None:
        """Spec: NEXT-73, NEXT-07, NEXT-18, NEXT-39, NEXT-70"""
        serve_childless_container(monkeypatch, body)

        payload = json.loads(run_cli(["next", "--json"], capsys).stdout)

        assert expected == (payload["close"], payload["waiting_on_operator"])

    def test_a_closed_out_container_with_a_returned_line_stays_with_the_head(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-73, NEXT-45, NEXT-18"""
        serve_childless_container(
            monkeypatch, complete_contract("keiner", expectation=[returned_option_entry()])
        )

        text = run_cli(["next"], capsys).stdout

        assert text.splitlines() == [
            "No actionable item.",
            "parallel: none",
            "scope unknown: none",
            "close: none",
            "with head: #7 line 1",
            "",
            "SKIPPED",
            "#7: held by an option line sent back to its head",
        ]
