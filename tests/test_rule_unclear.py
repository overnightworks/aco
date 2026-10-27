"""An open option line sent back to its head: the body grammar that stores
`returned_on` and `returned_note` (BODY-93/94), `aco rule --unclear` that writes
them (RULE-22..27) and `aco rulings` that reads them (RUL-17/18)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from board_fixtures import board_issue
from cli_fixtures import FROZEN_CLI_NOW, freeze_cli_now, run_cli
from github_fixtures import FakeForge, assert_github_world, serve_forge
from test_option_line_rewrites import assert_rewritten_alike
from test_option_lines import (
    GOLDEN_CARD_HASH,
    E,
    card,
    card_body,
    card_head,
    check_defects,
    malformed,
    other_card,
    ruled_card,
)
from test_rule_option import (
    ALREADY_RULED,
    CARD_CHANGED,
    RULED_YES_NO_LINE,
    STALE_CARD_HASH,
    YES_NO_LINE,
    decide,
    item_body,
    other_arguments,
    serve_item,
)

from aco import body, forge

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


TODAY = FROZEN_CLI_NOW.date().isoformat()
NOTE = "Was kostet B im Betrieb?"
AWKWARD_NOTE = "Zeile 1\n„Zitat“ \\ \u202e Ende"
LINE_TEXT_SUMMARY = (
    "Ein Klick auf den Ursprungs-Link springt in der App: die Version klappt auf, "
    "der Take ist markiert,…"
)
ALREADY_WITH_HEAD = "line 2 is already with its head; it comes back once revised"
ANSWERED_UNCLEAR = "line 2 was answered Unclear; --via default records no answer"


def returned_today(note: str | None = NOTE) -> str:
    """The open option line as `--unclear` writes it on the frozen day."""
    note_key = "" if note is None else f"returned_note = {json.dumps(note, ensure_ascii=False)}\n"
    return returned_card(f"returned_on = {TODAY}\n{note_key}")


def unclear(note: str | None = None, shown: str = GOLDEN_CARD_HASH, *, line: int = 2) -> list[str]:
    """`rule`'s arguments after the item for one send-back; `=` keeps a leading dash."""
    note_flags = [] if note is None else [f"--note={note}"]
    return ["--line", str(line), "--unclear", *note_flags, "--card-hash", shown]


def line_two(raw: str) -> dict[str, object]:
    return body.block_expectation_dicts(body.locate_block(raw).data)[1]


@pytest.fixture
def github_world(github_clone: Path, bare_remote: Path) -> None:
    assert_github_world(github_clone, bare_remote)


def rulings_of(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], raw_body: str, *flags: str
) -> str:
    """What `rulings` prints for the one item #7 with `raw_body`."""
    serve_forge(monkeypatch, FakeForge(board_issues=(board_issue(7, "Karte", raw_body),)))
    return run_cli(["rulings", *flags], capsys).stdout


