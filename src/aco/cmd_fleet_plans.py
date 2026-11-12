"""The `fleet-plans` command (`specs/fleet-plans.spec.md`)."""
# ruff: noqa: T201 - the fleet-plans command writes its result lines to stdout

import argparse
from dataclasses import dataclass
from enum import StrEnum

from . import inbox, protocol, report, usage, workboard
from .session import RunContext

_DESCRIPTION = (
    f"List the open items labelled {workboard.FLEET_PLAN_LABEL} of every repository on this "
    "machine, read-only."
)
_GLOBAL_REPO_MESSAGE = "aco fleet-plans finds its repositories itself; --repo does not apply to it"


class _FleetPlansReason(StrEnum):
    """`aco fleet-plans`' own `--json` `reason` vocabulary
    (`specs/fleet-plans.spec.md`): `listed` the only success, `invalid_usage`
    `--repo`, `unavailable` every other refusal."""

    LISTED = "listed"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class _Listed:
    repository: str
    plan: inbox.Plan


def _listed(entries: tuple[inbox.Waiting | inbox.Unavailable, ...]) -> list[_Listed]:
    return sorted(
        (
            _Listed(entry.repository, plan)
            for entry in entries
            if isinstance(entry, inbox.Waiting)
            for plan in entry.plans
        ),
        key=lambda listed: (listed.repository, listed.plan.number),
    )


def _unavailable(read: inbox.Inbox) -> list[inbox.Unavailable]:
    """The repositories whose read failed, then the checkouts discovery could
    not read, named by their directory."""
    return [
        *(entry for entry in read.entries if isinstance(entry, inbox.Unavailable)),
        *(
            inbox.Unavailable(str(checkout.directory), checkout.reason)
            for checkout in read.unreadable
        ),
    ]


def _plan_json(listed: _Listed) -> dict[str, object]:
    plan = listed.plan
    return {
        "repository": listed.repository,
        "number": plan.number,
        "title": plan.title,
        "url": plan.url,
        "updated_on": plan.updated_on,
    }


def _plan_text(listed: _Listed) -> str:
    plan = listed.plan
    line = (
        f"{listed.repository}#{plan.number} {plan.updated_on}: {protocol.terminal_text(plan.title)}"
    )
    return line if plan.url is None else f"{line} {plan.url}"


def _unavailable_text(entry: inbox.Unavailable) -> str:
    return f"unavailable {entry.repository}: {protocol.terminal_text(entry.reason)}"


def add_parser(commands: usage.Subcommands, name: str) -> None:
    report.add_json_flag(commands.add_parser(name, help=_DESCRIPTION, description=_DESCRIPTION))


def run(parsed: argparse.Namespace, _context: RunContext) -> int:
    as_json = parsed.json
    if parsed.repo is not None:
        return report.refuse(_FleetPlansReason.INVALID_USAGE, _GLOBAL_REPO_MESSAGE, as_json=as_json)
    try:
        read = inbox.read(inbox.discovered(), inbox.read_repository)
    except protocol.ClaimError as error:
        return report.refuse(_FleetPlansReason.UNAVAILABLE, error, as_json=as_json)
    plans = _listed(read.entries)
    unavailable = _unavailable(read)
    if all(isinstance(entry, inbox.Unavailable) for entry in read.entries):
        reasons = (f"{entry.repository}: {entry.reason}" for entry in unavailable)
        return report.refuse(
            _FleetPlansReason.UNAVAILABLE,
            report.bounded_refusal(inbox.no_repository_read(read.root, reasons)),
            as_json=as_json,
        )
    if as_json:
        report.emit_json(
            True,
            _FleetPlansReason.LISTED,
            plans=[_plan_json(listed) for listed in plans],
            unavailable=[
                {"repository": entry.repository, "reason": entry.reason} for entry in unavailable
            ],
        )
        return 0
    lines = [*map(_plan_text, plans), *map(_unavailable_text, unavailable)]
    print("\n".join(lines) if lines else "No fleet-wide plans.")
    return 0
