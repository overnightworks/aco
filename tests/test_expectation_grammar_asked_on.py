"""The day an option line was asked (BODY-101..103, RUL-19): required while
the line is open or returned, a TOML local date, outside the card hash, read by
`rulings`, and kept when `rule` rewrites the body."""

from __future__ import annotations

import json
import tomllib
from datetime import date
from pathlib import Path

import pytest
from board_fixtures import board_issue
from cli_fixtures import run_cli, run_context_over, track_board_config
from github_fixtures import FakeForge, serve_forge
from option_cards import (
    GOLDEN_CARD_HASH,
    RETURNED_NOTE,
    RETURNED_ON,
    E,
    card,
    card_body,
    check_defects,
    decide,
    item_body,
    malformed,
    returned_card,
    ruled_card,
    serve_item,
)

from aco import body, expectations, forge
from aco import decide as decide_module
from aco.expectation_grammar import card_hash

ASKED_ON = "asked_on = 2026-10-28\n"
TODAY = date(2026, 10, 29)


def without_asked_on(line: str) -> str:
    assert ASKED_ON in line
    return line.replace(ASKED_ON, "", 1)


def with_asked_on(line: str, value: str) -> str:
    return line.replace(ASKED_ON, f"asked_on = {value}\n", 1)


@pytest.mark.usefixtures("clone")
class TestAskedOnCheck:
    @pytest.mark.parametrize(
        "line",
        [
            pytest.param(without_asked_on(card()), id="open"),
            pytest.param(
                without_asked_on(returned_card(RETURNED_ON + RETURNED_NOTE)), id="returned"
            ),
        ],
    )
    def test_an_open_or_returned_line_without_it_is_refused(
        self, capsys: pytest.CaptureFixture[str], line: str
    ) -> None:
        """Spec: BODY-101."""
        status, defects = check_defects(capsys, card_body(line))
        assert defects == [malformed(f"{E}.asked_on", f"{E}.asked_on is required")]
        assert status == 2

    @pytest.mark.parametrize(
        "line",
        [
            pytest.param(with_asked_on(card(), '"2026-10-28"'), id="string-open"),
            pytest.param(with_asked_on(card(), "2026-10-28T10:00:00"), id="datetime-open"),
            pytest.param(with_asked_on(ruled_card(), '"2026-10-28"'), id="string-ruled"),
        ],
    )
    def test_a_value_that_is_not_a_local_date_is_refused(
        self, capsys: pytest.CaptureFixture[str], line: str
    ) -> None:
        """Spec: BODY-102 -- a datetime is no date."""
        status, defects = check_defects(capsys, card_body(line))
        assert defects == [malformed(f"{E}.asked_on", f"{E}.asked_on must be a TOML local date")]
        assert status == 2

    def test_a_ruled_line_may_lack_it(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: BODY-103."""
        status, defects = check_defects(capsys, card_body(without_asked_on(ruled_card())))
        assert defects == []
        assert status == 0

    def test_the_card_hash_is_the_same_with_and_without_it(self) -> None:
        """Spec: BODY-103 -- the golden card hash holds either way."""
        dated = tomllib.loads(card())["expectation"][0]
        undated = tomllib.loads(without_asked_on(card()))["expectation"][0]
        assert card_hash(dated) == GOLDEN_CARD_HASH
        assert card_hash(undated) == GOLDEN_CARD_HASH


@pytest.mark.usefixtures("github_world")
class TestAskedOnRulings:
    def line_json(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], line: str
    ) -> dict[str, object]:
        serve_forge(
            monkeypatch, FakeForge(board_issues=(board_issue(7, "Karte", card_body(line)),))
        )
        return json.loads(run_cli(["rulings", "--json"], capsys).stdout)["rulings"][0]["lines"][0]

    def test_the_date_follows_text_in_the_json(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RUL-19."""
        listed = self.line_json(monkeypatch, capsys, card())
        keys = list(listed)
        assert listed["asked_on"] == "2026-10-28"
        assert keys[keys.index("text") + 1] == "asked_on"

    def test_a_ruled_line_stored_without_it_prints_null(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RUL-19, BODY-103."""
        listed = self.line_json(monkeypatch, capsys, without_asked_on(ruled_card()))
        assert listed["asked_on"] is None


class TestAskedOnKeptByRule:
    @pytest.mark.usefixtures("github_world")
    def test_a_line_ruled_by_rule_on_github_keeps_it(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-101, RUL-19 -- the rewrite of `rule` drops no key."""
        client = serve_item(monkeypatch, item_body(card()))
        ruled = run_cli(["rule", "7", *decide("A", "chat")], capsys)
        assert ruled.status == 0, ruled.stderr
        assert ASKED_ON in client.item_bodies[7]

    def test_a_line_ruled_in_a_state_ref_checkout_keeps_it(self, clone: Path) -> None:
        """Spec: BODY-101, RUL-19 -- the shared writer drops no key on the state-ref pin."""
        track_board_config(clone, f'storage = "{body.Storage.STATE_REF.value}"\n')
        reference = forge.ItemReference(forge.ItemState.OPEN, "Karte", item_body(card()))
        client = FakeForge(issue_references={7: reference})
        context = run_context_over(client)
        choice = expectations.OptionChoice("A", expectations.RulingVia.CHAT, GOLDEN_CARD_HASH)
        outcome = decide_module.LineOutcome(2, choice)
        decide_module.rule(
            context, decide_module.fresh_item(context, 7, command="rule"), [outcome], TODAY
        )
        assert ASKED_ON in client.item_bodies[7]
