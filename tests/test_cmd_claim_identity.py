"""Who a claim is made as, on real temporary git worktrees: the role it
records, the agent filled from the documented chain when no flag names one,
and who may release it. The forge is the only fake."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from claim_worktrees import (
    StandIn,
    claim,
    claimed_here,
    make_stand_in,
    release,
    serve_item,
    standing_claims,
)
from cli_fixtures import AGENT_IDENTITY_ENV_NAMES, set_agent_identity_env

TRUNK_FILES = ("src/widget.py",)


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


def identity_from(monkeypatch: pytest.MonkeyPatch, environ: dict[str, str]) -> None:
    """The environment names exactly `environ` as the agent's identity; the
    scenario's own `ACO_AGENT` is gone."""
    for name in AGENT_IDENTITY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    set_agent_identity_env(monkeypatch, environ)


@pytest.mark.parametrize(
    ("role_flags", "role"),
    [
        pytest.param((), "builder", id="omitted-role-is-builder"),
        pytest.param(("--role", "builder"), "builder", id="explicit-builder"),
        pytest.param(("--role", "coordinator"), "coordinator", id="explicit-coordinator"),
    ],
)
def test_claim_records_the_role_it_is_given_and_builder_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    role_flags: tuple[str, ...],
    role: str,
) -> None:
    """Spec: CLAIM-36, CLAIM-05."""
    standpoint = stand_in()
    serve_item(monkeypatch, ("src",))

    status = claim(*role_flags)

    assert (status, claimed_here(standpoint).role) == (0, role)


def test_claim_with_an_empty_role_is_refused_and_stores_nothing(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: CLAIM-58."""
    standpoint = stand_in()
    serve_item(monkeypatch, ("src",))

    status = claim("--role", "")

    captured = capsys.readouterr()
    assert (status, captured.out) == (2, "")
    assert re.search(r"^ERROR: .*role.+must be one bounded non-empty line", captured.err)
    assert not standing_claims(standpoint)


@pytest.mark.parametrize(
    ("explicit", "environ", "agent"),
    [
        pytest.param(
            "Ada",
            {
                "ACO_AGENT": "Other",
                "GROK_SESSION_ID": "grok-session",
                "CLAUDE_CODE_SESSION_ID": "claude-session",
            },
            "Ada",
            id="the-flag-beats-the-environment",
        ),
        pytest.param(None, {"ACO_AGENT": "Ada"}, "Ada", id="aco-agent"),
        pytest.param(
            None,
            {"ACO_AGENT": "", "GROK_SESSION_ID": "sess-1"},
            "Grok sess-1",
            id="an-empty-aco-agent-falls-through-to-grok",
        ),
        pytest.param(
            None,
            {"GROK_SESSION_ID": "sess-1", "CLAUDE_CODE_SESSION_ID": "sess-2"},
            "Grok sess-1",
            id="grok-beats-claude",
        ),
        pytest.param(
            None, {"CLAUDE_CODE_SESSION_ID": "sess-2"}, "Claude sess-2", id="claude-session"
        ),
        pytest.param(
            None,
            {"ACO_AGENT": "", "GROK_SESSION_ID": "", "CLAUDE_CODE_SESSION_ID": "sess-2"},
            "Claude sess-2",
            id="empty-variables-fall-through-to-claude",
        ),
    ],
)
def test_claim_fills_the_agent_from_the_documented_chain(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    explicit: str | None,
    environ: dict[str, str],
    agent: str,
) -> None:
    """Spec: CLAIM-05."""
    standpoint = stand_in()
    serve_item(monkeypatch, ("src",))
    identity_from(monkeypatch, environ)

    status = claim(agent=explicit)

    assert (status, claimed_here(standpoint).agent) == (0, agent)


@pytest.mark.parametrize(
    ("claimed_by", "environ"),
    [
        pytest.param("Codex Sol", {}, id="the-agent-flag"),
        pytest.param(None, {"GROK_SESSION_ID": "session-1"}, id="a-filled-session-identity"),
    ],
)
def test_the_agent_that_claimed_releases_its_claim_the_same_way(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    claimed_by: str | None,
    environ: dict[str, str],
) -> None:
    """Spec: CLAIM-38, REL-12."""
    standpoint = stand_in()
    serve_item(monkeypatch, ("src",))
    identity_from(monkeypatch, environ)
    agent_flags = [] if claimed_by is None else ["--agent", claimed_by]

    claimed = claim("--role", "builder", agent=claimed_by)
    released = release("--role", "builder", *agent_flags)

    assert (claimed, released) == (0, 0)
    assert not standing_claims(standpoint)


def test_another_session_cannot_release_a_claim_and_the_holder_keeps_it(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: CLAIM-38, REL-12."""
    standpoint = stand_in()
    serve_item(monkeypatch, ("src",))
    identity_from(monkeypatch, {"GROK_SESSION_ID": "session-1"})
    assert claim("--role", "builder", agent=None) == 0
    capsys.readouterr()
    identity_from(monkeypatch, {"CLAUDE_CODE_SESSION_ID": "session-2"})

    status = release("--role", "builder")

    assert status == 2
    assert "original claimant" in capsys.readouterr().err
    assert claimed_here(standpoint).agent == "Grok session-1"
