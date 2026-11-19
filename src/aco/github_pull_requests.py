"""Pull request reads over REST: the requests of the board's merged and open lists, of one pull
request's landing facts and of an item's events, and the mapping of what they answer to the
port's values.

The module never runs `gh`: the adapter performs and counts every round trip, walks the pages
and hands the parsed rows back, so no read here costs a GraphQL point.
"""

from collections.abc import Callable, Iterable
from datetime import datetime

from . import forge, github_issue_payload, protocol, workboard

MALFORMED_PULL_REQUEST = "GitHub returned a malformed pull request"
_MALFORMED_BOARD_PULL_REQUEST = "GitHub returned a malformed board pull request"
_MALFORMED_EVENT = "GitHub returned a malformed issue event"
_BOT_TYPE = "Bot"
_BOT_LOGIN_SUFFIX = "[bot]"
# `gh` prints a list's array as one row per line under this filter; no key is mapped by it.
_ONE_ROW_PER_LINE = ["--jq", ".[]"]

# Resolves a head repository's `OWNER/REPO` to its identity, or `None` when the text is no
# repository; the adapter's answer also refuses a repository GitHub has renamed.
SourceRepository = Callable[[str], forge.RepositoryId | None]


def closed_issues_path(repository: forge.RepositoryId, since: str, page: int, per_page: int) -> str:
    """One page of the issues GitHub reports closed and updated at or after `since`, newest
    created first: a pull request merged after `since` was updated at its merge."""
    return f"repos/{repository}/issues?state=closed&since={since}&per_page={per_page}&page={page}"


def merged_page_request(
    repository: forge.RepositoryId, since: str, page: int, per_page: int
) -> list[str]:
    return ["api", closed_issues_path(repository, since, page, per_page), *_ONE_ROW_PER_LINE]


def open_page_request(repository: forge.RepositoryId, page: int, per_page: int) -> list[str]:
    path = f"repos/{repository}/pulls?state=open&per_page={per_page}&page={page}"
    return ["api", path, *_ONE_ROW_PER_LINE]


def landing_request(repository: forge.RepositoryId, number: int) -> list[str]:
    return ["api", f"repos/{repository}/pulls/{number}"]


def events_page_request(
    repository: forge.RepositoryId, number: int, page: int, per_page: int
) -> list[str]:
    path = f"repos/{repository}/issues/{number}/events?per_page={per_page}&page={page}"
    return ["api", path, *_ONE_ROW_PER_LINE]


def _malformed(message: str) -> forge.ForgeMalformedResponseError:
    return forge.ForgeMalformedResponseError(message)


