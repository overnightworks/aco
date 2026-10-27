"""The `next` command (`specs/next.spec.md`)."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from . import board_read, body, checkout, expectations, policy, protocol, report, session, workboard


def _checkout_scope_is_wide(scope: tuple[str, ...], context: session.RunContext) -> bool:
    """Whether the width gate calls `scope` wide in `context`'s checkout,
    measured as `cmd_claim.scope_versioning` measures a claim there."""
    directories = checkout.scope_directories(
        scope, directory=context.directory, toplevel=lambda: context.toplevel
    )
    versioned = checkout.versioned_paths(directory=context.directory)
    return policy.wide_scope_trip(scope, versioned, directories=directories) is not None


def _ruling_pull_hint(item: workboard.BoardItem) -> str | None:
    if item.expectation_state is body.ExpectationState.PROPOSED:
        return "expectations unruled: refine before the pull"
    if not item.ruling_old:
        return None
    return f"ruled {item.ruling_landings} landings ago: refine again at the pull"


def _next_action_command(
    action: workboard.WorkItemAction | workboard.CutSliceAction,
    storage: body.Storage,
    *,
    site: _PullSite,
) -> str:
    """The exact `aco` invocation `_next` prints and `_next --json` carries
    as `command` -- one owner so text and JSON never name a different
    command for the same action. `close_container` has none: there is no
    command to run, and neither grammar invents one.

    A `workboard.WorkItemAction` is `claim` where `next` runs in a checkout `claim`
    accepts (`site.claims_in_place`), else `start` with the slug `start` itself
    derives from the title, so the advice runs as printed from
    the default branch's checkout too. Either drops `--scope` entirely for
    an item carrying its own top-level `scope`; an item whose one `[[slice]]` row names paths claims
    exactly those; only an item naming neither still prints the
    placeholder, alongside `_SCOPE_UNKNOWN_NOTE`. A scope the width gate
    calls wide in this checkout, with no `whole` in the body, adds
    `--whole <reason>`. All render through `workboard.advice_command`, so the line
    runs as printed.
    """
    if isinstance(action, workboard.CutSliceAction):
        return workboard.cut_command(action.container.number, storage)
    item = action.item
    pull = workboard.PullScope(item.scope, action.scope, item.whole, site.scope_is_wide)
    if site.claims_in_place:
        return workboard.work_item_claim_command(item.number, storage, pull)
    slug = _advised_slug(item.number, item.title, storage)
    return workboard.work_item_start_command(item.number, storage, slug, pull)


def _advised_slug(number: int, title: str, storage: body.Storage) -> str:
    """The slug `start` derives from `title`, else, for a title with no
    usable slug, the one item `number`'s own id yields -- a
    value `start --slug` accepts, so the advice runs as printed."""
    try:
        return checkout.slug_from_title(title)
    except protocol.ClaimError:
        return checkout.slug_from_title(workboard.item_argument(number, storage))


@dataclass(frozen=True)
class _PullSite:
    """What the checkout `next` runs in says about pulling its action:
    whether `claim` accepts it in place, and whether the width gate calls
    the action's scope wide there."""

    claims_in_place: bool
    scope_is_wide: bool


def _pull_site(action: workboard.NextAction | None, context: session.RunContext) -> _PullSite:
    scope = action.scope if isinstance(action, workboard.WorkItemAction) else None
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


