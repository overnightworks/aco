"""The MCP server's `answer_step` tool and the `step` description that points to it
(`specs/mcp.spec.md`), driven without a process: a message in, the answer line out, the
writer a function the test passes."""

import dataclasses
import json
from collections.abc import Mapping
from typing import Any

import pytest

from aco import item_step, mcp_server


def _nothing(*_arguments: object) -> Mapping[str, object]:
    pytest.fail("a tool other than answer_step was called")


def _echoing(
    label: str, number: int, step: str, result: item_step.StepResult
) -> Mapping[str, object]:
    return {"repository": label, "item": number, "step": step, "result": dataclasses.asdict(result)}


def _reply(method: str, params: dict[str, object] | None = None) -> dict[str, Any]:
    tools = mcp_server.Tools(_nothing, _nothing, _nothing, _nothing, _echoing)
    message: dict[str, object] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        message["params"] = params
    line = mcp_server.reply(json.dumps(message), tools)
    assert line is not None
    return json.loads(line)


def _answer_step(**arguments: object) -> dict[str, Any]:
    given = {"repository": "o/r", "item": 4, "step": "Set it.", **arguments}
    return _reply("tools/call", {"name": "answer_step", "arguments": given})["result"]


def test_the_step_description_sends_an_answer_in_chat_to_answer_step() -> None:
    tools = _reply("tools/list")["result"]["tools"]

    description = {tool["name"]: tool["description"] for tool in tools}["step"]

    assert "answer_step" in description
    assert "head's own edit" not in description


@pytest.mark.parametrize(
    ("arguments", "result"),
    [
        ({"result": "Erfolgreich"}, {}),
        ({"result": "Fehlgeschlagen", "text": " Stayed red. "}, {"note": "Stayed red."}),
        ({"result": "report", "text": "All passed."}, {"report": "All passed."}),
    ],
    ids=["erfolgreich", "fehlgeschlagen", "report"],
)
def test_an_answer_step_call_hands_the_step_line_and_the_result_to_the_writer(
    arguments: dict[str, object], result: dict[str, str]
) -> None:
    answered = _answer_step(**{"step": " Set it. ", **arguments})

    assert answered["structuredContent"] == {
        "repository": "o/r",
        "item": 4,
        "step": "Set it.",
        "result": result,
    }


@pytest.mark.parametrize(
    "arguments",
    [
        {"result": "Fehlgeschlagen"},
        {"result": "report", "text": " "},
        {"result": "Erfolgreich", "text": "Extra."},
        {"result": "yes"},
        {"result": "Erfolgreich", "step": " "},
    ],
    ids=[
        "failure-no-text",
        "blank-report",
        "text-with-erfolgreich",
        "unknown-result",
        "blank-step",
    ],
)
def test_an_answer_step_call_with_a_defective_answer_never_reaches_the_writer(
    arguments: dict[str, object],
) -> None:
    result = _answer_step(**arguments)

    assert result["isError"] is True
