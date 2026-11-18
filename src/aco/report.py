"""The CLI's `--json` flag, the shared `--line` parser, output envelope, refusal rendering
(`specs/output.spec.md`) and the piped-body reader every stdin-fed command
shares."""
# ruff: noqa: T201 - the one owner of the JSON envelope and the error line

import argparse
import json
import os
import stat
import sys
from collections.abc import Callable, Sequence
from enum import StrEnum

from . import forge, protocol, usage, workboard

CLI_ERROR_PREFIX = "ERROR: "
REFUSAL_LINE_LENGTH_LIMIT = 200
_REFUSAL_SENTENCE_LENGTH_LIMIT = REFUSAL_LINE_LENGTH_LIMIT - len(CLI_ERROR_PREFIX)
_PATH_ELLIPSIS = "…/"

JSON_FLAG = "--json"
_JSON_HELP = "print the result as JSON instead of the human lines"


def add_json_flag(parser: argparse.ArgumentParser, help_text: str = _JSON_HELP) -> None:
    """The one place `--json` is declared: a command that never calls this
    has no JSON mode at all, and `cli.main` matches this same spelling when
    argparse refuses before any namespace is filled, so the flag needs a
    single owner. A command with no human output passes its own `help_text`."""
    parser.add_argument(JSON_FLAG, action="store_true", help=help_text)


def add_lines_command_parser(
    commands: usage.Subcommands, name: str, *, help: str, item_help: str, lines_help: str
) -> None:
    """The parser of a command that names option lines of one item (`withdraw`):
    the item, the repeatable `--line N` and `--json`, all required but `--json`."""
    add_lines_arguments(
        commands.add_parser(name, help=help),
        item_help=item_help,
        lines_help=lines_help,
        optional=False,
    )


def add_lines_arguments(
    parser: argparse.ArgumentParser, *, item_help: str, lines_help: str, optional: bool
) -> None:
    """The item, the repeatable `--line N` and `--json` of `parser`; `optional`
    leaves the item and the lines out together, for a command with a form that
    names neither (`wait`'s board form)."""
    parser.add_argument(
        "item", nargs="?" if optional else None, type=workboard.parse_item_reference, help=item_help
    )
    parser.add_argument(
        "--line",
        dest="lines",
        action="append",
        type=int,
        required=not optional,
        metavar="N",
        help=lines_help,
    )
    add_json_flag(parser)


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
    return template.format(foreign=cut_foreign_text(foreign_text, room), **words)


def refusal_around_foreign_path(template: str, path_text: str, **words: object) -> str:
    """`template` with `{foreign}` replaced by `path_text`, shown as `refusal_around_foreign_text`
    shows foreign text, but a path that does not fit loses the front of its directory (`…/`),
    so the file name and the words around it survive whole; the line passes its bound only
    when the file name and those words do not fit together. A path that the marker would not
    shorten is shown whole."""
    room = _REFUSAL_SENTENCE_LENGTH_LIMIT - len(template.format(foreign="", **words))
    printable = protocol.terminal_text(path_text)
    if len(printable) <= room:
        return template.format(foreign=printable, **words)
    file_name = printable.rpartition("/")[2]
    kept = printable[len(printable) - (room - len(_PATH_ELLIPSIS)) :]
    # `kept` starts mid-name; the first `/` ends that name, and a kept part with none holds no
    # whole directory name, so the file name stands alone.
    shortened = _PATH_ELLIPSIS + (kept.partition("/")[2] or file_name)
    if len(shortened) >= len(printable):
        shortened = printable
    return template.format(foreign=shortened, **words)


def cut_foreign_text(foreign_text: str, limit: int) -> str:
    """`foreign_text` shown as `bounded_refusal` shows foreign text, cut to `limit` characters."""
    return _cut_to(protocol.terminal_text(foreign_text), limit)


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


class BodyCheckReason(StrEnum):
    """The `--json` `reason` of a refusal that answers the forge's check of a
    body write (`specs/output.spec.md`): shared by every writer that answers it."""

    OVERWRITTEN = "overwritten"
    NOT_VERIFIED = "not_verified"


class ForgeReachReason(StrEnum):
    """The `--json` `reason` of a refusal whose cause is a forge aco could not
    reach (`specs/output.spec.md`): shared by every command that tells it from
    a forge that refused."""

    UNREACHABLE = "unreachable"


def refuse_checked_write(
    answer: forge.ForgeBodyWrittenError,
    *,
    as_json: bool,
    sentence: str | None = None,
    **payload: object,
) -> int:
    """The refusal for a body write the forge's check found overwritten or
    unverified: `overwritten` with `kept` after `payload`, or `not_verified`.
    It prints `sentence`, the answer's own when none is given."""
    shown = str(answer) if sentence is None else sentence
    if isinstance(answer, forge.ForgeBodyOverwrittenError):
        return refuse(
            BodyCheckReason.OVERWRITTEN, shown, as_json=as_json, **payload, kept=answer.kept
        )
    return refuse(BodyCheckReason.NOT_VERIFIED, shown, as_json=as_json, **payload)


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
    write path still names that command's own reason. The forge's check of a
    write that landed (`forge.ForgeBodyWrittenError`) comes first, through
    `refuse_checked_write`."""
    try:
        return work()
    except forge.ForgeBodyWrittenError as error:
        return refuse_checked_write(error, as_json=as_json)
    except protocol.ClaimError as error:
        reason = next((named for kind, named in reasons if isinstance(error, kind)), otherwise)
        return refuse(reason, error, as_json=as_json)
