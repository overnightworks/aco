"""The `[[expectation]]` entry grammar of a work-item body's `aco` block: the
accepted values, the card-field and picture rules, the defects a stored entry
can carry, and the canonical rendering of the entries. Pure; it never imports
`body`, which calls it while parsing and rendering a block and reports its
`FieldDefect` pairs as `ContractDefect`s.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import date
from typing import NamedTuple, cast

from . import protocol


class FieldDefect(NamedTuple):
    """One refusal: the dotted `field` it is about and its `message`."""

    field: str
    message: str


BLOCK_EXPECTATION_DEFAULTS = frozenset({"yes", "no", "later"})
# A ruling transcribes the operator's word: "later" is a legitimate
# final answer -- an explicit, dated decision to defer -- not only a
# proposer's guessed default, so it rules exactly like "yes"/"no" (`rule
# --later` writes `ruling = "later"` the same way `--yes`/`--no` do).
BLOCK_EXPECTATION_RULINGS = frozenset({"yes", "no", "later"})
# The three optional card fields a proposer (`aco ask`) may attach to an
# `[[expectation]]` entry: the operator-language question and
# example a card shows in place of `text`, and an inline-SVG picture. Absent
# entirely, a card falls back to `text` unchanged.
EXPECTATION_QUESTION_MAXIMUM_CHARACTERS = 160
EXPECTATION_PICTURE_MAXIMUM_BYTES = 8 * 1024


def _block_expectation_variant_defects(prefix: str, entry: dict[str, object]) -> list[FieldDefect]:
    has_default, has_ruling, has_ruled_on = (
        "default" in entry,
        "ruling" in entry,
        "ruled_on" in entry,
    )
    if has_default and (has_ruling or has_ruled_on):
        return [
            FieldDefect(
                f"{prefix}.default",
                f"{prefix} must be proposed (default) or ruled (ruling, ruled_on), not both",
            )
        ]
    if has_default:
        if entry["default"] not in BLOCK_EXPECTATION_DEFAULTS:
            return [FieldDefect(f"{prefix}.default", f"{prefix}.default must be yes, no, or later")]
        return []
    if has_ruling or has_ruled_on:
        defects = []
        if entry.get("ruling") not in BLOCK_EXPECTATION_RULINGS:
            defects.append(
                FieldDefect(f"{prefix}.ruling", f"{prefix}.ruling must be yes, no, or later")
            )
        if type(entry.get("ruled_on")) is not date:
            defects.append(
                FieldDefect(f"{prefix}.ruled_on", f"{prefix}.ruled_on must be a TOML local date")
            )
        return defects
    return [
        FieldDefect(
            f"{prefix}.default", f"{prefix} must carry default, or both ruling and ruled_on"
        )
    ]


def _expectation_question_defect(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "must be a non-empty string"
    if len(value) > EXPECTATION_QUESTION_MAXIMUM_CHARACTERS:
        return f"must be at most {EXPECTATION_QUESTION_MAXIMUM_CHARACTERS} characters"
    return None


def _expectation_example_defect(value: object) -> str | None:
    return None if isinstance(value, str) and value.strip() else "must be a non-empty string"


_EXPECTATION_PICTURE_EVENT_HANDLER_ATTRIBUTE = re.compile(r"[\s/]on[a-z]+\s*=", re.IGNORECASE)
# `/` joins `[\s:]` as a separator so `<a/href=…>` (slash instead of a space
# before the attribute) is still caught; the final alternative's class adds
# `\s` so a greedy `\s*` that backtracks into the gap between `=` and a
# quoted value (`href = "#x"`) cannot land on that whitespace and misread it
# as an unquoted external value.
_EXPECTATION_PICTURE_EXTERNAL_HREF = re.compile(
    r'(?:^|[\s:/])href\s*=\s*(?:"(?!#)|\'(?!#)|(?![\s"\'#]))', re.IGNORECASE
)
# SMIL can retarget `href` without ever writing `href=` itself:
# `<animate attributeName="href" to="http://…">` swaps
# the target after the document loads, and `xlink:href` is the same escape
# under its namespaced spelling. Refused only when both attributes sit on the
# same element: scanning each `<...>` tag on its
# own keeps an unrelated `attributeName`/`to` pair on a different element from
# falsely refusing the picture. Both attributes accept SMIL's own quoting
# forms -- double-quoted, single-quoted, or bare -- mirroring
# `_EXPECTATION_PICTURE_EXTERNAL_HREF`'s own unquoted-value check above.
_EXPECTATION_PICTURE_SMIL_HREF_ATTRIBUTE = re.compile(
    r"attributename\s*=\s*(?:\"(?:xlink:)?href\"|'(?:xlink:)?href'|(?:xlink:)?href(?=[\s/>]))",
    re.IGNORECASE,
)
# `values` lists a `;`-separated sequence of keyframes (SMIL's own syntax),
# so a rule that only reads the first character after `=` misses a later
# external segment such as `values="#a;http://evil.example"`.
# The regex only captures the raw attribute value in
# each of SMIL's own quoting forms; `_expectation_picture_smil_external_target`
# below splits it on `;` and refuses if any trimmed segment does not start
# with `#`, so `to`/`from` (which never carry a `;`) are covered by the same
# one-segment case.
_EXPECTATION_PICTURE_SMIL_TARGET_ATTRIBUTE = re.compile(
    r"""\b(?:to|from|values)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]*))""", re.IGNORECASE
)
_EXPECTATION_PICTURE_SVG_ELEMENT = re.compile(r"<[^<>]+>")


def _expectation_picture_smil_external_target(element: str) -> bool:
    """Whether `element` sets SMIL `to`, `from`, or `values` to any
    `;`-separated segment that does not start with `#`:
    `values` can list several keyframes, so every segment is
    checked, not only the value's first character."""
    for match in _EXPECTATION_PICTURE_SMIL_TARGET_ATTRIBUTE.finditer(element):
        raw = next(group for group in match.groups() if group is not None)
        if any(not segment.strip().startswith("#") for segment in raw.split(";")):
            return True
    return False


