"""Board and claim scenarios for test_board, test_body_cli, test_checkout,
test_cli, test_cut, test_github, test_items, test_protocol, test_rulings,
test_session, test_state_board, cli_fixtures, and github_fixtures.

Consumers import this module directly: pytest's rootless collection puts
tests/ on sys.path, so import board_fixtures resolves here.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from types import MappingProxyType

import pytest

from aco import forge, github_probe, protocol, workboard
from aco.body import (
    BLOCK_FENCE_INFO,
    ItemKind,
    locate_block,
    prose_above_fresh_block,
    render_block,
    replace_block,
)
from aco.protocol import ClaimRequest
from aco.session import RunContext

# Display controls a slice title refuses beside the Cc set --
# the bidi override and isolate and the zero-width space -- with the code
# point BODY-63 names.
BIDI_AND_ZERO_WIDTH_CONTROLS = (
    ("\N{RIGHT-TO-LEFT OVERRIDE}", "U+202E"),
    ("\N{LEFT-TO-RIGHT ISOLATE}", "U+2066"),
    ("\N{ZERO WIDTH SPACE}", "U+200B"),
)


BASE = "a" * 40


class _NoRulingSearch:
    def search(self, query: str) -> forge.RulingSearchResult:
        raise AssertionError(f"this test searches no rulings, yet {query!r} was searched")


class NoBoardProbe:
    def changed_since(self, target: forge.ProbeTarget, token: str | None) -> forge.ProbeAnswer:
        raise AssertionError(f"this test probes no board, yet {target!r} was probed")


searchless = partial(RunContext, ruling_search=_NoRulingSearch(), board_probe=NoBoardProbe())
"""A `RunContext` whose test never searches rulings and never probes the board: either fails
the test."""


@dataclass
class FakeBoardProbe:
    """A board probe whose targets stand for the tokens in `tokens` (the first one a
    target is asked about is `"first"`); a `failure` set answers every question."""

    tokens: dict[forge.ProbeTarget, str] = field(default_factory=dict)
    failure: forge.ForgeError | None = None
    asked: list[forge.ProbeTarget] = field(default_factory=list)

    def changed_since(self, target: forge.ProbeTarget, token: str | None) -> forge.ProbeAnswer:
        self.asked.append(target)
        if self.failure is not None:
            raise self.failure
        current = self.tokens.setdefault(target, "first")
        return forge.ProbeAnswer(changed=current != token, token=current)

    def change(self, target: forge.ProbeTarget) -> None:
        """What the forge answers for `target` from now on differs from what it answered."""
        self.tokens[target] = f"{self.tokens.get(target, 'first')}+"


def serve_board_probe(monkeypatch: pytest.MonkeyPatch, probe: FakeBoardProbe) -> FakeBoardProbe:
    """Installs one arranged probe as GitHub's board probe."""
    monkeypatch.setattr(github_probe, "GitHubBoardProbe", lambda _run: probe)
    return probe


REPOSITORY = "example/agent-coordination"


def request(
    claim_id: str = "claim-a",
    agent: str = "Codex Sol",
    *,
    issue: int | None = 71,
    lane: bool = False,
    role: str = "builder",
    branch: str | None = None,
    scope: tuple[str, ...] = ("docs/COORDINATION.md", "scripts/issue_claim.py"),
    resource: str | None = None,
    resource_value: int | None = None,
    whole_reason: str | None = None,
) -> ClaimRequest:
    """Build a `ClaimRequest`, issue-identified by default or lane-identified via `lane=True`.

    `issue=None` implies `lane=True` (mirrors the CLI's own "omitted issue number
    means lane mode" rule) so parametrized tables can drive both identity kinds
    from one `issue`/`lane` axis without hand-building identities at every call site.
    """
    lane = lane or issue is None
    identity: protocol.ClaimIdentity
    if lane:
        identity = protocol.LaneIdentity()
    else:
        assert issue is not None, "lane is False only when the caller passed an issue"
        identity = protocol.IssueIdentity(issue)
    default_branch = f"docs/lane-{claim_id}" if lane else f"codex/issue-{issue}-claims"
    return ClaimRequest(
        identity=identity,
        agent=agent,
        role=role,
        base=BASE,
        branch=branch or default_branch,
        scope=scope,
        claim_id=claim_id,
        resource=resource,
        resource_value=resource_value,
        whole_reason=whole_reason,
    )


