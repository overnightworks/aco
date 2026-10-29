"""Rulings through the real GitHub repository world; only the forge is injected."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from board_fixtures import (
    MINIMAL_BLOCK_TOML,
    REPOSITORY,
    RULED_ON,
    block_body,
    board_issue,
    complete_contract,
    ruled_expectation,
)
from cli_fixtures import real_git, run_cli, track_board_config
from github_fixtures import FakeForge, serve_forge
from github_pages import raw_board_issue
from option_cards import (
    RETURNED_NOTE,
    RETURNED_ON,
    card,
    card_body,
    card_head,
    open_option_entry,
    ruled_card,
)

from aco import body, github, store, workboard

pytestmark = pytest.mark.usefixtures("github_world")


@pytest.mark.parametrize(
    "issues, expected, config",
    [
        pytest.param(
            (
                board_issue(
                    10,
                    "Open expectation",
                    complete_contract(
                        "Ship #10.",
                        expectation=[
                            open_option_entry("Open decision 0."),
                            ruled_expectation("Settled decision 0."),
                        ],
                    ),
                ),
            ),
            (
                "#10 1/2: Open expectation\n"
                "  1 open: Open decision 0.\n"
                f"  2 ruled yes {RULED_ON.isoformat()}: Settled decision 0.\n"
            ),
            None,
            id="open-text",
        ),
        pytest.param(
            (
                board_issue(
                    11,
                    "Fully ruled",
                    complete_contract(
                        "Ship #11.",
                        expectation=[
                            ruled_expectation("Settled decision 0."),
                            ruled_expectation("Settled decision 1."),
                        ],
                    ),
                ),
            ),
            (
                "#11 0/2: Fully ruled\n"
                f"  1 ruled yes {RULED_ON.isoformat()}: Settled decision 0.\n"
                f"  2 ruled yes {RULED_ON.isoformat()}: Settled decision 1.\n"
            ),
            None,
            id="ruled-text",
        ),
        pytest.param(
            (
                board_issue(
                    400,
                    "Block-only expectations",
                    block_body(
                        f"{MINIMAL_BLOCK_TOML}[[expectation]]\n"
                        'text = "Deferred"\nruling = "later"\nruled_on = 2026-08-28\n'
                    )
                    + (
                        "\n\n## Erwartungen (refine-Lauf 28.08.2026)\n"
                        "- Ruled one *(geregelt: ja)*\n"
                        "- Ruled two *(geregelt: ja)*\n"
                    ),
                ),
            ),
            "#400 0/1: Block-only expectations\n  1 ruled later 2026-08-28: Deferred\n",
            'body_contract = "block"\n',
            id="stale-prose-text",
        ),
        pytest.param((), "No expectation lines.\n", None, id="empty-text"),
        pytest.param(
            (board_issue(99, "Without lines", complete_contract("Ship #99.")),),
            "No expectation lines.\n",
            None,
            id="without-lines-text",
        ),
        pytest.param(
            (
                board_issue(
                    10,
                    "Before\u202eAfter",
                    complete_contract(
                        "Ship #10.", expectation=[open_option_entry("A" * 98 + "\u202eBC")]
                    ),
                ),
            ),
            "#10 1/1: Before\\u202eAfter\n  1 open: " + "A" * 98 + "\\u202e…\n",
            None,
            id="long-text",
        ),
    ],
)
def test_rulings_lists_items_and_lines(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    issues: tuple[workboard.Issue, ...],
    expected: str,
    config: str | None,
) -> None:
    """Spec: RUL-01, RUL-02, RUL-04, RUL-07, RUL-11 -- exact rows; Never 2: block progress."""
    if config is not None:
        track_board_config(github_clone, config)
        assert real_git(github_clone, "show", "HEAD:.aco/board.toml").stdout == config
    serve_forge(monkeypatch, FakeForge(board_issues=issues))
    capsys.readouterr()
    result = run_cli(["rulings"], capsys)
    assert result.status == 0
    assert result.stdout == expected


@pytest.mark.parametrize(
    "issues, expected, raw",
    [
        pytest.param(
            (
                board_issue(
                    11,
                    "Fully ruled",
                    complete_contract(
                        "Ship #11.",
                        expectation=[
                            ruled_expectation("Settled decision 0."),
                            ruled_expectation("Settled decision 1."),
                        ],
                    ),
                ),
            ),
            {
                "ok": True,
                "reason": "listed",
                "rulings": [
                    {
                        "number": 11,
                        "title": "Fully ruled",
                        "open": 0,
                        "total": 2,
                        "lines": [
                            {
                                "index": 1,
                                "text": "Settled decision 0.",
                                "ruling": "yes",
                                "ruled_on": RULED_ON.isoformat(),
                            },
                            {
                                "index": 2,
                                "text": "Settled decision 1.",
                                "ruling": "yes",
                                "ruled_on": RULED_ON.isoformat(),
                            },
                        ],
                    }
                ],
            },
            None,
            id="ruled-json",
        ),
        pytest.param(
            (),
            {"ok": True, "reason": "listed", "rulings": []},
            '{"ok": true, "reason": "listed", "rulings": []}\n',
            id="empty-json",
        ),
        pytest.param(
            (board_issue(99, "Without lines", complete_contract("Ship #99.")),),
            {"ok": True, "reason": "listed", "rulings": []},
            None,
            id="without-lines-json",
        ),
        pytest.param(
            (
                board_issue(
                    10,
                    "Ruled expectation",
                    complete_contract(
                        "Ship #10.",
                        expectation=[
                            ruled_expectation(
                                "Settled decision.",
                                question="Ship it?",
                                example="Release on Friday.",
                                picture=(
                                    '<svg xmlns="http://www.w3.org/2000/svg">'
                                    '<circle cx="5" cy="5" r="4"/></svg>'
                                ),
                            )
                        ],
                    ),
                ),
            ),
            {
                "ok": True,
                "reason": "listed",
                "rulings": [
                    {
                        "number": 10,
                        "title": "Ruled expectation",
                        "open": 0,
                        "total": 1,
                        "lines": [
                            {
                                "index": 1,
                                "text": "Settled decision.",
                                "ruling": "yes",
                                "ruled_on": RULED_ON.isoformat(),
                                "question": "Ship it?",
                                "example": "Release on Friday.",
                                "picture": (
                                    '<svg xmlns="http://www.w3.org/2000/svg">'
                                    '<circle cx="5" cy="5" r="4"/></svg>'
                                ),
                            }
                        ],
                    }
                ],
            },
            None,
            id="optional-json",
        ),
    ],
)
@pytest.mark.usefixtures("github_clone")
def test_rulings_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    issues: tuple[workboard.Issue, ...],
    expected: dict[str, object],
    raw: str | None,
) -> None:
    """Spec: RUL-01, RUL-04, RUL-05, RUL-06, RUL-08, RUL-10, RUL-12 --
    Complete JSON objects and empty wire envelope."""
    serve_forge(monkeypatch, FakeForge(board_issues=issues))
    capsys.readouterr()
    result = run_cli(["rulings", "--json"], capsys)
    assert result.status == 0
    assert json.loads(result.stdout) == expected
    if raw is not None:
        assert result.stdout == raw


RULED_YES_NO = '[[expectation]]\ntext = "Alt"\nruling = "yes"\nruled_on = 2026-10-28\n'
CARD_DAY = "asked_on = 2026-10-28"


def _item_of(number: int, *lines: str) -> workboard.Issue:
    return board_issue(number, f"Item {number}", card_body("".join(lines)))


def _open_card(day: str) -> str:
    return card(card_head((CARD_DAY, f"asked_on = {day}")))


def _ruled_card(day: str | None) -> str:
    edit = (CARD_DAY + "\n", "") if day is None else (CARD_DAY, f"asked_on = {day}")
    return ruled_card(edit)


def _returned_card(day: str) -> str:
    keys = RETURNED_ON + RETURNED_NOTE
    return card(card_head(("question = ", keys + "question = "), (CARD_DAY, f"asked_on = {day}")))


@pytest.mark.parametrize("as_json", [pytest.param(False, id="text"), pytest.param(True, id="json")])
@pytest.mark.parametrize(
    "issues, numbers",
    [
        pytest.param(
            (
                _item_of(10, _open_card("2026-10-27")),
                _item_of(20, _open_card("2026-10-29")),
                _item_of(30, _open_card("2026-10-28")),
                _item_of(40, _open_card("2026-10-28")),
            ),
            [20, 40, 30, 10],
            id="newest-card-first-same-day-by-descending-number",
        ),
        pytest.param(
            (
                _item_of(10, _open_card("2026-10-30")),
                _item_of(
                    20,
                    _open_card("2026-10-25"),
                    _open_card("2026-10-29"),
                    _ruled_card("2026-10-31"),
                ),
                _item_of(30, _open_card("2026-10-28")),
            ),
            [10, 20, 30],
            id="multi-point-card-dated-by-its-newest-open-point",
        ),
        pytest.param(
            (
                _item_of(10, _returned_card("2026-10-29")),
                _item_of(20, _open_card("2026-10-28")),
                _item_of(30, _open_card("2026-10-30"), RULED_YES_NO),
            ),
            [30, 10, 20],
            id="card-with-its-head-and-card-plus-yes-no-ordered-by-card-date",
        ),
        pytest.param(
            (
                _item_of(10, _ruled_card("2026-10-31")),
                _item_of(30, _ruled_card(None)),
                _item_of(40, _open_card("2026-10-01")),
                _item_of(50, RULED_YES_NO, _open_card("2026-10-02")),
                _item_of(60, RULED_YES_NO),
            ),
            [50, 40, 60, 30, 10],
            id="dated-cards-then-fully-ruled-rows",
        ),
        pytest.param(
            (
                _item_of(10, _open_card("2026-10-28")),
                board_issue(
                    20,
                    "Malformed block",
                    block_body(MINIMAL_BLOCK_TOML + "[[expectation\n" + card()),
                ),
                dataclasses.replace(
                    _item_of(30, _open_card("2026-10-29")),
                    unreadable=body.ContractDefect("items/30", "cannot be read"),
                ),
                board_issue(40, "No block", "Prose only."),
                _item_of(50, '[[expectation]]\ntext = "Alt"\n'),
            ),
            [10],
            id="malformed-unreadable-and-block-less-rows-are-not-listed",
        ),
    ],
)
@pytest.mark.usefixtures("github_clone")
def test_rulings_orders_items(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    issues: tuple[workboard.Issue, ...],
    as_json: bool,
    numbers: list[int],
) -> None:
    """Spec: RUL-01, RUL-03, RUL-04, RUL-20, BODY-29 --
    Newest open card first, then fully ruled rows, in text and `--json`; malformed rows,
    an open yes/no line's among them, and unreadable rows are not listed."""
    serve_forge(monkeypatch, FakeForge(board_issues=issues))
    capsys.readouterr()
    result = run_cli(["rulings", *(["--json"] if as_json else [])], capsys)
    assert result.status == 0
    observed = (
        [item["number"] for item in json.loads(result.stdout)["rulings"]]
        if as_json
        else [int(line[1:].split(" ")[0]) for line in result.stdout.splitlines() if line[:1] == "#"]
    )
    assert observed == numbers


