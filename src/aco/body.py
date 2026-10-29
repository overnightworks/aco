"""The body-block codec: parses, validates,
renders, and names defects for one work-item body's typed `aco`
fenced block -- the `[[expectation]]`/`[[slice]]` arrays, `scope`/`size`/
`whole`, and the state-ref-only `[record]` table. `workboard.py` imports this
codec for its own board-builder domain (`Contract`, `ParsedBody`,
`BodyReadState`, `Storage`, `ItemKind`, ... are all board-domain field types
too, read straight off a parsed body); `items.py` and `state_board.py`
import it for the same one schema `workboard.py` used to own alone. This module
never imports `workboard`, `items`, or `state_board` back (Layers contract):
`items` may import this module, never the reverse, so a value both this
codec and `items.py` need (`ORIGIN_PATTERN`) is owned here instead.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import Enum, StrEnum
from typing import TypeGuard, cast

from . import expectation_grammar, metrics, protocol
from .expectation_grammar import NOT_A_LOCAL_DATE, block_expectation_defects, render_expectations

# CommonMark fence delimiters: at most 3 leading spaces, then a run of 3+
# backticks or 3+ tildes. An OPENING delimiter may carry an info string after
# the run (` ```python `); a CLOSING delimiter may not — only trailing
# spaces/tabs are allowed after the run (` ``` `, never ` ```python `), so
# `Closing`'s stricter pattern requires nothing but whitespace to follow.
# A 4-space-indented code block (CommonMark's other fencing form) is not
# modeled here; see `workboard.py`'s `_live_text` for why that gap is safe.
FENCE_OPENING_PATTERN = re.compile(r"^ {0,3}(?P<run>`{3,}|~{3,})")
FENCE_CLOSING_PATTERN = re.compile(r"^ {0,3}(?P<run>`{3,}|~{3,})[ \t]*$")

# A fresh container carries no automatic parent-provenance the way `cut`
# gives a fresh child one, so `item new` with nothing piped states the prose
# the global contract requires when nothing blocks it (README "`Blocked by:`
# prose beside the block is documentation only") above the same block
# `prose_above_fresh_block` builds for every kind -- one owner for the
# projection keys, never a second schema for a container's own skeleton.
CONTAINER_SKELETON_PROSE = "Blocked by: nichts"

# The one fenced-block info string a repository pinned to `body_contract =
# "block"` reads as its typed work-item body -- any other
# fence's info string is ordinary documentation.
BLOCK_FENCE_INFO = "aco"
BLOCK_TOP_LEVEL_KEYS = frozenset(
    {
        "version",
        "now",
        "next",
        "done_when",
        "frozen_until",
        "scope",
        "size",
        "whole",
        "expectation",
        "slice",
    }
)
# A work item's own size class, read straight from
# `metrics.Size` -- the one owner of the three letters and their order --
# rather than a second enum here. A top-level block key, not a `[record]`
# one: `[record]` is a `Storage.STATE_REF`-only table (BODY-15), while an
# estimate is offered for every item regardless of storage, and this
# module may never import `github`/`state_board` to give a GitHub-stored
# item a second write path.
SIZE_VALUES = frozenset(size.value for size in metrics.Size)
BLOCK_VERSION = 1


class Storage(StrEnum):
    """Where a repository's board and item data live (`.aco/board.toml`
    `storage`): `GITHUB` reads issues, `STATE_REF` reads
    `items/<id>.md` files in the tree of `refs/aco/state`. The pin decides
    which adapter `RunContext.repository_id` resolves for; it never guesses from
    the remote's own host."""

    GITHUB = "github"
    STATE_REF = "state-ref"


# A state-ref item file's own `[record]` table: the identity
# and relations a GitHub issue would otherwise carry through its native
# type, sub-issue, and blocked-by relations. Legal only under
# `storage = "state-ref"` -- `_block_schema_defects` refuses it by name as
# an unknown top-level key under `storage = "github"` (decision record 0001
# §2: blockers and parentage on GitHub, never duplicated in the body).
RECORD_KEY = "record"
RECORD_STATES = frozenset({"open", "closed"})
RECORD_KEYS = frozenset(
    {
        "title",
        "state",
        "kind",
        "labels",
        "blocked_by",
        "parent",
        "origin",
        "created_at",
        "updated_at",
        "closed_at",
    }
)

# The one origin grammar: a forge name or
# host/owner/repo path -- one or more letter/digit/hyphen segments joined by
# `.` or `/` -- then `#` and the number that forge itself uses for the
# issue. Case-insensitive on the host/owner/repo part: a
# hand-written v2 ref may carry the forge's own capitalization, e.g.
# `github.com/OvernightWorks/x#1`. `items.parse_origin`'s argparse `type=`
# and the persisted `[record].origin` field (`_record_relation_defects`
# below) both validate against this one pattern, so a stored malformed
# origin is exactly as rejected as a malformed `--origin` flag. This is
# also the one owner `aco pull <forge>#<n>` will later split
# `record.origin` back out through. Owned here, not in `items.py`, so this
# module's own `_record_relation_defects` never has to import a higher
# layer for one shared pattern (`items` may import `body`, never the
# reverse).
ORIGIN_PATTERN = re.compile(
    r"[a-z][a-z0-9-]*(?:[./][a-z][a-z0-9-]*)*#[1-9]\d*", re.ASCII | re.IGNORECASE
)
# The one hint text for a malformed origin, shared by `items.parse_origin`'s
# argparse refusal and `_record_relation_defects`' record defect, so a bad
# `--origin` flag and a bad stored `record.origin` read the same sentence
# rather than two independently worded rules for one grammar.
ORIGIN_GRAMMAR_HINT = "forge#n or host/owner/repo#n, e.g. gitlab#42"


class ItemKind(StrEnum):
    """An item's kind, read from the forge's native issue type -- the one
    owner for "is this a container" (decision record 0001 ruling D3)."""

    TASK = "task"
    BUG = "bug"
    FEATURE = "feature"
    CONTAINER = "container"