def projected_board(
    issues: tuple[workboard.Issue, ...],
    open_pull_requests: tuple[workboard.PullRequest, ...],
    recent_merged_pull_requests: tuple[workboard.PullRequest, ...],
    claims: tuple[protocol.ScopedClaim, ...],
    config: workboard.BoardConfig,
    *,
    repository: str = REPOSITORY,
    now: datetime | None = None,
    today: date | None = None,
    trunk_landings: tuple[datetime, ...] = (),
    trunk_landing_items: tuple[workboard.TrunkLandingItem, ...] = (),
    children: Mapping[int, workboard.ChildList] = MappingProxyType({}),
    dependencies: Mapping[int, tuple[workboard.IssueDependency, ...]] = MappingProxyType({}),
    open_pull_requests_supported: bool = True,
) -> workboard.Board:
    """`workboard.build_board` for scenarios that do not turn on which repository is projected."""
    observed_at = now or datetime(2026, 8, 21, tzinfo=UTC)
    return workboard.build_board(
        workboard.BoardBuildInputs(
            issues=issues,
            open_pull_requests=open_pull_requests,
            recent_merged_pull_requests=recent_merged_pull_requests,
            claims=claims,
            config=config,
            repository=repository,
            now=observed_at,
            today=today or observed_at.date(),
            trunk_landings=trunk_landings,
            trunk_landing_items=trunk_landing_items,
            children=children,
            dependencies=dependencies,
            claim_ages={claim.claim_id: observed_at for claim in claims},
            open_pull_requests_supported=open_pull_requests_supported,
        )
    )


def store_claim_from_request(
    claimed: ClaimRequest, *, opened_commit: str = BASE
) -> protocol.ActiveClaim:
    resource = None
    if claimed.resource is not None and claimed.resource_value is not None:
        resource = protocol.ResourceHold(claimed.resource, claimed.resource_value)
    return protocol.ActiveClaim(
        identity=claimed.identity,
        claim_id=protocol.ClaimId(claimed.claim_id),
        agent=claimed.agent,
        role=claimed.role,
        base=protocol.ObjectId(claimed.base),
        branch=claimed.branch,
        scope=claimed.scope,
        opened_commit=protocol.ObjectId(opened_commit),
        resource=resource,
        whole_reason=claimed.whole_reason,
    )


def standing_active_claim(
    agent: str = "Grok sess-1",
    *,
    claim_id: str = "cli-claim",
    role: str = "builder",
    scope: tuple[str, ...] = ("src",),
    branch: str = "codex/issue-72-claims",
    lane: bool = False,
    issue: int = 72,
    base: str = BASE,
    opened_commit: str = BASE,
    resource: protocol.ResourceHold | None = None,
    whole_reason: str | None = None,
) -> protocol.ActiveClaim:
    """Build one store-truth `ActiveClaim` directly: the store
    fake's counterpart to `request()`'s ledger-comment `ClaimRequest` --
    every `status` test that needs a live claim on a faked
    `store.fetch_state` builds it from here instead of round-tripping
    through a comment marker no store command reads any more."""
    identity: protocol.ClaimIdentity = (
        protocol.LaneIdentity() if lane else protocol.IssueIdentity(issue)
    )
    return protocol.ActiveClaim(
        identity=identity,
        claim_id=protocol.ClaimId(claim_id),
        agent=agent,
        role=role,
        base=protocol.ObjectId(base),
        branch=branch,
        scope=scope,
        opened_commit=protocol.ObjectId(opened_commit),
        resource=resource,
        whole_reason=whole_reason,
    )


def board_issue(
    number: int,
    title: str,
    body: str,
    *,
    labels: tuple[str, ...] = (),
    blocked_by_count: int = 0,
    kind: ItemKind | None = None,
    author_is_member: bool = True,
    children_closed: int | None = None,
    children_total: int | None = None,
) -> workboard.Issue:
    return workboard.Issue(
        number,
        title,
        labels,
        body,
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=kind,
        blocked_by_count=blocked_by_count,
        author_is_member=author_is_member,
        children_closed=children_closed,
        children_total=children_total,
    )


def block_dependency(
    number: int,
    *,
    repository: str = REPOSITORY,
    state: workboard.BlockerState = workboard.BlockerState.OPEN,
    is_pull_request: bool = False,
    closed_at: datetime | None = None,
) -> workboard.IssueDependency:
    return workboard.IssueDependency(
        workboard.IssueReference(repository, number), state, is_pull_request, closed_at
    )


def blocked_issue(
    number: int,
    title: str,
    *dependencies: workboard.IssueDependency,
    next_step: str | None = None,
    labels: tuple[str, ...] = (),
) -> tuple[workboard.Issue, dict[int, tuple[workboard.IssueDependency, ...]]]:
    """One item and the `blocked_by` dependencies GitHub records for it, with
    the listing count the forge would report for exactly those."""
    issue = board_issue(
        number,
        title,
        complete_contract(next_step or f"Claim #{number}."),
        labels=labels,
        blocked_by_count=len(dependencies),
    )
    return issue, {number: dependencies}


def block_body(
    toml_text: str,
    *,
    fence: str = "```",
    before: str = "Prose before.\n\n",
    after: str = "\nProse after.\n",
) -> str:
    """A body carrying one recognized block fence around `toml_text`, with
    `before` above it and `after` below its closing line -- ordinary prose
    on both sides by default."""
    return f"{before}{fence}{BLOCK_FENCE_INFO}\n{toml_text}\n{fence}\n{after}"


