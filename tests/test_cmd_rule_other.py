"""`aco rule --other` through the real CLI: it decides an open option line with
the operator's own answer, stores it verbatim, keeps a later write
byte-identical and stands (RULE-20, RULE-04, BODY-92, BODY-88, BODY-87, RUL-16)."""

from __future__ import annotations

import json

import pytest
from board_fixtures import board_issue
from cli_fixtures import FROZEN_CLI_NOW, freeze_cli_now, run_cli
from github_fixtures import FakeForge, serve_forge
from option_cards import (
    ALREADY_RULED,
    GOLDEN_CARD_HASH,
    OTHER_ANSWER,
    E,
    card,
    card_body,
    check_defects,
    decide,
    item_body,
    malformed,
    other_arguments,
    other_card,
    serve_item,
)

from aco import body


def line_two(rulings_stdout: str) -> dict[str, object]:
    return json.loads(rulings_stdout)["rulings"][0]["lines"][1]


def serve_written(monkeypatch: pytest.MonkeyPatch, written: str) -> None:
    serve_forge(monkeypatch, FakeForge(board_issues=(board_issue(7, "Karte", written),)))


@pytest.mark.usefixtures("github_world")
class TestRuleOther:
    @pytest.mark.parametrize("via", ["board", "chat"])
    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    def test_an_open_option_line_is_ruled_with_the_answer(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        via: str,
        newline: str,
    ) -> None:
        """Spec: RULE-20, RULE-01, BODY-92, BODY-88, RUL-16 -- five keys, the answer verbatim."""
        freeze_cli_now(monkeypatch)
        today = FROZEN_CLI_NOW.date()
        client = serve_item(monkeypatch, item_body(card(), newline=newline))
        ruled = run_cli(["rule", "7", *other_arguments(OTHER_ANSWER, via)], capsys)
        assert (ruled.status, ruled.stdout) == (0, "RULED #7 line 2 other; 0 line(s) still open\n")
        written = client.item_bodies[7]
        entry = body.block_expectation_dicts(body.locate_block(written).data)[1]
        assert (
            entry["ruling"],
            entry["ruled_on"],
            entry["card_hash"],
            entry["via"],
            entry["other"],
        ) == ("other", today, GOLDEN_CARD_HASH, via, OTHER_ANSWER)
        assert f'via = "{via}"{newline}other = ' in written
        checked = run_cli(["check", "-"], capsys, stdin=written)
        assert (checked.status, checked.stdout) == (0, "body ok\n")
        serve_written(monkeypatch, written)
        header = run_cli(["rulings"], capsys).stdout.splitlines()[0]
        line = line_two(run_cli(["rulings", "--json"], capsys).stdout)
        assert (header, line["ruling"], line["ruled_on"], line["via"], line["other"]) == (
            "#7 0/2: Karte",
            "other",
            today.isoformat(),
            via,
            OTHER_ANSWER,
        )
        assert (line["stored_card_hash"], line["card_hash"]) == (GOLDEN_CARD_HASH, GOLDEN_CARD_HASH)

    def test_the_json_answer_names_other(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-20, RULE-02 -- `other` is `ruling` in the success envelope."""
        freeze_cli_now(monkeypatch)
        serve_item(monkeypatch, item_body(card()))
        result = run_cli(["rule", "7", *other_arguments(OTHER_ANSWER), "--json"], capsys)
        assert (result.status, json.loads(result.stdout)) == (
            0,
            {
                "ok": True,
                "reason": "ruled",
                "item": 7,
                "index": 2,
                "ruling": "other",
                "ruled_on": FROZEN_CLI_NOW.date().isoformat(),
                "open": 0,
            },
        )

    @pytest.mark.parametrize(
        "answer",
        [
            pytest.param("Zeile 1\n„Zitat“ \\ \u202e Ende", id="multi-line-quotes-backslash-bidi"),
            pytest.param("  eingerückt \n", id="surrounding-whitespace"),
            pytest.param("-x", id="leading-dash"),
        ],
    )
    def test_the_answer_survives_verbatim(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], answer: str
    ) -> None:
        """Spec: RUL-16, RUL-11 -- `--json` carries the answer as stored."""
        client = serve_item(monkeypatch, item_body(card()))
        ruled = run_cli(["rule", "7", *other_arguments(answer)], capsys)
        assert ruled.status == 0, ruled.stderr
        serve_written(monkeypatch, client.item_bodies[7])
        assert line_two(run_cli(["rulings", "--json"], capsys).stdout)["other"] == answer

    def test_the_text_summary_is_the_escaped_answer(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RUL-02, RUL-11, RUL-16 -- the answer, not the card's text, whitespace
        collapsed and the display control escaped."""
        freeze_cli_now(monkeypatch)
        today = FROZEN_CLI_NOW.date().isoformat()
        client = serve_item(monkeypatch, item_body(card()))
        run_cli(["rule", "7", *other_arguments("Zeile 1\n„Zitat“ \\ \u202e Ende")], capsys)
        serve_written(monkeypatch, client.item_bodies[7])
        text = run_cli(["rulings"], capsys).stdout
        assert text.splitlines()[2] == f"  2 ruled other {today}: Zeile 1 „Zitat“ \\ \\u202e Ende"

    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    def test_a_later_write_keeps_the_other_line_byte_identical(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], newline: str
    ) -> None:
        """Spec: BODY-88 -- ruling another line leaves the Other line's bytes alone."""
        client = serve_item(monkeypatch, item_body(card(), yes_no_line=card(), newline=newline))
        run_cli(["rule", "7", *other_arguments(OTHER_ANSWER)], capsys)
        first = client.item_bodies[7]
        later = serve_item(monkeypatch, first)
        ruled = run_cli(["rule", "7", *decide("A", "chat", line=1)], capsys)
        assert ruled.status == 0, ruled.stderr
        other_line = first.split(f"[[expectation]]{newline}")[2].split("```")[0]
        assert other_line in later.item_bodies[7]

    @pytest.mark.parametrize(
        "arguments",
        [
            pytest.param(
                ["--line", "2", "--option", "A", "--via", "chat", "--card-hash", GOLDEN_CARD_HASH],
                id="a-letter",
            ),
            pytest.param(other_arguments("Anders"), id="a-second-answer"),
        ],
    )
    def test_an_other_ruling_stands(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        arguments: list[str],
    ) -> None:
        """Spec: RULE-04 -- a changed ruling is a new line."""
        client = serve_item(monkeypatch, item_body(other_card()))
        result = run_cli(["rule", "7", *arguments], capsys)
        assert (result.status, result.stderr) == (2, f"ERROR: {ALREADY_RULED}\n")
        assert client.body_writes == []

    def test_next_and_board_count_an_other_line_as_decided(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-04 -- `ruling` present means decided: `board` counts the Other line
        ruled, and `next` asks for no refining once its remaining line is ruled."""
        client = serve_item(monkeypatch, item_body(card(), yes_no_line=card()))
        run_cli(["rule", "7", *other_arguments(OTHER_ANSWER)], capsys)
        serve_written(monkeypatch, client.item_bodies[7])
        shown = json.loads(run_cli(["board", "--json"], capsys).expect_success())["items"][0]
        assert (shown["expectation_state"], shown["expectation_progress"]) == (
            "proposed",
            {"open": 1, "total": 2},
        )
        assert "expectations unruled" in run_cli(["next"], capsys).expect_success()
        later = serve_item(monkeypatch, client.item_bodies[7])
        run_cli(["rule", "7", *decide("A", "chat", line=1)], capsys)
        serve_written(monkeypatch, later.item_bodies[7])
        shown = json.loads(run_cli(["board", "--json"], capsys).expect_success())["items"][0]
        assert (shown["expectation_state"], shown["expectation_progress"]) == (
            "ruled",
            {"open": 0, "total": 2},
        )
        assert "expectations unruled" not in run_cli(["next"], capsys).expect_success()


@pytest.mark.usefixtures("clone")
class TestOtherLineGrammar:
    def test_an_other_card_edited_later_is_refused(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-92, BODY-87 -- the stored hash covers the card, not the answer."""
        edited = other_card(('area = "Song-Seite"', 'area = "Song-Liste"'))
        expected = [
            malformed(
                f"{E}.card_hash", f"{E} was edited after its ruling; a changed ruling is a new line"
            )
        ]
        assert check_defects(capsys, card_body(edited)) == (2, expected)