def _expectation_picture_smil_external_href(value: str) -> bool:
    """Whether any single SVG element in `value` both retargets `href` (or
    `xlink:href`) via SMIL's `attributeName` and points it outside the
    document -- scanning element-by-element instead of across the whole
    document."""
    return any(
        _EXPECTATION_PICTURE_SMIL_HREF_ATTRIBUTE.search(element)
        and _expectation_picture_smil_external_target(element)
        for element in _EXPECTATION_PICTURE_SVG_ELEMENT.findall(value)
    )


def _expectation_picture_content_refusals(value: str) -> tuple[tuple[bool, str], ...]:
    """Every path an inline SVG can run script or reach outside the
    document, checked case-insensitively: `refused` paired with the
    sentence for the first one `value` matches, in this fixed order."""
    lowered = value.lower()
    return (
        ("<script" in lowered, "must not contain <script>"),
        ("<foreignobject" in lowered, "must not contain <foreignObject>"),
        (
            bool(_EXPECTATION_PICTURE_EVENT_HANDLER_ATTRIBUTE.search(value)),
            "must not contain an event-handler attribute",
        ),
        ("javascript:" in lowered, "must not contain a javascript: reference"),
        ("data:" in lowered, "must not contain a data: reference"),
        (
            bool(_EXPECTATION_PICTURE_EXTERNAL_HREF.search(value)),
            "must not reference an href outside the document",
        ),
        (
            _expectation_picture_smil_external_href(value),
            "must not animate href to an external target",
        ),
        ("url(" in lowered, "must not contain a url() reference"),
        ("<iframe" in lowered, "must not contain <iframe>"),
        ("<embed" in lowered, "must not contain <embed>"),
        ("<object" in lowered, "must not contain <object>"),
        ("srcdoc" in lowered, "must not contain srcdoc"),
    )


