"""The `rulings` command (`specs/rulings.spec.md`)."""
# ruff: noqa: T201 - the rulings command writes its result lines to stdout

from __future__ import annotations

import argparse
from collections.abc import Iterable
from enum import StrEnum

from . import body, protocol, report, rulings, workboard
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
    (`specs/rulings.spec.md`): `listed` the only success. `invalid_usage`
    covers `--repo` under `storage = state-ref` (PIN-04); every other
    refusal -- an unsupported forge host (BOARD-02), a state-ref checkout
    with no resolvable default branch (PIN-05) -- falls to `unavailable`,
    matching `ask`/`rule`/`brief`'s own catch-all."""

    LISTED = "listed"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    as_json = parsed.json
    try:
        issues = context.forge.list_open_board_issues()
        storage = context.config.storage
    except RepoMeaninglessUnderStateRefError as error:
        return report.refuse(_RulingsReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_RulingsReason.UNAVAILABLE, error, as_json=as_json)
    _rulings(issues, as_json=as_json, storage=storage)
    return 0
