"""The `mcp` command (`specs/mcp.spec.md`): the stdio loop, the inbox read and
the card, answer and step writes it serves."""

import argparse
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TextIO

from . import (
    board_link,
    body,
    decide,
    earlier_rulings,
    expectation_grammar,
    expectations,
    inbox,
    item_step,
    item_wait,
    mcp_relay,
    mcp_server,
    protocol,
    report,
    repositories,
    rulings,
    usage,
    workboard,
)
from .session import RunContext

_HELP = (
    "serve the operator's inbox, a card writer, an answer writer, a step writer and "
    "a step answer writer to an agent host over MCP on stdio"
)
_GLOBAL_REPO_MESSAGE = "aco mcp finds its repositories itself; --repo does not apply to it"


def read_inbox() -> dict[str, object]:
    """The read of every repository the scan found."""
    return inbox.inbox_json(inbox.read(inbox.discovered(), inbox.read_repository))


def _context_in(discovery: repositories.Discovery, label: str) -> RunContext:
    """The run context of the repository `label` of `discovery`; refused when
    it has none of that label, the refusal pointing at `read_inbox`."""
    try:
        return inbox.context_in_checkout_of(discovery, label)
    except inbox.RepositoryNotFoundError as error:
        raise protocol.ClaimError(f"{error}; read_inbox lists them") from error


def _context_of(label: str) -> RunContext:
    """The run context of the discovered repository `label`; refused when no
    repository found has that label."""
    return _context_in(inbox.discovered(), label)


def _earlier(
    context: RunContext, asked: earlier_rulings.LineKey, area: str, tracked: tuple[str, ...]
) -> dict[str, object]:
    """The earlier rulings of `area` in the `tracked` repositories, `asked` left
    out, as the keys `ask` answers; when the search cannot answer completely,
    `earlier_unavailable` and one sentence naming why."""
    try:
        query = earlier_rulings.search_query(area, earlier_rulings.owners_of(tracked))
        found = earlier_rulings.recall(
            context.ruling_search.search(query), area=area, tracked=tracked, asked=asked
        )
    except (protocol.ClaimError, OSError) as error:
        reason = " ".join(str(error).split())
        return {"earlier_unavailable": f"the earlier rulings could not be searched: {reason}"}
    return earlier_rulings.earlier_json(found)


