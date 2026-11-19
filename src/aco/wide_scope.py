"""The wide-scope rule of a claim: the conditions under which a scope is too wide to claim
without a stated reason."""

from dataclasses import dataclass
from enum import StrEnum

WIDE_SCOPE_PATH_LIMIT = 3
WIDE_SCOPE_SHARE_LIMIT = 0.25
# A tiny repository must not trip the share condition.
WIDE_SCOPE_SHARE_FLOOR = 12


class WideScopeReason(StrEnum):
    """Which of the three wide-scope conditions tripped -- named so a
    refusal can print the one that actually fired instead of restating the
    whole rule."""

    PATH_COUNT = "path_count"
    DIRECTORY = "directory"
    SHARE = "share"


@dataclass(frozen=True)
class WideScopeTrip:
    """The tripped condition, plus the numbers it was judged against -- a
    refusal renders these instead of recomputing them."""

    reason: WideScopeReason
    path_count: int
    directories: tuple[str, ...]
    covered_file_count: int
    versioned_file_count: int


def wide_scope_trip(
    scope: tuple[str, ...],
    *,
    directories: tuple[str, ...],
    covered_file_count: int,
    versioned_file_count: int,
) -> WideScopeTrip | None:
    """Which wide-scope condition fires first, in the rule's own priority
    order -- more than three paths, then any directory, then, once the
    repository has at least `WIDE_SCOPE_SHARE_FLOOR` versioned files, more
    than a quarter of them -- or `None` when scope is not wide."""

    def trip(reason: WideScopeReason) -> WideScopeTrip:
        return WideScopeTrip(
            reason, len(scope), directories, covered_file_count, versioned_file_count
        )

    if len(scope) > WIDE_SCOPE_PATH_LIMIT:
        return trip(WideScopeReason.PATH_COUNT)
    if directories:
        return trip(WideScopeReason.DIRECTORY)
    if versioned_file_count < WIDE_SCOPE_SHARE_FLOOR:
        return None
    if covered_file_count / versioned_file_count > WIDE_SCOPE_SHARE_LIMIT:
        return trip(WideScopeReason.SHARE)
    return None
