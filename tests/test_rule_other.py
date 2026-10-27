"""`aco rule --other` through the real CLI: it decides an open option line with
the operator's own answer, stores it verbatim, and refuses every misuse
before any write (RULE-20, RULE-21, BODY-91, BODY-92, RUL-16)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from board_fixtures import board_issue
from cli_fixtures import FROZEN_CLI_NOW, freeze_cli_now, run_cli
from github_fixtures import FakeForge, assert_github_world, serve_forge
from test_option_lines import (
    GOLDEN_CARD_HASH,
    E,
    card,
    card_body,
    card_head,
    check_defects,
    malformed,
)
from test_rule_option import (
    CARD_CHANGED,
    RULED_YES_NO_LINE,
    STALE_CARD_HASH,
    YES_NO_LINE,
    item_body,
    serve_item,
)

from aco import body

ANSWER = "Nur auf dem Desktop offen lassen; auf dem Handy wie heute."
ALREADY_RULED = "line 2 is already ruled; a changed ruling is a new line"


@pytest.fixture
def github_world(github_clone: Path, bare_remote: Path) -> None:
    assert_github_world(github_clone, bare_remote)


def other_decision(answer: str = ANSWER) -> str:
    """The decided state of a card ruled `other` with the hash of the card shown."""
    return (
        f'ruling = "other"\nruled_on = 2026-10-28\ncard_hash = "{GOLDEN_CARD_HASH}"\n'
        f'via = "chat"\nother = "{answer}"\n'
    )


def other_card(*edits: tuple[str, str]) -> str:
    """The option line ruled `other`, `edits` applied to its head."""
    return card(card_head(("question = ", other_decision() + "question = "), *edits))


def open_card_with(decision: str) -> str:
    return card(card_head(("question = ", decision + "question = ")))


def other_arguments(
    answer: str, via: str = "chat", shown: str = GOLDEN_CARD_HASH, *, line: int = 2
) -> list[str]:
    """`rule`'s arguments after the item for one Other answer; `=` keeps a leading dash."""
    return ["--line", str(line), f"--other={answer}", "--via", via, "--card-hash", shown]


def line_two(rulings_stdout: str) -> dict[str, object]:
    return json.loads(rulings_stdout)["rulings"][0]["lines"][1]


def serve_written(monkeypatch: pytest.MonkeyPatch, written: str) -> None:
    serve_forge(monkeypatch, FakeForge(board_issues=(board_issue(7, "Karte", written),)))


