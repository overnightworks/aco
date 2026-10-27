"""A claim field is foreign text: the write side refuses every display control
(NEXT-37) and TAB, the read side lists a stored claim holding one unchanged, and
`aco status` and `aco brief` print each as its escape."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cli_fixtures import run_cli
from github_fixtures import FakeForge, serve_forge
from store_fixtures import claim_intent, publish_claims_from_a_second_clone

from aco import body, forge, protocol

ITEM = 417
STORED_AGENT = "Bo\u202eb"
STORED_ROLE = "bu\x9bilder"
STORED_BRANCH = "ada/\u200bwork"
STORED_WHOLE = "too\u2028wide"
ESCAPED_HOLDER = "Bo\\u202eb (bu\\x9bilder)"
ESCAPED_BRANCH = "ada/\\u200bwork"
ESCAPED_WHOLE = "  whole: too\\u2028wide"

DISPLAY_CONTROLS = ["\x9b", "\u202e", "\u200b", "\u2028", "\U000e0041", "\t"]
CONTROL_IDS = ["c1", "bidi", "zero-width", "line-separator", "tag", "tab"]
VALIDATIONS = {
    "agent": ("agent must be one bounded non-empty line", protocol.AGENT_MAX_LENGTH),
    "role": ("role must be one bounded non-empty line", protocol.ROLE_MAX_LENGTH),
    "abandoned reason": (
        "abandoned reason must be one bounded non-empty line",
        protocol.ABANDONED_REASON_MAX_LENGTH,
    ),
}


@pytest.mark.parametrize("character", DISPLAY_CONTROLS, ids=CONTROL_IDS)
@pytest.mark.parametrize("field", VALIDATIONS)
def test_a_one_line_field_refuses_tab_and_every_display_control(field: str, character: str) -> None:
    """Spec: CLAIM-58, REL-02"""
    sentence, maximum = VALIDATIONS[field]
    value = f"a{character}b"

    with pytest.raises(protocol.ClaimError, match=sentence):
        protocol.outbound_text(value, field, maximum=maximum)


@pytest.mark.parametrize("character", DISPLAY_CONTROLS, ids=CONTROL_IDS)
def test_a_block_whole_reason_refuses_tab_and_every_display_control(character: str) -> None:
    """Spec: BODY-61"""
    value = f"a{character}b"

    with pytest.raises(protocol.ClaimError, match="whole reason must be one bounded"):
        body.bounded_whole_reason(value)


@pytest.mark.parametrize("character", DISPLAY_CONTROLS, ids=CONTROL_IDS)
def test_a_branch_refuses_tab_and_every_display_control(character: str) -> None:
    """Spec: defect:#417"""
    payload: dict[str, object] = {"branch": f"ada/{character}work"}

    with pytest.raises(protocol.ClaimError, match="must be one bounded non-empty line"):
        protocol.valid_branch(payload)


@pytest.mark.parametrize("text", ["Größe", "a\u00a0b"], ids=["umlaut", "nbsp"])
def test_printable_text_still_passes_the_validators(text: str) -> None:
    """Spec: CLAIM-58, BODY-61"""
    assert (
        protocol.outbound_text(text, "agent", maximum=protocol.AGENT_MAX_LENGTH),
        body.bounded_whole_reason(text),
    ) == (text, text)


def _escaping_claim(identity: protocol.ClaimIdentity) -> protocol.ClaimIntent:
    return claim_intent(
        identity=identity,
        agent=STORED_AGENT,
        role=STORED_ROLE,
        branch=STORED_BRANCH,
        whole_reason=STORED_WHOLE,
        scope=("src/aco/protocol.py",),
    )


@pytest.fixture
def seeded_claim(
    github_clone: Path, bare_remote: Path, monkeypatch: pytest.MonkeyPatch
) -> protocol.ClaimIntent:
    """A claim already on the state ref whose four text fields hold a display
    control: the write rule of before this one let each of them in."""
    client = FakeForge()
    client.issue_references[ITEM] = forge.ItemReference(forge.ItemState.OPEN, "Item", "The body.")
    serve_forge(monkeypatch, client)
    intent = _escaping_claim(protocol.IssueIdentity(ITEM))
    publish_claims_from_a_second_clone(github_clone, bare_remote, (intent,))
    return intent


