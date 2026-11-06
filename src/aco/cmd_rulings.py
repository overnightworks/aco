"""The `rulings` command (`specs/rulings.spec.md`)."""
# ruff: noqa: T201 - the rulings command writes its result lines to stdout

import argparse
import sys
from collections.abc import Iterable
from enum import StrEnum

from . import board_read, body, forge, protocol, report, rulings, workboard
from .session import RepoMeaninglessUnderStateRefError, RunContext


def _rulings(issues: Iterable[workboard.Issue], *, as_json: bool, storage: body.Storage) -> None:
    rows = rulings.rows(issues, storage=storage)
    if as_json:
        report.emit_json(
            True,
            _RulingsReason.LISTED,
            rulings=[rulings.row_json(row) for row in rows],
        )
        return
    if not rows:
        print("No expectation lines.")
        return
    print("\n".join(rulings.row_text(row, storage) for row in rows))


class _RulingsReason(StrEnum):
    """`aco rulings`' own `--json` `reason` vocabulary
    (`specs/rulings.spec.md`): `listed` the only success. `missing` is a
    named number in neither number space (RUL-25) and `invalid_item` a named
    pull request (RUL-26, `rule`'s and `withdraw`'s token for it);
    `invalid_usage` covers `--repo` under `storage = state-ref` (PIN-04);
    every other refusal -- an unsupported forge host (BOARD-02), a state-ref
    checkout with no resolvable default branch (PIN-05) -- falls to
    `unavailable`, matching `ask`/`rule`/`brief`'s own catch-all."""

    LISTED = "listed"
    MISSING = "missing"
    INVALID_ITEM = "invalid_item"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


def _one_item(client: forge.ForgeReader, number: int) -> tuple[workboard.Issue] | _RulingsReason:
    """The one named item as a single-row listing, open or closed, or the
    refusal reason when the number is no issue (RUL-24, RUL-25)."""
    reference = client.item_reference(number)
    if reference.state is forge.ItemState.MISSING:
        return _RulingsReason.MISSING
    if reference.is_landing:
        return _RulingsReason.INVALID_ITEM
    return (
        workboard.Issue(
            number=number,
            title=reference.title or "",
            labels=(),
            body=reference.body or "",
            created_at="",
            updated_at="",
        ),
    )


def _refuse_named_item(
    reason: _RulingsReason, number: int, repository: str, storage: body.Storage, *, as_json: bool
) -> int:
    label = workboard.item_label(number, storage)
    if reason is _RulingsReason.MISSING:
        finding = f"does not exist in {repository}"
        if as_json:
            report.emit_json(False, reason, kind="missing", number=number, message=finding)
        else:
            print(f"REFUSED: {label} {finding}", file=sys.stderr)
        return 2
    return report.refuse(
        reason, board_read.pull_request_sentence(number, command="rulings"), as_json=as_json
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "item",
        nargs="?",
        type=workboard.parse_item_reference,
        help="list this one item, open or closed, instead of every open item",
    )
    report.add_json_flag(parser)


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    as_json = parsed.json
    try:
        storage = context.config.storage
        client = context.forge
        if parsed.item is None:
            issues: Iterable[workboard.Issue] = client.list_open_board_issues()
        else:
            one = _one_item(client, parsed.item)
            if isinstance(one, _RulingsReason):
                return _refuse_named_item(
                    one, parsed.item, client.repository.path, storage, as_json=as_json
                )
            issues = one
    except RepoMeaninglessUnderStateRefError as error:
        return report.refuse(_RulingsReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_RulingsReason.UNAVAILABLE, error, as_json=as_json)
    _rulings(issues, as_json=as_json, storage=storage)
    return 0
