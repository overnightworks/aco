"""`aco rule --option` through the real CLI: it decides an open option line,
records how the decision reached aco, and refuses a stale card, a wrong
letter or a wrong flag combination before any write (RULE-14..RULE-19)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from board_fixtures import board_issue
from cli_fixtures import FROZEN_CLI_NOW, freeze_cli_now, run_cli
from github_fixtures import FakeForge, assert_github_world, serve_forge
from test_option_lines import GOLDEN_CARD_HASH, card, card_body, ruled_card

from aco import body, forge

STALE_CARD_HASH = "sha256:" + "0" * 64
YES_NO_LINE = '[[expectation]]\ntext = "Alt"\ndefault = "no"\n'
RULED_YES_NO_LINE = '[[expectation]]\ntext = "Alt"\nruling = "no"\nruled_on = 2026-10-01\n'
CARD_CHANGED = "line 2 changed since its card was shown; show it again and rule what it shows now"


@pytest.fixture
def github_world(github_clone: Path, bare_remote: Path) -> None:
    assert_github_world(github_clone, bare_remote)


def item_body(option_line: str, *, yes_no_line: str = YES_NO_LINE, newline: str = "\n") -> str:
    """Issue #7's body: line 1 a yes/no line, line 2 `option_line`."""
    return card_body(option_line, before="\n" + yes_no_line, newline=newline)


def serve_item(monkeypatch: pytest.MonkeyPatch, raw_body: str) -> FakeForge:
    reference = forge.ItemReference(forge.ItemState.OPEN, "Karte", raw_body)
    return serve_forge(monkeypatch, FakeForge(issue_references={7: reference}))


def decide(letter: str, via: str, shown: str = GOLDEN_CARD_HASH, *, line: int = 2) -> list[str]:
    """`rule`'s arguments after the item for one option choice."""
    return ["--line", str(line), "--option", letter, "--via", via, "--card-hash", shown]


def decided_state(rulings_stdout: str) -> tuple[object, ...]:
    """Line 2's `rulings --json` decision as (ruling, ruled_on, via, stored, current hash)."""
    line = json.loads(rulings_stdout)["rulings"][0]["lines"][1]
    return (
        line["ruling"],
        line["ruled_on"],
        line["via"],
        line["stored_card_hash"],
        line["card_hash"],
    )


