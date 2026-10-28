"""`aco claim`, `aco rescope` and `aco release` against the remote that holds
the state ref, on real temporary git worktrees: a state ref that does not
exist, a forge target that names another repository than the canonical
remote, and a remote no forge adapter serves. The forge is the only fake."""

from __future__ import annotations

from pathlib import Path

import pytest
from claim_worktrees import (
    LANE_MODE_BRANCH,
    StandIn,
    assert_json_refusal_object,
    claim,
    make_stand_in,
    serve_item,
    standing_claims,
)
from cli_fixtures import forbid_forge_resolution, real_git
from store_fixtures import state_ref_tip

from aco import cli as issue_claim
from aco import protocol, store

TRUNK_FILES = ("src/widget.py", "docs/guide.md", "README.md")


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


@pytest.mark.parametrize(
    "json_flag", [pytest.param(False, id="without-json"), pytest.param(True, id="with-json")]
)
def test_claim_refuses_a_missing_state_ref_and_json_names_it_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
    json_flag: bool,
) -> None:
    """Spec: CAS-03, CLM-27, OUT-03."""
    stand_in()
    serve_item(monkeypatch, ("src",))
    real_git(bare_remote, "update-ref", "-d", store.STATE_REF)
    json_flags = ("--json",) if json_flag else ()

    status = claim(*json_flags, agent="Ada")

    captured = capsys.readouterr()
    assert status == 2
    assert protocol.MISSING_STATE_REF in captured.err
    if json_flag:
        assert_json_refusal_object(captured.err, captured.out, reason="unavailable")
    else:
        assert captured.out == ""
    assert state_ref_tip(bare_remote) is None


@pytest.mark.parametrize(
    "json_flag", [pytest.param(False, id="without-json"), pytest.param(True, id="with-json")]
)
def test_claim_refuses_a_forge_target_that_is_not_the_canonical_remote_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    github_clone: Path,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
    json_flag: bool,
) -> None:
    """Spec: CLM-27, OUT-03, PIN-53."""
    standpoint = stand_in()
    serve_item(monkeypatch, ("src",))
    other = "git@github.com:other/repo.git"
    real_git(github_clone, "config", "--add", f"url.{bare_remote}.insteadOf", other)
    real_git(github_clone, "remote", "set-url", "origin", other)
    tip_before = state_ref_tip(bare_remote)

    status = claim(*(("--json",) if json_flag else ()), agent="Ada")

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == (
        "ERROR: forge target example/agent-coordination does not match canonical remote "
        "other/repo; run aco from that repository's checkout\n"
    )
    if json_flag:
        assert_json_refusal_object(captured.err, captured.out, reason="unavailable")
    else:
        assert captured.out == ""
    assert state_ref_tip(bare_remote) == tip_before
    assert not standing_claims(standpoint)


def test_a_lane_claim_rescope_and_release_resolve_no_forge_against_a_bare_path_remote(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    clone: Path,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: CLAIM-03, CLM-06, RESC-12, REL-33, LAND-39."""
    place = make_stand_in(monkeypatch, tmp_path, clone, bare_remote, TRUNK_FILES)
    standpoint = place(branch=LANE_MODE_BRANCH)
    forbid_forge_resolution(monkeypatch)

    claimed = issue_claim.main(["claim", "--role", "builder", "--scope", "docs/guide.md"])
    rescoped = issue_claim.main(["rescope", "--add", str(standpoint.directory / "README.md")])
    [live] = standing_claims(standpoint)
    released = issue_claim.main(["release", "--abandoned", "stopped"])

    assert (claimed, rescoped, released) == (0, 0, 0)
    assert (live.branch, live.scope) == (LANE_MODE_BRANCH, ("README.md", "docs/guide.md"))
    assert not standing_claims(standpoint)
    assert capsys.readouterr().err == ""
