"""The `cut` command (`specs/cut.spec.md`)."""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from . import board_read, body, forge, protocol, report, workboard
from .session import RunContext

_CONTAINER_KINDS = frozenset({body.ItemKind.CONTAINER})


def open_container(
    open_issues: Iterable[workboard.Issue],
    number: int,
    storage: body.Storage,
    accepted_kinds: frozenset[body.ItemKind] = _CONTAINER_KINDS,
) -> workboard.Issue:
    """`number`'s open issue when its type is one of `accepted_kinds` --
    `cut`'s own target and `item new --parent` (issue #444) -- or why it is
    not."""
    target = next((issue for issue in open_issues if issue.number == number), None)
    if target is None:
        raise protocol.ClaimUnavailableError(
            f"{workboard.item_label(number, storage)} is not an open container"
        )
    if target.kind not in accepted_kinds:
        raise protocol.ClaimUnavailableError(
            f"{workboard.item_label(number, storage)} is not a container"
        )
    return target


def _cut_target(
    client: forge.ForgeWriter,
    open_issues: Iterable[workboard.Issue],
    number: int,
    storage: body.Storage,
) -> workboard.Issue:
    """The open container `cut` targets, or why it refuses before any write."""
    open_issues = tuple(open_issues)
    board_read.require_readable_item(
        client, next((issue for issue in open_issues if issue.number == number), None)
    )
    target = open_container(open_issues, number, storage)
    parent = client.parent_issue(number)
    if parent is not None:
        parent_label = workboard.relation_label(parent.reference, storage)
        raise protocol.ClaimUnavailableError(
            f"{workboard.item_label(number, storage)} is itself a child of {parent_label}; "
            "nested containers are not supported"
        )
    return target


@dataclass(frozen=True)
class _SliceRowRemoval:
    """`container`'s rewritten body, the cut row removed by `body.remove_slice_row` from its
    `aco` block, and `step`, the words naming that write."""

    container: int
    new_body: str
    step: str


def _link_created_child(
    client: forge.ForgeWriter, removal: _SliceRowRemoval, child: int, storage: body.Storage
) -> None:
    """Write `removal.new_body` back to `removal.container`.

    Not atomic with `create_child` -- GitHub has no transaction across the
    two writes. A failure here still leaves the created child behind, so it
    raises the same `forge.ForgePartialChildCreationError` a failed relation
    write inside `create_child` itself would -- one type, so `run`
    renders one recovery message for either, `step` naming what an
    identical re-run finishes.
    """
    try:
        client.update_item_body(removal.container, removal.new_body)
    except protocol.ClaimError as error:
        raise forge.ForgePartialChildCreationError(
            child=child,
            parent=removal.container,
            step=removal.step,
            cause=error,
            storage=storage,
        ) from error


class _CutReason(StrEnum):
    """`aco cut`'s own `--json` `reason` vocabulary (issue #425,
    `specs/cut.spec.md`): `cut`/`adopted` mirror the text form's own
    `CUT`/`ADOPTED` verb -- whether `child` was freshly created or an
    already-open child GitHub already recorded (#260). Every refusal
    before any write is `precondition_failed`; a write that created the
    child but failed to finish recording it
    (`forge.ForgePartialChildCreationError`) is `partial_write` instead,
    carrying `written`/`failed` as structured siblings rather than only
    the prose sentence stderr already printed."""

    CUT = "cut"
    ADOPTED = "adopted"
    PRECONDITION_FAILED = "precondition_failed"
    PARTIAL_WRITE = "partial_write"


@dataclass(frozen=True)
class _CutOutcome:
    """What one `cut` did: the container, the row it linked (if any), the
    child it created or adopted, and whether it adopted."""

    container: int
    row_index: int | None
    child: int
    adopted: bool


