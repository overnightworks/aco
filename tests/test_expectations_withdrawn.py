"""Every reader of a withdrawn expectation line: `aco rulings` lists it and never
counts it open, `aco rule` refuses it, `aco next` and `aco board --json` never
read it as unruled or as a ruling (RUL-22, RUL-23, RULE-37, NEXT-48)."""

from __future__ import annotations

import json

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body, board_issue
from cli_fixtures import run_cli
from github_fixtures import FakeForge, serve_forge
from option_cards import (
    GOLDEN_CARD_HASH,
    YES_NO_LINE,
    assert_refusal_writes_nothing,
    card,
    card_body,
    decide,
    other_arguments,
    returned_card,
    ruled_card,
    serve_item,
    unclear,
)
from store_fixtures import decoded_item_record

from aco import body, expectations, rulings, state_board
from aco.board import ports

WITHDRAWN_TEXT = "Soll der Song offen bleiben?"


def withdrawn(text: str = WITHDRAWN_TEXT, day: str = "2026-10-29") -> str:
    return f"[[expectation]]\ntext = {json.dumps(text)}\nwithdrawn_on = {day}\n"


def lines_body(*lines: str) -> str:
    """A body whose block carries `lines` in order."""
    return card_body(lines[-1], before="".join("\n" + line for line in lines[:-1]))


def serve_board(monkeypatch: pytest.MonkeyPatch, *bodies: tuple[int, str]) -> None:
    issues = tuple(board_issue(number, f"Item {number}", raw) for number, raw in bodies)
    serve_forge(monkeypatch, FakeForge(board_issues=issues))