def container_issue(number: int, toml_text: str) -> workboard.Issue:
    return workboard.Issue(
        number,
        "Epic",
        (),
        block_body(toml_text),
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=ItemKind.CONTAINER,
        children_closed=0,
        children_total=0,
    )


def container_with_children(
    number: int,
    *,
    closed: int,
    open_children: tuple[int, ...] = (),
    title: str = "Container",
    body: str = "",
    foreign_open: tuple[workboard.IssueReference, ...] = (),
) -> tuple[workboard.Issue, workboard.ChildList]:
    """A container whose child-count summary matches its sub-issue list: the
    `open_children` numbers listed open, the `foreign_open` references listed
    open from another repository, then `closed` closed children numbered
    from 1000."""
    listed = (
        *(
            workboard.ChildItem(child, workboard.ChildState.OPEN, f"Child {child}")
            for child in open_children
        ),
        *(
            workboard.ForeignChild(reference, workboard.ChildState.OPEN)
            for reference in foreign_open
        ),
        *(
            workboard.ChildItem(1000 + index, workboard.ChildState.CLOSED, f"Child {1000 + index}")
            for index in range(closed)
        ),
    )
    container = workboard.Issue(
        number,
        title,
        (),
        body,
        "2026-08-20T00:00:00Z",
        "2026-08-20T00:00:00Z",
        kind=ItemKind.CONTAINER,
        children_closed=closed,
        children_total=len(listed),
    )
    return container, listed


def write_repository_config(
    toplevel: Path, content: str = "", *, path: Path = workboard.CONFIG_PATH
) -> None:
    """`content` written as the repository configuration file `path` under
    `toplevel` -- the board's by default, `workboard.BRIEF_CONFIG_PATH` for the
    brief's -- its directory created when missing."""
    config = toplevel / path
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(content, encoding="utf-8")


MINIMAL_BLOCK_TOML = 'version = 1\nnow = "N"\nnext = "X"\ndone_when = "D"\n'
RULED_ON = date(2026, 8, 28)


def complete_contract(
    next_step: str,
    *,
    now: str = "Work is ready.",
    done_when: str = "The work is merged.",
    **block_entries: object,
) -> str:
    """A body whose one `aco` block carries every projection key
    filled, plus whatever `[[expectation]]`/`[[slice]]`/`wait`
    entries the scenario needs -- serialized by the production writer, so no
    test hand-writes the block's TOML escaping."""
    data: dict[str, object] = {
        "version": 1,
        "now": now,
        "next": next_step,
        "done_when": done_when,
        **block_entries,
    }
    return block_body(render_block(data).rstrip("\n"))


def unfilled_block_body(prose: str = "") -> str:
    """`prose` above a block whose three projection keys are present and
    empty -- a body nobody has filled yet: valid, but incomplete (BODY-12).
    Written by the production writer of a fresh block, so no test
    hand-writes its TOML."""
    return prose_above_fresh_block(prose, {})


WAIT_TRIGGER = "eine zweite Maschine bekommt einen Grund"
TRIGGER_WAIT = {"trigger": WAIT_TRIGGER, "since": date(2026, 8, 31)}
OPERATOR_WAIT = {"operator": "Decide.", "since": date(2026, 8, 31)}


def holding_for_the_operator(raw_body: str, step: Mapping[str, str] | None = None) -> str:
    """`raw_body` with an operator `wait` in its block, and `step` as its `[step]` table when
    given, written by the production writer."""
    located = locate_block(raw_body)
    held = {**located.data, "wait": OPERATOR_WAIT}
    return replace_block(raw_body, located, held if step is None else {**held, "step": dict(step)})


def ruled_expectation(
    text: str,
    *,
    ruling: str = "yes",
    ruled_on: date = RULED_ON,
    question: str | None = None,
    example: str | None = None,
    picture: str | None = None,
) -> dict[str, object]:
    """A ruled yes/no `[[expectation]]` entry, plus whichever of the optional
    card fields the scenario needs -- omitted entirely when left `None`."""
    entry: dict[str, object] = {"text": text, "ruling": ruling, "ruled_on": ruled_on}
    entry.update(
        (key, value)
        for key, value in (("question", question), ("example", example), ("picture", picture))
        if value is not None
    )
    return entry


def idea_body(wish: str) -> str:
    """An operator's idea: the wish in their own prose, above a block whose
    projection keys are all still empty."""
    return f"## Wunsch\n{wish}\n\n" + complete_contract("", now="", done_when="")


def slice_entries(*titles: str, first_index: int = 1) -> list[dict[str, object]]:
    """`[[slice]]` entries numbered from `first_index`, in order."""
    return [{"index": first_index + offset, "title": title} for offset, title in enumerate(titles)]