def ask(label: str, number: int, card: Mapping[str, object]) -> dict[str, object]:
    """Puts `card` on item `number` of the discovered repository `label` in the
    item's turn, and answers its line as `aco rulings --json` gives it and, once
    the turn has ended, the earlier rulings of the card's area in every
    repository found; refused when no repository found has that label."""
    discovery = inbox.discovered()
    context = _context_in(discovery, label)
    with decide.turn(
        context, number, command="ask", environment=os.environ, home=Path.home()
    ) as fresh:
        asked = decide.ask(context, fresh, card)
    tracked = tuple(repository.label for repository in discovery.repositories)
    key = earlier_rulings.LineKey(label, number, asked.line.index)
    return {
        "repository": label,
        "item": number,
        "written": asked.written,
        "line": rulings.line_json(asked.line),
        "link": board_link.configured_board_url_or_none(
            board_link.CardLink(label, number, asked.line.index)
        ),
        **_earlier(context, key, asked.line.area, tracked),
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
        committed = decide.rule(
            context,
            fresh,
            [decide.LineOutcome(line, choice)],
            context.today(),
            state=fresh.state_directory,
        )
    return {
        "repository": label,
        "item": number,
        "line": rulings.line_json(committed.lines[line - 1]),
        "open": committed.open_remaining,
    }


def answer_step(
    label: str, number: int, step_text: str, result: item_step.StepResult
) -> dict[str, object]:
    """Records the operator's chat `result` to the step of item `number` of the
    discovered repository `label` through `decide.answer_step_in_turn`, the turn
    `POST /api/step` takes; refused when no repository found has that label, when the
    item's step is not `step_text` or the item holds none. Answers the sentences the answer
    is owed, when there are any."""
    context = _context_of(label)
    answered = decide.answer_step_in_turn(
        context,
        number,
        result,
        lambda step: step.wait_text == step_text,
        item_step.AnswerChannel.CHAT,
        environment=os.environ,
        home=Path.home(),
    )
    if answered is None:
        raise protocol.ClaimError(
            f"#{number} no longer waits on the step {step_text!r}; read_inbox shows the current one"
        )
    note = {} if answered.note is None else {"note": answered.note}
    return {"repository": label, "item": number, "answered": True, **note}


def _holds_step(
    title: str, wait: item_wait.ItemWait | None, *, wanted_title: str, wanted_step: str
) -> bool:
    """Whether an item with `title` and `wait` is the one a call for `wanted_title`
    and `wanted_step` marks: it waits on the operator for exactly that step."""
    return title == wanted_title and item_wait.waits_on_operator(wait) and wait.step == wanted_step


def _standing_step_item(context: RunContext, title: str, text: str) -> int | None:
    """The highest number among the open, readable items a member wrote with
    exactly `title` and a block `wait.operator` equal to `text`, whether or not
    they carry the label: what an earlier call of the same `step` left behind."""
    storage = context.config.storage
    standing = (
        issue.number
        for issue in context.forge.list_open_board_issues()
        if issue.author_is_member
        and _holds_step(
            issue.title,
            body.parse_body(issue.body, storage=storage).wait,
            wanted_title=title,
            wanted_step=text,
        )
    )
    return max(standing, default=None)


def step(label: str, text: str, target: int | str, card: item_step.StepCard) -> dict[str, object]:
    """Marks the operator-only step `text`, detailed by `card`, on the discovered
    repository `label`:
    on item `target` when it is a number, in that item's turn; otherwise on the
    open item already holding the title `target` and that step, or on a new
    item of that title. Refused when no repository found has that label and
    under `storage = "state-ref"`, before any read of its items."""
    context = _context_of(label)
    if context.config.storage is body.Storage.STATE_REF:
        item_argument = (
            workboard.item_argument(target, context.config.storage)
            if isinstance(target, int)
            else "<item>"
        )
        raise protocol.ClaimError(
            f"{label} keeps its items in state-ref storage, where a step cannot be labelled; "
            f"write it into the item's wait with aco item edit {item_argument} --base <body_hash>; "
            f"aco item show {item_argument} --json prints the body_hash"
        )
    if isinstance(target, int):
        _mark_in_turn(context, target, text, card, standing_title=None)
        return _step_answer(label, target, text, created=False)
    standing = _standing_step_item(context, target, text)
    if standing is not None and _mark_in_turn(context, standing, text, card, standing_title=target):
        return _step_answer(label, standing, text, created=False)
    opened = decide.open_step_item(context, target, text, card)
    return _step_answer(label, opened, text, created=True)


def _step_answer(label: str, item: int, text: str, *, created: bool) -> dict[str, object]:
    """What `step` answers: the item, the step and the board's link to it."""
    return {
        "repository": label,
        "item": item,
        "step": text,
        "created": created,
        "link": board_link.configured_board_url_or_none(board_link.StepLink(label, item)),
    }


def _mark_in_turn(
    context: RunContext,
    number: int,
    text: str,
    card: item_step.StepCard,
    *,
    standing_title: str | None,
) -> bool:
    """Marks item `number` in its turn. With a `standing_title`, the item must
    still hold that title and the step `text` as the turn reads it; one another
    session changed since the lookup is left as it is and answers False."""
    with decide.turn(
        context, number, command="step", environment=os.environ, home=Path.home()
    ) as fresh:
        if standing_title is not None and not _holds_step(
            fresh.title,
            body.parse_body(fresh.body, storage=fresh.storage).wait,
            wanted_title=standing_title,
            wanted_step=text,
        ):
            return False
        decide.mark_step(context, fresh, text, card)
    return True


def serve(requests: Iterable[bytes], replies: TextIO) -> None:
    """Answer each line of `requests` on `replies` until the lines end; a line
    that is no UTF-8 is answered as unparsable."""
    tools = mcp_server.Tools(read_inbox, ask, record_answer, step, answer_step)

    def answer(request: bytes) -> str | None:
        try:
            return mcp_server.reply(request.decode("utf-8"), tools)
        except UnicodeDecodeError:
            return mcp_server.unparsable_reply()

    mcp_server.answer_lines(requests, replies, answer)


def add_parser(commands: usage.Subcommands, name: str) -> None:
    """`mcp`'s parser: its one flag, `--direct`, is the hand-off of `mcp_relay`."""
    commands.add_parser(name, help=_HELP).add_argument(
        "--direct", action="store_true", help=argparse.SUPPRESS
    )


def run(parsed: argparse.Namespace, _context: RunContext) -> int:
    """Serve the MCP protocol on stdin and stdout until stdin ends: in this process
    with `--direct`, else by handing each line to a fresh `aco mcp --direct`."""
    if parsed.repo is not None:
        return report.render_error(protocol.ClaimError(_GLOBAL_REPO_MESSAGE))
    try:
        (serve if parsed.direct else mcp_relay.relay)(sys.stdin.buffer, sys.stdout)
    except BrokenPipeError:
        # The host closed the pipe; the interpreter's own flush at exit must not
        # fail on it either.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    return 0
