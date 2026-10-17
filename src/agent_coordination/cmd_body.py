"""The `body` command (`specs/body.spec.md`)."""

from __future__ import annotations

import argparse
import sys
from enum import StrEnum

from . import (
    body,
    protocol,
    report,
)
from .session import (
    RunContext,
)


def read_body_check_input() -> str:
    """`body --check`'s body text, read from stdin only (issue #262 Sonar
    S8707): an agent pipes the file in (`aco body --check < body.md`)
    rather than naming a path the CLI would have to trust."""
    try:
        return sys.stdin.read()
    except UnicodeDecodeError as error:
        raise protocol.ClaimError(
            f"stdin is not valid UTF-8: {error}; pipe the body as UTF-8 text"
        ) from error


class _BodyCheckReason(StrEnum):
    """`aco body --check`'s own `--json` `reason` vocabulary
    (`specs/body.spec.md`, issue #404): `valid`/`malformed`/`incomplete`
    mirror `body.BodyShapeVerdict`'s own three values -- the same
    body-shape decision `check <item>`'s own `cmd_check._CheckReason` reads."""

    VALID = body.BodyShapeVerdict.VALID.value
    MALFORMED = body.BodyShapeVerdict.MALFORMED.value
    INCOMPLETE = body.BodyShapeVerdict.INCOMPLETE.value
    UNAVAILABLE = "unavailable"


def _body_check_report(check: body.BodyShapeCheck, *, as_json: bool) -> int:
    """The one rendering of a `body --check` answer: `body.body_shape_check`'s
    own sentences, never truncated to the first, since there is no live
    item here to refuse a single verdict about."""
    ok = check.verdict is body.BodyShapeVerdict.VALID
    if as_json:
        report.emit_json(ok, _BodyCheckReason(check.verdict.value), defects=list(check.defects))
    elif check.defects:
        for defect in check.defects:
            print(defect, file=sys.stderr)
    else:
        print("body ok")
    return 0 if ok else 2


def run(parsed: argparse.Namespace, context: RunContext) -> int:
    """`body --check` is forge-free (issue #262), the same way `status` and
    `bootstrap` are (issue #245): it reads stdin only, never an issue, a
    live claim, a filesystem path, or the forge's own `blocked_by`
    relation, so it never asks the `session.RunContext` for its forge (`cli.main` dispatches
    it outside `cli._dispatch`, exactly like `status`). It still reads the
    repository's own storage pin (issue #287): `[record]` is a known key
    under `storage = "state-ref"` and an unknown one under
    `storage = "github"`, the same gate `session._state_ref_forge`'s own items
    already read through `state_board._decode_item`."""
    as_json = parsed.json
    try:
        config = context.config
        raw_body = read_body_check_input()
    except protocol.ClaimError as error:
        return report.refuse(_BodyCheckReason.UNAVAILABLE, error, as_json=as_json)
    check = body.body_shape_check(raw_body, storage=config.storage)
    return _body_check_report(check, as_json=as_json)
