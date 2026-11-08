"""`aco item edit --size` and `--whole` answer the forge's check of their body write
(`specs/output.spec.md` OUT-07, `specs/item.spec.md` ITEM-76): the body was written, so
the answer is never `precondition_failed`. The forge is the only fake."""

import json

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import run_cli
from github_fixtures import FakeForge, serve_forge

from aco import body, forge

pytestmark = pytest.mark.usefixtures("github_world")

ITEM = 72
EDITS = [
    pytest.param(("--size", "L"), id="size"),
    pytest.param(("--whole", "the adapters share one lock"), id="whole"),
]
ANSWERS = [
    pytest.param(
        forge.ForgeBodyOverwrittenError(ITEM, "2026-11-08T10:05:00Z", "ghost", kept=False),
        {"reason": "overwritten", "kept": False},
        f"#{ITEM} body written, but overwritten in the meantime by ghost at 2026-11-08T10:05:00Z",
        id="overwritten",
    ),
    pytest.param(
        forge.ForgeBodyOverwrittenError(ITEM, "2026-11-08T10:05:00Z", "ghost", kept=True),
        {"reason": "overwritten", "kept": True},
        f"#{ITEM} body written over a change by ghost at 2026-11-08T10:05:00Z aco had not read; "
        "that change is only in the edit history",
        id="kept",
    ),
    pytest.param(
        forge.ForgeBodyNotVerifiedError(ITEM, "timeout"),
        {"reason": "not_verified"},
        f"#{ITEM} body written, not verified (timeout)",
        id="not-verified",
    ),
]


@pytest.mark.parametrize(("answer", "reason", "sentence"), ANSWERS)
@pytest.mark.parametrize("edit", EDITS)
@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_an_edit_whose_write_the_check_answers_prints_the_check_sentence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    answer: forge.ForgeBodyWrittenError,
    reason: dict[str, object],
    sentence: str,
    edit: tuple[str, ...],
    as_json: bool,
) -> None:
    """Spec: ITEM-76, OUT-07 -- the check's own sentence, exit 2, `overwritten` (with
    `kept`) or `not_verified`; the field is written."""
    client = serve_forge(
        monkeypatch,
        FakeForge(
            issue_references={
                ITEM: forge.ItemReference(
                    forge.ItemState.OPEN, "Claims", block_body(MINIMAL_BLOCK_TOML)
                )
            },
            update_item_body_error=answer,
            update_item_body_lands_before_error=True,
        ),
    )

    result = run_cli(["item", "edit", str(ITEM), *edit, *(["--json"] * as_json)], capsys)

    envelope = {"ok": False, **reason, "message": sentence}
    assert (result.status, result.stderr) == (2, f"ERROR: {sentence}\n")
    assert result.stdout == (json.dumps(envelope) + "\n" if as_json else "")
    written = body.parse_body(client.item_bodies[ITEM])
    assert (written.size, written.whole) != (None, None)
