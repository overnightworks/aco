"""The `[[expectation]]` entry grammar of a work-item body's `aco` block: the
accepted values, the card-field and picture rules, the defects a stored entry
can carry, its card hash, and the canonical rendering of the entries. An entry
carrying `option` tables is an option line; any other is a yes/no line. Pure;
it never imports `body`, which calls it while parsing and rendering a block and
reports its `FieldDefect` pairs as `ContractDefect`s.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator, Mapping
from datetime import date
from enum import StrEnum
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
# A chosen figure, not a measured one: a line holds at most five pictures
# (today plus four results), about 3 KB each.
OPTION_LINE_PICTURES_MAXIMUM_BYTES = 16 * 1024
OPTION_LETTERS = "ABCD"
OPTION_COUNT_MINIMUM = 2
_CARD_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_PICTURE = "picture"
_SAME_AS_TODAY = "same_as_today"
_CAPTION = "caption"


class DecisionKind(StrEnum):
    """What kind of decision an option line asks for."""

    PRODUCT = "product"
    TECHNICAL = "technical"
    DATA_RISK = "data_risk"
    MONEY = "money"
    ACCESS = "access"
    WORDING = "wording"
    RELEASE = "release"


class Undo(StrEnum):
    """Whether an option, once built, can be taken back."""

    REVERSIBLE = "reversible"
    FINAL = "final"


# The card keys of an option line, each required, in rendering order after
# `text` and the decided state; `question` and `picture` are shared with the
# yes/no line, the others belong to the option line alone.
OPTION_LINE_KEYS = (
    "question",
    "problem",
    _PICTURE,
    _CAPTION,
    "decision_kind",
    "area",
    "topic",
    "recommended",
    "reason",
)
_OPTION_LINE_ONLY_KEYS = frozenset(OPTION_LINE_KEYS) - {"question", _PICTURE}
_OPTION_LINE_REFUSED_KEYS = ("default", "example")
# Every key of one `[[expectation.option]]` table, in rendering order; an
# option carries either `picture` or `same_as_today`, and `caption` only
# beside a picture.
OPTION_KEYS = (
    "name",
    "effect",
    _PICTURE,
    _SAME_AS_TODAY,
    _CAPTION,
    "notice",
    "cost",
    "undo",
    "undo_how",
    "contract",
)
_OPTION_REQUIRED_KEYS = tuple(
    key for key in OPTION_KEYS if key not in {_PICTURE, _SAME_AS_TODAY, _CAPTION}
)
_YES_NO_CARD_KEYS = ("text", "default", "question", "example", _PICTURE)


def _one_of(values: tuple[str, ...]) -> str:
    """`a, b, or c` -- the house wording of a list of accepted values."""
    return f"{', '.join(values[:-1])}, or {values[-1]}"


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


def _non_empty_string_defect(value: object) -> str | None:
    return None if isinstance(value, str) and value.strip() else "must be a non-empty string"


def _decision_kind_defect(value: object) -> str | None:
    kinds = tuple(DecisionKind)
    return None if value in kinds else f"must be {_one_of(kinds)}"


def _undo_defect(value: object) -> str | None:
    return None if value in tuple(Undo) else f"must be {Undo.REVERSIBLE} or {Undo.FINAL}"


def _letter_defect(letters: tuple[str, ...]) -> Callable[[object], str | None]:
    """The check that a value names one of the line's present `letters`;
    without a valid option count there are no letters to name, and the
    count's own refusal stands alone."""

    def defect(value: object) -> str | None:
        if not letters or value in letters:
            return None
        return f"must be one of {', '.join(letters)}"

    return defect


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
    ("example", _non_empty_string_defect),
    (_PICTURE, _expectation_picture_defect),
)
_EXPECTATION_KNOWN_KEYS = frozenset(
    {"text", "default", "ruling", "ruled_on", *(key for key, _ in EXPECTATION_OPTIONAL_FIELDS)}
)
_OPTION_TABLES = "option"
_OPTION_LINE_DECISION_KEYS = ("ruling", "ruled_on", "card_hash")
_OPTION_LINE_KNOWN_KEYS = frozenset(
    {
        "text",
        _OPTION_TABLES,
        *_OPTION_LINE_DECISION_KEYS,
        *OPTION_LINE_KEYS,
        *_OPTION_LINE_REFUSED_KEYS,
    }
)


