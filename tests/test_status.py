"""`aco status` reads the state ref and nothing else: no forge, no write; a claim's
age is the committer date of the commit that preceded its own."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, timedelta
from pathlib import Path

import pytest
from cli_fixtures import (
    FROZEN_CLI_NOW,
    configure_github_remote,
    forbid_forge_resolution,
    freeze_cli_now,
    head_sha,
    push_repository_trunk,
    real_git,
    run_cli,
    track_board_config,
)
from github_fixtures import assert_github_world
from store_fixtures import (
    claim_intent,
    publish_claims_from_a_second_clone,
    push_claim_record,
    state_ref_tip,
    twin_claim_key,
)

from agent_coordination import cmd_status, github, protocol, store, workboard

STATE_REF_PIN = 'storage = "state-ref"\n'
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
    severed: bool = False
    board_configuration: str = ""
    github: bool = True
    trunk_resolves: bool = True
    stale_observation: bool = False


@dataclass(frozen=True)
class StatusCase:
    world: StatusWorld
    argv: tuple[str, ...]
    exit: int
    text: str
    envelope: dict[str, object]
    stderr: str = ""


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


def holder(
    claim: protocol.ClaimIntent,
    *,
    resource: str | None = None,
    resource_value: int | None = None,
    whole: str | None = None,
) -> dict[str, object]:
    full = claim_object(claim, resource=resource, resource_value=resource_value, whole=whole)
    return {key: value for key, value in full.items() if key not in {"overlaps", "age", "old"}}


def path_line(path: str, subject: str, claim: protocol.ClaimIntent, *lines: str) -> str:
    head = f"CLAIMED {path} {subject}: {claim.agent} (builder) claim={claim.claim_id}"
    return "\n".join([head, *lines]) + "\n"


def path_listing(reason: str, path: str, *claims: dict[str, object]) -> dict[str, object]:
    return {
        "ok": True,
        "reason": reason,
        "path": path,
        "claims": list(claims),
        "lane_shared": [],
        "lane_shared_unavailable": None,
    }


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
PRODUCT = issue_claim(72, "Ada", "claim-a", "docs", "src/widget.py")
DOCS = issue_claim(72, "Ada", "claim-a", "docs")
SRC_GROK = issue_claim(73, "Grok", "claim-b", "src")
BROKEN_CLAIM_AGE = "<base> is not an ancestor of <tip>; the ref may have been rewritten"

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
CLAIM_ON_SRC = StatusCase(
    StatusWorld(claims=(SRC_ONLY,)),
    ("status",),
    0,
    block("CLAIMED issue #72", SRC_ONLY, "  src"),
    listing("claimed", None, "<tip>", claim_object(SRC_ONLY)),
)
HOLDER_OF_SRC = StatusCase(
    CLAIM_ON_SRC.world,
    ("status", "--path", "src"),
    0,
    path_line("src", "issue #72", SRC_ONLY),
    path_listing("claimed", "src", holder(SRC_ONLY)),
)
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
LIVE_ROWS["no-trunk-resolves"] = replace(
    CLAIM_ON_SRC,
    world=replace(
        CLAIM_ON_SRC.world,
        board_configuration='lane_shared = ["scripts/registry.txt"]\n',
        trunk_resolves=False,
    ),
)
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

PATH_ROWS = {
    "one-holder": StatusCase(
        StatusWorld(claims=(PRODUCT,)),
        ("status", "--path", "docs/PRODUCT.md"),
        0,
        path_line("docs/PRODUCT.md", "issue #72", PRODUCT),
        path_listing("claimed", "docs/PRODUCT.md", holder(PRODUCT)),
    ),
    "no-holder-beside-a-claimed-directory": StatusCase(
        StatusWorld(claims=(DOCS,)),
        ("status", "--path", "docs2/guide.md"),
        0,
        "UNCLAIMED docs2/guide.md\n",
        path_listing("unclaimed", "docs2/guide.md"),
    ),
    "two-holders": StatusCase(
        StatusWorld(claims=(SRC_ONLY, SRC_GROK)),
        ("status", "--path", "src"),
        0,
        path_line("src", "issue #72", SRC_ONLY)
        + path_line("src", "issue #73", SRC_GROK)
        + "overlap: issue #72 (claim-a), issue #73 (claim-b)\n",
        path_listing("claimed", "src", holder(SRC_ONLY), holder(SRC_GROK)),
    ),
    "beside-an-issue-argument": replace(HOLDER_OF_SRC, argv=("status", "73", "--path", "src")),
    "holders-of-one-identity": StatusCase(
        StatusWorld(claims=(TIDY,), twin=TWIN),
        ("status", "--path", "docs"),
        0,
        path_line("docs", "lane docs/tidy", TWIN)
        + path_line("docs", "lane docs/tidy", TIDY)
        + "overlap: lane docs/tidy (twin-claim-lane), lane docs/tidy (claim-lane)\n",
        path_listing("claimed", "docs", holder(TWIN), holder(TIDY)),
    ),
    "holder-with-a-hold": StatusCase(
        StatusWorld(claims=(HELD,)),
        ("status", "--path", "src"),
        0,
        path_line("src", "issue #72", HELD, "  whole: touches too much"),
        path_listing(
            "claimed",
            "src",
            holder(HELD, resource="schema-hop", resource_value=1, whole="touches too much"),
        ),
    ),
}
SEVERED_WORLD = StatusWorld(claims=(PRODUCT,), severed=True)
SEVERED_ROWS = {
    "path-answers": replace(PATH_ROWS["one-holder"], world=SEVERED_WORLD),
    "status-refuses": StatusCase(
        SEVERED_WORLD,
        ("status",),
        2,
        "",
        {"ok": False, "reason": "unavailable", "message": BROKEN_CLAIM_AGE},
        f"ERROR: {BROKEN_CLAIM_AGE}\n",
    ),
}
MOVED_STATE_REF = (
    "refs/aco/state moved from <base> to <tip> without <base> as an ancestor of the new tip; "
    "the ref may have been rewritten"
)
STALE_ROW = replace(
    SEVERED_ROWS["status-refuses"],
    world=replace(SEVERED_WORLD, severed=False, stale_observation=True),
    envelope={"ok": False, "reason": "unavailable", "message": MOVED_STATE_REF},
    stderr=f"ERROR: {MOVED_STATE_REF}\n",
)
SEVERED_ROWS |= {
    "stale-observation-refuses": STALE_ROW,
    "stale-observation-refuses-a-path": replace(
        STALE_ROW, argv=("status", "--path", "docs/PRODUCT.md")
    ),
}
STATE_REF_WORLD = replace(
    OVERLAPPING_ROWS["overlapping-claims"].world, board_configuration=STATE_REF_PIN
)
FIRST_ITEM, SECOND_ITEM = "aco-000048", "aco-000049"
STATE_REF_ROWS = {
    "overlap-notes": replace(
        OVERLAPPING_ROWS["overlapping-claims"],
        world=STATE_REF_WORLD,
        text=block(
            f"CLAIMED issue {FIRST_ITEM}",
            SHARED,
            "  shared",
            f"  overlaps issue {SECOND_ITEM} (claim-b)",
        )
        + block(
            f"CLAIMED issue {SECOND_ITEM}",
            SHARED_FILE,
            "  shared/file.py",
            f"  overlaps issue {FIRST_ITEM} (claim-a)",
        ),
    ),
    "unclaimed-issue": replace(
        UNCLAIMED_ROWS["unclaimed-issue"],
        world=replace(STATE_REF_WORLD, claims=(SECOND,)),
        text=f"UNCLAIMED issue {FIRST_ITEM}\n",
    ),
    "path-with-two-holders": replace(
        PATH_ROWS["two-holders"],
        world=replace(STATE_REF_WORLD, claims=(SRC_ONLY, SRC_GROK)),
        text=path_line("src", f"issue {FIRST_ITEM}", SRC_ONLY)
        + path_line("src", f"issue {SECOND_ITEM}", SRC_GROK)
        + f"overlap: issue {FIRST_ITEM} (claim-a), issue {SECOND_ITEM} (claim-b)\n",
    ),
}
OUTSIDE_GITHUB = replace(CLAIM_ON_SRC.world, github=False)
FORGE_FREE_ROWS = {
    "another-repository-flag": replace(CLAIM_ON_SRC, argv=("--repo", "other/repository", "status")),
    "non-github-remote": replace(CLAIM_ON_SRC, world=OUTSIDE_GITHUB),
    "non-github-remote-path": replace(HOLDER_OF_SRC, world=OUTSIDE_GITHUB),
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
            remote, "log", "--first-parent", "--reverse", "--format=%H %ct", tip
        ).stdout.splitlines()
    ]
    opened_at = int((FROZEN_CLI_NOW - world.claim_age).timestamp())
    rewrites = int(world.twin is not None or world.severed)
    assert [int(date) for _commit, date in history] == [
        opened_at,
        *[int(FROZEN_CLI_NOW.timestamp())] * (len(intents) + rewrites),
    ]
    opened_commits = {
        intent.claim_id: history[position][0] for position, intent in enumerate(intents)
    }
    if world.severed:
        opened_commits[intents[0].claim_id] = intents[0].base
    arranged = {
        protocol.claim_key(intent.identity, intent.branch): recorded(
            intent, opened_commits[intent.claim_id]
        )
        for intent in intents
    }
    if world.twin is not None:
        original = next(intent for intent in intents if intent.branch == world.twin.branch)
        twin = replace(world.twin, base=original.base)
        arranged[twin_claim_key(original)] = recorded(twin, opened_commits[original.claim_id])
    live = store.peek_state(worktree=clone, remote=str(remote)).claims
    assert {key: published(claim) for key, claim in live.items()} == arranged
    return tip


def filled(text: str, base: str, tip: str | None) -> str:
    return text.replace("<base>", base).replace("<tip>", tip or "")


StatusCheck = Callable[[StatusCase, Flags], None]


@pytest.fixture
def check_status(
    clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> StatusCheck:
    monkeypatch.setenv("LC_ALL", "C")
    freeze_cli_now(monkeypatch)
    forbid_forge_resolution(monkeypatch)
    assert cmd_status.datetime.now(UTC) == FROZEN_CLI_NOW
    for forge_entry_point in ("GitHubForge", "discover_repository"):
        construct = getattr(github, forge_entry_point)
        with pytest.raises(pytest.fail.Exception):
            construct()
    assert Path.cwd() == clone
    monkeypatch.setenv("GIT_COMMITTER_DATE", FROZEN_CLI_NOW.isoformat())

    def check(case: StatusCase, flags: Flags) -> None:
        world = case.world
        if world.github:
            configure_github_remote(clone, bare_remote)
        if world.board_configuration:
            track_board_config(clone, world.board_configuration)
            push_repository_trunk(clone, "origin")
        if world.github:
            assert_github_world(clone, bare_remote)
        else:
            assert (
                real_git(clone, "config", "--get", "remote.origin.url").stdout == f"{bare_remote}\n"
            )
        assert real_git(clone, "show", f"HEAD:{workboard.CONFIG_PATH}").stdout == (
            world.board_configuration
        )
        base = head_sha(clone)
        intents = tuple(replace(claim, base=protocol.ObjectId(base)) for claim in world.claims)
        if world.bootstrapped:
            publish_claims_from_a_second_clone(
                clone,
                bare_remote,
                intents,
                bootstrapped_at=(FROZEN_CLI_NOW - world.claim_age).isoformat(),
            )
        if (twin := world.twin) is not None:
            original = next(claim for claim in intents if claim.branch == twin.branch)
            push_claim_record(
                bare_remote,
                clone,
                source_key=protocol.claim_key(original.identity, original.branch),
                key=twin_claim_key(original),
                edit=lambda record: record.replace(
                    f'claim_id = "{original.claim_id}"', f'claim_id = "{twin.claim_id}"'
                ),
            )
        if world.severed:
            first_key = protocol.claim_key(intents[0].identity, intents[0].branch)
            push_claim_record(
                bare_remote,
                clone,
                source_key=first_key,
                key=first_key,
                edit=lambda record: re.sub(
                    r'opened_commit = "\w+"', f'opened_commit = "{base}"', record
                ),
            )
        tip = assert_world_arranged(world, intents, clone, bare_remote)
        stamp = clone / ".git" / "aco" / "last-oid"
        if world.stale_observation:
            stamp.parent.mkdir(exist_ok=True)
            stamp.write_text(f"{base}\n")
        if not world.trunk_resolves:
            real_git(clone, "update-ref", "refs/remotes/origin/renamed", "refs/remotes/origin/main")
            real_git(clone, "update-ref", "-d", "refs/remotes/origin/main")
            real_git(clone, "symbolic-ref", "-d", "refs/remotes/origin/HEAD")
        trunk_names = ("HEAD", "main") if world.trunk_resolves else ("renamed",)
        before = refs_of(clone, bare_remote)
        origin_refs = [ref for ref in before[0].splitlines() if "/origin/" in ref]
        assert (stamp.read_text() if stamp.exists() else None, origin_refs) == (
            f"{base}\n" if world.stale_observation else None,
            [f"refs/remotes/origin/{name} {base}" for name in trunk_names],
        )
        result = run_cli([*case.argv, *flags], capsys)
        stdout = json.dumps(case.envelope) + "\n" if flags else case.text
        observed = Observation(
            result.status, result.stdout, result.stderr, refs_of(clone, bare_remote)
        )
        expected = Observation(
            case.exit, filled(stdout, base, tip), filled(case.stderr, base, tip), before
        )
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
    """Spec: STAT-07, STAT-09, STAT-17, STAT-19, STAT-31, CLAIM-01, CLAIM-29, CLAIM-41, CLAIM-47,
    CLAIM-48"""
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


@IN_BOTH_FORMS
@pytest.mark.parametrize("case", PATH_ROWS.values(), ids=PATH_ROWS.keys())
def test_a_path_names_the_claims_holding_it(
    case: StatusCase, flags: Flags, check_status: StatusCheck
) -> None:
    """Spec: STAT-10, STAT-11, STAT-12, STAT-13, STAT-25, STAT-26, STAT-27, STAT-28, CLAIM-35"""
    check_status(case, flags)


@IN_BOTH_FORMS
@pytest.mark.parametrize("case", SEVERED_ROWS.values(), ids=SEVERED_ROWS.keys())
def test_a_broken_state_ref_history_stops_status_but_a_path_survives_a_claim_age_break(
    case: StatusCase, flags: Flags, check_status: StatusCheck
) -> None:
    """Spec: STAT-18, STAT-29, STAT-30, CLAIM-50, CAS-11"""
    check_status(case, flags)


@IN_BOTH_FORMS
@pytest.mark.parametrize("case", STATE_REF_ROWS.values(), ids=STATE_REF_ROWS.keys())
def test_state_ref_items_are_labelled_by_id_and_numbered_in_json(
    case: StatusCase, flags: Flags, check_status: StatusCheck
) -> None:
    """Spec: STAT-14, STAT-15"""
    check_status(case, flags)


@IN_BOTH_FORMS
@pytest.mark.parametrize("case", FORGE_FREE_ROWS.values(), ids=FORGE_FREE_ROWS.keys())
def test_status_needs_no_forge_for_any_remote(
    case: StatusCase, flags: Flags, check_status: StatusCheck
) -> None:
    """Spec: STAT-16"""
    check_status(case, flags)
