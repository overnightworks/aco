"""A whole-body `aco item edit` names the body hash `aco item show --json` printed
(`specs/item.spec.md` ITEM-70..ITEM-76), on the real checkout of a GitHub-hosted
board. The forge is the only fake. The state-ref twins live in `test_state_board.py`."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import run_cli
from github_fixtures import serve_forge
from item_base import edit_with_base, shown_body_hash
from item_lock_witness import LockWitnessForge

from aco import forge

pytestmark = pytest.mark.usefixtures("github_world")

ITEM = 72
ITEM_ARGUMENT = str(ITEM)
STORED = block_body(MINIMAL_BLOCK_TOML)
REPLACEMENT = block_body(MINIMAL_BLOCK_TOML, before="Replacement prose.\n\n")
CHANGED_ELSEWHERE = block_body(MINIMAL_BLOCK_TOML, before="Ruled in the meantime.\n\n")
NO_BASE_HASH = "sha256:" + "0" * 64

type ServeItem = Callable[..., LockWitnessForge]


@pytest.fixture
def serve_item(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ServeItem:
    """Serves item 72 holding `stored`, whose reads answer the body last written; `answer`
    is what a write the forge's check answers raises, the body written first."""

    def serve(
        stored: str = STORED, answer: forge.ForgeBodyWrittenError | None = None
    ) -> LockWitnessForge:
        reference = forge.ItemReference(forge.ItemState.OPEN, "Claims", stored)
        client = LockWitnessForge(tmp_path / "item-locks", issue_references={ITEM: reference})
        client.update_item_body_error = answer
        client.update_item_body_lands_before_error = answer is not None
        return serve_forge(monkeypatch, client)

    return serve