@dataclass(frozen=True)
class SliceRow:
    """One `[[slice]]` entry of a body's `aco` block: a slice its
    container still has to dispatch. `index` is exactly what `cut --row N`
    names it by, `title` exactly what `cut --title` must match. `scope`
    is the row's own optional `scope = [...]`, validated and
    canonicalized like the block's top-level field; `None` when the row
    names no paths of its own. `done_when` is the row's own
    one-line done-when, the child's `done_when` once `cut` creates it;
    `None` when the row carries none."""

    index: int
    title: str
    scope: tuple[str, ...] | None = None
    done_when: str | None = None


@dataclass(frozen=True)
class ContractDefect:
    field: str
    message: str


def body_defect_text(defect: ContractDefect) -> str:
    """The one rendering of a malformed body defect.

    `cut` and the board/claim checks share this; a second renderer is a
    defect. `check` in slice F reuses it. It escapes each display control
    as `protocol.terminal_text` does, so no caller prints a stored key raw.
    """
    return protocol.terminal_text(f"body malformed: {defect.field}: {defect.message}")


def contract_fields(contract: Contract) -> tuple[tuple[str, str | None], ...]:
    """The three projection keys in block order, paired with their current
    value -- the one place that knows both the names and the order, so a
    caller asking which are present (`_contract_summary`) and a caller
    asking which are missing (`missing_or_empty_sections`) never drift
    apart. A block body has no dependency key at all: its dependencies live
    on the forge, never in the body.
    """
    return (
        ("Now", contract.now),
        ("Next", contract.next),
        ("Done when", contract.done_when),
    )


@dataclass(frozen=True)
class Contract:
    now: str | None
    next: str | None
    done_when: str | None
    defects: tuple[ContractDefect, ...] = ()


class ExpectationState(StrEnum):
    NONE = "-"
    PROPOSED = "proposed"
    RULED = "ruled"


@dataclass(frozen=True)
class ExpectationProgress:
    open: int
    total: int


def opening_fence_delimiter(line: str) -> tuple[str, int] | None:
    match = FENCE_OPENING_PATTERN.match(line)
    if match is None:
        return None
    run = match.group("run")
    return run[0], len(run)


def closing_fence_delimiter(line: str) -> tuple[str, int] | None:
    match = FENCE_CLOSING_PATTERN.match(line)
    if match is None:
        return None
    run = match.group("run")
    return run[0], len(run)


class BodyReadState(StrEnum):
    """How `parse_body` read one issue's body.

    `MALFORMED` covers both a block whose schema was refused and a body
    with no recognized `aco` block at all -- the latter carries the
    one defect `no aco block` (there is no third state
    for a body written before the block existed).
    """

    VALID = "valid"
    MALFORMED = "malformed"


@dataclass(frozen=True)
class ParsedBody:
    """The one typed read of a work-item body. Every consumer reads this
    instead of re-parsing the raw body."""

    contract: Contract
    contract_complete: bool
    expectation_state: ExpectationState
    expectation_progress: ExpectationProgress
    ruling_date: date | None
    frozen_trigger: str | None
    # The block's own top-level `scope = [...]`, exactly the
    # canonical (sorted, deduplicated) tuple `protocol.valid_scope` returns
    # -- the same function a live claim's own scope passes through, so the
    # two stay comparable regardless of typed order. `None` when the block
    # carries no `scope` key at all, never for an empty one
    # (`_block_scope_defects` refuses that before this projection is ever
    # built).
    scope: tuple[str, ...] | None
    slices: tuple[SliceRow, ...]
    read_state: BodyReadState
    # The block's own top-level `size`, or `None` for a body
    # that names no size at all -- absent means "no estimate", never a
    # default class a reader would have to guess.
    size: metrics.Size | None = None
    # The block's own top-level `whole` reason, or `None` when
    # the item names none -- `claim`/`start`'s own fallback for `--whole`
    # when the call itself names none, read here rather than re-parsed at
    # each call site.
    whole: str | None = None
    # The validated `[record]` table, or `None` for every body
    # parsed under `Storage.GITHUB` and every state-ref body without one --
    # `items.py` is the one reader that ever looks at this field.
    record: Mapping[str, object] | None = None


def _line_ending(raw_line: str) -> str:
    if raw_line.endswith("\r\n"):
        return "\r\n"
    if raw_line.endswith("\n"):
        return "\n"
    return ""


def _line_without_ending(raw_line: str) -> str:
    ending = _line_ending(raw_line)
    return raw_line[: len(raw_line) - len(ending)] if ending else raw_line


def first_line(body: str) -> str:
    """`body`'s first line with its ending stripped, whether the body uses
    LF or CRLF -- a GitHub GET returns CRLF (`_line_ending` above), so a
    caller comparing against a fixed marker line must not split on a bare
    `"\\n"`."""
    lines = body.splitlines(keepends=True)
    return _line_without_ending(lines[0]) if lines else ""


def parent_line(label: str) -> str:
    """The parent provenance line for an already-rendered item label."""
    return f"Parent: {label}"


def names_parent(raw: str, label: str) -> bool:
    """Whether the first line names exactly this parent, under LF or CRLF."""
    return first_line(raw) == parent_line(label)


