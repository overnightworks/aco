"""Line 14's card rules: an open or returned option line breaking them is refused
by `aco check -` (BODY-95..BODY-100); a ruled line is exempt. The pattern table is
judged on the pure rules, the fields and the exemptions through the real CLI."""

from __future__ import annotations

import re
import tomllib

import pytest
from option_cards import (
    GOLDEN_CARD_HASH,
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
    returned_card,
)

from aco.card_rules import card_rule_defects
from aco.expectation_grammar import card_hash

ISSUE_NUMBER = "an issue number"
PATH = "a path"
FILE_NAME = "a file name"
BACKTICK = "a backtick"
SNAKE_CASE = "a snake case name"
CAMEL_CASE = "a camel case name"
FLAG = "a flag"


@pytest.mark.parametrize(
    ("text", "phrases"),
    [
        pytest.param("wie in #123", (ISSUE_NUMBER,), id="issue-reference"),
        pytest.param("siehe (#13).", (ISSUE_NUMBER,), id="issue-reference-in-brackets"),
        pytest.param("Wir schreiben in C#", (), id="c-sharp"),
        pytest.param("Punkt 3 und Nr. 3", (), id="numbers-without-hash"),
        pytest.param("docs/board/mockup.html", (PATH,), id="path-with-file-name"),
        pytest.param("./run", (PATH,), id="path-from-here"),
        pytest.param("~/Musik", (PATH,), id="path-from-home"),
        pytest.param("im Ordner /etc", (PATH,), id="absolute-path"),
        pytest.param("https://x.de", (PATH,), id="url"),
        pytest.param("Ja/Nein", (), id="two-alternatives"),
        pytest.param("A/B", (), id="two-letters"),
        pytest.param("A/B/C", (), id="three-letters"),
        pytest.param("Ja/Nein/Später", (), id="three-alternatives"),
        pytest.param("Ja / Nein", (), id="spaced-alternatives"),
        pytest.param("und/oder", (), id="and-or"),
        pytest.param("lies README.md.", (FILE_NAME,), id="readme"),
        pytest.param("in cmd.py", (FILE_NAME,), id="python-file"),
        pytest.param("(app.svelte)", (FILE_NAME,), id="file-in-brackets"),
        pytest.param("v5.2", (), id="version"),
        pytest.param("z. B. hallucinai.de", (), id="abbreviation-and-domain"),
        pytest.param("`aco rule`", (BACKTICK,), id="backtick"),
        pytest.param("„so“ und 'so'", (), id="quotes"),
        pytest.param("card_hash", (SNAKE_CASE,), id="snake-case"),
        pytest.param("same_as_today", (SNAKE_CASE,), id="snake-case-three-words"),
        pytest.param("cmd_rule.py", (FILE_NAME, SNAKE_CASE), id="snake-case-file"),
        pytest.param("E-Mail und Zwei-Wort", (), id="hyphens"),
        pytest.param("cardHash", (CAMEL_CASE,), id="camel-case"),
        pytest.param("isOptionLine", (CAMEL_CASE,), id="camel-case-three-words"),
        pytest.param(
            "iPhone eBay macOS YouTube GitHub JavaScript WhatsApp", (), id="product-names"
        ),
        pytest.param("mit --unclear", (FLAG,), id="flag-after-space"),
        pytest.param("--option", (FLAG,), id="flag-at-start"),
        pytest.param("A \u2013 B und Satz -- Satz", (), id="dashes"),
    ],
)
def test_a_text_is_refused_by_exactly_the_rules_it_breaks(
    text: str, phrases: tuple[str, ...]
) -> None:
    """Spec: BODY-96, BODY-100 -- every row of line 14's pattern table."""
    path = f"{E}.reason"
    assert card_rule_defects(E, {"reason": text}, ()) == [
        (path, f"{path} must not contain {phrase}") for phrase in phrases
    ]


@pytest.mark.parametrize(
    ("key", "text", "reason"),
    [
        pytest.param("problem", " ".join(["Wort"] * 20), None, id="twenty-words"),
        pytest.param(
            "problem", " ".join(["Wort"] * 21), "must be at most 20 words", id="twenty-one-words"
        ),
        pytest.param("name", "Ein", "must be 2 to 5 words", id="one-word-name"),
        pytest.param("name", "Zwei Wörter", None, id="two-word-name"),
        pytest.param("name", "Ein Name mit fünf Wörtern", None, id="five-word-name"),
        pytest.param(
            "name", "Ein Name mit sechs ganzen Wörtern", "must be 2 to 5 words", id="six-word-name"
        ),
        pytest.param("area", "Song-Seite", None, id="area"),
        pytest.param(
            "area", "Song-Seite ", "must be one line without spaces around it", id="area-trailing"
        ),
        pytest.param(
            "topic", " Sprung", "must be one line without spaces around it", id="topic-leading"
        ),
        pytest.param(
            "topic",
            "Sprung\nzum Take",
            "must be one line without spaces around it",
            id="topic-newline",
        ),
        pytest.param(
            "name",
            "Song bleibt\noffen",
            "must be one line without spaces around it",
            id="name-newline",
        ),
    ],
)
def test_a_length_or_line_rule_judges_its_own_field(
    key: str, text: str, reason: str | None
) -> None:
    """Spec: BODY-97, BODY-98, BODY-99 -- problem length, option name length, one-line fields."""
    options = [("option[0]", {key: text})] if key == "name" else []
    line = {} if key == "name" else {key: text}
    path = f"{E}.option[0].{key}" if key == "name" else f"{E}.{key}"
    assert card_rule_defects(E, line, options) == (
        [] if reason is None else [(path, f"{path} {reason}")]
    )


