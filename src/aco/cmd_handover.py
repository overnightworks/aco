"""The `handover` command (`specs/handover.spec.md`): the acting session takes over the claim a
predecessor session held, and the item records who took over from whom and why."""
# ruff: noqa: T201 - the handover command writes its result line to stdout

import argparse
import os
import uuid
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
        "item", type=workboard.parse_item_reference, help="the item whose claim is taken over"
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


def _live_claim(context: RunContext, number: int) -> protocol.ActiveClaim:
    protocol.require_state_ref(context.observation)
    try:
        return workboard.selected_store_claim(
            context.observation,
            protocol.IssueIdentity(number),
            None,
            None,
            context.config.storage,
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
    try:
        context.transition(subject, intent)
    except protocol.ClaimError as error:
        label = workboard.item_label(fresh.number, fresh.storage)
        raise protocol.ClaimUnavailableError(
            f"{label} records the handover, but the claim was not handed over: {error}; "
            "run the same command again"
        ) from error


def _emit(
    record: item_handover.ItemHandover,
    number: int,
    storage: body.Storage,
    *,
    repeated: bool,
    as_json: bool,
) -> None:
    if as_json:
        reason = _HandoverReason.ALREADY_HANDED_OVER if repeated else _HandoverReason.HANDED_OVER
        report.emit_json(
            True,
            reason,
            item=number,
            **{item_handover.FROM_KEY: record.from_agent, item_handover.TO_KEY: record.to_agent},
        )
        return
    verb = "ALREADY HANDED OVER" if repeated else "HANDED OVER"
    label = workboard.item_label(number, storage)
    print(f"{verb} {label}: {record.from_agent} -> {record.to_agent}")


def _take_over(parsed: argparse.Namespace, context: RunContext) -> int:
    """`handover`'s own work, every refusal raised by name for `run` to report."""
    number = int(parsed.item)
    wanted = item_handover.ItemHandover(
        parsed.from_agent, parsed.agent, _bounded_reason(parsed.reason), context.today()
    )
    afresh = context.observed_afresh()
    with decide.turn(
        afresh, number, command=_COMMAND, environment=os.environ, home=Path.home()
    ) as fresh:
        holder = _live_claim(afresh, number)
        label = workboard.item_label(number, fresh.storage)
        existing = item_handover.parse_handover(fresh.located.data)
        record = _handover_record(existing, wanted)
        if holder.agent == wanted.to_agent:
            if record != existing:
                raise HandoverRefusedError(f"this session already holds {label}")
            _emit(record, number, fresh.storage, repeated=True, as_json=parsed.json)
            return 0
        if holder.agent != wanted.from_agent:
            raise HandoverRefusedError(
                f"{label} is held by {holder.agent!r}, not by {wanted.from_agent!r}; "
                "pass the holder as --from"
            )
        _handed_over_claim(afresh, fresh, holder, record)
    _emit(record, number, fresh.storage, repeated=False, as_json=parsed.json)
    return 0


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`handover` with its own `--json` refusals for the whole command, the body write
    inside the shared path included."""
    return report.refusing_by_type(
        partial(_take_over, parsed, context),
        _REFUSAL_REASONS,
        _HandoverReason.UNAVAILABLE,
        as_json=parsed.json,
    )