def _fence_matches(body: str) -> list[tuple[int, int | None, str]]:
    """Every fence in `body` whose info string is exactly `aco`:
    `(opening line index, closing line index or None when
    unclosed, interior text)`. Walks `body.splitlines(keepends=True)` --
    stripping only each line's own ending before matching the CommonMark
    fence patterns, so CRLF is recognized and every other byte, including
    the fence's own line endings, is preserved for the caller. Only one
    fence is ever open at a time, matching `_live_line_entries`: an
    already-open fence, recognized or not, blocks a new opening delimiter
    from being recognized until it closes.
    """
    lines = body.splitlines(keepends=True)
    matches: list[tuple[int, int | None, str]] = []
    index = 0
    open_start: int | None = None
    open_char = ""
    open_length = 0
    open_recognized = False
    while index < len(lines):
        bare = _line_without_ending(lines[index])
        if open_start is None:
            opening = FENCE_OPENING_PATTERN.match(bare)
            if opening is not None:
                run = opening.group("run")
                info = bare[opening.end() :].strip(" \t")
                open_start, open_char, open_length = index, run[0], len(run)
                open_recognized = info == BLOCK_FENCE_INFO
            index += 1
            continue
        closing = FENCE_CLOSING_PATTERN.match(bare)
        if (
            closing is not None
            and closing.group("run")[0] == open_char
            and len(closing.group("run")) >= open_length
        ):
            if open_recognized:
                matches.append((open_start, index, "".join(lines[open_start + 1 : index])))
            open_start, open_recognized = None, False
        index += 1
    if open_start is not None and open_recognized:
        matches.append((open_start, None, ""))
    return matches


def _block_version_defect(data: dict[str, object]) -> ContractDefect | None:
    if "version" not in data:
        return ContractDefect("version", "version is required and must be 1")
    value = data["version"]
    if isinstance(value, bool) or value != BLOCK_VERSION:
        return ContractDefect("version", f"version must be exactly {BLOCK_VERSION}")
    return None


def _block_projection_defects(data: dict[str, object]) -> list[ContractDefect]:
    defects: list[ContractDefect] = []
    for key in ("now", "next", "done_when"):
        if key not in data:
            defects.append(ContractDefect(key, f"{key} is required"))
        elif not isinstance(data[key], str):
            defects.append(ContractDefect(key, f"{key} must be a string"))
    return defects


def _block_frozen_until_defects(data: dict[str, object]) -> list[ContractDefect]:
    if "frozen_until" not in data:
        return []
    value = data["frozen_until"]
    if not isinstance(value, dict):
        return [
            ContractDefect(
                "frozen_until.trigger", "frozen_until must be a table with trigger and ruled_on"
            )
        ]
    defects: list[ContractDefect] = []
    trigger = value.get("trigger")
    if not isinstance(trigger, str) or not trigger.strip():
        defects.append(
            ContractDefect(
                "frozen_until.trigger", "frozen_until.trigger must be a non-empty string"
            )
        )
    ruled_on = value.get("ruled_on")
    if type(ruled_on) is not date:
        defects.append(
            ContractDefect("frozen_until.ruled_on", f"frozen_until.ruled_on {NOT_A_LOCAL_DATE}")
        )
    unknown = sorted(set(value) - {"trigger", "ruled_on"})
    defects.extend(
        ContractDefect(f"frozen_until.{key}", f"unknown key frozen_until.{key}") for key in unknown
    )
    return defects


SCOPE_MUST_NAME_A_PATH = "must name at least one path"


def _scope_value_defect(field_name: str, value: object) -> ContractDefect | None:
    """One `scope` field's own refusal -- the block's top-level `scope`
    (`field_name="scope"`) or one `[[slice]]` row's own
    (`field_name="slice[N].scope"`). Called only once the
    caller already knows the key is present; a present value must be a
    non-empty list, refused with this module's own sentence, and every
    entry must pass `protocol.valid_scope` -- the one path grammar `claim`
    already owns, whose own refusal becomes the defect sentence verbatim
    rather than a second grammar invented here."""
    if not isinstance(value, list) or not value:
        return ContractDefect(field_name, f"{field_name} {SCOPE_MUST_NAME_A_PATH}")
    try:
        protocol.valid_scope(value)
    except protocol.InvalidClaimMarkerError as error:
        return ContractDefect(field_name, str(error))
    return None


def _block_scope_defects(data: dict[str, object]) -> list[ContractDefect]:
    if "scope" not in data:
        return []
    defect = _scope_value_defect("scope", data["scope"])
    return [defect] if defect is not None else []


def _block_size_defect(data: dict[str, object]) -> ContractDefect | None:
    if "size" not in data:
        return None
    value = data["size"]
    if isinstance(value, str) and value in SIZE_VALUES:
        return None
    return ContractDefect("size", "size must be S, M, or L")


_WHOLE_REASON_LABEL = "whole reason"
WHOLE_REASON_TEXT_MAXIMUM = 512


def bounded_whole_reason(value: object) -> str:
    """Validate the shared body and flag whole-reason contract."""
    if not isinstance(value, str):
        raise protocol.ClaimError(f"{_WHOLE_REASON_LABEL} must be one bounded non-empty line")
    return protocol.outbound_text(value, _WHOLE_REASON_LABEL, maximum=WHOLE_REASON_TEXT_MAXIMUM)


def _block_whole_defect(data: dict[str, object]) -> ContractDefect | None:
    """An absent reason is valid; a present one shares the flag's bound."""
    if "whole" not in data:
        return None
    try:
        bounded_whole_reason(data["whole"])
    except protocol.ClaimError as error:
        return ContractDefect("whole", str(error))
    return None


def _canonical_scope(value: object) -> tuple[str, ...]:
    """`value`'s validated scope entries, in `protocol.valid_scope`'s own
    canonical (sorted, deduplicated) order -- the one scope normaliser a
    live claim's own scope is built through too, so a body's projected
    `scope` and a claim's recorded `scope` stay comparable as tuples.
    Callable only once a schema check (`_block_scope_defects`,
    `_block_slice_entry_defects`) has already proven `value` valid."""
    return protocol.valid_scope(value)


def _record_timestamp_defect(value: object, key_name: str) -> ContractDefect | None:
    if not isinstance(value, str) or protocol.RFC3339_TIMESTAMP_PATTERN.fullmatch(value) is None:
        return ContractDefect(
            f"record.{key_name}", f"record.{key_name} must be an RFC 3339 UTC timestamp"
        )
    return None


def is_valid_title(title: object) -> TypeGuard[str]:
    """An item title's one rule, `record.title`'s and `--title`'s alike:
    a string holding more than whitespace."""
    return isinstance(title, str) and bool(title.strip())


