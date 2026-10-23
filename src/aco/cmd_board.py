"""The `board` command (`specs/board.spec.md`)."""

from __future__ import annotations

import argparse
from enum import StrEnum

from . import board_read, protocol, report, workboard
from .session import RepoMeaninglessUnderStateRefError, RunContext


class _BoardReason(StrEnum):
    """`aco board`'s own `--json` `reason` vocabulary (issue #412,
    `specs/board.spec.md`): `projected` the only success. `invalid_usage`
    covers a bare `aco board` naming no `--json` (BOARD-44) and `--repo`
    under `storage = state-ref` (PIN-04); every other refusal -- an
    unsupported forge host (BOARD-02), a state-ref checkout with no
    resolvable default branch (PIN-05) -- falls to `unavailable`, matching
    `ask`/`rule`/`brief`'s own catch-all."""

    PROJECTED = "projected"
    INVALID_USAGE = "invalid_usage"
    UNAVAILABLE = "unavailable"


class _BoardNoModeUsageError(protocol.ClaimError):
    """No `--json` given (BOARD-44): the retired text table (issue #420,
    #390 Befund 13) leaves `board` with no default mode of its own any
    more, so a bare `aco board` must name `--json` instead of guessing."""


_BOARD_NO_MODE_MESSAGE = "aco board requires --json"


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    as_json = parsed.json
    try:
        if not as_json:
            raise _BoardNoModeUsageError(_BOARD_NO_MODE_MESSAGE)
        projected = board_read.observed_board(context).board
    except _BoardNoModeUsageError as error:
        return report.refuse(_BoardReason.INVALID_USAGE, error, as_json=as_json)
    except RepoMeaninglessUnderStateRefError as error:
        return report.refuse(_BoardReason.INVALID_USAGE, error, as_json=as_json)
    except protocol.ClaimError as error:
        return report.refuse(_BoardReason.UNAVAILABLE, error, as_json=as_json)
    report.emit_json(True, _BoardReason.PROJECTED, **workboard.board_payload(projected))
    return 0
