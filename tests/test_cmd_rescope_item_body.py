"""The item body beside the claim for `aco rescope`, on real temporary git
worktrees and the real state ref: both owners of the scope move together, a
failed write names what went through, and a body that cannot carry the scope
or whose `whole` is defective changes neither. The forge is the only fake."""

import json
from pathlib import Path

import pytest
from board_fixtures import complete_contract
from claim_worktrees import (
    ISSUE,
    StandIn,
    assert_json_refusal_object,
    assert_no_item_body_written,
    claimed_here,
    held_by_ada,
    make_stand_in,
    rescope_arguments,
    serve_body,
)
from cli_fixtures import run_cli
from github_fixtures import FakeForge, serve_forge
from item_lock_witness import LockWitnessForge, run_second_writer_beside_the_first
from store_fixtures import fail_every_state_ref_push, state_ref_tip

from aco import body, cli, forge
from aco.protocol import ClaimError

TRUNK_FILES = ("src/widget.py",)
HELD_SCOPE = ("src/widget.py",)
FOUR_FILE_REASON = "the four files share one lock"
BOUND_SENTENCE = "whole reason must be one bounded non-empty line"
NEW_FILE = "src/new.py"
OTHER_NEW_FILE = "src/other.py"


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


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
    standpoint = stand_in(standing=held_by_ada(HELD_SCOPE))
    if from_source:
        monkeypatch.chdir(standpoint.directory / "src")
    entries = {} if body_whole is None else {"whole": body_whole}
    served = serve_body(monkeypatch, complete_contract("Build it.", **entries))
    flags = tuple(part.replace("{root}", str(standpoint.directory)) for part in argv_tail)

    result = run_cli(rescope_arguments(*flags), capsys)

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
    standpoint = stand_in(standing=held_by_ada(HELD_SCOPE))
    served = serve_body(monkeypatch, complete_contract("Build it."))
    tip = state_ref_tip(bare_remote)
    if body_write_fails:
        served.fail_update_item_body = True
    else:
        fail_every_state_ref_push(monkeypatch, ClaimError("push rejected (simulated)"))

    result = run_cli(rescope_arguments("--add", NEW_FILE), capsys)

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
    standpoint = stand_in(standing=held_by_ada(HELD_SCOPE))
    served = serve_body(monkeypatch, "Prose only, no block.\n")
    tip = state_ref_tip(bare_remote)

    result = run_cli(rescope_arguments("--add", NEW_FILE, "--json"), capsys)

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
    standpoint = stand_in(standing=held_by_ada(HELD_SCOPE))
    entries = {} if body_whole is None else {"whole": body_whole}
    raw_body = complete_contract("Ship it.", **entries)
    served = serve_body(monkeypatch, raw_body)
    tip = state_ref_tip(bare_remote)

    result = run_cli(rescope_arguments(*flags, *(("--json",) if as_json else ())), capsys)

    assert result.status == 2
    if as_json:
        assert_json_refusal_object(result.stderr, result.stdout, reason=reason)
    assert result.stderr == sentence
    assert state_ref_tip(bare_remote) == tip
    assert claimed_here(standpoint).scope == HELD_SCOPE
    assert served.board_issues[0].body == raw_body
    assert_no_item_body_written(served)


def serve_witness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, pause_first_call: bool = False
) -> LockWitnessForge:
    reference = forge.ItemReference(forge.ItemState.OPEN, "Claims", complete_contract("Build it."))
    return serve_forge(
        monkeypatch,
        LockWitnessForge(
            tmp_path / "state" / "aco" / "item-locks",
            issue_references={ISSUE: reference},
            pause_first_call=pause_first_call,
        ),
    )


def test_a_rescope_reads_and_writes_the_item_body_while_its_lock_is_held(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: RESC-33 -- the item read, the body write and the claim write are under the
    item's lock, and the claim state the turn judges is read after the lock is taken."""
    stand_in(standing=held_by_ada(HELD_SCOPE))
    client = serve_witness(monkeypatch, tmp_path)
    client.witness_claim_store(monkeypatch)

    result = run_cli(rescope_arguments("--add", NEW_FILE), capsys)

    assert (result.status, result.stderr) == (0, "")
    assert (
        client.lock_held_at_reads,
        client.lock_held_at_writes,
        client.lock_held_at_claim_writes,
        client.lock_held_at_state_fetches[-1],
    ) == ([True], [True], [True], True)


def test_a_second_rescope_says_it_waits_for_the_lock_and_writes_after_the_first(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, tmp_path: Path
) -> None:
    """Spec: RESC-33, RULE-42 -- the wait line, then the second run's read and write."""
    stand_in(standing=held_by_ada(HELD_SCOPE))
    client = serve_witness(monkeypatch, tmp_path, pause_first_call=True)
    client.witness_claim_store(monkeypatch)

    added = iter([NEW_FILE, OTHER_NEW_FILE])

    def writer() -> int:
        return cli.main(rescope_arguments("--add", next(added)))

    contended = run_second_writer_beside_the_first(monkeypatch, client, writer)

    assert contended.statuses == (0, 0)
    assert contended.stderr == f"waiting for the item lock at {client.the_lock_file()}\n"
    assert contended.body_writes_when_the_second_waited == 0
    assert (client.lock_held_at_reads, client.lock_held_at_writes) == ([True, True], [True, True])
    assert client.lock_held_at_claim_writes == [True, True]
    assert written_scope_and_whole(client)[0] == (NEW_FILE, OTHER_NEW_FILE, *HELD_SCOPE)


def test_an_unwritable_lock_directory_refuses_unavailable_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    tmp_path: Path,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: RESC-33, RULE-41 -- a lock the item cannot take names its path; the body
    and the claim stay."""
    standpoint = stand_in(standing=held_by_ada(HELD_SCOPE))
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker))
    client = serve_witness(monkeypatch, tmp_path)
    tip = state_ref_tip(bare_remote)
    held = claimed_here(standpoint)

    result = run_cli([*rescope_arguments("--add", NEW_FILE), "--json"], capsys)

    assert (
        result.status,
        result.stderr.startswith(
            f"ERROR: cannot lock the item at {blocker / 'aco' / 'item-locks'}"
        ),
        json.loads(result.stdout)["reason"],
        client.body_writes,
        state_ref_tip(bare_remote),
        claimed_here(standpoint).scope,
    ) == (2, True, "unavailable", [], tip, held.scope)