def _record_identity_defects(value: dict[str, object]) -> list[ContractDefect]:
    """`[record]`'s own identity fields: `title`, `state`, `kind`, `labels`,
    `blocked_by` -- split from `_block_record_defects` only to stay under
    one function's branch budget; the two together are the whole table."""
    defects: list[ContractDefect] = []
    if not is_valid_title(value.get("title")):
        defects.append(ContractDefect("record.title", "record.title must be a non-empty string"))
    if value.get("state") not in RECORD_STATES:
        defects.append(ContractDefect("record.state", "record.state must be open or closed"))
    kind = value.get("kind")
    if kind is not None and kind not in set(ItemKind):
        defects.append(ContractDefect("record.kind", "record.kind must be a known item kind"))
    labels = value.get("labels", [])
    if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
        defects.append(ContractDefect("record.labels", "record.labels must be an array of strings"))
    blocked_by = value.get("blocked_by", [])
    if not isinstance(blocked_by, list) or not all(isinstance(item, str) for item in blocked_by):
        defects.append(
            ContractDefect("record.blocked_by", "record.blocked_by must be an array of item ids")
        )
    return defects


def _record_relation_defects(value: dict[str, object]) -> list[ContractDefect]:
    """`[record]`'s remaining fields: `parent`, `origin`, the three
    timestamps, and the unknown-key sweep."""
    defects: list[ContractDefect] = []
    parent = value.get("parent")
    if parent is not None and not isinstance(parent, str):
        defects.append(ContractDefect("record.parent", "record.parent must be an item id string"))
    origin = value.get("origin")
    if origin is not None and (
        not isinstance(origin, str) or ORIGIN_PATTERN.fullmatch(origin) is None
    ):
        defects.append(
            ContractDefect("record.origin", f"record.origin must be {ORIGIN_GRAMMAR_HINT}")
        )
    for key_name in ("created_at", "updated_at"):
        defect = _record_timestamp_defect(value.get(key_name), key_name)
        if defect is not None:
            defects.append(defect)
    closed_at = value.get("closed_at")
    if closed_at is not None:
        defect = _record_timestamp_defect(closed_at, "closed_at")
        if defect is not None:
            defects.append(defect)
    if value.get("state") == "closed" and closed_at is None:
        defects.append(
            ContractDefect(
                "record.closed_at", "record.closed_at is required when record.state is closed"
            )
        )
    unknown = sorted(set(value) - RECORD_KEYS)
    defects.extend(ContractDefect(f"record.{key}", f"unknown key record.{key}") for key in unknown)
    return defects


def _block_record_defects(data: dict[str, object]) -> list[ContractDefect]:
    """`[record]`, valid only when this parse is storage-gated
    to allow it at all (`_block_schema_defects`'s caller): the identity and
    relations a GitHub issue would otherwise carry natively. `items.py`
    trusts every field's shape once this returns no defect -- it never
    re-validates what this function already checked."""
    if RECORD_KEY not in data:
        return []
    value = data[RECORD_KEY]
    if not isinstance(value, dict):
        return [ContractDefect(RECORD_KEY, f"{RECORD_KEY} must be a table")]
    return _record_identity_defects(value) + _record_relation_defects(value)


def _block_slice_entry_defects(
    index: int, entry: object, seen_indices: dict[int, int]
) -> list[ContractDefect]:
    prefix = f"slice[{index}]"
    if not isinstance(entry, dict):
        return [ContractDefect(prefix, f"{prefix} must be a table")]
    defects: list[ContractDefect] = []
    slice_index = entry.get("index")
    if not isinstance(slice_index, int) or isinstance(slice_index, bool) or slice_index <= 0:
        defects.append(
            ContractDefect(f"{prefix}.index", f"{prefix}.index must be a positive integer")
        )
    elif slice_index in seen_indices:
        defects.append(
            ContractDefect(
                f"{prefix}.index", f"{prefix}.index duplicates slice index {slice_index}"
            )
        )
    else:
        seen_indices[slice_index] = index
    defects.extend(_slice_text_defects(prefix, entry))
    if "scope" in entry:
        scope_defect = _scope_value_defect(f"{prefix}.scope", entry["scope"])
        if scope_defect is not None:
            defects.append(scope_defect)
    unknown = sorted(set(entry) - {"index", *SLICE_LINE_KEYS, "scope"})
    defects.extend(
        ContractDefect(f"{prefix}.{key}", f"unknown key {prefix}.{key}") for key in unknown
    )
    return defects


# A `[[slice]]` row's two one-line text fields (BODY-47, BODY-63):
# `title` is required, `done_when` optional -- absent, `cut` leaves
# the child's `done_when` empty.
SLICE_LINE_KEYS = ("title", "done_when")


def _slice_text_defects(prefix: str, entry: dict[str, object]) -> list[ContractDefect]:
    return [
        ContractDefect(f"{prefix}.{key}", f"{prefix}.{key} must be a non-empty string")
        for key in SLICE_LINE_KEYS
        if (key == "title" or key in entry)
        and not (isinstance(entry.get(key), str) and cast(str, entry[key]).strip())
    ]


def _block_slice_defects(entries: list[object]) -> list[ContractDefect]:
    seen_indices: dict[int, int] = {}
    defects: list[ContractDefect] = []
    for index, entry in enumerate(entries):
        defects.extend(_block_slice_entry_defects(index, entry, seen_indices))
    return defects


def _block_array_or_defect(
    data: dict[str, object], key: str
) -> tuple[list[object], ContractDefect | None]:
    value = data.get(key, [])
    if not isinstance(value, list):
        return [], ContractDefect(key, f"{key} must be an array of tables")
    return value, None


