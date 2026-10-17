"""The `land` command (`specs/land.spec.md`)."""

from __future__ import annotations

import argparse
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, cast

from . import (
    board,
    board_read,
    body,
    checkout,
    cmd_release,
    forge,
    github,
    policy,
    protocol,
    report,
    store,
)
from .session import RunContext

_LAND_GITHUB_ONLY_REFUSAL = (
    "aco land is a github command; storage = state-ref has no pull requests to land"
)
_LAND_SELF_PACKAGE_NAME = "agent-coordination"
_LAND_REINSTALL_LINE = "reinstall: uv tool install --force --from . agent-coordination"


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
# `report.render_error`'s `CLI_ERROR_PREFIX` still fits under the same 200-character
# printed-line budget (issue #405 round-4 finding) -- so several long check
# names can never print a refusal line past 200 characters.
_LAND_CHECK_NAME_LENGTH_LIMIT = 40
_LAND_QUALITY_CONFIG_PATH = Path("quality/config.toml")
_LAND_QUALITY_VERDICT_CHECK = "quality / verdict"
_LAND_REFUSAL_LINE_LENGTH_LIMIT = 200
_LAND_REFUSAL_SENTENCE_LENGTH_LIMIT = _LAND_REFUSAL_LINE_LENGTH_LIMIT - len(report.CLI_ERROR_PREFIX)


def _land_not_open_refusal(number: int) -> str:
    return f"pull request #{number} is not open; it cannot be landed"


def _land_not_mergeable_refusal(number: int, state: str) -> str:
    return f"pull request #{number} is not mergeable ({state})"


def _land_truncated_check_name(name: str) -> str:
    if len(name) <= _LAND_CHECK_NAME_LENGTH_LIMIT:
        return name
    return name[: _LAND_CHECK_NAME_LENGTH_LIMIT - 1] + "…"


