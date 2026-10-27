"""Line 14's rules for the words of an open option card: no issue numbers, paths,
file names, code names or flags outside `contract`; a short `problem`; option
names of two to five words; one-line `area`, `topic` and option names. Pure; it
returns `(field, message)` pairs and imports nothing from the expectation
grammar, which wraps them in its own defect type.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence

FILE_EXTENSIONS = (
    "py",
    "ts",
    "svelte",
    "js",
    "md",
    "toml",
    "json",
    "yml",
    "yaml",
    "html",
    "css",
    "sh",
)
LINE_TEXT_KEYS = ("question", "problem", "caption", "area", "topic", "reason")
OPTION_TEXT_KEYS = ("name", "effect", "caption", "notice", "cost", "undo_how")
PROBLEM_MAXIMUM_WORDS = 20
OPTION_NAME_MINIMUM_WORDS = 2
OPTION_NAME_MAXIMUM_WORDS = 5
_ONE_LINE_KEYS = frozenset({"area", "topic", "name"})
_TOKEN_OPENERS = "„“”\"'»«([{"
_TOKEN_CLOSERS = "„“”\"'»«)]},;:!?."
_EXTENSIONS = "|".join(FILE_EXTENSIONS)
_ISSUE_NUMBER = re.compile(r"(?<!\w)#\d+")
_PATH = re.compile(rf"^(?:\./|~/|/[A-Za-z])|://|/[^/]*\.(?:{_EXTENSIONS})$")
_FILE_NAME = re.compile(rf"[^/]*\.(?:{_EXTENSIONS})")
_SNAKE_CASE = re.compile(r"(?<!\w)[a-zäöüß]+(?:_[a-zäöüß0-9]+)+(?!\w)")
_CAMEL_CASE = re.compile(r"(?<!\w)[a-zäöüß]{2,}[A-ZÄÖÜ][a-zäöüß]")
_FLAG = re.compile(r"(?<!\S)--[A-Za-z]")


def _tokens(text: str) -> Iterator[str]:
    """The whitespace-separated words of `text` without the quotes, brackets and
    sentence punctuation around them."""
    for word in text.split():
        yield word.lstrip(_TOKEN_OPENERS).rstrip(_TOKEN_CLOSERS)


def _has_token(pattern: re.Pattern[str]) -> Callable[[str], bool]:
    return lambda text: any(pattern.search(token) for token in _tokens(text))


def _has_file_name(text: str) -> bool:
    return any(_FILE_NAME.fullmatch(token) for token in _tokens(text))


# What `text` must not contain, in the order the sentences print.
_JARGON_RULES: tuple[tuple[str, Callable[[str], bool]], ...] = (
    ("an issue number", lambda text: _ISSUE_NUMBER.search(text) is not None),
    ("a path", _has_token(_PATH)),
    ("a file name", _has_file_name),
    ("a backtick", lambda text: "`" in text),
    ("a snake case name", lambda text: _SNAKE_CASE.search(text) is not None),
    ("a camel case name", lambda text: _CAMEL_CASE.search(text) is not None),
    ("a flag", lambda text: _FLAG.search(text) is not None),
)


def _length_reasons(key: str, text: str) -> Iterator[str]:
    words = len(text.split())
    if key == "problem" and words > PROBLEM_MAXIMUM_WORDS:
        yield f"must be at most {PROBLEM_MAXIMUM_WORDS} words"
    if key == "name" and not OPTION_NAME_MINIMUM_WORDS <= words <= OPTION_NAME_MAXIMUM_WORDS:
        yield f"must be {OPTION_NAME_MINIMUM_WORDS} to {OPTION_NAME_MAXIMUM_WORDS} words"
    if key in _ONE_LINE_KEYS and (text != text.strip() or len(text.splitlines()) > 1):
        yield "must be one line without spaces around it"


def _text_reasons(key: str, text: str) -> Iterator[str]:
    for phrase, found in _JARGON_RULES:
        if found(text):
            yield f"must not contain {phrase}"
    yield from _length_reasons(key, text)


def _checked_texts(
    prefix: str, line: Mapping[str, object], options: Sequence[tuple[str, Mapping[str, object]]]
) -> Iterator[tuple[str, str, str]]:
    """Each checked string of the card as `(path, key, text)`, the line's first."""
    for owner, table, keys in (
        (prefix, line, LINE_TEXT_KEYS),
        *((f"{prefix}.{suffix}", option, OPTION_TEXT_KEYS) for suffix, option in options),
    ):
        for key in keys:
            text = table.get(key)
            if isinstance(text, str) and text.strip():
                yield f"{owner}.{key}", key, text


def card_rule_defects(
    prefix: str, line: Mapping[str, object], options: Sequence[tuple[str, Mapping[str, object]]]
) -> list[tuple[str, str]]:
    """`(field, message)` for every rule an open option card breaks; `options`
    pairs each option table with its path suffix under `prefix`."""
    return [
        (path, f"{path} {reason}")
        for path, key, text in _checked_texts(prefix, line, options)
        for reason in _text_reasons(key, text)
    ]