def _block_schema_defects(data: dict[str, object], storage: Storage) -> tuple[ContractDefect, ...]:
    defects: list[ContractDefect] = []
    version_defect = _block_version_defect(data)
    if version_defect is not None:
        defects.append(version_defect)
    defects.extend(_block_projection_defects(data))
    defects.extend(_block_frozen_until_defects(data))
    defects.extend(_block_scope_defects(data))
    size_defect = _block_size_defect(data)
    if size_defect is not None:
        defects.append(size_defect)
    whole_defect = _block_whole_defect(data)
    if whole_defect is not None:
        defects.append(whole_defect)
    expectations, expectation_defect = _block_array_or_defect(data, "expectation")
    defects.append(expectation_defect) if expectation_defect else defects.extend(
        ContractDefect(*defect) for defect in block_expectation_defects(expectations)
    )
    slices, slice_defect = _block_array_or_defect(data, "slice")
    defects.append(slice_defect) if slice_defect else defects.extend(_block_slice_defects(slices))
    allowed_keys = BLOCK_TOP_LEVEL_KEYS
    if storage is Storage.STATE_REF:
        allowed_keys = allowed_keys | {RECORD_KEY}
        defects.extend(_block_record_defects(data))
    unknown = sorted(set(data) - allowed_keys)
    defects.extend(ContractDefect(key, f"unknown top-level key {key}") for key in unknown)
    return tuple(defects)


def _escaped_defect(defect: ContractDefect) -> ContractDefect:
    return ContractDefect(
        protocol.terminal_text(defect.field), protocol.terminal_text(defect.message)
    )


def malformed_parsed_body(defects: tuple[ContractDefect, ...]) -> ParsedBody:
    return ParsedBody(
        contract=Contract(None, None, None, tuple(_escaped_defect(defect) for defect in defects)),
        contract_complete=False,
        expectation_state=ExpectationState.NONE,
        expectation_progress=ExpectationProgress(0, 0),
        ruling_date=None,
        frozen_trigger=None,
        scope=None,
        slices=(),
        read_state=BodyReadState.MALFORMED,
    )


_NO_BLOCK_PARSED_BODY = malformed_parsed_body(
    (ContractDefect(BLOCK_FENCE_INFO, f"no {BLOCK_FENCE_INFO} block"),)
)


def _block_array(data: dict[str, object], key: str) -> list[object]:
    value = data.get(key)
    return value if isinstance(value, list) else []


def block_expectation_dicts(data: dict[str, object]) -> list[dict[str, object]]:
    return [entry for entry in _block_array(data, "expectation") if isinstance(entry, dict)]


def _block_expectation_state(expectations: list[dict[str, object]]) -> ExpectationState:
    if not expectations:
        return ExpectationState.NONE
    if any(map(expectation_grammar.is_open_line, expectations)):
        return ExpectationState.PROPOSED
    return ExpectationState.RULED


def _block_expectation_progress(expectations: list[dict[str, object]]) -> ExpectationProgress:
    return ExpectationProgress(
        open=sum(map(expectation_grammar.is_open_line, expectations)), total=len(expectations)
    )


def _block_ruling_date(expectations: list[dict[str, object]]) -> date | None:
    ruled_dates = [
        entry["ruled_on"]
        for entry in expectations
        if "ruled_on" in entry and type(entry["ruled_on"]) is date
    ]
    return min(ruled_dates) if ruled_dates else None


def _block_frozen_trigger(data: dict[str, object]) -> str | None:
    value = data.get("frozen_until")
    trigger = value.get("trigger") if isinstance(value, dict) else None
    return trigger if isinstance(trigger, str) else None


def slice_row(entry: Mapping[str, object]) -> SliceRow:
    """One schema-valid `[[slice]]` entry as a `SliceRow` -- the one reader
    `parse_body` and `cut` share, so a row field `cut` acts on is never read
    a second way."""
    return SliceRow(
        cast(int, entry["index"]),
        cast(str, entry["title"]),
        _canonical_scope(entry["scope"]) if "scope" in entry else None,
        cast(str, entry["done_when"]) if "done_when" in entry else None,
    )


def _block_slices(data: dict[str, object]) -> tuple[SliceRow, ...]:
    """Every still-undispatched `[[slice]]` entry: `cut` removes an entry
    from the block at the moment it links a child to it, so whatever is left
    here is exactly what is still uncut. Each row's own `scope`
    is canonicalized the same way the block's top-level one is."""
    return tuple(
        slice_row(entry)
        for entry in _block_array(data, "slice")
        if isinstance(entry, dict)
        and isinstance(entry.get("index"), int)
        and isinstance(entry.get("title"), str)
    )


def _valid_block_parsed_body(data: dict[str, object], storage: Storage) -> ParsedBody:
    now, next_value, done_when = (
        cast(str, data["now"]).strip(),
        cast(str, data["next"]).strip(),
        cast(str, data["done_when"]).strip(),
    )
    expectations = block_expectation_dicts(data)
    expectation_state = _block_expectation_state(expectations)
    record = data.get(RECORD_KEY) if storage is Storage.STATE_REF else None
    return ParsedBody(
        contract=Contract(now, next_value, done_when, ()),
        contract_complete=bool(now and next_value and done_when),
        expectation_state=expectation_state,
        expectation_progress=_block_expectation_progress(expectations),
        ruling_date=(
            _block_ruling_date(expectations)
            if expectation_state is ExpectationState.RULED
            else None
        ),
        frozen_trigger=_block_frozen_trigger(data),
        scope=_canonical_scope(data["scope"]) if "scope" in data else None,
        slices=_block_slices(data),
        read_state=BodyReadState.VALID,
        size=metrics.Size(data["size"]) if "size" in data else None,
        whole=cast(str, data["whole"]) if "whole" in data else None,
        record=cast("Mapping[str, object] | None", record),
    )