@pytest.mark.usefixtures("github_clone")
def test_rulings_reads_one_listing_page_and_no_claim_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: RUL-03, Never 1 -- One request for 99 raw entries; no board projection read."""
    calls: list[list[str]] = []
    carrying_card = raw_board_issue(number=7, body=_item_of(7, _open_card("2026-10-28")).body)
    pull_request = raw_board_issue(number=8, isPullRequest=True)
    filler = [raw_board_issue(number=number) for number in range(100, 197)]
    page = "\n".join(json.dumps(row) for row in [carrying_card, pull_request, *filler])
    assert len(page.splitlines()) == 99

    def run(arguments: list[str], input_data: bytes | None = None) -> str:
        calls.append(arguments)
        return page

    def refuse_claim_state(**_: object) -> object:
        raise AssertionError("rulings must not read the claim state")

    client = serve_forge(monkeypatch, github.GitHubForge(github.repository_id(REPOSITORY), run=run))
    monkeypatch.setattr(store, "fetch_state", refuse_claim_state)
    capsys.readouterr()
    result = run_cli(["rulings", "--json"], capsys)
    assert result.status == 0
    assert [item["number"] for item in json.loads(result.stdout)["rulings"]] == [7]
    assert client.requests == 1
    assert len(calls) == 1
    assert "issues?state=open" in calls[0][1]


@pytest.mark.parametrize(
    "issues, fields, expected",
    [
        pytest.param(
            (
                board_issue(
                    10,
                    "Before\u202eAfter",
                    complete_contract(
                        "Ship #10.", expectation=[open_option_entry("A" * 98 + "\u202eBC")]
                    ),
                ),
            ),
            ("title", "text"),
            ("Before\u202eAfter", ["A" * 98 + "\u202eBC"]),
            id="long-json",
        ),
        pytest.param(
            (
                board_issue(
                    10,
                    "Open expectation",
                    complete_contract(
                        "Ship #10.",
                        expectation=[
                            open_option_entry("Open decision 0."),
                            ruled_expectation("Settled decision 0."),
                        ],
                    ),
                ),
            ),
            ("open", "total", "ruling", "ruled_on"),
            (1, 2, [None, "yes"], [None, RULED_ON.isoformat()]),
            id="open-json",
        ),
    ],
)
@pytest.mark.usefixtures("github_clone")
def test_rulings_preserves_json_content(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    issues: tuple[workboard.Issue, ...],
    fields: tuple[str, ...],
    expected: tuple[object, ...],
) -> None:
    """Spec: RUL-10, RUL-11, RUL-12 --
    Stored controls, untruncated text, and an open line's counts and null ruling."""
    serve_forge(monkeypatch, FakeForge(board_issues=issues))
    capsys.readouterr()
    result = run_cli(["rulings", "--json"], capsys)
    assert result.status == 0
    item = json.loads(result.stdout)["rulings"][0]
    observed = tuple(
        item[field] if field in item else [line[field] for line in item["lines"]]
        for field in fields
    )
    assert observed == expected