@pytest.mark.usefixtures(github_world.__name__)
class TestRuleUnclear:
    @pytest.mark.parametrize("note", [None, NOTE], ids=["no-note", "note"])
    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    def test_an_open_option_line_is_sent_back_to_its_head(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        note: str | None,
        newline: str,
    ) -> None:
        """Spec: RULE-22, RULE-23, BODY-94, RUL-17, RUL-18 -- the line stays open and gains the
        frozen day and the note, nothing else."""
        freeze_cli_now(monkeypatch)
        client = serve_item(monkeypatch, item_body(card(), newline=newline))
        sent = run_cli(["rule", "7", *unclear(note)], capsys)
        assert (sent.status, sent.stdout) == (
            0,
            "RETURNED #7 line 2 to its head; 2 line(s) still open\n",
        )
        written = client.item_bodies[7]
        expected = item_body(returned_today(note), newline=newline)
        assert body.locate_block(written).data == body.locate_block(expected).data
        checked = run_cli(["check", "-"], capsys, stdin=written)
        assert (checked.status, checked.stdout) == (0, "body ok\n")
        listed = rulings_of(monkeypatch, capsys, written, "--json")
        line = json.loads(listed)["rulings"][0]["lines"][1]
        assert (line["ruling"], line["via"], line["stored_card_hash"]) == (None, None, None)
        assert (line["returned_on"], line["returned_note"], line["card_hash"]) == (
            TODAY,
            note,
            GOLDEN_CARD_HASH,
        )
        text = rulings_of(monkeypatch, capsys, written)
        summary = LINE_TEXT_SUMMARY if note is None else note
        assert text == (f"#7 2/2: Karte\n  1 open: Alt\n  2 with head {TODAY}: {summary}\n")

    def test_the_json_answer_names_the_day(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-22, RULE-02 -- `returned` is the success reason."""
        freeze_cli_now(monkeypatch)
        serve_item(monkeypatch, item_body(card()))
        result = run_cli(["rule", "7", *unclear(), "--json"], capsys)
        assert (result.status, json.loads(result.stdout)) == (
            0,
            {
                "ok": True,
                "reason": "returned",
                "item": 7,
                "index": 2,
                "returned_on": TODAY,
                "open": 2,
            },
        )

    def test_the_note_survives_verbatim(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RUL-17, RUL-18, RUL-11 -- `--json` keeps every character, text escapes."""
        client = serve_item(monkeypatch, item_body(card()))
        sent = run_cli(["rule", "7", *unclear(AWKWARD_NOTE)], capsys)
        assert sent.status == 0, sent.stderr
        written = client.item_bodies[7]
        listed = rulings_of(monkeypatch, capsys, written, "--json")
        assert json.loads(listed)["rulings"][0]["lines"][1]["returned_note"] == AWKWARD_NOTE
        text = rulings_of(monkeypatch, capsys, written)
        assert text.splitlines()[-1].endswith(": Zeile 1 „Zitat“ \\ \\u202e Ende")

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            pytest.param(
                ["--line", "2", "--unclear"],
                "--unclear needs --card-hash",
                id="RULE-15-without-card-hash",
            ),
            pytest.param(
                ["--line", "2", "--unclear", "--via", "chat"],
                "--unclear needs --card-hash",
                id="RULE-15-card-hash-before-via",
            ),
            pytest.param(
                [*unclear(), "--via", "chat"],
                "--via does not go with --unclear; nothing is decided",
                id="RULE-15-via",
            ),
            pytest.param(
                [*unclear(), "--via", "chat", "--note", "  "],
                "--via does not go with --unclear; nothing is decided",
                id="RULE-15-via-before-RULE-26",
            ),
            pytest.param(
                [*unclear(), "--note", "  "],
                "a blank --note says nothing; leave it out",
                id="RULE-26-blank",
            ),
            pytest.param(
                [*unclear(), "--note", ""],
                "a blank --note says nothing; leave it out",
                id="RULE-26-empty",
            ),
            pytest.param(
                ["--line", "1", "--yes", "--card-hash", GOLDEN_CARD_HASH],
                "--via and --card-hash do not go with --yes, --no or --later",
                id="RULE-15-yes-no",
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
        """Spec: RULE-15, RULE-26, RULE-09 -- before the forge is asked, text and `--json`."""
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
                unclear(line=1),
                "line 1 is a yes/no line; --unclear returns only an option line",
                "invalid_usage",
                id="RULE-16-before-RULE-04",
            ),
            pytest.param(
                card(),
                YES_NO_LINE,
                unclear(line=3),
                "line 3 out of range: this item has 2 expectation line(s)",
                "line_out_of_range",
                id="RULE-05-before-RULE-16",
            ),
            pytest.param(
                ruled_card(),
                YES_NO_LINE,
                unclear(shown=STALE_CARD_HASH),
                ALREADY_RULED,
                "already_ruled",
                id="RULE-04-letter",
            ),
            pytest.param(
                other_card(),
                YES_NO_LINE,
                unclear(),
                ALREADY_RULED,
                "already_ruled",
                id="RULE-04-other",
            ),
            pytest.param(
                returned_today(),
                YES_NO_LINE,
                unclear(shown=STALE_CARD_HASH),
                ALREADY_WITH_HEAD,
                "with_head",
                id="RULE-24-before-RULE-17",
            ),
            pytest.param(
                card(),
                YES_NO_LINE,
                unclear(shown=STALE_CARD_HASH),
                CARD_CHANGED,
                "card_changed",
                id="RULE-17",
            ),
        ],
    )
    def test_a_refused_send_back_leaves_the_body_unwritten(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        option_line: str,
        yes_no_line: str,
        arguments: list[str],
        message: str,
        reason: str,
    ) -> None:
        """Spec: RULE-05, RULE-16, RULE-04, RULE-24, RULE-17, RULE-09 -- in that check order."""
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
        [decide("A", "board"), other_arguments("Anders", "board")],
        ids=["letter", "other"],
    )
    def test_a_ruling_takes_a_line_with_its_head(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        arguments: list[str],
    ) -> None:
        """Spec: RULE-25, RULE-14, RULE-20 -- the line is ruled and both keys are gone."""
        client = serve_item(monkeypatch, item_body(returned_today()))
        ruled = run_cli(["rule", "7", *arguments], capsys)
        assert (ruled.status, ruled.stdout.startswith("RULED #7 line 2 ")) == (0, True)
        entry = line_two(client.item_bodies[7])
        assert {"returned_on", "returned_note"} & set(entry) == set()
        assert entry["card_hash"] == GOLDEN_CARD_HASH
        checked = run_cli(["check", "-"], capsys, stdin=client.item_bodies[7])
        assert (checked.status, checked.stdout) == (0, "body ok\n")

    def test_via_default_records_no_answer_on_a_line_with_its_head(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-27, RULE-09 -- an answered card is not a card left unanswered."""
        client = serve_item(monkeypatch, item_body(returned_today()))
        command = ["rule", "7", *decide("A", "default")]
        text = run_cli(command, capsys)
        wire = run_cli([*command, "--json"], capsys)
        assert (text.status, text.stderr) == (2, f"ERROR: {ANSWERED_UNCLEAR}\n")
        assert (wire.status, json.loads(wire.stdout)) == (
            2,
            {"ok": False, "reason": "with_head", "message": ANSWERED_UNCLEAR},
        )
        assert client.body_writes == []

    def test_via_default_still_rules_an_open_line_not_with_its_head(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-14, RULE-27 -- the refusal is for a line with its head only."""
        serve_item(monkeypatch, item_body(card()))
        ruled = run_cli(["rule", "7", *decide("A", "default")], capsys)
        assert (ruled.status, ruled.stdout) == (0, "RULED #7 line 2 A; 1 line(s) still open\n")

    def test_the_heads_revising_edit_opens_the_line_again(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-94, RUL-18, RULE-23 -- both keys dropped and the card revised reads open,
        and the new card can be sent back again."""
        revised = item_body(card(card_head(('area = "Song-Seite"', 'area = "Anderer Bereich"'))))
        listed = rulings_of(monkeypatch, capsys, revised, "--json")
        line = json.loads(listed)["rulings"][0]["lines"][1]
        assert (line["returned_on"], line["card_hash"] != GOLDEN_CARD_HASH) == (None, True)
        text = rulings_of(monkeypatch, capsys, revised)
        assert text.splitlines()[-1].startswith("  2 open: ")
        client = serve_item(monkeypatch, revised)
        sent = run_cli(["rule", "7", *unclear(NOTE, line["card_hash"])], capsys)
        assert (sent.status, line_two(client.item_bodies[7])["returned_note"]) == (0, NOTE)


@pytest.mark.usefixtures(github_world.__name__)
class TestReturnedLineRewrites:
    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    def test_a_later_write_keeps_a_returned_line_byte_for_byte(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        newline: str,
    ) -> None:
        """Spec: BODY-88 -- `rule` on another line, then `ask` appending one."""
        raw = item_body(returned_today(), newline=newline)
        reference = forge.ItemReference(forge.ItemState.OPEN, "Karte", raw)
        client = serve_forge(monkeypatch, FakeForge(issue_references={7: reference}))
        ruled = run_cli(["rule", "7", "--line", "1", "--yes"], capsys)
        assert ruled.status == 0, ruled.stderr
        assert_rewritten_alike(raw, client.item_bodies[7], body.Storage.GITHUB)
        client.issue_references[7] = dataclasses.replace(reference, body=client.item_bodies[7])
        asked = run_cli(["ask", "7", "--text", "Neue Frage?"], capsys)
        assert asked.status == 0, asked.stderr
        assert_rewritten_alike(raw, client.item_bodies[7], body.Storage.GITHUB)
        kept = line_two(client.item_bodies[7])
        assert (kept["returned_on"], kept["returned_note"]) == (FROZEN_CLI_NOW.date(), NOTE)