@pytest.mark.usefixtures(github_world.__name__)
class TestRuleOption:
    @pytest.mark.parametrize("via", ["board", "chat", "default"])
    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    def test_an_open_option_line_is_ruled_with_its_letter_via_and_card_hash(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        via: str,
        newline: str,
    ) -> None:
        """Spec: RULE-14, RULE-01, BODY-85, BODY-88, RUL-02, RUL-15 -- four keys, nothing else."""
        freeze_cli_now(monkeypatch)
        today = FROZEN_CLI_NOW.date().isoformat()
        client = serve_item(monkeypatch, item_body(card(), newline=newline))
        ruled = run_cli(["rule", "7", *decide("A", via)], capsys)
        assert (ruled.status, ruled.stdout) == (0, "RULED #7 line 2 A; 1 line(s) still open\n")
        written = client.item_bodies[7]
        expected = item_body(
            ruled_card(("ruled_on = 2026-10-28", f"ruled_on = {today}"), ('"board"', f'"{via}"')),
            newline=newline,
        )
        assert body.locate_block(written).data == body.locate_block(expected).data
        checked = run_cli(["check", "-"], capsys, stdin=written)
        assert (checked.status, checked.stdout) == (0, "body ok\n")
        serve_forge(monkeypatch, FakeForge(board_issues=(board_issue(7, "Karte", written),)))
        rulings = run_cli(["rulings", "--json"], capsys)
        decided = ("A", today, via, GOLDEN_CARD_HASH, GOLDEN_CARD_HASH)
        assert decided_state(rulings.stdout) == decided

    def test_the_json_answer_names_the_letter(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-14, RULE-02 -- the letter is `ruling` in the success envelope."""
        freeze_cli_now(monkeypatch)
        serve_item(monkeypatch, item_body(card()))
        result = run_cli(["rule", "7", *decide("B", "board"), "--json"], capsys)
        assert (result.status, json.loads(result.stdout)) == (
            0,
            {
                "ok": True,
                "reason": "ruled",
                "item": 7,
                "index": 2,
                "ruling": "B",
                "ruled_on": FROZEN_CLI_NOW.date().isoformat(),
                "open": 1,
            },
        )

    @pytest.mark.parametrize(
        ("option_line", "yes_no_line", "arguments", "message", "reason"),
        [
            pytest.param(
                card(),
                RULED_YES_NO_LINE,
                decide("A", "chat", line=1),
                "line 1 is a yes/no line; --option rules only an option line",
                "invalid_usage",
                id="RULE-16-before-RULE-04",
            ),
            pytest.param(
                card(),
                YES_NO_LINE,
                decide("A", "chat", line=3),
                "line 3 out of range: this item has 2 expectation line(s)",
                "line_out_of_range",
                id="RULE-05-before-RULE-16",
            ),
            pytest.param(
                ruled_card(),
                YES_NO_LINE,
                decide("B", "chat", STALE_CARD_HASH),
                "line 2 is already ruled; a changed ruling is a new line",
                "already_ruled",
                id="RULE-04-before-RULE-17",
            ),
            pytest.param(
                card(),
                YES_NO_LINE,
                decide("C", "board", STALE_CARD_HASH),
                CARD_CHANGED,
                "card_changed",
                id="RULE-17-before-RULE-18",
            ),
            pytest.param(
                card(),
                YES_NO_LINE,
                decide("A", "chat", "nope"),
                CARD_CHANGED,
                "card_changed",
                id="RULE-17-malformed-hash",
            ),
            pytest.param(
                card(),
                YES_NO_LINE,
                decide("C", "default"),
                "line 2 has no option C; its options are A, B",
                "invalid_usage",
                id="RULE-18-before-RULE-19",
            ),
            pytest.param(
                card(),
                YES_NO_LINE,
                decide("a", "chat"),
                "line 2 has no option a; its options are A, B",
                "invalid_usage",
                id="RULE-18-lowercase",
            ),
            pytest.param(
                card(),
                YES_NO_LINE,
                decide("", "chat"),
                "line 2 has no option ; its options are A, B",
                "invalid_usage",
                id="RULE-18-empty",
            ),
            pytest.param(
                card(),
                YES_NO_LINE,
                decide("AB", "chat"),
                "line 2 has no option AB; its options are A, B",
                "invalid_usage",
                id="RULE-18-longer-than-one-letter",
            ),
            pytest.param(
                card(),
                YES_NO_LINE,
                decide("B", "default"),
                "--via default keeps only the recommended option A, not B",
                "invalid_usage",
                id="RULE-19",
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
        """Spec: RULE-04, RULE-05, RULE-09, RULE-16..RULE-19 -- in that check order."""
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
        ("arguments", "message"),
        [
            pytest.param(
                ["--line", "2", "--option", "A", "--via", "chat"],
                "--option needs --via and --card-hash",
                id="option-without-card-hash",
            ),
            pytest.param(
                ["--line", "2", "--option", "A", "--card-hash", GOLDEN_CARD_HASH],
                "--option needs --via and --card-hash",
                id="option-without-via",
            ),
            pytest.param(
                ["--line", "1", "--yes", "--via", "chat"],
                "--via and --card-hash go only with --option",
                id="via-without-option",
            ),
            pytest.param(
                ["--line", "1", "--no", "--card-hash", GOLDEN_CARD_HASH],
                "--via and --card-hash go only with --option",
                id="card-hash-without-option",
            ),
            pytest.param(
                [*decide("A", "chat"), "--note", "Ja."],
                "--note does not go with --option; keep the operator's word in the item's journal",
                id="note-with-option",
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
        """Spec: RULE-15, RULE-09 -- an item no forge knows would refuse RULE-07 if reached."""
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
