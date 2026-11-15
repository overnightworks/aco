"""The expected and observed effects of a refused `aco land`."""

from dataclasses import dataclass
from enum import Enum

from cli_fixtures import CliRun
from github_fixtures import LandingWorld, landing_effects


@dataclass(frozen=True)
class ParserExit:
    exited: bool
    usage_prefix: str


class RefusalLength(Enum):
    UNCHECKED = "unchecked"
    WITHIN_LIMIT = "within-limit"
    EXACTLY_LIMIT = "exactly-limit"


def refusal_observations(
    world: LandingWorld,
    result: CliRun,
    sentence: str,
    *,
    length: RefusalLength = RefusalLength.UNCHECKED,
    parser_exit: ParserExit | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    observed = {"exit": result.status, "out": result.stdout, **landing_effects(world)}
    expected = {"exit": 2, "out": "", **world.unchanged}
    if parser_exit is not None:
        observed.update(
            {
                "exception": parser_exit.exited,
                "usage": result.stderr.startswith(parser_exit.usage_prefix),
                "last": result.stderr.splitlines()[-1] if result.stderr else "",
            }
        )
        expected.update({"exception": True, "usage": True, "last": sentence})
    else:
        observed["err"] = result.stderr
        expected["err"] = "ERROR: " + sentence + "\n"
    if length is not RefusalLength.UNCHECKED:
        actual_length = len(result.stderr.rstrip("\n"))
        exact = length is RefusalLength.EXACTLY_LIMIT
        observed["length"] = actual_length if exact else actual_length <= 200
        expected["length"] = 200 if exact else True
    return observed, expected
