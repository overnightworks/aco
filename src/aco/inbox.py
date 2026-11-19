"""The decisions waiting on the operator.

The per-repository read: the rows `aco rulings` prints, on the items a member
of the repository wrote and no other. In a public repository a stranger can
open an item that carries a card, and a card reaches the operator's decision
surface only from a writer of the repository.

The steps only the operator can take come from the same items: those a member
wrote whose block's `wait` names the operator, each with that wait's text. The
fleet-wide plans are those a member wrote that carry the `fleet-plan` label.

The read across repositories: of those rows, the option lines still waiting on
the operator, the steps and the plans, for every repository discovery found.
"""

import os
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from . import (
    board_read,
    body,
    checkout,
    expectations,
    forge,
    item_step,
    item_wait,
    lane_measure,
    lane_record,
    progress,
    protocol,
    repositories,
    rulings,
    session,
    store,
    workboard,
)
from .progress import Progress, ProgressUnavailable


def rows(issues: Iterable[workboard.Issue], *, storage: body.Storage) -> tuple[rulings.Row, ...]:
    """`rulings.rows` over the members' items among `issues`."""
    members = (issue for issue in issues if issue.author_is_member)
    return rulings.rows(members, storage=storage)


def waiting_rows(rows_read: Iterable[rulings.Row]) -> tuple[rulings.Row, ...]:
    """Of `rows_read`, each item that still has a line waiting on the operator,
    reduced to those lines: an option line neither ruled, nor returned to its
    head, nor withdrawn. A returned line is with its head."""
    waiting: list[rulings.Row] = []
    for row in rows_read:
        lines = tuple(
            line for line in row.lines if expectations.is_open(line) and line.returned is None
        )
        if lines:
            waiting.append(replace(row, lines=lines))
    return tuple(waiting)


@dataclass(frozen=True)
class Step:
    number: int
    title: str
    wait_text: str
    """The text of the item's operator `wait`."""
    card: item_step.StepCard | None = None
    """The block's `step` table; `None` for a step marked without one."""


def step_in(number: int, title: str, item_body: str, *, storage: body.Storage) -> Step | None:
    """The step an item's body asks the operator for: `None` unless its `wait` names
    the operator. The one reader of a step, for the listing and for the board's
    answer to it, whose fingerprints must match."""
    wait = body.parse_body(item_body, storage=storage).wait
    if not item_wait.waits_on_operator(wait):
        return None
    card = item_step.parse_step(body.locate_block(item_body).data)
    return Step(number, title, wait.step, card)


def steps(issues: Iterable[workboard.Issue], *, storage: body.Storage) -> tuple[Step, ...]:
    """The members' readable items among `issues` whose `wait` names the
    operator, by descending number."""
    found = [
        step
        for issue in issues
        if issue.author_is_member and issue.unreadable is None
        if (step := step_in(issue.number, issue.title, issue.body, storage=storage)) is not None
    ]
    return tuple(sorted(found, key=lambda step: -step.number))


@dataclass(frozen=True)
class Plan:
    number: int
    title: str
    url: str | None
    """The item's page; `None` under `storage = "state-ref"`, whose items are no
    forge pages."""
    updated_on: str
    """The day the item last changed, `YYYY-MM-DD`."""


_DAY_LENGTH = len("YYYY-MM-DD")


def plans(
    issues: Iterable[workboard.Issue], *, repository: forge.RepositoryId, storage: body.Storage
) -> tuple[Plan, ...]:
    """The members' readable items among `issues` that carry the `fleet-plan`
    label, by ascending number."""
    found = [
        Plan(
            issue.number,
            issue.title,
            None
            if storage is body.Storage.STATE_REF
            else f"https://{repository.host}/{repository.path}/issues/{issue.number}",
            issue.updated_at[:_DAY_LENGTH],
        )
        for issue in issues
        if issue.author_is_member
        and issue.unreadable is None
        and workboard.has_label(issue.labels, workboard.FLEET_PLAN_LABEL)
    ]
    return tuple(sorted(found, key=lambda plan: plan.number))