def _expectation_picture_defect(value: object) -> str | None:
    """The refusal sentence for an invalid `[[expectation]]` picture, or
    `None` for a valid one: an inline SVG, rooted at `<svg`, at
    most `EXPECTATION_PICTURE_MAXIMUM_BYTES`, and free of every refusal
    `_expectation_picture_content_refusals` names. The one owner the body
    parser's defects and `append_expectation`'s pre-write refusal both
    call."""
    if not isinstance(value, str):
        return "must be a string"
    if len(value.encode("utf-8")) > EXPECTATION_PICTURE_MAXIMUM_BYTES:
        return f"must be at most {EXPECTATION_PICTURE_MAXIMUM_BYTES} bytes"
    if not value.strip().startswith("<svg"):
        return "must be inline SVG rooted at <svg>"
    for refused, reason in _expectation_picture_content_refusals(value):
        if refused:
            return reason
    return None


# The three optional `[[expectation]]` card fields, each with
# its own refusal-sentence check -- shared, in this fixed order, by the body
# parser's defects (`_block_expectation_optional_field_defects`) and by
# `append_expectation`'s pre-write validation, so the rule is owned once.
EXPECTATION_OPTIONAL_FIELDS: tuple[tuple[str, Callable[[object], str | None]], ...] = (
    ("question", _expectation_question_defect),
    ("example", _expectation_example_defect),
    ("picture", _expectation_picture_defect),
)
_EXPECTATION_KNOWN_KEYS = frozenset(
    {"text", "default", "ruling", "ruled_on", *(key for key, _ in EXPECTATION_OPTIONAL_FIELDS)}
)


def _block_expectation_optional_field_defects(
    prefix: str, entry: dict[str, object]
) -> list[FieldDefect]:
    defects: list[FieldDefect] = []
    for key, check in EXPECTATION_OPTIONAL_FIELDS:
        if key not in entry:
            continue
        reason = check(entry[key])
        if reason is not None:
            defects.append(FieldDefect(f"{prefix}.{key}", f"{prefix}.{key} {reason}"))
    return defects


def _block_expectation_entry_defects(index: int, entry: object) -> list[FieldDefect]:
    prefix = f"expectation[{index}]"
    if not isinstance(entry, dict):
        return [FieldDefect(prefix, f"{prefix} must be a table")]
    defects: list[FieldDefect] = []
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        defects.append(FieldDefect(f"{prefix}.text", f"{prefix}.text must be a non-empty string"))
    defects.extend(_block_expectation_variant_defects(prefix, entry))
    defects.extend(_block_expectation_optional_field_defects(prefix, entry))
    unknown = sorted(set(entry) - _EXPECTATION_KNOWN_KEYS)
    defects.extend(FieldDefect(f"{prefix}.{key}", f"unknown key {prefix}.{key}") for key in unknown)
    return defects


def block_expectation_defects(entries: list[object]) -> list[FieldDefect]:
    return [
        defect
        for index, entry in enumerate(entries)
        for defect in _block_expectation_entry_defects(index, entry)
    ]


def render_expectations(data: Mapping[str, object]) -> list[str]:
    lines: list[str] = []
    for expectation in cast(list[dict[str, object]], data.get("expectation", [])):
        lines.extend(("", "[[expectation]]", f"text = {protocol.toml_string(expectation['text'])}"))
        if "default" in expectation:
            lines.append(f"default = {protocol.toml_string(expectation['default'])}")
        else:
            ruled_on = cast(date, expectation["ruled_on"])
            lines.append(f"ruling = {protocol.toml_string(expectation['ruling'])}")
            lines.append(f"ruled_on = {ruled_on.isoformat()}")
        if "question" in expectation:
            lines.append(f"question = {protocol.toml_string(expectation['question'])}")
        if "example" in expectation:
            lines.append(f"example = {protocol.toml_string(expectation['example'])}")
        if "picture" in expectation:
            lines.append(
                f"picture = {protocol.toml_multiline_string(cast(str, expectation['picture']))}"
            )
    return lines
