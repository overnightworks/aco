"""Remove landed lanes safely and report why a merged lane must stay."""

from dataclasses import replace

import pytest
from release_cleanup_world import (
    LISTING_ARGUMENTS,
    MERGED,
    MERGED_BRANCH_KEPT,
    OWN_KEYS,
    PREFIX,
    RELEASE_COMMAND,
    Absent,
    CleanupCase,
    CleanupCheck,
    Intervention,
    LaunchFailure,
    LaunchIntervention,
    Phase,
    Present,
    rendered,
)

from aco import workboard

PAST_HEAD = CleanupCase(
    intervention=Intervention.COMMIT_BEFORE,
    stdout=PREFIX + "worktree: kept -- not merged into the default branch\n",
    worktree_exists=True,
    branch=Present("{raced}"),
    keys=Present(OWN_KEYS),
    own_section=Present(OWN_KEYS),
    intervention_tip=Present("{raced}"),
    intervention_parent=Present("{head}"),
)
SECTION_KEPT = CleanupCase(keys=Present(OWN_KEYS), own_section=Present(OWN_KEYS))
CONFIG_TIMEOUT = replace(
    SECTION_KEPT,
    stdout=PREFIX
    + "worktree: removed; branch.{lane} section kept -- git failure: git config timed out\n",
)
DELETE_ARGV = (("update-ref", "-d", "refs/heads/{lane}", "{head}"),)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(PAST_HEAD, id="land-with-the-lane-past-the-pinned-head"),
        pytest.param(
            CleanupCase(command=RELEASE_COMMAND, premerge=workboard.MergeMethod.SQUASH),
            id="release-rerun-on-the-recorded-head",
        ),
        pytest.param(
            replace(PAST_HEAD, command=RELEASE_COMMAND, premerge=workboard.MergeMethod.SQUASH),
            id="release-rerun-past-the-recorded-head",
        ),
    ],
)
def test_a_squashed_lane_goes_only_on_its_recorded_head(
    case: CleanupCase, cleanup_check: CleanupCheck
) -> None:
    """Keep land's Accepted residual; reruns use the recorded squash head.

    Spec: REL-43, E-REL-20, LANDCMD-18.
    """
    cleanup_check(case)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(CleanupCase(), id="clean"),
        pytest.param(
            replace(
                PAST_HEAD,
                intervention=Intervention.COMMIT_WINDOW,
                phase=Phase.WINDOW,
                worktree_exists=False,
                stdout=PREFIX
                + "worktree: removed; branch kept -- git failure: error: cannot lock ref "
                "'refs/heads/{lane}': is at {raced} but expected {head}\n",
            ),
            id="commit-raced-past-the-head",
        ),
        pytest.param(
            replace(
                SECTION_KEPT,
                intervention=Intervention.LIST_REFUSED,
                stdout=PREFIX + "worktree: removed; branch.{lane} section kept -- git failure: "
                "fatal: the listing failed\n",
            ),
            id="configuration-listing-refused",
        ),
        pytest.param(
            replace(
                SECTION_KEPT,
                intervention=Intervention.LOCK,
                phase=Phase.WINDOW,
                locked=True,
                stdout=PREFIX + "worktree: removed; branch.{lane} section kept -- git failure: "
                "error: could not lock config file .git/config\n",
            ),
            id="configuration-locked",
        ),
        pytest.param(
            replace(
                SECTION_KEPT,
                intervention=LaunchIntervention(LaunchFailure.LAUNCH_FAILS, ("update-ref", "-d")),
                branch=Present("{head}"),
                launches=DELETE_ARGV,
                stdout=PREFIX + "worktree: removed; branch kept -- git failure: "
                "git failed to launch: permission denied\n",
            ),
            id="deletion-failed-to-start",
        ),
        pytest.param(
            replace(
                SECTION_KEPT,
                intervention=LaunchIntervention(LaunchFailure.TIMES_OUT, ("update-ref", "-d")),
                branch=Present("{head}"),
                launches=DELETE_ARGV,
                stdout=PREFIX + "worktree: removed; branch unknown -- git update-ref timed out; "
                "check git branch --list {lane}\n",
            ),
            id="deletion-timed-out",
        ),
        pytest.param(
            replace(
                CONFIG_TIMEOUT,
                intervention=LaunchIntervention(LaunchFailure.TIMES_OUT, LISTING_ARGUMENTS),
                launches=(
                    ("config", "--local", "--null", "--name-only", "--get-regexp", r"^branch\."),
                ),
            ),
            id="configuration-listing-timed-out",
        ),
        pytest.param(
            replace(
                CONFIG_TIMEOUT,
                intervention=LaunchIntervention(
                    LaunchFailure.TIMES_OUT,
                    ("config", "--local", "--remove-section", "branch.{lane}"),
                ),
                launches=(("config", "--local", "--remove-section", "branch.{lane}"),),
            ),
            id="section-removal-timed-out",
        ),
        pytest.param(
            replace(
                SECTION_KEPT,
                intervention=Intervention.RECREATE,
                phase=Phase.BRANCH_EXISTS,
                existed_before=Absent(),
                lane_status=Absent(),
                branch=Present("{head}"),
            ),
            id="same-name-branch-recreated",
        ),
        pytest.param(
            CleanupCase(
                intervention=Intervention.DOTTED,
                phase=Phase.WINDOW,
                keys=Present(("branch.{lane}.x.remote",)),
                intervention_keys=Present(("branch.{lane}.x.remote",)),
            ),
            id="dotted-sibling-without-an-own-section",
        ),
        pytest.param(
            CleanupCase(
                intervention=Intervention.LATIN1,
                phase=Phase.WINDOW,
                keys=Present(("branch.other.description",)),
                intervention_keys=Present((*OWN_KEYS, "branch.other.description")),
                latin1=True,
            ),
            id="another-branch-value-not-utf-8",
        ),
    ],
)
def test_a_squashed_lane_branch_goes_by_compare_and_delete(
    case: CleanupCase, cleanup_check: CleanupCheck
) -> None:
    """Delete only the pinned branch and its own configuration section.

    Spec: REL-34, REL-42, REL-44, REL-45, REL-46, E-REL-21, E-REL-22, E-REL-23.
    """
    cleanup_check(case)


