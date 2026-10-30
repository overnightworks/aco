"""The CLI's `--json` flag, output envelope, refusal rendering
(`specs/output.spec.md`) and the piped-body reader every stdin-fed command
shares."""
# ruff: noqa: T201 - the one owner of the JSON envelope and the error line

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections.abc import Callable, Sequence
from enum import StrEnum

from . import protocol

CLI_ERROR_PREFIX = "ERROR: "
REFUSAL_LINE_LENGTH_LIMIT = 200
_REFUSAL_SENTENCE_LENGTH_LIMIT = REFUSAL_LINE_LENGTH_LIMIT - len(CLI_ERROR_PREFIX)

JSON_FLAG = "--json"
_JSON_HELP = "print the result as JSON instead of the human lines"


def add_json_flag(parser: argparse.ArgumentParser) -> None:
    """The one place `--json` is declared: a command that never calls this
    has no JSON mode at all, and `cli.main` matches this same spelling when
    argparse refuses before any namespace is filled, so the flag needs a
    single owner."""
    parser.add_argument(JSON_FLAG, action="store_true", help=_JSON_HELP)


def _stdin_file_mode() -> int | None:
    """The type bits of the descriptor on stdin, told without reading, since
    an idle pipe or socket a harness holds open would block a read forever;
    `None` for a closed stdin."""
    try:
        return os.fstat(sys.stdin.fileno()).st_mode
    except AttributeError, OSError, ValueError:
        return None


def stdin_carries_a_body() -> bool:
    """Whether stdin carries a body a command reads:
    a redirected file (`< body.md`) or a pipe
    (`printf ... |`). A socket -- what Claude Code's Bash tool hands a
    command -- a terminal, `/dev/null` or a closed stdin carry none, so the
    command never waits on an idle harness stdin."""
    mode = _stdin_file_mode()
    return mode is not None and (stat.S_ISREG(mode) or stat.S_ISFIFO(mode))


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
    reader can stop before it. `rule` and `brief` are its first
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


type RefusalReasons[Reason: StrEnum] = Sequence[tuple[type[protocol.ClaimError], Reason]]


def refusing_by_type[Reason: StrEnum](
    work: Callable[[], int],
    reasons: RefusalReasons[Reason],
    otherwise: Reason,
    *,
    as_json: bool,
) -> int:
    """`work`'s exit status, or its refusal reported through `refuse` with the
    reason of the first type in `reasons` it is an instance of, `otherwise`
    for any other -- a command's whole run, so a failure inside its shared
    write path still names that command's own reason."""
    try:
        return work()
    except protocol.ClaimError as error:
        reason = next((named for kind, named in reasons if isinstance(error, kind)), otherwise)
        return refuse(reason, error, as_json=as_json)