class _NextReason(StrEnum):
    """`aco next`'s own `--json` `reason` vocabulary
    (`specs/next.spec.md`): the action type -- `work_item`, `cut_slice`,
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


def _next_action_reason(action: workboard.NextAction) -> _NextReason:
    if isinstance(action, workboard.WorkItemAction):
        return _NextReason.WORK_ITEM
    if isinstance(action, workboard.CutSliceAction):
        return _NextReason.CUT_SLICE
    if isinstance(action, workboard.CheckContainerAction):
        return _NextReason.CHECK_CONTAINER
    return _NextReason.CLOSE_CONTAINER


def _next_action_payload(
    action: workboard.NextAction, storage: body.Storage, *, site: _PullSite
) -> dict[str, object]:
    """The action-specific fields `_next_json` adds beyond `recovery`/`skipped`
    -- `_next_action_reason` now carries what an `"action"` key used to."""
    number = workboard.item_json_reference(workboard.next_action_item(action).number, storage)
    if isinstance(action, workboard.WorkItemAction):
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
    if isinstance(action, workboard.CutSliceAction):
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
        "next_step": (
            action.next_step if isinstance(action, workboard.CheckContainerAction) else None
        ),
    }


# The three sentences `next`'s own text form adds, each named
# once so text and JSON (`_parallel_json`) never restate them (Sonar S1192).
_SCOPE_UNKNOWN_NOTE = "scope unknown"
_PARALLEL_UNKNOWN_LINE = "parallel: unknown (first action names no scope)"
# "Text zeigt höchstens drei Kandidaten plus 'and N more'":
# a stable display cap, not something an operator tunes.
_PARALLEL_TEXT_LIMIT = 3


def _parallel_candidate_label(candidate: workboard.ParallelCandidate, storage: body.Storage) -> str:
    label = workboard.item_label(candidate.number, storage)
    count = len(candidate.scope)
    unit = "path" if count == 1 else "paths"
    return f"{label} ({count} {unit})"


def _parallel_line(parallel: workboard.ParallelSet, storage: body.Storage) -> str:
    """`next`'s own `parallel:` line: the unknown sentence when the first
    action itself names no scope, `none` when the walk placed nothing,
    otherwise every placed candidate capped at `_PARALLEL_TEXT_LIMIT` --
    reusing `protocol.named_with_overflow_count`, the one "and N more"
    owner, rather than a second overflow renderer here."""
    if parallel.first_scope_unknown:
        return _PARALLEL_UNKNOWN_LINE
    if not parallel.candidates:
        return "parallel: none"
    labels = tuple(
        _parallel_candidate_label(candidate, storage) for candidate in parallel.candidates
    )
    return f"parallel: {protocol.named_with_overflow_count(labels, limit=_PARALLEL_TEXT_LIMIT)}"


def _scope_unknown_line(parallel: workboard.ParallelSet, storage: body.Storage) -> str:
    if not parallel.scope_unknown:
        return "scope unknown: none"
    named = ", ".join(workboard.item_label(number, storage) for number in parallel.scope_unknown)
    return f"scope unknown: {named}"


def _close_line(close: tuple[int, ...], storage: body.Storage) -> str:
    if not close:
        return "close: none"
    return "close: " + ", ".join(workboard.item_label(number, storage) for number in close)


def _next_json_numbers(numbers: Iterable[int], storage: body.Storage) -> list[int | str]:
    return [workboard.item_json_reference(number, storage) for number in numbers]


def _parallel_json(parallel: workboard.ParallelSet, storage: body.Storage) -> dict[str, object]:
    return {
        "first_scope_unknown": parallel.first_scope_unknown,
        "candidates": [
            {
                "number": workboard.item_json_reference(candidate.number, storage),
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
    ceiling: the board's own first action (`None` when nothing
    qualifies), the unworkable rows `SKIPPED` names, the landed-but-open
    `RECOVERY` rows, the parallel-capacity projection, the zero-cost
    `close:` list, the items waiting on the operator, the items
    labelled as ideas, and whether `claim` accepts this checkout, which picks
    `claim` or `start` as the advice."""

    action: workboard.NextAction | None
    skipped: tuple[workboard.BoardItem, ...]
    recovery: tuple[workboard.BoardItem, ...]
    parallel: workboard.ParallelSet
    close: tuple[int, ...]
    waiting: tuple[int, ...]
    ideas: tuple[int, ...]
    with_head: tuple[tuple[int, tuple[int, ...]], ...]
    site: _PullSite


def _next_json(next_report: _NextReport, storage: body.Storage) -> None:
    reason = (
        _next_action_reason(next_report.action)
        if next_report.action is not None
        else _NextReason.NOTHING_ACTIONABLE
    )
    payload: dict[str, object] = {
        "recovery": [
            {
                "number": workboard.item_json_reference(recovery_item.number, storage),
                "title": recovery_item.title,
                "step": workboard.RECOVERY_STEP,
            }
            for recovery_item in next_report.recovery
        ],
        "skipped": [
            {
                "number": workboard.item_json_reference(skipped_item.number, storage),
                "reason": skipped_item.actionable_reason,
            }
            for skipped_item in next_report.skipped
        ],
        "parallel": _parallel_json(next_report.parallel, storage),
        "close": _next_json_numbers(next_report.close, storage),
        "waiting_on_operator": _next_json_numbers(next_report.waiting, storage),
        "ideas": _next_json_numbers(next_report.ideas, storage),
        "with_head": [
            {
                "number": workboard.item_json_reference(number, storage),
                "lines": list(line_indexes),
            }
            for number, line_indexes in next_report.with_head
        ],
    }
    if next_report.action is not None:
        payload.update(_next_action_payload(next_report.action, storage, site=next_report.site))
    report.emit_json(next_report.action is not None, reason, **payload)


