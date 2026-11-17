"""The `planned_at_first_cut` of a container's `aco` block: how many children and
rows the container held when `aco cut` first cut it."""

from collections.abc import Mapping

PLANNED_AT_FIRST_CUT_KEY = "planned_at_first_cut"


def planned_defects(data: Mapping[str, object]) -> list[tuple[str, str]]:
    """The `(field, message)` refusal of the stamp, none when it is absent or a positive integer."""
    if PLANNED_AT_FIRST_CUT_KEY not in data:
        return []
    value = data[PLANNED_AT_FIRST_CUT_KEY]
    if type(value) is int and value >= 1:
        return []
    return [
        (
            PLANNED_AT_FIRST_CUT_KEY,
            f"{PLANNED_AT_FIRST_CUT_KEY} must be a positive integer",
        )
    ]


def render_planned(data: Mapping[str, object]) -> list[str]:
    """The block lines of the stamp, none when absent."""
    if PLANNED_AT_FIRST_CUT_KEY not in data:
        return []
    return ["", f"{PLANNED_AT_FIRST_CUT_KEY} = {data[PLANNED_AT_FIRST_CUT_KEY]}"]
