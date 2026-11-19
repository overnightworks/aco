"""The answers of the direct-merge path of the `land` command (`specs/land.spec.md`) to a merge
call that may still be running. `cmd_land` decides when it merges and what follows a merge."""

from . import forge, github, protocol, report, workboard

_PENDING_REFUSAL = (
    "pull request #{number} may still be merging ({foreign}); re-run aco land {number} --head <sha>"
)


def pending_refusal(number: int, error: forge.ForgeError) -> protocol.ClaimUnavailableError:
    """The refusal of a merge call after which the pull request may still be merging: a
    re-run finds it merged and finishes the landing, or merges it."""
    return protocol.ClaimUnavailableError(
        report.refusal_around_foreign_text(_PENDING_REFUSAL, str(error), number=number)
    )


def merge_commit_after_server_error(
    client: github.GitHubForge,
    number: int,
    pinned_head: str,
    error: forge.ForgeMergeUnansweredError,
) -> str:
    """The merge commit of a pull request GitHub merged at `pinned_head` although the merge
    call failed with a server error, found by one read of it; a pull request still open, or
    a read that fails, refuses as a merge that may still be pending."""
    try:
        read = client.landing(number)
    except forge.ForgeError:
        raise pending_refusal(number, error) from error
    if read.merge_commit is None or read.head_sha != pinned_head:
        raise pending_refusal(number, error) from error
    return read.merge_commit


def merge_method(
    pinned: workboard.MergeMethod | None,
    allowed: frozenset[workboard.MergeMethod],
    branch: str,
) -> workboard.MergeMethod:
    """The method `aco land` merges into `branch` with: the board
    configuration's own pin, refused where the forge's `allowed` methods exclude it;
    otherwise a squash wherever the forge allows one, and a merge commit where it
    allows a merge commit but no squash -- never a rebase, so a forge allowing no
    method at all, or only a rebase, to an unpinned land refuses."""
    if pinned is not None and allowed:
        if pinned not in allowed:
            allowed_list = ", ".join(
                method.value for method in workboard.MergeMethod if method in allowed
            )
            raise protocol.ClaimUnavailableError(
                f"board.toml merge_method {pinned.value} is not allowed on {branch}: "
                f"GitHub allows {allowed_list}"
            )
        return pinned
    for method in (workboard.MergeMethod.SQUASH, workboard.MergeMethod.MERGE):
        if method in allowed:
            return method
    raise protocol.ClaimUnavailableError(f"GitHub allows no merge method aco can use on {branch}")


def allowed_merge_methods(
    client: github.GitHubForge, number: int, rules: forge.BranchMergeRules
) -> frozenset[workboard.MergeMethod]:
    """Every method the forge allows on `branch`: the repository's own
    settings -- every method where it withholds them from a token without
    push rights, refused before any write unless they allow one `aco land`
    can use -- narrowed by each rule on `branch` (LANDCMD-42), since GitHub
    refuses a method any one of them excludes."""
    settings = client.allowed_merge_methods()
    allowed = frozenset(workboard.MergeMethod) if settings is None else settings
    if not allowed & workboard.LANDING_MERGE_METHODS:
        raise protocol.ClaimUnavailableError(
            f"pull request #{number} cannot land: this repository allows neither a merge commit "
            "nor a squash merge"
        )
    for rule in rules.merge_methods:
        allowed &= rule
    return allowed
