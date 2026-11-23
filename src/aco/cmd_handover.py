"""The `handover` command (`specs/handover.spec.md`): the acting session takes over the claim a
predecessor session held; an item records who took over from whom and why, a lane claim has
only its claim transition."""
# ruff: noqa: T201 - the handover command writes its result line to stdout

import argparse
import os
import uuid
from collections.abc import Mapping
from dataclasses import replace
from enum import StrEnum
from functools import partial
from pathlib import Path

from . import body, decide, item_handover, protocol, report, store, usage, workboard
from .session import RepoMeaninglessUnderStateRefError, RunContext

_COMMAND = "handover"


class _HandoverReason(StrEnum):
    """`aco handover`'s own `--json` `reason` vocabulary (`specs/handover.spec.md`):
    `handed_over` and `already_handed_over` are the successes."""

    HANDED_OVER = "handed_over"
    ALREADY_HANDED_OVER = "already_handed_over"
    PRECONDITION_FAILED = "precondition_failed"
    INVALID_ITEM = "invalid_item"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


class HandoverRefusedError(protocol.ClaimError):
    """HANDOVER-05: the claim is not there to take over, or not held by `--from`."""


class HandoverUsageError(protocol.ClaimError):
    """HANDOVER-08: a `--reason` that is not one bounded non-empty line."""


_REFUSAL_REASONS: report.RefusalReasons[_HandoverReason] = (
    (HandoverRefusedError, _HandoverReason.PRECONDITION_FAILED),
    (decide.InvalidTargetError, _HandoverReason.INVALID_ITEM),
    (HandoverUsageError, _HandoverReason.INVALID_USAGE),
    (RepoMeaninglessUnderStateRefError, _HandoverReason.INVALID_USAGE),
)


def add_parser(commands: usage.Subcommands, name: str) -> None:
    parser = commands.add_parser(name, help="take over the claim a predecessor session held")
    parser.add_argument(
        "item",
        nargs="?",
        type=workboard.parse_item_reference,
        help="the item whose claim is taken over; give it or --branch",
    )
    parser.add_argument(
        "--branch",
        help="the branch of the issue-less lane whose claim is taken over; give it or the item",
    )
    parser.add_argument(
        "--from",
        dest="from_agent",
        required=True,
        help="the agent that holds the claim now; the claim is refused unless it is the holder",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="why this session takes over, one line: the restart order that gives it the authority",
    )
    parser.add_argument("--agent", help="the acting agent's name; the new holder")
    report.add_json_flag(parser)


def _bounded_reason(reason: str) -> str:
    try:
        return protocol.outbound_text(reason, "reason", maximum=item_handover.REASON_TEXT_MAXIMUM)
    except protocol.ClaimError as error:
        raise HandoverUsageError(str(error)) from error


def _live_claim(
    context: RunContext, identity: protocol.ClaimIdentity, branch: str | None
) -> protocol.ActiveClaim:
    protocol.require_state_ref(context.observation)
    try:
        return workboard.selected_store_claim(
            context.observation, identity, branch, None, context.config.storage
        )
    except protocol.ClaimError as error:
        raise HandoverRefusedError(str(error)) from error


def _handover_record(
    existing: item_handover.ItemHandover | None, wanted: item_handover.ItemHandover
) -> item_handover.ItemHandover:
    """`wanted`, dated as an earlier record of the same takeover so a repeat is no new one."""
    if existing is not None and replace(existing, on=wanted.on) == wanted:
        return existing
    return wanted


def _handed_over_claim(
    context: RunContext,
    fresh: decide.FreshItem,
    holder: protocol.ActiveClaim,
    record: item_handover.ItemHandover,
) -> None:
    """The record on the item first, then the claim's own transition: a refused body write
    leaves the claim as it stood, and a claim write that fails after it says the record
    stands and that the same command finishes the takeover."""
    new_data = {
        **fresh.located.data,
        item_handover.HANDOVER_KEY: item_handover.handover_table(record),
    }
    decide.write_item_body(
        context.forge_writer,
        fresh.number,
        body.replace_block(fresh.body, fresh.located, new_data),
        replacing=fresh.body,
    )
    try:
        _hand_over_claim(context, holder, record)
    except protocol.ClaimError as error:
        label = workboard.item_label(fresh.number, fresh.storage)
        raise protocol.ClaimUnavailableError(
            f"{label} records the handover, but the claim was not handed over: {error}; "
            "run the same command again"
        ) from error


