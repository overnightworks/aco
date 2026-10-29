"""Real-pipe CLI proofs for `aco check -`; field grammar lives in test_board."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import NamedTuple, TextIO

import pytest
from board_fixtures import BIDI_AND_ZERO_WIDTH_CONTROLS, MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import (
    body_file_on_stdin,
    closed_stdin,
    devnull_on_stdin,
    empty_harness_socket_on_stdin,
    forbid_forge_resolution,
    piped_body_on_stdin,
    real_git,
    run_cli,
    terminal_on_stdin,
    track_board_config,
)

from aco import body, process, report, store


@pytest.fixture
def tracked_default_pin(clone: Path) -> Path:
    """The command starts with the real, tracked default pin."""
    assert (clone / ".aco/board.toml").read_text() == ""
    assert real_git(clone, "ls-files", ".aco/board.toml").stdout == ".aco/board.toml\n"
    return clone


@pytest.fixture(params=[pytest.param(False, id="text"), pytest.param(True, id="json")])
def as_json(request: pytest.FixtureRequest) -> bool:
    return request.param


_RECORD_TOML = (
    '\n[record]\ntitle = "T"\nstate = "open"\nlabels = []\nblocked_by = []\n'
    'created_at = "2026-09-10T00:00:00Z"\nupdated_at = "2026-09-15T00:00:00Z"\n'
)


@pytest.fixture(
    params=[
        pytest.param(
            (
                (),
                False,
                [],
                ".aco/board.toml was removed on this branch; restore it with "
                "git checkout origin/main -- :/.aco/board.toml",
            ),
            id="absent",
        ),
        pytest.param(
            (
                ("--cached",),
                True,
                [""],
                ".aco/board.toml is not tracked in this checkout, "
                "so its storage pin cannot be trusted: git add -f .aco/board.toml",
            ),
            id="untracked",
        ),
    ]
)
def untrusted_pin(request: pytest.FixtureRequest, tracked_default_pin: Path) -> str:
    """Change the real index, preserving the committed pin on main."""
    clone = tracked_default_pin
    remove_arguments, file_stays, contents, message = request.param
    real_git(clone, "rm", *remove_arguments, ".aco/board.toml")
    assert real_git(clone, "ls-files", ".aco/board.toml").stdout == ""
    assert real_git(clone, "show", "origin/main:.aco/board.toml").stdout == ""
    assert real_git(clone, "show", "HEAD:.aco/board.toml").stdout == ""
    assert (clone / ".aco/board.toml").exists() is file_stays
    assert [path.read_text() for path in clone.glob(".aco/board.toml")] == contents
    return message


class StoragePin(NamedTuple):
    arrange: str
    text: str
    defects: list[str]
    verdict: str
    ok: bool
    exit_code: int
    stream: str
    output: str


@pytest.fixture
def tracked_state_ref_pin(tracked_default_pin: Path) -> Path:
    track_board_config(tracked_default_pin, 'storage = "state-ref"\n')
    return tracked_default_pin


@pytest.fixture(
    params=[
        pytest.param(
            StoragePin(
                "tracked_default_pin",
                "",
                ["body malformed: record: unknown top-level key record"],
                "malformed",
                False,
                2,
                "stderr",
                "body malformed: record: unknown top-level key record\n",
            ),
            id="record-default",
        ),
        pytest.param(
            StoragePin(
                "tracked_state_ref_pin",
                'storage = "state-ref"\n',
                [],
                "valid",
                True,
                0,
                "stdout",
                "body ok\n",
            ),
            id="record-state-ref",
        ),
    ]
)
def storage_pin(request: pytest.FixtureRequest) -> StoragePin:
    """Each row supplies a real tracked pin and its expected command result."""
    pin: StoragePin = request.param
    clone: Path = request.getfixturevalue(pin.arrange)
    assert (clone / ".aco/board.toml").read_text() == pin.text
    assert real_git(clone, "ls-files", ".aco/board.toml").stdout == ".aco/board.toml\n"
    return pin


@pytest.mark.usefixtures("clone", "tracked_default_pin")
class TestBodyCheck:
    @pytest.mark.parametrize(
        ("raw_body", "defects", "verdict", "exit_code", "wire"),
        [
            pytest.param(
                block_body(MINIMAL_BLOCK_TOML),
                [],
                "valid",
                0,
                '{"ok": true, "reason": "valid", "defects": []}\n',
                id="minimal",
            ),
            pytest.param(
                "no block\n",
                ["body malformed: aco: no aco block"],
                "malformed",
                2,
                '{"ok": false, "reason": "malformed", '
                '"defects": ["body malformed: aco: no aco block"]}\n',
                id="no-block",
            ),
            pytest.param(
                block_body('version = 1\nnext = "X"\n'),
                [
                    "body malformed: now: now is required",
                    "body malformed: done_when: done_when is required",
                ],
                "malformed",
                2,
                '{"ok": false, "reason": "malformed", '
                '"defects": ["body malformed: now: now is required", '
                '"body malformed: done_when: done_when is required"]}\n',
                id="multiple-defects",
            ),
            pytest.param(
                block_body('version = 1\nnow = ""\nnext = ""\ndone_when = ""\n'),
                ["body incomplete: Now, Next, Done when"],
                "incomplete",
                2,
                '{"ok": false, "reason": "incomplete", '
                '"defects": ["body incomplete: Now, Next, Done when"]}\n',
                id="every-key-empty",
            ),
            pytest.param(
                block_body(
                    'version = 1\nnow = "Cut from #90"\nnext = "Build it."\ndone_when = ""\n'
                ),
                ["body incomplete: Done when"],
                "incomplete",
                2,
                '{"ok": false, "reason": "incomplete", '
                '"defects": ["body incomplete: Done when"]}\n',
                id="only-done-when-empty",
            ),
            pytest.param(
                block_body(MINIMAL_BLOCK_TOML + '"k\\u001b]0;x\\u0007" = 1\n'),
                ["body malformed: k\\x1b]0;x\\x07: unknown top-level key k\\x1b]0;x\\x07"],
                "malformed",
                2,
                r'{"ok": false, "reason": "malformed", "defects": '
                r'["body malformed: k\\x1b]0;x\\x07: unknown top-level key k\\x1b]0;x\\x07"]}'
                "\n",
                id="display-control-key-is-escaped",
            ),
            pytest.param(
                block_body(MINIMAL_BLOCK_TOML + '"a\\nb" = 1\n'),
                ["body malformed: a\\nb: unknown top-level key a\\nb"],
                "malformed",
                2,
                r'{"ok": false, "reason": "malformed", "defects": '
                r'["body malformed: a\\nb: unknown top-level key a\\nb"]}'
                "\n",
                id="line-feed-key-is-escaped",
            ),
            pytest.param(
                block_body(MINIMAL_BLOCK_TOML + '"Größe\\t\\u00a0" = 1\n'),
                ["body malformed: Größe\t\u00a0: unknown top-level key Größe\t\u00a0"],
                "malformed",
                2,
                '{"ok": false, "reason": "malformed", "defects": '
                '["body malformed: Gr\\u00f6\\u00dfe\\t\\u00a0: unknown top-level key '
                'Gr\\u00f6\\u00dfe\\t\\u00a0"]}\n',
                id="printable-key-is-unchanged",
            ),
        ],
    )
    def test_check_stdin_judges_a_piped_body(
        self,
        capsys: pytest.CaptureFixture[str],
        as_json: bool,
        raw_body: str,
        defects: list[str],
        verdict: str,
        exit_code: int,
        wire: str,
    ) -> None:
        """Spec: CHECK-17, CHECK-18, CHECK-19, BODY-12, BODY-14, BODY-68, OUT-01."""
        result = run_cli(["check", "-", *(["--json"] if as_json else [])], capsys, stdin=raw_body)
        if as_json:
            payload = json.loads(result.stdout)
            assert payload.get("defects") == defects
            assert payload.get("reason") == verdict
            assert payload.get("ok") is (exit_code == 0)
            assert set(payload) == {"ok", "reason", "defects"}
            assert result.stdout == wire
        elif defects:
            assert result.stderr == "".join(f"{defect}\n" for defect in defects)
        else:
            assert result.stdout == "body ok\n"
        if not defects:
            assert result.stderr == ""
        assert result.status == exit_code

    @pytest.mark.parametrize("raw_body", [pytest.param("", id="empty-text")])
    def test_check_stdin_judges_an_empty_pipe(
        self, capsys: pytest.CaptureFixture[str], raw_body: str
    ) -> None:
        """Spec: CHECK-18; an explicitly empty pipe is still supplied stdin."""
        result = run_cli(["check", "-"], capsys, stdin=raw_body)
        assert result.stderr == "body malformed: aco: no aco block\n"
        assert result.status == 2

    @pytest.mark.parametrize(
        ("toml_text", "reason"),
        [
            pytest.param(
                MINIMAL_BLOCK_TOML + '\n[[slice]]\nindex = 1\ntitle = "Slice A"\n'
                'done_when = "The parser reads the new key."\n',
                "",
                id="slice-row-done-when",
            ),
            pytest.param(MINIMAL_BLOCK_TOML + 'size = "M"\n', "", id="size-M"),
            pytest.param(
                MINIMAL_BLOCK_TOML + 'size = "XL"\n', "size: size must be S, M, or L", id="size-XL"
            ),
            *(
                pytest.param(
                    f"{MINIMAL_BLOCK_TOML}whole = {json.dumps(value)}\n",
                    "whole: whole reason must be one bounded non-empty line",
                    id=f"whole-{shape}",
                )
                for shape, value in (
                    ("too-long", "x" * 513),
                    ("newline", "a\nb"),
                    ("control", "a\u0007b"),
                    ("leading-space", " a"),
                    ("empty", ""),
                    ("whitespace", "   "),
                    ("not-a-string", 1),
                )
            ),
            pytest.param(f'{MINIMAL_BLOCK_TOML}whole = "{"x" * 512}"\n', "", id="whole-boundary"),
            pytest.param(
                'version = 1\nnow = "N"\nnext = "X"\n',
                "done_when: done_when is required",
                id="missing-done-when",
            ),
            pytest.param(
                f'{MINIMAL_BLOCK_TOML}owner = "x"\n',
                "owner: unknown top-level key owner",
                id="unknown-key",
            ),
            *(
                pytest.param(
                    f'{MINIMAL_BLOCK_TOML}\n[[slice]]\nindex = 1\ntitle = "Flip{control}side"\n',
                    f"slice[0].title: slice[0].title of row 1 holds {codepoint}; "
                    "a slice title stays on one line",
                    id=f"slice-title-{codepoint}",
                )
                for control, codepoint in BIDI_AND_ZERO_WIDTH_CONTROLS
            ),
            *(
                pytest.param(
                    f"{MINIMAL_BLOCK_TOML}\n[[slice]]\nindex = 1\n"
                    f'title = "A"\ndone_when = {value}\n',
                    "slice[0].done_when: slice[0].done_when must be a non-empty string",
                    id=f"slice-done-when-{shape}",
                )
                for shape, value in (("blank", '"  "'), ("not-a-string", "1"))
            ),
            pytest.param(
                f'{MINIMAL_BLOCK_TOML}\n[[slice]]\nindex = 1\ntitle = "A"\n'
                'done_when = "One\\u000bTwo"\n',
                "slice[0].done_when: slice[0].done_when of row 1 holds U+000B; "
                "a slice done_when stays on one line",
                id="slice-done-when-control",
            ),
        ],
    )
    def test_check_stdin_judges_block_fields(
        self,
        capsys: pytest.CaptureFixture[str],
        toml_text: str,
        reason: str,
    ) -> None:
        """Spec: CHECK-17, CHECK-18, BODY-58, BODY-59, BODY-61, BODY-62, BODY-63,
        BODY-65, BODY-66, BODY-67."""
        result = run_cli(["check", "-"], capsys, stdin=block_body(toml_text))
        if reason:
            assert result.stderr == f"body malformed: {reason}\n"
        else:
            assert result.stdout == "body ok\n"
        assert result.status == (2 if reason else 0)

    @pytest.mark.parametrize(
        "global_options",
        [pytest.param([], id="no-repo"), pytest.param(["--repo", "acme/items"], id="repo-ignored")],
    )
    def test_check_stdin_uses_the_storage_pin(
        self,
        capsys: pytest.CaptureFixture[str],
        as_json: bool,
        storage_pin: StoragePin,
        global_options: list[str],
    ) -> None:
        """Spec: CHECK-22, CHECK-23, BODY-15, BODY-16; the fixture verifies the tracked pin,
        and `--repo` is neither read nor refused under either storage."""
        result = run_cli(
            [*global_options, "check", "-", *(["--json"] if as_json else [])],
            capsys,
            stdin=block_body(MINIMAL_BLOCK_TOML + _RECORD_TOML),
        )
        if as_json:
            payload = json.loads(result.stdout)
            assert payload.get("defects") == storage_pin.defects
            assert payload.get("reason") == storage_pin.verdict
            assert payload.get("ok") is storage_pin.ok
        else:
            assert getattr(result, storage_pin.stream) == storage_pin.output
        assert result.status == storage_pin.exit_code

    @pytest.mark.parametrize(
        "stdin_source",
        [
            pytest.param(empty_harness_socket_on_stdin, id="harness-socket"),
            pytest.param(terminal_on_stdin, id="terminal"),
            pytest.param(devnull_on_stdin, id="devnull"),
            pytest.param(closed_stdin, id="closed"),
        ],
    )
    def test_check_stdin_refuses_a_stdin_that_carries_no_body(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
        as_json: bool,
        stdin_source: Callable[[Path], AbstractContextManager[TextIO | None]],
    ) -> None:
        """Spec: CHECK-24; a socket, terminal, `/dev/null` or closed stdin
        refuses at once and is never read (the socket is the hang)."""

        def forbidden_read() -> str:
            pytest.fail("check - must not read a stdin that carries no body")

        monkeypatch.setattr(report, "read_piped_body", forbidden_read)
        sentence = "check - needs the body on stdin: aco check - < body.md"
        with stdin_source(tmp_path) as stdin:
            monkeypatch.setattr(sys, "stdin", stdin)
            result = run_cli(["check", "-", *(["--json"] if as_json else [])], capsys)
        envelope = {"ok": False, "reason": "unavailable", "message": sentence}
        assert (result.status, result.stderr) == (2, f"ERROR: {sentence}\n")
        assert result.stdout == (json.dumps(envelope) + "\n" if as_json else "")

    def test_check_stdin_refuses_the_pin_before_a_stdin_that_carries_no_body(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
        untrusted_pin: str,
    ) -> None:
        """Spec: CHECK-24, CHECK-21; the pin refusal comes first."""
        with empty_harness_socket_on_stdin(tmp_path) as stdin:
            monkeypatch.setattr(sys, "stdin", stdin)
            result = run_cli(["check", "-"], capsys)
        assert (result.status, result.stderr) == (2, f"ERROR: {untrusted_pin}\n")

    @pytest.mark.parametrize(
        "stdin_source",
        [
            pytest.param(body_file_on_stdin, id="redirected-file"),
            pytest.param(piped_body_on_stdin, id="pipe"),
        ],
    )
    def test_check_stdin_judges_a_file_or_a_pipe_on_stdin(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
        stdin_source: Callable[[Path], AbstractContextManager[TextIO | None]],
    ) -> None:
        """Spec: CHECK-24; a redirected file or a pipe carries a body."""
        with stdin_source(tmp_path) as stdin:
            monkeypatch.setattr(sys, "stdin", stdin)
            result = run_cli(["check", "-"], capsys)
        assert (result.status, result.stdout, result.stderr) == (0, "body ok\n", "")

    @pytest.mark.parametrize("raw_body", [pytest.param(b"\xff", id="invalid-utf8")])
    def test_check_stdin_refuses_undecodable_input(
        self,
        capsys: pytest.CaptureFixture[str],
        as_json: bool,
        raw_body: bytes,
    ) -> None:
        """Spec: CHECK-20, CHECK-19 unavailable; real bytes cross the strict decoder."""
        message = (
            "stdin is not valid UTF-8: 'utf-8' codec can't decode byte 0xff in position 0: "
            "invalid start byte; pipe the body as UTF-8 text"
        )
        result = run_cli(["check", "-", *(["--json"] if as_json else [])], capsys, stdin=raw_body)
        if as_json:
            payload = json.loads(result.stdout)
            assert payload.get("message") == message
            assert payload.get("reason") == "unavailable"
            assert payload.get("ok") is False
        assert result.stderr == f"ERROR: {message}\n"
        assert result.status == 2

    def test_check_stdin_refuses_an_untrusted_pin(
        self,
        capsys: pytest.CaptureFixture[str],
        as_json: bool,
        untrusted_pin: str,
    ) -> None:
        """Spec: CHECK-21, PIN-01, PIN-32; trust refusal, independent of read ordering."""
        result = run_cli(
            ["check", "-", *(["--json"] if as_json else [])],
            capsys,
            stdin=block_body(MINIMAL_BLOCK_TOML),
        )
        if as_json:
            payload = json.loads(result.stdout)
            assert payload.get("message") == untrusted_pin
            assert payload.get("reason") == "unavailable"
            assert payload.get("ok") is False
        assert result.stderr == f"ERROR: {untrusted_pin}\n"
        assert result.status == 2

    @pytest.mark.usefixtures("untrusted_pin")
    def test_check_stdin_checks_the_pin_before_reading_stdin(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        as_json: bool,
    ) -> None:
        """Spec: CHECK-21; the pin refusal precedes any stdin read."""

        def forbidden_read() -> str:
            pytest.fail("check - must trust the pin before reading stdin")

        monkeypatch.setattr(report, "read_piped_body", forbidden_read)
        run_cli(
            ["check", "-", *(["--json"] if as_json else [])],
            capsys,
            stdin=block_body(MINIMAL_BLOCK_TOML),
        )

    @pytest.mark.parametrize("raw_body", [pytest.param(b"\xff", id="invalid-utf8")])
    def test_check_stdin_decodes_before_parsing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        as_json: bool,
        raw_body: bytes,
    ) -> None:
        """Spec: CHECK-20; decoding refusal precedes any body parse."""

        def forbidden_parse(*args: object, **kwargs: object) -> None:
            pytest.fail("check - must decode before parsing")

        monkeypatch.setattr(body, "body_shape_check", forbidden_parse)
        run_cli(["check", "-", *(["--json"] if as_json else [])], capsys, stdin=raw_body)

    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param(["body"], id="bare"),
            pytest.param(["body", "--check"], id="check-flag"),
        ],
    )
    def test_body_is_an_unknown_command(
        self, capsys: pytest.CaptureFixture[str], argv: list[str]
    ) -> None:
        """Spec: CHECK-16; no alias is left behind."""
        result = run_cli(argv, capsys, stdin=block_body(MINIMAL_BLOCK_TOML))
        assert "invalid choice: 'body'" in result.stderr
        assert result.status == 2

    def test_check_stdin_never_touches_a_forge_the_store_or_gh(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Spec: CHECK-17, check - Never; each forbidden boundary has its own injected fault."""
        forbid_forge_resolution(monkeypatch)

        def forbidden_store(*args: object, **kwargs: object) -> None:
            pytest.fail("check - must not fetch the store")

        monkeypatch.setattr(store, "fetch_state", forbidden_store)
        for name in ("run_captured", "run_bounded", "run_bounded_captured"):
            launch = getattr(process, name)

            def without_gh(arguments, *, _launch=launch, **kwargs):
                assert arguments[0] != "gh", "check - must not launch gh"
                return _launch(arguments, **kwargs)

            monkeypatch.setattr(process, name, without_gh)
        result = run_cli(["check", "-"], capsys, stdin=block_body(MINIMAL_BLOCK_TOML))
        assert result.stdout == "body ok\n"
        assert result.status == 0


@pytest.mark.usefixtures("outside_a_checkout")
def test_check_stdin_outside_a_checkout_refuses_before_reading_stdin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    as_json: bool,
) -> None:
    """Spec: CHECK-25; the storage pin needs a checkout, so the refusal
    is CHECK-10's sentence and the piped body stays unread."""

    def forbidden_read() -> str:
        pytest.fail("check - must find a checkout before reading stdin")

    monkeypatch.setattr(report, "read_piped_body", forbidden_read)
    result = run_cli(
        ["check", "-", *(["--json"] if as_json else [])],
        capsys,
        stdin=block_body(MINIMAL_BLOCK_TOML),
    )
    prefix = (
        "ERROR: this command reads the repository's body contract from .aco/board.toml "
        "and needs a checkout (a shallow one is enough): "
    )
    assert (result.status, result.stderr.startswith(prefix)) == (2, True)
    if as_json:
        payload = json.loads(result.stdout)
        assert (payload["ok"], payload["reason"]) == (False, "unavailable")
