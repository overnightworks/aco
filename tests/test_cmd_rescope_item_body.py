"""The item body beside the claim for `aco rescope`, on real temporary git
worktrees and the real state ref: both owners of the scope move together, a
failed write names what went through, and a body that cannot carry the scope
or whose `whole` is defective changes neither. The forge is the only fake."""

from __future__ import annotations

from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, complete_contract
from claim_worktrees import (
    ISSUE,
    StandIn,
    Standing,
    assert_json_refusal_object,
    assert_no_item_body_written,
    claimed_here,
    make_stand_in,
    serve_body,
)
from cli_fixtures import run_cli
from github_fixtures import FakeForge
from store_fixtures import fail_every_state_ref_push, state_ref_tip

from aco import body
from aco.protocol import ClaimError

TRUNK_FILES = ("src/widget.py",)
HELD_SCOPE = ("src/widget.py",)
FOUR_FILE_REASON = "the four files share one lock"
BOUND_SENTENCE = "whole reason must be one bounded non-empty line"
NEW_FILE = "src/new.py"


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


def rescope(*flags: str) -> list[str]:
    return ["--repo", REPOSITORY, "rescope", str(ISSUE), *flags]


def held_claim() -> tuple[Standing, ...]:
    return (Standing(HELD_SCOPE, issue=ISSUE, agent="Ada"),)


def written_scope_and_whole(served: FakeForge) -> tuple[tuple[str, ...] | None, str | None]:
    parsed = body.parse_body(served.item_bodies[ISSUE])
    return parsed.scope, parsed.whole


@pytest.mark.parametrize(
    ("argv_tail", "scope", "whole", "body_whole", "from_source"),
    [
        pytest.param(
            ("--add", "{root}/src/new.py"),
            (NEW_FILE, "src/widget.py"),
            None,
            None,
            False,
            id="absolute-add",
        ),
        pytest.param(
            ("--add", NEW_FILE),
            (NEW_FILE, "src/widget.py"),
            None,
            None,
            True,
            id="relative-add-read-against-the-checkout-not-the-working-directory",
        ),
        pytest.param(
            ("--add", "{root}/src/new.py", "--drop", "src/widget.py"),
            (NEW_FILE,),
            None,
            None,
            True,
            id="relative-drop-beside-an-absolute-add",
        ),
        pytest.param(
            ("--add", "a.py", "--add", "b.py", "--add", "c.py", "--whole", FOUR_FILE_REASON),
            ("a.py", "b.py", "c.py", "src/widget.py"),
            FOUR_FILE_REASON,
            None,
            False,
            id="whole-flag-written-into-the-body",
        ),
        pytest.param(
            ("--add", "a.py", "--add", "b.py", "--add", "c.py"),
            ("a.py", "b.py", "c.py", "src/widget.py"),
            FOUR_FILE_REASON,
            FOUR_FILE_REASON,
            False,
            id="body-whole-admits-a-wide-scope-as-for-start",
        ),
    ],
)
def test_a_rescope_moves_the_claim_and_the_item_body_scope_together(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    argv_tail: tuple[str, ...],
    scope: tuple[str, ...],
    whole: str | None,
    body_whole: str | None,
    from_source: bool,
) -> None:
    """Spec: RESC-12, RESC-22, RESC-25. One call writes both owners of the
    scope; a relative entry is read against the checkout's toplevel, never the
    working directory."""
    standpoint = stand_in(standing=held_claim())
    if from_source:
        monkeypatch.chdir(standpoint.directory / "src")
    entries = {} if body_whole is None else {"whole": body_whole}
    served = serve_body(monkeypatch, complete_contract("Build it.", **entries))
    flags = tuple(part.replace("{root}", str(standpoint.directory)) for part in argv_tail)

    result = run_cli(rescope(*flags), capsys)

    assert (result.status, result.stderr) == (0, "")
    claimed = claimed_here(standpoint)
    assert (claimed.scope, claimed.whole_reason) == (scope, whole)
    assert written_scope_and_whole(served) == (scope, whole)


