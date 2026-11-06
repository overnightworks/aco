"""Pictures on an option card are optional (BODY-72, BODY-80, BODY-107, RUL-06,
RUL-10): the checker accepts a card without them, `rulings --json` names none,
and a caption still needs a picture beside it."""

from __future__ import annotations

import json

import pytest
from board_fixtures import board_issue
from cli_fixtures import run_cli
from github_fixtures import FakeForge, serve_forge
from option_cards import (
    E,
    card,
    card_body,
    card_head,
    card_option_a,
    card_option_b,
    check_defects,
    malformed,
    pictureless,
    pictureless_card,
)


@pytest.mark.usefixtures("clone")
class TestPicturelessCardCheck:
    def test_a_card_without_any_picture_is_ok(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: BODY-72, BODY-85 -- no line picture, no caption, an option with no result."""
        result = run_cli(["check", "-"], capsys, stdin=card_body(pictureless_card()))
        assert (result.status, result.stdout, result.stderr) == (0, "body ok\n", "")

    def test_a_line_caption_without_a_line_picture_is_refused(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-107 -- the line's caption needs a picture beside it."""
        head = pictureless(card_head()) + 'caption = "Heute"\n'
        status, defects = check_defects(capsys, card_body(card(head)))
        assert (status, defects) == (
            2,
            [malformed(f"{E}.caption", f"{E}.caption needs a picture beside it")],
        )

    def test_an_option_caption_without_a_picture_is_refused(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: BODY-80 -- an option with only a caption has no picture beside it."""
        option = card_option_b(("notice = ", 'caption = "C"\nnotice = '))
        option = option.replace("same_as_today = true\n", "")
        status, defects = check_defects(capsys, card_body(card(None, card_option_a(), option)))
        assert (status, defects) == (
            2,
            [
                malformed(
                    f"{E}.option[1].caption", f"{E}.option[1].caption needs a picture beside it"
                )
            ],
        )


@pytest.mark.usefixtures("github_world")
class TestPicturelessCardRulings:
    def test_rulings_json_names_no_picture_and_the_card_still_rules(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: RUL-06, RUL-10, BODY-89 -- absent picture keys add no key, the hash rules."""
        line_text = pictureless_card()
        serve_forge(
            monkeypatch,
            FakeForge(board_issues=(board_issue(7, "Karte", card_body(line_text)),)),
        )
        line = json.loads(run_cli(["rulings", "--json"], capsys).stdout)["rulings"][0]["lines"][0]
        assert {"picture", "caption"}.isdisjoint(line)
        assert [{"picture", "caption", "same_as_today"} & set(o) for o in line["options"]] == [
            set(),
            set(),
        ]
        ruled = line_text.replace(
            "question = ",
            f'ruling = "B"\nruled_on = 2026-10-28\ncard_hash = "{line["card_hash"]}"\n'
            'via = "default"\nquestion = ',
            1,
        )
        result = run_cli(["check", "-"], capsys, stdin=card_body(ruled))
        assert (result.status, result.stdout) == (0, "body ok\n")
