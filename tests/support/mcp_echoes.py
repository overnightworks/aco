"""The MCP server's tool writers as test doubles, each handing back what it was called with,
and the server's replies driven without a process: a message in, the answer line out."""

import dataclasses
import json
from collections.abc import Mapping
from typing import Any, NoReturn

import pytest

from aco import expectations, item_step, mcp_server

INBOX: dict[str, object] = {"root": "/work", "repositories": [], "unreadable": []}
NEXT: dict[str, object] = {
    "root": "/work",
    "repositories": [{"repository": "owner/a", "next": {"ok": True, "reason": "work_item"}}],
    "unreadable": [],
}


def echoing_ask(label: str, number: int, card: Mapping[str, object]) -> Mapping[str, object]:
    return {"repository": label, "item": number, "written": True, "card": dict(card)}


def echoing_record(
    label: str,
    number: int,
    line: int,
    card_hash: str,
    answer: str | expectations.OtherAnswer,
) -> Mapping[str, object]:
    given = answer.text if isinstance(answer, expectations.OtherAnswer) else answer
    return {
        "repository": label,
        "item": number,
        "line": line,
        "card_hash": card_hash,
        "answer": given,
        "own_words": isinstance(answer, expectations.OtherAnswer),
    }


def echoing_step(
    label: str, step: str, target: int | str, card: item_step.StepCard
) -> Mapping[str, object]:
    return {"repository": label, "step": step, "target": target, "card": dataclasses.asdict(card)}


def echoing_answer_step(
    label: str, number: int, step: str, result: item_step.StepResult
) -> Mapping[str, object]:
    return {"repository": label, "item": number, "step": step, "result": dataclasses.asdict(result)}


def reaches_nothing(*_: object) -> NoReturn:
    pytest.fail("a call with a defective envelope reached the writer")


def serve(
    message: object,
    read_inbox: mcp_server.ReadInbox = lambda: INBOX,
    ask: mcp_server.Ask = echoing_ask,
    record_answer: mcp_server.RecordAnswer = echoing_record,
    step: mcp_server.Step = echoing_step,
    answer_step: mcp_server.AnswerStep = echoing_answer_step,
    read_next: mcp_server.ReadNext = lambda: NEXT,
) -> dict[str, Any]:
    tools = mcp_server.Tools(read_inbox, ask, record_answer, step, answer_step, read_next)
    line = mcp_server.reply(message if isinstance(message, str) else json.dumps(message), tools)
    assert line is not None
    assert "\n" not in line
    return json.loads(line)


def rpc_request(method: str, params: object = None, request_id: object = 1) -> dict[str, object]:
    message: dict[str, object] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def tool_call(arguments: object = None, name: str = "read_inbox") -> dict[str, object]:
    params: dict[str, object] = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    return rpc_request("tools/call", params)


def step_arguments(**changes: object) -> dict[str, object]:
    return {
        "repository": "owner/repo",
        "step": "Rotate the key.",
        "item": 7,
        "purpose": "Why.",
        "paste": "make rotate",
        "expected": "See that.",
        **changes,
    }


def without(arguments: dict[str, object], *keys: str) -> dict[str, object]:
    return {key: value for key, value in arguments.items() if key not in keys}
