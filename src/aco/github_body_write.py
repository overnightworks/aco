"""Writing one item's body on GitHub, checking the write against the item's edit
history, and judging what a failed write tells of it."""

import json
from collections.abc import Callable
from enum import StrEnum

from . import forge, github_graphql
from .protocol import ClaimError

GitHubRunner = Callable[..., str]

_REVISIONS_JUDGED = 2
_FEWER_THAN_TWO = "the edit history holds fewer than two revisions"
_DELETED = "a revision in the edit history was deleted"
_NOT_SHOWN = "the edit history does not show this write"


class BodyWriteOutcome(StrEnum):
    """What a failed `update_item_body` tells of the body: `REFUSED` wrote
    nothing, `UNKNOWN` may have written it."""

    REFUSED = "refused"
    UNKNOWN = "unknown"


def body_write_outcome(error: ClaimError) -> BodyWriteOutcome:
    """The outcome of a body write that raised `error`: the forge's own
    refusal of the call (authorization, no such item), and a `gh` that never
    ran (a plain `ClaimError` -- `_bounded_command` raises only typed forge
    errors once the process has started) wrote nothing; any other forge
    failure may have come after the write."""
    refused = isinstance(
        error, forge.ForgePermissionDeniedError | forge.ForgeNotFoundError
    ) or not isinstance(error, forge.ForgeError)
    return BodyWriteOutcome.REFUSED if refused else BodyWriteOutcome.UNKNOWN


def judge_write(
    number: int,
    written: str,
    replacing: str,
    revisions: tuple[github_graphql.BodyRevision, ...],
) -> forge.ForgeBodyWrittenError | None:
    """What the newest two `revisions` (newest first) show of the write that
    answered `written` over `replacing`: `None` when it is the newest and
    replaced `replacing`; otherwise the answer to raise."""
    if len(revisions) < _REVISIONS_JUDGED:
        return forge.ForgeBodyNotVerifiedError(number, _FEWER_THAN_TWO)
    newest, before = revisions[0], revisions[1]
    if newest.deleted or before.deleted:
        return forge.ForgeBodyNotVerifiedError(number, _DELETED)
    if newest.text == written:
        if before.text == replacing:
            return None
        return forge.ForgeBodyOverwrittenError(number, before.edited_at, before.editor, kept=True)
    if before.text == written:
        return forge.ForgeBodyOverwrittenError(number, newest.edited_at, newest.editor, kept=False)
    return forge.ForgeBodyNotVerifiedError(number, _NOT_SHOWN)


def _written_body(answer: str) -> str:
    """The `body` the PATCH answered, `null` read as empty."""
    try:
        value = json.loads(answer)
    except json.JSONDecodeError as error:
        raise forge.ForgeMalformedResponseError(
            "GitHub returned invalid body write answer JSON"
        ) from error
    if not isinstance(value, dict) or "body" not in value:
        raise forge.ForgeMalformedResponseError("GitHub returned a malformed body write answer")
    body = value["body"]
    if not isinstance(body, str | None):
        raise forge.ForgeMalformedResponseError("GitHub returned a malformed body write answer")
    return body or ""


def patch_item_body(
    run: GitHubRunner, repository: forge.RepositoryId, number: int, body: str
) -> str:
    """Send `body` as issue `number`'s body through the caller's `run`; the
    answer is the PATCH response's text."""
    path = f"repos/{repository}/issues/{number}"
    return run(
        ["api", "--method", "PATCH", path, "--input", "-"],
        input_data=json.dumps({"body": body}).encode("utf-8"),
    )


def check_item_body_write(
    fetch: github_graphql.FetchBlock, number: int, answer: str, replacing: str
) -> None:
    """Read the edit history once through `fetch` and raise what it shows of
    the write whose PATCH answered `answer` over `replacing` (`judge_write`).
    Anything that fails after the PATCH landed is `ForgeBodyNotVerifiedError`."""
    try:
        written = _written_body(answer)
        history = github_graphql.read_batched(
            github_graphql.EDIT_HISTORY_READ, [number], fetch=fetch, concurrency=1
        )
    except ClaimError as error:
        raise forge.ForgeBodyNotVerifiedError(number, str(error)) from error
    judgement = judge_write(number, written, replacing, history[number])
    if judgement is not None:
        raise judgement