def parse_body(body: str, *, storage: Storage = Storage.GITHUB) -> ParsedBody:
    """The one read of a work-item body:
    the typed `aco` block. Every consumer reads the
    returned `ParsedBody` instead of re-parsing the raw body. Human prose
    around the block is never parsed -- another repository may own its own
    section headings in the same body.

    `storage` gates the one storage-specific extension, `[record]`:
    legal, and validated, only under `Storage.STATE_REF`; an unknown
    top-level key under `Storage.GITHUB`, the default every existing caller
    keeps reading with.
    """
    data = _block_data(body)
    if isinstance(data, ParsedBody):
        return data
    defects = _block_schema_defects(data, storage)
    if defects:
        return malformed_parsed_body(defects)
    return _valid_block_parsed_body(data, storage)


def _block_data(body: str) -> dict[str, object] | ParsedBody:
    """`body`'s one closed `aco` block, decoded as TOML but not yet
    schema-checked, or the `ParsedBody` that already says why it cannot be."""
    fences = _fence_matches(body)
    if not fences:
        return _NO_BLOCK_PARSED_BODY
    if len(fences) > 1:
        return malformed_parsed_body(
            (
                ContractDefect(
                    BLOCK_FENCE_INFO,
                    f"multiple {BLOCK_FENCE_INFO} blocks; exactly one is allowed",
                ),
            )
        )
    _start, end, content = fences[0]
    if end is None:
        return malformed_parsed_body(
            (ContractDefect(BLOCK_FENCE_INFO, f"unclosed {BLOCK_FENCE_INFO} block"),)
        )
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        return malformed_parsed_body(
            (
                ContractDefect(
                    BLOCK_FENCE_INFO, f"{BLOCK_FENCE_INFO} block is not valid TOML: {error}"
                ),
            )
        )
    return data


class UnreadParent(Enum):
    """The parent of an item whose `[record]`, or its `parent`, does not
    read: it may name any item, so no container can rule it out as its
    child (ITEM-54)."""

    UNREAD = "unread"


def readable_record_title(body: str) -> str | None:
    """`body`'s `[record]` title when it alone still reads -- even when
    another field leaves the block malformed, so `item new`'s
    twin search still compares a malformed state-ref item's title; `None`
    when no valid title can be read at all."""
    record = _readable_record(body)
    title = None if record is None else record.get("title")
    return title.strip() if is_valid_title(title) else None


def readable_record_parent(body: str) -> str | UnreadParent | None:
    """`body`'s `[record]` parent when it alone still reads -- even when
    another field leaves the block malformed, so a container
    still counts a malformed state-ref child as its own; `None` when the
    record reads without a parent, a top-level item; `UnreadParent.UNREAD`
    when the record or its parent does not read."""
    record = _readable_record(body)
    if record is None:
        return UnreadParent.UNREAD
    parent = record.get("parent")
    return parent if parent is None or isinstance(parent, str) else UnreadParent.UNREAD


def _readable_record(body: str) -> Mapping[str, object] | None:
    """`body`'s `[record]` table as far as its block still decodes as TOML,
    `None` when it does not."""
    data = _block_data(body)
    record = data.get(RECORD_KEY) if isinstance(data, dict) else None
    return record if isinstance(record, dict) else None


@dataclass(frozen=True)
class LocatedBlock:
    """A valid `aco` block's decoded TOML, plus the byte-exact span
    of its interior -- between the fence lines, which stay byte-identical --
    and the newline convention new interior lines are rendered with.
    Callable only on a body `parse_body` already read as `VALID`;
    `cut` refuses a malformed target before ever calling this."""

    data: dict[str, object]
    content_start: int
    content_end: int
    newline: str


def locate_block(body: str) -> LocatedBlock:
    lines = body.splitlines(keepends=True)
    matches = _fence_matches(body)
    if not matches:
        raise protocol.ClaimError(f"locate_block found no recognized {BLOCK_FENCE_INFO} fence")
    start_line, end_line, content = matches[0]
    if end_line is None:
        raise protocol.ClaimError(f"locate_block found no closed {BLOCK_FENCE_INFO} fence")
    content_start = sum(len(line) for line in lines[: start_line + 1])
    content_end = sum(len(line) for line in lines[:end_line])
    newline = _line_ending(lines[start_line]) or "\n"
    return LocatedBlock(tomllib.loads(content), content_start, content_end, newline)


def has_slice_table(located: LocatedBlock) -> bool:
    """Whether the block carries a slice key, including an empty table."""
    return "slice" in located.data


def cuttable_rows(located: LocatedBlock) -> tuple[SliceRow, ...]:
    """The remaining slice rows of a schema-validated block, in stored order."""
    return _block_slices(located.data)


def remove_slice_row(located: LocatedBlock, index: int) -> dict[str, object]:
    """Copy validated block data without the row whose `index` is `index`."""
    remaining = [
        entry
        for entry in cast(list[dict[str, object]], located.data.get("slice", []))
        if entry["index"] != index
    ]
    return {**located.data, "slice": remaining}


# The shape one decoded JSON object takes -- one alias so `cast` names a
# real type instead of repeating the `"dict[str, object]"` string literal
# (python:S1192).
_JsonObject = dict[str, object]

# The shape a decoded homogeneous array of tables (`[[expectation]]`,
# `[[slice]]`) or an `asdict`'d list of dataclasses takes -- one alias so
# `cast` names a real type instead of repeating the string.
_JsonRows = list[_JsonObject]

# `protocol.toml_string` is this repository's one TOML basic-string writer:
# it lives below this module in the Layers contract, so it is
# imported rather than kept as a second escape table here, and so is its
# multi-line twin `protocol.toml_multiline_string`.


def _render_frozen_until(data: Mapping[str, object]) -> list[str]:
    frozen_until = data.get("frozen_until")
    if not isinstance(frozen_until, dict):
        return []
    ruled_on = cast(date, frozen_until["ruled_on"])
    return [
        "",
        f"frozen_until = {{ trigger = {protocol.toml_string(frozen_until['trigger'])}, "
        f"ruled_on = {ruled_on.isoformat()} }}",
    ]