@dataclass(frozen=True)
class Reading:
    """What one listing of a repository's open items holds for the operator."""

    rows: tuple[rulings.Row, ...]
    steps: tuple[Step, ...]
    plans: tuple[Plan, ...] = ()
    progress: Progress | ProgressUnavailable | None = None
    """The repository's progress view; `None` unless the read asked for it."""


def read_issues(
    issues: Iterable[workboard.Issue],
    *,
    storage: body.Storage,
    plans: tuple[Plan, ...] = (),
) -> Reading:
    """The rows and the steps among `issues`, which are listed once, with `plans`."""
    listed = tuple(issues)
    return Reading(rows(listed, storage=storage), steps(listed, storage=storage), plans)


def read_context(context: session.RunContext, *, with_progress: bool = False) -> Reading:
    """The rows, the steps and the plans of the checkout `context` is bound to,
    from one listing of its open items; with `with_progress`, also the progress
    view, which reads each container's parent and sub-issues, the trunk's trailers and the
    state ref's lane records."""
    listed = tuple(context.forge.list_open_board_issues())
    storage = context.config.storage
    reading = read_issues(
        listed,
        storage=storage,
        plans=plans(listed, repository=context.forge.repository, storage=storage),
    )
    if not with_progress:
        return reading
    return Reading(
        reading.rows,
        reading.steps,
        reading.plans,
        _progress(context, listed, reading.steps),
    )


def _progress(
    context: session.RunContext,
    listed: tuple[workboard.Issue, ...],
    operator_steps: tuple[Step, ...],
) -> Progress | ProgressUnavailable:
    """The progress view of `listed`, whose landed items the trunk's trailers
    name; a failed trunk read leaves it unknown."""
    try:
        landings = checkout.trunk_landings(
            context.trunk_ref, board_read.TRUNK_LANDING_DEPTH, directory=context.toplevel
        )
    except protocol.ClaimError as error:
        return ProgressUnavailable(str(error))
    lanes = _recorded_lanes(context)
    return progress.of(
        listed,
        storage=context.config.storage,
        marks=progress.Marks(
            frozenset(step.number for step in operator_steps),
            frozenset(item.item for item in board_read.trunk_landing_items(landings)),
            None if lanes is None else lane_measure.lane_prices(lanes),
            None if lanes is None else lane_measure.item_actuals(lanes),
        ),
        parent_of=context.forge.parent_issue,
        children_of=context.forge.list_children,
    )


def _recorded_lanes(context: session.RunContext) -> tuple[lane_record.RecordedLane, ...] | None:
    """The lane records on the state ref's tip; `None` when the ref cannot be read, which
    leaves only the work-left ranges and the closed children's actuals unknown."""
    try:
        observed = store.peek_state(
            worktree=context.toplevel, remote=context.configured_canonical_remote
        )
        return lane_record.recorded_lanes(context.toplevel, observed.tip)
    except protocol.ClaimError:
        return None


def read_repository(repository: repositories.Repository) -> Reading:
    """`read_context` of the checkout `repository` names."""
    # Looked up on the module at every call, so a replaced `run_context` (the
    # board's test forge) reaches every read.
    return read_context(session.run_context(None).for_directory(repository.directory))


type IssueReader = Callable[[repositories.Repository], Reading]
"""One repository's `Reading`; raises `protocol.ClaimError` or `OSError` when
that repository cannot be read."""


@dataclass(frozen=True)
class Waiting:
    repository: str
    rows: tuple[rulings.Row, ...]
    steps: tuple[Step, ...]
    plans: tuple[Plan, ...]


@dataclass(frozen=True)
class Unavailable:
    repository: str
    reason: str


