"""What GitHub's merge queue appends to a landed commit message.

When a queue squashes with the pull request's title and body, it appends a
paragraph of `Co-authored-by:` trailers after the body (and, with several
commits, a paragraph of hyphens before it), which pushes the body's own
`Work-Item:`/`No-Item:` paragraph out of git's last-paragraph trailer block.
This module only recognises that appended block and cuts it off; git's own
trailer parsing reads what is left, and `trailer_values` lists its output.
"""

import re

_COAUTHOR_LINE = re.compile(r"co-authored-by:[ \t]*\S", re.IGNORECASE)
_HYPHEN_LINE = re.compile(r"-{3,}")
# The characters git counts as blank; str.strip() would also drop Unicode
# whitespace that git reads as content.
_GIT_BLANK = " \t\r\n"


def without_appended_coauthors(message: str) -> str | None:
    """`message` without GitHub's appended block -- an optional paragraph of
    one line of hyphens, then a paragraph in which every line is a
    `Co-authored-by:` trailer -- or `None` when the message does not end in
    that block or nothing else is left. Nothing but that block is cut."""
    lines = message.rstrip(_GIT_BLANK).split("\n")
    coauthors = lines[_last_paragraph_start(lines) :]
    if not coauthors or not all(_COAUTHOR_LINE.match(line) for line in coauthors):
        return None
    kept = _without_trailing_blank_lines(lines[: len(lines) - len(coauthors)])
    hyphens = kept[_last_paragraph_start(kept) :]
    if len(hyphens) == 1 and _HYPHEN_LINE.fullmatch(hyphens[0].strip(_GIT_BLANK)):
        kept = _without_trailing_blank_lines(kept[: len(kept) - 1])
    return "\n".join(kept) + "\n" if kept else None


def _last_paragraph_start(lines: list[str]) -> int:
    start = len(lines)
    while start > 0 and lines[start - 1].strip(_GIT_BLANK):
        start -= 1
    return start


def _without_trailing_blank_lines(lines: list[str]) -> list[str]:
    end = len(lines)
    while end > 0 and not lines[end - 1].strip(_GIT_BLANK):
        end -= 1
    return lines[:end]


def trailer_values(trailers: tuple[str, ...], key: str) -> tuple[str, ...]:
    """The values of `trailers`' `key` lines (`Token: value`, as git's trailer
    parsing prints them), as `%(trailers:key=...,valueonly)` lists them."""
    split_lines = (line.partition(":") for line in trailers)
    values = (
        value.removeprefix(" ") for token, _, value in split_lines if token.lower() == key.lower()
    )
    return tuple(value for value in values if value)
