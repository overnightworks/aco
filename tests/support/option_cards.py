"""Option-card arrangement shared by the option-line, rewrite and `rule` test
modules: card bodies, rule arguments and the rewrite invariant."""

from __future__ import annotations

import json
import tomllib

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import FROZEN_CLI_NOW, run_cli
from github_fixtures import FakeForge, serve_forge

from aco import body, forge
from aco.expectations import OptionLine, expectation_lines

GOLDEN_CARD_HASH = "sha256:f7f1db4c507733e34c58d64de61fd482ad3d308db7ce3bf14bc503179c26519d"
RULED_KEYS = (
    f'ruling = "A"\nruled_on = 2026-10-28\ncard_hash = "{GOLDEN_CARD_HASH}"\nvia = "board"\n'
)


def card_head(*edits: tuple[str, str]) -> str:
    """The line keys of the open card the item body shows, `edits` applied."""
    head = (
        "[[expectation]]\n"
        'text = "Ein Klick auf den Ursprungs-Link springt in der App: die Version klappt auf, '
        'der Take ist markiert, der Song bleibt offen."\n'
        "asked_on = 2026-10-28\n"
        'question = "Soll dein Song beim Sprung zum Ursprungs-Take offen bleiben?"\n'
        'problem = "Klickst du den Link zum Ursprungs-Take, ist dein geöffneter Song weg."\n'
        'picture = """\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 80">'
        '<style>.b{fill:#fff;stroke:#555}</style><rect class="b" x="1" y="1" width="198" '
        'height="78" rx="8"/></svg>"""\n'
        'caption = "Der Browser springt selbst, dabei geht der Song verloren."\n'
        'decision_kind = "product"\n'
        'area = "Song-Seite"\n'
        'topic = "Sprung zum Ursprungs-Take"\n'
        'recommended = "A"\n'
        'reason = "Behebt den Verlust; Strg- und Mittelklick bleiben normale Links."\n'
    )
    return apply_edits(head, edits)


def card_option_a(*edits: tuple[str, str]) -> str:
    option = (
        "\n[[expectation.option]]\n"
        'name = "Song bleibt offen"\n'
        'effect = "Die App springt selbst: v5 klappt auf, Take 7 ist markiert."\n'
        'picture = """\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 80">'
        '<style>.b{fill:#fff;stroke:#2a7}</style><rect class="b" x="1" y="1" width="198" '
        'height="78" rx="8"/></svg>"""\n'
        'caption = "Der Song bleibt offen."\n'
        'notice = "Du bleibst in deinem Song; Zurück führt zur Ansicht davor."\n'
        'cost = "Mehr Navigationscode, abgesichert durch Browserfälle."\n'
        'undo = "reversible"\n'
        'undo_how = "jederzeit änderbar."\n'
        'contract = "Ein normaler Klick oder Enter auf den Ursprungs-Link öffnet die Version '
        'in der App; der Song bleibt geöffnet."\n'
    )
    return apply_edits(option, edits)


def card_option_b(*edits: tuple[str, str]) -> str:
    option = (
        "\n[[expectation.option]]\n"
        'name = "Bleibt wie heute"\n'
        'effect = "Der Browser springt; der Song schließt sich."\n'
        "same_as_today = true\n"
        'notice = "Nach dem Klick wählst du den Song neu."\n'
        'cost = "Keine."\n'
        'undo = "reversible"\n'
        'undo_how = "es wird nichts gebaut."\n'
        'contract = "Der Ursprungs-Link bleibt ein normaler Browser-Sprung."\n'
    )
    return apply_edits(option, edits)


def apply_edits(text: str, edits: tuple[tuple[str, str], ...]) -> str:
    for old, new in edits:
        assert old in text, old
        text = text.replace(old, new, 1)
    return text


def card(head: str | None = None, *options: str) -> str:
    """One option line: `head` and `options`, the open card by default."""
    return (card_head() if head is None else head) + "".join(
        options or (card_option_a(), card_option_b())
    )


def ruled_card(*edits: tuple[str, str]) -> str:
    """The card ruled `A` with the hash of the card shown, `edits` applied to its head."""
    return card(card_head(("question = ", RULED_KEYS + "question = "), *edits))


def open_option_entry() -> dict[str, object]:
    """The open option card as the `[[expectation]]` entry a block projection carries."""
    return tomllib.loads(card())["expectation"][0]


def card_body(line: str, *, before: str = "", newline: str = "\n") -> str:
    return block_body(MINIMAL_BLOCK_TOML + before + "\n" + line).replace("\n", newline)


def check_defects(capsys: pytest.CaptureFixture[str], raw_body: str) -> tuple[object, list[str]]:
    result = run_cli(["check", "-", "--json"], capsys, stdin=raw_body)
    return result.status, json.loads(result.stdout)["defects"]


def malformed(field: str, message: str) -> str:
    return f"body malformed: {field}: {message}"


E = "expectation[0]"
OTHER_ANSWER = "Nur auf dem Desktop offen lassen; auf dem Handy wie heute."


