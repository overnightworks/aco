"""The `whole` bound of `aco item new` and `aco item edit`, on real temporary
git worktrees and the real state ref: a flag or a body that breaks it refuses
before any write. The forge is the only fake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, complete_contract
from claim_worktrees import (
    ISSUE,
    StandIn,
    assert_no_item_body_written,
    make_stand_in,
    serve_body,
)
from cli_fixtures import run_cli
from store_fixtures import state_ref_tip

BOUND_SENTENCE = "whole reason must be one bounded non-empty line"
LONG_WHOLE = "x" * 513


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, ())


@pytest.mark.parametrize(
    ("command", "stored_whole", "piped", "reason", "sentence"),
    [
        pytest.param(
            ("new", "--title", "Fresh", "--whole", LONG_WHOLE),
            None,
            None,
            "precondition_failed",
            f"ERROR: {BOUND_SENTENCE}\n",
            id="new-flag",
        ),
        pytest.param(
            ("edit", str(ISSUE), "--whole", ""),
            None,
            None,
            "precondition_failed",
            f"ERROR: {BOUND_SENTENCE}\n",
            id="edit-flag",
        ),
        pytest.param(
            ("edit", str(ISSUE), "--whole", "ok"),
            LONG_WHOLE,
            None,
            "precondition_failed",
            f"ERROR: #72 body malformed: whole: {BOUND_SENTENCE}; "
            "item edit --whole needs a valid aco block\n",
            id="edit-body",
        ),
        pytest.param(
            ("new", "--title", "Fresh"),
            None,
            LONG_WHOLE,
            "body_invalid",
            f"ERROR: body malformed: whole: {BOUND_SENTENCE}\n",
            id="new-body",
        ),
    ],
)
@pytest.mark.parametrize("as_json", [False, True], ids=["plain", "json"])
def test_an_item_command_with_a_defective_whole_refuses_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
    command: tuple[str, ...],
    stored_whole: str | None,
    piped: str | None,
    reason: str,
    sentence: str,
    as_json: bool,
) -> None:
    """Spec: ITEM-23, ITEM-24, ITEM-25, ITEM-27, BODY-62. The flag, the stored
    body and a piped body hold one bound, and a refusal writes nothing."""
    stand_in()
    entries = {} if stored_whole is None else {"whole": stored_whole}
    raw_body = complete_contract("Ship it.", **entries)
    served = serve_body(monkeypatch, raw_body)
    tip = state_ref_tip(bare_remote)
    stdin = None if piped is None else complete_contract("Ship it.", whole=piped)

    result = run_cli(
        ["--repo", REPOSITORY, "item", *command, *(("--json",) if as_json else ())],
        capsys,
        stdin=stdin,
    )

    assert result.status == 2
    if as_json:
        refusal = json.loads(result.stdout)
        message = sentence.removeprefix("ERROR: ").rstrip("\n")
        assert (refusal["reason"], refusal["message"]) == (reason, message)
    assert result.stderr == sentence
    assert state_ref_tip(bare_remote) == tip
    assert served.board_issues[0].body == raw_body
    assert_no_item_body_written(served)
