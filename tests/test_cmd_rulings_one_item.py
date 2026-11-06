"""`aco rulings <n>` through the real GitHub repository world; only the forge is injected."""

from __future__ import annotations

import json

import pytest
from board_fixtures import REPOSITORY, RULED_ON, complete_contract, ruled_expectation
from cli_fixtures import run_cli
from github_fixtures import FakeForge, serve_forge
from option_cards import open_option_entry

from aco import forge

pytestmark = pytest.mark.usefixtures("github_world")

ITEM = 12
IN_BOTH_FORMS = pytest.mark.parametrize("flags", [[], ["--json"]], ids=["text", "json"])


def _reference(state: forge.ItemState, *, expectation: bool = True) -> forge.ItemReference:
    lines = [open_option_entry("Open decision 0."), ruled_expectation("Settled decision 0.")]
    body = complete_contract("Ship #12.", expectation=lines if expectation else [])
    return forge.ItemReference(state, "Song jump", body)


@IN_BOTH_FORMS
@pytest.mark.parametrize("state", [forge.ItemState.OPEN, forge.ItemState.CLOSED])
def test_rulings_names_one_item_open_or_closed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    state: forge.ItemState,
) -> None:
    """Spec: RUL-24"""
    serve_forge(monkeypatch, FakeForge(issue_references={ITEM: _reference(state)}))

    result = run_cli(["rulings", str(ITEM), *flags], capsys)

    assert result.status == 0
    if flags:
        listed = json.loads(result.stdout)["rulings"]
        assert [(row["number"], row["title"], row["open"], row["total"]) for row in listed] == [
            (ITEM, "Song jump", 1, 2)
        ]
        assert [line["index"] for line in listed[0]["lines"]] == [1, 2]
        assert listed[0]["lines"][0]["card_hash"].startswith("sha256:")
    else:
        assert result.stdout == (
            f"#{ITEM} 1/2: Song jump\n"
            "  1 open: Open decision 0.\n"
            f"  2 ruled yes {RULED_ON.isoformat()}: Settled decision 0.\n"
        )


@IN_BOTH_FORMS
def test_rulings_of_an_item_without_lines_prints_the_empty_listing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flags: list[str]
) -> None:
    """Spec: RUL-24"""
    reference = _reference(forge.ItemState.CLOSED, expectation=False)
    serve_forge(monkeypatch, FakeForge(issue_references={ITEM: reference}))

    result = run_cli(["rulings", str(ITEM), *flags], capsys)

    assert result.status == 0
    assert result.stdout == (
        '{"ok": true, "reason": "listed", "rulings": []}\n' if flags else "No expectation lines.\n"
    )


def test_rulings_refuses_a_missing_number_as_check_does_in_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: RUL-25"""
    serve_forge(
        monkeypatch,
        FakeForge(issue_references={ITEM: forge.ItemReference(forge.ItemState.MISSING)}),
    )

    result = run_cli(["rulings", str(ITEM)], capsys)

    assert (result.status, result.stdout, result.stderr) == (
        2,
        "",
        f"REFUSED: #{ITEM} does not exist in {REPOSITORY}\n",
    )


def test_rulings_refuses_a_missing_number_as_check_does_in_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: RUL-25"""
    serve_forge(
        monkeypatch,
        FakeForge(issue_references={ITEM: forge.ItemReference(forge.ItemState.MISSING)}),
    )

    result = run_cli(["rulings", str(ITEM), "--json"], capsys)

    assert result.status == 2
    assert json.loads(result.stdout) == {
        "ok": False,
        "reason": "missing",
        "kind": "missing",
        "number": ITEM,
        "message": f"does not exist in {REPOSITORY}",
    }


@IN_BOTH_FORMS
def test_rulings_refuses_a_pull_request_number(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flags: list[str]
) -> None:
    """Spec: RUL-26"""
    landing = forge.ItemReference(forge.ItemState.OPEN, "A change", "", is_landing=True)
    serve_forge(monkeypatch, FakeForge(issue_references={ITEM: landing}))
    sentence = f"#{ITEM} is a pull request, not an issue; rulings needs an issue"

    result = run_cli(["rulings", str(ITEM), *flags], capsys)

    assert result.status == 2
    assert f"ERROR: {sentence}" in result.stderr
    if flags:
        assert json.loads(result.stdout) == {
            "ok": False,
            "reason": "invalid_item",
            "message": sentence,
        }
