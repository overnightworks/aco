"""This repository's one TOML string writer: what the claim records and the item body
blocks render their strings with.

Hand-written, not a TOML-writing library, so every writer escapes what
`tomllib.loads` reads back unchanged. It escapes every control character TOML's
basic-string grammar forbids unescaped (U+0000-U+001F and U+007F) and the line
separators U+0085, U+2028 and U+2029, which `str.splitlines` ends a line at, so a
raw one would split a value in the body's line-wise fence walk: the short escapes
where TOML has one, `\\uXXXX` for the rest.
"""

from typing import cast

# The first printable ASCII code point (space) and DEL bound the control
# characters a claim marker field, scope path, or outbound text may never
# contain -- each is meant to read as a single printable line.
ASCII_PRINTABLE_MIN = 0x20
ASCII_DEL = 0x7F

_TOML_STRING_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}
# A multi-line basic string keeps a newline and a tab literally.
_TOML_MULTILINE_LITERALS = frozenset("\n\t")
_FENCE_CHARACTERS = frozenset("`~")


def has_control_character(text: str) -> bool:
    return any(
        ord(character) < ASCII_PRINTABLE_MIN or ord(character) == ASCII_DEL for character in text
    )


def toml_string(value: object) -> str:
    """A TOML basic string for `value` -- the writer's one escaping path,
    matching what `tomllib.loads` (the reader) accepts back unchanged."""
    escaped = "".join(_toml_string_escape(char) for char in cast(str, value))
    return f'"{escaped}"'


def toml_multiline_string(value: str) -> str:
    """A TOML multi-line basic string for `value` -- a `picture`'s inline SVG.
    The text stands inside a fenced block, so a raw run of backticks or tildes
    could end it: each is written as `\\uXXXX`, every other character as
    `toml_string` does. `tomllib.loads` reads it back to `value` unchanged."""
    escaped = "".join(_multiline_escape(char) for char in value)
    return f'"""\n{escaped}"""'


def _multiline_escape(char: str) -> str:
    if char in _FENCE_CHARACTERS:
        return f"\\u{ord(char):04X}"
    return char if char in _TOML_MULTILINE_LITERALS else _toml_string_escape(char)


def _toml_string_escape(char: str) -> str:
    if char in _TOML_STRING_ESCAPES:
        return _TOML_STRING_ESCAPES[char]
    if has_control_character(char) or char.splitlines() != [char]:
        return f"\\u{ord(char):04X}"
    return char