def _print_cut_result(outcome: _CutOutcome, storage: body.Storage, *, as_json: bool) -> None:
    """Print `cut`'s result: the text form's `CUT`/`ADOPTED` verb becomes
    `--json`'s own `reason` (issue #425) -- `adopted` no longer needs its
    own boolean sibling once the envelope's `reason` already names it."""
    if as_json:
        report.emit_json(
            True,
            _CutReason.ADOPTED if outcome.adopted else _CutReason.CUT,
            container=outcome.container,
            row=outcome.row_index,
            child=outcome.child,
        )
        return
    suffix = "" if outcome.row_index is None else f" row {outcome.row_index}"
    verb = "ADOPTED" if outcome.adopted else "CUT"
    container_label = workboard.item_label(outcome.container, storage)
    print(f"{verb} {container_label}{suffix} -> {workboard.item_label(outcome.child, storage)}")


class PartialWriteError(protocol.ClaimError):
    """Wraps `forge.ForgePartialCreationError` so `cut` and `item new`
    can choose `partial_write`'s own structured `--json` shape (`written`,
    `failed`) without parsing the wrapped error's prose (mirrors `ask`/
    `rule`'s own `cmd_rule.TargetUnavailableError`/`cmd_rule.InvalidTargetError`, issue
    #396); `recovery` is the caller's own way to finish the write."""

    def __init__(self, error: forge.ForgePartialCreationError, *, recovery: str) -> None:
        self.written = error.created
        self.failed = error.step
        super().__init__(f"{error}; {recovery}")


def requested_body_scope(raw: list[str] | None) -> tuple[str, ...] | None:
    """A repeated `--scope` flag's canonical value, or `None` when it was
    never given -- `item new` and `cut` (issue #337) both take an optional
    `--scope`, so this is the one place either turns the raw flag list into
    the same canonical form `protocol.valid_scope` produces for `claim`."""
    return None if raw is None else protocol.valid_scope(raw)


# Fixed text naming no child number (issue #606 line 2), so the child is
# written once, in the same create call that mints its number.
_CUT_CHILD_NEXT = f"Build this slice; claim it with {workboard.advice_command('start')}."


def _cut_child_body(
    container: int,
    storage: body.Storage,
    scope: tuple[str, ...] | None = None,
    done_when: str | None = None,
) -> str:
    """The body `cut` writes for a fresh child: `body.parent_line` above a fresh
    block whose `now` names the container it was cut from, whose `next` is
    `_CUT_CHILD_NEXT`, and whose `done_when` is the linked row's own (issue
    #606), plus the cut slice's own top-level `scope = [...]` (issue #337)
    when the cut carries one -- the linked row's own scope, or a filled
    `--scope`. With no row `done_when` to take -- the row carries none, or
    the cut is untied -- that key stays empty, never a refusal. A repeat
    `cut` after a partial failure reads the parent line back
    (`body.names_parent`) to tell `container`'s own orphan apart from
    an unrelated open issue that merely shares the row's title (#260)."""
    fields: dict[str, object] = {
        "now": f"Cut from {workboard.item_label(container, storage)}",
        "next": _CUT_CHILD_NEXT,
    }
    if done_when is not None:
        fields["done_when"] = done_when
    if scope is not None:
        fields["scope"] = list(scope)
    return body.prose_above_fresh_block(
        body.parent_line(workboard.item_label(container, storage)), fields
    )


