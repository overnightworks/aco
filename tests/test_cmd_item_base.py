"""A whole-body `aco item edit` names the body hash `aco item show --json` printed
(`specs/item.spec.md` ITEM-70..ITEM-76), on the real checkout of a GitHub-hosted
board. The forge is the only fake. The state-ref twins live in
`test_cmd_item_base_state_ref.py`."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import run_cli
from github_fixtures import serve_forge
from item_base import edit_with_base, shown_body_hash
from item_lock_witness import LockWitnessForge

from aco import forge

pytestmark = pytest.mark.usefixtures("github_world")


@dataclass(frozen=True)
class Scenario:
    """The item every case edits and the bodies it moves between."""

    number: int
    stored: str
    replacement: str
    changed_elsewhere: str

    @property
    def argument(self) -> str:
        return str(self.number)


@pytest.fixture
def scenario() -> Scenario:
    return Scenario(
        number=72,
        stored=block_body(MINIMAL_BLOCK_TOML),
        replacement=block_body(MINIMAL_BLOCK_TOML, before="Replacement prose.\n\n"),
        changed_elsewhere=block_body(MINIMAL_BLOCK_TOML, before="Ruled in the meantime.\n\n"),
    )


type ServeItem = Callable[..., LockWitnessForge]


@pytest.fixture
def serve_item(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, scenario: Scenario) -> ServeItem:
    """Serves the scenario's item holding `stored` (its own stored body by default), whose reads
    answer the body last written; `answer` is what a write the forge's check answers raises,
    the body written first."""

    def serve(
        stored: str | None = None, answer: forge.ForgeBodyWrittenError | None = None
    ) -> LockWitnessForge:
        reference = forge.ItemReference(
            forge.ItemState.OPEN, "Claims", scenario.stored if stored is None else stored
        )
        client = LockWitnessForge(
            tmp_path / "item-locks", issue_references={scenario.number: reference}
        )
        client.update_item_body_error = answer
        client.update_item_body_lands_before_error = answer is not None
        return serve_forge(monkeypatch, client)

    return serve


def test_a_hash_item_show_printed_lets_item_edit_replace_the_body(
    serve_item: ServeItem, scenario: Scenario, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ITEM-70, ITEM-71 -- the edit prints `EDITED` and, under `--json`, the hash of the
    written body, which is the one a later `item show --json` prints for it."""
    client = serve_item()
    arguments = edit_with_base(scenario.argument, capsys)

    result = run_cli([*arguments, "--json"], capsys, stdin=scenario.replacement)

    assert result.status == 0
    assert client.item_bodies == {scenario.number: scenario.replacement}
    edited = json.loads(result.stdout)
    assert [edited[key] for key in ("ok", "reason", "item", "number")] == [
        True,
        "edited",
        f"#{scenario.number}",
        scenario.number,
    ]
    assert edited["body_hash"] == shown_body_hash(scenario.argument, capsys)


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_an_edit_from_a_copy_read_before_another_write_refuses_and_keeps_that_write(
    serve_item: ServeItem, scenario: Scenario, capsys: pytest.CaptureFixture[str], as_json: bool
) -> None:
    """Spec: ITEM-72 -- a base that is no longer the body's hash refuses `stale`, exit 2, and
    nothing is written."""
    client = serve_item()
    arguments = edit_with_base(scenario.argument, capsys)
    client.item_bodies[scenario.number] = scenario.changed_elsewhere
    current = shown_body_hash(scenario.argument, capsys)

    result = run_cli([*arguments, *(["--json"] * as_json)], capsys, stdin=scenario.replacement)

    base = arguments[-1]
    sentence = (
        f"#{scenario.number} changed since it was read (base {base}, now {current}); "
        "read it again with "
        f"aco item show {scenario.argument} --json and apply your change to that body"
    )
    assert (result.status, result.stderr) == (2, f"ERROR: {sentence}\n")
    envelope = {"ok": False, "reason": "stale", "message": sentence}
    assert result.stdout == (json.dumps(envelope) + "\n" if as_json else "")
    assert client.body_writes == []