@pytest.mark.usefixtures(github_world.__name__)
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
        ruled = run_cli(["rule", "7", *other_arguments(ANSWER, via)], capsys)
        assert (ruled.status, ruled.stdout) == (0, "RULED #7 line 2 other; 1 line(s) still open\n")
        written = client.item_bodies[7]
        entry = body.block_expectation_dicts(body.locate_block(written).data)[1]
        decided = {key: entry[key] for key in ("ruling", "ruled_on", "card_hash", "via", "other")}
        assert decided == {
            "ruling": "other",
            "ruled_on": today,
            "card_hash": GOLDEN_CARD_HASH,
            "via": via,
            "other": ANSWER,
        }
        checked = run_cli(["check", "-"], capsys, stdin=written)
        assert (checked.status, checked.stdout) == (0, "body ok\n")
        serve_written(monkeypatch, written)
        header = run_cli(["rulings"], capsys).stdout.splitlines()[0]
        line = line_two(run_cli(["rulings", "--json"], capsys).stdout)
        assert header == "#7 1/2: Karte"
        assert (line["ruling"], line["ruled_on"], line["via"], line["other"]) == (
            "other",
            today.isoformat(),
            via,
            ANSWER,
        )
        assert (line["stored_card_hash"], line["card_hash"]) == (GOLDEN_CARD_HASH,) * 2

    def test_the_json_answer_names_other(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-20, RULE-02 -- `other` is `ruling` in the success envelope."""
        freeze_cli_now(monkeypatch)
        serve_item(monkeypatch, item_body(card()))
        result = run_cli(["rule", "7", *other_arguments(ANSWER), "--json"], capsys)
        assert (result.status, json.loads(result.stdout)) == (
            0,
            {
                "ok": True,
                "reason": "ruled",
                "item": 7,
                "index": 2,
                "ruling": "other",
                "ruled_on": FROZEN_CLI_NOW.date().isoformat(),
                "open": 1,
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
        client = serve_item(monkeypatch, item_body(card(), newline=newline))
        run_cli(["rule", "7", *other_arguments(ANSWER)], capsys)
        first = client.item_bodies[7]
        later = serve_item(monkeypatch, first)
        ruled = run_cli(["rule", "7", "--line", "1", "--yes"], capsys)
        assert ruled.status == 0, ruled.stderr
        other_line = first.split(f"[[expectation]]{newline}")[2].split("```")[0]
        assert other_line in later.item_bodies[7]

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            pytest.param(
                ["--line", "2", "--other", "A", "--via", "chat"],
                "--other needs --via and --card-hash",
                id="without-card-hash",
            ),
            pytest.param(
                ["--line", "2", "--other", "A", "--card-hash", GOLDEN_CARD_HASH],
                "--other needs --via and --card-hash",
                id="without-via",
            ),
            pytest.param(
                [*other_arguments("A"), "--note", "Ja."],
                "--note does not go with --other; its text is the answer",
                id="with-note",
            ),
            pytest.param(
                other_arguments("A", "default"),
                "--via default keeps only the recommended option, not --other",
                id="via-default",
            ),
            pytest.param(
                ["--line", "1", "--yes", "--via", "chat"],
                "--via and --card-hash go only with --option or --other",
                id="via-with-a-yes-no-outcome",
            ),
            pytest.param(
                other_arguments("   "),
                "--other needs a non-empty answer",
                id="blank",
            ),
            pytest.param(
                other_arguments("\n"),
                "--other needs a non-empty answer",
                id="lone-newline",
            ),
        ],
    )
    def test_a_flag_combination_is_refused_before_any_forge_call(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        arguments: list[str],
        message: str,
    ) -> None:
        """Spec: RULE-15, RULE-21, RULE-09 -- an item no forge knows would refuse RULE-07."""
        client = serve_forge(monkeypatch, FakeForge())
        command = ["rule", "7", *arguments]
        text = run_cli(command, capsys)
        wire = run_cli([*command, "--json"], capsys)
        assert (text.status, text.stderr) == (2, f"ERROR: {message}\n")
        assert (wire.status, json.loads(wire.stdout)) == (
            2,
            {"ok": False, "reason": "invalid_usage", "message": message},
        )
        assert client.body_writes == []

    @pytest.mark.parametrize(
        ("option_line", "yes_no_line", "arguments", "message", "reason"),
        [
            pytest.param(
                card(),
                RULED_YES_NO_LINE,
                other_arguments(ANSWER, line=1),
                "line 1 is a yes/no line; --other rules only an option line",
                "invalid_usage",
                id="RULE-16-before-RULE-04",
            ),
            pytest.param(
                card(),
                YES_NO_LINE,
                other_arguments(ANSWER, line=3),
                "line 3 out of range: this item has 2 expectation line(s)",
                "line_out_of_range",
                id="RULE-05-before-RULE-16",
            ),
            pytest.param(
                other_card(),
                YES_NO_LINE,
                other_arguments(ANSWER, shown=STALE_CARD_HASH),
                ALREADY_RULED,
                "already_ruled",
                id="RULE-04-before-RULE-17",
            ),
            pytest.param(
                card(),
                YES_NO_LINE,
                other_arguments(ANSWER, shown=STALE_CARD_HASH),
                CARD_CHANGED,
                "card_changed",
                id="RULE-17",
            ),
        ],
    )
    def test_a_refused_ruling_leaves_the_body_unwritten(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        option_line: str,
        yes_no_line: str,
        arguments: list[str],
        message: str,
        reason: str,
    ) -> None:
        """Spec: RULE-04, RULE-05, RULE-09, RULE-16, RULE-17 -- in that check order."""
        client = serve_item(monkeypatch, item_body(option_line, yes_no_line=yes_no_line))
        command = ["rule", "7", *arguments]
        text = run_cli(command, capsys)
        wire = run_cli([*command, "--json"], capsys)
        assert (text.status, text.stderr) == (2, f"ERROR: {message}\n")
        assert (wire.status, json.loads(wire.stdout)) == (
            2,
            {"ok": False, "reason": reason, "message": message},
        )
        assert client.body_writes == []

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


@pytest.mark.usefixtures("clone")
class TestOtherLineGrammar:
    @pytest.mark.parametrize(
        ("line", "defects"),
        [
            pytest.param(
                open_card_with(other_decision().replace(f'other = "{ANSWER}"\n', "")),
                [malformed(f"{E}.other", f"{E}.other is required when ruling is other")],
                id="required-for-other",
            ),
            pytest.param(
                open_card_with(
                    other_decision()
                    .replace('ruling = "other"', 'ruling = "A"')
                    .replace(ANSWER, "x")
                ),
                [malformed(f"{E}.other", f"{E}.other belongs only to a line ruled other")],
                id="refused-beside-a-letter",
            ),
            pytest.param(
                open_card_with('other = "x"\n'),
                [malformed(f"{E}.other", f"{E}.other belongs only to a line ruled other")],
                id="refused-on-an-open-line",
            ),
            pytest.param(
                open_card_with(other_decision().replace(ANSWER, "  ")),
                [malformed(f"{E}.other", f"{E}.other must be a non-empty string")],
                id="non-empty",
            ),
        ],
    )
    def test_a_defective_other_is_refused(
        self, capsys: pytest.CaptureFixture[str], line: str, defects: list[str]
    ) -> None:
        """Spec: BODY-91 -- one sentence per refusal."""
        assert check_defects(capsys, card_body(line)) == (2, defects)

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
