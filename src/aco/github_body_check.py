"""Writing one item's body on GitHub and checking the write against the item's
edit history."""

import json

from . import forge, github_body_write, github_graphql
from .protocol import ClaimError

_REVISIONS_JUDGED = 2
_FEWER_THAN_TWO = "the edit history holds fewer than two revisions"
_DELETED = "a revision in the edit history was deleted"
_NOT_SHOWN = "the edit history does not show this write"


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


def write_body_checked(  # noqa: PLR0913, PLR0917 - the forge's one delegate; a record would grow it
    run: github_body_write.GitHubRunner,
    fetch: github_graphql.FetchBlock,
    repository: forge.RepositoryId,
    number: int,
    body: str,
    replacing: str,
) -> None:
    """Send `body` through `run`, read the edit history once through `fetch` and
    raise what it shows of the write over `replacing` (`judge_write`). Anything
    that fails after the PATCH landed is `ForgeBodyNotVerifiedError`."""
    answer = github_body_write.patch_item_body(run, repository, number, body)
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