def _adopt_existing_child(
    client: forge.ForgeWriter,
    container: int,
    title: str,
    config: workboard.BoardConfig,
    open_issues: Iterable[workboard.Issue],
) -> workboard.ChildItem | None:
    """`container`'s already-open child titled exactly `title`, so a repeat
    `cut` after a partial failure (`forge.ForgePartialChildCreationError`)
    adopts the child GitHub already recorded instead of risking a second one
    (#260). Two sources can carry that child: already linked under
    `container` (`list_children`), or an orphan -- one of the caller's own
    `open_issues` snapshot with no recorded parent at all, exactly the shape
    a failed `link_child` POST leaves behind. A title match alone is too
    weak to adopt an orphan: any unrelated open issue anywhere in the
    repository -- including one a human filed -- could share it. An orphan
    is adoptable only when it is also a `TASK` (never the container itself,
    never an idea-labelled item) and its body still names `container` as the
    parent `_cut_child_body` wrote for it; a recovery orphan is always
    exactly that shape, and nothing else can fake it. An untyped orphan
    (`forge.ForgeIssueTypeNotSetError`, issue #444) is never adopted: the
    twin search names it instead. An orphan match is linked under
    `container` right here before it is returned, so the caller's remaining steps treat it exactly
    like an already-linked child; the container's own issue is never created
    twice for it. More than one open match refuses by name rather than guess
    which one the failed cut actually created. A closed linked child with
    that title refuses too -- adoption finishes an interrupted cut, it does
    not reopen a closed one. `None` when nothing matches, so the caller
    falls through to `create_child`.
    """
    linked = [
        child
        for child in client.list_children(container)
        if client.item_reference(child.number).title == title
    ]
    open_linked = [child.number for child in linked if child.state is workboard.ChildState.OPEN]
    orphans = [
        issue.number
        for issue in open_issues
        if issue.title == title
        and issue.number != container
        and issue.kind is body.ItemKind.TASK
        and not workboard.has_label(issue.labels, config.idea_label)
        and body.names_parent(issue.body, workboard.item_label(container, config.storage))
        and client.parent_issue(issue.number) is None
    ]
    open_matches = open_linked + orphans
    container_label = workboard.item_label(container, config.storage)
    if len(open_matches) > 1:
        named = ", ".join(workboard.item_label(number, config.storage) for number in open_matches)
        raise protocol.ClaimUnavailableError(
            f"{container_label}'s row {title!r} matches more than one open issue ({named}); "
            "adopt the right one by hand and remove the row"
        )
    if open_matches:
        [number] = open_matches
        if number in orphans:
            client.link_child(container, number)
        return workboard.ChildItem(number, workboard.ChildState.OPEN)
    closed = next((child for child in linked if child.state is workboard.ChildState.CLOSED), None)
    if closed is None:
        return None
    raise protocol.ClaimUnavailableError(
        f"{container_label} already has a closed child "
        f"{workboard.item_label(closed.number, config.storage)} titled {title!r}; "
        "reopen it or remove the row by hand"
    )


# How far back a closed issue still counts for the twin search (issue #444):
# a duplicate usually repeats an item closed weeks, not months, ago.
_TWIN_SEARCH_CLOSED_WINDOW = timedelta(days=30)


# Two titles are possible twins when at least this share of their combined
# distinct casefolded words appears in both (issue #444).
_TWIN_TITLE_WORD_OVERLAP = 0.6


_TITLE_WORD = re.compile(r"\w+")


def _title_words(title: str) -> frozenset[str]:
    return frozenset(_TITLE_WORD.findall(title.casefold()))


def _title_overlap(title: str, other: str) -> float:
    """The share of both titles' combined distinct words they have in
    common; an identical title overlaps fully even without a single word,
    so a re-run is always named as its own earlier run's twin."""
    if other == title:
        return 1.0
    first, second = _title_words(title), _title_words(other)
    combined = first | second
    return len(first & second) / len(combined) if combined else 0.0


def numbered_titles(issues: Iterable[workboard.Issue]) -> tuple[tuple[int, str], ...]:
    return tuple((issue.number, issue.title) for issue in issues)


def _possible_twin(title: str, candidates: Iterable[tuple[int, str]]) -> int | None:
    """The candidate whose title overlaps `title` most, at least
    `_TWIN_TITLE_WORD_OVERLAP`, the lower number on a tie; `None` when no
    candidate reaches it."""
    hits = [
        (overlap, number)
        for number, other in candidates
        if (overlap := _title_overlap(title, other)) >= _TWIN_TITLE_WORD_OVERLAP
    ]
    return min(hits, key=lambda hit: (-hit[0], hit[1]))[1] if hits else None


