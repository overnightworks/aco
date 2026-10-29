"""Option lines through the real CLI: `check -` judges them, `rulings` reads
them, and the card hash pins the card the operator decided
(BODY-69..89, RUL-02/10/12..14)."""

from __future__ import annotations

import json

import pytest
from board_fixtures import board_issue
from cli_fixtures import run_cli
from github_fixtures import FakeForge, serve_forge
from option_cards import (
    GOLDEN_CARD_HASH,
    OTHER_ANSWER,
    RETURNED_NOTE,
    RETURNED_ON,
    RULED_KEYS,
    E,
    card,
    card_body,
    card_head,
    card_option_a,
    card_option_b,
    check_defects,
    malformed,
    other_card,
    other_decision,
    returned_card,
    ruled_card,
)


def open_card_with(decision: str) -> str:
    return card(card_head(("question = ", decision + "question = ")))


def ruled_with(keys: str) -> str:
    """The option line ruled `A`, `keys` placed where a returned line has them."""
    return ruled_card(("question = ", keys + "question = "))


PAD = "a" * 6000


@pytest.mark.usefixtures("clone")
class TestOptionLineCheck:
    @pytest.mark.parametrize(
        "line",
        [
            pytest.param(card(), id="open"),
            pytest.param(ruled_card(), id="ruled"),
            pytest.param(
                card(
                    card_head(
                        ('topic = "Sprung zum Ursprungs-Take"\n', ""),
                        ('picture = """', 'topic = "Sprung zum Ursprungs-Take"\npicture = """'),
                        ("question = ", RULED_KEYS + "question = "),
                    ),
                    card_option_a(
                        ('undo = "reversible"\n', ""), ("name = ", 'undo = "reversible"\nname = ')
                    ),
                    card_option_b(),
                ),
                id="ruled-reordered-keys",
            ),
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
    def test_a_complete_option_line_is_ok(
        self, capsys: pytest.CaptureFixture[str], line: str, newline: str
    ) -> None:
        """Spec: BODY-85, BODY-87, BODY-89, BODY-94 -- the stored hash survives key order and CRLF;
        a line with its head keeps the card editable."""
        result = run_cli(["check", "-"], capsys, stdin=card_body(line, newline=newline))
        assert (result.status, result.stdout, result.stderr) == (0, "body ok\n", "")

    @pytest.mark.parametrize(
        ("line", "defects"),
        [
            pytest.param(
                card_head() + 'option = "A"\n',
                [malformed(f"{E}.option", f"{E}.option must be an array of tables")],
                id="BODY-69",
            ),
            pytest.param(
                card(None, card_option_a()),
                [malformed(f"{E}.option", f"{E} must carry 2 to 4 options")],
                id="BODY-70-one",
            ),
            pytest.param(
                card(None, *(card_option_a(),) * 5),
                [malformed(f"{E}.option", f"{E} must carry 2 to 4 options")],
                id="BODY-70-five",
            ),
            pytest.param(
                card_head() + "option = [1, 2]\n",
                [
                    malformed(f"{E}.option[0]", f"{E}.option[0] must be a table"),
                    malformed(f"{E}.option[1]", f"{E}.option[1] must be a table"),
                ],
                id="BODY-71",
            ),
            pytest.param(
                card(card_head(('problem = "Klickst', 'nothing = "Klickst'))),
                [
                    malformed(f"{E}.problem", f"{E}.problem is required"),
                    malformed(f"{E}.nothing", f"unknown key {E}.nothing"),
                ],
                id="BODY-72-problem",
            ),
            pytest.param(
                card(card_head(("picture = ", "drawing = "))),
                [
                    malformed(f"{E}.picture", f"{E}.picture is required"),
                    malformed(f"{E}.drawing", f"unknown key {E}.drawing"),
                ],
                id="BODY-72-today-picture",
            ),
            pytest.param(
                card(None, card_option_a(), card_option_b(("contract = ", "promise = "))),
                [
                    malformed(f"{E}.option[1].contract", f"{E}.option[1].contract is required"),
                    malformed(f"{E}.option[1].promise", f"unknown key {E}.option[1].promise"),
                ],
                id="BODY-73",
            ),
            pytest.param(
                card(
                    card_head(('area = "Song-Seite"', 'area = " "')),
                    card_option_a(("cost = ", "cost = 1\nx = ")),
                    card_option_b(),
                ),
                [
                    malformed(f"{E}.area", f"{E}.area must be a non-empty string"),
                    malformed(
                        f"{E}.option[0].cost", f"{E}.option[0].cost must be a non-empty string"
                    ),
                    malformed(f"{E}.option[0].x", f"unknown key {E}.option[0].x"),
                ],
                id="BODY-74",
            ),
            pytest.param(
                card(card_head(('question = "Soll', f'question = "{"x" * 161}"\nq = "Soll'))),
                [
                    malformed(f"{E}.question", f"{E}.question must be at most 160 characters"),
                    malformed(f"{E}.q", f"unknown key {E}.q"),
                ],
                id="BODY-34-on-an-option-line",
            ),
            pytest.param(
                card(card_head(('"product"', '"kind"'))),
                [
                    malformed(
                        f"{E}.decision_kind",
                        f"{E}.decision_kind must be product, technical, data_risk, money, "
                        "access, wording, or release",
                    )
                ],
                id="BODY-75",
            ),
            pytest.param(
                card(None, card_option_a(('"reversible"', '"maybe"')), card_option_b()),
                [
                    malformed(
                        f"{E}.option[0].undo", f"{E}.option[0].undo must be reversible or final"
                    )
                ],
                id="BODY-76",
            ),
            pytest.param(
                card(card_head(('recommended = "A"', 'recommended = "C"'))),
                [malformed(f"{E}.recommended", f"{E}.recommended must be one of A, B")],
                id="BODY-77",
            ),
            pytest.param(
                ruled_card(('ruling = "A"', 'ruling = "C"')),
                [malformed(f"{E}.ruling", f"{E}.ruling must be one of A, B, or other")],
                id="BODY-78",
            ),
            pytest.param(
                ruled_card(("ruled_on = 2026-10-28", 'ruled_on = "2026-10-28"')),
                [malformed(f"{E}.ruled_on", f"{E}.ruled_on must be a TOML local date")],
                id="BODY-32-on-an-option-line",
            ),
            pytest.param(
                card(card_head(("question = ", 'default = "yes"\nexample = "E"\nquestion = '))),
                [
                    malformed(f"{E}.example", f"{E}.example does not belong on an option line"),
                    malformed(f"{E}.default", f"unknown key {E}.default"),
                ],
                id="BODY-79",
            ),
            pytest.param(
                card(
                    None,
                    card_option_a(),
                    card_option_b(
                        ("same_as_today = true", 'picture = "<svg/>"\nsame_as_today = true')
                    ),
                ),
                [
                    malformed(
                        f"{E}.option[1].same_as_today",
                        f"{E}.option[1] must carry exactly one of picture and same_as_today = true",
                    )
                ],
                id="BODY-80-both",
            ),
            pytest.param(
                card(None, card_option_a(), card_option_b(("same_as_today = true\n", ""))),
                [
                    malformed(
                        f"{E}.option[1].picture",
                        f"{E}.option[1] must carry exactly one of picture and same_as_today = true",
                    )
                ],
                id="BODY-80-neither",
            ),
            pytest.param(
                card(None, card_option_a(), card_option_b(("= true", "= false"))),
                [
                    malformed(
                        f"{E}.option[1].same_as_today", f"{E}.option[1].same_as_today must be true"
                    )
                ],
                id="BODY-80-not-true",
            ),
            pytest.param(
                card(
                    None, card_option_a(), card_option_b(("notice = ", 'caption = "C"\nnotice = '))
                ),
                [
                    malformed(
                        f"{E}.option[1].caption", f"{E}.option[1].caption needs a picture beside it"
                    )
                ],
                id="BODY-80-caption-without-picture",
            ),
            pytest.param(
                card(None, card_option_a(("<rect", "<script/><rect")), card_option_b()),
                [
                    malformed(
                        f"{E}.option[0].picture", f"{E}.option[0].picture must not contain <script>"
                    )
                ],
                id="BODY-81-option",
            ),
            pytest.param(
                card(card_head(('"""\n<svg', '"""\n<div><svg'))),
                [malformed(f"{E}.picture", f"{E}.picture must be inline SVG rooted at <svg>")],
                id="BODY-81-today",
            ),
            pytest.param(
                card(
                    card_head(("</svg>", f"{PAD}</svg>")),
                    card_option_a(("</svg>", f"{PAD}</svg>")),
                    card_option_b(("same_as_today = true", f'picture = "<svg>{PAD}</svg>"')),
                ),
                [malformed(E, f"{E} pictures must total at most 16384 bytes")],
                id="BODY-82",
            ),
            pytest.param(
                card(None, card_option_a(("name = ", 'letter = "A"\nname = ')), card_option_b()),
                [malformed(f"{E}.option[0].letter", f"unknown key {E}.option[0].letter")],
                id="BODY-84",
            ),
            pytest.param(
                card(card_head(("question = ", 'ruling = "A"\nquestion = '))),
                [malformed(f"{E}.ruled_on", f"{E} carries ruling without ruled_on")],
                id="BODY-86-ruling",
            ),
            pytest.param(
                card(
                    card_head(
                        (
                            "question = ",
                            f'ruling = "A"\ncard_hash = "{GOLDEN_CARD_HASH}"\nquestion = ',
                        )
                    )
                ),
                [malformed(f"{E}.ruled_on", f"{E} carries ruling without ruled_on")],
                id="BODY-86-ruling-card-hash",
            ),
            pytest.param(
                card(
                    card_head(("question = ", 'ruling = "A"\nruled_on = 2026-10-28\nquestion = '))
                ),
                [malformed(f"{E}.card_hash", f"{E} is ruled without card_hash")],
                id="BODY-86-ruling-ruled-on",
            ),
            pytest.param(
                card(card_head(("question = ", "ruled_on = 2026-10-28\nquestion = "))),
                [malformed(f"{E}.ruling", f"{E} carries ruled_on without ruling")],
                id="BODY-86-ruled-on",
            ),
            pytest.param(
                card(
                    card_head(
                        (
                            "question = ",
                            f'ruled_on = 2026-10-28\ncard_hash = "{GOLDEN_CARD_HASH}"\nquestion = ',
                        )
                    )
                ),
                [malformed(f"{E}.ruling", f"{E} carries ruled_on without ruling")],
                id="BODY-86-ruled-on-card-hash",
            ),
            pytest.param(
                card(card_head(("question = ", f'card_hash = "{GOLDEN_CARD_HASH}"\nquestion = '))),
                [malformed(f"{E}.ruling", f"{E} carries card_hash without ruling")],
                id="BODY-86-card-hash",
            ),
            pytest.param(
                ruled_card((GOLDEN_CARD_HASH, GOLDEN_CARD_HASH.upper())),
                [
                    malformed(
                        f"{E}.card_hash",
                        f"{E}.card_hash must be sha256: followed by 64 lowercase hex digits",
                    )
                ],
                id="BODY-86-card-hash-shape",
            ),
            pytest.param(
                ruled_card(('via = "board"\n', "")),
                [malformed(f"{E}.via", f"{E} is ruled without via")],
                id="BODY-86-ruled-without-via",
            ),
            pytest.param(
                card(card_head(("question = ", 'via = "chat"\nquestion = '))),
                [malformed(f"{E}.ruling", f"{E} carries via without ruling")],
                id="BODY-86-via",
            ),
            pytest.param(
                ruled_card(('ruling = "A"\nruled_on = 2026-10-28\n', "")),
                [malformed(f"{E}.ruling", f"{E} carries card_hash without ruling")],
                id="BODY-86-card-hash-via",
            ),
            pytest.param(
                ruled_card(('via = "board"', 'via = "phone"')),
                [malformed(f"{E}.via", f"{E}.via must be board, chat, or default")],
                id="BODY-90",
            ),
            pytest.param(
                ruled_card(('area = "Song-Seite"', 'area = "Song-Liste"')),
                [
                    malformed(
                        f"{E}.card_hash",
                        f"{E} was edited after its ruling; a changed ruling is a new line",
                    )
                ],
                id="BODY-87",
            ),
            pytest.param(
                ruled_card(
                    ('area = "Song-Seite"', 'area = "Song-Liste"'), ('"A"\nreason', '"C"\nreason')
                ),
                [malformed(f"{E}.recommended", f"{E}.recommended must be one of A, B")],
                id="BODY-87-only-without-another-defect",
            ),
            pytest.param(
                card(
                    card_head(
                        ("problem = ", 'ruling = "A"\nnote = "N"\nissue = '),
                    ),
                    card_option_a(("<rect", "<script/><rect")),
                    card_option_b(("undo = ", "undo = 1\nx = ")),
                ),
                [
                    malformed(f"{E}.ruled_on", f"{E} carries ruling without ruled_on"),
                    malformed(f"{E}.problem", f"{E}.problem is required"),
                    malformed(
                        f"{E}.option[1].undo", f"{E}.option[1].undo must be reversible or final"
                    ),
                    malformed(
                        f"{E}.option[0].picture", f"{E}.option[0].picture must not contain <script>"
                    ),
                    malformed(f"{E}.issue", f"unknown key {E}.issue"),
                    malformed(f"{E}.note", f"unknown key {E}.note"),
                    malformed(f"{E}.option[1].x", f"unknown key {E}.option[1].x"),
                ],
                id="order-within-one-entry",
            ),
            pytest.param(
                open_card_with(other_decision().replace(f'other = "{OTHER_ANSWER}"\n', "")),
                [malformed(f"{E}.other", f"{E}.other is required when ruling is other")],
                id="BODY-91-required-for-other",
            ),
            pytest.param(
                open_card_with(
                    other_decision()
                    .replace('ruling = "other"', 'ruling = "A"')
                    .replace(OTHER_ANSWER, "x")
                ),
                [malformed(f"{E}.other", f"{E}.other belongs only to a line ruled other")],
                id="BODY-91-refused-beside-a-letter",
            ),
            pytest.param(
                open_card_with('other = "x"\n'),
                [malformed(f"{E}.other", f"{E}.other belongs only to a line ruled other")],
                id="BODY-91-refused-on-an-open-line",
            ),
            pytest.param(
                open_card_with(other_decision().replace(OTHER_ANSWER, "  ")),
                [malformed(f"{E}.other", f"{E}.other must be a non-empty string")],
                id="BODY-91-non-empty",
            ),
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
    def test_a_defective_option_line_is_refused(
        self, capsys: pytest.CaptureFixture[str], line: str, defects: list[str]
    ) -> None:
        """Spec: BODY-69..BODY-84, BODY-86, BODY-87, BODY-90, BODY-91, BODY-93 -- one sentence per
        refusal, in entry order."""
        assert check_defects(capsys, card_body(line)) == (2, defects)

    @pytest.mark.parametrize(
        ("line", "defects"),
        [
            pytest.param(
                '[[expectation]]\ntext = "T"\nruling = "no"\nruled_on = 2026-10-01\nproblem = "P"\n'
                'card_hash = "H"\nvia = "chat"\n',
                [
                    malformed(
                        f"{E}.problem", f"{E}.problem belongs to an option line; this line has none"
                    ),
                    malformed(f"{E}.card_hash", f"unknown key {E}.card_hash"),
                    malformed(f"{E}.via", f"unknown key {E}.via"),
                ],
                id="BODY-83",
            ),
            pytest.param(
                '[[expectation]]\ntext = "T"\n',
                [malformed(E, f"{E} is an open yes/no line; write an option card")],
                id="BODY-29-yes-no-only",
            ),
            pytest.param(
                '[[expectation]]\ntext = "T"\ndefault = "yes"\n',
                [
                    malformed(E, f"{E} is an open yes/no line; write an option card"),
                    malformed(f"{E}.default", f"unknown key {E}.default"),
                ],
                id="BODY-29-open-with-default",
            ),
            pytest.param(
                '[[expectation]]\ntext = "T"\nruling = "no"\nruled_on = 2026-10-01\n'
                'default = "yes"\n',
                [malformed(f"{E}.default", f"unknown key {E}.default")],
                id="BODY-33-ruled-with-default",
            ),
            pytest.param(
                '[[expectation]]\ntext = "T"\nruling = "no"\n',
                [malformed(f"{E}.ruled_on", f"{E}.ruled_on must be a TOML local date")],
                id="BODY-32-ruling-alone",
            ),
            pytest.param(
                '[[expectation]]\ntext = "T"\nruled_on = 2026-10-01\n',
                [malformed(f"{E}.ruling", f"{E}.ruling must be yes, no, or later")],
                id="BODY-31-ruled-on-alone",
            ),
            pytest.param(
                '[[expectation]]\ntext = "T"\nruling = "no"\nruled_on = 2026-10-01\n'
                'question = "Q?"\nexample = "E"\n'
                'picture = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>"""\n',
                [],
                id="ruled-with-card-fields",
            ),
            pytest.param(
                '[[expectation]]\ntext = "T"\nruling = "later"\nruled_on = 2026-10-01\n',
                [],
                id="ruled-later",
            ),
        ],
    )
    def test_a_yes_no_line_keeps_its_own_grammar(
        self, capsys: pytest.CaptureFixture[str], line: str, defects: list[str]
    ) -> None:
        """Spec: BODY-29, BODY-31, BODY-32, BODY-33, BODY-83 -- an open yes/no line is refused;
        a ruled one stays readable history."""
        assert check_defects(capsys, card_body(line)) == (2 if defects else 0, defects)


def option_json(**card_values: object) -> dict[str, object]:
    return {
        "letter": "A",
        "name": "Song bleibt offen",
        "effect": "Die App springt selbst: v5 klappt auf, Take 7 ist markiert.",
        "picture": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 80">'
        '<style>.b{fill:#fff;stroke:#2a7}</style><rect class="b" x="1" y="1" width="198" '
        'height="78" rx="8"/></svg>',
        "caption": "Der Song bleibt offen.",
        "notice": "Du bleibst in deinem Song; Zurück führt zur Ansicht davor.",
        "cost": "Mehr Navigationscode, abgesichert durch Browserfälle.",
        "undo": "reversible",
        "undo_how": "jederzeit änderbar.",
        "contract": "Ein normaler Klick oder Enter auf den Ursprungs-Link öffnet die Version "
        "in der App; der Song bleibt geöffnet.",
        **card_values,
    }


@pytest.mark.usefixtures("github_world")
class TestOptionLineRulings:
    @pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
    def test_rulings_json_carries_every_card_field_and_the_card_hash(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], newline: str
    ) -> None:
        """Spec: RUL-10, RUL-12..RUL-15, BODY-89 -- a mixed item, the golden hash."""
        yes_no = '[[expectation]]\ntext = "Alt"\nruling = "no"\nruled_on = 2026-10-01\n'
        raw_body = card_body(card(), before="\n" + yes_no, newline=newline)
        serve_forge(monkeypatch, FakeForge(board_issues=(board_issue(7, "Karte", raw_body),)))
        result = run_cli(["rulings", "--json"], capsys)
        assert result.status == 0, result.stderr
        lines = json.loads(result.stdout)["rulings"][0]["lines"]
        assert lines[0] == {"index": 1, "text": "Alt", "ruling": "no", "ruled_on": "2026-10-01"}
        assert lines[1]["form"] == "options"
        assert lines[1] == {
            "index": 2,
            "form": "options",
            "text": "Ein Klick auf den Ursprungs-Link springt in der App: die Version klappt "
            "auf, der Take ist markiert, der Song bleibt offen.",
            "asked_on": "2026-10-28",
            "ruling": None,
            "ruled_on": None,
            "card_hash": GOLDEN_CARD_HASH,
            "stored_card_hash": None,
            "via": None,
            "other": None,
            "returned_on": None,
            "returned_note": None,
            "question": "Soll dein Song beim Sprung zum Ursprungs-Take offen bleiben?",
            "problem": "Klickst du den Link zum Ursprungs-Take, ist dein geöffneter Song weg.",
            "picture": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 80">'
            '<style>.b{fill:#fff;stroke:#555}</style><rect class="b" x="1" y="1" '
            'width="198" height="78" rx="8"/></svg>',
            "caption": "Der Browser springt selbst, dabei geht der Song verloren.",
            "decision_kind": "product",
            "area": "Song-Seite",
            "topic": "Sprung zum Ursprungs-Take",
            "recommended": "A",
            "reason": "Behebt den Verlust; Strg- und Mittelklick bleiben normale Links.",
            "options": [
                option_json(),
                {
                    "letter": "B",
                    "name": "Bleibt wie heute",
                    "effect": "Der Browser springt; der Song schließt sich.",
                    "same_as_today": True,
                    "notice": "Nach dem Klick wählst du den Song neu.",
                    "cost": "Keine.",
                    "undo": "reversible",
                    "undo_how": "es wird nichts gebaut.",
                    "contract": "Der Ursprungs-Link bleibt ein normaler Browser-Sprung.",
                },
            ],
        }

    def test_a_ruled_option_line_lists_its_letter_and_date(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RUL-02, RUL-12, RUL-15 -- text names the letter, `--json` the letter, stored
        hash and via."""
        raw_body = card_body(ruled_card())
        serve_forge(monkeypatch, FakeForge(board_issues=(board_issue(7, "Karte", raw_body),)))
        text = run_cli(["rulings"], capsys)
        assert text.stdout == (
            "#7 0/1: Karte\n  1 ruled A 2026-10-28: Ein Klick auf den Ursprungs-Link springt "
            "in der App: die Version klappt auf, der Take ist markiert,…\n"
        )
        line = json.loads(run_cli(["rulings", "--json"], capsys).stdout)["rulings"][0]["lines"][0]
        assert (
            line["ruling"],
            line["ruled_on"],
            line["card_hash"],
            line["stored_card_hash"],
            line["via"],
        ) == ("A", "2026-10-28", GOLDEN_CARD_HASH, GOLDEN_CARD_HASH, "board")

    def test_a_caption_less_option_hashes_without_the_caption(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-89 -- an absent covered key is left out, and its hash rules the card."""
        without_caption = card(
            None, card_option_a(('caption = "Der Song bleibt offen."\n', "")), card_option_b()
        )
        serve_forge(
            monkeypatch,
            FakeForge(board_issues=(board_issue(7, "Karte", card_body(without_caption)),)),
        )
        line = json.loads(run_cli(["rulings", "--json"], capsys).stdout)["rulings"][0]["lines"][0]
        assert "caption" not in line["options"][0]
        assert line["card_hash"] != GOLDEN_CARD_HASH
        ruled = without_caption.replace(
            "question = ",
            f'ruling = "B"\nruled_on = 2026-10-28\ncard_hash = "{line["card_hash"]}"\n'
            'via = "default"\nquestion = ',
            1,
        )
        result = run_cli(["check", "-"], capsys, stdin=card_body(ruled))
        assert (result.status, result.stdout) == (0, "body ok\n")
