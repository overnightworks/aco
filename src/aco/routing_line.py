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


NO_STAGE = "none"
_STAGES_THAT_MAY_BE_ABSENT = frozenset({RoutingStage.FIX, RoutingStage.TEST, RoutingStage.GATE})

_LINE = re.compile(r"^Routing: (.*)$", re.MULTILINE)
_MODEL_AND_EFFORT = re.compile(r"[a-z0-9][a-z0-9.-]*/[a-z0-9-]+")
_FIX_ROUNDS = re.compile(r"\bFix rounds: (\d{1,3})(?=[,.\s]|$)")
_EXPERIMENT = re.compile(r"(?:^|\. )Experiment: ([a-z0-9-]{1,40})(?=\.|\s|$)")
_BLOCKING = re.compile(r"(?:^|\. )Blocking: (.*)$")
_NO_BLOCKING = re.compile(r"none(?:\.|$)")
_ARROW = "→"
_STAGE_AFTER_ARROW = re.compile(_ARROW + r"\s*[A-Za-z][A-Za-z0-9-]*")


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
    rounds = _FIX_ROUNDS.search(body)
    experiment = _EXPERIMENT.search(body)
    blocking = _BLOCKING.search(body)
    return RoutingLine(
        stages=_stages(body.split(". ", 1)[0]),
        fix_rounds=None if rounds is None else int(rounds[1]),
        blocking=None if blocking is None else _blocking_count(blocking[1].strip()),
        experiment=None if experiment is None else experiment[1],
    )


def _stages(text: str) -> Mapping[RoutingStage, str]:
    named: defaultdict[RoutingStage, list[str]] = defaultdict(list)
    for piece in text.removesuffix(".").split(";"):
        name, _, choice = piece.strip().partition(" ")
        if name in RoutingStage:
            named[RoutingStage(name)].append(choice)
    return MappingProxyType(
        {
            stage: choices[0]
            for stage, choices in named.items()
            if len(choices) == 1 and _fits(stage, choices[0])
        }
    )


def _fits(stage: RoutingStage, choice: str) -> bool:
    if choice == NO_STAGE:
        return stage in _STAGES_THAT_MAY_BE_ABSENT
    return _MODEL_AND_EFFORT.fullmatch(choice) is not None


def _blocking_count(text: str) -> int | None:
    if _NO_BLOCKING.match(text):
        return 0
    findings = [finding for finding in text.split(";") if finding.strip()]
    if findings and all(_is_one_finding(finding) for finding in findings):
        return len(findings)
    return None


def _is_one_finding(finding: str) -> bool:
    return finding.count(_ARROW) == 1 and _STAGE_AFTER_ARROW.search(finding) is not None
