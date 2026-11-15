"""GitHub's conditional request for `forge.BoardProbe`: one `gh api` call that
sends the last answer's ETag and reads the status line, because `gh` exits
non-zero on the 304 that means unchanged."""

import re

from . import forge, github, process, protocol

_PURPOSE = "GitHub board probe"
_STATUS_LINE = re.compile(r"HTTP/\S+\s+(\d{3})")
_ETAG_HEADER = re.compile(r"etag:\s*(\S.*?)\s*", re.IGNORECASE)
_CHANGED = 200
_NOT_MODIFIED = 304
_NEWEST_UPDATED = "issues?state=all&sort=updated&direction=desc&per_page=1"


def _path(target: forge.ProbeTarget) -> str:
    suffix = _NEWEST_UPDATED if target.number is None else f"issues/{target.number}"
    return f"repos/{target.repository}/{suffix}"


def _command(target: forge.ProbeTarget, token: str | None) -> list[str]:
    conditional = [] if token is None else ["-H", f"If-None-Match: {token}"]
    return ["gh", "api", "-i", *conditional, _path(target)]


def _run(command: list[str]) -> process.BoundedResult:
    try:
        return process.run_bounded(
            command, env=github.command_environment(), timeout=github.GH_TIMEOUT_SECONDS
        )
    except (process.ExecutableMissingError, process.ProcessStartFailedError) as error:
        raise protocol.ClaimError(f"cannot start {_PURPOSE}: {error}") from error
    except process.ProcessError as error:
        raise github.forge_failure(error, _PURPOSE) from error


def _status(lines: list[str]) -> int | None:
    found = _STATUS_LINE.match(lines[0]) if lines else None
    return None if found is None else int(found.group(1))


def _etag(lines: list[str]) -> str | None:
    """The ETag header of the response head, which ends at its first blank line."""
    head = lines[: lines.index("")] if "" in lines else lines
    found = (_ETAG_HEADER.fullmatch(line) for line in head)
    return next((match.group(1) for match in found if match is not None), None)


class GitHubBoardProbe:
    """`forge.BoardProbe` over `gh api`."""

    def changed_since(self, target: forge.ProbeTarget, token: str | None) -> forge.ProbeAnswer:
        """A 304 is unchanged whatever `gh`'s exit status; a 200 is changed and
        carries the ETag to send next. Any other answer is classified as a
        failed `gh` call is."""
        result = _run(_command(target, token))
        decoded = github.decoded_output(result, _PURPOSE)
        lines = decoded.splitlines()
        status = _status(lines)
        if status == _NOT_MODIFIED and token is not None:
            return forge.ProbeAnswer(changed=False, token=token)
        if status != _CHANGED:
            raise github.nonzero_exit_failure(decoded, result.exit_status, _PURPOSE)
        etag = _etag(lines)
        if etag is None:
            raise forge.ForgeMalformedResponseError(f"{_PURPOSE} returned no ETag")
        return forge.ProbeAnswer(changed=True, token=etag)
