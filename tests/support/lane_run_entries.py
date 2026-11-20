"""Stored run entries of a lane, as `aco lane-record begin` and `add` leave them."""

import json

from lane_record_fixtures import four, lane_record_object, marked

from aco import lane_record, lane_runs
from aco.routing_line import RoutingStage

END_TIP = "b" * 40
START_TIP = "a" * 40


def begun(run: str, *, follows: bool = True, start_tip: str | None = None) -> lane_runs.RunEntry:
    """A run begun and not added."""
    return lane_runs.RunEntry(run, start_tip, follows)


def added(
    run: str,
    *ran: str,
    marker: str = "m",
    follows: bool = True,
    start_tip: str | None = None,
    **changes: object,
) -> lane_runs.RunEntry:
    """A run that ran `ran`, added with a record that states `changes` over a valid one whose
    stage choices carry `marker`; a change to `None` leaves the field out."""
    content = lane_record_object(
        **{"stages": marked(marker), "misses": four(0, 0, 0, 0), **changes}
    )
    stated = {name: value for name, value in content.items() if value is not None}
    record = lane_record.parse_record_file(json.dumps(stated).encode())
    stored = lane_runs.RunAdded(END_TIP, tuple(RoutingStage(stage) for stage in ran), record)
    return lane_runs.RunEntry(run, start_tip, follows, stored)


def not_following(run: str, *ran: str, marker: str = "m", **changes: object) -> lane_runs.RunEntry:
    """A run added that does not follow the run before it."""
    return added(run, *ran, marker=marker, follows=False, start_tip=START_TIP, **changes)