def is_option_line(entry: Mapping[str, object]) -> bool:
    """Whether `entry` is an option line: exactly when it carries `option`."""
    return _OPTION_TABLES in entry


def _field_defect(path: str, reason: str | None) -> list[FieldDefect]:
    return [] if reason is None else [FieldDefect(path, f"{path} {reason}")]


def _unknown_key_defects(prefix: str, keys: list[str]) -> list[FieldDefect]:
    return [FieldDefect(f"{prefix}.{key}", f"unknown key {prefix}.{key}") for key in keys]


def _option_tables(options: object) -> list[tuple[str, dict[str, object]]]:
    """Each option of `options` that is a table, with its own index suffix."""
    if not isinstance(options, list):
        return []
    return [
        (f"option[{position}]", cast(dict[str, object], option))
        for position, option in enumerate(cast(list[object], options))
        if isinstance(option, dict)
    ]


def _present_letters(options: object) -> tuple[str, ...]:
    """The option letters, by position, of a line whose option count is valid."""
    if not isinstance(options, list):
        return ()
    count = len(cast(list[object], options))
    valid = OPTION_COUNT_MINIMUM <= count <= len(OPTION_LETTERS)
    return tuple(OPTION_LETTERS[:count]) if valid else ()


def _partial_decision_defect(prefix: str, entry: dict[str, object]) -> FieldDefect:
    """The one refusal of a partial decided state: some but not all of
    `ruling`, `ruled_on` and `card_hash`."""
    if "ruling" in entry and "ruled_on" not in entry:
        return FieldDefect(f"{prefix}.ruled_on", f"{prefix} carries ruling without ruled_on")
    if "ruling" in entry:
        return FieldDefect(f"{prefix}.card_hash", f"{prefix} is ruled without card_hash")
    beside = "ruled_on" if "ruled_on" in entry else "card_hash"
    return FieldDefect(f"{prefix}.ruling", f"{prefix} carries {beside} without ruling")


def _card_hash_defect(value: object) -> str | None:
    if isinstance(value, str) and _CARD_HASH_PATTERN.fullmatch(value):
        return None
    return "must be sha256: followed by 64 lowercase hex digits"


def _option_line_decision_defects(
    prefix: str, entry: dict[str, object], letters: tuple[str, ...]
) -> list[FieldDefect]:
    present = tuple(key in entry for key in _OPTION_LINE_DECISION_KEYS)
    if not any(present):
        return []
    if not all(present):
        return [_partial_decision_defect(prefix, entry)]
    ruled_on_reason = None if type(entry["ruled_on"]) is date else "must be a TOML local date"
    return [
        *_field_defect(f"{prefix}.ruling", _letter_defect(letters)(entry["ruling"])),
        *_field_defect(f"{prefix}.ruled_on", ruled_on_reason),
        *_field_defect(f"{prefix}.card_hash", _card_hash_defect(entry["card_hash"])),
    ]


def _option_line_key_defects(
    prefix: str, entry: dict[str, object], letters: tuple[str, ...]
) -> list[FieldDefect]:
    checks: dict[str, Callable[[object], str | None]] = {
        "question": _expectation_question_defect,
        "decision_kind": _decision_kind_defect,
        "recommended": _letter_defect(letters),
    }
    defects: list[FieldDefect] = []
    for key in OPTION_LINE_KEYS:
        path = f"{prefix}.{key}"
        if key not in entry:
            defects.append(FieldDefect(path, f"{path} is required"))
        elif key != _PICTURE:
            defects.extend(
                _field_defect(path, checks.get(key, _non_empty_string_defect)(entry[key]))
            )
    defects.extend(
        FieldDefect(f"{prefix}.{key}", f"{prefix}.{key} does not belong on an option line")
        for key in _OPTION_LINE_REFUSED_KEYS
        if key in entry
    )
    return defects