def _land_bounded_refusal(sentence: str) -> str:
    """`sentence` as one bounded refusal line: a pull request's own text
    (a check name, a head's board configuration key) may carry a newline or
    a terminal escape, so it is shown as `next` shows foreign text (`\\n`,
    `\\x1b`) before the length cap applies (issues #505, #538)."""
    printable = board.terminal_text(sentence)
    if len(printable) <= _LAND_REFUSAL_SENTENCE_LENGTH_LIMIT:
        return printable
    return printable[: _LAND_REFUSAL_SENTENCE_LENGTH_LIMIT - 1] + "…"


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
        check.name == _LAND_QUALITY_VERDICT_CHECK for check in checks
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
    adopted = client.file_at_commit(_LAND_QUALITY_CONFIG_PATH, default_branch) is not None
    if adopted and _land_lacks_quality_verdict(readiness.checks):
        raise protocol.ClaimUnavailableError(
            _land_bounded_refusal(
                f"pull request #{readiness.number} has no {_LAND_QUALITY_VERDICT_CHECK} check; "
                f"{default_branch} adopts the quality gate ({_LAND_QUALITY_CONFIG_PATH})"
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


def _land_preflight(
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
    `policy.classification_defect`) rather than a second copy of them. Dependency
    listings must match the readiness head that `--head` verified and the merge pins.

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
    it. `run`'s own entry already validated `--coordinator-override`'s
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
        context,
        tuple(observed.claims.values()),
        detail,
        structural,
        expected_head=readiness.head_sha,
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


def _land_merge_body(title: str, body: str, classification: board.Classification) -> str:
    """The merge commit message `aco land` composes itself (issue #405,
    Befund 42 on #310): the pull request's own body with its classification
    line removed, then that classification, in the trunk's own trailer
    grammar, as the message's own last line -- so the trailer a later trunk
    walk reads through git's own trailer parsing is never wherever the pull
    request body happened to put it. Git reads trailers from the last
    paragraph only, so a body already ending in a trailer block (a
    `Co-Authored-By:` line) takes the classification into that block
    rather than behind a blank line that would orphan it -- but only where
    git then reads that block's trailers and the classification both, a
    question asked of the composed message itself: git reading the body
    alone skips a trailing comment line and still finds the trailer block
    above it, but once joined that comment line no longer ends the message,
    and git reads it with the classification as the last paragraph instead
    (issue #594)."""
    without_classification = board.body_without_classification(body)
    trailer = board.land_trunk_trailer(classification)
    if not without_classification:
        return f"{trailer}\n"
    joined = f"{without_classification}\n{trailer}"
    body_trailers = checkout.message_trailers(f"{title}\n\n{without_classification}\n")
    # Read as git reads it: a configured `trailer.<token>.key` renames it.
    classification_trailers = checkout.message_trailers(f"{title}\n\n{trailer}\n")
    joined_keeps_every_trailer = bool(body_trailers) and checkout.message_trailers(
        f"{title}\n\n{joined}\n"
    ) == (*body_trailers, *classification_trailers)
    if joined_keeps_every_trailer:
        return f"{joined}\n"
    return f"{without_classification}\n\n{trailer}\n"


def _land_merge_method(
    pinned: board.MergeMethod | None, client: github.GitHubForge, number: int, branch: str
) -> board.MergeMethod:
    """The method `aco land` merges pull request `number` into `branch` with
    (issues #578, #615): the board configuration's own pin, refused where
    the forge's allowed methods exclude it; otherwise a merge commit wherever
    the forge allows one, and a squash where it allows a squash but no merge
    commit -- never a rebase, so a forge allowing no method at all, or only a
    rebase to an unpinned land, refuses."""
    allowed = _forge_allowed_merge_methods(client, number, branch)
    if pinned is not None and allowed:
        if pinned not in allowed:
            allowed_list = ", ".join(
                method.value for method in board.MergeMethod if method in allowed
            )
            raise protocol.ClaimUnavailableError(
                f"board.toml merge_method {pinned.value} is not allowed on {branch}: "
                f"GitHub allows {allowed_list}"
            )
        return pinned
    for method in (board.MergeMethod.MERGE, board.MergeMethod.SQUASH):
        if method in allowed:
            return method
    raise protocol.ClaimUnavailableError(f"GitHub allows no merge method aco can use on {branch}")


def _forge_allowed_merge_methods(
    client: github.GitHubForge, number: int, branch: str
) -> frozenset[board.MergeMethod]:
    """Every method the forge allows on `branch`: the repository's own
    settings -- every method where it withholds them from a token without
    push rights, refused before any write unless they allow one `aco land`
    can use -- narrowed by each rule on `branch` (LANDCMD-42), since GitHub
    refuses a method any one of them excludes."""
    settings = client.allowed_merge_methods()
    allowed = frozenset(board.MergeMethod) if settings is None else settings
    if not allowed & board.LANDING_MERGE_METHODS:
        raise protocol.ClaimUnavailableError(
            f"pull request #{number} cannot land: this repository allows neither a merge commit "
            "nor a squash merge"
        )
    for rule in client.branch_merge_rules(branch):
        allowed &= rule
    return allowed


def _land_merge_title(method: board.MergeMethod, detail: forge.Landing) -> str:
    """A merge commit's own title, or a squash commit's: the pull request
    title plus `(#<n>)`, the convention a squash-only history reads."""
    if method is board.MergeMethod.SQUASH:
        return f"{detail.title} (#{detail.number})"
    return f"Merge pull request #{detail.number}"


def _land_merge(
    client: github.GitHubForge,
    detail: forge.Landing,
    readiness: forge.LandingReadiness,
    classification: board.Classification,
    method: board.MergeMethod,
) -> str:
    title = _land_merge_title(method, detail)
    try:
        return client.merge_landing(
            detail.number,
            head_sha=readiness.head_sha,
            method=method,
            title=title,
            body=_land_merge_body(title, detail.body, classification),
        )
    except forge.ForgeMergeConflictError as error:
        raise protocol.ClaimUnavailableError(
            f"pull request #{detail.number} changed while it was checked; re-run land"
        ) from error
    except forge.ForgeMergeRefusedError as error:
        raise protocol.ClaimUnavailableError(
            f"GitHub refused the merge of pull request #{detail.number}: "
            f"{board.terminal_text(str(error))}"
        ) from error


_LandStepResult = TypeVar("_LandStepResult")


def _land_step(
    number: int, sha: str, step: str, action: Callable[[], _LandStepResult]
) -> _LandStepResult:
    """Every step `aco land` runs once its merge already landed (issue
    #405): a failure here never means "not merged" -- the merge already
    happened -- so it reports the one ruled recovery line instead of the
    generic refusal an earlier precondition would print. A rerun starts
    `run` over from the top, finds the pull request already merged,
    and resumes here without a second merge. The failure is Git's or the
    forge's own text, so its display controls print escaped and the
    recovery stays one line."""
    try:
        return action()
    except protocol.ClaimError as error:
        raise protocol.ClaimUnavailableError(
            f"MERGED pull request #{number} as {sha}; follow-up incomplete: {step} "
            f"({board.terminal_text(str(error))}); re-run aco land {number}"
        ) from error


def _land_release_routing(
    classification: board.Classification | None, merge_sha: str, context: RunContext
) -> int | None:
    """The issue `aco land`'s own delegated `release --merged` call routes
    to (issue #405 point 4): a fresh merge reuses the classification this
    same run's own preflight already verified, never a re-read of the pull
    request's own mutable body. `classification` is `None` only for a rerun
    against a pull request `run` found already merged -- preflight
    never ran this time -- so this reads the merge commit's own trailer
    instead, exactly as `cmd_release._verify_merged_release` does (issue #397, Befund
    41): the same authority a lane release itself checks, never the pull
    request's `body`, which stays mutable long after the merge. Runs inside
    the `release` step's own `_land_step` (issue #405 review finding), so a
    defect here -- an edited body's classification long gone from the merge
    commit's own history -- prints the ruled `MERGED ... follow-up
    incomplete: release; re-run aco land <n>` line, never a bare refusal."""
    if classification is not None:
        if isinstance(classification, board.WorkItemClassification):
            return classification.item.number
        return None
    landings = checkout.trunk_landings(
        context.fetched_default_branch_ref(),
        board_read.TRUNK_LANDING_DEPTH,
        directory=context.toplevel,
    )
    landing = next((entry for entry in landings if entry.sha == merge_sha), None)
    trunk_classification = None if landing is None else landing.classification
    if isinstance(trunk_classification, board.TrunkWorkItemClassification):
        return trunk_classification.numbers[0]
    if isinstance(trunk_classification, board.NoItemClassification):
        return None
    raise protocol.ClaimUnavailableError(
        f"merge commit {merge_sha} carries no `Work-Item:` or `No-Item:` trailer"
    )


def _land_release(
    parsed: argparse.Namespace,
    context: RunContext,
    issue: int | None,
    branch: str,
) -> cmd_release.ReleaseEnding:
    """`aco land`'s own delegated call into the existing `release --merged`
    path (issue #405): never a second copy of its close/release/report/
    cleanup -- `--branch` selects the lane by name without requiring this
    checkout to be on it: the release may run from the coordinator's primary
    checkout, exactly where `land` runs from. Calls `cmd_release.release_transition` directly, never
    `cmd_release.run` (issue #425): `land` needs a raised `ClaimError` here so
    `_land_step` can convert it into its own ruled `MERGED ... follow-up
    incomplete: release` line, not `cmd_release.run`'s own caught-and-printed
    `--json` refusal, which `land` never uses (`json=False` above) and
    would otherwise print its sentence a second time. The release reads
    through a fresh `context` (issue #457 proof 6): the fast-forward just
    wrote the landed trunk into this very checkout, so the configuration
    and forge read before it no longer answer for it."""
    release_parsed = argparse.Namespace(
        issue=issue,
        agent=parsed.agent,
        role=parsed.role,
        branch=branch,
        merged=str(parsed.pull_request),
        abandoned=None,
        claim_id=None,
        coordinator_override=parsed.coordinator_override,
        keep_worktree=parsed.keep_worktree,
        # `land` has no `--json` mode of its own (specs/land.spec.md): the
        # delegated release path always reports in text, exactly as every
        # other line `land` itself prints does.
        json=False,
        repo=parsed.repo,
    )
    return cmd_release.release_transition(release_parsed, context.fresh(), branch)


def _land_is_own_repository(toplevel: Path) -> bool:
    """Whether `toplevel` is this very package's own repository (issue
    #405): `land`'s own reinstall reminder applies only there -- landing in
    any other repository this tool coordinates leaves nothing to
    reinstall."""
    try:
        with (toplevel / "pyproject.toml").open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        return False
    project = data.get("project")
    return isinstance(project, dict) and project.get("name") == _LAND_SELF_PACKAGE_NAME


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`aco land <pr>` (issue #405): preflight every ruled precondition
    read-only, merge with a pinned head sha and a commit message this tool
    composes itself, delete the merged branch, fast-forward this checkout's
    own default branch, then run the existing `release --merged` path
    unchanged. A pull request `landing` already finds merged -- a resumed
    run after an earlier step failed -- skips preflight and the merge
    itself entirely: `merge_landing` never runs twice for the same pull
    request. `--coordinator-override`'s own role is validated here, at
    entry, before that fresh/rerun split and before any read (issue #405
    round-4 finding 1): a rerun skips `_land_preflight` entirely, so a
    check placed only there left a rerun free to delete the branch and
    fast-forward -- and `cmd_release.release_transition` free to close the item -- on a bare
    `--coordinator-override` with no coordinator role behind it."""
    toplevel = context.toplevel
    config = context.config
    if config.storage is not body.Storage.GITHUB:
        raise protocol.ClaimUnavailableError(_LAND_GITHUB_ONLY_REFUSAL)
    if parsed.coordinator_override:
        protocol.require_coordinator_override(parsed.role)
    client = cast(github.GitHubForge, context.forge)
    number = parsed.pull_request
    repository = client.repository.path
    detail = client.landing(number)
    classification: board.Classification | None
    if detail.merged:
        assert detail.merge_commit is not None  # `merged` is true; github.py guarantees this.
        merge_sha = detail.merge_commit
        checkout.refuse_unlandable_checkout(context.default_branch, directory=toplevel)
        # A rerun: this run's own preflight never ran, so it never verified a
        # classification -- `_land_release_routing` reads the merge commit's
        # own trailer instead (issue #405 point 4).
        classification = None
    else:

        def claims_provider() -> protocol.ClaimState:
            # `store.peek_state`, never `RunContext.observation`'s
            # `fetch_state` (issue #405 review/gate finding): a pull
            # request this preflight goes on to refuse must anchor no ref
            # and stamp no lineage -- the same read-only requirement
            # `cmd_reset._reset_observation` already carries for `reset`.
            observed = store.peek_state(worktree=context.toplevel, remote=context.canonical_remote)
            protocol.require_state_ref(observed)
            return observed

        check_context = policy.LandingCheckContext(context, repository, config.storage)
        detail, classification, readiness = _land_preflight(
            client, claims_provider, check_context, number, parsed
        )
        checkout.refuse_unlandable_checkout(context.default_branch, directory=toplevel)
        method = _land_merge_method(config.merge_method, client, number, context.default_branch)
        merge_sha = _land_merge(client, detail, readiness, classification, method)
    _land_step(
        number, merge_sha, "delete-branch", lambda: client.delete_branch(detail.source_branch)
    )
    _land_step(
        number,
        merge_sha,
        "fast-forward",
        lambda: checkout.fast_forward_default_branch(
            context.fetched_default_branch_ref(), directory=toplevel
        ),
    )
    ending = _land_step(
        number,
        merge_sha,
        "release",
        lambda: _land_release(
            parsed,
            context,
            _land_release_routing(classification, merge_sha, context),
            detail.source_branch,
        ),
    )
    # The run whose release succeeded already printed it (LANDCMD-38).
    if ending is cmd_release.ReleaseEnding.RELEASED and _land_is_own_repository(toplevel):
        print(_LAND_REINSTALL_LINE)
    return 0
