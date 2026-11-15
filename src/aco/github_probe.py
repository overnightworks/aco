"""GitHub's conditional request for `forge.BoardProbe`: one `gh api` call that
sends the last answer's ETag and reads the status line, because `gh` exits
non-zero on the 304 that means unchanged."""

import re
from collections.abc import Callable

from . import forge, github

type ResponseRunner = Callable[..., tuple[str, int]]
"""Runs the `gh` command line it is given for the stated `purpose` and answers
its decoded output and exit status, whatever that status is."""

_PURPOSE = "GitHub board probe"
_STATUS_LINE = re.compile(r"HTTP/\S+\s+(\d{3})")
_CHANGED = 200
_NOT_MODIFIED = 304
_NEWEST_UPDATED = "issues?state=all&sort=updated&direction=desc&per_page=1"


def _path(target: forge.ProbeTarget) -> str:
    suffix = _NEWEST_UPDATED if target.number is None else f"issues/{target.number}"
    return f"repos/{target.repository}/{suffix}"


def _command(target: forge.ProbeTarget, token: str | None) -> list[str]:
    conditional = [] if token is None else ["-H", f"If-None-Match: {token}"]
    return ["gh", "api", "-i", *conditional, _path(target)]


def _status(lines: list[str]) -> int | None:
    found = _STATUS_LINE.match(lines[0]) if lines else None
    return None if found is None else int(found.group(1))


def _etag(lines: list[str]) -> str | None:
    """The ETag header of the response head, which ends at its first blank line."""
    head = lines[: lines.index("")] if "" in lines else lines
    headers = (line.partition(":") for line in head)
    values = (value.strip() for name, _colon, value in headers if name.lower() == "etag")
    return next((value for value in values if value), None)


class GitHubBoardProbe:
    """`forge.BoardProbe` over `gh api`."""

    def __init__(self, run: ResponseRunner) -> None:
        self._run = run

    def changed_since(self, target: forge.ProbeTarget, token: str | None) -> forge.ProbeAnswer:
        """A 304 is unchanged whatever `gh`'s exit status; a 200 is changed and
        carries the ETag to send next. Any other answer is classified as a
        failed `gh` call is."""
        decoded, exit_status = self._run(_command(target, token), purpose=_PURPOSE)
        lines = decoded.splitlines()
        status = _status(lines)
        if status == _NOT_MODIFIED and token is not None:
            return forge.ProbeAnswer(changed=False, token=token)
        if status != _CHANGED:
            raise github.nonzero_exit_failure(decoded, exit_status, _PURPOSE)
        etag = _etag(lines)
        if etag is None:
            raise forge.ForgeMalformedResponseError(f"{_PURPOSE} returned no ETag")
        return forge.ProbeAnswer(changed=True, token=etag)
