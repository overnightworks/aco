"""`aco rule` never stamps a `ruled_on` before the line's `asked_on` (RULE-38)."""

from __future__ import annotations

import pytest
from cli_fixtures import FROZEN_CLI_NOW, freeze_cli_now, run_cli
from option_cards import (
    assert_refusal_writes_nothing,
    card,
    card_head,
    decide,
    item_body,
    other_arguments,
    serve_item,
)

from aco import body

ASKED_TOMORROW = "asked_on = 2026-08-22\n"


@pytest.mark.usefixtures("github_world")
class TestAskedAfterToday:
    @pytest.mark.parametrize(
        "arguments",
        [
            pytest.param(decide("A", "chat"), id="option"),
            pytest.param(other_arguments("Weder noch"), id="other"),
        ],
    )
    def test_a_line_asked_after_todays_utc_date_is_refused_before_any_write(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        arguments: list[str],
    ) -> None:
        """Spec: RULE-38."""
        freeze_cli_now(monkeypatch)
        line = card(card_head(("asked_on = 2026-08-20\n", ASKED_TOMORROW)))
        client = serve_item(monkeypatch, item_body(line))
        assert_refusal_writes_nothing(
            client,
            capsys,
            arguments,
            "line 2 has asked_on 2026-08-22, after today's UTC date 2026-08-21; "
            "asked_on must be today's UTC date or earlier",
            "invalid_usage",
        )

    def test_a_line_asked_today_is_ruled_on_the_day_it_was_asked(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-38 -- the same UTC day is valid."""
        freeze_cli_now(monkeypatch)
        today = FROZEN_CLI_NOW.date()
        line = card(card_head(("asked_on = 2026-08-20", f"asked_on = {today.isoformat()}")))
        client = serve_item(monkeypatch, item_body(line))
        ruled = run_cli(["rule", "7", *decide("A", "chat")], capsys)
        assert (ruled.status, ruled.stdout) == (0, "RULED #7 line 2 A; 0 line(s) still open\n")
        expectations = body.locate_block(client.item_bodies[7]).data["expectation"]
        assert isinstance(expectations, list)
        written = expectations[1]
        assert (written["asked_on"], written["ruled_on"]) == (today, today)
