"""The `stats` command (`specs/stats.spec.md`)."""
# ruff: noqa: T201 - the stats command writes its result lines to stdout

import argparse
from enum import StrEnum

from . import lane_measure, lane_record, protocol, report, usage
from .lane_measure import Figure, SideStats, StageChoices
from .session import RunContext

_DESCRIPTION = (
    "Compare two groups of lanes by the records their releases left on refs/aco/state, "
    "read-only. A group is FROM..TO (ISO days, by the release commit's date) or tag:NAME "
    "(the lane's experiment tag)."
)
_REPO_MESSAGE = "aco stats reads this checkout's own state ref; --repo does not apply to it"
_SIDE_NAMES = ("A", "B")
_UNKNOWN = "unknown"


class _StatsReason(StrEnum):
    """`aco stats`' own `--json` `reason` vocabulary (`specs/stats.spec.md`): `compared` the
    only success, `invalid_usage` `--repo`, `unavailable` a state ref git cannot read. A group
    that is neither a range nor a tag is refused by the parser as `invalid_usage`."""

    COMPARED = "compared"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


def _figure_json(figure: Figure) -> dict[str, object]:
    return {"median": figure.median, "n": figure.n, "unknown": figure.unknown}


def _stage_json(choices: StageChoices) -> dict[str, object]:
    return {"choices": dict(choices.counts), "unknown": choices.unknown}


def _side_json(side: SideStats) -> dict[str, object]:
    return {
        "group": str(side.group),
        "lanes": side.lanes,
        "outcomes": {outcome.value: count for outcome, count in side.outcomes.items()},
        "figures": {name.value: _figure_json(figure) for name, figure in side.figures.items()},
        "stages": {stage.value: _stage_json(choices) for stage, choices in side.stages.items()},
    }


def _figure_text(name: str, figure: Figure) -> str:
    median = _UNKNOWN if figure.median is None else figure.median
    return f"  {name}: median {median}, n {figure.n}, unknown {figure.unknown}"


def _stage_text(name: str, choices: StageChoices) -> str:
    ranked = sorted(choices.counts.items(), key=lambda choice: (-choice[1], choice[0]))
    counted = [f"{choice} {count}" for choice, count in ranked]
    return f"  {name}: {', '.join([*counted, f'{_UNKNOWN} {choices.unknown}'])}"


def _side_text(name: str, side: SideStats) -> list[str]:
    outcomes = ", ".join(f"{outcome.value} {count}" for outcome, count in side.outcomes.items())
    return [
        f"{name} {side.group}: lanes {side.lanes} ({outcomes})",
        *(_figure_text(figure.value, side.figures[figure]) for figure in side.figures),
        *(_stage_text(stage.value, choices) for stage, choices in side.stages.items()),
    ]


def add_parser(commands: usage.Subcommands, name: str) -> None:
    stats = commands.add_parser(name, help=_DESCRIPTION, description=_DESCRIPTION)
    for side in _SIDE_NAMES:
        stats.add_argument(
            side,
            type=lane_measure.parse_group,
            metavar=f"{side}_GROUP",
            help="FROM..TO as YYYY-MM-DD days, both inclusive, or tag:NAME",
        )
    report.add_json_flag(stats)


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    as_json = parsed.json
    if parsed.repo is not None:
        return report.refuse(_StatsReason.INVALID_USAGE, _REPO_MESSAGE, as_json=as_json)
    try:
        lanes = lane_record.recorded_lanes(context.toplevel, context.observation.tip)
    except protocol.ClaimError as error:
        return report.refuse(_StatsReason.UNAVAILABLE, error, as_json=as_json)
    sides = [lane_measure.measure(getattr(parsed, name), lanes) for name in _SIDE_NAMES]
    if as_json:
        report.emit_json(
            True,
            _StatsReason.COMPARED,
            **{
                name.lower(): _side_json(side)
                for name, side in zip(_SIDE_NAMES, sides, strict=True)
            },
        )
        return 0
    for name, side in zip(_SIDE_NAMES, sides, strict=True):
        print("\n".join(_side_text(name, side)))
    return 0
