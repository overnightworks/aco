"""`aco cut` answers the forge's check of its row-removal write (`specs/cut.spec.md`
CUT-42, CUT-43): the child exists and the write landed, so the answer is never
`partial_write`. The forge is the only fake."""

import json

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, container_issue
from cli_fixtures import run_cli
from github_fixtures import FakeForge, serve_forge

from aco import forge

pytestmark = pytest.mark.usefixtures("github_world")

CONTAINER = 79
EDITED_AT = "2026-11-08T10:05:00Z"
CUT_ARGUMENTS = ["cut", str(CONTAINER), "--title", "Slice A", "--not-a-twin"]
ONE_ROW = MINIMAL_BLOCK_TOML + '[[slice]]\nindex = 1\ntitle = "Slice A"\ndone_when = "D"\n'
RERUN = "if row 1 is still in #79's aco block, re-run aco cut 79 --row 1 -- it adopts the child"


def _serve_a_check_answering(
    monkeypatch: pytest.MonkeyPatch, answer: forge.ForgeBodyWrittenError
) -> FakeForge:
    container = container_issue(CONTAINER, ONE_ROW)
    return serve_forge(
        monkeypatch,
        FakeForge(
            issue_references={
                CONTAINER: forge.ItemReference(forge.ItemState.OPEN, "Epic", container.body)
            },
            board_issues=(container,),
            update_item_body_error=answer,
            update_item_body_lands_before_error=True,
        ),
    )


@pytest.mark.parametrize(
    ("answer", "reason", "kept", "sentence"),
    [
        pytest.param(
            forge.ForgeBodyOverwrittenError(CONTAINER, EDITED_AT, "ghost", kept=False),
            "overwritten",
            False,
            f"#79 body written, but overwritten in the meantime by ghost at {EDITED_AT}",
            id="overwritten",
        ),
        pytest.param(
            forge.ForgeBodyNotVerifiedError(CONTAINER, "timeout"),
            "not_verified",
            None,
            "#79 body written, not verified (timeout)",
            id="not-verified",
        ),
    ],
)
@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_a_checked_row_removal_names_the_child_and_how_to_finish(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    answer: forge.ForgeBodyWrittenError,
    reason: str,
    kept: bool | None,
    sentence: str,
    as_json: bool,
) -> None:
    """Spec: CUT-42, CUT-43 -- stderr names the created child, the check's sentence and the
    re-run that adopts it; `--json` carries the reason, `written` and, for `overwritten`,
    `kept`."""
    _serve_a_check_answering(monkeypatch, answer)
    line = f"created #900; {sentence}; {RERUN}"
    envelope: dict[str, object] = {"ok": False, "reason": reason, "written": 900}
    if kept is not None:
        envelope["kept"] = kept
    envelope["message"] = line

    result = run_cli([*CUT_ARGUMENTS, *(["--json"] * as_json)], capsys)

    assert (result.status, result.stderr) == (2, f"ERROR: {line}\n")
    assert result.stdout == (json.dumps(envelope) + "\n" if as_json else "")


def test_a_row_removal_kept_over_an_unread_change_is_answered_with_the_rerun(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CUT-42, CUT-43 -- the kept write keeps the words around the check's sentence:
    the child, the sentence's start and the re-run."""
    _serve_a_check_answering(
        monkeypatch, forge.ForgeBodyOverwrittenError(CONTAINER, EDITED_AT, "ghost", kept=True)
    )

    result = run_cli([*CUT_ARGUMENTS, "--json"], capsys)

    envelope = json.loads(result.stdout)
    assert (result.status, envelope["reason"], envelope["kept"], envelope["written"]) == (
        2,
        "overwritten",
        True,
        900,
    )
    assert envelope["message"].startswith("created #900; #79 body written over a change by ghost")
    assert envelope["message"].endswith(RERUN)
