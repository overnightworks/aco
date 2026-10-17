"""The `next` command (`specs/next.spec.md`)."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from . import board, board_read, body, checkout, policy, protocol, report, session


def _checkout_scope_is_wide(scope: tuple[str, ...], context: session.RunContext) -> bool:
    """Whether the width gate calls `scope` wide in `context`'s checkout,
    measured as `cmd_claim.scope_versioning` measures a claim there."""
    directories = checkout.scope_directories(
        scope, directory=context.directory, toplevel=lambda: context.toplevel
    )
    versioned = checkout.versioned_paths(directory=context.directory)
    return policy.wide_scope_trip(scope, versioned, directories=directories) is not None


def _ruling_pull_hint(item: board.BoardItem) -> str | None:
    if item.expectation_state is body.ExpectationState.PROPOSED:
        return "expectations unruled: refine before the pull"
    if not item.ruling_old:
        return None
    return f"ruled {item.ruling_landings} landings ago: refine again at the pull"


def _next_action_command(
    action: board.WorkItemAction | board.CutSliceAction,
    storage: body.Storage,
    *,
    site: _PullSite,
) -> str:
    """The exact `aco` invocation `_next` prints and `_next --json` carries
    as `command` -- one owner so text and JSON never name a different
    command for the same action. `close_container` has none: there is no
    command to run, and neither grammar invents one.

    A `board.WorkItemAction` is `claim` where `next` runs in a checkout `claim`
    accepts (`site.claims_in_place`), else `start` with the slug `start` itself
    derives from the title (issue #562), so the advice runs as printed from
    the default branch's checkout too. Either drops `--scope` entirely for
    an item carrying its own top-level `scope` (issue #348, #337's own
    derivation); an item whose one `[[slice]]` row names paths claims
    exactly those; only an item naming neither still prints the
    placeholder, alongside `SCOPE_UNKNOWN_NOTE`. A scope the width gate
    calls wide in this checkout, with no `whole` in the body, adds
    `--whole <reason>` (issue #566). All render through `board.advice_command`, so the line runs as
    printed (issue #510).
    """
    if isinstance(action, board.CutSliceAction):
        return board.cut_command(action.container.number, storage)
    item = action.item
    pull = board.PullScope(item.scope, action.scope, item.whole, site.scope_is_wide)
    if site.claims_in_place:
        return board.work_item_claim_command(item.number, storage, pull)
    slug = _advised_slug(item.number, item.title, storage)
    return board.work_item_start_command(item.number, storage, slug, pull)


def _advised_slug(number: int, title: str, storage: body.Storage) -> str:
    """The slug `start` derives from `title`, else, for a title with no
    usable slug (issue #566), the one item `number`'s own id yields -- a
    value `start --slug` accepts, so the advice runs as printed."""
    try:
        return checkout.slug_from_title(title)
    except protocol.ClaimError:
        return checkout.slug_from_title(board.item_argument(number, storage))


@dataclass(frozen=True)
class _PullSite:
    """What the checkout `next` runs in says about pulling its action:
    whether `claim` accepts it in place, and whether the width gate calls
    the action's scope wide there (issue #566)."""

    claims_in_place: bool
    scope_is_wide: bool


def _pull_site(action: board.NextAction | None, context: session.RunContext) -> _PullSite:
    scope = action.scope if isinstance(action, board.WorkItemAction) else None
    return _PullSite(
        claims_in_place=_claims_in_place(context),
        scope_is_wide=scope is not None and _checkout_scope_is_wide(scope, context),
    )


def _claims_in_place(context: session.RunContext) -> bool:
    """Whether `claim` accepts a build claim in this run's checkout: a
    linked worktree on an attached branch other than the default one, the
    isolation `claim` itself requires (cli.CLAIM_DESCRIPTION)."""
    here = checkout.resolve_path_checkout(context.toplevel)
    return (
        here is not None
        and here.kind is checkout.CheckoutKind.LINKED_WORKTREE
        and not checkout.is_detached_head(here.branch)
        and not checkout.is_default_branch(here.branch, context.recorded_default_branch)
    )


class NextReason(StrEnum):
    """`aco next`'s own `--json` `reason` vocabulary (issue #412,
    `specs/next.spec.md`): the action type -- `work_item`, `cut_slice`,
    `check_container`, `close_container` -- names a success (`ok: true`) exactly as it did
    when carried under the dropped `"action"` key; `nothing_actionable`
    is the one `ok: false` outcome that exits `3` in text (NEXT-01) and
    under `--json` alike, the sole reason exit `3` is ever used.
    `invalid_usage` covers `--repo` under `storage = state-ref`
    (PIN-04); every other refusal -- an unsupported forge host (BOARD-02),
    a state-ref checkout with no resolvable default branch (PIN-05) --
    falls to `unavailable`, matching `ask`/`rule`/`brief`'s own catch-all."""

    WORK_ITEM = "work_item"
    CUT_SLICE = "cut_slice"
    CHECK_CONTAINER = "check_container"
    CLOSE_CONTAINER = "close_container"
    NOTHING_ACTIONABLE = "nothing_actionable"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


def _next_action_reason(action: board.NextAction) -> NextReason:
    if isinstance(action, board.WorkItemAction):
        return NextReason.WORK_ITEM
    if isinstance(action, board.CutSliceAction):
        return NextReason.CUT_SLICE
    if isinstance(action, board.CheckContainerAction):
        return NextReason.CHECK_CONTAINER
    return NextReason.CLOSE_CONTAINER


def _next_action_payload(
    action: board.NextAction, storage: body.Storage, *, site: _PullSite
) -> dict[str, object]:
    """The action-specific fields `_next_json` adds beyond `recovery`/`skipped`
    -- `_next_action_reason` now carries what an `"action"` key used to."""
    number = board.item_json_reference(board.next_action_item(action).number, storage)
    if isinstance(action, board.WorkItemAction):
        item = action.item
        payload: dict[str, object] = {
            "number": number,
            "score": item.score,
            "title": item.title,
            "next": item.next_step,
            "command": _next_action_command(action, storage, site=site),
            "ruling_landings": item.ruling_landings,
            "ruling_old": item.ruling_old,
        }
        hint = _ruling_pull_hint(item)
        if hint is not None:
            payload["ruling_hint"] = hint
        return payload
    if isinstance(action, board.CutSliceAction):
        return {
            "number": number,
            "title": action.container.title,
            "slice": action.next_step,
            "cut_title": action.cut_title,
            "command": _next_action_command(action, storage, site=site),
        }
    return {
        "number": number,
        "closed": action.container_progress.closed,
        "total": action.container_progress.total,
        "next_step": (action.next_step if isinstance(action, board.CheckContainerAction) else None),
    }


# The three sentences issue #348 adds to `next`'s own text form, each named
# once so text and JSON (`_parallel_json`) never restate them (Sonar S1192).
SCOPE_UNKNOWN_NOTE = "scope unknown"
PARALLEL_UNKNOWN_LINE = "parallel: unknown (first action names no scope)"
# "Text zeigt höchstens drei Kandidaten plus 'and N more'" (issue #348 Form):
# a stable display cap, not something an operator tunes.
PARALLEL_TEXT_LIMIT = 3


def _parallel_candidate_label(candidate: board.ParallelCandidate, storage: body.Storage) -> str:
    label = board.item_label(candidate.number, storage)
    count = len(candidate.scope)
    unit = "path" if count == 1 else "paths"
    return f"{label} ({count} {unit})"


def _parallel_line(parallel: board.ParallelSet, storage: body.Storage) -> str:
    """`next`'s own `parallel:` line: the unknown sentence when the first
    action itself names no scope, `none` when the walk placed nothing,
    otherwise every placed candidate capped at `PARALLEL_TEXT_LIMIT` --
    reusing `protocol.named_with_overflow_count`, the one "and N more"
    owner, rather than a second overflow renderer here."""
    if parallel.first_scope_unknown:
        return PARALLEL_UNKNOWN_LINE
    if not parallel.candidates:
        return "parallel: none"
    labels = tuple(
        _parallel_candidate_label(candidate, storage) for candidate in parallel.candidates
    )
    return f"parallel: {protocol.named_with_overflow_count(labels, limit=PARALLEL_TEXT_LIMIT)}"


def _scope_unknown_line(parallel: board.ParallelSet, storage: body.Storage) -> str:
    if not parallel.scope_unknown:
        return "scope unknown: none"
    named = ", ".join(board.item_label(number, storage) for number in parallel.scope_unknown)
    return f"scope unknown: {named}"


def _close_line(close: tuple[int, ...], storage: body.Storage) -> str:
    if not close:
        return "close: none"
    return "close: " + ", ".join(board.item_label(number, storage) for number in close)


def _next_json_numbers(numbers: Iterable[int], storage: body.Storage) -> list[int | str]:
    return [board.item_json_reference(number, storage) for number in numbers]


def _parallel_json(parallel: board.ParallelSet, storage: body.Storage) -> dict[str, object]:
    return {
        "first_scope_unknown": parallel.first_scope_unknown,
        "candidates": [
            {
                "number": board.item_json_reference(candidate.number, storage),
                "scope": list(candidate.scope),
            }
            for candidate in parallel.candidates
        ],
        "scope_unknown": _next_json_numbers(parallel.scope_unknown, storage),
    }


@dataclass(frozen=True)
class _NextReport:
    """Everything `_next`/`_next_json` print for one `next` run, bundled so
    each printer takes one argument instead of PLR0913's five-scalar
    ceiling (issue #348): the board's own first action (`None` when nothing
    qualifies), the unworkable rows `SKIPPED` names, the landed-but-open
    `RECOVERY` rows, the parallel-capacity projection, the zero-cost
    `close:` list, the items waiting on the operator (issue #553), and
    whether `claim` accepts this checkout, which picks `claim` or `start`
    as the advice (issue #562)."""

    action: board.NextAction | None
    skipped: tuple[board.BoardItem, ...]
    recovery: tuple[board.BoardItem, ...]
    parallel: board.ParallelSet
    close: tuple[int, ...]
    waiting: tuple[int, ...]
    site: _PullSite


def _next_json(next_report: _NextReport, storage: body.Storage) -> None:
    reason = (
        _next_action_reason(next_report.action)
        if next_report.action is not None
        else NextReason.NOTHING_ACTIONABLE
    )
    payload: dict[str, object] = {
        "recovery": [
            {
                "number": board.item_json_reference(recovery_item.number, storage),
                "title": recovery_item.title,
                "step": board.RECOVERY_STEP,
            }
            for recovery_item in next_report.recovery
        ],
        "skipped": [
            {
                "number": board.item_json_reference(skipped_item.number, storage),
                "reason": skipped_item.actionable_reason,
            }
            for skipped_item in next_report.skipped
        ],
        "parallel": _parallel_json(next_report.parallel, storage),
        "close": _next_json_numbers(next_report.close, storage),
        "waiting_on_operator": _next_json_numbers(next_report.waiting, storage),
    }
    if next_report.action is not None:
        payload.update(_next_action_payload(next_report.action, storage, site=next_report.site))
    report.emit_json(next_report.action is not None, reason, **payload)


def _next_action_lines(
    action: board.NextAction, storage: body.Storage, *, site: _PullSite
) -> list[str]:
    """The action-specific lines `_next` prints before `parallel:`/`close:`."""
    if isinstance(action, board.WorkItemAction):
        item = action.item
        label = board.item_label(item.number, storage)
        lines = [
            f"{label} score {item.score}: {board.terminal_text(item.title)}",
            f"Next: {board.terminal_text(str(item.next_step))}",
            f"Run: {_next_action_command(action, storage, site=site)}",
        ]
        if action.scope is None:
            lines.append(SCOPE_UNKNOWN_NOTE)
        hint = _ruling_pull_hint(item)
        if hint is not None:
            lines.append(hint)
        return lines
    container_label = board.item_label(action.container.number, storage)
    if isinstance(action, board.CutSliceAction):
        return [
            f"cut_slice {container_label}: {board.terminal_text(action.next_step)}",
            f"Next: {_next_action_command(action, storage, site=site)}",
        ]
    if isinstance(action, board.CheckContainerAction):
        return [
            f"check_container {container_label}: {board.CHECK_DONE_WHEN}",
            f"Next: {board.terminal_text(action.next_step)}",
        ]
    progress = action.container_progress
    return [
        f"close_container {container_label}: "
        f"{progress.closed}/{progress.total} children closed, no Next work"
    ]


def _next(next_report: _NextReport, storage: body.Storage) -> None:
    """A landed-but-open item is named before anything new is pulled; the
    parallel set and the zero-cost `close:` list are named right after the
    first action, unconditionally (issue #348) -- regardless of that
    action's own rank, so a closable container or a recovery item never goes
    unmentioned merely because something else pulled ahead of it."""
    lines: list[str] = []
    if next_report.recovery:
        lines.append("RECOVERY")
        lines.extend(
            f"{board.item_label(recovery_item.number, storage)}: {board.RECOVERY_STEP}"
            for recovery_item in next_report.recovery
        )
        lines.append("")
    lines.extend(
        _next_action_lines(next_report.action, storage, site=next_report.site)
        if next_report.action is not None
        else ["No actionable item."]
    )
    lines.append(_parallel_line(next_report.parallel, storage))
    if not next_report.parallel.first_scope_unknown:
        lines.append(_scope_unknown_line(next_report.parallel, storage))
    lines.append(_close_line(next_report.close, storage))
    if next_report.waiting:
        named = ", ".join(board.item_label(number, storage) for number in next_report.waiting)
        lines.append(f"{board.WAITING_ON_OPERATOR}: {named}")
    if next_report.skipped:
        skipped_lines = (
            f"{board.item_label(skipped_item.number, storage)}: "
            f"{skipped_item.terminal_actionable_reason}"
            for skipped_item in next_report.skipped
        )
        lines.extend(("", "SKIPPED", *skipped_lines))
    print("\n".join(lines))


def _unworkable(projected: board.Board) -> tuple[board.BoardItem, ...]:
    return tuple(item for item in projected.items if not item.actionable)


def _next_action_container_number(action: board.NextAction | None) -> int | None:
    """The container `action` targets, when it targets one -- excluded from
    `SKIPPED` below since a container is always non-actionable itself."""
    if action is None or isinstance(action, board.WorkItemAction):
        return None
    return action.container.number


def run(parsed: argparse.Namespace, context: session.RunContext) -> int:
    as_json = parsed.json
    try:
        observed = board_read.observed_board(context)
        storage = context.config.storage
        projected = observed.board
        action = board.next_action(projected)
        site = _pull_site(action, context)
    except session.RepoMeaninglessUnderStateRefError as error:
        return report.refuse(NextReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(NextReason.UNAVAILABLE, error, as_json=as_json)
    close = board.zero_cost_closes(projected)
    waiting = board.waiting_on_operator(projected)
    already_named = {_next_action_container_number(action), *close, *waiting}
    skipped = tuple(item for item in _unworkable(projected) if item.number not in already_named)
    next_report = _NextReport(
        action=action,
        skipped=skipped,
        recovery=projected.recovery,
        parallel=board.parallel_set(projected, observed.live_claims, action),
        close=close,
        waiting=waiting,
        site=site,
    )
    if as_json:
        _next_json(next_report, storage)
    else:
        _next(next_report, storage)
    return 0 if action is not None else 3