def _render_scope_array(values: object) -> str:
    """`values`'s scope entries as a canonical TOML array: the one rendering
    `_render_scope` (top-level) and `_render_slices` (per row) both call,
    routed through `protocol.valid_scope` -- the one scope canonicalizer,
    rather than a second sort/dedupe owner
    here. Callable only once a schema check has already proven `values`
    valid, so this never itself refuses a duplicate."""
    entries = protocol.valid_scope(values)
    return "[" + ", ".join(protocol.toml_string(value) for value in entries) + "]"


def _render_scope(data: Mapping[str, object]) -> list[str]:
    if "scope" not in data:
        return []
    return ["", f"scope = {_render_scope_array(data['scope'])}"]


def _render_size(data: Mapping[str, object]) -> list[str]:
    if "size" not in data:
        return []
    return ["", f"size = {protocol.toml_string(data['size'])}"]


def _render_whole(data: Mapping[str, object]) -> list[str]:
    if "whole" not in data:
        return []
    return ["", f"whole = {protocol.toml_string(data['whole'])}"]


def _render_empty_slice_table(data: Mapping[str, object]) -> list[str]:
    """`slice = []` (BODY-49), the typed "nothing left to cut", among the
    top-level keys: written after any `[[expectation]]` table, TOML would
    bind it to that table as `expectation[N].slice`."""
    if data.get("slice") == []:
        return ["", "slice = []"]
    return []


def _render_slices(data: Mapping[str, object]) -> list[str]:
    lines: list[str] = []
    for entry in cast(_JsonRows, data.get("slice", [])):
        lines.extend(
            (
                "",
                "[[slice]]",
                f"index = {entry['index']}",
                f"title = {protocol.toml_string(entry['title'])}",
            )
        )
        if "done_when" in entry:
            lines.append(f"done_when = {protocol.toml_string(entry['done_when'])}")
        if "scope" in entry:
            lines.append(f"scope = {_render_scope_array(entry['scope'])}")
    return lines


def _render_record_array(values: object) -> str:
    entries = cast("list[str]", values)
    return "[" + ", ".join(protocol.toml_string(value) for value in entries) + "]"


def _render_record(data: Mapping[str, object]) -> list[str]:
    """`[record]`, rendered only when `data` carries one --
    every GitHub-stored block never does. Optional fields (`kind`, `parent`,
    `origin`, `closed_at`) are omitted entirely rather than written `= ""`,
    matching how `parse_body`/`_block_record_defects` read their absence as
    `None`, never as an empty string."""
    if RECORD_KEY not in data:
        return []
    record = cast(Mapping[str, object], data[RECORD_KEY])
    lines = [
        "",
        f"[{RECORD_KEY}]",
        f"title = {protocol.toml_string(record['title'])}",
        f"state = {protocol.toml_string(record['state'])}",
    ]
    if record.get("kind") is not None:
        lines.append(f"kind = {protocol.toml_string(record['kind'])}")
    lines.append(f"labels = {_render_record_array(record.get('labels', []))}")
    lines.append(f"blocked_by = {_render_record_array(record.get('blocked_by', []))}")
    if record.get("parent") is not None:
        lines.append(f"parent = {protocol.toml_string(record['parent'])}")
    if record.get("origin") is not None:
        lines.append(f"origin = {protocol.toml_string(record['origin'])}")
    lines.append(f"created_at = {protocol.toml_string(record['created_at'])}")
    lines.append(f"updated_at = {protocol.toml_string(record['updated_at'])}")
    if record.get("closed_at") is not None:
        lines.append(f"closed_at = {protocol.toml_string(record['closed_at'])}")
    return lines


def render_block(data: Mapping[str, object], newline: str = "\n") -> str:
    """The canonical `aco` block interior for `data`:
    schema key order, TOML-safe strings, unquoted dates, ending in
    `newline` so a following fence line starts clean. Production caller:
    block-mode `cut`; there is no standalone validator."""
    lines = [f"version = {data['version']}"]
    lines.extend(
        f"{key} = {protocol.toml_string(data[key])}" for key in ("now", "next", "done_when")
    )
    lines.extend(_render_frozen_until(data))
    lines.extend(_render_scope(data))
    lines.extend(_render_size(data))
    lines.extend(_render_whole(data))
    lines.extend(_render_empty_slice_table(data))
    lines.extend(render_expectations(data))
    lines.extend(_render_slices(data))
    lines.extend(_render_record(data))
    return newline.join((*lines, ""))


def replace_block(body: str, located: LocatedBlock, data: Mapping[str, object]) -> str:
    """`body` with its one `aco` block's interior replaced by
    `render_block(data, located.newline)` -- pure, changing only that span
    and preserving every other byte, fence lines included."""
    return (
        body[: located.content_start]
        + render_block(data, located.newline)
        + body[located.content_end :]
    )


def carries_block(body: str) -> bool:
    """Whether `body` opens any `aco` fence at all, closed or not --
    a body without one is prose a fresh block goes below."""
    return bool(_fence_matches(body))


_SKELETON_PROJECTION: Mapping[str, object] = {
    "version": BLOCK_VERSION,
    "now": "",
    "next": "",
    "done_when": "",
}


def prose_above_fresh_block(prose: str, fields: Mapping[str, object]) -> str:
    """`prose`, kept byte for byte, above a fresh `aco` block holding
    `fields`, every projection key `fields` leaves out
    written empty; the bare block when `prose` is empty. The block follows
    one blank line below the prose, in the prose's own line ending."""
    newline = _first_line_ending(prose)
    block = render_block({**_SKELETON_PROJECTION, **fields}, newline)
    fence = f"```{BLOCK_FENCE_INFO}{newline}{block}```{newline}"
    if not prose:
        return fence
    last_line_end = "" if _line_ending(prose) else newline
    return f"{prose}{last_line_end}{newline}{fence}"


def _first_line_ending(text: str) -> str:
    """The line ending `text`'s first ended line carries, `\\n` when none."""
    return next(
        (ending for line in text.splitlines(keepends=True) if (ending := _line_ending(line))),
        "\n",
    )


