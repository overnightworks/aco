"""The `land` command (`specs/land.spec.md`)."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from . import board, board_read, cmd_release, forge, github, policy, protocol, report


def _land_repeat_command(parsed: argparse.Namespace) -> tuple[str, ...]:
    """The `aco land` command line `parsed` came from, without its identity
    flags, for `cmd_release._holder_repeat_command`: `--head` and `--keep-worktree`
    stay, since a repeat without them would land an unreviewed head or
    remove the worktree the operator kept."""
    command = ["aco", "land", str(parsed.pull_request)]
    if parsed.head is not None:
        command.extend(["--head", parsed.head])
    if parsed.keep_worktree:
        command.append(cmd_release.KEEP_WORKTREE_FLAG)
    return tuple(command)


# A check name is GitHub's own external vocabulary -- a workflow job or a
# third-party status context's own title -- with no length limit this tool
# controls, unlike the internal path names `protocol.named_with_overflow_count`
# was written for (issue #405 review/gate finding): each name is truncated
# here before that same three-then-`and N more` grammar ever sees it, and the
# assembled sentence is capped again as a final backstop -- short enough that
# `cli.main`'s own `report.CLI_ERROR_PREFIX` still fits under the same 200-character
# printed-line budget (issue #405 round-4 finding) -- so several long check
# names can never print a refusal line past 200 characters.
LAND_CHECK_NAME_LENGTH_LIMIT = 40
LAND_QUALITY_CONFIG_PATH = Path("quality/config.toml")
LAND_QUALITY_VERDICT_CHECK = "quality / verdict"
LAND_REFUSAL_LINE_LENGTH_LIMIT = 200
LAND_REFUSAL_SENTENCE_LENGTH_LIMIT = LAND_REFUSAL_LINE_LENGTH_LIMIT - len(report.CLI_ERROR_PREFIX)


def _land_not_open_refusal(number: int) -> str:
    return f"pull request #{number} is not open; it cannot be landed"


def _land_not_mergeable_refusal(number: int, state: str) -> str:
    return f"pull request #{number} is not mergeable ({state})"


def _land_truncated_check_name(name: str) -> str:
    if len(name) <= LAND_CHECK_NAME_LENGTH_LIMIT:
        return name
    return name[: LAND_CHECK_NAME_LENGTH_LIMIT - 1] + "…"


def _land_bounded_refusal(sentence: str) -> str:
    """`sentence` as one bounded refusal line: a pull request's own text
    (a check name, a head's board configuration key) may carry a newline or
    a terminal escape, so it is shown as `next` shows foreign text (`\\n`,
    `\\x1b`) before the length cap applies (issues #505, #538)."""
    printable = board.terminal_text(sentence)
    if len(printable) <= LAND_REFUSAL_SENTENCE_LENGTH_LIMIT:
        return printable
    return printable[: LAND_REFUSAL_SENTENCE_LENGTH_LIMIT - 1] + "…"


def _land_pending_check_names(checks: tuple[forge.CheckRun, ...]) -> tuple[str, ...]:
    return tuple(
        _land_truncated_check_name(check.name) for check in checks if check.conclusion is None
    )


def _land_failed_check(checks: tuple[forge.CheckRun, ...]) -> forge.CheckRun | None:
    return next(
        (
            check
            for check in checks
            if check.conclusion is not None and check.conclusion != forge.CHECK_CONCLUSION_SUCCESS
        ),
        None,
    )


def _land_checks_refusal(number: int, checks: tuple[forge.CheckRun, ...]) -> str | None:
    """Why `aco land`'s preflight refuses on `checks` alone, or `None` when
    every one of them proves green (issue #405): no checks at all, a check
    still running, then a check that finished without success -- in that
    order, since a still-running check is not yet a failure."""
    if not checks:
        return f"pull request #{number} exposes no CI checks; cannot verify green CI"
    pending = _land_pending_check_names(checks)
    if pending:
        # Capped the same way `next`'s own `parallel:` line is (issue #348,
        # `protocol.named_with_overflow_count`): a pull request with many
        # still-running checks must never print a refusal past 200
        # characters (issue #405 review/gate finding) -- each name already
        # truncated by `_land_pending_check_names` before this grammar sees
        # it, `_land_bounded_refusal` a final backstop on the whole line.
        return _land_bounded_refusal(
            f"pull request #{number} has checks still running: "
            f"{protocol.named_with_overflow_count(pending)}; wait for every check to succeed"
        )
    failed = _land_failed_check(checks)
    if failed is not None:
        conclusion = failed.conclusion
        assert conclusion is not None  # `_land_failed_check` only returns a completed check.
        return _land_bounded_refusal(
            f"pull request #{number} has non-successful checks: "
            f"{_land_truncated_check_name(failed.name)} ({conclusion}); "
            "land only after every check succeeds"
        )
    return None


def _land_lacks_quality_verdict(checks: tuple[forge.CheckRun, ...]) -> bool:
    """Whether every check completed and none is the quality verdict: a
    check still running may yet be the verdict, so it is not missing."""
    return all(check.conclusion is not None for check in checks) and not any(
        check.name == LAND_QUALITY_VERDICT_CHECK for check in checks
    )


def _refuse_land_missing_quality_verdict(
    client: github.GitHubForge,
    readiness: forge.LandingReadiness,
    resolve_default_branch: Callable[[], str],
) -> None:
    """LANDCMD-43: where the default branch -- never the pull request head --
    holds the quality gate's configuration, presence alone adopts the gate
    and the verdict must be among the checks."""
    default_branch = resolve_default_branch()
    adopted = client.file_at_commit(LAND_QUALITY_CONFIG_PATH, default_branch) is not None
    if adopted and _land_lacks_quality_verdict(readiness.checks):
        raise protocol.ClaimUnavailableError(
            _land_bounded_refusal(
                f"pull request #{readiness.number} has no {LAND_QUALITY_VERDICT_CHECK} check; "
                f"{default_branch} adopts the quality gate ({LAND_QUALITY_CONFIG_PATH})"
            )
        )


def _refuse_land_readiness(
    client: github.GitHubForge,
    readiness: forge.LandingReadiness,
    resolve_default_branch: Callable[[], str],
) -> None:
    if not readiness.open:
        raise protocol.ClaimUnavailableError(_land_not_open_refusal(readiness.number))
    _refuse_land_missing_quality_verdict(client, readiness, resolve_default_branch)
    if readiness.mergeable_state != forge.MERGEABLE_STATE_CLEAN:
        raise protocol.ClaimUnavailableError(
            _land_not_mergeable_refusal(readiness.number, readiness.mergeable_state)
        )
    checks_refusal = _land_checks_refusal(readiness.number, readiness.checks)
    if checks_refusal is not None:
        raise protocol.ClaimUnavailableError(checks_refusal)


def _refuse_unreviewed_head(readiness: forge.LandingReadiness, reviewed_head: str | None) -> None:
    """`land --head` (issue #590): the head this preflight read -- the one
    the merge pins -- must be the commit the reviewers saw, so a push after
    their review never lands unseen."""
    if reviewed_head is None or readiness.head_sha.startswith(reviewed_head):
        return
    raise protocol.ClaimUnavailableError(
        f"pull request #{readiness.number} head is {readiness.head_sha}, "
        f"not the reviewed {reviewed_head}; review the new head before landing"
    )


def _land_governing_settings(config: board.BoardConfig) -> dict[str, object]:
    """The settings that decide where `aco land`'s own release half writes
    (issue #505): a pull request may change any other setting and still
    land, but never one of these under its own landing."""
    return {"storage": config.storage, "canonical_remote": config.canonical_remote}


def _land_head_config_refusal(
    number: int, head_text: str | None, landed: board.BoardConfig
) -> str | None:
    """Why the pull request head's board configuration `head_text` refuses
    `aco land` against the default branch's own `landed` one (LANDCMD-22..24),
    or `None` when it keeps every governing setting. The head's copy is
    only checked, never obeyed: `landed` alone governs this run (issue
    #505 R1)."""
    path = board.CONFIG_PATH
    cannot_release = "aco land cannot release its claim across that change"
    if head_text is None:
        return f"pull request #{number} removes {path}; {cannot_release}"
    try:
        head = board.parse_config(head_text, path)
    except protocol.ClaimError as error:
        return _land_bounded_refusal(f"pull request #{number} carries an invalid {path}: {error}")
    landed_settings = _land_governing_settings(landed)
    changed = next(
        (
            setting
            for setting, value in _land_governing_settings(head).items()
            if value != landed_settings[setting]
        ),
        None,
    )
    if changed is None:
        return None
    return f"pull request #{number} changes {changed} in {path}; {cannot_release}"


def _refuse_land_head_config(
    client: github.GitHubForge, readiness: forge.LandingReadiness, landed: board.BoardConfig
) -> None:
    head_text = client.file_at_commit(board.CONFIG_PATH, readiness.head_sha)
    refusal = _land_head_config_refusal(readiness.number, head_text, landed)
    if refusal is not None:
        raise protocol.ClaimUnavailableError(refusal)


def land_preflight(
    client: github.GitHubForge,
    claims_provider: Callable[[], protocol.ClaimState],
    context: policy.LandingCheckContext,
    number: int,
    parsed: argparse.Namespace,
) -> tuple[forge.Landing, board.Classification, forge.LandingReadiness]:
    """Every read-only precondition `aco land` proves before its first write
    (issue #405): a green, open, mergeable pull request classifying exactly
    one open item, or declaring itself issue-less -- reusing `check <pr>`'s
    own classification/claim/parent/closing rules (`policy.structural_classification`/
    `policy.classification_defect`) rather than a second copy of them.

    In order: the reviewed head `--head` names, readiness (neither a local
    git read), the pull request's own
    shape, its head's board configuration against this checkout's own
    (LANDCMD-22..24, issue #505), then the named item's live open state --
    LANDCMD-08 before claim validation (issue #405 review/gate finding) --
    then `claims_provider`,
    the one step that reads `refs/aco/state` locally, so a pull request this
    preflight would refuse on GitHub's own answers alone never pays for that
    read at all, and finally this session's own authorization against the
    exact claim just proven to exist (`cmd_release.authorize_releaser`, `release`'s
    own claimant/coordinator-override check, issue #405 review finding): a
    claim held by another agent or role refuses here, before the merge,
    rather than only once the delegated `release --merged` step runs after
    it. `cli._cmd_land`'s own entry already validated `--coordinator-override`'s
    role (issue #405 round-4 finding 1) -- before this preflight, and before
    the fresh/rerun split that skips it entirely on a rerun -- so this
    function itself never repeats that check.
    """
    readiness = client.landing_readiness(number)
    _refuse_unreviewed_head(readiness, parsed.head)
    _refuse_land_readiness(client, readiness, lambda: context.run.default_branch)
    detail = client.landing(number)
    structural = policy.structural_classification(context, detail)
    if isinstance(structural, board.ClassificationDefect):
        raise protocol.ClaimUnavailableError(f"pull request #{number} {structural.message}")
    _refuse_land_head_config(client, readiness, context.run.config)
    if isinstance(structural, board.WorkItemClassification):
        reference = board_read.fetch_issue_reference(client, structural.item.number)
        if reference.state is not forge.ItemState.OPEN:
            raise protocol.ClaimUnavailableError(
                f"work item #{structural.item.number} is not open; it cannot be landed"
            )
    observed = claims_provider()
    defect = policy.classification_defect(
        context, tuple(observed.claims.values()), detail, structural
    )
    if defect is not None:
        raise protocol.ClaimUnavailableError(f"pull request #{number} {defect.message}")
    identity: protocol.ClaimIdentity = (
        protocol.IssueIdentity(structural.item.number)
        if isinstance(structural, board.WorkItemClassification)
        else protocol.LaneIdentity()
    )
    selected = cmd_release.select_release_claim(
        argparse.Namespace(branch=None, claim_id=None),
        observed,
        identity,
        detail.source_branch,
        context.storage,
    )
    cmd_release.authorize_releaser(parsed, selected, _land_repeat_command(parsed))
    return detail, structural, readiness