def other_decision(answer: str = OTHER_ANSWER) -> str:
    """The decided state of a card ruled `other` with the hash of the card shown."""
    return (
        f'ruling = "other"\nruled_on = 2026-10-28\ncard_hash = "{GOLDEN_CARD_HASH}"\n'
        f'via = "chat"\nother = "{answer}"\n'
    )


def open_card_with(decision: str) -> str:
    return card(card_head(("question = ", decision + "question = ")))


def other_card(*edits: tuple[str, str]) -> str:
    """The option line ruled `other`, `edits` applied to its head."""
    return card(card_head(("question = ", other_decision() + "question = "), *edits))


RETURNED_ON = "returned_on = 2026-10-28\n"
RETURNED_NOTE = 'returned_note = "Was kostet B im Betrieb?"\n'


def returned_card(keys: str = RETURNED_ON + RETURNED_NOTE) -> str:
    """The open option line with `keys` between its text and its card keys."""
    return card(card_head(("question = ", keys + "question = ")))


STALE_CARD_HASH = "sha256:" + "0" * 64
ALREADY_RULED = "line 2 is already ruled; a changed ruling is a new line"
YES_NO_LINE = '[[expectation]]\ntext = "Alt"\ndefault = "no"\n'


def item_body(option_line: str, *, yes_no_line: str = YES_NO_LINE, newline: str = "\n") -> str:
    """Issue #7's body: line 1 a yes/no line, line 2 `option_line`."""
    return card_body(option_line, before="\n" + yes_no_line, newline=newline)


def serve_item(monkeypatch: pytest.MonkeyPatch, raw_body: str) -> FakeForge:
    reference = forge.ItemReference(forge.ItemState.OPEN, "Karte", raw_body)
    return serve_forge(monkeypatch, FakeForge(issue_references={7: reference}))


def assert_refusal_writes_nothing(
    client: FakeForge,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    message: str,
    reason: str,
) -> None:
    """`rule 7 <arguments>` refuses with `message` in both forms and writes no body."""
    command = ["rule", "7", *arguments]
    text = run_cli(command, capsys)
    wire = run_cli([*command, "--json"], capsys)
    assert (text.status, text.stderr) == (2, f"ERROR: {message}\n")
    assert (wire.status, json.loads(wire.stdout)) == (
        2,
        {"ok": False, "reason": reason, "message": message},
    )
    assert client.body_writes == []


def decide(letter: str, via: str, shown: str = GOLDEN_CARD_HASH, *, line: int = 2) -> list[str]:
    """`rule`'s arguments after the item for one option choice."""
    return ["--line", str(line), "--option", letter, "--via", via, "--card-hash", shown]


def other_arguments(
    answer: str, via: str = "chat", shown: str = GOLDEN_CARD_HASH, *, line: int = 2
) -> list[str]:
    """`rule`'s arguments after the item for one Other answer; `=` keeps a leading dash."""
    return ["--line", str(line), f"--other={answer}", "--via", via, "--card-hash", shown]


TODAY = FROZEN_CLI_NOW.date().isoformat()
NOTE = "Was kostet B im Betrieb?"


def returned_today(note: str | None = NOTE) -> str:
    """The open option line as `--unclear` writes it on the frozen day."""
    note_key = "" if note is None else f"returned_note = {json.dumps(note, ensure_ascii=False)}\n"
    return returned_card(f"returned_on = {TODAY}\n{note_key}")


def unclear(note: str | None = None, shown: str = GOLDEN_CARD_HASH, *, line: int = 2) -> list[str]:
    """`rule`'s arguments after the item for one send-back; `=` keeps a leading dash."""
    note_flags = [] if note is None else [f"--note={note}"]
    return ["--line", str(line), "--unclear", *note_flags, "--card-hash", shown]


def option_entries(raw: str) -> list[dict[str, object]]:
    entries = body.block_expectation_dicts(body.locate_block(raw).data)
    return [entry for entry in entries if "option" in entry]


def assert_rewritten_alike(before: str, after: str, storage: body.Storage) -> None:
    """`after` is valid, keeps `before`'s option lines value for value and its
    newline, and rendering it again changes no byte."""
    located = body.locate_block(after)
    assert body.parse_body(after, storage=storage).read_state is body.BodyReadState.VALID
    assert option_entries(after) == option_entries(before)
    assert ("\r\n" in after) is ("\r\n" in before)
    assert body.replace_block(after, located, located.data) == after
    assert {
        line.card_hash
        for line in expectation_lines(after, storage=storage)
        if isinstance(line, OptionLine)
    } <= {GOLDEN_CARD_HASH}


SECOND_CARD = card(card_head(("Soll dein Song", "Soll dein Lied")))


def group_body(third: str = SECOND_CARD, *, yes_no_line: str = YES_NO_LINE) -> str:
    """Issue #7: line 1 `yes_no_line`, lines 2 and 3 open option lines."""
    return card_body(third, before="\n" + yes_no_line + "\n" + card())


def shown_hash(raw: str, index: int) -> str:
    line = expectation_lines(raw)[index - 1]
    assert isinstance(line, OptionLine)
    return line.card_hash