def test_status_prints_each_display_control_of_a_stored_claim_as_its_escape(
    seeded_claim: protocol.ClaimIntent, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STAT-32, CLAIM-74"""
    result = run_cli(["status"], capsys)

    holder_line = result.stdout.splitlines()[0]
    assert result.status == 0
    assert (ESCAPED_HOLDER in holder_line, f"branch={ESCAPED_BRANCH} " in holder_line) == (
        True,
        True,
    )
    assert ESCAPED_WHOLE in result.stdout.splitlines()
    assert "\u202e" not in result.stdout


def test_status_of_a_path_prints_its_holder_escaped(
    seeded_claim: protocol.ClaimIntent, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STAT-32"""
    result = run_cli(["status", "--path", "src/aco/protocol.py"], capsys)

    assert result.status == 0
    assert ESCAPED_HOLDER in result.stdout.splitlines()[0]
    assert ESCAPED_WHOLE in result.stdout.splitlines()


def test_status_of_a_path_json_carries_a_stored_claim_as_stored(
    seeded_claim: protocol.ClaimIntent, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STAT-32"""
    result = run_cli(["status", "--path", "src/aco/protocol.py", "--json"], capsys)

    [claim] = json.loads(result.stdout)["claims"]
    assert (result.status, claim["agent"], claim["role"], claim["branch"], claim["whole"]) == (
        0,
        seeded_claim.agent,
        seeded_claim.role,
        seeded_claim.branch,
        seeded_claim.whole_reason,
    )


def test_a_coordinator_override_releases_a_stored_claim_holding_a_display_control(
    seeded_claim: protocol.ClaimIntent, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CLAIM-74, REL-13"""
    released = run_cli(
        [
            "release",
            str(ITEM),
            "--role",
            "coordinator",
            "--coordinator-override",
            "--abandoned",
            "legacy holder",
        ],
        capsys,
    )
    status = run_cli(["status", str(ITEM)], capsys)

    assert (released.status, released.stderr) == (0, "")
    assert (status.status, status.stdout) == (0, f"UNCLAIMED issue #{ITEM}\n")


def test_status_of_a_lane_claim_prints_its_branch_escaped_in_the_subject(
    github_clone: Path, bare_remote: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STAT-32"""
    intent = _escaping_claim(protocol.LaneIdentity())
    publish_claims_from_a_second_clone(github_clone, bare_remote, (intent,))

    result = run_cli(["status"], capsys)

    assert result.status == 0
    assert result.stdout.startswith(f"CLAIMED lane {ESCAPED_BRANCH}: ")


def test_status_json_carries_a_stored_claim_as_stored(
    seeded_claim: protocol.ClaimIntent, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STAT-32, CLAIM-74"""
    result = run_cli(["status", "--json"], capsys)

    [claim] = json.loads(result.stdout)["claims"]
    assert (result.status, claim["agent"], claim["role"], claim["branch"], claim["whole"]) == (
        0,
        seeded_claim.agent,
        seeded_claim.role,
        seeded_claim.branch,
        seeded_claim.whole_reason,
    )


def test_brief_prints_each_display_control_of_a_stored_claim_as_its_escape(
    seeded_claim: protocol.ClaimIntent, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BRIEF-28, CLAIM-74"""
    result = run_cli(["brief", str(ITEM)], capsys)

    claim_lines = result.stdout.split("CLAIM\n", 1)[1].splitlines()
    assert result.status == 0
    assert claim_lines[0].startswith(f"{ESCAPED_HOLDER} branch={ESCAPED_BRANCH} base=")
    assert ESCAPED_WHOLE in claim_lines


def test_brief_json_carries_a_stored_claim_as_stored(
    seeded_claim: protocol.ClaimIntent, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BRIEF-28, CLAIM-74"""
    result = run_cli(["brief", str(ITEM), "--json"], capsys)

    claim = json.loads(result.stdout)["claim"]
    assert (result.status, claim["agent"], claim["role"], claim["branch"], claim["whole"]) == (
        0,
        seeded_claim.agent,
        seeded_claim.role,
        seeded_claim.branch,
        seeded_claim.whole_reason,
    )
