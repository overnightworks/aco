"""The `mcp` command (`specs/mcp.spec.md`): the stdio loop, the inbox read and
the card, answer and step writes it serves."""

import argparse
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TextIO

from . import (
    body,
    decide,
    expectation_grammar,
    expectations,
    inbox,
    mcp_server,
    protocol,
    report,
    repositories,
    rulings,
    session,
    usage,
)
from .session import RunContext

_GLOBAL_REPO_MESSAGE = "aco mcp finds its repositories itself; --repo does not apply to it"


def _repository_reading(repository: repositories.Repository) -> inbox.Reading:
    # Looked up on the module at every call, so a replaced `run_context` (the
    # board's test forge) reaches every read.
    context = session.run_context(None).for_directory(repository.directory)
    return inbox.read_context(context)


def _discovered() -> repositories.Discovery:
    """One fresh scan of the configured root; refused, naming the file or the
    root, when there is no repository to read."""
    root = repositories.configured_root(repositories.config_path(os.environ, Path.home()))
    discovery = repositories.discover(root)
    if not discovery.repositories:
        reasons = "; ".join(f"{entry.directory}: {entry.reason}" for entry in discovery.unavailable)
        raise protocol.ClaimError(f"no repository could be read under {root} ({reasons})")
    return discovery


def read_inbox() -> dict[str, object]:
    """The read of every repository the scan found."""
    return inbox.inbox_json(inbox.read(_discovered(), _repository_reading))


def _context_of(label: str) -> RunContext:
    """The run context of the discovered repository `label`; refused when no
    repository found has that label."""
    found = {repository.label: repository for repository in _discovered().repositories}
    if label not in found:
        raise protocol.ClaimError(f"no repository {label} found; read_inbox lists them")
    return session.run_context(None).for_directory(found[label].directory)


def ask(label: str, number: int, card: Mapping[str, object]) -> dict[str, object]:
    """Puts `card` on item `number` of the discovered repository `label` in the
    item's turn, and answers its line as `aco rulings --json` gives it; refused
    when no repository found has that label."""
    context = _context_of(label)
    with decide.turn(
        context, number, command="ask", environment=os.environ, home=Path.home()
    ) as fresh:
        asked = decide.ask(context, fresh, card)
    return {
        "repository": label,
        "item": number,
        "written": asked.written,
        "line": rulings.line_json(asked.line),
    }


def record_answer(
    label: str, number: int, line: int, card_hash: str, answer: str | expectations.OtherAnswer
) -> dict[str, object]:
    """Records the operator's chat `answer` on line `line` of item `number` of the
    discovered repository `label` in the item's turn, as `aco rule --via chat`
    does, and answers the ruled line as `aco rulings --json` gives it with the
    lines still open; refused when no repository found has that label."""
    context = _context_of(label)
    choice = expectations.OptionChoice(answer, expectation_grammar.RulingVia.CHAT, card_hash)
    with decide.turn(
        context, number, command="record_answer", environment=os.environ, home=Path.home()
    ) as fresh:
        committed = decide.rule(context, fresh, [decide.LineOutcome(line, choice)], context.today())
    return {
        "repository": label,
        "item": number,
        "line": rulings.line_json(committed.lines[line - 1]),
        "open": committed.open_remaining,
    }


def _holds_step(title: str, step: object, *, wanted_title: str, wanted_step: str) -> bool:
    """Whether an item with `title` and `next` value `step` is the one a call
    for `wanted_title` and `wanted_step` marks, padding of `next` ignored."""
    return title == wanted_title and isinstance(step, str) and step.strip() == wanted_step


def _standing_step_item(context: RunContext, title: str, text: str) -> int | None:
    """The highest number among the open, readable items a member wrote with
    exactly `title` and a block `next` equal to `text`, whether or not they
    carry the label: what an earlier call of the same `step` left behind."""
    storage = context.config.storage
    standing = (
        issue.number
        for issue in context.forge.list_open_board_issues()
        if issue.author_is_member
        and _holds_step(
            issue.title,
            body.parse_body(issue.body, storage=storage).contract.next,
            wanted_title=title,
            wanted_step=text,
        )
    )
    return max(standing, default=None)


def step(label: str, text: str, target: int | str) -> dict[str, object]:
    """Marks the operator-only step `text` on the discovered repository `label`:
    on item `target` when it is a number, in that item's turn; otherwise on the
    open item already holding the title `target` and that step, or on a new
    item of that title. Refused when no repository found has that label and
    under `storage = "state-ref"`, before any read of its items."""
    context = _context_of(label)
    if context.config.storage is body.Storage.STATE_REF:
        raise protocol.ClaimError(
            f"{label} keeps its items in state-ref storage, where a step cannot be labelled; "
            "write it into the item's next with aco item edit"
        )
    if isinstance(target, int):
        _mark_in_turn(context, target, text, standing_title=None)
        return {"repository": label, "item": target, "step": text, "created": False}
    standing = _standing_step_item(context, target, text)
    if standing is not None and _mark_in_turn(context, standing, text, standing_title=target):
        return {"repository": label, "item": standing, "step": text, "created": False}
    opened = decide.open_step_item(context, target, text)
    return {"repository": label, "item": opened, "step": text, "created": True}


def _mark_in_turn(
    context: RunContext, number: int, text: str, *, standing_title: str | None
) -> bool:
    """Marks item `number` in its turn. With a `standing_title`, the item must
    still hold that title and the step `text` as the turn reads it; one another
    session changed since the lookup is left as it is and answers False."""
    with decide.turn(
        context, number, command="step", environment=os.environ, home=Path.home()
    ) as fresh:
        if standing_title is not None and not _holds_step(
            fresh.title,
            fresh.located.data.get("next"),
            wanted_title=standing_title,
            wanted_step=text,
        ):
            return False
        decide.mark_step(context, fresh, text)
    return True


def serve(requests: Iterable[bytes], replies: TextIO) -> None:
    """Answer each line of `requests` on `replies` until the lines end; a line
    that is no UTF-8 is answered as unparsable."""
    for request in requests:
        if not request.strip():
            continue
        try:
            answer = mcp_server.reply(
                request.decode("utf-8"), mcp_server.Tools(read_inbox, ask, record_answer, step)
            )
        except UnicodeDecodeError:
            answer = mcp_server.unparsable_reply()
        if answer is not None:
            replies.write(answer + "\n")
            replies.flush()


def add_parser(commands: usage.Subcommands, name: str) -> None:
    """`mcp`'s parser: it takes no flags."""
    commands.add_parser(
        name,
        help=(
            "serve the operator's inbox, a card writer, an answer writer and a step writer "
            "to an agent host over MCP on stdio"
        ),
    )


def run(parsed: argparse.Namespace, _context: RunContext) -> int:
    """Serve the MCP protocol on stdin and stdout until stdin ends."""
    if parsed.repo is not None:
        return report.render_error(protocol.ClaimError(_GLOBAL_REPO_MESSAGE))
    try:
        serve(sys.stdin.buffer, sys.stdout)
    except BrokenPipeError:
        # The host closed the pipe; the interpreter's own flush at exit must not
        # fail on it either.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    return 0