def refuse_possible_twin(
    client: forge.ForgeReader,
    title: str,
    open_titles: Iterable[tuple[int, str]],
    *,
    parent: int | None,
    storage: body.Storage,
) -> None:
    """The one twin search `item new` and `cut` run before they create an
    issue (issue #444): `open_titles` -- every open issue's number and title
    -- and the titles of every issue closed within `_TWIN_SEARCH_CLOSED_WINDOW`,
    never the new issue's own `parent`. A hit refuses by number;
    `--not-a-twin` is the caller's way past it."""
    since = datetime.now(UTC) - _TWIN_SEARCH_CLOSED_WINDOW
    candidates = [
        *open_titles,
        *((issue.number, issue.title) for issue in client.list_recently_closed_issues(since)),
    ]
    twin = _possible_twin(title, (entry for entry in candidates if entry[0] != parent))
    if twin is not None:
        raise protocol.ClaimUnavailableError(
            f"possible twin {workboard.item_label(twin, storage)}; pass --not-a-twin"
        )


def _cut_link(
    label: str, located: body.LocatedBlock, row_number: int | None
) -> body.SliceRow | None:
    """Which `[[slice]]` entry `cut` links its fresh child to (#150 §7):
    without `--row`, the first entry when the block carries one; with `--row
    N`, the entry `N` names, refusing by name when the block has no `slice`
    key at all or no such row left (every remaining entry is cuttable: a
    linked entry is removed by `body.remove_slice_row` at the moment it is cut).
    `body.cuttable_rows` owns decoding the validated block."""
    entries = body.cuttable_rows(located)
    if row_number is None:
        return entries[0] if entries else None
    if not body.has_slice_table(located):
        raise protocol.ClaimUnavailableError(
            f"{label} has no slice table; --row needs one to select a row from"
        )
    match = next((entry for entry in entries if entry.index == row_number), None)
    if match is None:
        cuttable = ", ".join(str(entry.index) for entry in entries) or "none"
        raise protocol.ClaimUnavailableError(
            f"{label} has no row {row_number}; cuttable rows: {cuttable}"
        )
    return match


def _child_title(label: str, link: body.SliceRow | None, title: str | None) -> str:
    """The title `cut`'s child gets (issue #604): the linked row's own title,
    which a given `--title` must match exactly; with no linked row, `--title`
    itself, which is then required."""
    if link is None:
        if title is None:
            raise protocol.ClaimUnavailableError(f"{label} has no slice row; pass --title")
        return title
    if title is not None and title != link.title:
        raise protocol.ClaimUnavailableError(
            f"{label}'s slice {link.index} is titled {link.title!r}; --title must match it exactly"
        )
    return link.title


_CUT_ROW_SCOPE_ALREADY_SET = "slice {index} already names a scope; edit the container instead"


def _cut_row_scope(
    link: body.SliceRow | None, requested: tuple[str, ...] | None
) -> tuple[str, ...] | None:
    """The scope `cut`'s fresh child inherits (issue #337): the linked
    row's own scope when it already has one -- `--scope` then refuses by
    name, since the row is the one place to change it -- else `--scope`
    fills the (still empty) row and becomes the child's scope; with no
    linked row at all, `--scope` becomes the child's scope directly."""
    if link is not None and link.scope is not None:
        if requested is not None:
            raise protocol.ClaimUnavailableError(
                _CUT_ROW_SCOPE_ALREADY_SET.format(index=link.index)
            )
        return link.scope
    return requested


