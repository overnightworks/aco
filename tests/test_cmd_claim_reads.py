"""What `aco claim` reads of the repository and of the state ref, counted on a
real linked worktree and the real state ref. The forge is the only fake."""

from __future__ import annotations

from pathlib import Path

import pytest
from board_fixtures import complete_contract
from claim_worktrees import StandIn, claim, make_stand_in, serve_body, serve_item
from cli_fixtures import count_context_reads

TRUNK_FILES = ("src/widget.py",)
COMMA_REFUSAL_OPENING = "ERROR: 'a,b' matches no versioned file; "


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


def test_a_claim_reads_its_toplevel_its_configuration_and_the_state_ref_once(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn
) -> None:
    """Spec: CAS-53. However many of its steps ask, the claim resolves the
    working directory's toplevel once, reads that checkout's board
    configuration once, and observes the state ref once."""
    standpoint = stand_in()
    serve_item(monkeypatch, TRUNK_FILES)
    reads = count_context_reads(monkeypatch)

    status = claim(scope=TRUNK_FILES)

    assert (status, *reads.drain()) == (
        0,
        {None: 1},
        {standpoint.directory: 1},
        {standpoint.directory: 1},
    )


def test_a_claim_refused_for_a_comma_scope_matching_nothing_never_observes_the_state_ref(
    monkeypatch: pytest.MonkeyPatch, stand_in: StandIn, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CAS-53, CLAIM-18. The comma guard lists the checkout's versioned
    files, so it reads the toplevel and configuration once; it refuses before
    the claim needs the state ref, which it therefore never observes."""
    standpoint = stand_in()
    serve_body(monkeypatch, complete_contract("Build it."))
    reads = count_context_reads(monkeypatch)

    status = claim(scope=("a,b",))

    refusal = capsys.readouterr().err
    assert (status, refusal.startswith(COMMA_REFUSAL_OPENING), *reads.drain()) == (
        2,
        True,
        {None: 1},
        {standpoint.directory: 1},
        {},
    )
