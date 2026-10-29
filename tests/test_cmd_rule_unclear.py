"""An open option line sent back to its head: the body grammar that stores
`returned_on` and `returned_note` (BODY-93/94), `aco rule --unclear` that writes
them (RULE-22..27) and `aco rulings` that reads them (RUL-17/18)."""

from __future__ import annotations

import json

import pytest
from board_fixtures import board_issue
from cli_fixtures import FROZEN_CLI_NOW, freeze_cli_now, run_cli
from github_fixtures import FakeForge, serve_forge
from option_cards import (
    GOLDEN_CARD_HASH,
    NOTE,
    RETURNED_ON,
    STALE_CARD_HASH,
    TODAY,
    E,
    card,
    card_body,
    card_head,
    check_defects,
    decide,
    item_body,
    malformed,
    option_entries,
    other_arguments,
    returned_today,
    serve_item,
    unclear,
)

from aco import body, forge


@pytest.mark.usefixtures("clone")
class TestReturnedLineGrammar:
    def test_a_yes_no_line_keeps_returned_on_an_unknown_key(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-93, BODY-33 -- only an option line can be with its head."""
        line = '[[expectation]]\ntext = "T"\ndefault = "yes"\n' + RETURNED_ON
        assert check_defects(capsys, card_body(line)) == (
            2,
            [malformed(f"{E}.returned_on", f"unknown key {E}.returned_on")],
        )


AWKWARD_NOTE = "Zeile 1\n„Zitat“ \\ \u202e Ende"
LINE_TEXT_SUMMARY = (
    "Ein Klick auf den Ursprungs-Link springt in der App: die Version klappt auf, "
    "der Take ist markiert,…"
)
ANSWERED_UNCLEAR = "line 2 was answered Unclear; --via default records no answer"


def line_two(raw: str) -> dict[str, object]:
    return body.block_expectation_dicts(body.locate_block(raw).data)[1]


def rulings_of(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], raw_body: str, *flags: str
) -> str:
    """What `rulings` prints for the one item #7 with `raw_body`."""
    serve_forge(monkeypatch, FakeForge(board_issues=(board_issue(7, "Karte", raw_body),)))
    return run_cli(["rulings", *flags], capsys).stdout


@pytest.mark.usefixtures("github_world")
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

    @pytest.mark.parametrize(
        "shown",
        [
            pytest.param(GOLDEN_CARD_HASH, id="RULE-27"),
            pytest.param(STALE_CARD_HASH, id="RULE-27-before-RULE-17"),
        ],
    )
    def test_via_default_records_no_answer_on_a_line_with_its_head(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], shown: str
    ) -> None:
        """Spec: RULE-27, RULE-09 -- an answered card is not a card left unanswered."""
        client = serve_item(monkeypatch, item_body(returned_today()))
        command = ["rule", "7", *decide("A", "default", shown)]
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


@pytest.mark.usefixtures("github_world")
class TestReturnedLineRewrites:
    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    def test_ruling_another_line_keeps_a_returned_line_byte_for_byte(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        newline: str,
    ) -> None:
        """Spec: BODY-88 -- `rule` on another line keeps a returned line."""
        raw = item_body(returned_today(), yes_no_line=card(), newline=newline)
        reference = forge.ItemReference(forge.ItemState.OPEN, "Karte", raw)
        client = serve_forge(monkeypatch, FakeForge(issue_references={7: reference}))
        ruled = run_cli(["rule", "7", *decide("A", "chat", line=1)], capsys)
        assert ruled.status == 0, ruled.stderr
        assert option_entries(client.item_bodies[7])[1:] == option_entries(raw)[1:]
        kept = line_two(client.item_bodies[7])
        assert (kept["returned_on"], kept["returned_note"]) == (FROZEN_CLI_NOW.date(), NOTE)
