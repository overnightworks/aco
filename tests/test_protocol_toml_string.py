"""A TOML string the writer produces holds no line separator that
`str.splitlines` ends a line at, so a line-wise reader of a body never sees a
free-text value split in two, and `tomllib` reads it back unchanged."""

import tomllib

import pytest

from aco import protocol

SEPARATORS = ["\x85", " ", " "]
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