def _hand_over_claim(
    context: RunContext, holder: protocol.ActiveClaim, record: item_handover.ItemHandover
) -> None:
    """The one claim transition of a takeover, the same for an item and a lane."""
    intent = protocol.HandoverIntent(
        claim_id=holder.claim_id,
        previous_agent=record.from_agent,
        agent=record.to_agent,
        operation_id=uuid.uuid4().hex,
    )
    subject = store.transition_subject(_COMMAND, holder.identity, holder.branch)
    subject = replace(
        subject,
        trailers=(
            f"{item_handover.FROM_KEY}: {record.from_agent}",
            f"{item_handover.TO_KEY}: {record.to_agent}",
            f"{item_handover.REASON_KEY}: {record.reason}",
        ),
    )
    context.transition(subject, intent)


def _emit(
    record: item_handover.ItemHandover,
    label: str,
    target: Mapping[str, object],
    *,
    repeated: bool,
    as_json: bool,
) -> None:
    """The success line, or its `--json` object naming `target` (`item` or `lane`)."""
    if as_json:
        reason = _HandoverReason.ALREADY_HANDED_OVER if repeated else _HandoverReason.HANDED_OVER
        report.emit_json(
            True,
            reason,
            **target,
            **{item_handover.FROM_KEY: record.from_agent, item_handover.TO_KEY: record.to_agent},
        )
        return
    verb = "ALREADY HANDED OVER" if repeated else "HANDED OVER"
    print(f"{verb} {label}: {record.from_agent} -> {record.to_agent}")


def _take_over_item(
    parsed: argparse.Namespace, context: RunContext, wanted: item_handover.ItemHandover
) -> int:
    number = int(parsed.item)
    afresh = context.observed_afresh()
    with decide.turn(
        afresh, number, command=_COMMAND, environment=os.environ, home=Path.home()
    ) as fresh:
        holder = _live_claim(afresh, protocol.IssueIdentity(number), None)
        label = workboard.item_label(number, fresh.storage)
        existing = item_handover.parse_handover(fresh.located.data)
        record = _handover_record(existing, wanted)
        if holder.agent == wanted.to_agent:
            if record != existing:
                raise HandoverRefusedError(f"this session already holds {label}")
            _emit(record, label, {"item": number}, repeated=True, as_json=parsed.json)
            return 0
        if holder.agent != wanted.from_agent:
            raise _not_the_holder(label, holder, wanted)
        _handed_over_claim(afresh, fresh, holder, record)
    _emit(record, label, {"item": number}, repeated=False, as_json=parsed.json)
    return 0


def _not_the_holder(
    label: str, holder: protocol.ActiveClaim, wanted: item_handover.ItemHandover
) -> HandoverRefusedError:
    return HandoverRefusedError(
        f"{label} is held by {holder.agent!r}, not by {wanted.from_agent!r}; "
        "pass the holder as --from"
    )


def _take_over_lane(
    parsed: argparse.Namespace, context: RunContext, wanted: item_handover.ItemHandover
) -> int:
    """A lane claim has no item body: its one claim transition carries the reason, and a
    session that already holds the claim finds the takeover done."""
    branch = str(parsed.branch)
    holder = _live_claim(context.observed_afresh(), protocol.LaneIdentity(), branch)
    label = f"lane {branch}"
    target = {"lane": branch}
    if holder.agent != wanted.from_agent:
        raise _not_the_holder(f"lane {branch!r}", holder, wanted)
    if holder.agent == wanted.to_agent:
        _emit(wanted, label, target, repeated=True, as_json=parsed.json)
        return 0
    _hand_over_claim(context, holder, wanted)
    _emit(wanted, label, target, repeated=False, as_json=parsed.json)
    return 0


def _take_over(parsed: argparse.Namespace, context: RunContext) -> int:
    """`handover`'s own work, every refusal raised by name for `run` to report."""
    wanted = item_handover.ItemHandover(
        parsed.from_agent, parsed.agent, _bounded_reason(parsed.reason), context.today()
    )
    if (parsed.item is None) == (parsed.branch is None):
        raise HandoverUsageError("name either an item or --branch, not both and not neither")
    if parsed.item is None:
        return _take_over_lane(parsed, context, wanted)
    return _take_over_item(parsed, context, wanted)


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`handover` with its own `--json` refusals for the whole command, the body write
    inside the shared path included."""
    return report.refusing_by_type(
        partial(_take_over, parsed, context),
        _REFUSAL_REASONS,
        _HandoverReason.UNAVAILABLE,
        as_json=parsed.json,
    )
