"""Remove a merged lane whose worktree holds only a git-ignored file."""

from dataclasses import replace
from functools import partial

import pytest
from release_cleanup_world import (
    MERGED,
    CleanupCase,
    CleanupCheck,
    CleanupIntervention,
    rendered,
)


class OnlyAnIgnoredFile:
    def install(self, target: CleanupIntervention) -> None:
        target.before(partial(self.write, target))

    @staticmethod
    def write(target: CleanupIntervention) -> None:
        (target.clone / ".git/info").mkdir()
        (target.clone / ".git/info/exclude").write_text("*.cache\n")
        (target.world.lane / "notes.cache").write_text("only in the worktree\n")


@pytest.mark.parametrize(
    "case",
    rendered("only-an-ignored-file", "removed", replace(MERGED, intervention=OnlyAnIgnoredFile())),
)
def test_a_merged_lane_holding_only_an_ignored_file_is_removed(
    case: CleanupCase, cleanup_check: CleanupCheck
) -> None:
    """Remove the worktree: a git-ignored file is no dirt.

    Spec: REL-25, REL-28.
    """
    cleanup_check(case)
