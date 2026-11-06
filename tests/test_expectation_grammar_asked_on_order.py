"""A ruled option line was not ruled before it was asked (BODY-108)."""

from __future__ import annotations

import pytest
from option_cards import E, card_body, check_defects, malformed, ruled_card

ASKED_ON = "asked_on = 2026-08-20\n"
RULED_ON = "ruled_on = 2026-10-28\n"


@pytest.mark.usefixtures("clone")
class TestRuledBeforeAsked:
    def test_a_line_ruled_before_it_was_asked_is_refused(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-108 -- the refusal names both dates."""
        line = ruled_card().replace(RULED_ON, "ruled_on = 2026-08-19\n", 1)
        status, defects = check_defects(capsys, card_body(line))
        assert defects == [
            malformed(
                f"{E}.ruled_on",
                f"{E}.ruled_on 2026-08-19 is before asked_on 2026-08-20",
            )
        ]
        assert status == 2

    @pytest.mark.parametrize(
        "ruled_on",
        [
            pytest.param("2026-08-20", id="same-day"),
            pytest.param("2026-08-21", id="later"),
        ],
    )
    def test_a_line_ruled_on_or_after_the_day_it_was_asked_is_accepted(
        self, capsys: pytest.CaptureFixture[str], ruled_on: str
    ) -> None:
        """Spec: BODY-108."""
        line = ruled_card().replace(RULED_ON, f"ruled_on = {ruled_on}\n", 1)
        status, defects = check_defects(capsys, card_body(line))
        assert defects == []
        assert status == 0

    def test_a_ruled_line_without_asked_on_is_accepted(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-103 -- nothing to compare."""
        line = ruled_card().replace(ASKED_ON, "", 1).replace(RULED_ON, "ruled_on = 2020-01-01\n", 1)
        status, defects = check_defects(capsys, card_body(line))
        assert defects == []
        assert status == 0
