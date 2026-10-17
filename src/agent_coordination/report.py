"""The CLI's output envelope and refusal rendering (`specs/output.spec.md`)."""

from __future__ import annotations

import json
import sys
from enum import StrEnum

from . import protocol

CLI_ERROR_PREFIX = "ERROR: "

JSON_FLAG = "--json"


def emit_json(ok: bool, reason: StrEnum, **payload: object) -> None:
    """The one `--json` envelope owner (issue #396, `specs/output.spec.md`):
    `ok` and `reason` always print first, in that order -- `reason` a
    stable enum token, never an `error` object -- then the payload in the
    order given, with an optional `message` (free prose) moved last so a
    reader can stop before it. `ask`, `rule`, and `brief` are its first
    callers, on success and on every refusal alike. `reason` is typed
    `StrEnum` -- the shared base every command's own reason vocabulary
    already subclasses -- so a loose string can never reach this envelope."""
    message = payload.pop("message", None)
    envelope: dict[str, object] = {"ok": ok, "reason": reason}
    envelope.update(payload)
    if message is not None:
        envelope["message"] = message
    print(json.dumps(envelope))


def refuse(reason: StrEnum, error: protocol.ClaimError, *, as_json: bool, **payload: object) -> int:
    """One shared refusal report for every `--json` command (issue #396) and
    for `_dispatch`'s own pre-start checks (issue #425): `ERROR: <sentence>`
    on stderr exactly as `main`'s own generic sink always printed it, then
    -- only under `--json` -- the envelope naming this call's own reason
    instead of the dropped `error` key. Exit `2`, the one exit every refusal
    past the parser still uses."""
    print(f"{CLI_ERROR_PREFIX}{error}", file=sys.stderr)
    if as_json:
        emit_json(False, reason, **payload, message=str(error))
    return 2
