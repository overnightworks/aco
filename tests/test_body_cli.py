"""Real-pipe CLI proofs for specs/body.spec.md; field grammar lives in test_board."""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

import pytest
from board_fixtures import BIDI_AND_ZERO_WIDTH_CONTROLS, MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import forbid_forge_resolution, real_git, run_cli, track_board_config

from agent_coordination import body, cmd_body, process, store


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
        ],
    )
    def test_body_check_judges_a_piped_body(
        self,
        capsys: pytest.CaptureFixture[str],
        as_json: bool,
        raw_body: str,
        defects: list[str],
        verdict: str,
        exit_code: int,
        wire: str,
    ) -> None:
        """Spec: BDY-07, BDY-08, BDY-09, BODY-12, BODY-14, OUT-01."""
        result = run_cli(
            ["body", "--check", *(["--json"] if as_json else [])], capsys, stdin=raw_body
        )
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
    def test_body_check_judges_an_empty_pipe(
        self, capsys: pytest.CaptureFixture[str], raw_body: str
    ) -> None:
        """Spec: BDY-08; an explicitly empty pipe is still supplied stdin."""
        result = run_cli(["body", "--check"], capsys, stdin=raw_body)
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
            pytest.param(
                f'{MINIMAL_BLOCK_TOML}\n[[expectation]]\ntext = "x"\n'
                'default = "yes"\nruling = "yes"\n',
                "expectation[0].default: expectation[0] must be proposed (default) or ruled "
                "(ruling, ruled_on), not both",
                id="default-and-ruling",
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
    def test_body_check_judges_block_fields(
        self,
        capsys: pytest.CaptureFixture[str],
        toml_text: str,
        reason: str,
    ) -> None:
        """Spec: BDY-07, BDY-08, BODY-58, BODY-59, BODY-61, BODY-62, BODY-63,
        BODY-65, BODY-66, BODY-67."""
        result = run_cli(["body", "--check"], capsys, stdin=block_body(toml_text))
        if reason:
            assert result.stderr == f"body malformed: {reason}\n"
        else:
            assert result.stdout == "body ok\n"
        assert result.status == (2 if reason else 0)

    def test_body_check_uses_the_storage_pin(
        self,
        capsys: pytest.CaptureFixture[str],
        as_json: bool,
        storage_pin: StoragePin,
    ) -> None:
        """Spec: BDY-12, BODY-15, BODY-16; the fixture verifies the tracked pin."""
        result = run_cli(
            ["body", "--check", *(["--json"] if as_json else [])],
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

    @pytest.mark.parametrize("raw_body", [pytest.param(b"\xff", id="invalid-utf8")])
    def test_body_check_refuses_undecodable_input(
        self,
        capsys: pytest.CaptureFixture[str],
        as_json: bool,
        raw_body: bytes,
    ) -> None:
        """Spec: BDY-10, BDY-09 unavailable; real bytes cross the strict decoder."""
        message = (
            "stdin is not valid UTF-8: 'utf-8' codec can't decode byte 0xff in position 0: "
            "invalid start byte; pipe the body as UTF-8 text"
        )
        result = run_cli(
            ["body", "--check", *(["--json"] if as_json else [])], capsys, stdin=raw_body
        )
        if as_json:
            payload = json.loads(result.stdout)
            assert payload.get("message") == message
            assert payload.get("reason") == "unavailable"
            assert payload.get("ok") is False
        assert result.stderr == f"ERROR: {message}\n"
        assert result.status == 2

    def test_body_check_refuses_an_untrusted_pin(
        self,
        capsys: pytest.CaptureFixture[str],
        as_json: bool,
        untrusted_pin: str,
    ) -> None:
        """Spec: BDY-11, PIN-01, PIN-32; trust refusal, independent of read ordering."""
        result = run_cli(
            ["body", "--check", *(["--json"] if as_json else [])],
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
    def test_body_check_checks_the_pin_before_reading_stdin(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        as_json: bool,
    ) -> None:
        """Spec: BDY-11; the pin refusal precedes any stdin read."""

        def forbidden_read() -> str:
            pytest.fail("body --check must trust the pin before reading stdin")

        monkeypatch.setattr(cmd_body, "read_body_check_input", forbidden_read)
        run_cli(
            ["body", "--check", *(["--json"] if as_json else [])],
            capsys,
            stdin=block_body(MINIMAL_BLOCK_TOML),
        )

    @pytest.mark.parametrize("raw_body", [pytest.param(b"\xff", id="invalid-utf8")])
    def test_body_check_decodes_before_parsing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        as_json: bool,
        raw_body: bytes,
    ) -> None:
        """Spec: BDY-10; decoding refusal precedes any body parse."""

        def forbidden_parse(*args: object, **kwargs: object) -> None:
            pytest.fail("body --check must decode before parsing")

        monkeypatch.setattr(body, "body_shape_check", forbidden_parse)
        run_cli(["body", "--check", *(["--json"] if as_json else [])], capsys, stdin=raw_body)

    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param(["body"], id="missing-check"),
            pytest.param(["body", "--check", "body.md"], id="file-argument"),
            pytest.param(["body", "--check", "42"], id="item-argument"),
        ],
    )
    def test_body_rejects_an_invalid_invocation(
        self, capsys: pytest.CaptureFixture[str], argv: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Spec: BDY-13, Never 2; no file or live-item positional interface."""

        def forbidden_run(*args: object, **kwargs: object) -> None:
            pytest.fail("the parser must refuse before the body command runs")

        monkeypatch.setattr(cmd_body, "run", forbidden_run)
        result = run_cli(argv, capsys, stdin=block_body(MINIMAL_BLOCK_TOML))
        assert result.status == 2

    def test_body_check_never_touches_a_forge_the_store_or_gh(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Spec: body Never 1; each forbidden boundary has its own injected fault."""
        forbid_forge_resolution(monkeypatch)

        def forbidden_store(*args: object, **kwargs: object) -> None:
            pytest.fail("body --check must not fetch the store")

        monkeypatch.setattr(store, "fetch_state", forbidden_store)
        for name in ("run_captured", "run_bounded"):
            launch = getattr(process, name)

            def without_gh(arguments, *, _launch=launch, **kwargs):
                assert arguments[0] != "gh", "body --check must not launch gh"
                return _launch(arguments, **kwargs)

            monkeypatch.setattr(process, name, without_gh)
        result = run_cli(["body", "--check"], capsys, stdin=block_body(MINIMAL_BLOCK_TOML))
        assert result.stdout == "body ok\n"
        assert result.status == 0
