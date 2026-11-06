"""`aco rule` never stamps a `ruled_on` before the line's `asked_on` (RULE-38)."""

from __future__ import annotations

import pytest
from cli_fixtures import freeze_cli_now
from option_cards import (
    assert_refusal_writes_nothing,
    card,
    card_head,
    decide,
    item_body,
    other_arguments,
    serve_item,
)

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
