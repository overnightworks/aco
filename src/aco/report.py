"""The CLI's output envelope, refusal rendering (`specs/output.spec.md`) and
the piped-body reader every stdin-fed command shares."""

from __future__ import annotations

import json
import sys
from enum import StrEnum

from . import protocol

CLI_ERROR_PREFIX = "ERROR: "
REFUSAL_LINE_LENGTH_LIMIT = 200
_REFUSAL_SENTENCE_LENGTH_LIMIT = REFUSAL_LINE_LENGTH_LIMIT - len(CLI_ERROR_PREFIX)

JSON_FLAG = "--json"


def read_piped_body() -> str:
    """The body text a command reads from stdin only: an agent pipes the file
    in (`aco check - < body.md`) rather than naming a path the CLI would have
    to trust."""
    try:
        return sys.stdin.read()
    except UnicodeDecodeError as error:
        raise protocol.ClaimError(
            f"stdin is not valid UTF-8: {error}; pipe the body as UTF-8 text"
        ) from error


def emit_json(ok: bool, reason: StrEnum, **payload: object) -> None:
    """The one `--json` envelope owner (`specs/output.spec.md`):
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


def render_error(error: protocol.ClaimError | str) -> int:
    """Write the CLI error line to stderr and return its refusal exit code."""
    print(f"{CLI_ERROR_PREFIX}{error}", file=sys.stderr)
    return 2


def bounded_refusal(sentence: str) -> str:
    """`sentence` as one bounded refusal line: a pull request's own text
    (a check name, a head's board configuration key) may carry a newline or
    a terminal escape, so it is shown as `next` shows foreign text (`\\n`,
    `\\x1b`) before the length cap applies."""
    return _cut_to(protocol.terminal_text(sentence), _REFUSAL_SENTENCE_LENGTH_LIMIT)


def refusal_around_foreign_text(template: str, foreign_text: str, **words: object) -> str:
    """`template` with `{foreign}` replaced by `foreign_text` (a forge's error)
    shown as `bounded_refusal` shows foreign text, and cut alone so that the
    words around it always survive."""
    room = _REFUSAL_SENTENCE_LENGTH_LIMIT - len(template.format(foreign="", **words))
    shown = _cut_to(protocol.terminal_text(foreign_text), room)
    return template.format(foreign=shown, **words)


def _cut_to(printable: str, limit: int) -> str:
    if len(printable) <= limit:
        return printable
    return printable[: limit - 1] + "…"


def refuse(
    reason: StrEnum, error: protocol.ClaimError | str, *, as_json: bool, **payload: object
) -> int:
    """One shared refusal report for every `--json` command and
    for `main`'s own pre-start checks: `ERROR: <sentence>`
    on stderr through `render_error`, then
    -- only under `--json` -- the envelope naming this call's own reason
    instead of the dropped `error` key. Exit `2`, the one exit every refusal
    past the parser still uses. `error` is a `ClaimError` or a plain sentence
    (`str`); additional `payload` keys retain their given order, with
    `message` last."""
    status = render_error(error)
    if as_json:
        emit_json(False, reason, **payload, message=str(error))
    return status