def _object(value: object, message: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _malformed(message)
    return value


def _timestamp(value: object, message: str) -> str:
    """`value`, once it is an RFC 3339 instant with real calendar and clock values."""
    if not isinstance(value, str) or protocol.RFC3339_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise _malformed(message)
    try:
        datetime.fromisoformat(value)
    except ValueError as error:
        raise _malformed(message) from error
    return value


def _number_title_body(row: dict[str, object], message: str) -> tuple[int, str, str]:
    number, title, body = row.get("number"), row.get("title"), row.get("body")
    text = "" if body is None else body
    if (
        isinstance(number, bool)
        or not isinstance(number, int)
        or number < 1
        or not isinstance(title, str)
        or not isinstance(text, str)
    ):
        raise _malformed(message)
    return number, title, text


def open_pull_request(value: object) -> workboard.PullRequest:
    row = _object(value, _MALFORMED_BOARD_PULL_REQUEST)
    number, title, body = _number_title_body(row, _MALFORMED_BOARD_PULL_REQUEST)
    head = row.get("head")
    branch = head.get("ref") if isinstance(head, dict) else None
    if not isinstance(branch, str):
        raise _malformed(_MALFORMED_BOARD_PULL_REQUEST)
    return workboard.PullRequest(number, title, body, branch)


def open_pull_requests(rows: Iterable[object]) -> tuple[workboard.PullRequest, ...]:
    return tuple(map(open_pull_request, rows))


def _merge_time_of_issue_row(row: dict[str, object]) -> str | None:
    """The time a closed issue-list row was merged, or `None` for a plain issue and a pull
    request closed unmerged. A pull request row without its `merged_at` key is malformed: it
    never reads as unmerged."""
    pull_request = row.get("pull_request")
    if pull_request is None:
        return None
    if not isinstance(pull_request, dict) or "merged_at" not in pull_request:
        raise _malformed(_MALFORMED_BOARD_PULL_REQUEST)
    merged_at = pull_request["merged_at"]
    if merged_at is None:
        return None
    return _timestamp(merged_at, _MALFORMED_BOARD_PULL_REQUEST)


def _merged_pull_request(value: object, floor: str) -> workboard.PullRequest | None:
    row = _object(value, _MALFORMED_BOARD_PULL_REQUEST)
    number, title, body = _number_title_body(row, _MALFORMED_BOARD_PULL_REQUEST)
    merged_at = _merge_time_of_issue_row(row)
    # Both times share RFC 3339's fixed UTC `Z` form, so string order is time order. The board
    # reads the branch of an open pull request only.
    if merged_at is None or merged_at < floor:
        return None
    return workboard.PullRequest(number, title, body, "", merged_at)


def merged_pull_requests(rows: Iterable[object], floor: str) -> tuple[workboard.PullRequest, ...]:
    """The pull requests among closed-issue `rows` merged at or after `floor`, each number once."""
    merged: dict[int, workboard.PullRequest] = {}
    for value in rows:
        pull_request = _merged_pull_request(value, floor)
        if pull_request is not None:
            merged.setdefault(pull_request.number, pull_request)
    return tuple(merged.values())


def _author_login(pull: dict[str, object]) -> str:
    user = _object(pull.get("user"), MALFORMED_PULL_REQUEST)
    login = user.get("login")
    if not isinstance(login, str) or not login:
        raise _malformed(MALFORMED_PULL_REQUEST)
    if user.get("type") == _BOT_TYPE and login.endswith(_BOT_LOGIN_SUFFIX):
        return f"app/{login.removesuffix(_BOT_LOGIN_SUFFIX)}"
    return login


def _head_repository_path(head: dict[str, object]) -> str | None:
    repository = head.get("repo")
    name = repository.get("name") if isinstance(repository, dict) else None
    owner = repository.get("owner") if isinstance(repository, dict) else None
    login = owner.get("login") if isinstance(owner, dict) else None
    if not isinstance(name, str) or not isinstance(login, str):
        return None
    return f"{login}/{name}"


def _head(
    pull: dict[str, object], source_repository: SourceRepository
) -> tuple[str, str, forge.RepositoryId]:
    """The head's branch, commit and source repository."""
    head = _object(pull.get("head"), MALFORMED_PULL_REQUEST)
    path = _head_repository_path(head)
    source = None if path is None else source_repository(path)
    branch, sha = head.get("ref"), head.get("sha")
    if (
        source is None
        or not isinstance(branch, str)
        or not isinstance(sha, str)
        or protocol.COMMIT_PATTERN.fullmatch(sha) is None
    ):
        raise _malformed(MALFORMED_PULL_REQUEST)
    return branch, sha, source


def _merge_commit(pull: dict[str, object]) -> str | None:
    """The merge commit of a merged pull request, `None` for an open or closed one: REST also
    names a test-merge commit there, which is no merge."""
    if "merged_at" not in pull:
        raise _malformed(MALFORMED_PULL_REQUEST)
    if pull["merged_at"] is None:
        return None
    _timestamp(pull["merged_at"], MALFORMED_PULL_REQUEST)
    sha = pull.get("merge_commit_sha")
    if not isinstance(sha, str) or protocol.COMMIT_PATTERN.fullmatch(sha) is None:
        raise _malformed(MALFORMED_PULL_REQUEST)
    return sha


def landing(value: object, source_repository: SourceRepository) -> forge.Landing:
    pull = _object(value, MALFORMED_PULL_REQUEST)
    branch, head_sha, source = _head(pull, source_repository)
    number, title, body = _number_title_body(pull, MALFORMED_PULL_REQUEST)
    target = _object(pull.get("base"), MALFORMED_PULL_REQUEST).get("ref")
    login = _author_login(pull)
    merge_commit = _merge_commit(pull)
    if not isinstance(target, str):
        raise _malformed(MALFORMED_PULL_REQUEST)
    return forge.Landing(
        number,
        login,
        body,
        source,
        branch,
        target,
        merge_commit is not None,
        merge_commit,
        title,
        head_sha,
        github_issue_payload.is_dependency_bot(login),
    )


def reopened_at(events: Iterable[object]) -> datetime | None:
    """The newest `reopened` event among an item's `events`, or `None` when it never was."""
    reopened: list[datetime] = []
    for value in events:
        event = _object(value, _MALFORMED_EVENT)
        kind = event.get("event")
        if not isinstance(kind, str):
            raise _malformed(_MALFORMED_EVENT)
        if kind == "reopened":
            reopened.append(
                datetime.fromisoformat(_timestamp(event.get("created_at"), _MALFORMED_EVENT))
            )
    return max(reopened, default=None)
