"""The yes/no line is read-only history (BODY-29, BODY-31..33): an open one is
refused with a pointer to the option card, `default` is an unknown key, and a
ruled one keeps passing with its card fields."""

from __future__ import annotations

import pytest
from option_cards import E, card_body, check_defects, malformed

OPEN_LINE = f"{E} is an open yes/no line; write an option card"
RULED = 'ruling = "no"\nruled_on = 2026-10-01\n'
PICTURE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>'


def yes_no_line(keys: str) -> str:
    return f'[[expectation]]\ntext = "Alt"\n{keys}'


@pytest.mark.usefixtures("clone")
class TestYesNoLineCheck:
    @pytest.mark.parametrize(
        ("keys", "defects"),
        [
            pytest.param("", [malformed(E, OPEN_LINE)], id="BODY-29-open"),
            pytest.param(
                'default = "yes"\n',
                [malformed(E, OPEN_LINE), malformed(f"{E}.default", f"unknown key {E}.default")],
                id="BODY-29-open-with-default",
            ),
            pytest.param(
                RULED + 'default = "yes"\n',
                [malformed(f"{E}.default", f"unknown key {E}.default")],
                id="BODY-33-ruled-with-default",
            ),
            pytest.param(
                'ruling = "no"\n',
                [malformed(f"{E}.ruled_on", f"{E}.ruled_on must be a TOML local date")],
                id="BODY-32-ruling-alone",
            ),
            pytest.param(
                "ruled_on = 2026-10-01\n",
                [malformed(f"{E}.ruling", f"{E}.ruling must be yes, no, or later")],
                id="BODY-31-ruled-on-alone",
            ),
        ],
    )
    def test_a_yes_no_line_that_is_not_ruled_history_is_refused(
        self, capsys: pytest.CaptureFixture[str], keys: str, defects: list[str]
    ) -> None:
        """Spec: BODY-29, BODY-31, BODY-32, BODY-33."""
        assert check_defects(capsys, card_body(yes_no_line(keys))) == (2, defects)

    @pytest.mark.parametrize(
        "keys",
        [
            pytest.param(
                f'{RULED}question = "Q?"\nexample = "E"\npicture = """{PICTURE}"""\n',
                id="ruled-with-card-fields",
            ),
            pytest.param('ruling = "later"\nruled_on = 2026-10-01\n', id="ruled-later"),
        ],
    )
    def test_a_ruled_yes_no_line_passes(
        self, capsys: pytest.CaptureFixture[str], keys: str
    ) -> None:
        """Spec: BODY-29, BODY-33 -- ruled history stays readable."""
        assert check_defects(capsys, card_body(yes_no_line(keys))) == (0, [])
