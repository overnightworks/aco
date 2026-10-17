"""The board's read leaves: the issue reference fetch, the board config load,
dependency validation, the read-after-write hint, the missing-item refusal,
parent closability, and the trunk landing depth."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TypeVar

from . import board, body, forge, protocol
from .session import RunContext


def parent_closable_number(
    client: forge.ForgeReader, closed_child: int, storage: body.Storage
) -> int | None:
    """The container `closed_child`'s own landing may just have completed
    (issue #348, the parent hint `release --merged`/`item close` share): its
    parent, read fresh, when every other child is already closed too and no
    undispatched `[[slice]]` row is left to cut -- `board.closable_container_number`
    is the one owner for that decision, reused rather than re-derived board-wide
    for one relation. `None` covers every non-container parent, one still
    holding another open child, an already-closed parent (a second close
    would only refuse), or no parent at all. The container decision runs
    before the parent's own state read, so an unreadable parent (issue
    #517, never a container by kind) is answered `None` rather than
    refusing a close that already stood."""
    parent = client.parent_issue(closed_child)
    if parent is None:
        return None
    children = client.list_children(parent.reference.number)
    closable = board.closable_container_number(parent, children, storage)
    if closable is None:
        return None
    parent_is_open = client.item_reference(closable).state is forge.ItemState.OPEN
    return closable if parent_is_open else None


# A stable invariant of the board's own ruling-freshness read (issue #304),
# not something an operator tunes: `RULING_OLD_AFTER_LANDINGS` (10) is the
# most any ruling ever needs counted, so this bounds `git log`'s walk deep
# enough that no realistic ruling window is ever truncated.
TRUNK_LANDING_DEPTH = 5000


def validated_dependencies(
    issues: tuple[board.Issue, ...], fetched: dict[int, tuple[board.IssueDependency, ...]]
) -> dict[int, tuple[board.IssueDependency, ...]]:
    """`fetched`, keyed by exactly the positive-`blocked_by_count` issues,
    each list checked against its own listing count (#150 §6): a length
    mismatch or a duplicated dependency is the same class of malformed
    forge response as a disagreeing container summary -- named loud rather
    than guessed through."""
    validated: dict[int, tuple[board.IssueDependency, ...]] = {}
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


def load_board_config(client: forge.BoardSource, context: RunContext) -> board.BoardConfig:
    """`context`'s board configuration, validated against what `client`
    can actually do (#150 §3): reading a body's dependencies requires
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
    issue #256; `item close`, issue #541): a forge hiccup (LAND-38) or a
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
    """The one wording every post-write command shares (issue #546): it
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
    return f"{board.item_label(number, storage)} does not exist in {client.repository.path}"
