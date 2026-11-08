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


def _serve_a_check_answering(
    monkeypatch: pytest.MonkeyPatch, answer: forge.ForgeBodyWrittenError
) -> FakeForge:
    one_row = MINIMAL_BLOCK_TOML + '[[slice]]\nindex = 1\ntitle = "Slice A"\ndone_when = "D"\n'
    container = container_issue(79, one_row)
    return serve_forge(
        monkeypatch,
        FakeForge(
            issue_references={
                79: forge.ItemReference(forge.ItemState.OPEN, "Epic", container.body)
            },
            board_issues=(container,),
            update_item_body_error=answer,
            update_item_body_lands_before_error=True,
        ),
    )


def _cut_line(check_sentence: str) -> str:
    return (
        f"created #900; {check_sentence}; if row 1 is still in #79's aco block, "
        "re-run aco cut 79 --row 1 -- it adopts the child"
    )


@pytest.mark.parametrize(
    ("answer", "reason", "kept", "sentence"),
    [
        pytest.param(
            forge.ForgeBodyOverwrittenError(79, "2026-11-08T10:05:00Z", "ghost", kept=False),
            "overwritten",
            False,
            "#79 body written, but overwritten in the meantime by ghost at 2026-11-08T10:05:00Z",
            id="overwritten",
        ),
        pytest.param(
            forge.ForgeBodyOverwrittenError(79, "2026-11-08T10:05:00Z", "ghost", kept=True),
            "overwritten",
            True,
            "#79 body written over a change by ghost at 2026-11-08T10:05:00Z aco had not read; "
            "that change is only in the edit history",
            id="kept",
        ),
        pytest.param(
            forge.ForgeBodyOverwrittenError(79, "2026-11-08T10:05:00Z", None, kept=True),
            "overwritten",
            True,
            "#79 body written over a change by an unknown editor at 2026-11-08T10:05:00Z "
            "aco had not read; that change is only in the edit history",
            id="kept-by-an-unknown-editor",
        ),
        pytest.param(
            forge.ForgeBodyOverwrittenError(79, "2026-11-08T10:05:00Z", None, kept=False),
            "overwritten",
            False,
            "#79 body written, but overwritten in the meantime by an unknown editor "
            "at 2026-11-08T10:05:00Z",
            id="overwritten-by-an-unknown-editor",
        ),
        pytest.param(
            forge.ForgeBodyNotVerifiedError(79, "timeout"),
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
    """Spec: CUT-42, CUT-43 -- stderr names the created child, the check's whole sentence
    and the re-run that adopts it; `--json` carries the reason, `written` and, for
    `overwritten`, `kept`."""
    _serve_a_check_answering(monkeypatch, answer)
    envelope: dict[str, object] = {"ok": False, "reason": reason, "written": 900}
    if kept is not None:
        envelope["kept"] = kept
    envelope["message"] = _cut_line(sentence)

    result = run_cli(
        ["cut", "79", "--title", "Slice A", "--not-a-twin", *(["--json"] * as_json)], capsys
    )

    assert (result.status, result.stderr) == (2, f"ERROR: {_cut_line(sentence)}\n")
    assert result.stdout == (json.dumps(envelope) + "\n" if as_json else "")
