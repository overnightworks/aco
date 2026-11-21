"""A GitHub REST listing read one page per `gh api <path> -i` call, and the split of an `-i`
answer into its header block and body.

A page's `Link` header names the next page and its absence ends the walk, so no page past the
last is ever requested. Each page is one call of the caller's runner, which counts it.
"""

import re
from collections.abc import Callable

from . import forge

API_ORIGIN = "https://api.github.com/"
_STATUS_LINE = re.compile(r"HTTP/\S+\s+(\d{3})")
_HEADER_FIELD = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+:")
_HEAD_END = re.compile(r"\r?\n\r?\n")
_LINK_ENTRY = r'<([^>]*)>;\s*rel="([^"]*)"'
_LINK_VALUE = re.compile(rf"{_LINK_ENTRY}(?:,\s*{_LINK_ENTRY})*")
_LINK_ENTRY_PATTERN = re.compile(_LINK_ENTRY)
_NEXT = "next"


def split_answer(decoded: str) -> tuple[list[str], str]:
    """The header lines and the body of an `-i` answer. The head ends at its first blank line,
    or is the whole answer when the body is empty."""
    head, *body = _HEAD_END.split(decoded, maxsplit=1)
    return head.splitlines(), "".join(body)


def status(head: list[str]) -> int | None:
    """The status code of a response head's first line, `None` when it has no status line."""
    found = _STATUS_LINE.match(head[0]) if head else None
    return None if found is None else int(found.group(1))


def header(head: list[str], name: str) -> str | None:
    """The first non-empty value of the response header `name`."""
    fields = (line.partition(":") for line in head)
    values = (value.strip() for key, _colon, value in fields if key.lower() == name)
    return next((value for value in values if value), None)


def _next_path(head: list[str]) -> str | None:
    link = header(head, "link")
    if link is None:
        return None
    if _LINK_VALUE.fullmatch(link) is None:
        raise forge.ForgeMalformedResponseError("GitHub returned a malformed Link header")
    targets = [url for url, relation in _LINK_ENTRY_PATTERN.findall(link) if relation == _NEXT]
    if not targets:
        return None
    if not targets[0].startswith(API_ORIGIN):
        raise forge.ForgeMalformedResponseError("GitHub returned a next link outside its API")
    return targets[0].removeprefix(API_ORIGIN)


def read_pages(run: Callable[[list[str]], str], path: str, jq: str) -> str:
    """The `--jq` output of every page of the listing at `path`, page after page in one text.

    Each page is one `run` of `api <path> -i --jq <jq>`; a failed one raises as `run` raises."""
    pages: list[str] = []
    next_path: str | None = path
    while next_path is not None:
        head, body = split_answer(run(["api", next_path, "-i", "--jq", jq]))
        if status(head) is None:
            raise forge.ForgeMalformedResponseError("GitHub returned an answer without a header")
        if not all(_HEADER_FIELD.match(line) for line in head[1:]):
            raise forge.ForgeMalformedResponseError("GitHub returned a malformed header block")
        next_path = _next_path(head)
        if body:
            pages.append(body)
    return "\n".join(pages)