def with_value(piece: str, key: str, value: str) -> str:
    """`piece` with the one-line `key = "..."` set to `value`."""
    pattern = re.compile(rf"^{key} = .*$", re.MULTILINE)
    assert pattern.search(piece), key
    return pattern.sub(lambda _: f'{key} = "{value}"', piece, count=1)


def broken_card(key: str, value: str, *, where: str = "line", head_keys: str = "") -> str:
    """The open card with the line key or the first option's `key` set to `value`."""
    head = card_head(("question = ", head_keys + "question = "))
    if where == "line":
        return card(with_value(head, key, value))
    return card(head, with_value(card_option_a(), key, value), card_option_b())


LINE_FIELDS = ("question", "problem", "caption", "area", "topic", "reason")
OPTION_FIELDS = ("name", "effect", "caption", "notice", "cost", "undo_how")
BREACH = "wie in #13"


@pytest.mark.usefixtures("clone")
class TestCardRulesThroughCheck:
    @pytest.mark.parametrize(
        ("where", "key", "head_keys"),
        [
            *(("line", key, "") for key in LINE_FIELDS),
            *(("option", key, "") for key in OPTION_FIELDS),
            *(("line", key, RETURNED_ON + RETURNED_NOTE) for key in ("question", "reason")),
        ],
    )
    def test_every_checked_field_of_an_open_or_returned_line_is_judged(
        self, capsys: pytest.CaptureFixture[str], where: str, key: str, head_keys: str
    ) -> None:
        """Spec: BODY-95, BODY-96 -- the checked fields, open and with its head."""
        field = f"{E}.{key}" if where == "line" else f"{E}.option[0].{key}"
        line = broken_card(key, BREACH, where=where, head_keys=head_keys)
        assert check_defects(capsys, card_body(line)) == (
            2,
            [malformed(field, f"{field} must not contain an issue number")],
        )

    def test_a_long_problem_is_refused_with_its_own_sentence(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-97 -- 21 words."""
        line = broken_card("problem", " ".join(["Wort"] * 21))
        field = f"{E}.problem"
        assert check_defects(capsys, card_body(line)) == (
            2,
            [malformed(field, f"{field} must be at most 20 words")],
        )

    def test_a_one_word_option_name_is_refused_with_its_own_sentence(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-98 -- the name of an option."""
        line = broken_card("name", "Ein", where="option")
        field = f"{E}.option[0].name"
        assert check_defects(capsys, card_body(line)) == (
            2,
            [malformed(field, f"{field} must be 2 to 5 words")],
        )

    def test_the_contract_is_exempt(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: BODY-100 -- `contract` may name files, flags and code."""
        line = broken_card(
            "contract", "Der Aufruf `aco rule` --flag in cmd_rule.py", where="option"
        )
        assert check_defects(capsys, card_body(line)) == (0, [])

    def test_the_text_the_returned_note_and_the_pictures_are_exempt(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-100 -- `text`, `returned_note` and the SVG are not judged."""
        head = card_head(
            ("question = ", RETURNED_ON + f'returned_note = "{BREACH}"\n' + "question = "),
            ("Ein Klick", "Ein Klick auf `aco rule` in cmd_rule.py"),
            ("<style>", "<style>/* card_hash --flag */"),
        )
        assert check_defects(capsys, card_body(card(head))) == (0, [])

    def test_a_ruled_line_is_exempt(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: BODY-100 -- a ruled card keeps its words; its hash is of the card as written."""
        written = with_value(card_head(), "area", BREACH)
        entry = tomllib.loads(card(written))["expectation"][0]
        decision = RULED_KEYS.replace(GOLDEN_CARD_HASH, card_hash(entry))
        line = card(written.replace("question = ", decision + "question = ", 1))
        assert check_defects(capsys, card_body(line)) == (0, [])

    def test_ordinary_prose_with_alternatives_and_names_passes(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-100 -- the passing column of the table reads `body ok`."""
        line = broken_card(
            "reason", "Ja/Nein, A/B/C, und/oder; E-Mail, iPhone, GitHub, v5.2, z. B. „so“"
        )
        assert check_defects(capsys, card_body(line)) == (0, [])

    def test_a_card_breaking_several_rules_prints_each_in_field_order(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-95, BODY-96 -- one sentence per breach, after the shape refusals."""
        line = card(
            with_value(card_head(), "topic", "Sprung zum `aco rule`"),
            with_value(card_option_a(), "cost", "mit --unclear"),
            card_option_b(),
        )
        topic, cost = f"{E}.topic", f"{E}.option[0].cost"
        assert check_defects(capsys, card_body(line)) == (
            2,
            [
                malformed(topic, f"{topic} must not contain a backtick"),
                malformed(cost, f"{cost} must not contain a flag"),
            ],
        )

    def test_a_shape_defect_is_reported_before_the_card_rules(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-95 -- the card rules come after the unknown keys."""
        line = card(
            with_value(card_head(), "topic", BREACH).replace(
                "recommended", 'surprise = "x"\nrecommended', 1
            )
        )
        topic = f"{E}.topic"
        assert check_defects(capsys, card_body(line)) == (
            2,
            [
                malformed(f"{E}.surprise", f"unknown key {E}.surprise"),
                malformed(topic, f"{topic} must not contain an issue number"),
            ],
        )

    def test_a_returned_card_keeps_passing_after_a_revision(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-94, BODY-95 -- a revised, rule-keeping card stays ok."""
        assert check_defects(capsys, card_body(returned_card())) == (0, [])
