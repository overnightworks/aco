"""`aco rule` with several `--line`: each named line is checked in the order written and
all are written in one body write with one date, or none is (RULE-29..36, E-RULE-13/14)."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from cli_fixtures import FROZEN_CLI_NOW, CliRun, freeze_cli_now, run_cli
from github_fixtures import FakeForge
from option_cards import (
    GOLDEN_CARD_HASH,
    NOTE,
    STALE_CARD_HASH,
    assert_refusal_writes_nothing,
    card,
    group_body,
    other_card,
    returned_today,
    ruled_card,
    serve_item,
    shown_hash,
)

from aco import body, session

TODAY = FROZEN_CLI_NOW.date().isoformat()
ANSWER = "Nur am Desktop."
NOT_GIVEN_TWICE = "{flag} is given twice; give it once"
HASH_2 = shown_hash(group_body(), 2)
HASH_3 = shown_hash(group_body(), 3)

# Each outcome kind: the flags one named line carries and the flags given once.
KINDS = {
    "option": (
        lambda letter, shown: ["--option", letter, "--card-hash", shown],
        lambda via: ["--via", via],
    ),
    "other": (
        lambda letter, shown: ["--card-hash", shown],
        lambda via: [f"--other={ANSWER}", "--via", via],
    ),
    "unclear": (lambda letter, shown: ["--card-hash", shown], lambda via: ["--unclear"]),
    "unclear-note": (
        lambda letter, shown: ["--card-hash", shown],
        lambda via: ["--unclear", "--note", NOTE],
    ),
}


def lines_of(kind: str, *named: tuple[int, str, str], via: str = "chat") -> list[str]:
    """`--line` arguments for `named` (index, letter, hash), then the flags given once."""
    own, once = KINDS[kind]
    return [
        flag
        for index, letter, shown in named
        for flag in ("--line", str(index), *own(letter, shown))
    ] + once(via)


def stored(client: FakeForge, index: int) -> dict[str, object]:
    entries = body.block_expectation_dicts(body.locate_block(client.item_bodies[7]).data)
    return entries[index - 1]


@pytest.mark.usefixtures("github_clone")
class TestSeveralLinesInOneWrite:
    @pytest.mark.parametrize(
        ("kind", "letters", "via", "ruled", "text"),
        [
            pytest.param("option", "AB", "board", "AB", "lines 2 A, 3 B", id="option-board"),
            pytest.param("option", "AB", "chat", "AB", "lines 2 A, 3 B", id="option-chat"),
            pytest.param("option", "AA", "default", "AA", "lines 2 A, 3 A", id="option-default"),
            pytest.param(
                "other", "  ", "chat", ["other"] * 2, "lines 2 other, 3 other", id="other"
            ),
        ],
    )
    def test_ruled_lines_are_written_once_with_one_date(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        kind: str,
        letters: str,
        via: str,
        ruled: list[str],
        text: str,
    ) -> None:
        """Spec: RULE-29, RULE-30, RULE-31, RULE-14, RULE-19, RULE-20 -- own letters and
        hashes, one write, one day."""
        freeze_cli_now(monkeypatch)
        client = serve_item(monkeypatch, group_body())
        arguments = lines_of(kind, (2, letters[0], HASH_2), (3, letters[1], HASH_3), via=via)
        result = run_cli(["rule", "7", *arguments], capsys)
        assert (result.status, result.stdout) == (
            0,
            f"RULED #7 {text}; 1 line(s) still open\n",
        )
        entries = [stored(client, 2), stored(client, 3)]
        assert [
            (entry["ruling"], entry["card_hash"], entry["via"], str(entry["ruled_on"]))
            for entry in entries
        ] == [(ruled[0], HASH_2, via, TODAY), (ruled[1], HASH_3, via, TODAY)]
        assert len(client.body_writes) == 1
        checked = run_cli(["check", "-"], capsys, stdin=client.item_bodies[7])
        assert (checked.status, checked.stdout) == (0, "body ok\n")

    @pytest.mark.parametrize(
        ("kind", "letters", "via", "envelope"),
        [
            pytest.param(
                "option",
                "AB",
                via,
                {
                    "reason": "ruled",
                    "lines": [{"index": 2, "ruling": "A"}, {"index": 3, "ruling": "B"}],
                    "ruled_on": TODAY,
                    "open": 1,
                },
                id=f"option-{via}",
            )
            for via in ("board", "chat")
        ]
        + [
            pytest.param(
                "option",
                "AA",
                "default",
                {
                    "reason": "ruled",
                    "lines": [{"index": 2, "ruling": "A"}, {"index": 3, "ruling": "A"}],
                    "ruled_on": TODAY,
                    "open": 1,
                },
                id="option-default",
            ),
            pytest.param(
                "other",
                "  ",
                "chat",
                {
                    "reason": "ruled",
                    "lines": [{"index": 2, "ruling": "other"}, {"index": 3, "ruling": "other"}],
                    "ruled_on": TODAY,
                    "open": 1,
                },
                id="other",
            ),
            pytest.param(
                "unclear",
                "  ",
                "chat",
                {
                    "reason": "returned",
                    "lines": [{"index": 2}, {"index": 3}],
                    "returned_on": TODAY,
                    "open": 3,
                },
                id="unclear",
            ),
            pytest.param(
                "unclear-note",
                "  ",
                "chat",
                {
                    "reason": "returned",
                    "lines": [{"index": 2}, {"index": 3}],
                    "returned_on": TODAY,
                    "open": 3,
                },
                id="unclear-note",
            ),
        ],
    )
    def test_the_json_answer_lists_the_lines_under_one_date(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        kind: str,
        letters: str,
        via: str,
        envelope: dict[str, object],
    ) -> None:
        """Spec: RULE-32, E-RULE-14 -- `lines` replaces `index` and `ruling`, beside one date."""
        freeze_cli_now(monkeypatch)
        serve_item(monkeypatch, group_body())
        arguments = lines_of(kind, (2, letters[0], HASH_2), (3, letters[1], HASH_3), via=via)
        result = run_cli(["rule", "7", *arguments, "--json"], capsys)
        assert (result.status, json.loads(result.stdout)) == (
            0,
            {"ok": True, "item": 7, **envelope},
        )

    @pytest.mark.parametrize("note", [None, NOTE], ids=["no-note", "note"])
    def test_lines_are_sent_back_to_their_head_in_one_write(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], note: str | None
    ) -> None:
        """Spec: RULE-29, RULE-31, RULE-32, RULE-36, E-RULE-14 -- one note for every line."""
        freeze_cli_now(monkeypatch)
        client = serve_item(monkeypatch, group_body())
        arguments = lines_of("unclear", (2, "", HASH_2), (3, "", HASH_3))
        if note is not None:
            arguments += ["--note", note]
        sent = run_cli(["rule", "7", *arguments], capsys)
        assert (sent.status, sent.stdout) == (
            0,
            "RETURNED #7 lines 2, 3 to its head; 3 line(s) still open\n",
        )
        for index in (2, 3):
            entry = stored(client, index)
            assert (str(entry["returned_on"]), entry.get("returned_note")) == (TODAY, note)
        assert len(client.body_writes) == 1

    def test_a_returned_pair_is_then_ruled_with_the_one_text(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-36, RULE-25, E-RULE-14 -- the text goes to both and the head keys go."""
        freeze_cli_now(monkeypatch)
        client = serve_item(monkeypatch, group_body())
        sent = run_cli(
            ["rule", "7", *lines_of("unclear", (2, "", HASH_2), (3, "", HASH_3)), "--note", NOTE],
            capsys,
        )
        assert sent.status == 0
        ruled = run_cli(
            ["rule", "7", *lines_of("other", (2, "", HASH_2), (3, "", HASH_3)), "--json"], capsys
        )
        assert (ruled.status, json.loads(ruled.stdout)["lines"]) == (
            0,
            [{"index": 2, "ruling": "other"}, {"index": 3, "ruling": "other"}],
        )
        for index in (2, 3):
            entry = stored(client, index)
            assert (entry["other"], {"returned_on", "returned_note"} & set(entry)) == (
                ANSWER,
                set(),
            )

    def test_every_line_takes_the_first_date_when_the_clock_steps(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-29, RULE-32 -- one date per write, however often the clock is read."""
        reads: list[date] = []

        def stepping_today() -> date:
            reads.append(FROZEN_CLI_NOW.date() + timedelta(days=len(reads)))
            return reads[-1]

        client = serve_item(monkeypatch, group_body())
        monkeypatch.setattr(
            session,
            "run_context",
            lambda repo: session.RunContext(
                repo, build_forge=lambda _: client, today=stepping_today
            ),
        )
        arguments = lines_of("option", (2, "A", HASH_2), (3, "B", HASH_3))
        result = run_cli(["rule", "7", *arguments, "--json"], capsys)
        first_day = FROZEN_CLI_NOW.date().isoformat()
        assert (result.status, json.loads(result.stdout)["ruled_on"]) == (0, first_day)
        assert [str(stored(client, index)["ruled_on"]) for index in (2, 3)] == [first_day] * 2

    def test_a_failing_write_stores_neither_line(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-11, RULE-29 -- the forge's failure is `unavailable` and nothing is stored."""
        client = serve_item(monkeypatch, group_body())
        client.fail_update_item_body = True
        arguments = lines_of("option", (2, "A", HASH_2), (3, "B", HASH_3))
        result = run_cli(["rule", "7", *arguments, "--json"], capsys)
        assert (result.status, json.loads(result.stdout)["reason"]) == (2, "unavailable")
        assert client.body_writes == []

    def test_one_named_line_prints_and_writes_alike_in_any_flag_order(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-30, RULE-01 -- with one `--line` the flags may stand anywhere."""
        freeze_cli_now(monkeypatch)
        runs: list[tuple[CliRun, str]] = []
        for arguments in (
            ["--line", "2", "--option", "A", "--via", "chat", "--card-hash", HASH_2],
            ["--option", "A", "--via", "chat", "--card-hash", HASH_2, "--line", "2"],
        ):
            client = serve_item(monkeypatch, group_body())
            runs.append((run_cli(["rule", "7", *arguments], capsys), client.item_bodies[7]))
        assert runs[0][0].stdout == "RULED #7 line 2 A; 2 line(s) still open\n"
        assert (runs[1][0].status, runs[1][0].stdout, runs[1][1]) == (
            runs[0][0].status,
            runs[0][0].stdout,
            runs[0][1],
        )


@pytest.mark.usefixtures("github_clone")
class TestRefusedBeforeAnyForgeCall:
    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            pytest.param(
                [
                    *("--line", "2", "--card-hash", HASH_2),
                    *("--line", "3", "--option", "B", "--card-hash", HASH_3, "--option", "A"),
                    *("--via", "chat"),
                ],
                "line 3 has a second --option",
                id="RULE-34-mispair",
            ),
            pytest.param(
                [
                    *("--option", "A", "--line", "2", "--card-hash", HASH_2),
                    *("--line", "3", "--option", "B", "--card-hash", HASH_3, "--via", "chat"),
                ],
                "--option before the first --line belongs to no line",
                id="RULE-34-option-before-the-first-line",
            ),
            pytest.param(
                [
                    *("--card-hash", HASH_2, "--line", "2", "--option", "A"),
                    *("--line", "3", "--option", "B", "--card-hash", HASH_3, "--via", "chat"),
                ],
                "--card-hash before the first --line belongs to no line",
                id="RULE-34-card-hash-before-the-first-line",
            ),
            pytest.param(
                ["--line", "2", "--option", "A", "--option", "B", "--card-hash", HASH_2],
                "line 2 has a second --option",
                id="RULE-34-one-line-option",
            ),
            pytest.param(
                [
                    *("--line", "2", "--option", "A", "--card-hash", HASH_2),
                    *("--card-hash", HASH_2, "--via", "chat"),
                ],
                "line 2 has a second --card-hash",
                id="RULE-34-one-line-card-hash",
            ),
            pytest.param(
                [
                    *("--line", "2", "--option", "A", "--card-hash", HASH_2),
                    *("--line", "2", "--option", "B", "--card-hash", HASH_2, "--via", "chat"),
                ],
                "line 2 is named twice",
                id="RULE-33",
            ),
            pytest.param(
                [
                    *("--line", "2", "--option", "A", "--card-hash", HASH_2),
                    *("--line", "3", "--card-hash", HASH_3, "--via", "chat"),
                ],
                "line 3 needs its own --option after it",
                id="RULE-15-option-missing-on-the-second-line",
            ),
            pytest.param(
                [
                    *("--line", "2", "--card-hash", HASH_2, "--line", "3"),
                    *("--option", "B", "--card-hash", HASH_3, "--via", "chat"),
                ],
                "line 2 needs its own --option after it",
                id="RULE-15-option-missing-on-the-first-line",
            ),
            pytest.param(
                [
                    *("--line", "2", "--option", "A", "--card-hash", HASH_2),
                    *("--line", "3", "--option", "B", "--via", "chat"),
                ],
                "line 3 needs its own --card-hash after it",
                id="RULE-15-card-hash-missing-on-the-second-line",
            ),
            pytest.param(
                [
                    *("--line", "2", "--option", "A", "--line", "3"),
                    *("--card-hash", HASH_3, "--via", "chat"),
                ],
                "line 2 needs its own --card-hash after it",
                id="RULE-15-judged-line-by-line-not-flag-by-flag",
            ),
            pytest.param(
                ["--line", "2", "--unclear", "--line", "3", "--card-hash", HASH_3],
                "line 2 needs its own --card-hash after it",
                id="RULE-15-card-hash-missing-with-unclear",
            ),
            pytest.param(
                [
                    *("--line", "2", "--other", "Nur am Desktop.", "--card-hash", HASH_2),
                    *("--line", "3", "--other", "Nie.", "--card-hash", HASH_3, "--via", "chat"),
                ],
                NOT_GIVEN_TWICE.format(flag="--other"),
                id="RULE-35-per-line-other",
            ),
            pytest.param(
                [
                    *lines_of("unclear", (2, "", HASH_2), (3, "", HASH_3)),
                    *("--note", "Eins", "--note", "Zwei"),
                ],
                NOT_GIVEN_TWICE.format(flag="--note"),
                id="RULE-35-note",
            ),
            pytest.param(
                [
                    *lines_of("option", (2, "A", HASH_2), (3, "B", HASH_3)),
                    *("--via", "board"),
                ],
                NOT_GIVEN_TWICE.format(flag="--via"),
                id="RULE-35-via",
            ),
            pytest.param(
                [*lines_of("option", (2, "A", HASH_2)), "--via", "board"],
                NOT_GIVEN_TWICE.format(flag="--via"),
                id="RULE-35-via-one-line",
            ),
            pytest.param(
                [*lines_of("other", (2, "", HASH_2)), "--other", "Nie."],
                NOT_GIVEN_TWICE.format(flag="--other"),
                id="RULE-35-other-one-line",
            ),
            pytest.param(
                [
                    *("--line", "2", "--unclear", "--card-hash", HASH_2, "--note", "Eins"),
                    *("--note", "Zwei"),
                ],
                NOT_GIVEN_TWICE.format(flag="--note"),
                id="RULE-35-note-one-line",
            ),
            pytest.param(
                [
                    *("--line", "2", "--option", "A", "--card-hash", HASH_2),
                    *("--line", "2", "--option", "B", "--card-hash", HASH_2),
                    *("--via", "chat", "--via", "board"),
                ],
                NOT_GIVEN_TWICE.format(flag="--via"),
                id="RULE-35-before-RULE-33",
            ),
        ],
    )
    def test_an_ambiguous_flag_record_refuses(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        arguments: list[str],
        message: str,
    ) -> None:
        """Spec: RULE-15, RULE-33, RULE-34, RULE-35, RULE-09 -- invalid usage before the forge."""
        if "--via" not in arguments and "--unclear" not in arguments:
            arguments = [*arguments, "--via", "chat"]
        raw = group_body()
        client = serve_item(monkeypatch, raw)
        command = ["rule", "7", *arguments]
        text = run_cli(command, capsys)
        wire = run_cli([*command, "--json"], capsys)
        assert (text.status, text.stderr) == (2, f"ERROR: {message}\n")
        assert (wire.status, json.loads(wire.stdout)) == (
            2,
            {"ok": False, "reason": "invalid_usage", "message": message},
        )
        assert (client.issue_reference_lookups, client.body_writes) == ([], [])


def refusal_call(
    kind: str, shown: str, letter: str, via: str, refused: int, position: str
) -> list[str]:
    """The call naming the good line 2 and the `refused` line, the refused one in `position`."""
    named = [(2, "A", GOLDEN_CARD_HASH), (refused, letter, shown)]
    return lines_of(kind, *(named[::-1] if position == "first" else named), via=via)


@pytest.mark.usefixtures("github_clone")
class TestOneRefusedLineStoresNone:
    @pytest.mark.parametrize(
        ("kind", "third", "shown", "letter", "via", "message", "reason", "refused"),
        [
            pytest.param(
                "option",
                ruled_card(),
                GOLDEN_CARD_HASH,
                "A",
                "chat",
                "line 3 is already ruled; a changed ruling is a new line",
                "already_ruled",
                3,
                id="RULE-04-option",
            ),
            pytest.param(
                "other",
                other_card(),
                GOLDEN_CARD_HASH,
                "",
                "chat",
                "line 3 is already ruled; a changed ruling is a new line",
                "already_ruled",
                3,
                id="RULE-04-other",
            ),
            pytest.param(
                "unclear",
                ruled_card(),
                GOLDEN_CARD_HASH,
                "",
                "chat",
                "line 3 is already ruled; a changed ruling is a new line",
                "already_ruled",
                3,
                id="RULE-04-unclear",
            ),
            pytest.param(
                "option",
                card(),
                STALE_CARD_HASH,
                "A",
                "board",
                "line 3 changed since its card was shown; show it again and rule what it shows now",
                "card_changed",
                3,
                id="RULE-17-option",
            ),
            pytest.param(
                "other",
                card(),
                STALE_CARD_HASH,
                "",
                "board",
                "line 3 changed since its card was shown; show it again and rule what it shows now",
                "card_changed",
                3,
                id="RULE-17-other",
            ),
            pytest.param(
                "unclear",
                card(),
                STALE_CARD_HASH,
                "",
                "chat",
                "line 3 changed since its card was shown; show it again and rule what it shows now",
                "card_changed",
                3,
                id="RULE-17-unclear",
            ),
            pytest.param(
                "option",
                card(),
                GOLDEN_CARD_HASH,
                "C",
                "chat",
                "line 3 has no option C; its options are A, B",
                "invalid_usage",
                3,
                id="RULE-18",
            ),
            pytest.param(
                "option",
                card(),
                GOLDEN_CARD_HASH,
                "B",
                "default",
                "--via default keeps only the recommended option A, not B",
                "invalid_usage",
                3,
                id="RULE-19",
            ),
            pytest.param(
                "unclear",
                returned_today(),
                GOLDEN_CARD_HASH,
                "",
                "chat",
                "line 3 is already with its head; it comes back once revised",
                "with_head",
                3,
                id="RULE-24",
            ),
            pytest.param(
                "unclear-note",
                returned_today(),
                GOLDEN_CARD_HASH,
                "",
                "chat",
                "line 3 is already with its head; it comes back once revised",
                "with_head",
                3,
                id="RULE-24-note",
            ),
            pytest.param(
                "option",
                returned_today(),
                GOLDEN_CARD_HASH,
                "A",
                "default",
                "line 3 was answered Unclear; --via default records no answer",
                "with_head",
                3,
                id="RULE-27",
            ),
            pytest.param(
                "option",
                card(),
                GOLDEN_CARD_HASH,
                "A",
                "chat",
                "line 4 out of range: this item has 3 expectation line(s)",
                "line_out_of_range",
                4,
                id="RULE-05-option",
            ),
            pytest.param(
                "other",
                card(),
                GOLDEN_CARD_HASH,
                "A",
                "chat",
                "line 4 out of range: this item has 3 expectation line(s)",
                "line_out_of_range",
                4,
                id="RULE-05-other",
            ),
            pytest.param(
                "unclear",
                card(),
                GOLDEN_CARD_HASH,
                "A",
                "chat",
                "line 4 out of range: this item has 3 expectation line(s)",
                "line_out_of_range",
                4,
                id="RULE-05-unclear",
            ),
            pytest.param(
                "option",
                card(),
                GOLDEN_CARD_HASH,
                "A",
                "chat",
                "line 1 is a yes/no line; --option rules only an option line",
                "invalid_usage",
                1,
                id="RULE-16-option",
            ),
            pytest.param(
                "other",
                card(),
                GOLDEN_CARD_HASH,
                "A",
                "chat",
                "line 1 is a yes/no line; --other rules only an option line",
                "invalid_usage",
                1,
                id="RULE-16-other",
            ),
            pytest.param(
                "unclear",
                card(),
                GOLDEN_CARD_HASH,
                "A",
                "chat",
                "line 1 is a yes/no line; --unclear returns only an option line",
                "invalid_usage",
                1,
                id="RULE-16-unclear",
            ),
        ],
    )
    @pytest.mark.parametrize("position", ["first", "second"])
    def test_no_line_is_stored_when_one_named_line_is_refused(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        kind: str,
        third: str,
        shown: str,
        letter: str,
        via: str,
        message: str,
        reason: str,
        refused: int,
        position: str,
    ) -> None:
        """Spec: RULE-29, RULE-04..05, RULE-16..19, RULE-24, RULE-27, RULE-09 -- all or nothing."""
        client = serve_item(monkeypatch, group_body(third))
        arguments = refusal_call(kind, shown, letter, via, refused, position)
        assert_refusal_writes_nothing(client, capsys, arguments, message, reason)