def test_a_hash_item_show_printed_lets_item_edit_replace_the_body(
    serve_item: ServeItem, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ITEM-70, ITEM-71 -- the edit prints `EDITED` and, under `--json`, the hash of the
    written body, which is the one a later `item show --json` prints for it."""
    client = serve_item()
    arguments = edit_with_base(ITEM_ARGUMENT, capsys)

    result = run_cli([*arguments, "--json"], capsys, stdin=REPLACEMENT)

    assert result.status == 0
    assert client.item_bodies == {ITEM: REPLACEMENT}
    edited = json.loads(result.stdout)
    assert [edited[key] for key in ("ok", "reason", "item", "number")] == [
        True,
        "edited",
        f"#{ITEM}",
        ITEM,
    ]
    assert edited["body_hash"] == shown_body_hash(ITEM_ARGUMENT, capsys)


def test_an_edit_prints_edited_and_its_item(
    serve_item: ServeItem, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ITEM-71."""
    serve_item()
    arguments = edit_with_base(ITEM_ARGUMENT, capsys)

    result = run_cli(arguments, capsys, stdin=REPLACEMENT)

    assert (result.status, result.stdout, result.stderr) == (0, f"EDITED #{ITEM}\n", "")


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_an_edit_from_a_copy_read_before_another_write_refuses_and_keeps_that_write(
    serve_item: ServeItem, capsys: pytest.CaptureFixture[str], as_json: bool
) -> None:
    """Spec: ITEM-72 -- a base that is no longer the body's hash refuses `stale`, exit 2, and
    nothing is written."""
    client = serve_item()
    arguments = edit_with_base(ITEM_ARGUMENT, capsys)
    client.item_bodies[ITEM] = CHANGED_ELSEWHERE
    current = shown_body_hash(ITEM_ARGUMENT, capsys)

    result = run_cli([*arguments, *(["--json"] * as_json)], capsys, stdin=REPLACEMENT)

    base = arguments[-1]
    sentence = (
        f"#{ITEM} changed since it was read (base {base}, now {current}); read it again with "
        f"aco item show #{ITEM} --json and apply your change to that body"
    )
    assert (result.status, result.stderr) == (2, f"ERROR: {sentence}\n")
    envelope = {"ok": False, "reason": "stale", "message": sentence}
    assert result.stdout == (json.dumps(envelope) + "\n" if as_json else "")
    assert client.body_writes == []


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_an_edit_without_a_base_refuses_before_it_reads_stdin(
    serve_item: ServeItem, capsys: pytest.CaptureFixture[str], as_json: bool
) -> None:
    """Spec: ITEM-73 -- no `--base` names the way to get one and writes nothing; it refuses ahead
    of the stdin rule, so a missing redirect is not what the person is told."""
    client = serve_item()

    result = run_cli(["item", "edit", ITEM_ARGUMENT, *(["--json"] * as_json)], capsys)

    sentence = f"item edit #{ITEM} needs --base <hash>; aco item show #{ITEM} --json prints it"
    assert (result.status, result.stderr) == (2, f"ERROR: {sentence}\n")
    envelope = {"ok": False, "reason": "precondition_failed", "message": sentence}
    assert result.stdout == (json.dumps(envelope) + "\n" if as_json else "")
    assert client.body_writes == []


def test_a_malformed_body_refuses_before_the_item_is_read(
    serve_item: ServeItem, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ITEM-74 -- the shape check refuses `body_invalid` ahead of the lock and the read."""
    client = serve_item()
    arguments = edit_with_base(ITEM_ARGUMENT, capsys)
    reads_before = len(client.issue_reference_lookups)

    result = run_cli([*arguments, "--json"], capsys, stdin="no block here\n")

    defect = "body malformed: aco: no aco block"
    assert result.status == 2
    assert json.loads(result.stdout)["reason"] == "body_invalid"
    assert result.stderr == f"ERROR: {defect}\n"
    assert len(client.issue_reference_lookups) == reads_before
    assert client.body_writes == []


def test_a_body_equal_to_the_stored_one_writes_nothing(
    serve_item: ServeItem, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ITEM-75 -- `UNCHANGED`, exit 0, no write, `--json` `reason: "unchanged"`."""
    client = serve_item()
    arguments = edit_with_base(ITEM_ARGUMENT, capsys)

    text = run_cli(arguments, capsys, stdin=STORED)
    envelope = run_cli([*arguments, "--json"], capsys, stdin=STORED)

    assert (text.status, text.stdout) == (0, f"UNCHANGED #{ITEM}\n")
    assert json.loads(envelope.stdout)["reason"] == "unchanged"
    assert client.body_writes == []


@pytest.mark.parametrize(
    ("answer", "reason", "sentence"),
    [
        pytest.param(
            forge.ForgeBodyOverwrittenError(ITEM, "2026-11-08T10:05:00Z", "ghost", kept=False),
            {"reason": "overwritten", "kept": False},
            f"#{ITEM} body written, but overwritten in the meantime by ghost "
            "at 2026-11-08T10:05:00Z",
            id="overwritten",
        ),
        pytest.param(
            forge.ForgeBodyNotVerifiedError(ITEM, "timeout"),
            {"reason": "not_verified"},
            f"#{ITEM} body written, not verified (timeout)",
            id="not-verified",
        ),
    ],
)
def test_a_write_the_forges_check_answers_prints_the_check_sentence(
    serve_item: ServeItem,
    capsys: pytest.CaptureFixture[str],
    answer: forge.ForgeBodyWrittenError,
    reason: dict[str, object],
    sentence: str,
) -> None:
    """Spec: ITEM-76, OUT-10, OUT-11 -- the check's own sentence and `reason`, exit 2; the body
    is written."""
    client = serve_item(answer=answer)
    arguments = edit_with_base(ITEM_ARGUMENT, capsys)

    result = run_cli([*arguments, "--json"], capsys, stdin=REPLACEMENT)

    envelope = {"ok": False, **reason, "message": sentence}
    assert (result.status, result.stderr) == (2, f"ERROR: {sentence}\n")
    assert result.stdout == json.dumps(envelope) + "\n"
    assert client.item_bodies == {ITEM: REPLACEMENT}


@pytest.mark.parametrize(
    ("flags", "refusal"),
    [
        pytest.param(
            ["--size", "L", "--base", NO_BASE_HASH],
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
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    refusal: str,
) -> None:
    """Spec: ITEM-50, ITEM-73 -- `--base` excludes the narrow flags and takes a `sha256:` hash,
    refused before anything is read or written."""
    client = serve_item()

    result = run_cli(["item", "edit", ITEM_ARGUMENT, *flags], capsys, stdin=REPLACEMENT)

    assert (result.status, result.stderr.splitlines()[-1]) == (
        2,
        f"aco item edit: error: {refusal}",
    )
    assert client.body_writes == []


def test_a_github_item_with_no_block_is_repaired_with_the_hash_show_printed(
    serve_item: ServeItem, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ITEM-70, ITEM-71 -- the raw read has no block gate, so a body without a valid
    `aco` block is replaced against its own hash."""
    client = serve_item(stored="Prose only.\n")
    arguments = edit_with_base(ITEM_ARGUMENT, capsys)

    result = run_cli(arguments, capsys, stdin=REPLACEMENT)

    assert (result.status, result.stdout) == (0, f"EDITED #{ITEM}\n")
    assert client.item_bodies == {ITEM: REPLACEMENT}
