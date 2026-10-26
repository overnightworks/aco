"""Rule through a real GitHub checkout, injecting only at the forge boundary."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import cast

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body, board_issue
from cli_fixtures import (
    FROZEN_CLI_NOW,
    freeze_cli_now,
    real_git,
    run_cli,
    track_board_config,
)
from github_fixtures import FakeForge, assert_github_world, serve_forge

from aco import board_read, body, cli, expectations, forge, github, session, store


@dataclass(frozen=True)
class RuleInput:
    arguments: tuple[str, ...]
    initial_body: str


def json_wire(stdout: str) -> dict[str, object]:
    """Parse a JSON wire; empty stdout parses to nothing so the comparison shows it."""
    return json.loads(stdout) if stdout else {}


@pytest.fixture
def github_world(github_clone: Path, bare_remote: Path) -> None:
    assert_github_world(github_clone, bare_remote)


@pytest.mark.usefixtures(github_world.__name__)
class TestGithubRule:
    @pytest.mark.parametrize("ruling", ["yes", "no", "later"])
    @pytest.mark.parametrize("note", [None, "Ja, mit Rückweg."])
    @pytest.mark.parametrize("with_card", [True, False], ids=["card", "no-card"])
    def test_rule_preserves_card_and_other_body_values(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        ruling: str,
        note: str | None,
        with_card: bool,
    ) -> None:
        """Spec: RULE-12, RULE-03 — retain card data through write and fresh rulings read."""
        freeze_cli_now(monkeypatch)
        card = (
            'question = "Änderung behalten?"\nexample = "Ein Skript bleibt nutzbar."\n'
            "picture = '<svg xmlns=\"http://www.w3.org/2000/svg\"><text>ä</text></svg>'\n"
            if with_card
            else ""
        )
        untouched = '[[expectation]]\ntext = "Andere Zeile"\ndefault = "no"\n' + card
        block_text = (
            MINIMAL_BLOCK_TOML
            + 'scope = ["src/aco/body.py"]\n'
            + untouched
            + '[[expectation]]\ntext = "Ship it?"\ndefault = "later"\n'
            + card
            + untouched
        )
        initial = block_body(block_text, before="Vorspann\n\n", after="\nNachspann\n")
        reference = forge.ItemReference(forge.ItemState.OPEN, "Entscheidung", initial)
        client = serve_forge(monkeypatch, FakeForge(issue_references={90: reference}))
        arguments = ["rule", "90", "--line", "2", f"--{ruling}"]
        result = run_cli(arguments + ([] if note is None else ["--note", note]), capsys)
        assert result.status == 0, result.stderr
        written = client.item_bodies[90]
        expected = tomllib.loads(block_text)
        target = expected["expectation"][1]
        del target["default"]
        target.update(ruling=ruling, ruled_on=FROZEN_CLI_NOW.date())
        target["text"] = "Ship it?" if note is None else f"Ship it? Anmerkung: {note}"
        located = body.locate_block(written)
        assert located.data == expected
        assert written[: located.content_start] == "Vorspann\n\n```aco\n"
        assert written[located.content_end :] == "```\n\nNachspann\n"
        client.board_issues = (board_issue(90, "Entscheidung", written),)
        reread = run_cli(["rulings", "--json"], capsys)
        assert reread.status == 0, reread.stderr
        line = json.loads(reread.stdout)["rulings"][0]["lines"][1]
        assert line.pop("card_hash").startswith("sha256:")
        assert line == {
            "index": 2,
            "form": "yes_no",
            "text": target["text"],
            "ruling": ruling,
            "ruled_on": FROZEN_CLI_NOW.date().isoformat(),
            "default": None,
            **{key: target[key] for key in ("question", "example", "picture") if key in target},
        }

    @pytest.mark.parametrize(
        "scenario,observe,expected",
        [
            pytest.param(
                RuleInput(
                    (flag,),
                    block_body(
                        MINIMAL_BLOCK_TOML
                        + '[[expectation]]\ntext = "Ship it?"\ndefault = "later"\n'
                        '[[expectation]]\ntext = "Ship it too?"\ndefault = "later"\n'
                    ),
                ),
                lambda written: {
                    **{
                        f"e{index + 1}.{key}": value
                        for index in (0, 1)
                        for key, value in asdict(
                            expectations.expectation_lines(written[90])[index]
                        ).items()
                    },
                },
                {
                    "exit": 0,
                    "stdout": sentence,
                    "stderr": "",
                    **{
                        f"e{index + 1}.{key}": value
                        for index, entry in enumerate(
                            (
                                expectations.YesNoLine(
                                    1, "Ship it?", ruling, FROZEN_CLI_NOW.date()
                                ),
                                expectations.YesNoLine(
                                    2, "Ship it too?", None, None, default="later"
                                ),
                            )
                        )
                        for key, value in asdict(entry).items()
                    },
                },
                id=ruling,
            )
            for flag, ruling, sentence in (
                ("--yes", "yes", "RULED #90 line 1 yes; 1 line(s) still open\n"),
                ("--no", "no", "RULED #90 line 1 no; 1 line(s) still open\n"),
                ("--later", "later", "RULED #90 line 1 later; 1 line(s) still open\n"),
            )
        ]
        + [
            pytest.param(
                RuleInput(
                    ("--yes", "--note", "Ja, sofort."),
                    block_body(
                        MINIMAL_BLOCK_TOML
                        + '[[expectation]]\ntext = "Ship it?"\ndefault = "later"\n'
                    ),
                ),
                lambda written: {
                    "text": cast(
                        list[dict[str, object]], body.locate_block(written[90]).data["expectation"]
                    )[0]["text"],
                    "keys": set(
                        cast(
                            list[dict[str, object]],
                            body.locate_block(written[90]).data["expectation"],
                        )[0]
                    ),
                },
                {
                    "exit": 0,
                    "stdout": "RULED #90 line 1 yes; 0 line(s) still open\n",
                    "stderr": "",
                    "text": "Ship it? Anmerkung: Ja, sofort.",
                    "keys": {"text", "ruling", "ruled_on"},
                },
                id="note",
            ),
            pytest.param(
                RuleInput(
                    ("--yes",),
                    block_body(
                        MINIMAL_BLOCK_TOML
                        + '[[expectation]]\ntext = "Ship it?"\ndefault = "later"\n'
                        '[[slice]]\nindex = 1\ntitle = "Bad\\u000Btitle"\n'
                    ),
                ),
                lambda written: {"written keys": tuple(written)},
                {
                    "exit": 0,
                    "stdout": "RULED #90 line 1 yes; 0 line(s) still open\n",
                    "stderr": "",
                    "written keys": (90,),
                },
                id="display-control",
            ),
        ],
    )
    def test_text(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        scenario: RuleInput,
        observe: Callable[[dict[int, str]], dict[str, object]],
        expected: dict[str, object],
    ) -> None:
        """Spec: RULE-01, RULE-03, BODY-63, BODY-66 — RULED, note in text, legacy body accepted."""
        freeze_cli_now(monkeypatch)
        reference = forge.ItemReference(
            forge.ItemState.OPEN, "Decide something", scenario.initial_body
        )
        client = serve_forge(monkeypatch, FakeForge(issue_references={90: reference}))
        assert client.issue_references == {90: reference}
        assert client.item_bodies == {}
        capsys.readouterr()
        result = run_cli(["rule", "90", "--line", "1", *scenario.arguments], capsys)
        written_state = (
            observe(client.item_bodies)
            if 90 in client.item_bodies
            else {"written": client.item_bodies}
        )
        observed = {
            "exit": result.status,
            "stdout": result.stdout,
            "stderr": result.stderr,
            **written_state,
        }
        assert observed == expected

    @pytest.mark.parametrize(
        "scenario,expected",
        [
            pytest.param(
                RuleInput(
                    ("--yes",),
                    block_body(
                        MINIMAL_BLOCK_TOML
                        + '[[expectation]]\ntext = "Ship it?"\ndefault = "later"\n'
                    ),
                ),
                {
                    "ok": True,
                    "reason": "ruled",
                    "item": 90,
                    "index": 1,
                    "ruling": "yes",
                    "ruled_on": FROZEN_CLI_NOW.date().isoformat(),
                    "open": 0,
                },
                id="yes",
            ),
            pytest.param(
                RuleInput(
                    ("--later",),
                    block_body(
                        MINIMAL_BLOCK_TOML
                        + '[[expectation]]\ntext = "Ship it?"\ndefault = "later"\n'
                        '[[expectation]]\ntext = "Ship it too?"\ndefault = "later"\n'
                    ),
                ),
                {
                    "ok": True,
                    "reason": "ruled",
                    "item": 90,
                    "index": 1,
                    "ruling": "later",
                    "ruled_on": FROZEN_CLI_NOW.date().isoformat(),
                    "open": 1,
                },
                id="open-remaining",
            ),
        ],
    )
    def test_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        scenario: RuleInput,
        expected: dict[str, object],
    ) -> None:
        """Spec: RULE-02, OUT-01 — ruled envelope, open zero or one, ordered JSON."""
        freeze_cli_now(monkeypatch)
        reference = forge.ItemReference(
            forge.ItemState.OPEN, "Decide something", scenario.initial_body
        )
        client = serve_forge(monkeypatch, FakeForge(issue_references={90: reference}))
        assert client.issue_references == {90: reference}
        assert client.item_bodies == {}
        capsys.readouterr()
        result = run_cli(["rule", "90", "--line", "1", *scenario.arguments, "--json"], capsys)
        parsed = json_wire(result.stdout)
        observed = {
            "exit": result.status,
            "wire": result.stdout,
            "stderr": result.stderr,
            "keys": set(parsed),
            **parsed,
        }
        assert observed == {
            "exit": 0,
            "wire": json.dumps(expected) + "\n",
            "stderr": "",
            "keys": set(expected),
            **expected,
        }

    @pytest.mark.parametrize(
        "as_json", [pytest.param(False, id="text"), pytest.param(True, id="json")]
    )
    @pytest.mark.parametrize(
        "arguments,initial,state,is_landing,capability,fails,message,reason",
        [
            pytest.param(
                ("--line", "1", "--no"),
                block_body(
                    MINIMAL_BLOCK_TOML
                    + '[[expectation]]\ntext = "Ship it?"\nruling = "yes"\nruled_on = 2026-08-01\n'
                    'question = "Behalten?"\nexample = "Es bleibt so."\n'
                    "picture = '<svg xmlns=\"http://www.w3.org/2000/svg\"/>'\n"
                ),
                forge.ItemState.OPEN,
                False,
                None,
                False,
                "line 1 is already ruled; a changed ruling is a new line",
                "already_ruled",
                id="already-ruled",
            ),
            *[
                pytest.param(
                    ("--line", line, "--yes"),
                    block_body(
                        MINIMAL_BLOCK_TOML
                        + '[[expectation]]\ntext = "Ship it?"\ndefault = "later"\n'
                    ),
                    forge.ItemState.OPEN,
                    False,
                    None,
                    False,
                    message,
                    "line_out_of_range",
                    id=case,
                )
                for line, message, case in (
                    (
                        "2",
                        "line 2 out of range: this item has 1 expectation line(s)",
                        "out-of-range",
                    ),
                    (
                        "0",
                        "line 0 out of range: this item has 1 expectation line(s)",
                        "out-of-range-zero",
                    ),
                )
            ],
            pytest.param(
                ("--line", "1", "--yes"),
                block_body(
                    MINIMAL_BLOCK_TOML + '[[expectation]]\ntext = "Ship it?"\ndefault = "later"\n'
                ),
                forge.ItemState.OPEN,
                False,
                forge.Capability.READ_ONLY,
                False,
                "this forge cannot update_item_body; rule by hand",
                "unavailable",
                id="read-only",
            ),
            pytest.param(
                ("--line", "1", "--yes"),
                "",
                forge.ItemState.MISSING,
                False,
                None,
                False,
                "#90 does not exist",
                "invalid_item",
                id="missing-item",
            ),
            pytest.param(
                ("--line", "1", "--yes"),
                block_body(
                    MINIMAL_BLOCK_TOML + '[[expectation]]\ntext = "Ship it?"\ndefault = "later"\n'
                ),
                forge.ItemState.OPEN,
                True,
                None,
                False,
                "#90 is a pull request, not an issue; rule needs an issue",
                "invalid_item",
                id="pull-request",
            ),
            pytest.param(
                ("--line", "1", "--yes"),
                "## Now\nOld prose.\n",
                forge.ItemState.OPEN,
                False,
                None,
                False,
                "#90 body malformed: aco: no aco block; rule needs a valid aco block",
                "invalid_item",
                id="malformed-body",
            ),
            pytest.param(
                ("--line", "1", "--yes"),
                block_body(
                    MINIMAL_BLOCK_TOML + '[[expectation]]\ntext = "Ship it?"\ndefault = "later"\n'
                ),
                forge.ItemState.OPEN,
                False,
                None,
                True,
                "update item body failed (simulated)",
                "unavailable",
                id="write-failure",
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
        capability: forge.Capability | None,
        fails: bool,
        message: str,
        reason: str,
        as_json: bool,
    ) -> None:
        """Spec: RULE-04, RULE-05, RULE-06, RULE-07, RULE-08, RULE-09, RULE-11,
        ASK-05, Never 2, OUT-01 — refuse invalid targets and failed writes with ERROR.
        """
        reference = forge.ItemReference(state, "Decide something", initial, is_landing)
        capabilities = (
            {} if capability is None else {forge.ForgeOperation.UPDATE_ITEM_BODY: capability}
        )
        client = serve_forge(
            monkeypatch,
            FakeForge(
                issue_references={90: reference},
                capability_overrides=capabilities,
                fail_update_item_body=fails,
            ),
        )
        assert client.issue_references == {90: reference}
        assert client.capability_overrides == capabilities
        assert client.fail_update_item_body == fails
        assert client.item_bodies == {}
        capsys.readouterr()
        result = run_cli(["rule", "90", *arguments, *(["--json"] if as_json else [])], capsys)
        expected = {"ok": False, "reason": reason, "message": message}
        observed = {
            "exit": result.status,
            "stderr": result.stderr,
            "stdout": result.stdout,
            **(json_wire(result.stdout) if as_json else {}),
            "writes": client.item_bodies if not fails else None,
        }
        assert observed == {
            "exit": 2,
            "stderr": f"ERROR: {message}\n",
            "stdout": json.dumps(expected) + "\n" if as_json else "",
            **(expected if as_json else {}),
            "writes": {} if not fails else None,
        }

    @pytest.mark.parametrize(
        "initial,expected",
        [
            pytest.param(
                block_body(
                    MINIMAL_BLOCK_TOML + '[[expectation]]\ntext = "Ship it?"\ndefault = "later"\n',
                    before="Preamble stays.\n\n",
                    after="\nTail stays.\n",
                ),
                {"prefix": "Preamble stays.\n\n```aco\n", "suffix": "```\n\nTail stays.\n"},
                id="surrounding-bytes",
            )
        ],
    )
    def test_persistence(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        initial: str,
        expected: dict[str, str],
    ) -> None:
        """Spec: Never 3 — preserve bytes outside the block; the stronger entry claim is open."""
        freeze_cli_now(monkeypatch)
        reference = forge.ItemReference(forge.ItemState.OPEN, "Decide something", initial)
        client = serve_forge(monkeypatch, FakeForge(issue_references={90: reference}))
        assert client.issue_references == {90: reference}
        assert client.item_bodies == {}
        capsys.readouterr()
        run_cli(["rule", "90", "--line", "1", "--yes"], capsys)
        written = client.item_bodies[90]
        block = body.locate_block(written)
        observed = {
            "prefix": written[: block.content_start],
            "suffix": written[block.content_end :],
        }
        assert observed == expected


@pytest.mark.parametrize("as_json", [pytest.param(False, id="text"), pytest.param(True, id="json")])
@pytest.mark.parametrize(
    "directory_fixture,remote_url,pin,arguments,boundaries,message,reason,explicit_directory",
    [
        pytest.param(
            "clone",
            "file:///srv/git/agent-coordination.git",
            None,
            ("rule", "90", "--line", "1", "--yes"),
            ((github, "discover_repository"),),
            "no forge adapter for host file",
            "unavailable",
            False,
            id="host",
        ),
        pytest.param(
            "clone",
            None,
            'storage = "state-ref"\n',
            ("--repo", "acme/items", "rule", "258", "--line", "1", "--yes"),
            ((github, "GitHubForge"), (store, "fetch_state")),
            "--repo is meaningless under storage = state-ref",
            "invalid_usage",
            False,
            id="state-ref-repo",
        ),
        pytest.param(
            "tmp_path",
            None,
            None,
            ("rule", "90", "--line", "1", "--yes"),
            (
                (github, "discover_repository"),
                (github, "GitHubForge"),
                (board_read, "item_body_or_refuse"),
            ),
            "this command reads the repository's body contract from .aco/board.toml and needs "
            "a checkout (a shallow one is enough): fatal: not a git repository "
            "(or any of the parent directories): .git",
            "unavailable",
            True,
            id="checkout",
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
    explicit_directory: bool,
    as_json: bool,
) -> None:
    """Spec: RULE-09, RULE-10, PIN-04, BOARD-02, CHECK-10, Never 4 — ERROR before forbidden work."""
    directory = request.getfixturevalue(directory_fixture)
    monkeypatch.chdir(directory)
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("GIT_DISCOVERY_ACROSS_FILESYSTEM", "1")
    assert (real_git(directory, "rev-parse", "--show-toplevel", check=False).returncode == 0) == (
        directory_fixture == "clone"
    )
    if remote_url is not None:
        real_git(directory, "remote", "set-url", "origin", remote_url)
        assert (
            real_git(directory, "config", "--get", "remote.origin.url").stdout == remote_url + "\n"
        )
    if pin is not None:
        track_board_config(directory, pin)
        assert real_git(directory, "show", "HEAD:.aco/board.toml").stdout == pin
    if explicit_directory:
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
        monkeypatch.setattr(owner, name, forbidden)
    capsys.readouterr()
    result = run_cli([*arguments, *(["--json"] if as_json else [])], capsys)
    expected = {"ok": False, "reason": reason, "message": message}
    observed = {
        "exit": result.status,
        "stderr": result.stderr,
        "stdout": result.stdout,
        **(json_wire(result.stdout) if as_json else {}),
    }
    assert observed == {
        "exit": 2,
        "stderr": f"ERROR: {message}\n",
        "stdout": json.dumps(expected) + "\n" if as_json else "",
        **(expected if as_json else {}),
    }


@pytest.mark.parametrize(
    "arguments,sentence",
    [
        pytest.param(
            ["rule", "90", "--line", "1"],
            "aco rule: error: one of the arguments --yes --no --later is required",
            id="no-outcome",
        ),
        pytest.param(
            ["rule", "90", "--line", "1", "--yes", "--no"],
            "aco rule: error: argument --no: not allowed with argument --yes",
            id="two-outcomes",
        ),
    ],
)
def test_parser_refusal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    sentence: str,
) -> None:
    """Spec: Never 1 — parser requires exactly one of --yes, --no, --later before command entry."""

    def forbidden(*args, **kwargs):
        pytest.fail("invalid outcomes reached the rule command entry")

    monkeypatch.setitem(cli._COMMANDS, "rule", replace(cli._COMMANDS["rule"], run=forbidden))
    capsys.readouterr()
    with pytest.raises(SystemExit) as raised:
        cli.main(arguments)
    captured = capsys.readouterr()
    usage = "usage: aco rule "
    observed = {
        "code": raised.value.code,
        "sentence": "".join(captured.err.splitlines()[-1:])[: len(sentence)],
        "usage": captured.err[: len(usage)],
        "stdout": captured.out,
    }
    assert observed == {"code": 2, "sentence": sentence, "usage": usage, "stdout": ""}