def body_with_block_fields(body: str, fields: Mapping[str, object]) -> str:
    """`body` with each field of `fields` its one schema-valid `aco`
    block lacks written in, the block re-rendered canonically and every byte
    outside it kept -- `body` itself when it lacks none (ITEM-62). The one
    writer behind `item new`'s and `cut`'s block flags."""
    located = locate_block(body)
    lacking = {key: value for key, value in fields.items() if key not in located.data}
    if not lacking:
        return body
    return replace_block(body, located, {**located.data, **lacking})


def _block_field_text(key: str, value: object) -> str:
    """One block field's value as `render_block` writes it, scope canonical."""
    return _render_scope_array(value) if key == "scope" else protocol.toml_string(value)


def block_field_conflicts(body: str, fields: Mapping[str, object]) -> tuple[str, ...]:
    """One sentence per field of `fields` that `body`'s schema-valid block
    already holds with another value, naming both values: a
    flag never silently overrides, nor yields to, a piped block."""
    data = locate_block(body).data
    conflicts: list[str] = []
    for key, value in fields.items():
        flagged, piped = _block_field_text(key, value), _block_field_text(key, data.get(key, value))
        if flagged != piped:
            flag = f"--{key.replace('_', '-')}"
            conflicts.append(f"{flag} {flagged} contradicts the piped block's {key} = {piped}")
    return tuple(conflicts)


def missing_or_empty_sections(contract: Contract) -> tuple[str, ...]:
    """Every projection key a body-incomplete refusal names: an absent key
    and a fresh skeleton's empty string both count, even though both stay
    legitimate CONTRACT-column *presence* (`_contract_summary` is
    `None`-only for that column, matching the rule that a block
    skeleton still shows `Now, Next, Done when`)."""
    return tuple(name for name, value in contract_fields(contract) if not value)


def _slice_line_defects(slices: tuple[SliceRow, ...]) -> tuple[ContractDefect, ...]:
    """The rule wherever a body's shape is judged -- `check -`,
    `check`, `item new`/`item edit`: a slice title is
    one line, since `next` prints it inside a runnable `cut`, so every
    `protocol.is_display_control` character is a defect; a
    row's `done_when` keeps the same rule, since `cut` copies it into the
    child's one-line `done_when`. `board` and `next` keep
    reading a body stored before this rule, and `next` names such a row
    instead of printing its `cut` (`unprintable_slice_line_key`)."""
    return tuple(
        defect
        for position, row in enumerate(slices)
        for key, text in _slice_lines(row)
        if (defect := _slice_line_defect(position, row.index, key, text)) is not None
    )


def unprintable_slice_line_key(row: SliceRow) -> str | None:
    """The first of `row`'s one-line fields that breaks BODY-66, or `None`:
    `next` withholds the row's `cut` on it (NEXT-32), since a title would
    split the printed command and a `done_when` makes that `cut` refuse
    (CUT-39)."""
    return next(
        (key for key, text in _slice_lines(row) if _display_control_in(text) is not None),
        None,
    )


def _slice_lines(row: SliceRow) -> tuple[tuple[str, str | None], ...]:
    return tuple(zip(SLICE_LINE_KEYS, (row.title, row.done_when), strict=True))


def _display_control_in(text: str | None) -> str | None:
    return next(filter(protocol.is_display_control, text or ""), None)


def _slice_line_defect(
    position: int, index: int, key: str, text: str | None
) -> ContractDefect | None:
    breaking = _display_control_in(text)
    if breaking is None:
        return None
    field = f"slice[{position}].{key}"
    return ContractDefect(
        field,
        f"{field} of row {index} holds U+{ord(breaking):04X}; a slice {key} stays on one line",
    )


def slice_done_when_defect(located: LocatedBlock, row: SliceRow) -> str | None:
    """BODY-66 for the one row of `located` that `cut` selects,
    in the sentence `check -` prints for it: `cut` copies only
    that row's `done_when` into a child, so no other row's line can refuse
    the cut."""
    position = _block_slices(located.data).index(row)
    defect = _slice_line_defect(position, row.index, "done_when", row.done_when)
    return None if defect is None else body_defect_text(defect)


class BodyShapeVerdict(StrEnum):
    """Whether a body's own shape is one a builder can start from:
    the third state beyond `BodyReadState.VALID`/`MALFORMED` -- a
    schema-valid block that still leaves a required section unfilled.
    `check <item>` and `check -` both need to tell `malformed` from
    `incomplete` apart for their own `--json` `reason`, never by sniffing a
    defect sentence's own prefix."""

    VALID = BodyReadState.VALID.value
    MALFORMED = BodyReadState.MALFORMED.value
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class BodyShapeCheck:
    """One body's own shape verdict and defect sentences: the
    single read `check <item>` and `check -` both share, so neither
    writes a second rendering of `body_defect_text`'s or the incomplete
    sentence's own text."""

    verdict: BodyShapeVerdict
    defects: tuple[str, ...]


def body_shape_check(body: str, *, storage: Storage = Storage.GITHUB) -> BodyShapeCheck:
    """Every finding a body's own shape can carry without asking a forge
    anything -- malformed (one sentence per schema defect) or incomplete
    (one joined sentence) -- paired with the verdict a caller's `--json`
    `reason` reads. `storage` gates the one storage-specific extension,
    `[record]`."""
    parsed = parse_body(body, storage=storage)
    malformed = (
        parsed.contract.defects
        if parsed.read_state is BodyReadState.MALFORMED
        else _slice_line_defects(parsed.slices)
    )
    if malformed:
        defects = tuple(body_defect_text(defect) for defect in malformed)
        return BodyShapeCheck(BodyShapeVerdict.MALFORMED, defects)
    missing = missing_or_empty_sections(parsed.contract)
    if missing:
        return BodyShapeCheck(
            BodyShapeVerdict.INCOMPLETE, (f"body incomplete: {', '.join(missing)}",)
        )
    return BodyShapeCheck(BodyShapeVerdict.VALID, ())
