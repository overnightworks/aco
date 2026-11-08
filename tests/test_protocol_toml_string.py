"""A TOML string the writer produces holds no line separator that
`str.splitlines` ends a line at, so a line-wise reader of a body never sees a
free-text value split in two, and `tomllib` reads it back unchanged."""

import tomllib

import pytest

from aco import body_fence, protocol

SEPARATORS = ["\N{NEXT LINE}", "\N{LINE SEPARATOR}", "\N{PARAGRAPH SEPARATOR}"]
SEPARATOR_IDS = ["next-line", "line-separator", "paragraph-separator"]


@pytest.mark.parametrize("separator", SEPARATORS, ids=SEPARATOR_IDS)
def test_toml_string_writes_a_line_separator_escaped_and_reads_it_back(separator: str) -> None:
    value = f"before{separator}```aco"

    written = protocol.toml_string(value)

    assert len(written.splitlines()) == 1
    assert tomllib.loads(f"key = {written}")["key"] == value


@pytest.mark.parametrize("separator", SEPARATORS, ids=SEPARATOR_IDS)
def test_toml_multiline_string_keeps_its_newlines_and_escapes_a_line_separator(
    separator: str,
) -> None:
    value = f"first\n{separator}second"

    written = protocol.toml_multiline_string(value)

    assert len(written.splitlines()) == 3
    assert tomllib.loads(f"key = {written}")["key"] == value


@pytest.mark.parametrize(
    "fence_line",
    ["```", "~~~", "`````", "~~~~~~", "   ```", "```   ", "```svg", "~~~ info"],
    ids=[
        "backticks",
        "tildes",
        "long-backticks",
        "long-tildes",
        "indented",
        "trailing-spaces",
        "info-string",
        "tilde-info-string",
    ],
)
def test_toml_multiline_string_never_writes_a_fence_line_and_reads_it_back(
    fence_line: str,
) -> None:
    value = f"<svg/>\n{fence_line}\nafter"

    written = protocol.toml_multiline_string(value)

    fence_openings = [
        line for line in written.splitlines() if body_fence.FENCE_OPENING_PATTERN.match(line)
    ]
    assert fence_openings == []
    assert tomllib.loads(f"key = {written}")["key"] == value


def test_toml_multiline_string_writes_a_value_without_backtick_or_tilde_as_it_does_today() -> None:
    written = protocol.toml_multiline_string('<svg a="b"/>\n\tx')

    assert written == '"""\n<svg a=\\"b\\"/>\n\tx"""'
