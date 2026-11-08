"""The one walk over a body's CommonMark fences.

Knows no block key: every reader of what a body fences, the `aco` block or the
running text beside it, filters this walk.
"""

import re
from dataclasses import dataclass

# CommonMark fence delimiters: at most 3 leading spaces, then a run of 3+
# backticks or 3+ tildes. An OPENING delimiter may carry an info string after
# the run (` ```python `); a CLOSING delimiter may not -- only trailing
# spaces/tabs are allowed after the run (` ``` `, never ` ```python `), so
# the closing pattern requires nothing but whitespace to follow.
# A 4-space-indented code block (CommonMark's other fencing form) is not
# modeled: a line written there reads as running text, visible on `board`/`next`
# and correctable by fencing it properly, never a silent divergence.
FENCE_OPENING_PATTERN = re.compile(r"^ {0,3}(?P<run>`{3,}|~{3,})")
FENCE_CLOSING_PATTERN = re.compile(r"^ {0,3}(?P<run>`{3,}|~{3,})[ \t]*$")


@dataclass(frozen=True)
class Fence:
    """One fence: the index of its opening line, of its closing line (`None`
    when it never closes and runs to the end of the body), its info string and
    the byte-exact text of the lines between."""

    opening_line: int
    closing_line: int | None
    info: str
    interior: str


@dataclass(frozen=True)
class FenceWalk:
    """Every fence of a body in order, and every line outside all fences as
    `(line index, text without its line boundary)`."""

    fences: tuple[Fence, ...]
    outside_lines: tuple[tuple[int, str], ...]


def _text_of(line_with_boundary: str) -> str:
    return line_with_boundary.splitlines()[0]


def _closes(text: str, fence_character: str, fence_length: int) -> bool:
    closing = FENCE_CLOSING_PATTERN.match(text)
    if closing is None:
        return False
    run = closing.group("run")
    return run[0] == fence_character and len(run) >= fence_length


def walk_fences(body: str) -> FenceWalk:
    """Walk `body.splitlines(keepends=True)` once. A line opens a fence when
    it matches the opening pattern outside every fence; only a later line with
    the same fence character, a run at least as long, and nothing but trailing
    whitespace after the run closes it, so a line like ` ```python ` is
    content. A fence that never closes runs to the end of the body, as GitHub
    renders it. Only one fence is open at a time. A line is matched without
    its boundary, as `str.splitlines()` ends it: LF, CRLF and the other
    separators `str.splitlines` knows; an interior keeps every original byte.
    """
    lines = body.splitlines(keepends=True)
    fences: list[Fence] = []
    outside: list[tuple[int, str]] = []
    open_line: int | None = None
    open_character = ""
    open_length = 0
    open_info = ""
    for index, line_with_boundary in enumerate(lines):
        text = _text_of(line_with_boundary)
        if open_line is None:
            opening = FENCE_OPENING_PATTERN.match(text)
            if opening is None:
                outside.append((index, text))
                continue
            run = opening.group("run")
            open_line, open_character, open_length = index, run[0], len(run)
            open_info = text[opening.end() :].strip(" \t")
        elif _closes(text, open_character, open_length):
            interior = "".join(lines[open_line + 1 : index])
            fences.append(Fence(open_line, index, open_info, interior))
            open_line = None
    if open_line is not None:
        fences.append(Fence(open_line, None, open_info, "".join(lines[open_line + 1 :])))
    return FenceWalk(tuple(fences), tuple(outside))
