"""The MCP server's `answer_step` tool and the `step` description that points to it
(`specs/mcp.spec.md`), driven without a process: a message in, the answer line out, the
writer a function the test passes."""

import json
from collections.abc import Mapping
from typing import Any

import pytest
from mcp_echoes import echoing_answer_step

from aco import mcp_server


def _nothing(*_arguments: object) -> Mapping[str, object]:
    pytest.fail("a tool other than answer_step was called")


def _reply(method: str, params: dict[str, object] | None = None) -> dict[str, Any]:
    tools = mcp_server.Tools(_nothing, _nothing, _nothing, _nothing, echoing_answer_step)
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
    ],
    ids=["erfolgreich", "fehlgeschlagen"],
)
def test_an_answer_step_call_hands_the_step_line_and_the_result_to_the_writer(
    arguments: dict[str, object], result: dict[str, str]
) -> None:
    """Spec: MCP-72"""
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
        {"result": "Fehlgeschlagen", "text": " "},
        {"result": "Erfolgreich", "text": "Extra."},
        {"result": "Erfolgreich", "step": " "},
        {"result": "Erfolgreich", "report": "All passed."},
    ],
    ids=[
        "failure-no-text",
        "failure-blank-text",
        "text-with-erfolgreich",
        "blank-step",
        "unknown-argument",
    ],
)
def test_an_answer_step_call_with_a_defective_answer_is_a_tool_error(
    arguments: dict[str, object],
) -> None:
    """Spec: MCP-75"""
    result = _answer_step(**arguments)

    assert result["isError"] is True


@pytest.mark.parametrize(
    "kind",
    [
        pytest.param("report", id="report"),
        pytest.param("yes", id="yes"),
        pytest.param(None, id="none"),
    ],
)
def test_an_answer_step_result_outside_the_two_is_a_tool_error_naming_them(
    kind: str | None,
) -> None:
    """Spec: MCP-75"""
    result = _answer_step(result=kind, text="All passed.")

    assert result["isError"] is True
    assert "result must be one of Erfolgreich, Fehlgeschlagen" in result["content"][0]["text"]


def test_an_answer_step_call_with_a_text_that_is_no_string_says_so() -> None:
    """Spec: MCP-75"""
    result = _answer_step(result="Fehlgeschlagen", text=3)

    assert result["isError"] is True
    assert "text must be a string" in result["content"][0]["text"]


def test_the_answer_step_schema_offers_the_two_results_and_names_no_report() -> None:
    """Spec: MCP-72"""
    tools = _reply("tools/list")["result"]["tools"]

    [answer_step] = [tool for tool in tools if tool["name"] == "answer_step"]

    assert answer_step["inputSchema"]["properties"]["result"]["enum"] == [
        "Erfolgreich",
        "Fehlgeschlagen",
    ]
    assert "report" not in json.dumps(answer_step)