def _option_result_defects(path: str, option: dict[str, object]) -> list[FieldDefect]:
    has_picture, has_same_as_today = _PICTURE in option, _SAME_AS_TODAY in option
    if has_same_as_today and option[_SAME_AS_TODAY] is not True:
        return _field_defect(f"{path}.{_SAME_AS_TODAY}", "must be true")
    if has_same_as_today == has_picture:
        offending = _SAME_AS_TODAY if has_same_as_today else _PICTURE
        return [
            FieldDefect(
                f"{path}.{offending}",
                f"{path} must carry exactly one of picture and same_as_today = true",
            )
        ]
    if _CAPTION in option and not has_picture:
        return _field_defect(f"{path}.{_CAPTION}", "needs a picture beside it")
    return []


def _option_defects(path: str, option: dict[str, object]) -> list[FieldDefect]:
    defects: list[FieldDefect] = []
    for key in _OPTION_REQUIRED_KEYS:
        key_path = f"{path}.{key}"
        if key not in option:
            defects.append(FieldDefect(key_path, f"{key_path} is required"))
            continue
        check = _undo_defect if key == "undo" else _non_empty_string_defect
        defects.extend(_field_defect(key_path, check(option[key])))
    defects.extend(_option_result_defects(path, option))
    if _CAPTION in option:
        defects.extend(
            _field_defect(f"{path}.{_CAPTION}", _non_empty_string_defect(option[_CAPTION]))
        )
    return defects


def _options_defects(prefix: str, options: object) -> list[FieldDefect]:
    path = f"{prefix}.{_OPTION_TABLES}"
    if not isinstance(options, list):
        return [FieldDefect(path, f"{path} must be an array of tables")]
    defects: list[FieldDefect] = []
    if not _present_letters(options):
        maximum = len(OPTION_LETTERS)
        defects.append(
            FieldDefect(path, f"{prefix} must carry {OPTION_COUNT_MINIMUM} to {maximum} options")
        )
    for position, option in enumerate(cast(list[object], options)):
        option_path = f"{path}[{position}]"
        if isinstance(option, dict):
            defects.extend(_option_defects(option_path, cast(dict[str, object], option)))
        else:
            defects.append(FieldDefect(option_path, f"{option_path} must be a table"))
    return defects


def _option_line_pictures(prefix: str, entry: dict[str, object]) -> Iterator[tuple[str, object]]:
    """Every picture of an option line with its own field path: today's
    first, then each option's result in order."""
    if _PICTURE in entry:
        yield f"{prefix}.{_PICTURE}", entry[_PICTURE]
    for suffix, option in _option_tables(entry[_OPTION_TABLES]):
        if _PICTURE in option:
            yield f"{prefix}.{suffix}.{_PICTURE}", option[_PICTURE]


def _option_line_picture_defects(prefix: str, entry: dict[str, object]) -> list[FieldDefect]:
    pictures = list(_option_line_pictures(prefix, entry))
    defects = [
        defect
        for path, picture in pictures
        for defect in _field_defect(path, _expectation_picture_defect(picture))
    ]
    total = sum(len(picture.encode("utf-8")) for _, picture in pictures if isinstance(picture, str))
    if total > OPTION_LINE_PICTURES_MAXIMUM_BYTES:
        defects.append(
            FieldDefect(
                prefix,
                f"{prefix} pictures must total at most {OPTION_LINE_PICTURES_MAXIMUM_BYTES} bytes",
            )
        )
    return defects


def _option_line_defects(prefix: str, entry: dict[str, object]) -> list[FieldDefect]:
    """An option line's defects after `text`, in the fixed order: decided
    state, line keys, options, pictures, picture budget, unknown keys."""
    options = entry[_OPTION_TABLES]
    letters = _present_letters(options)
    return [
        *_option_line_decision_defects(prefix, entry, letters),
        *_option_line_key_defects(prefix, entry, letters),
        *_options_defects(prefix, options),
        *_option_line_picture_defects(prefix, entry),
        *_unknown_key_defects(prefix, sorted(set(entry) - _OPTION_LINE_KNOWN_KEYS)),
        *(
            defect
            for suffix, option in _option_tables(options)
            for defect in _unknown_key_defects(
                f"{prefix}.{suffix}", sorted(set(option) - set(OPTION_KEYS))
            )
        ),
    ]


def _edited_ruled_card_defects(prefix: str, entry: dict[str, object]) -> list[FieldDefect]:
    """A ruled option line whose stored `card_hash` no longer matches the
    card it carries: someone edited the card after the decision."""
    stored = entry.get("card_hash")
    if stored is None or stored == card_hash(entry):
        return []
    return [
        FieldDefect(
            f"{prefix}.card_hash",
            f"{prefix} was edited after its ruling; a changed ruling is a new line",
        )
    ]


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


