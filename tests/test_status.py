"""`aco status` reads the state ref and nothing else: no forge, no write; a claim's
age is the committer date of the commit that preceded its own."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, timedelta
from pathlib import Path

import pytest
from cli_fixtures import (
    FROZEN_CLI_NOW,
    forbid_github_construction,
    freeze_cli_now,
    head_sha,
    real_git,
    run_cli,
)
from github_fixtures import assert_github_world
from store_fixtures import (
    claim_intent,
    publish_claims_from_a_second_clone,
    push_twin_claim,
    state_ref_tip,
)

from agent_coordination import board, cmd_status, github, protocol, store

BOARD_CONFIGURATION = ""
Flags = list[str]
Record = tuple[object, ...]


def issue_claim(number: int, agent: str, claim_id: str, *scope: str) -> protocol.ClaimIntent:
    return claim_intent(
        identity=protocol.IssueIdentity(number),
        agent=agent,
        branch=f"ada/issue-{number}",
        scope=scope,
        claim_id=claim_id,
        operation_id=f"op-{claim_id}",
    )


def lane_claim(branch: str, claim_id: str, *scope: str) -> protocol.ClaimIntent:
    return claim_intent(
        identity=protocol.LaneIdentity(),
        agent="Ada",
        branch=branch,
        scope=scope,
        claim_id=claim_id,
        operation_id=f"op-{claim_id}",
    )


@dataclass(frozen=True)
class StatusWorld:
    claims: tuple[protocol.ClaimIntent, ...] = ()
    bootstrapped: bool = True
    claim_age: timedelta = timedelta(0)
    twin: protocol.ClaimIntent | None = None


@dataclass(frozen=True)
class StatusCase:
    world: StatusWorld
    argv: tuple[str, ...]
    exit: int
    text: str
    envelope: dict[str, object]


def block(subject: str, claim: protocol.ClaimIntent, *lines: str, age: str = "0h 0m") -> str:
    head = (
        f"{subject}: {claim.agent} (builder) base=<base> "
        f"branch={claim.branch} claim={claim.claim_id} {age}"
    )
    return "\n".join([head, *lines]) + "\n"


def identity_fields(claim: protocol.ClaimIntent) -> dict[str, object]:
    if isinstance(claim.identity, protocol.IssueIdentity):
        return {"issue": claim.identity.issue, "lane": None}
    return {"issue": None, "lane": True}


def claim_object(
    claim: protocol.ClaimIntent,
    *,
    resource: str | None = None,
    resource_value: int | None = None,
    whole: str | None = None,
    overlaps: list[dict[str, object]] | None = None,
    state: str = "CLAIMED",
    age: str = "0h 0m",
    old: bool = False,
) -> dict[str, object]:
    return {
        **identity_fields(claim),
        "claim_id": claim.claim_id,
        "agent": claim.agent,
        "role": "builder",
        "base": "<base>",
        "branch": claim.branch,
        "scope": list(claim.scope),
        "resource": resource,
        "resource_value": resource_value,
        **({"whole": whole} if whole else {}),
        "overlaps": overlaps or [],
        "state": state,
        "age": age,
        "old": old,
    }


def peer(claim: protocol.ClaimIntent) -> dict[str, object]:
    return {**identity_fields(claim), "claim_id": claim.claim_id, "agent": claim.agent}


def listing(
    reason: str, issue: int | None, tip: str | None, *claims: dict[str, object], ok: bool = True
) -> dict[str, object]:
    return {
        "ok": ok,
        "reason": reason,
        "issue": issue,
        "tip": tip,
        "claims": list(claims),
        "lane_shared": [],
        "lane_shared_unavailable": None,
    }


TWO_PATHS = issue_claim(72, "Ada", "claim-a", "docs", "src")
SECOND = issue_claim(73, "Grok", "claim-b", "tests")
THIRD = issue_claim(74, "Ada", "claim-c", "src")
SHARED = issue_claim(72, "Ada", "claim-a", "shared")
SHARED_FILE = issue_claim(73, "Grok", "claim-b", "shared/file.py")
DESCENDANT = issue_claim(72, "Ada", "claim-a", "shared/file.py")
PARENT = issue_claim(73, "Grok", "claim-b", "shared")
TIDY = lane_claim("docs/tidy", "claim-lane", "docs")
OTHER_LANE = lane_claim("docs/other", "claim-other", "notes")
TWIN = replace(TIDY, claim_id=protocol.ClaimId("twin-claim-lane"))
GUIDE = issue_claim(74, "Ada", "claim-guide", "docs/guide.md")
SRC_ONLY = issue_claim(72, "Ada", "claim-a", "src")
HELD = replace(
    SRC_ONLY,
    whole_reason="touches too much",
    resource_name="schema-hop",
    resource_value=1,
)
UNCLAIMED_REPOSITORY = "UNCLAIMED repository\n"

UNCLAIMED_ROWS = {
    "unclaimed-before-bootstrap": StatusCase(
        StatusWorld(bootstrapped=False),
        ("status",),
        0,
        UNCLAIMED_REPOSITORY,
        listing("unclaimed", None, None),
    ),
    "unclaimed-repository": StatusCase(
        StatusWorld(), ("status",), 0, UNCLAIMED_REPOSITORY, listing("unclaimed", None, "<tip>")
    ),
    "unclaimed-issue": StatusCase(
        StatusWorld(claims=(SECOND,)),
        ("status", "72"),
        0,
        "UNCLAIMED issue #72\n",
        listing("unclaimed", 72, "<tip>"),
    ),
}
LIVE_ROWS = {
    "claimed-issue": StatusCase(
        StatusWorld(claims=(TWO_PATHS,)),
        ("status", "72"),
        0,
        block("CLAIMED issue #72", TWO_PATHS, "  docs", "  src"),
        listing("claimed", 72, "<tip>", claim_object(TWO_PATHS)),
    ),
    "lane-claim": StatusCase(
        StatusWorld(claims=(TIDY,)),
        ("status",),
        0,
        block("CLAIMED lane docs/tidy", TIDY, "  docs"),
        listing("claimed", None, "<tip>", claim_object(TIDY)),
    ),
    "resource-and-whole": StatusCase(
        StatusWorld(claims=(HELD,)),
        ("status", "72"),
        0,
        block(
            "CLAIMED issue #72",
            HELD,
            "  src",
            "  resource schema-hop=1",
            "  whole: touches too much",
        ),
        listing(
            "claimed",
            72,
            "<tip>",
            claim_object(HELD, resource="schema-hop", resource_value=1, whole="touches too much"),
        ),
    ),
    "past-the-hour": StatusCase(
        StatusWorld(claims=(SRC_ONLY,), claim_age=timedelta(minutes=61)),
        ("status", "72"),
        0,
        block("CLAIMED issue #72", SRC_ONLY, "  src", age="1h 1m old"),
        listing("claimed", 72, "<tip>", claim_object(SRC_ONLY, age="1h 1m", old=True)),
    ),
    "exactly-an-hour": StatusCase(
        StatusWorld(claims=(SRC_ONLY,), claim_age=timedelta(hours=1)),
        ("status", "72"),
        0,
        block("CLAIMED issue #72", SRC_ONLY, "  src", age="1h 0m"),
        listing("claimed", 72, "<tip>", claim_object(SRC_ONLY, age="1h 0m")),
    ),
}
OVERLAPPING_ROWS = {
    "overlapping-claims": StatusCase(
        StatusWorld(claims=(SHARED, SHARED_FILE)),
        ("status",),
        0,
        block("CLAIMED issue #72", SHARED, "  shared", "  overlaps issue #73 (claim-b)")
        + block(
            "CLAIMED issue #73", SHARED_FILE, "  shared/file.py", "  overlaps issue #72 (claim-a)"
        ),
        listing(
            "claimed",
            None,
            "<tip>",
            claim_object(SHARED, overlaps=[peer(SHARED_FILE)]),
            claim_object(SHARED_FILE, overlaps=[peer(SHARED)]),
        ),
    ),
    "claimed-after-its-descendant": StatusCase(
        StatusWorld(claims=(DESCENDANT, PARENT)),
        ("status",),
        0,
        block("CLAIMED issue #72", DESCENDANT, "  shared/file.py", "  overlaps issue #73 (claim-b)")
        + block("CLAIMED issue #73", PARENT, "  shared", "  overlaps issue #72 (claim-a)"),
        listing(
            "claimed",
            None,
            "<tip>",
            claim_object(DESCENDANT, overlaps=[peer(PARENT)]),
            claim_object(PARENT, overlaps=[peer(DESCENDANT)]),
        ),
    ),
    "issue-names-its-peers": StatusCase(
        StatusWorld(claims=(SHARED, SHARED_FILE, THIRD)),
        ("status", "72"),
        0,
        block("CLAIMED issue #72", SHARED, "  shared", "  overlaps issue #73 (claim-b)")
        + block(
            "CLAIMED issue #73", SHARED_FILE, "  shared/file.py", "  overlaps issue #72 (claim-a)"
        ),
        listing(
            "claimed",
            72,
            "<tip>",
            claim_object(SHARED, overlaps=[peer(SHARED_FILE)]),
            claim_object(SHARED_FILE, overlaps=[peer(SHARED)]),
        ),
    ),
    "disjoint-claims": StatusCase(
        StatusWorld(claims=(SRC_ONLY, SECOND, TIDY, OTHER_LANE)),
        ("status",),
        0,
        block("CLAIMED issue #72", SRC_ONLY, "  src")
        + block("CLAIMED issue #73", SECOND, "  tests")
        + block("CLAIMED lane docs/other", OTHER_LANE, "  notes")
        + block("CLAIMED lane docs/tidy", TIDY, "  docs"),
        listing(
            "claimed",
            None,
            "<tip>",
            claim_object(SRC_ONLY),
            claim_object(SECOND),
            claim_object(OTHER_LANE),
            claim_object(TIDY),
        ),
    ),
}
CONFLICT_ROWS = {
    "identity-conflict": StatusCase(
        StatusWorld(claims=(TIDY,), twin=TWIN),
        ("status",),
        2,
        block("CONFLICT lane docs/tidy", TWIN, "  docs", "  overlaps lane docs/tidy (claim-lane)")
        + block(
            "CONFLICT lane docs/tidy", TIDY, "  docs", "  overlaps lane docs/tidy (twin-claim-lane)"
        ),
        listing(
            "conflict",
            None,
            "<tip>",
            claim_object(TWIN, overlaps=[peer(TIDY)], state="CONFLICT"),
            claim_object(TIDY, overlaps=[peer(TWIN)], state="CONFLICT"),
            ok=False,
        ),
    ),
    "conflict-beside-an-overlap": StatusCase(
        StatusWorld(claims=(TIDY, GUIDE), twin=TWIN),
        ("status",),
        2,
        block(
            "CLAIMED issue #74",
            GUIDE,
            "  docs/guide.md",
            "  overlaps lane docs/tidy (claim-lane), lane docs/tidy (twin-claim-lane)",
        )
        + block(
            "CONFLICT lane docs/tidy",
            TWIN,
            "  docs",
            "  overlaps issue #74 (claim-guide), lane docs/tidy (claim-lane)",
        )
        + block(
            "CONFLICT lane docs/tidy",
            TIDY,
            "  docs",
            "  overlaps issue #74 (claim-guide), lane docs/tidy (twin-claim-lane)",
        ),
        listing(
            "conflict",
            None,
            "<tip>",
            claim_object(GUIDE, overlaps=[peer(TIDY), peer(TWIN)]),
            claim_object(TWIN, overlaps=[peer(GUIDE), peer(TIDY)], state="CONFLICT"),
            claim_object(TIDY, overlaps=[peer(GUIDE), peer(TWIN)], state="CONFLICT"),
            ok=False,
        ),
    ),
}


@dataclass(frozen=True)
class Observation:
    exit: int | str | None
    stdout: str
    stderr: str
    written: tuple[str, str]


def refs_of(clone: Path, remote: Path) -> tuple[str, str]:
    """Every ref of the clone, except the anchor each state read sets, and of the remote."""
    clone_refs = "".join(
        record + "\n"
        for record in real_git(
            clone, "for-each-ref", "--format=%(refname) %(objectname)"
        ).stdout.splitlines()
        if record.split(" ", 1)[0] != "refs/worktree/aco/state"
    )
    return clone_refs, real_git(remote, "for-each-ref").stdout


def recorded(claim: protocol.ClaimIntent, opened_commit: str) -> Record:
    resource = None if claim.resource_name is None else (claim.resource_name, claim.resource_value)
    return (
        claim.identity,
        claim.claim_id,
        claim.agent,
        claim.role,
        claim.base,
        claim.branch,
        claim.scope,
        resource,
        claim.whole_reason,
        opened_commit,
    )


def published(claim: protocol.ActiveClaim) -> Record:
    resource = None if claim.resource is None else (claim.resource.name, claim.resource.value)
    return (
        claim.identity,
        claim.claim_id,
        claim.agent,
        claim.role,
        claim.base,
        claim.branch,
        claim.scope,
        resource,
        claim.whole_reason,
        claim.opened_commit,
    )


def assert_world_arranged(
    world: StatusWorld, intents: tuple[protocol.ClaimIntent, ...], clone: Path, remote: Path
) -> str | None:
    """The state ref holds exactly the arranged claims, each opened at the commit before
    its own, and every commit carries the arranged committer date."""
    tip = state_ref_tip(remote)
    assert (tip is not None) == world.bootstrapped
    assert real_git(clone, "for-each-ref", store.STATE_REF).stdout == ""
    if tip is None:
        return None
    history = [
        line.split()
        for line in real_git(
            remote, "log", "--first-parent", "--reverse", "--format=%H %cI", tip
        ).stdout.splitlines()
    ]
    opened_at = (FROZEN_CLI_NOW - world.claim_age).isoformat()
    assert [date for _commit, date in history] == [
        opened_at,
        *[FROZEN_CLI_NOW.isoformat()] * (len(intents) + int(world.twin is not None)),
    ]
    opened_commits = {
        intent.claim_id: history[position][0] for position, intent in enumerate(intents)
    }
    arranged = {
        protocol.claim_key(intent.identity, intent.branch): recorded(
            intent, opened_commits[intent.claim_id]
        )
        for intent in intents
    }
    if world.twin is not None:
        original = next(intent for intent in intents if intent.branch == world.twin.branch)
        twin = replace(world.twin, base=original.base)
        arranged[f"{protocol.claim_key(twin.identity, twin.branch)}-twin"] = recorded(
            twin, opened_commits[original.claim_id]
        )
    live = store.peek_state(worktree=clone, remote=str(remote)).claims
    assert {key: published(claim) for key, claim in live.items()} == arranged
    return tip


def filled(text: str, base: str, tip: str | None) -> str:
    return text.replace("<base>", base).replace("<tip>", tip or "")


StatusCheck = Callable[[StatusCase, Flags], None]


@pytest.fixture
def check_status(
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> StatusCheck:
    monkeypatch.setenv("LC_ALL", "C")
    assert_github_world(github_clone, bare_remote)
    assert real_git(github_clone, "show", f"HEAD:{board.CONFIG_PATH}").stdout == BOARD_CONFIGURATION
    freeze_cli_now(monkeypatch)
    forbid_github_construction(monkeypatch)
    assert cmd_status.datetime.now(UTC) == FROZEN_CLI_NOW
    for forge_entry_point in ("GitHubForge", "discover_repository"):
        construct = getattr(github, forge_entry_point)
        with pytest.raises(pytest.fail.Exception):
            construct()
    assert Path.cwd() == github_clone
    monkeypatch.setenv("GIT_COMMITTER_DATE", FROZEN_CLI_NOW.isoformat())

    def check(case: StatusCase, flags: Flags) -> None:
        world = case.world
        base = head_sha(github_clone)
        intents = tuple(replace(claim, base=protocol.ObjectId(base)) for claim in world.claims)
        if world.bootstrapped:
            publish_claims_from_a_second_clone(
                github_clone,
                bare_remote,
                intents,
                bootstrapped_at=(FROZEN_CLI_NOW - world.claim_age).isoformat(),
            )
        if world.twin is not None:
            original = next(claim for claim in intents if claim.branch == world.twin.branch)
            push_twin_claim(bare_remote, github_clone, original, world.twin.claim_id)
        tip = assert_world_arranged(world, intents, github_clone, bare_remote)
        before = refs_of(github_clone, bare_remote)
        result = run_cli([*case.argv, *flags], capsys)
        stdout = json.dumps(case.envelope) + "\n" if flags else case.text
        observed = Observation(
            result.status, result.stdout, result.stderr, refs_of(github_clone, bare_remote)
        )
        expected = Observation(case.exit, filled(stdout, base, tip), "", before)
        assert observed == expected

    return check


IN_BOTH_FORMS = pytest.mark.parametrize("flags", [[], ["--json"]], ids=["text", "json"])


@IN_BOTH_FORMS
@pytest.mark.parametrize("case", UNCLAIMED_ROWS.values(), ids=UNCLAIMED_ROWS.keys())
def test_an_unclaimed_repository_or_issue_is_named_in_both_forms(
    case: StatusCase, flags: Flags, check_status: StatusCheck
) -> None:
    """Spec: STAT-01, STAT-02, STAT-03"""
    check_status(case, flags)


@IN_BOTH_FORMS
@pytest.mark.parametrize("case", LIVE_ROWS.values(), ids=LIVE_ROWS.keys())
def test_a_live_claim_shows_its_hold_and_age(
    case: StatusCase, flags: Flags, check_status: StatusCheck
) -> None:
    """Spec: STAT-07, STAT-09, STAT-17, CLAIM-01, CLAIM-29, CLAIM-41, CLAIM-47, CLAIM-48"""
    check_status(case, flags)


@IN_BOTH_FORMS
@pytest.mark.parametrize("case", OVERLAPPING_ROWS.values(), ids=OVERLAPPING_ROWS.keys())
def test_overlapping_claims_name_each_other(
    case: StatusCase, flags: Flags, check_status: StatusCheck
) -> None:
    """Spec: STAT-06, STAT-08, STAT-24"""
    check_status(case, flags)


@IN_BOTH_FORMS
@pytest.mark.parametrize("case", CONFLICT_ROWS.values(), ids=CONFLICT_ROWS.keys())
def test_two_claims_on_one_identity_are_a_conflict(
    case: StatusCase, flags: Flags, check_status: StatusCheck
) -> None:
    """Spec: STAT-04, STAT-05"""
    check_status(case, flags)