@pytest.mark.parametrize(
    "case",
    [
        *rendered("clean", "removed", MERGED),
        *rendered(
            "branch-deletion-refused",
            "removed; branch kept -- git failure: error: branch not fully merged",
            replace(MERGED_BRANCH_KEPT, intervention=Intervention.DELETE_REFUSED),
        ),
        pytest.param(
            replace(
                MERGED_BRANCH_KEPT,
                intervention=LaunchIntervention(LaunchFailure.LAUNCH_FAILS, ("branch", "-d")),
                launches=(("branch", "-d", "{lane}"),),
                stdout=PREFIX + "worktree: removed; branch kept -- git failure: "
                "git failed to launch: permission denied\n",
            ),
            id="branch-deletion-failed-to-start",
        ),
        pytest.param(
            replace(
                MERGED_BRANCH_KEPT,
                intervention=LaunchIntervention(LaunchFailure.TIMES_OUT, ("branch", "-d")),
                launches=(("branch", "-d", "{lane}"),),
                stdout=PREFIX + "worktree: removed; branch unknown -- git branch timed out; "
                "check git branch --list {lane}\n",
            ),
            id="branch-deletion-timed-out",
        ),
    ],
)
def test_a_merged_lane_branch_goes_by_branch_delete(
    case: CleanupCase, cleanup_check: CleanupCheck
) -> None:
    """Remove a merged worktree and report the branch deletion's result.

    Spec: REL-25, REL-34, REL-35, REL-45, E-REL-08, E-REL-16, E-REL-17, E-REL-22.
    """
    cleanup_check(case)


KEPT = replace(
    MERGED,
    worktree_exists=True,
    branch=Present("{head}"),
    keys=Present(OWN_KEYS),
    own_section=Present(OWN_KEYS),
)


@pytest.mark.parametrize(
    "case",
    [
        *rendered(
            "dirty",
            "kept -- dirty",
            replace(
                KEPT,
                intervention=Intervention.DIRTY,
                lane_status=Present("?? scratch.txt\n"),
            ),
        ),
        *rendered(
            "checked-out-elsewhere",
            "kept -- branch checked out elsewhere",
            replace(
                KEPT,
                intervention=Intervention.CHECKED_ELSEWHERE,
                worktree_exists=False,
                lane_status=Absent(),
                landing_branch="{lane}",
                workplace="{bystander}",
            ),
        ),
        *rendered(
            "git-failure",
            "kept -- git failure: fatal: cannot change to 'gone': No such file or directory",
            replace(KEPT, intervention=Intervention.GIT_FAILURE),
        ),
        *rendered(
            "foreign-worktree-git-failure",
            "kept -- git failure: fatal: broken",
            replace(KEPT, intervention=Intervention.FOREIGN_COMMIT_READ_FAILS),
        ),
    ],
)
def test_a_merged_lane_is_kept_for_the_reason_it_cannot_go(
    case: CleanupCase, cleanup_check: CleanupCheck
) -> None:
    """Keep a merged lane's worktree and branch when cleanup must not remove them.

    Spec: REL-28, REL-31, REL-32, REL-35, E-REL-11, E-REL-14, E-REL-15, E-REL-17.
    """
    cleanup_check(case)


NO_LINKED_WORKTREE = (
    "kept -- no linked worktree on {lane} in this checkout; "
    "run aco release 72 --merged 12 --branch {lane} in the checkout that holds it"
)


@pytest.mark.parametrize(
    "case",
    [
        *rendered(
            "keep-worktree-flag",
            "kept -- --keep-worktree was given",
            replace(KEPT, command=(*RELEASE_COMMAND, "--keep-worktree")),
        ),
        *rendered(
            "ran-from-inside",
            "kept -- release ran from inside it",
            replace(KEPT, intervention=Intervention.INSIDE, workplace="{worktree}"),
        ),
        *rendered(
            "no-linked-worktree",
            NO_LINKED_WORKTREE,
            replace(
                KEPT,
                intervention=Intervention.NO_WORKTREE,
                worktree_exists=False,
                lane_status=Absent(),
            ),
        ),
        *rendered(
            "not-merged",
            "kept -- not merged into the default branch",
            replace(
                PAST_HEAD,
                command=RELEASE_COMMAND,
                premerge=workboard.MergeMethod.MERGE,
                worktree_exists=True,
            ),
        ),
    ],
)
def test_a_merged_lane_is_kept_when_the_run_declines_to_remove_it(
    case: CleanupCase, cleanup_check: CleanupCheck
) -> None:
    """Keep the lane when the run's location, flag or merge state prevents cleanup.

    Spec: REL-26, REL-27, REL-29, REL-30, REL-35, REL-52,
    E-REL-09, E-REL-10, E-REL-12, E-REL-13, E-REL-24.
    """
    cleanup_check(case)
