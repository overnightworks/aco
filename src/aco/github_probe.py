"""GitHub's conditional request for `forge.BoardProbe`: one `gh api` call that
sends the last answer's ETag and reads the status line, because `gh` exits
non-zero on the 304 that means unchanged."""

from collections.abc import Callable

from . import forge, github_failure, github_paging

type ResponseRunner = Callable[..., tuple[str, int]]
"""Runs the `gh` command line it is given for the stated `purpose` and answers
its decoded output and exit status, whatever that status is."""

_PURPOSE = "GitHub board probe"
_CHANGED = 200
_NOT_MODIFIED = 304
_NEWEST_UPDATED = "issues?state=all&sort=updated&direction=desc&per_page=1"


def _path(target: forge.ProbeTarget) -> str:
    suffix = _NEWEST_UPDATED if target.number is None else f"issues/{target.number}"
    return f"repos/{target.repository}/{suffix}"


def _command(target: forge.ProbeTarget, token: str | None) -> list[str]:
    conditional = [] if token is None else ["-H", f"If-None-Match: {token}"]
    return ["gh", "api", "-i", *conditional, _path(target)]


class GitHubBoardProbe:
    """`forge.BoardProbe` over `gh api`."""

    def __init__(self, run: ResponseRunner) -> None:
        self._run = run

    def changed_since(self, target: forge.ProbeTarget, token: str | None) -> forge.ProbeAnswer:
        """A 304 is unchanged whatever `gh`'s exit status; a 200 is changed and
        carries the ETag to send next. Any other answer is classified as a
        failed `gh` call is."""
        decoded, exit_status = self._run(_command(target, token), purpose=_PURPOSE)
        head, _body = github_paging.split_answer(decoded)
        status = github_paging.status(head)
        if status == _NOT_MODIFIED and token is not None:
            return forge.ProbeAnswer(changed=False, token=token)
        if status != _CHANGED:
            raise self._failure(decoded, exit_status)
        etag = github_paging.header(head, "etag")
        if etag is None:
            raise forge.ForgeMalformedResponseError(f"{_PURPOSE} returned no ETag")
        return forge.ProbeAnswer(changed=True, token=etag)

    def _failure(self, decoded: str, exit_status: int) -> forge.ForgeError:
        """The failure of a refused probe; a rate limit carries the reset its owner states,
        read through this probe's own runner."""
        failure = github_failure.nonzero_exit_failure(decoded, exit_status, _PURPOSE)
        if isinstance(failure, github_failure.RateLimitedError):
            return github_failure.with_reset(failure, self._answer)
        return failure

    def _answer(self, arguments: list[str]) -> str:
        decoded, exit_status = self._run(["gh", *arguments], purpose=_PURPOSE)
        if exit_status != 0:
            raise github_failure.nonzero_exit_failure(decoded, exit_status, _PURPOSE)
        return decoded
