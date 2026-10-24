"""Shared board reads, builds, claim history, validation, post-write hints,
and live-body gates before item rewrites."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from . import body, checkout, forge, metrics, protocol, store, workboard
from .session import RunContext


def parent_closable_number(
    client: forge.ForgeReader, closed_child: int, storage: body.Storage
) -> int | None:
    """The container `closed_child`'s own landing may just have completed
    (the parent hint `release --merged`/`item close` share): its
    parent, read fresh, when every other child is already closed too and no
    undispatched `[[slice]]` row is left to cut -- `workboard.closable_container_number`
    is the one owner for that decision, reused rather than re-derived board-wide
    for one relation. `None` covers every non-container parent, one still
    holding another open child, an already-closed parent (a second close
    would only refuse), or no parent at all. The container decision runs
    before the parent's own state read, so an unreadable parent
    (never a container by kind) is answered `None` rather than
    refusing a close that already stood."""
    parent = client.parent_issue(closed_child)
    if parent is None:
        return None
    children = client.list_children(parent.reference.number)
    closable = workboard.closable_container_number(parent, children, storage)
    if closable is None:
        return None
    parent_is_open = client.item_reference(closable).state is forge.ItemState.OPEN
    return closable if parent_is_open else None


# A stable invariant of the board's own ruling-freshness read,
# not something an operator tunes: `RULING_OLD_AFTER_LANDINGS` (10) is the
# most any ruling ever needs counted, so this bounds `git log`'s walk deep
# enough that no realistic ruling window is ever truncated.
TRUNK_LANDING_DEPTH = 5000


def validated_dependencies(
    issues: tuple[workboard.Issue, ...], fetched: dict[int, tuple[workboard.IssueDependency, ...]]
) -> dict[int, tuple[workboard.IssueDependency, ...]]:
    """`fetched`, keyed by exactly the positive-`blocked_by_count` issues,
    each list checked against its own listing count: a length
    mismatch or a duplicated dependency is the same class of malformed
    forge response as a disagreeing container summary -- named loud rather
    than guessed through."""
    validated: dict[int, tuple[workboard.IssueDependency, ...]] = {}
    for issue in issues:
        if issue.blocked_by_count <= 0:
            continue
        dependencies = fetched.get(issue.number, ())
        distinct = {dependency.reference for dependency in dependencies}
        length = len(dependencies)
        if length != issue.blocked_by_count or len(distinct) != length:
            raise forge.ForgeMalformedResponseError(
                f"GitHub returned a malformed board blocked-by list for #{issue.number}: "
                f"listing total_blocked_by={issue.blocked_by_count}, detail length={length}"
            )
        validated[issue.number] = dependencies
    return validated


def load_board_config(client: forge.BoardSource, context: RunContext) -> workboard.BoardConfig:
    """`context`'s board configuration, validated against what `client`
    can actually do: reading a body's dependencies requires
    `list_board_dependencies` at read-only or better, and the typed block is
    the one body grammar, so every repository needs it."""
    config = context.config
    if (
        client.capability(forge.ForgeOperation.LIST_BOARD_DEPENDENCIES)
        is forge.Capability.UNSUPPORTED
    ):
        raise protocol.ClaimError(
            "reading work-item bodies requires forge operation list_board_dependencies"
        )
    return config


def fetch_issue_reference(client: forge.ForgeReader, number: int) -> forge.ItemReference:
    """The live state, title, and body of issue `number` from `client`.

    Called only for a claim target that the already-fetched open board
    didn't resolve as OPEN — a closed or missing issue never appears in
    `list_open_board_issues`, so those two states need their own targeted
    lookup; this is that lookup, kept to one issue at a time rather than a
    repository-wide query.
    """
    return client.item_reference(number)


_BoardRead = TypeVar("_BoardRead")


def board_read_after_write(read: Callable[[], _BoardRead]) -> _BoardRead | str:
    """`read`'s result, or the one hint that replaces it, for a board read a
    command runs once its own write already committed (`release --merged`,
    `item close`): a forge hiccup (LAND-38) or a
    board read refusal (LAND-65) can only downgrade that report, never undo
    or fail the write, so this is the one owner of which refusals become a
    hint and what it says."""
    try:
        return read()
    except forge.ForgeError as error:
        return _board_read_hint(error, "once the forge is reachable")
    except protocol.MalformedStateTreeError as error:
        return _board_read_hint(error, "once it is repaired")


def _board_read_hint(refusal: protocol.ClaimError, until: str) -> str:
    """The one wording every post-write command shares: it
    names the write rather than a landing, since `item close` lands
    nothing, and advises the one board read that runs as printed."""
    return (
        f"hint: could not read the board to report what this write freed ({refusal}); "
        f"run `aco board --json` {until}"
    )


def print_board_read_hint(hint: str, *, as_json: bool) -> None:
    """Print `board_read_after_write`'s hint on the channel both of its
    callers share: stderr under `--json`, so stdout stays one JSON document,
    and stdout in text mode, in place of the lines the read would have
    printed."""
    print(hint, file=sys.stderr if as_json else sys.stdout)


def missing_item_refusal(number: int, client: forge.ForgeReader, storage: body.Storage) -> str:
    """The refusal sentence for a missing item number -- every forge-backed
    command that checks `client.item_reference(number).state is
    forge.ItemState.MISSING` before acting shares this one sentence rather
    than typing it out again. The repository slot is the canonical remote's
    own path: `owner/repo` on a forge host, the bare remote's local path
    for a forge-less remote under `state-ref` (PIN-28)."""
    return f"{workboard.item_label(number, storage)} does not exist in {client.repository.path}"


# A container's children are their own `gh list_children` subprocess call;
# an unbounded pool would spawn one worker per container on a large board.
# This caps that fan-out -- a stable invariant of this executor, not
# something an operator tunes. `_fetch_children` gives it a dedicated
# executor sized to exactly this constant, so the cap holds regardless of
# whether the three base board reads below have already finished.
BOARD_CHILD_FETCH_CONCURRENCY = 4


def _fetch_children(
    client: forge.BoardSource, container_numbers: tuple[int, ...]
) -> dict[int, tuple[workboard.ChildItem, ...]]:
    """Every container's children, at most `BOARD_CHILD_FETCH_CONCURRENCY`
    `gh` subprocesses at a time; excess containers queue behind it."""
    if not container_numbers:
        return {}
    workers = min(len(container_numbers), BOARD_CHILD_FETCH_CONCURRENCY)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            number: pool.submit(client.list_children, number) for number in container_numbers
        }
        return {number: future.result() for number, future in futures.items()}


def fetch_dependencies(
    client: forge.BoardSource, issue_numbers: tuple[int, ...]
) -> dict[int, tuple[workboard.IssueDependency, ...]]:
    """Every named issue's `blocked_by` dependencies, at most
    `BOARD_CHILD_FETCH_CONCURRENCY` `gh` subprocesses at a time -- run only
    after `build_board`'s base reads and children wave have already finished,
    so this wave never overlaps them."""
    if not issue_numbers:
        return {}
    workers = min(len(issue_numbers), BOARD_CHILD_FETCH_CONCURRENCY)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            number: pool.submit(client.list_board_dependencies, number) for number in issue_numbers
        }
        return {number: future.result() for number, future in futures.items()}


@dataclass(frozen=True)
class ClaimHistory:
    """The store's own git-history reads one board build needs:
    bundled into one parameter so `build_board` stays under the five-argument
    ceiling instead of growing a `claim_ages`-shaped parameter every time
    another history read joins it. `ages`, `lane_events`, and
    `unparsed_lifecycle_commits` are always read from the same
    already-fetched `ClaimState` (`_claim_history` below), never from two
    different observations."""

    ages: Mapping[str, datetime] = field(default_factory=dict)
    lane_events: tuple[metrics.LaneEvent, ...] = ()
    # Claim-shaped `refs/aco/state` commits `store.claim_lifecycle` could not
    # parse -- older history predating the `item:` trailer,
    # or a foreign commit merely shaped like one -- counted rather than
    # silently dropped.
    unparsed_lifecycle_commits: int = 0


@dataclass(frozen=True)
class LandingReads:
    """What a merged release already read before its board report, bundled so
    `build_board` stays under the five-argument ceiling:
    the dependency wave `workboard.freed_item_numbers` needed for the same candidate
    set, and the trunk ref the release judged its landing on, which the
    board walks instead of the trunk as the last fetch left it."""

    dependencies: dict[int, tuple[workboard.IssueDependency, ...]]
    trunk_ref: str


def _closed_item_sizes(
    client: forge.ForgeReader, numbers: frozenset[int], storage: body.Storage
) -> dict[int, metrics.Size | None]:
    """Each closed (or vanished) item's own current size, read through one
    batched forge/state fetch: a completed lane
    for a since-closed item still belongs in its size class's own measured
    lanes -- most lanes close their item on landing, so without this the
    size classes `aco board` estimates from would stay almost always empty.
    `ItemState.MISSING` (a deleted or renumbered item) and a bodyless
    reference both read as no size, exactly like an open item that never
    carried a `size` key. `client.item_references` -- not one `item_
    reference` call per number -- is what turned this from the board's own
    dominant cost (32 serial round trips, 12.8 of an 18s build) into a
    single round trip that stays flat as the closed-item history grows."""
    references = client.item_references(numbers)
    return {
        number: (
            None
            if (raw_body := references[number].body) is None
            else body.parse_body(raw_body, storage=storage).size
        )
        for number in numbers
    }


def build_board(
    context: RunContext,
    claims: tuple[protocol.ActiveClaim, ...],
    *,
    issues: tuple[workboard.Issue, ...] | None = None,
    history: ClaimHistory | None = None,
    landing: LandingReads | None = None,
) -> workboard.Board:
    history = history or ClaimHistory()
    now = datetime.now(UTC)
    client = context.forge
    config = load_board_config(client, context)
    if issues is None:
        issues = client.list_open_board_issues()
    since = workboard.merged_pull_request_floor(issues, now)
    # A container whose own summary already says 0 (or carries no summary at
    # all, `children_total is None`) can never own an open child either way:
    # `workboard._container_progress` returns no progress at all without both numbers,
    # and returns an empty open-children list when they're both 0 -- exactly
    # what an absent `children` entry already defaults to. Fetching its
    # detail list would cost a request `board` never needed.
    container_numbers = tuple(
        issue.number
        for issue in issues
        if issue.kind is body.ItemKind.CONTAINER and issue.children_total
    )
    # Open and recently-merged pull requests, the closed-item size batch
    # (one `item_references` round trip rather than the 32
    # serial single-item reads this used to pay before the pool ever
    # started), and each container's children are independent reads once
    # `since` is known, so fetching them on separate threads instead of one
    # after another overlaps their `gh` subprocess wait time. Children get
    # their own executor (`_fetch_children`) so their concurrency stays
    # capped at `BOARD_CHILD_FETCH_CONCURRENCY` even once these three base
    # reads finish and free their own pool's workers. The dependency wave
    # runs afterward instead (below), so it never overlaps them. The readers in
    # `github.py` fan out further inside each call, up to
    # `PARALLEL_FETCH_CONCURRENCY` workers.
    with ThreadPoolExecutor(max_workers=3) as pool:
        open_pull_requests = pool.submit(client.list_open_board_pull_requests)
        merged_pull_requests = pool.submit(client.list_recent_merged_board_pull_requests, since)
        closed_item_sizes_future = pool.submit(
            _closed_item_sizes,
            client,
            workboard.closed_item_numbers(
                history.lane_events, frozenset(issue.number for issue in issues)
            ),
            config.storage,
        )
        children = _fetch_children(client, container_numbers)
        open_pull_request_rows = open_pull_requests.result()
        merged_pull_request_rows = merged_pull_requests.result()
        closed_item_sizes = closed_item_sizes_future.result()
    # The same forge relation `cmd_cut._cut_target` refuses a nested container on,
    # so `next` never proposes a `cut` that `cut` refuses.
    nesting_parents = {
        number: parent.reference
        for number in workboard.childless_containers_with_uncut_rows(issues, config.storage)
        if (parent := client.parent_issue(number)) is not None
    }
    if landing is None:
        dependencies = validated_dependencies(
            issues,
            fetch_dependencies(
                client, tuple(issue.number for issue in issues if issue.blocked_by_count > 0)
            ),
        )
        trunk_ref = context.trunk_ref
    else:
        # A merged release already fetched and validated this exact
        # candidate set (`cmd_release._release_landing`'s own `list_board_dependencies`
        # wave) and judged its landing on its own trunk
        # ref, so neither is read a second time here.
        dependencies, trunk_ref = landing.dependencies, landing.trunk_ref
    trunk_landings = checkout.trunk_landings(
        trunk_ref, TRUNK_LANDING_DEPTH, directory=context.toplevel
    )
    # `trunk_landing_items` (sha and all) drives the Landungen view and
    # `Stage.CODE_LANDED`; `trunk_landings` below keeps only the timestamps,
    # also of commits that classify no work item.
    trunk_landing_items = tuple(
        workboard.TrunkLandingItem(number, landing.sha, landing.committed_at)
        for landing in trunk_landings
        if isinstance(landing.classification, workboard.TrunkWorkItemClassification)
        for number in landing.classification.numbers
    )
    return workboard.build_board(
        workboard.BoardBuildInputs(
            issues=issues,
            open_pull_requests=open_pull_request_rows,
            recent_merged_pull_requests=merged_pull_request_rows,
            claims=claims,
            config=config,
            repository=client.repository.path,
            now=now,
            trunk_landings=tuple(landing.committed_at for landing in trunk_landings),
            trunk_landing_items=trunk_landing_items,
            children=children,
            nesting_parents=nesting_parents,
            dependencies=dependencies,
            requests=client.requests,
            claim_ages=history.ages,
            lane_events=history.lane_events,
            unparsed_lifecycle_commits=history.unparsed_lifecycle_commits,
            closed_item_sizes=closed_item_sizes,
            open_pull_requests_supported=(
                client.capability(forge.ForgeOperation.LIST_OPEN_BOARD_PULL_REQUESTS)
                is not forge.Capability.UNSUPPORTED
            ),
        )
    )


def claim_ages(worktree: Path, state: protocol.ClaimState) -> dict[str, datetime]:
    """Each live claim's age in an already-fetched state -- one batched read
    of `state.tip`'s history (`store.claim_ages`), never a git
    call per claim.
    """
    if state.tip is None:
        return {}
    return store.claim_ages(worktree=worktree, tip=state.tip, claims=state.claims.values())


def _claim_lifecycle(worktree: Path, state: protocol.ClaimState) -> store.ClaimLifecycle:
    """Every claim's own ref-history lifecycle in an already-fetched state --
    one batched `store.claim_lifecycle` walk of `state.tip`'s
    history, mirroring `claim_ages`'s own no-refetch seam: a fresh fetch of
    `refs/aco/state` never happens twice for the one board build that
    already read it."""
    if state.tip is None:
        return store.ClaimLifecycle(events=(), unparsed=0)
    return store.claim_lifecycle(worktree=worktree, tip=state.tip)


def _claim_history(worktree: Path, state: protocol.ClaimState) -> ClaimHistory:
    """`build_board`'s own bundle of the two store history reads a full board
    build needs, from one already-fetched state -- `board`, `rulings`, and
    `next` all read this rather than `claim_ages` and `_claim_lifecycle`
    separately."""
    lifecycle = _claim_lifecycle(worktree, state)
    return ClaimHistory(
        ages=claim_ages(worktree, state),
        lane_events=lifecycle.events,
        unparsed_lifecycle_commits=lifecycle.unparsed,
    )


@dataclass(frozen=True)
class _ObservedBoard:
    """`observed_board`'s own result: the projected board, plus every live
    claim it was built from -- `next`'s own `parallel_set`
    needs each claim's scope for its occupied-paths accounting, and this is
    the one fetch that already read them, never a second store observation
    for the same run."""

    board: workboard.Board
    live_claims: tuple[protocol.ScopedClaim, ...]


@dataclass(frozen=True)
class _StoreAndIssues:
    """`_store_observation_and_issues`'s own result: the context's
    observation of the claim state and the open-issue list, read
    concurrently rather than one after the other -- neither
    reads the other's result. Under `github` both are round trips a board
    build pays; under `state-ref` the forge already holds the observation
    and the item files before the threads start, so neither
    thread pays a round trip."""

    observed: protocol.ClaimState
    issues: tuple[workboard.Issue, ...]


def _store_observation_and_issues(context: RunContext) -> _StoreAndIssues:
    """The claim-state fetch (`ls-remote` + `fetch`) and the open-issue list
    overlapped on separate threads: a board build that needs
    both -- every one that has not already been handed a pre-fetched
    `issues` tuple -- used to pay their wait times back to back. The forge
    is resolved first, on this thread, so its refusals keep their order and
    the context's facts are read once, before either thread asks for them;
    the state-ref board already reads the context's one observation there,
    which the observing thread then finds held."""
    client = context.forge
    with ThreadPoolExecutor(max_workers=2) as pool:
        observation = pool.submit(lambda: context.observation)
        issues = pool.submit(client.list_open_board_issues)
        return _StoreAndIssues(observation.result(), issues.result())


def observed_board(
    context: RunContext,
    *,
    issues: tuple[workboard.Issue, ...] | None = None,
) -> _ObservedBoard:
    """`board`/`rulings`/`next` share this: the store's live claims, projected
    onto forge board data (claims no longer come from the
    ledger; the forge is still the board's own data source)."""
    if issues is None:
        fetched = _store_observation_and_issues(context)
        observed, issues = fetched.observed, fetched.issues
    else:
        # A caller that already fetched `issues` itself (`rulings`) has
        # nothing left to overlap the state fetch with.
        observed = context.observation
    live_claims = tuple(observed.claims.values())
    projected = build_board(
        context,
        live_claims,
        issues=issues,
        history=_claim_history(context.toplevel, observed),
    )
    return _ObservedBoard(projected, live_claims)


def item_body_or_refuse(
    client: forge.ForgeReader, number: int, *, command: str, storage: body.Storage
) -> str:
    """The live body of issue `number`, or a by-name refusal before any
    write: `rule` and `ask` both target one existing issue, never a pull
    request -- a pull request exists only on a forge, so that refusal
    keeps the forge's own `#n`."""
    reference = client.item_reference(number)
    if reference.state is forge.ItemState.MISSING:
        raise protocol.ClaimUnavailableError(
            f"{workboard.item_label(number, storage)} does not exist"
        )
    if reference.is_landing:
        raise protocol.ClaimUnavailableError(
            f"#{number} is a pull request, not an issue; {command} needs an issue"
        )
    return reference.body or ""


def require_readable_item(client: forge.ForgeReader, issue: workboard.Issue | None) -> None:
    """Refuses a board row the state-ref store set aside as unreadable with
    the store's own refusal for that item (PIN-14, PIN-15), the one sentence a
    single-item read of it prints. A row on any other storage is never
    unreadable, so this does nothing there."""
    if issue is not None and issue.unreadable is not None:
        client.item_reference(issue.number)


def require_update_item_body(client: forge.ForgeWriter, *, command: str) -> None:
    if client.capability(forge.ForgeOperation.UPDATE_ITEM_BODY) is not forge.Capability.READ_WRITE:
        raise protocol.ClaimUnavailableError(
            f"this forge cannot update_item_body; {command} by hand"
        )
