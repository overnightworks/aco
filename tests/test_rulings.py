"""Rulings through the real GitHub repository world; only the forge is injected."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from board_fixtures import (
    MINIMAL_BLOCK_TOML,
    RULED_ON,
    block_body,
    board_issue,
    complete_contract,
    proposed_expectation,
    ruled_expectation,
)
from cli_fixtures import real_git, run_cli, track_board_config
from github_fixtures import FakeForge, serve_forge
from store_fixtures import state_ref_tip

from agent_coordination import board


@pytest.fixture(autouse=True)
def _github_world(github_clone: Path, bare_remote: Path) -> None:
    """Arrangement guards G1-G3; no command result or effect is inspected."""
    assert real_git(github_clone, "ls-files", ".aco/board.toml").stdout == ".aco/board.toml\n"
    main = real_git(github_clone, "rev-parse", "main").stdout.strip()
    assert real_git(github_clone, "rev-parse", "origin/HEAD").stdout.strip() == main
    assert (
        real_git(github_clone, "config", "--get", "remote.origin.url").stdout
        == "git@github.com:example/agent-coordination.git\n"
    )
    assert (
        real_git(github_clone, "ls-remote", "origin", "refs/heads/main").stdout
        == f"{main}\trefs/heads/main\n"
    )
    assert state_ref_tip(bare_remote) is None


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
                            proposed_expectation("Open decision 0."),
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
                        'text = "Proposed"\ndefault = "later"\n'
                    )
                    + (
                        "\n\n## Erwartungen (refine-Lauf 28.08.2026)\n"
                        "- Ruled one *(geregelt: ja)*\n"
                        "- Ruled two *(geregelt: ja)*\n"
                    ),
                ),
            ),
            "#400 1/1: Block-only expectations\n  1 open: Proposed\n",
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
                        "Ship #10.", expectation=[proposed_expectation("A" * 98 + "\u202eBC")]
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
    issues: tuple[board.Issue, ...],
    expected: str,
    config: str | None,
) -> None:
    """Spec: RUL-01, RUL-02, RUL-04, RUL-07, RUL-11 -- exact rows; Never 2: block progress."""
    if config is not None:
        track_board_config(github_clone, config)
        assert real_git(github_clone, "show", "HEAD:.aco/board.toml").stdout == config
        assert 'text = "Proposed"' in issues[0].body
        assert issues[0].body.count("*(geregelt: ja)*") == 2
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
                    10,
                    "Open expectation",
                    complete_contract(
                        "Ship #10.",
                        expectation=[
                            proposed_expectation("Open decision 0."),
                            ruled_expectation("Settled decision 0."),
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
                        "title": "Open expectation",
                        "open": 1,
                        "total": 2,
                        "lines": [
                            {
                                "index": 1,
                                "text": "Open decision 0.",
                                "ruling": None,
                                "ruled_on": None,
                                "default": "later",
                            },
                            {
                                "index": 2,
                                "text": "Settled decision 0.",
                                "ruling": "yes",
                                "ruled_on": RULED_ON.isoformat(),
                                "default": None,
                            },
                        ],
                    }
                ],
            },
            None,
            id="open-json",
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
                                "default": None,
                            },
                            {
                                "index": 2,
                                "text": "Settled decision 1.",
                                "ruling": "yes",
                                "ruled_on": RULED_ON.isoformat(),
                                "default": None,
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
                    "Open expectation",
                    complete_contract(
                        "Ship #10.",
                        expectation=[
                            proposed_expectation(
                                "Open decision.",
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
                        "title": "Open expectation",
                        "open": 1,
                        "total": 1,
                        "lines": [
                            {
                                "index": 1,
                                "text": "Open decision.",
                                "ruling": None,
                                "ruled_on": None,
                                "default": "later",
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
def test_rulings_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    issues: tuple[board.Issue, ...],
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


@pytest.mark.parametrize("as_json", [pytest.param(False, id="text"), pytest.param(True, id="json")])
@pytest.mark.parametrize(
    "issues, headers, numbers",
    [
        pytest.param(
            (
                board_issue(
                    50,
                    "In-flight security work",
                    complete_contract(
                        "Ship #50.",
                        expectation=[
                            proposed_expectation("Open decision 0."),
                            proposed_expectation("Open decision 1."),
                            ruled_expectation("Settled decision 0."),
                        ],
                    ),
                    labels=("security",),
                ),
                board_issue(
                    30,
                    "Later security tie",
                    complete_contract(
                        "Ship #30.",
                        expectation=[
                            proposed_expectation("Open decision 0."),
                            ruled_expectation("Settled decision 0."),
                        ],
                    ),
                    labels=("security",),
                ),
                board_issue(
                    10,
                    "Earlier security tie",
                    complete_contract(
                        "Ship #10.",
                        expectation=[
                            proposed_expectation("Open decision 0."),
                            proposed_expectation("Open decision 1."),
                            ruled_expectation("Settled decision 0."),
                        ],
                    ),
                    labels=("security",),
                ),
                board_issue(
                    40,
                    "More open security work",
                    complete_contract(
                        "Ship #40.",
                        expectation=[
                            proposed_expectation("Open decision 0."),
                            proposed_expectation("Open decision 1."),
                            ruled_expectation("Settled decision 0."),
                        ],
                    ),
                    labels=("security",),
                ),
                board_issue(
                    60,
                    "Lower-priority product work",
                    complete_contract(
                        "Ship #60.", expectation=[proposed_expectation("Open decision 0.")]
                    ),
                    labels=("product",),
                ),
                board_issue(
                    70,
                    "Fully ruled security work",
                    complete_contract(
                        "Ship #70.", expectation=[ruled_expectation("Settled decision 0.")]
                    ),
                    labels=("security",),
                ),
            ),
            [
                "#50 2/3: In-flight security work",
                "#30 1/2: Later security tie",
                "#10 2/3: Earlier security tie",
                "#40 2/3: More open security work",
                "#60 1/1: Lower-priority product work",
                "#70 0/1: Fully ruled security work",
            ],
            [50, 30, 10, 40, 60, 70],
            id="priority",
        ),
        pytest.param(
            (
                board_issue(
                    50,
                    "In-flight ruled",
                    complete_contract(
                        "Ship #50.", expectation=[ruled_expectation("Settled decision 0.")]
                    ),
                    labels=("security",),
                ),
                board_issue(
                    10,
                    "Earlier ruled",
                    complete_contract(
                        "Ship #10.", expectation=[ruled_expectation("Settled decision 0.")]
                    ),
                    labels=("security",),
                ),
                board_issue(
                    40,
                    "Later ruled",
                    complete_contract(
                        "Ship #40.", expectation=[ruled_expectation("Settled decision 0.")]
                    ),
                    labels=("security",),
                ),
                board_issue(
                    5,
                    "Product ruled",
                    complete_contract(
                        "Ship #5.", expectation=[ruled_expectation("Settled decision 0.")]
                    ),
                    labels=("product",),
                ),
            ),
            [
                "#50 0/1: In-flight ruled",
                "#10 0/1: Earlier ruled",
                "#40 0/1: Later ruled",
                "#5 0/1: Product ruled",
            ],
            [50, 10, 40, 5],
            id="fully-ranked",
        ),
    ],
)
def test_rulings_orders_items(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    issues: tuple[board.Issue, ...],
    as_json: bool,
    headers: list[str],
    numbers: list[int],
) -> None:
    """Spec: RUL-01, RUL-03, RUL-04 --
    Category, score, open count and numeric ties in both groups."""
    serve_forge(
        monkeypatch,
        FakeForge(
            board_issues=issues,
            board_open_pull_requests=(board.PullRequest(200, "Fixes #50", "", "branch"),),
        ),
    )
    capsys.readouterr()
    result = run_cli(["rulings", *(["--json"] if as_json else [])], capsys)
    assert result.status == 0
    observed = (
        [item["number"] for item in json.loads(result.stdout)["rulings"]]
        if as_json
        else [line for line in result.stdout.splitlines() if line.startswith("#")]
    )
    assert observed == (numbers if as_json else headers)


@pytest.mark.parametrize(
    "issues, fields, expected",
    [
        pytest.param(
            (
                board_issue(
                    10,
                    "Before\u202eAfter",
                    complete_contract(
                        "Ship #10.", expectation=[proposed_expectation("A" * 98 + "\u202eBC")]
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
                    "Defaults",
                    complete_contract(
                        "Ship #10.",
                        expectation=[
                            proposed_expectation("Yes", default="yes"),
                            proposed_expectation("No", default="no"),
                            proposed_expectation("Later", default="later"),
                        ],
                    ),
                ),
            ),
            ("default",),
            (["yes", "no", "later"],),
            id="defaults-json",
        ),
    ],
)
def test_rulings_preserves_json_content(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    issues: tuple[board.Issue, ...],
    fields: tuple[str, ...],
    expected: tuple[object, ...],
) -> None:
    """Spec: RUL-10, RUL-11, RUL-12 --
    Stored controls, untruncated text and every proposed outcome."""
    serve_forge(monkeypatch, FakeForge(board_issues=issues))
    capsys.readouterr()
    result = run_cli(["rulings", "--json"], capsys)
    assert result.status == 0
    item = json.loads(result.stdout)["rulings"][0]
    observed = tuple(
        item[field] if field == "title" else [line[field] for line in item["lines"]]
        for field in fields
    )
    assert observed == expected
