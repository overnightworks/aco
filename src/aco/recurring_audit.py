"""The recurring audits a repository declares in `.aco/board.toml`: the entry,
its anchor line and the pure due rule (`specs/next.spec.md`)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Protocol

from . import protocol

ANCHOR_LINE_PREFIX = "audited through "


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


def unavailable(entry: RecurringAudit, sentence: str) -> Finding:
    return Finding(entry, Reason.UNAVAILABLE, error=sentence)


def _last_anchor_line(body: str) -> str | None:
    named = [
        stripped.removeprefix(ANCHOR_LINE_PREFIX).strip()
        for stripped in map(str.strip, body.splitlines())
        if stripped.startswith(ANCHOR_LINE_PREFIX)
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
