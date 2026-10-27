"""Ask through a real GitHub checkout, with injection only at the forge boundary."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body, board_issue
from cli_fixtures import (
    CliRun,
    freeze_cli_now,
    real_git,
    run_cli,
    track_board_config,
)
from github_fixtures import FakeForge, assert_github_world, serve_forge

from aco import body, cli, expectations, forge, github, session


@dataclass(frozen=True)
class AskInput:
    arguments: tuple[str, ...] = ()
    initial_body: str = block_body(MINIMAL_BLOCK_TOML)
    picture: str | None = None


@dataclass(frozen=True)
class TextResult:
    stdout: str
    entries: tuple[expectations.ExpectationLine, ...] | None = None
    stderr: str | None = None
    written_keys: tuple[int, ...] | None = None


@pytest.fixture
def github_world(github_clone: Path, bare_remote: Path) -> None:
    assert_github_world(github_clone, bare_remote)


@pytest.mark.usefixtures(github_world.__name__)
class TestGithubAsk:
    @pytest.mark.parametrize(
        "scenario,expected",
        [
            pytest.param(
                AskInput(
                    initial_body=block_body(
                        MINIMAL_BLOCK_TOML + '[[expectation]]\ntext = "Ship it?"\n'
                        'ruling = "yes"\nruled_on = 2026-08-01\n'
                    )
                ),
                TextResult("ASKED #90 line 2: New question?\n"),
                id="append",
            ),
            pytest.param(
                AskInput(
                    (
                        "--question",
                        "Ship it?",
                        "--example",
                        "Release on Friday.",
                        "--picture",
                        "sketch.svg",
                    ),
                    picture='<svg xmlns="http://www.w3.org/2000/svg">'
                    '<circle cx="5" cy="5" r="4"/></svg>',
                ),
                TextResult(
                    "ASKED #90 line 1: New question?\n",
                    (
                        expectations.YesNoLine(
                            1,
                            "New question?",
                            None,
                            None,
                            default="yes",
                            question="Ship it?",
                            example="Release on Friday.",
                            picture='<svg xmlns="http://www.w3.org/2000/svg">'
                            '<circle cx="5" cy="5" r="4"/></svg>',
                        ),
                    ),
                ),
                id="card",
            ),
            pytest.param(
                AskInput(
                    initial_body=block_body(
                        MINIMAL_BLOCK_TOML
                        + '[[expectation]]\ntext = "Ship it?"\ndefault = "later"\n'
                        '[[slice]]\nindex = 1\ntitle = "Bad\\u000Btitle"\n'
                    )
                ),
                TextResult("ASKED #90 line 2: New question?\n", stderr="", written_keys=(90,)),
                id="display-control",
            ),
        ],
    )
    def test_text(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        scenario: AskInput,
        expected: TextResult,
    ) -> None:
        """Spec: ASK-01, ASK-03, ASK-05 — append, attach cards, accept stored display controls."""
        client = serve_forge(
            monkeypatch,
            FakeForge(
                issue_references={
                    90: forge.ItemReference(
                        forge.ItemState.OPEN, "Decide something", scenario.initial_body
                    )
                }
            ),
        )
        if scenario.picture is not None:
            Path("sketch.svg").write_text(scenario.picture, encoding="utf-8")
        capsys.readouterr()
        result = run_cli(["ask", "90", "--text", "New question?", *scenario.arguments], capsys)
        actual = TextResult(
            result.stdout,
            expectations.expectation_lines(client.item_bodies[90])
            if expected.entries is not None
            else None,
            result.stderr if expected.stderr is not None else None,
            tuple(client.item_bodies) if expected.written_keys is not None else None,
        )
        assert (result.status, actual) == (0, expected)

    @pytest.mark.parametrize(
        "scenario,expected,wire",
        [
            pytest.param(
                AskInput(("--default", "later")),
                {
                    "ok": True,
                    "reason": "asked",
                    "item": 90,
                    "index": 1,
                    "text": "New question?",
                    "default": "later",
                },
                True,
                id="later",
            ),
            pytest.param(
                AskInput(
                    (
                        "--question",
                        "Ship it?",
                        "--example",
                        "Release on Friday.",
                        "--picture",
                        "sketch.svg",
                    ),
                    picture='<svg xmlns="http://www.w3.org/2000/svg">'
                    '<circle cx="5" cy="5" r="4"/></svg>',
                ),
                {
                    "ok": True,
                    "reason": "asked",
                    "item": 90,
                    "index": 1,
                    "text": "New question?",
                    "default": "yes",
                    "question": "Ship it?",
                    "example": "Release on Friday.",
                    "picture": '<svg xmlns="http://www.w3.org/2000/svg">'
                    '<circle cx="5" cy="5" r="4"/></svg>',
                },
                False,
                id="card",
            ),
            pytest.param(
                AskInput(("--question", "Ship it?")),
                {
                    "ok": True,
                    "reason": "asked",
                    "item": 90,
                    "index": 1,
                    "text": "New question?",
                    "default": "yes",
                    "question": "Ship it?",
                },
                False,
                id="question-only",
            ),
        ],
    )
    def test_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        scenario: AskInput,
        expected: dict[str, object],
        wire: bool,
    ) -> None:
        """Spec: ASK-02, ASK-04 — success fields and only the supplied card keys."""
        serve_forge(
            monkeypatch,
            FakeForge(
                issue_references={
                    90: forge.ItemReference(
                        forge.ItemState.OPEN, "Decide something", scenario.initial_body
                    )
                }
            ),
        )
        if scenario.picture is not None:
            Path("sketch.svg").write_text(scenario.picture, encoding="utf-8")
        capsys.readouterr()
        result = run_cli(
            ["ask", "90", "--text", "New question?", *scenario.arguments, "--json"], capsys
        )
        assert (result.status, json.loads(result.stdout), result.stdout if wire else None) == (
            0,
            expected,
            json.dumps(expected) + "\n" if wire else None,
        )

    @pytest.mark.parametrize(
        "arguments,initial,state,is_landing,fails,picture,message,reason,wire,store",
        [
            pytest.param(
                (),
                "## Now\nOld prose.\n",
                forge.ItemState.OPEN,
                False,
                False,
                None,
                "#90 body malformed: aco: no aco block; ask needs a valid aco block",
                "invalid_item",
                True,
                True,
                id="blockless",
            ),
            pytest.param(
                ("--text", "   "),
                block_body(MINIMAL_BLOCK_TOML),
                forge.ItemState.OPEN,
                False,
                False,
                None,
                "expectation text must be a non-empty string",
                "invalid_expectation",
                True,
                True,
                id="blank-text",
            ),
            pytest.param(
                ("--picture", "sketch.svg"),
                block_body(MINIMAL_BLOCK_TOML),
                forge.ItemState.OPEN,
                False,
                False,
                "<div>not an svg</div>",
                "picture must be inline SVG rooted at <svg>",
                "invalid_picture",
                True,
                True,
                id="bad-svg",
            ),
            pytest.param(
                ("--question", "   "),
                block_body(MINIMAL_BLOCK_TOML),
                forge.ItemState.OPEN,
                False,
                False,
                None,
                "question must be a non-empty string",
                "invalid_expectation",
                True,
                True,
                id="blank-question",
            ),
            pytest.param(
                ("--example", "   "),
                block_body(MINIMAL_BLOCK_TOML),
                forge.ItemState.OPEN,
                False,
                False,
                None,
                "example must be a non-empty string",
                "invalid_expectation",
                True,
                True,
                id="blank-example",
            ),
            pytest.param(
                ("--question", "Q" * 161),
                block_body(MINIMAL_BLOCK_TOML),
                forge.ItemState.OPEN,
                False,
                False,
                None,
                "question must be at most 160 characters",
                "invalid_expectation",
                True,
                True,
                id="long-question",
            ),
            pytest.param(
                (),
                "",
                forge.ItemState.MISSING,
                False,
                False,
                None,
                "#90 does not exist",
                "invalid_item",
                True,
                True,
                id="missing-item",
            ),
            pytest.param(
                (),
                block_body(MINIMAL_BLOCK_TOML),
                forge.ItemState.OPEN,
                True,
                False,
                None,
                "#90 is a pull request, not an issue; ask needs an issue",
                "invalid_item",
                True,
                True,
                id="pull-request",
            ),
            pytest.param(
                (),
                block_body(MINIMAL_BLOCK_TOML),
                forge.ItemState.OPEN,
                False,
                True,
                None,
                "update item body failed (simulated)",
                "unavailable",
                False,
                False,
                id="write-failure",
            ),
            pytest.param(
                ("--picture", "missing.svg"),
                block_body(MINIMAL_BLOCK_TOML),
                forge.ItemState.OPEN,
                False,
                False,
                None,
                "--picture missing.svg could not be read: "
                "[Errno 2] No such file or directory: 'missing.svg'",
                None,
                False,
                True,
                id="missing-picture-text",
            ),
            pytest.param(
                ("--picture", "missing.svg"),
                block_body(MINIMAL_BLOCK_TOML),
                forge.ItemState.OPEN,
                False,
                False,
                None,
                "--picture missing.svg could not be read: "
                "[Errno 2] No such file or directory: 'missing.svg'",
                "invalid_picture",
                True,
                True,
                id="missing-picture-json",
            ),
        ],
    )
    def test_refusal(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        arguments: tuple[str, ...],
        initial: str,
        state: forge.ItemState,
        is_landing: bool,
        fails: bool,
        picture: str | None,
        message: str,
        reason: str | None,
        wire: bool,
        store: bool,
    ) -> None:
        """Spec: ASK-05, ASK-06, ASK-07, ASK-08, ASK-09, ASK-10, ASK-12,
        RULE-07, RULE-08 — invalid input and failed writes.
        """
        client = serve_forge(
            monkeypatch,
            FakeForge(
                issue_references={
                    90: forge.ItemReference(state, "Decide something", initial, is_landing)
                },
                fail_update_item_body=fails,
            ),
        )
        if picture is not None:
            Path("sketch.svg").write_text(picture, encoding="utf-8")
        assert picture is None or Path("sketch.svg").read_text(encoding="utf-8") == picture
        assert not Path("missing.svg").exists()
        capsys.readouterr()
        result = run_cli(
            [
                "ask",
                "90",
                "--text",
                "New question?",
                *arguments,
                *(["--json"] if reason is not None else []),
            ],
            capsys,
        )
        expected = {"ok": False, "reason": reason, "message": message}
        assert (
            result.status,
            result.stderr,
            json.loads(result.stdout) if reason is not None else None,
            result.stdout if wire else None,
            client.item_bodies if store else None,
        ) == (
            2,
            f"ERROR: {message}\n",
            expected if reason is not None else None,
            json.dumps(expected) + "\n" if wire else None,
            {} if store else None,
        )

    @pytest.mark.parametrize(
        "initial,arguments,repeat,list_rulings,observe,expected",
        [
            pytest.param(
                block_body(
                    MINIMAL_BLOCK_TOML + '[[expectation]]\ntext = "Ship it?"\n'
                    'ruling = "yes"\nruled_on = 2026-08-01\n'
                ),
                (),
                False,
                True,
                lambda result, written: (result.status, result.stdout),
                (
                    0,
                    "#90 1/2: Decide something\n  1 ruled yes 2026-08-01: Ship it?\n"
                    "  2 open: New question?\n",
                ),
                id="rulings",
            ),
            pytest.param(
                block_body(MINIMAL_BLOCK_TOML),
                ("--default", "yes"),
                False,
                False,
                lambda result, written: proposal_fields(written),
                ("yes", False, False),
                id="default-yes",
            ),
            pytest.param(
                block_body(MINIMAL_BLOCK_TOML),
                (),
                True,
                False,
                lambda result, written: (
                    result.stdout,
                    tuple(entry.text for entry in expectations.expectation_lines(written)),
                ),
                ("ASKED #90 line 2: New question?\n", ("New question?", "New question?")),
                id="duplicate",
            ),
            pytest.param(
                block_body(
                    MINIMAL_BLOCK_TOML, before="Preamble stays.\n\n", after="\nTail stays.\n"
                ),
                (),
                False,
                False,
                lambda result, written: surrounding_bytes(written),
                ("Preamble stays.\n\n```aco\n", "```\n\nTail stays.\n"),
                id="surrounding-bytes",
            ),
        ],
    )
    def test_persistence(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        initial: str,
        arguments: tuple[str, ...],
        repeat: bool,
        list_rulings: bool,
        observe: Callable[[CliRun, str], object],
        expected: object,
    ) -> None:
        """Spec: ASK-01, Never 1, Never 2, Never 3 — proposals, duplicate appends, bytes
        before and after the block."""
        freeze_cli_now(monkeypatch)
        reference = forge.ItemReference(forge.ItemState.OPEN, "Decide something", initial)
        client = serve_forge(monkeypatch, FakeForge(issue_references={90: reference}))
        capsys.readouterr()
        command = ["ask", "90", "--text", "New question?", *arguments]
        result = run_cli(command, capsys)
        if repeat:
            client.issue_references[90] = replace(reference, body=client.item_bodies[90])
            result = run_cli(command, capsys)
        if list_rulings:
            client.board_issues = (board_issue(90, "Decide something", client.item_bodies[90]),)
            result = run_cli(["rulings"], capsys)
        assert observe(result, client.item_bodies[90]) == expected


def proposal_fields(written: str) -> tuple[object, bool, bool]:
    entries = cast(list[dict[str, object]], body.locate_block(written).data["expectation"])
    entry = entries[0]
    return entry.get("default"), "ruling" in entry, "ruled_on" in entry


def surrounding_bytes(written: str) -> tuple[str, str]:
    block = body.locate_block(written)
    return written[: block.content_start], written[block.content_end :]


@pytest.mark.parametrize(
    "directory_fixture,remote_url,pin,arguments,boundaries,message,reason",
    [
        pytest.param(
            "clone",
            "file:///srv/git/agent-coordination.git",
            None,
            ("ask", "90", "--text", "New question?", "--json"),
            ((github, "discover_repository"),),
            "no forge adapter for host file",
            "unavailable",
            id="host",
        ),
        pytest.param(
            "clone",
            None,
            'storage = "state-ref"\n',
            ("--repo", "acme/items", "ask", "258", "--text", "New question?", "--json"),
            (),
            "--repo is meaningless under storage = state-ref",
            "invalid_usage",
            id="state-ref-repo",
        ),
        pytest.param(
            "tmp_path",
            None,
            None,
            ("ask", "90", "--text", "New question?", "--json"),
            ((github, "discover_repository"), (github, "GitHubForge")),
            "this command reads the repository's body contract from .aco/board.toml and needs "
            "a checkout (a shallow one is enough): fatal: not a git repository "
            "(or any of the parent directories): .git",
            "unavailable",
            id="checkout",
        ),
        pytest.param(
            "tmp_path",
            None,
            None,
            ("ask", "90", "--text", "New question?", "--picture", "missing.svg", "--json"),
            ((session.RunContext, "toplevel"), (session.RunContext, "forge_writer")),
            "--picture missing.svg could not be read: "
            "[Errno 2] No such file or directory: 'missing.svg'",
            "invalid_picture",
            id="picture-outside",
        ),
    ],
)
def test_context_refusal(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    directory_fixture: str,
    remote_url: str | None,
    pin: str | None,
    arguments: tuple[str, ...],
    boundaries: tuple[tuple[object, str], ...],
    message: str,
    reason: str,
) -> None:
    """Spec: ASK-06, ASK-09, ASK-11, BOARD-02, CHECK-10 — refuse before forbidden work."""
    directory = request.getfixturevalue(directory_fixture)
    monkeypatch.chdir(directory)
    monkeypatch.setenv("LC_ALL", "C")
    assert (real_git(directory, "rev-parse", "--show-toplevel", check=False).returncode == 0) == (
        directory_fixture == "clone"
    )
    assert not (directory / "missing.svg").exists()
    if remote_url is not None:
        real_git(directory, "remote", "set-url", "origin", remote_url)
        assert (
            real_git(directory, "config", "--get", "remote.origin.url").stdout == remote_url + "\n"
        )
    if pin is not None:
        track_board_config(directory, pin)
        assert real_git(directory, "show", "HEAD:.aco/board.toml").stdout == pin
    monkeypatch.setattr(
        session,
        "run_context",
        lambda repo: session.RunContext(
            repo, build_forge=session._build_forge, directory=directory
        ),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("context refusal must precede this boundary")

    for owner, name in boundaries:
        monkeypatch.setattr(
            owner, name, property(forbidden) if owner is session.RunContext else forbidden
        )
    capsys.readouterr()
    result = run_cli(list(arguments), capsys)
    expected = {"ok": False, "reason": reason, "message": message}
    assert (result.status, result.stderr, result.stdout, json.loads(result.stdout)) == (
        2,
        f"ERROR: {message}\n",
        json.dumps(expected) + "\n",
        expected,
    )


@pytest.mark.parametrize(
    "arguments,code,sentence,usage,stdout",
    [
        pytest.param(
            ["ask", "90", "--text", "New question?", "--default", "maybe"],
            2,
            "aco ask: error: argument --default: invalid choice: 'maybe' (choose from",
            "usage: aco ask ",
            "",
            id="invalid-default",
        )
    ],
)
def test_parser_refusal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    code: int,
    sentence: str,
    usage: str,
    stdout: str,
) -> None:
    """Spec: Never 6 — the parser rejects an invalid default before command entry."""

    def forbidden(*args, **kwargs):
        pytest.fail("invalid default reached the ask command entry")

    monkeypatch.setitem(cli._COMMANDS, "ask", replace(cli._COMMANDS["ask"], run=forbidden))
    capsys.readouterr()
    with pytest.raises(SystemExit) as raised:
        cli.main(arguments)
    captured = capsys.readouterr()
    assert (
        raised.value.code,
        "".join(captured.err.splitlines()[-1:])[: len(sentence)],
        captured.err[: len(usage)],
        captured.out,
    ) == (code, sentence, usage, stdout)