@pytest.mark.usefixtures("github_world")
class TestRulingsReadsAWithdrawnLine:
    def test_text_lists_it_in_the_total_and_never_as_open(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RUL-01, RUL-22 -- open, returned, ruled and withdrawn on one item."""
        raw = lines_body(card(), returned_card(), ruled_card(), withdrawn())
        serve_board(monkeypatch, (7, raw))
        result = run_cli(["rulings"], capsys)
        assert (result.status, result.stdout.splitlines()[0]) == (0, "#7 2/4: Item 7")
        assert result.stdout.splitlines()[4] == f"  4 withdrawn 2026-10-29: {WITHDRAWN_TEXT}"

    def test_its_text_is_capped_and_escaped(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RUL-22, RUL-02, RUL-11."""
        right_to_left_override = chr(0x202E)
        serve_board(monkeypatch, (7, lines_body(withdrawn(right_to_left_override + "x" * 120))))
        line = run_cli(["rulings"], capsys).stdout.splitlines()[1]
        assert line == "  1 withdrawn 2026-10-29: \\u202e" + "x" * 98 + "…"

    def test_items_of_ruled_or_withdrawn_lines_sit_in_the_fully_ruled_group(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RUL-03, RUL-04 -- a dated open line first, then by descending number."""
        serve_board(
            monkeypatch,
            (5, lines_body(withdrawn())),
            (6, lines_body(withdrawn(), card())),
            (9, lines_body(YES_NO_LINE, withdrawn())),
        )
        headers = [
            line for line in run_cli(["rulings"], capsys).stdout.splitlines() if line[0] == "#"
        ]
        assert headers == ["#6 1/2: Item 6", "#9 0/2: Item 9", "#5 0/1: Item 5"]

    def test_json_carries_exactly_index_form_text_and_withdrawn_on(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RUL-23 -- no `ruling` key, so no reader takes it for an open line."""
        serve_board(monkeypatch, (7, lines_body(withdrawn(), card())))
        row = json.loads(run_cli(["rulings", "--json"], capsys).stdout)["rulings"][0]
        assert (row["open"], row["total"], row["lines"][0]) == (
            1,
            2,
            {
                "index": 1,
                "form": "withdrawn",
                "text": WITHDRAWN_TEXT,
                "withdrawn_on": "2026-10-29",
            },
        )


def test_the_form_rulings_names_is_the_one_the_board_skips() -> None:
    """Spec: RUL-23, ABRD-60 -- the board's reader and `rulings`' writer of the form agree."""
    line = expectations.expectation_lines(lines_body(withdrawn()))[0]
    assert rulings.line_json(line)["form"] == ports.WITHDRAWN_FORM


REFUSED = "line 1 was withdrawn by its head"


@pytest.mark.usefixtures("github_world")
class TestRuleRefusesAWithdrawnLine:
    @pytest.mark.parametrize(
        "arguments",
        [
            pytest.param(decide("A", "chat", line=1), id="option"),
            pytest.param(other_arguments("Anders.", line=1), id="other"),
            pytest.param(unclear(line=1), id="unclear"),
        ],
    )
    def test_each_outcome_is_refused_before_any_write(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        arguments: list[str],
    ) -> None:
        """Spec: RULE-37, RULE-09 -- `card_changed`: read again and find the line gone."""
        client = serve_item(monkeypatch, lines_body(withdrawn(), card()))
        assert_refusal_writes_nothing(client, capsys, arguments, REFUSED, "card_changed")

    def test_a_withdrawn_line_among_several_refuses_them_all(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-37, RULE-29."""
        client = serve_item(monkeypatch, lines_body(card(), withdrawn("Zweite.")))
        arguments = [
            *decide("A", "chat", line=1),
            *["--line", "2", "--option", "A", "--card-hash", GOLDEN_CARD_HASH],
        ]
        message = "line 2 was withdrawn by its head"
        assert_refusal_writes_nothing(client, capsys, arguments, message, "card_changed")

    def test_the_range_counts_withdrawn_lines(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-05 -- a withdrawn line keeps its index, so it counts."""
        client = serve_item(monkeypatch, lines_body(card(), withdrawn(), card()))
        message = "line 4 out of range: this item has 3 expectation line(s)"
        arguments = decide("A", "chat", line=4)
        assert_refusal_writes_nothing(client, capsys, arguments, message, "line_out_of_range")

    def test_ruling_a_neighbour_keeps_the_tombstone_and_leaves_it_out_of_the_open_count(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RULE-01, BODY-88 -- the tombstone's bytes survive the rewrite."""
        client = serve_item(monkeypatch, lines_body(withdrawn(), card(), card()))
        result = run_cli(["rule", "7", *decide("A", "chat")], capsys)
        assert (result.status, result.stdout) == (0, "RULED #7 line 2 A; 1 line(s) still open\n")
        assert withdrawn() in client.item_bodies[7]


def test_the_state_ref_record_write_keeps_the_tombstone() -> None:
    """Spec: BODY-88, BODY-104 -- the store's `[record]` rewrite under `state-ref`."""
    raw = block_body((MINIMAL_BLOCK_TOML + "\n" + withdrawn() + "\n" + card()).rstrip("\n"))
    written = state_board._with_record(raw, decoded_item_record())
    lines = expectations.expectation_lines(written, storage=body.Storage.STATE_REF)
    assert withdrawn() in written
    assert [line.form for line in lines] == [
        expectations.LineForm.WITHDRAWN,
        expectations.LineForm.OPTIONS,
    ]


@pytest.mark.usefixtures("github_world")
class TestNextAndBoardNeverReadItAsOpenOrRuled:
    @pytest.mark.parametrize(
        ("lines", "state", "progress", "hint"),
        [
            pytest.param(
                (card(), withdrawn()),
                "proposed",
                {"open": 1, "total": 2},
                "expectations unruled: refine before the pull",
                id="open-and-withdrawn",
            ),
            pytest.param(
                (withdrawn(), withdrawn("Zweite.")),
                "ruled",
                {"open": 0, "total": 2},
                None,
                id="only-withdrawn",
            ),
        ],
    )
    def test_a_withdrawn_line_counts_in_the_total_and_never_as_open(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        lines: tuple[str, ...],
        state: str,
        progress: dict[str, int],
        hint: str | None,
    ) -> None:
        """Spec: NEXT-48, NEXT-04, NEXT-11 -- only withdrawn lines add neither hint."""
        serve_board(monkeypatch, (7, lines_body(*lines)))
        shown = json.loads(run_cli(["board", "--json"], capsys).expect_success())["items"][0]
        pulled = json.loads(run_cli(["next", "--json"], capsys).expect_success())
        assert (shown["expectation_state"], shown["expectation_progress"]) == (state, progress)
        assert (pulled.get("ruling_hint"), pulled["ruling_landings"], pulled["ruling_old"]) == (
            hint,
            None,
            None,
        )

    def test_a_withdrawn_line_never_dates_the_ruling(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-48 -- beside a ruled line, the age is the ruled line's alone: a
        withdrawal older than every trunk commit leaves a ruling newer than all of them."""
        ruled_after_every_commit = (
            '[[expectation]]\ntext = "Alt"\nruling = "no"\nruled_on = 2099-12-31\n'
        )
        serve_board(
            monkeypatch,
            (7, lines_body(ruled_after_every_commit)),
            (8, lines_body(ruled_after_every_commit, withdrawn(day="2000-01-01"))),
        )
        shown = json.loads(run_cli(["board", "--json"], capsys).expect_success())["items"]
        ages = {item["number"]: item["ruling_landings"] for item in shown}
        assert ages[8] == ages[7]
        assert ages[7] is not None