@pytest.mark.parametrize(
    ("body_write_fails", "body_scope", "refusal"),
    [
        pytest.param(
            True,
            None,
            "ERROR: update item body failed (simulated)\n",
            id="body-write-fails-first-and-the-claim-stays",
        ),
        pytest.param(
            False,
            (NEW_FILE, "src/widget.py"),
            "ERROR: #72 body scope now reads ['src/new.py', 'src/widget.py'], but the claim "
            "was not rescoped: push rejected (simulated); run the same rescope again\n",
            id="claim-write-fails-second-and-names-the-written-body",
        ),
    ],
)
def test_a_rescope_names_what_went_through_when_a_write_fails(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
    body_write_fails: bool,
    body_scope: tuple[str, ...] | None,
    refusal: str,
) -> None:
    """Spec: RESC-23, RESC-17, RESC-24. The body is written first, so a failed
    body write leaves the claim as it stood, and a failed claim write after it
    says the body already moved and how to bring the claim in step."""
    standpoint = stand_in(standing=held_claim())
    served = serve_body(monkeypatch, complete_contract("Build it."))
    tip = state_ref_tip(bare_remote)
    if body_write_fails:
        served.fail_update_item_body = True
    else:
        fail_every_state_ref_push(monkeypatch, ClaimError("push rejected (simulated)"))

    result = run_cli(rescope("--add", NEW_FILE), capsys)

    assert (result.status, result.stderr) == (2, refusal)
    assert state_ref_tip(bare_remote) == tip
    assert claimed_here(standpoint).scope == HELD_SCOPE
    written = served.item_bodies.get(ISSUE)
    assert (None if written is None else body.parse_body(written).scope) == body_scope


def test_a_rescope_refuses_an_item_body_without_a_block_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: RESC-24, RESC-16. A body that cannot carry the scope refuses with
    both owners as they stood."""
    standpoint = stand_in(standing=held_claim())
    served = serve_body(monkeypatch, "Prose only, no block.\n")
    tip = state_ref_tip(bare_remote)

    result = run_cli(rescope("--add", NEW_FILE, "--json"), capsys)

    assert result.status == 2
    assert_json_refusal_object(result.stderr, result.stdout, reason="precondition_failed")
    assert result.stderr == (
        "ERROR: #72 body malformed: aco: no aco block; rescope needs a valid aco block\n"
    )
    assert state_ref_tip(bare_remote) == tip
    assert claimed_here(standpoint).scope == HELD_SCOPE
    assert_no_item_body_written(served)


@pytest.mark.parametrize(
    ("body_whole", "flags", "reason", "sentence"),
    [
        pytest.param(
            "x" * 513,
            ("--add", NEW_FILE),
            "precondition_failed",
            f"ERROR: #72 body malformed: whole: {BOUND_SENTENCE}; "
            "rescope needs a valid aco block\n",
            id="rescope-body",
        ),
        pytest.param(
            None,
            ("--whole", " a"),
            "unavailable",
            f"ERROR: {BOUND_SENTENCE}\n",
            id="rescope-flag",
        ),
    ],
)
@pytest.mark.parametrize("as_json", [False, True], ids=["plain", "json"])
def test_a_rescope_with_a_defective_whole_changes_neither_the_claim_nor_the_body(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
    body_whole: str | None,
    flags: tuple[str, ...],
    reason: str,
    sentence: str,
    as_json: bool,
) -> None:
    """Spec: CLM-36, RESC-17, RESC-24, BODY-62. The stored body's `whole` and
    the flag's hold one bound, and a refusal writes nothing."""
    standpoint = stand_in(standing=held_claim())
    entries = {} if body_whole is None else {"whole": body_whole}
    raw_body = complete_contract("Ship it.", **entries)
    served = serve_body(monkeypatch, raw_body)
    tip = state_ref_tip(bare_remote)

    result = run_cli(rescope(*flags, *(("--json",) if as_json else ())), capsys)

    assert result.status == 2
    if as_json:
        assert_json_refusal_object(result.stderr, result.stdout, reason=reason)
    assert result.stderr == sentence
    assert state_ref_tip(bare_remote) == tip
    assert claimed_here(standpoint).scope == HELD_SCOPE
    assert served.board_issues[0].body == raw_body
    assert_no_item_body_written(served)