def _next_action_lines(
    action: workboard.NextAction, storage: body.Storage, *, site: _PullSite
) -> list[str]:
    """The action-specific lines `_next` prints before `parallel:`/`close:`."""
    if isinstance(action, workboard.WorkItemAction):
        item = action.item
        label = workboard.item_label(item.number, storage)
        lines = [
            f"{label} score {item.score}: {protocol.terminal_text(item.title)}",
            f"Next: {protocol.terminal_text(str(item.next_step))}",
            f"Run: {_next_action_command(action, storage, site=site)}",
        ]
        if action.scope is None:
            lines.append(_SCOPE_UNKNOWN_NOTE)
        hint = _ruling_pull_hint(item)
        if hint is not None:
            lines.append(hint)
        return lines
    container_label = workboard.item_label(action.container.number, storage)
    if isinstance(action, workboard.CutSliceAction):
        return [
            f"cut_slice {container_label}: {protocol.terminal_text(action.next_step)}",
            f"Next: {_next_action_command(action, storage, site=site)}",
        ]
    if isinstance(action, workboard.CheckContainerAction):
        return [
            f"check_container {container_label}: {workboard.CHECK_DONE_WHEN}",
            f"Next: {protocol.terminal_text(action.next_step)}",
        ]
    progress = action.container_progress
    return [
        f"close_container {container_label}: "
        f"{progress.closed}/{progress.total} children closed, no Next work"
    ]


def _next(next_report: _NextReport, storage: body.Storage) -> None:
    """A landed-but-open item is named before anything new is pulled; the
    parallel set and the zero-cost `close:` list are named right after the
    first action, unconditionally -- regardless of that
    action's own rank, so a closable container or a recovery item never goes
    unmentioned merely because something else pulled ahead of it."""
    lines: list[str] = []
    if next_report.recovery:
        lines.append("RECOVERY")
        lines.extend(
            f"{workboard.item_label(recovery_item.number, storage)}: {workboard.RECOVERY_STEP}"
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
        named = ", ".join(workboard.item_label(number, storage) for number in next_report.waiting)
        lines.append(f"{workboard.WAITING_ON_OPERATOR}: {named}")
    if next_report.ideas:
        named = ", ".join(workboard.item_label(number, storage) for number in next_report.ideas)
        lines.append(f"ideas: {named}")
    if next_report.with_head:
        named = ", ".join(
            f"{workboard.item_label(number, storage)} line {index}"
            for number, line_indexes in next_report.with_head
            for index in line_indexes
        )
        lines.append(f"with head: {named}")
    if next_report.skipped:
        skipped_lines = (
            f"{workboard.item_label(skipped_item.number, storage)}: "
            f"{skipped_item.terminal_actionable_reason}"
            for skipped_item in next_report.skipped
        )
        lines.extend(("", "SKIPPED", *skipped_lines))
    print("\n".join(lines))


def _unworkable(projected: workboard.Board) -> tuple[workboard.BoardItem, ...]:
    return tuple(item for item in projected.items if not item.actionable)


def _next_action_container_number(action: workboard.NextAction | None) -> int | None:
    """The container `action` targets, when it targets one -- excluded from
    `SKIPPED` below since a container is always non-actionable itself."""
    if action is None or isinstance(action, workboard.WorkItemAction):
        return None
    return action.container.number


def _with_head(
    issues: Iterable[workboard.Issue], storage: body.Storage
) -> tuple[tuple[int, tuple[int, ...]], ...]:
    """Each open item with an option line sent back to its head, with that
    line's indexes, in board order."""
    named = (
        (issue.number, expectations.returned_line_indexes(issue.body, storage=storage))
        for issue in issues
    )
    return tuple((number, indexes) for number, indexes in named if indexes)


def run(parsed: argparse.Namespace, context: session.RunContext) -> int:
    as_json = parsed.json
    try:
        issues = context.forge.list_open_board_issues()
        observed = board_read.observed_board(context, issues=issues)
        storage = context.config.storage
        projected = observed.board
        action = workboard.next_action(projected)
        site = _pull_site(action, context)
    except session.RepoMeaninglessUnderStateRefError as error:
        return report.refuse(_NextReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_NextReason.UNAVAILABLE, error, as_json=as_json)
    close = workboard.zero_cost_closes(projected)
    waiting = workboard.waiting_on_operator(projected)
    ideas = workboard.ideas(projected)
    with_head = _with_head(issues, storage)
    already_named = {_next_action_container_number(action), *close, *waiting, *ideas}
    skipped = tuple(item for item in _unworkable(projected) if item.number not in already_named)
    next_report = _NextReport(
        action=action,
        skipped=skipped,
        recovery=projected.recovery,
        parallel=workboard.parallel_set(projected, observed.live_claims, action),
        close=close,
        waiting=waiting,
        ideas=ideas,
        with_head=with_head,
        site=site,
    )
    if as_json:
        _next_json(next_report, storage)
    else:
        _next(next_report, storage)
    return 0 if action is not None else 3
