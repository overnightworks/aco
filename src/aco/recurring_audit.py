"""The recurring audits a repository declares in `.aco/board.toml`: the entry,
its anchor line and the pure due rule (`specs/next.spec.md`)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from . import protocol

ANCHOR_PHRASE = "audited through"
# The depth of the trunk walk an anchor is searched in.
MAX_LANDINGS = 5000
_ENTRY_KEYS = ("name", "label", "landings", "days", "run")


class Reason(StrEnum):
    """Why an audit is due, or `UNAVAILABLE` when it could not be judged (not due)."""

    LANDINGS = "landings"
    DAYS = "days"
    NO_ANCHOR = "no_anchor"
    ANCHOR_MALFORMED = "anchor_malformed"
    ANCHOR_OFF_TRUNK = "anchor_off_trunk"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class RecurringAudit:
    """One `[[audit]]` entry of the board configuration."""

    name: str
    label: str
    landings: int
    days: int
    run: str


class Landing(Protocol):
    """A first-parent trunk commit: its full sha and committer date."""

    @property
    def sha(self) -> str: ...

    @property
    def committed_at(self) -> datetime: ...


class LabelledIssue(Protocol):
    """An issue carrying an entry's label."""

    @property
    def number(self) -> int: ...

    @property
    def body(self) -> str: ...


@dataclass(frozen=True)
class Anchor:
    """The newest `audited through` line: `named` is the text after the prefix."""

    issue: int
    named: str

    @property
    def is_commit(self) -> bool:
        return protocol.COMMIT_PATTERN.fullmatch(self.named) is not None


@dataclass(frozen=True)
class Finding:
    """An entry's due verdict, or its `UNAVAILABLE` reading with the error's sentence."""

    entry: RecurringAudit
    reason: Reason
    anchor: Anchor | None = None
    landings_since: int | None = None
    days_since: int | None = None
    error: str | None = None

    @property
    def is_due(self) -> bool:
        return self.reason is not Reason.UNAVAILABLE


def _refusal(path: Path, index: int, sentence: str) -> protocol.ClaimError:
    return protocol.ClaimError(f"board configuration {path} audit entry {index} {sentence}")


def _unique_text(value: object, taken: set[str]) -> str | None:
    """`value` when it is non-empty text without surrounding space or a display
    control that `taken` does not hold."""
    if (
        isinstance(value, str)
        and value
        and value.strip() == value
        and not any(protocol.is_display_control(character) for character in value)
        and value not in taken
    ):
        return value
    return None


def _count(value: object, maximum: int | None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value if maximum is None or value <= maximum else None


def _parse_entry(
    table: dict[str, object], index: int, path: Path, names: set[str], labels: set[str]
) -> RecurringAudit:
    unknown = sorted(set(table) - set(_ENTRY_KEYS))
    if unknown:
        named = protocol.terminal_text(", ".join(unknown))
        raise _refusal(path, index, f"has unknown key {named}")
    missing = [key for key in _ENTRY_KEYS if key not in table]
    if missing:
        raise _refusal(path, index, f"is missing {', '.join(missing)}")
    name = _unique_text(table["name"], names)
    if name is None:
        raise _refusal(path, index, "name must be a unique non-empty name")
    label = _unique_text(table["label"], labels)
    if label is None or "," in label:
        raise _refusal(path, index, "label must be a unique non-empty label without a comma")
    landings = _count(table["landings"], MAX_LANDINGS)
    if landings is None:
        raise _refusal(path, index, f"landings must be a positive integer up to {MAX_LANDINGS}")
    days = _count(table["days"], None)
    if days is None:
        raise _refusal(path, index, "days must be a positive integer")
    run = table["run"]
    if not isinstance(run, str) or not run.strip():
        raise _refusal(path, index, "run must be non-empty text")
    return RecurringAudit(name, label, landings, days, run)


def parse_entries(raw: object, path: Path) -> tuple[RecurringAudit, ...]:
    """The entries of the configuration's `audit` value, `None` when absent;
    the first malformed one refuses by its position, counted from 1."""
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(table, dict) for table in raw):
        raise protocol.ClaimError(f"board configuration {path} audit must be an array of tables")
    entries: list[RecurringAudit] = []
    for index, table in enumerate(raw, start=1):
        entry = _parse_entry(
            table,
            index,
            path,
            {entry.name for entry in entries},
            {entry.label for entry in entries},
        )
        entries.append(entry)
    return tuple(entries)


def unavailable(entry: RecurringAudit, sentence: str) -> Finding:
    return Finding(entry, Reason.UNAVAILABLE, error=sentence)


def _last_anchor_line(body: str) -> str | None:
    named = [
        stripped.removeprefix(ANCHOR_PHRASE).strip()
        for stripped in map(str.strip, body.splitlines())
        if stripped.startswith(f"{ANCHOR_PHRASE} ")
    ]
    return named[-1] if named else None


def anchor_in(issues: Sequence[LabelledIssue]) -> Anchor | None:
    """The anchor in `issues`, newest first: the first issue holding an
    `audited through` line, its last such line."""
    for issue in issues:
        named = _last_anchor_line(issue.body)
        if named is not None:
            return Anchor(issue.number, named)
    return None


def _position(anchor: Anchor, trunk: Sequence[Landing]) -> int | None:
    return next((index for index, landing in enumerate(trunk) if landing.sha == anchor.named), None)


def is_off_trunk(anchor: Anchor, trunk: Sequence[Landing]) -> bool:
    """Whether `anchor` names a full commit that `trunk` does not hold."""
    return anchor.is_commit and _position(anchor, trunk) is None


def _due_reason(entry: RecurringAudit, landings_since: int, days_since: int) -> Reason | None:
    if landings_since >= entry.landings:
        return Reason.LANDINGS
    if landings_since >= 1 and days_since >= entry.days:
        return Reason.DAYS
    return None


def verdict(
    entry: RecurringAudit, anchor: Anchor | None, trunk: Sequence[Landing], today: date
) -> Finding | None:
    """`entry`'s due finding, `None` when not due. `trunk` is the first-parent
    landings, oldest first; the days count from the anchor commit's committer date."""
    if anchor is None:
        return Finding(entry, Reason.NO_ANCHOR)
    if not anchor.is_commit:
        return Finding(entry, Reason.ANCHOR_MALFORMED, anchor)
    position = _position(anchor, trunk)
    if position is None:
        return Finding(entry, Reason.ANCHOR_OFF_TRUNK, anchor)
    landings_since = len(trunk) - 1 - position
    days_since = (today - trunk[position].committed_at.astimezone(UTC).date()).days
    reason = _due_reason(entry, landings_since, days_since)
    if reason is None:
        return None
    return Finding(entry, reason, anchor, landings_since, days_since)