@dataclass(frozen=True)
class Inbox:
    root: Path
    entries: tuple[Waiting | Unavailable, ...]
    """One per discovered repository, in discovery's order."""
    unreadable: tuple[repositories.UnavailableCheckout, ...]


def no_repository_read(root: Path, reasons: Iterable[str]) -> str:
    """The refusal sentence for a root none of whose repositories could be read."""
    return f"no repository could be read under {root} ({'; '.join(reasons)})"


def discovered() -> repositories.Discovery:
    """One fresh scan of the configured root; refused, naming the file or the
    root, when there is no repository to read."""
    root = repositories.configured_root(repositories.config_path(os.environ, Path.home()))
    discovery = repositories.discover(root)
    if not discovery.repositories:
        raise protocol.ClaimError(
            no_repository_read(
                root, (f"{entry.directory}: {entry.reason}" for entry in discovery.unavailable)
            )
        )
    return discovery


class RepositoryNotFoundError(protocol.ClaimError):
    """No repository the scan found carries the label."""

    def __init__(self, label: str) -> None:
        super().__init__(f"no repository {label} found")


class UnreadableRepositoryError(protocol.ClaimError):
    """The checkout of the repository exists but could not be read."""

    def __init__(self, label: str, checkout: repositories.UnavailableCheckout) -> None:
        super().__init__(
            f"repository {label} is unreadable: {checkout.directory}: {checkout.reason}"
        )


def context_in_checkout_of(discovery: repositories.Discovery, label: str) -> session.RunContext:
    """The run context in the checkout of the repository `label` of `discovery`,
    with no `--repo` of its own, so the checkout's own remote is the target;
    refused when `discovery` has no repository of that label, naming the
    checkout and its defect when one that could not be read carries it."""
    found = {repository.label: repository for repository in discovery.repositories}
    if label not in found:
        for unreadable in discovery.unavailable:
            if unreadable.label == label:
                raise UnreadableRepositoryError(label, unreadable)
        raise RepositoryNotFoundError(label)
    return session.run_context(None).for_directory(found[label].directory)


def read(discovery: repositories.Discovery, read_issues_of: IssueReader) -> Inbox:
    """What waits on the operator in every repository of `discovery`, the
    repositories read concurrently; one that cannot be read is listed as
    unavailable and the others are still read."""

    def read_one(repository: repositories.Repository) -> Waiting | Unavailable:
        try:
            reading = read_issues_of(repository)
            return Waiting(
                repository.label, waiting_rows(reading.rows), reading.steps, reading.plans
            )
        except (protocol.ClaimError, OSError) as error:
            return Unavailable(repository.label, str(error))

    with ThreadPoolExecutor(max_workers=max(1, len(discovery.repositories))) as pool:
        entries = tuple(pool.map(read_one, discovery.repositories))
    return Inbox(discovery.root, entries, discovery.unavailable)


def step_json(step: Step) -> dict[str, object]:
    card = step.card
    return {
        "number": step.number,
        "title": step.title,
        "step": step.wait_text,
        item_step.PURPOSE_KEY: card and card.purpose,
        item_step.ACTIONS_KEY: card and card.actions,
        item_step.EXPECTED_KEY: card and card.expected,
        item_step.ANSWER_KEY: card and card.answer,
    }


def inbox_json(inbox: Inbox) -> dict[str, object]:
    """The inbox as JSON: items and lines in the shapes `aco rulings --json`
    prints, and the steps."""
    return {
        "root": str(inbox.root),
        "repositories": [
            {"repository": entry.repository, "unavailable": entry.reason}
            if isinstance(entry, Unavailable)
            else {
                "repository": entry.repository,
                "items": [rulings.row_json(row) for row in entry.rows],
                "steps": [step_json(step) for step in entry.steps],
            }
            for entry in inbox.entries
        ],
        "unreadable": [
            {"directory": str(checkout.directory), "reason": checkout.reason}
            for checkout in inbox.unreadable
        ],
    }