def _cut_row_done_when(
    number: int, located: body.LocatedBlock, link: body.SliceRow | None, storage: body.Storage
) -> str | None:
    """The `done_when` `cut`'s fresh child inherits (issue #606 line 2):
    the linked row's own, refused in CUT-05's form before any write when it
    breaks BODY-66 (CUT-39)."""
    if link is None:
        return None
    defect = body.slice_done_when_defect(located, link)
    if defect is not None:
        workboard.refuse_malformed_block(number, defect, "cut", storage)
    return link.done_when


_CUT_RERUN_RECOVERY = "re-run the same cut -- it adopts the child"


_CUT_TYPE_RECOVERY = f"set that type on the forge by hand, then {_CUT_RERUN_RECOVERY}"


def _cut_slice(
    client: forge.ForgeWriter,
    target: workboard.Issue,
    open_issues: Iterable[workboard.Issue],
    parsed: argparse.Namespace,
    config: workboard.BoardConfig,
) -> int:
    number = target.number
    storage = config.storage
    label = workboard.item_label(number, storage)
    located = workboard.located_block_or_refuse(number, target.body, command="cut", storage=storage)
    link = _cut_link(label, located, parsed.row)
    title = _child_title(label, link, parsed.title)
    child_scope = _cut_row_scope(link, requested_body_scope(parsed.scope))
    child_done_when = _cut_row_done_when(number, located, link, storage)
    adopted = _adopt_existing_child(client, number, title, config, open_issues)
    if adopted is None and not parsed.not_a_twin:
        refuse_possible_twin(
            client, title, numbered_titles(open_issues), parent=number, storage=storage
        )
    try:
        child = (
            adopted.number
            if adopted is not None
            else client.create_child(
                parent=number,
                title=title,
                body=_cut_child_body(number, storage, child_scope, child_done_when),
                kind=body.ItemKind.TASK,
            )
        )
        if link is not None:
            new_data = body.remove_slice_row(located, link.index)
            removal = _SliceRowRemoval(
                container=number,
                new_body=body.replace_block(target.body, located, new_data),
                step=f"remove row {link.index} from {label}'s {body.BLOCK_FENCE_INFO} block",
            )
            _link_created_child(client, removal, child, storage)
    except forge.ForgeIssueTypeNotSetError as error:
        raise PartialWriteError(error, recovery=_CUT_TYPE_RECOVERY) from error
    except forge.ForgePartialChildCreationError as error:
        raise PartialWriteError(error, recovery=_CUT_RERUN_RECOVERY) from error
    outcome = _CutOutcome(
        container=number,
        row_index=None if link is None else link.index,
        child=child,
        adopted=adopted is not None,
    )
    _print_cut_result(outcome, storage, as_json=parsed.json)
    return 0


def refuse_partial_write(error: PartialWriteError, reason: StrEnum, *, as_json: bool) -> int:
    return report.refuse(reason, error, as_json=as_json, written=error.written, failed=error.failed)


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`cut`'s own `--json` envelope (issue #425): a partial write reports
    through `refuse_partial_write`'s own structured shape; every other
    refusal past the parser is `precondition_failed`, matching this
    command's single generic refusal bucket."""
    as_json = parsed.json
    try:
        client = context.forge_writer
        number = int(parsed.issue)
        for operation in (
            forge.ForgeOperation.CREATE_CHILD,
            forge.ForgeOperation.LINK_CHILD,
            forge.ForgeOperation.UPDATE_ITEM_BODY,
        ):
            if client.capability(operation) is not forge.Capability.READ_WRITE:
                raise protocol.ClaimUnavailableError(
                    f"this forge cannot {operation.value}; cut the slice by hand"
                )
        config = board_read.load_board_config(client, context)
        open_issues = client.list_open_board_issues()
        target = _cut_target(client, open_issues, number, config.storage)
        return _cut_slice(client, target, open_issues, parsed, config)
    except PartialWriteError as error:
        return refuse_partial_write(error, _CutReason.PARTIAL_WRITE, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_CutReason.PRECONDITION_FAILED, error, as_json=as_json)