def _yes_no_line_defects(prefix: str, entry: dict[str, object]) -> list[FieldDefect]:
    keys = set(entry)
    return [
        *_block_expectation_variant_defects(prefix, entry),
        *_block_expectation_optional_field_defects(prefix, entry),
        *(
            FieldDefect(
                f"{prefix}.{key}", f"{prefix}.{key} belongs to an option line; this line has none"
            )
            for key in sorted(keys & _OPTION_LINE_ONLY_KEYS)
        ),
        *_unknown_key_defects(
            prefix, sorted(keys - _EXPECTATION_KNOWN_KEYS - _OPTION_LINE_ONLY_KEYS)
        ),
    ]


def _block_expectation_entry_defects(index: int, entry: object) -> list[FieldDefect]:
    prefix = f"expectation[{index}]"
    if not isinstance(entry, dict):
        return [FieldDefect(prefix, f"{prefix} must be a table")]
    table = cast(dict[str, object], entry)
    form_defects = _option_line_defects if is_option_line(table) else _yes_no_line_defects
    defects = [
        *_field_defect(f"{prefix}.text", _non_empty_string_defect(table.get("text"))),
        *form_defects(prefix, table),
    ]
    if defects or not is_option_line(table):
        return defects
    return _edited_ruled_card_defects(prefix, table)


def block_expectation_defects(entries: list[object]) -> list[FieldDefect]:
    return [
        defect
        for index, entry in enumerate(entries)
        for defect in _block_expectation_entry_defects(index, entry)
    ]


def _present_values(table: Mapping[str, object], keys: tuple[str, ...]) -> dict[str, object]:
    """`table`'s values for `keys`, a key absent or `None` left out."""
    return {key: table[key] for key in keys if table.get(key) is not None}


def card_hash(entry: Mapping[str, object]) -> str:
    """The hash of exactly the fields a card shows, over parsed values:
    the present covered keys as compact, key-sorted JSON in UTF-8, hashed
    with SHA-256 and written `sha256:<64 lowercase hex>` (BODY-89). A key
    absent from `entry`, or `None`, is left out, so a covered key added
    later leaves every hash of a line without it unchanged."""
    if is_option_line(entry):
        covered = _present_values(entry, ("text", *OPTION_LINE_KEYS))
        options = cast(list[Mapping[str, object]], entry[_OPTION_TABLES])
        covered["options"] = [_present_values(option, OPTION_KEYS) for option in options]
    else:
        covered = _present_values(entry, _YES_NO_CARD_KEYS)
    canonical = json.dumps(covered, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _rendered_value(key: str, value: object) -> str:
    if key == _PICTURE:
        return f"{key} = {protocol.toml_multiline_string(cast(str, value))}"
    if isinstance(value, date):
        return f"{key} = {value.isoformat()}"
    if value is True:
        return f"{key} = true"
    return f"{key} = {protocol.toml_string(value)}"


def _rendered_present(table: Mapping[str, object], keys: tuple[str, ...]) -> list[str]:
    return [_rendered_value(key, table[key]) for key in keys if key in table]


def render_expectations(data: Mapping[str, object]) -> list[str]:
    """Every `[[expectation]]` entry in canonical order (BODY-88): `text`,
    the decided state, the card keys of its form, then each option table;
    a key is written only when present, and a line's own keys always come
    before its option tables, which TOML would otherwise bind them to."""
    lines: list[str] = []
    for expectation in cast(list[dict[str, object]], data.get("expectation", [])):
        option_line = is_option_line(expectation)
        lines.extend(("", "[[expectation]]"))
        lines.extend(
            _rendered_present(expectation, ("text", "default", *_OPTION_LINE_DECISION_KEYS))
        )
        card_keys = OPTION_LINE_KEYS if option_line else ("question", "example", _PICTURE)
        lines.extend(_rendered_present(expectation, card_keys))
        for option in cast(list[dict[str, object]], expectation.get(_OPTION_TABLES, [])):
            lines.extend(("", "[[expectation.option]]", *_rendered_present(option, OPTION_KEYS)))
    return lines
