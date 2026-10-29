"""Rule through a real GitHub checkout, injecting only at the forge boundary."""

from __future__ import annotations

import json
import tomllib
from dataclasses import replace

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import (
    FROZEN_CLI_NOW,
    freeze_cli_now,
    real_git,
    run_cli,
    track_board_config,
)
from github_fixtures import FakeForge, serve_forge
from option_cards import (
    GOLDEN_CARD_HASH,
    YES_NO_LINE,
    card,
    decide,
    other_arguments,
    ruled_card,
)

from aco import board_read, body, cli, expectations, forge, github, session, store


def json_wire(stdout: str) -> dict[str, object]:
    """Parse a JSON wire; empty stdout parses to nothing so the comparison shows it."""
    return json.loads(stdout) if stdout else {}


def option_item(*lines: str) -> str:
    """An item body whose expectation lines are `lines`, in order."""
    return block_body(MINIMAL_BLOCK_TOML + "\n".join(lines))


def decision(letter: str = "A", *, line: int = 1) -> list[str]:
    """`rule`'s arguments after the item for a chat decision of option `letter`."""
    return decide(letter, "chat", line=line)


@pytest.mark.usefixtures("github_world")
class TestGithubRule:
    def test_rule_preserves_card_and_other_body_values(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Spec: RULE-12, Never 3 — the card and every byte outside the block survive the write."""
        freeze_cli_now(monkeypatch)
        block_text = MINIMAL_BLOCK_TOML + 'scope = ["src/aco/body.py"]\n' + YES_NO_LINE + card()
        initial = block_body(block_text, before="Vorspann\n\n", after="\nNachspann\n")
        reference = forge.ItemReference(forge.ItemState.OPEN, "Entscheidung", initial)
        client = serve_forge(monkeypatch, FakeForge(issue_references={90: reference}))
        result = run_cli(["rule", "90", *decision(line=2)], capsys)
        assert result.status == 0, result.stderr
        written = client.item_bodies[90]
        expected = tomllib.loads(block_text)
        expected["expectation"][1].update(
            ruling="A", ruled_on=FROZEN_CLI_NOW.date(), card_hash=GOLDEN_CARD_HASH, via="chat"
        )
        located = body.locate_block(written)
        assert located.data == expected
        assert written[: located.content_start] == "Vorspann\n\n```aco\n"
        assert written[located.content_end :] == "```\n\nNachspann\n"

    @pytest.mark.parametrize(
        "arguments,sentence,ruling",
        [
            pytest.param(
                decision(),
                "RULED #90 line 1 A; 1 line(s) still open\n",
                "A",
                id="option",
            ),
            pytest.param(
                other_arguments("Nur am Desktop.", line=1),
                "RULED #90 line 1 other; 1 line(s) still open\n",
                "other",
                id="other",
            ),
        ],
    )
    def test_text(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        arguments: list[str],
        sentence: str,
        ruling: str,
    ) -> None:
        """Spec: RULE-01 — RULED line; the other line stays open."""
        freeze_cli_now(monkeypatch)
        initial = option_item(card(), YES_NO_LINE)
        reference = forge.ItemReference(forge.ItemState.OPEN, "Decide something", initial)
        client = serve_forge(monkeypatch, FakeForge(issue_references={90: reference}))
        result = run_cli(["rule", "90", *arguments], capsys)
        written = expectations.expectation_lines(client.item_bodies[90])
        observed = {
            "exit": result.status,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "rulings": [line.ruling for line in written],
        }
        assert observed == {"exit": 0, "stdout": sentence, "stderr": "", "rulings": [ruling, None]}

    @pytest.mark.parametrize(
        "lines,open_remaining",
        [
            pytest.param((card(),), 0, id="none-open"),
            pytest.param((card(), YES_NO_LINE), 1, id="open-remaining"),
        ],
    )
    def test_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        lines: tuple[str, ...],
        open_remaining: int,
    ) -> None:
        """Spec: RULE-02, OUT-01 — ruled envelope, open zero or one, ordered JSON."""
        freeze_cli_now(monkeypatch)
        reference = forge.ItemReference(
            forge.ItemState.OPEN, "Decide something", option_item(*lines)
        )
        serve_forge(monkeypatch, FakeForge(issue_references={90: reference}))
        result = run_cli(["rule", "90", *decision(), "--json"], capsys)
        expected = {
            "ok": True,
            "reason": "ruled",
            "item": 90,
            "index": 1,
            "ruling": "A",
            "ruled_on": FROZEN_CLI_NOW.date().isoformat(),
            "open": open_remaining,
        }
        assert (result.status, result.stdout, result.stderr) == (
            0,
            json.dumps(expected) + "\n",
            "",
        )

    @pytest.mark.parametrize(
        "as_json", [pytest.param(False, id="text"), pytest.param(True, id="json")]
    )
    @pytest.mark.parametrize(
        "line,initial,state,is_landing,fails,message,reason",
        [
            pytest.param(
                1,
                option_item(ruled_card()),
                forge.ItemState.OPEN,
                False,
                False,
                "line 1 is already ruled; a changed ruling is a new line",
                "already_ruled",
                id="already-ruled",
            ),
            *[
                pytest.param(
                    line,
                    option_item(card()),
                    forge.ItemState.OPEN,
                    False,
                    False,
                    f"line {line} out of range: this item has 1 expectation line(s)",
                    "line_out_of_range",
                    id=case,
                )
                for line, case in ((2, "out-of-range"), (0, "out-of-range-zero"))
            ],
            pytest.param(
                1,
                "",
                forge.ItemState.MISSING,
                False,
                False,
                "#90 does not exist",
                "invalid_item",
                id="missing-item",
            ),
            pytest.param(
                1,
                option_item(card()),
                forge.ItemState.OPEN,
                True,
                False,
                "#90 is a pull request, not an issue; rule needs an issue",
                "invalid_item",
                id="pull-request",
            ),
            pytest.param(
                1,
                "## Now\nOld prose.\n",
                forge.ItemState.OPEN,
                False,
                False,
                "#90 body malformed: aco: no aco block; rule needs a valid aco block",
                "invalid_item",
                id="malformed-body",
            ),
            pytest.param(
                1,
                option_item(card()),
                forge.ItemState.OPEN,
                False,
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
        line: int,
        initial: str,
        state: forge.ItemState,
        is_landing: bool,
        fails: bool,
        message: str,
        reason: str,
        as_json: bool,
    ) -> None:
        """Spec: RULE-04, RULE-05, RULE-07, RULE-08, RULE-09, RULE-11,
        RULE-28, Never 2, OUT-01 — refuse invalid targets and failed writes with ERROR.
        """
        reference = forge.ItemReference(state, "Decide something", initial, is_landing)
        client = serve_forge(
            monkeypatch,
            FakeForge(
                issue_references={90: reference},
                fail_update_item_body=fails,
            ),
        )
        result = run_cli(
            ["rule", "90", *decision(line=line), *(["--json"] if as_json else [])], capsys
        )
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


@pytest.mark.parametrize("as_json", [pytest.param(False, id="text"), pytest.param(True, id="json")])
@pytest.mark.parametrize(
    "directory_fixture,remote_url,pin,arguments,boundaries,message,reason,explicit_directory",
    [
        pytest.param(
            "clone",
            "file:///srv/git/agent-coordination.git",
            None,
            ("rule", "90", *decision()),
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
            ("--repo", "acme/items", "rule", "258", *decision()),
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
            ("rule", "90", *decision()),
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
            "aco rule: error: one of the arguments --option --other --unclear is required",
            id="no-outcome",
        ),
        pytest.param(
            ["rule", "90", *decision(), "--yes"],
            "aco: error: unrecognized arguments: --yes",
            id="yes",
        ),
        pytest.param(
            ["rule", "90", *decision(), "--no"],
            "aco: error: unrecognized arguments: --no",
            id="no",
        ),
        pytest.param(
            ["rule", "90", *decision(), "--later"],
            "aco: error: unrecognized arguments: --later",
            id="later",
        ),
        pytest.param(
            ["rule", "90", "--line", "1", "--other", "Anders", "--option", "A"],
            "aco rule: error: argument --option: not allowed with argument --other",
            id="other-and-option",
        ),
        pytest.param(
            ["rule", "90", "--line", "1", "--option", "A", "--unclear"],
            "aco rule: error: argument --unclear: not allowed with argument --option",
            id="option-and-unclear",
        ),
        pytest.param(
            ["rule", "90", "--line", "1", "--option", "A", "--via", "phone"],
            "aco rule: error: argument --via: invalid choice: 'phone'",
            id="unknown-via",
        ),
    ],
)
def test_parser_refusal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    sentence: str,
) -> None:
    """Spec: Never 1 — parser requires exactly one of --option, --other, --unclear, refuses
    the retired yes/no flags and a known --via before command entry."""

    def forbidden(*args, **kwargs):
        pytest.fail("invalid outcomes reached the rule command entry")

    monkeypatch.setitem(cli._COMMANDS, "rule", replace(cli._COMMANDS["rule"], run=forbidden))
    capsys.readouterr()
    with pytest.raises(SystemExit) as raised:
        cli.main(arguments)
    captured = capsys.readouterr()
    usage = "usage: aco "
    observed = {
        "code": raised.value.code,
        "sentence": "".join(captured.err.splitlines()[-1:])[: len(sentence)],
        "usage": captured.err[: len(usage)],
        "stdout": captured.out,
    }
    assert observed == {"code": 2, "sentence": sentence, "usage": usage, "stdout": ""}


def test_usage_and_help_name_every_flag_with_a_help_line_unclear_included(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: Never 1 — usage and --help name the answer flags, --unclear among them."""
    with pytest.raises(SystemExit):
        cli.main(["rule", "90", "--line", "1"])
    usage_text = capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["rule", "--help"])
    help_text = capsys.readouterr().out
    shown = ("--option", "--other", "--unclear", "--via", "--card-hash")
    retired = ("--yes", "--no", "--later")
    assert [flag in usage_text for flag in ("--option", "--other", "--unclear")] == [True] * 3
    assert [flag in help_text for flag in shown] == [True] * len(shown)
    assert " ".join(help_text.split()).count("send an open option line back to its head") == 1
    words = (usage_text + help_text).replace("[", " ").replace("]", " ").split()
    assert [flag in words for flag in retired] == [False] * len(retired)
