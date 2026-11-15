"""Remove a merged lane whose worktree holds only a git-ignored file."""

from dataclasses import replace
from functools import partial
from pathlib import Path

import pytest
from test_cmd_release_cleanup import (
    MERGED,
    CleanupCase,
    CleanupCheck,
    CleanupIntervention,
    rendered,
    verify_cleanup,
)


class OnlyAnIgnoredFile:
    def install(self, target: CleanupIntervention) -> None:
        target.before(partial(self.write, target))

    @staticmethod
    def write(target: CleanupIntervention) -> None:
        (target.clone / ".git/info").mkdir()
        (target.clone / ".git/info/exclude").write_text("*.cache\n")
        (target.world.lane / "notes.cache").write_text("only in the worktree\n")


@pytest.fixture
def ignored_check(
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> CleanupCheck:
    return partial(
        verify_cleanup,
        github_clone=github_clone,
        bare_remote=bare_remote,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )


@pytest.mark.parametrize(
    "case",
    rendered("only-an-ignored-file", "removed", replace(MERGED, intervention=OnlyAnIgnoredFile())),
)
def test_a_merged_lane_holding_only_an_ignored_file_is_removed(
    case: CleanupCase, ignored_check: CleanupCheck
) -> None:
    """Remove the worktree: a git-ignored file is no dirt.

    Spec: REL-25, REL-28.
    """
    ignored_check(case)
