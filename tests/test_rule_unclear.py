"""An open option line sent back to its head: the body grammar that stores
`returned_on` and `returned_note` (BODY-93/94), `aco rule --unclear` that writes
them (RULE-22..27) and `aco rulings` that reads them (RUL-17/18)."""

from __future__ import annotations

import pytest
from cli_fixtures import run_cli
from test_option_lines import (
    E,
    card,
    card_body,
    card_head,
    check_defects,
    malformed,
    other_card,
    ruled_card,
)

RETURNED_ON = "returned_on = 2026-10-28\n"
RETURNED_NOTE = 'returned_note = "Was kostet B im Betrieb?"\n'


def returned_card(keys: str = RETURNED_ON + RETURNED_NOTE) -> str:
    """The open option line with `keys` between its text and its card keys."""
    return card(card_head(("question = ", keys + "question = ")))


def ruled_with(keys: str) -> str:
    """The option line ruled `A`, `keys` placed where a returned line has them."""
    return ruled_card(("question = ", keys + "question = "))


@pytest.mark.usefixtures("clone")
class TestReturnedLineGrammar:
    @pytest.mark.parametrize(
        "line",
        [
            pytest.param(returned_card(), id="date-and-note"),
            pytest.param(returned_card(RETURNED_ON), id="date-alone"),
            pytest.param(
                card(
                    card_head(
                        ("question = ", RETURNED_ON + RETURNED_NOTE + "question = "),
                        ('area = "Song-Seite"', 'area = "Anderer Bereich"'),
                    )
                ),
                id="card-revised-beside-the-keys",
            ),
        ],
    )
    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    def test_an_open_option_line_with_its_head_is_ok(
        self, capsys: pytest.CaptureFixture[str], line: str, newline: str
    ) -> None:
        """Spec: BODY-94 -- the date and an optional note; the card stays editable."""
        result = run_cli(["check", "-"], capsys, stdin=card_body(line, newline=newline))
        assert (result.status, result.stdout) == (0, "body ok\n")

    @pytest.mark.parametrize(
        ("line", "defects"),
        [
            pytest.param(
                returned_card(RETURNED_NOTE),
                [malformed(f"{E}.returned_note", f"{E}.returned_note needs returned_on beside it")],
                id="note-without-date",
            ),
            pytest.param(
                returned_card('returned_on = "2026-10-28"\n'),
                [malformed(f"{E}.returned_on", f"{E}.returned_on must be a TOML local date")],
                id="string-date",
            ),
            pytest.param(
                returned_card(RETURNED_ON + 'returned_note = "  "\n'),
                [malformed(f"{E}.returned_note", f"{E}.returned_note must be a non-empty string")],
                id="blank-note",
            ),
            pytest.param(
                ruled_with(RETURNED_ON + RETURNED_NOTE),
                [
                    malformed(f"{E}.returned_on", f"{E}.returned_on belongs only to an open line"),
                    malformed(
                        f"{E}.returned_note", f"{E}.returned_note belongs only to an open line"
                    ),
                ],
                id="both-keys-on-a-line-ruled-a-letter",
            ),
            pytest.param(
                other_card(("question = ", RETURNED_ON + "question = ")),
                [malformed(f"{E}.returned_on", f"{E}.returned_on belongs only to an open line")],
                id="date-on-a-line-ruled-other",
            ),
        ],
    )
    def test_a_defective_returned_key_is_refused(
        self, capsys: pytest.CaptureFixture[str], line: str, defects: list[str]
    ) -> None:
        """Spec: BODY-93 -- one sentence per refusal, right after `other`'s."""
        assert check_defects(capsys, card_body(line)) == (2, defects)

    def test_a_yes_no_line_keeps_returned_on_an_unknown_key(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-93, BODY-33 -- only an option line can be with its head."""
        line = '[[expectation]]\ntext = "T"\ndefault = "yes"\n' + RETURNED_ON
        assert check_defects(capsys, card_body(line)) == (
            2,
            [malformed(f"{E}.returned_on", f"unknown key {E}.returned_on")],
        )
