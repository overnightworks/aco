"""Decoding of one GitHub issue object: the board listing's issue and the
single-item read, which share the one rule for who counts as a member."""

from typing import TypeIs

from . import forge, protocol, workboard
from .body import ItemKind

# The organization's native issue types: casefolded so an org's own casing of
# the type name never matters. An unrecognized type name maps to no kind at
# all -- never guessed from a label -- so a repository whose org renames a type
# loses that item's container/bug rules rather than silently misreading them.
ISSUE_TYPE_KINDS: dict[str, ItemKind] = {
    "container": ItemKind.CONTAINER,
    "bug": ItemKind.BUG,
    "task": ItemKind.TASK,
    "feature": ItemKind.FEATURE,
}
_MEMBER_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")  # tuple: unhashable input is no member
_MALFORMED_ITEM_REFERENCE = "GitHub returned a malformed issue reference"


def is_member(association: object) -> bool:
    """Whether a GitHub `author_association` names a member of the repository."""
    return association in _MEMBER_ASSOCIATIONS


def issue_kind(value: object) -> ItemKind | None:
    return ISSUE_TYPE_KINDS.get(value.casefold()) if isinstance(value, str) else None


def _is_count(value: object, minimum: int = 0) -> TypeIs[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _is_timestamp(value: object) -> TypeIs[str]:
    return (
        isinstance(value, str) and protocol.RFC3339_TIMESTAMP_PATTERN.fullmatch(value) is not None
    )


def _valid_children_progress(closed: object, total: object) -> bool:
    """`childrenClosed`/`childrenTotal` (`sub_issues_summary`) must arrive
    both present or both absent -- `ContainerProgress` has no
    representation for "closed known, total unknown", and inventing one
    would let the board show a progress figure the forge never sent.
    `None` for both is preserved as `None`: `0/0` is a real container
    state, never a stand-in for "the forge said nothing"."""
    if closed is None and total is None:
        return True
    if closed is None or total is None:
        return False
    return _is_count(closed) and _is_count(total) and int(closed) <= int(total)


def board_issue(value: object) -> workboard.Issue:
    if not isinstance(value, dict):
        raise forge.ForgeMalformedResponseError("GitHub returned a malformed board issue")
    number = value.get("number")
    title = value.get("title")
    labels = value.get("labels")
    body = value.get("body")
    created_at = value.get("createdAt")
    updated_at = value.get("updatedAt")
    kind_raw = value.get("kind")
    children_closed = value.get("childrenClosed")
    children_total = value.get("childrenTotal")
    blocked_by_count = value.get("blockedByCount")
    if (
        not _is_count(number, minimum=1)
        or not isinstance(title, str)
        or not isinstance(labels, list)
        or not all(isinstance(label, str) for label in labels)
        or not isinstance(body, str)
        or not _is_timestamp(created_at)
        or not _is_timestamp(updated_at)
        or (kind_raw is not None and not isinstance(kind_raw, str))
        or not _valid_children_progress(children_closed, children_total)
        or not _is_count(blocked_by_count)
    ):
        raise forge.ForgeMalformedResponseError("GitHub returned a malformed board issue")
    return workboard.Issue(
        number,
        title,
        tuple(labels),
        body,
        created_at,
        updated_at,
        issue_kind(kind_raw),
        children_closed,
        children_total,
        blocked_by_count,
        author_is_member=is_member(value.get("authorAssociation")),
    )


def item_reference(value: object) -> forge.ItemReference:
    """The single-item read of an existing issue or pull request."""
    if not isinstance(value, dict):
        raise forge.ForgeMalformedResponseError(_MALFORMED_ITEM_REFERENCE)
    state = value.get("state")
    title = value.get("title")
    body = value.get("body")
    is_landing = value.get("is_landing")
    if (
        state not in {"open", "closed"}
        or not isinstance(title, str)
        or (body is not None and not isinstance(body, str))
        or not isinstance(is_landing, bool)
    ):
        raise forge.ForgeMalformedResponseError(_MALFORMED_ITEM_REFERENCE)
    return forge.ItemReference(
        forge.ItemState.OPEN if state == "open" else forge.ItemState.CLOSED,
        title,
        body or "",
        is_landing,
        author_is_member=is_member(value.get("author_association")),
    )
