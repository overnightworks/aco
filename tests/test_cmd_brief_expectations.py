"""`aco brief` prints each ruled option line as its binding sentence (BRIEF-29 to BRIEF-31)."""

import json
import tomllib

import pytest
from board_fixtures import REPOSITORY
from cli_fixtures import run_cli
from option_cards import (
    OTHER_ANSWER,
    RETURNED_NOTE,
    RETURNED_ON,
    YES_NO_LINE,
    card,
    item_body,
    other_card,
    returned_card,
    ruled_card,
    serve_item,
)

CHOSEN_OPTIONS = {
    "A": (
        "Song bleibt offen",
        "Ein normaler Klick oder Enter auf den Ursprungs-Link öffnet die Version "
        "in der App; der Song bleibt geöffnet.",
    ),
    "B": ("Bleibt wie heute", "Der Ursprungs-Link bleibt ein normaler Browser-Sprung."),
}
QUESTION = 'question = "Soll dein Song beim Sprung zum Ursprungs-Take offen bleiben?"\n'
LINE_TEXT = (
    'text = "Ein Klick auf den Ursprungs-Link springt in der App: die Version klappt auf, '
    'der Take ist markiert, der Song bleibt offen."\n'
)


def brief_stdout(capsys: pytest.CaptureFixture[str], *flags: str) -> str:
    result = run_cli(["--repo", REPOSITORY, "brief", "7", *flags], capsys)
    assert (result.status, result.stderr) == (0, "")
    return result.stdout


@pytest.mark.parametrize("via", ["board", "chat", "default"])
@pytest.mark.parametrize("letter", ["A", "B"])
def test_brief_prints_a_ruled_line_as_its_question_chosen_option_and_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    via: str,
    letter: str,
    github_clone: object,
) -> None:
    serve_item(
        monkeypatch,
        item_body(
            ruled_card(
                ('via = "board"', f'via = "{via}"'), ('ruling = "A"', f'ruling = "{letter}"')
            )
        ),
    )
    name, contract = CHOSEN_OPTIONS[letter]

    stdout = brief_stdout(capsys)

    assert (
        "[[expectation]]\n"
        + LINE_TEXT
        + f'ruling = "{letter}"\nruled_on = 2026-10-28\n'
        + f'via = "{via}"\n'
        + QUESTION
        + "\n[[expectation.option]]\n"
        + f'name = "{name}"\ncontract = "{contract}"\n'
        + "```\n"
    ) in stdout


def test_brief_prints_a_line_ruled_other_as_his_answer_without_options(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], github_clone: object
) -> None:
    serve_item(monkeypatch, item_body(other_card()))

    stdout = brief_stdout(capsys)

    assert (
        "[[expectation]]\n"
        + LINE_TEXT
        + 'ruling = "other"\nruled_on = 2026-10-28\nvia = "chat"\n'
        + f'other = "{OTHER_ANSWER}"\n'
        + QUESTION
        + "```\n"
    ) in stdout
    assert "expectation.option" not in stdout


@pytest.mark.parametrize(("newline", "shown"), [("\n", "\n"), ("\r\n", "\\r\n")])
def test_brief_keeps_prose_around_the_block_verbatim(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    newline: str,
    shown: str,
    github_clone: object,
) -> None:
    serve_item(monkeypatch, item_body(ruled_card(), newline=newline))

    stdout = brief_stdout(capsys)

    assert stdout.startswith(f"Prose before.{shown}{shown}```aco{shown}")
    assert f"```{shown}{shown}Prose after.{shown}" in stdout


@pytest.mark.parametrize(
    "line",
    [
        card(),
        returned_card(RETURNED_ON + RETURNED_NOTE),
        '[[expectation]]\ntext = "Alt"\nwithdrawn_on = 2026-10-02\n',
    ],
    ids=["open", "returned", "withdrawn"],
)
def test_brief_prints_open_returned_and_withdrawn_lines_as_stored(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    line: str,
    github_clone: object,
) -> None:
    body = item_body(line)
    serve_item(monkeypatch, body)

    stdout = brief_stdout(capsys)

    assert stdout.startswith(body)


@pytest.mark.parametrize(
    "line",
    [
        card(),
        returned_card(RETURNED_ON + RETURNED_NOTE),
        '[[expectation]]\ntext = "Alt"\nwithdrawn_on = 2026-10-02\n',
    ],
    ids=["open", "returned", "withdrawn"],
)
def test_brief_prints_a_line_beside_a_ruled_one_in_full_and_in_order(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    line: str,
    github_clone: object,
) -> None:
    serve_item(monkeypatch, item_body(line, yes_no_line=ruled_card()))

    stdout = brief_stdout(capsys)

    block = stdout.split("```aco\n", 1)[1].split("\n```\n", 1)[0]
    entries = tomllib.loads(block)["expectation"]
    assert [entry["text"] for entry in entries] == [
        tomllib.loads(ruled_card())["expectation"][0]["text"],
        tomllib.loads(line)["expectation"][0]["text"],
    ]
    assert entries[0]["ruling"] == "A"
    assert entries[1] == tomllib.loads(line)["expectation"][0]


def test_brief_prints_a_yes_no_line_as_stored(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], github_clone: object
) -> None:
    serve_item(monkeypatch, item_body(card()))

    stdout = brief_stdout(capsys)

    assert YES_NO_LINE in stdout


def test_brief_prints_a_malformed_body_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], github_clone: object
) -> None:
    body = item_body(ruled_card(("ruled_on = 2026-10-28\n", 'ruled_on = "gestern"\n')))
    serve_item(monkeypatch, body)

    stdout = brief_stdout(capsys)

    assert stdout.startswith(body)


def test_brief_json_body_keeps_ruled_lines_as_stored(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], github_clone: object
) -> None:
    body = item_body(ruled_card())
    serve_item(monkeypatch, body)

    payload = json.loads(brief_stdout(capsys, "--json"))

    assert payload["body"] == body
