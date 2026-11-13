"""The `Routing:` line of a merge commit or an `--abandoned` reason, read into typed
fields (`specs/lane-record.spec.md`, LANREC-13..LANREC-20).

Reading is tolerant: a field that does not parse is unknown (`None`, or a stage missing from
`stages`), and the others still read. Only tokens a trailer may carry leave this module; a
finding's text, a `hard:` text and every other free text stay behind."""

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class RoutingStage(StrEnum):
    BUILD = "build"
    FIX = "fix"
    REVIEW = "review"
    TEST = "test"
    GATE = "gate"
    LAND = "land"


_STAGE_ORDER = tuple(RoutingStage)
NO_STAGE = "none"
_STAGES_THAT_MAY_BE_ABSENT = frozenset({RoutingStage.FIX, RoutingStage.TEST, RoutingStage.GATE})

_LINE = re.compile(r"^Routing: (.*)$", re.MULTILINE)
_MODEL_AND_EFFORT = re.compile(r"[a-z0-9][a-z0-9.-]*/[a-z0-9-]+")
_FIX_ROUNDS_LABEL = re.compile(r"\bFix rounds:")
_FIX_ROUNDS = re.compile(r"\bFix rounds: (\d{1,3})(?=\.(?:\s|$)|, hard:|$)")
_EXPERIMENT_LABEL = re.compile(r"(?:^|\. )Experiment:")
EXPERIMENT_TAG = re.compile(r"[a-z0-9-]{1,40}")
_EXPERIMENT = re.compile(rf"(?:^|\. )Experiment: ({EXPERIMENT_TAG.pattern})(?=\.(?:\s|$)|$)")
_BLOCKING_LABEL = re.compile(r"(?:^|\. )Blocking:")
_BLOCKING = re.compile(r"(?:^|\. )Blocking: (.*)$")
_NO_BLOCKING_LEAD = re.compile(r"none(?=\.|\s|$)")
_NO_BLOCKING = re.compile(r"none\.?")
_ARROW = "→"
_STAGE_AFTER_ARROW = re.compile(_ARROW + r"\s*[A-Za-z][A-Za-z0-9-]*")
_COUNTED_FINDING = re.compile(r"\s*(\d{1,3})\u00d7")


@dataclass(frozen=True)
class RoutingLine:
    """What one routing line states. `stages` holds `<model>/<effort>` or `none` for each stage
    that parsed; the three counts are `None` when unknown."""

    stages: Mapping[RoutingStage, str]
    fix_rounds: int | None
    blocking: int | None
    experiment: str | None


def parse_routing_line(message: str) -> RoutingLine | None:
    """The one `Routing:` line of `message`, or `None` when it holds none or several."""
    lines = _LINE.findall(message)
    if len(lines) != 1:
        return None
    body = lines[0].strip()
    first_blocking = _BLOCKING_LABEL.search(body)
    before_blocking = body if first_blocking is None else body[: first_blocking.start()]
    blocking = _sentence_value(_BLOCKING_LABEL, _BLOCKING, body)
    rounds = _sentence_value(_FIX_ROUNDS_LABEL, _FIX_ROUNDS, before_blocking)
    experiment = _sentence_value(_EXPERIMENT_LABEL, _EXPERIMENT, before_blocking)
    return RoutingLine(
        stages=_stages(body.split(". ", 1)[0]),
        fix_rounds=None if rounds is None else int(rounds[1]),
        blocking=None if blocking is None else _blocking_count(blocking[1].strip()),
        experiment=None if experiment is None else experiment[1],
    )


def _sentence_value(
    label: re.Pattern[str], value: re.Pattern[str], text: str
) -> re.Match[str] | None:
    """The match of `value` when `text` holds exactly one sentence that starts with `label`: a
    doubled sentence is ambiguous, so it reads as unknown."""
    return value.search(text) if len(label.findall(text)) == 1 else None


def _stages(text: str) -> Mapping[RoutingStage, str]:
    appearance: list[RoutingStage] = []
    named: defaultdict[RoutingStage, list[str]] = defaultdict(list)
    for piece in text.removesuffix(".").split(";"):
        name, _, choice = piece.strip().partition(" ")
        if name in RoutingStage:
            appearance.append(RoutingStage(name))
            named[RoutingStage(name)].append(choice)
    if appearance != sorted(appearance, key=_STAGE_ORDER.index):
        return MappingProxyType({})
    return MappingProxyType(
        {
            stage: choices[0]
            for stage, choices in named.items()
            if len(choices) == 1 and stage_choice_fits(stage, choices[0])
        }
    )


def stage_choice_fits(stage: RoutingStage, choice: str) -> bool:
    """Whether `choice` is what `stage` may name: `<model>/<effort>`, or `none` where a stage
    may be absent."""
    if choice == NO_STAGE:
        return stage in _STAGES_THAT_MAY_BE_ABSENT
    return _MODEL_AND_EFFORT.fullmatch(choice) is not None


def _blocking_count(text: str) -> int | None:
    if _NO_BLOCKING_LEAD.match(text):
        return 0 if _NO_BLOCKING.fullmatch(text) else None
    findings = [finding for finding in text.split(";") if finding.strip()]
    if not findings or not all(_is_one_finding(finding) for finding in findings):
        return None
    counts = [_finding_count(finding) for finding in findings]
    return None if 0 in counts else sum(counts)


def _finding_count(finding: str) -> int:
    counted = _COUNTED_FINDING.match(finding)
    return int(counted[1]) if counted else 1


def _is_one_finding(finding: str) -> bool:
    return finding.count(_ARROW) == 1 and _STAGE_AFTER_ARROW.search(finding) is not None