def test_an_edit_without_a_base_reports_precondition_failed_and_writes_nothing(
    serve_item: ServeItem, scenario: Scenario, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ITEM-73 -- no `--base` refuses ahead of the stdin rule with `--json` reason
    `precondition_failed`; the sentence is the printed-wording table's."""
    client = serve_item()

    result = run_cli(["item", "edit", scenario.argument, "--json"], capsys)

    assert result.status == 2
    assert json.loads(result.stdout)["reason"] == "precondition_failed"
    assert client.body_writes == []


def test_a_malformed_body_refuses_before_the_item_is_read(
    serve_item: ServeItem, scenario: Scenario, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ITEM-74 -- the shape check refuses `body_invalid` ahead of the lock and the read."""
    client = serve_item()
    arguments = edit_with_base(scenario.argument, capsys)
    reads_before = len(client.issue_reference_lookups)

    result = run_cli([*arguments, "--json"], capsys, stdin="```aco\nversion = \n```\n")

    defect = (
        "body malformed: aco: aco block is not valid TOML: Invalid value (at line 1, column 11)"
    )
    assert result.status == 2
    assert json.loads(result.stdout)["reason"] == "body_invalid"
    assert result.stderr == f"ERROR: {defect}\n"
    assert len(client.issue_reference_lookups) == reads_before
    assert client.body_writes == []


def test_a_body_equal_to_the_stored_one_writes_nothing(
    serve_item: ServeItem, scenario: Scenario, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ITEM-75 -- exit 0, no write, `--json` `reason: "unchanged"`; the text sentence is the
    printed-wording table's."""
    client = serve_item()
    arguments = edit_with_base(scenario.argument, capsys)

    envelope = run_cli([*arguments, "--json"], capsys, stdin=scenario.stored)

    assert envelope.status == 0
    assert json.loads(envelope.stdout)["reason"] == "unchanged"
    assert client.body_writes == []


@pytest.mark.parametrize(
    ("check_answer", "reason"),
    [
        pytest.param(
            lambda number: (
                forge.ForgeBodyOverwrittenError(
                    number, "2026-11-08T10:05:00Z", "ghost", kept=False
                ),
                f"#{number} body written, but overwritten in the meantime by ghost "
                "at 2026-11-08T10:05:00Z",
            ),
            {"reason": "overwritten", "kept": False},
            id="overwritten",
        ),
        pytest.param(
            lambda number: (
                forge.ForgeBodyNotVerifiedError(number, "timeout"),
                f"#{number} body written, not verified (timeout)",
            ),
            {"reason": "not_verified"},
            id="not-verified",
        ),
    ],
)
def test_a_write_the_forges_check_answers_prints_the_check_sentence(
    serve_item: ServeItem,
    scenario: Scenario,
    capsys: pytest.CaptureFixture[str],
    check_answer: Callable[[int], tuple[forge.ForgeBodyWrittenError, str]],
    reason: dict[str, object],
) -> None:
    """Spec: ITEM-76, OUT-10, OUT-11 -- the check's own sentence and `reason`, exit 2; the body
    is written."""
    number = scenario.number
    answer, sentence = check_answer(number)
    client = serve_item(answer=answer)
    arguments = edit_with_base(scenario.argument, capsys)

    result = run_cli([*arguments, "--json"], capsys, stdin=scenario.replacement)

    envelope = {"ok": False, **reason, "message": sentence}
    assert (result.status, result.stderr) == (2, f"ERROR: {sentence}\n")
    assert result.stdout == json.dumps(envelope) + "\n"
    assert client.item_bodies == {number: scenario.replacement}


@pytest.mark.parametrize(
    ("flags", "refusal"),
    [
        pytest.param(
            ["--size", "L", "--base", "sha256:" + "0" * 64],
            "argument --base: not allowed with argument --size",
            id="narrow-edit",
        ),
        pytest.param(
            ["--base", "sha256:abc"],
            "argument --base: must be sha256: followed by 64 lowercase hex digits",
            id="malformed-hash",
        ),
    ],
)
def test_a_base_that_cannot_stand_refuses_at_the_parser(
    serve_item: ServeItem,
    scenario: Scenario,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    refusal: str,
) -> None:
    """Spec: ITEM-50, ITEM-73 -- `--base` excludes the narrow flags and takes a `sha256:` hash,
    refused before anything is read or written."""
    client = serve_item()

    result = run_cli(
        ["item", "edit", scenario.argument, *flags], capsys, stdin=scenario.replacement
    )

    assert (result.status, result.stderr.splitlines()[-1]) == (
        2,
        f"aco item edit: error: {refusal}",
    )
    assert client.body_writes == []


def test_a_github_item_with_no_block_is_repaired_with_the_hash_show_printed(
    serve_item: ServeItem, scenario: Scenario, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ITEM-70, ITEM-71 -- the raw read has no block gate, so a body without a valid
    `aco` block is replaced against its own hash."""
    client = serve_item(stored="Prose only.\n")
    arguments = edit_with_base(scenario.argument, capsys)

    result = run_cli(arguments, capsys, stdin=scenario.replacement)

    assert (result.status, result.stdout) == (0, f"EDITED #{scenario.number}\n")
    assert client.item_bodies == {scenario.number: scenario.replacement}
