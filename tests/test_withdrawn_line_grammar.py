"""A withdrawn expectation line through `aco check -` and through every body
rewrite: `text` and a local-date `withdrawn_on`, nothing else, its index kept
(BODY-104..BODY-106, BODY-27, BODY-88)."""

from __future__ import annotations

import json

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import run_cli
from option_cards import (
    YES_NO_LINE,
    E,
    card,
    card_body,
    check_defects,
    malformed,
    returned_card,
    ruled_card,
)

from aco import body

WITHDRAWN = '[[expectation]]\ntext = "Soll der Song offen bleiben?"\nwithdrawn_on = 2026-10-29\n'


def withdrawn_with(keys: str, *, text: str = 'text = "Soll der Song offen bleiben?"\n') -> str:
    """A withdrawn line carrying `keys` after its `withdrawn_on`."""
    return f"[[expectation]]\n{text}withdrawn_on = 2026-10-29\n{keys}"


def not_on_a_withdrawn_line(key: str) -> str:
    return malformed(f"{E}.{key}", f"{E}.{key} does not belong on a withdrawn line")


OVERLOADED = withdrawn_with(
    'ruling = "yes"\nruled_on = 2026-10-01\nquestion = "Q?"\nasked_on = 2026-10-28\n'
    'default = "yes"\nweird = 1\n\n[[expectation.option]]\nname = "Wie heute"\n'
)
OVERLOADED_DEFECTS = [
    not_on_a_withdrawn_line(key)
    for key in ("ruling", "ruled_on", "question", "asked_on", "default", "weird", "option")
]


@pytest.mark.usefixtures("clone")
class TestWithdrawnLineCheck:
    @pytest.mark.parametrize(
        "neighbours",
        [
            pytest.param((), id="alone"),
            pytest.param((card(),), id="beside-an-open-line"),
            pytest.param((returned_card(),), id="beside-a-returned-line"),
            pytest.param((ruled_card(),), id="beside-a-ruled-option-line"),
            pytest.param((YES_NO_LINE,), id="beside-a-ruled-yes-no-line"),
            pytest.param((card(), returned_card(), ruled_card(), YES_NO_LINE), id="beside-all"),
        ],
    )
    def test_a_withdrawn_line_passes_check(
        self, capsys: pytest.CaptureFixture[str], neighbours: tuple[str, ...]
    ) -> None:
        """Spec: BODY-104 -- text and a local-date withdrawn_on, nothing else."""
        raw = card_body(WITHDRAWN, before="".join("\n" + line for line in neighbours))
        result = run_cli(["check", "-"], capsys, stdin=raw)
        assert (result.status, result.stdout, result.stderr) == (0, "body ok\n", "")

    def test_every_other_key_is_refused_once_in_the_order_written(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-105 -- no option-line or yes/no sentence judges a withdrawn line."""
        result = run_cli(["check", "-"], capsys, stdin=card_body(OVERLOADED))
        assert (result.status, result.stderr.splitlines()) == (2, OVERLOADED_DEFECTS)

    def test_check_json_carries_the_same_defects_in_its_envelope(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-105, CHECK-19."""
        result = run_cli(["check", "-", "--json"], capsys, stdin=card_body(OVERLOADED))
        payload = json.loads(result.stdout)
        assert (result.status, payload["ok"], payload["reason"], payload["defects"]) == (
            2,
            False,
            "malformed",
            OVERLOADED_DEFECTS,
        )

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param('"2026-10-29"', id="string"),
            pytest.param("2026-10-29T10:00:00", id="local-datetime"),
            pytest.param("2026-10-29T10:00:00Z", id="offset-datetime"),
            pytest.param("20261029", id="integer"),
        ],
    )
    def test_a_withdrawn_on_that_is_no_local_date_is_refused(
        self, capsys: pytest.CaptureFixture[str], value: str
    ) -> None:
        """Spec: BODY-106."""
        line = f'[[expectation]]\ntext = "T"\nwithdrawn_on = {value}\n'
        expected = malformed(f"{E}.withdrawn_on", f"{E}.withdrawn_on must be a TOML local date")
        assert check_defects(capsys, card_body(line)) == (2, [expected])

    @pytest.mark.parametrize(
        ("text", "keys", "defects"),
        [
            pytest.param("", "", [], id="missing"),
            pytest.param('text = "  "\n', "", [], id="blank"),
            pytest.param(
                "", 'via = "chat"\n', [not_on_a_withdrawn_line("via")], id="missing-and-a-key"
            ),
        ],
    )
    def test_a_missing_or_blank_text_is_refused_first(
        self, capsys: pytest.CaptureFixture[str], text: str, keys: str, defects: list[str]
    ) -> None:
        """Spec: BODY-27, BODY-105 -- text, then withdrawn_on, then every other key."""
        line = withdrawn_with(keys, text=text)
        first = malformed(f"{E}.text", f"{E}.text must be a non-empty string")
        assert check_defects(capsys, card_body(line)) == (2, [first, *defects])


def mixed_block(newline: str) -> str:
    """Line 1 an open card, line 2 withdrawn with its keys written the other way round,
    line 3 a ruled yes/no line."""
    reversed_withdrawn = (
        '[[expectation]]\nwithdrawn_on = 2026-10-29\ntext = "Soll der Song offen bleiben?"\n'
    )
    lines = "\n".join((card(), reversed_withdrawn, YES_NO_LINE))
    return block_body((MINIMAL_BLOCK_TOML + "\n" + lines).rstrip("\n")).replace("\n", newline)


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_a_rewrite_keeps_the_withdrawn_line_with_withdrawn_on_after_text(newline: str) -> None:
    """Spec: BODY-88 -- values kept, `withdrawn_on` right after `text`, a second
    rewrite changes no byte."""
    raw = mixed_block(newline)
    located = body.locate_block(raw)
    rewritten = body.replace_block(raw, located, located.data)
    reread = body.locate_block(rewritten)
    assert reread.data == located.data
    assert WITHDRAWN.replace("\n", newline) in rewritten
    assert body.replace_block(rewritten, reread, reread.data) == rewritten
    assert body.parse_body(rewritten).read_state is body.BodyReadState.VALID
