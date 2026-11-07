"""The MCP server's replies (`specs/mcp.spec.md`), driven without a process: a
message in, the answer line out, the inbox read a function the test passes."""

import json
from typing import Any, cast

import pytest

from aco import __version__, mcp_server, protocol

_INBOX: dict[str, object] = {"root": "/work", "repositories": [], "unreadable": []}


def _answer(message: object, read_inbox: mcp_server.ReadInbox = lambda: _INBOX) -> dict[str, Any]:
    line = mcp_server.reply(
        message if isinstance(message, str) else json.dumps(message), read_inbox
    )
    assert line is not None
    assert "\n" not in line
    return json.loads(line)


def _request(method: str, params: object = None, request_id: object = 1) -> dict[str, object]:
    message: dict[str, object] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def _call(arguments: object = None, name: str = "read_inbox") -> dict[str, object]:
    params: dict[str, object] = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    return _request("tools/call", params)


@pytest.mark.parametrize(
    ("asked", "answered"),
    [
        pytest.param("2025-11-25", "2025-11-25", id="newest"),
        pytest.param("2025-06-18", "2025-06-18", id="older"),
        pytest.param("2026-07-28", "2025-11-25", id="unknown-answers-newest"),
        pytest.param(None, "2025-11-25", id="none-given"),
    ],
)
def test_initialize_answers_the_clients_version_when_supported_else_the_newest(
    asked: str | None, answered: str
) -> None:
    params = {"capabilities": {}, "clientInfo": {"name": "host", "version": "1"}}
    if asked is not None:
        params["protocolVersion"] = asked

    result = _answer(_request("initialize", params))["result"]

    assert result["protocolVersion"] == answered
    assert result["capabilities"] == {"tools": {}}
    assert result["serverInfo"] == {"name": "aco", "version": __version__}
    assert isinstance(result["instructions"], str)


def test_initialize_without_params_still_answers() -> None:
    result = _answer(_request("initialize"))["result"]

    assert result["protocolVersion"] == mcp_server.SUPPORTED_PROTOCOL_VERSIONS[0]


def test_ping_answers_an_empty_result() -> None:
    assert _answer(_request("ping", request_id="p")) == {"jsonrpc": "2.0", "id": "p", "result": {}}


def test_tools_list_offers_the_read_only_inbox_tool_without_arguments() -> None:
    [tool] = _answer(_request("tools/list"))["result"]["tools"]

    assert tool["name"] == "read_inbox"
    assert tool["annotations"] == {"readOnlyHint": True}
    assert tool["inputSchema"]["type"] == "object"
    assert tool["inputSchema"]["properties"] == {}


@pytest.mark.parametrize("arguments", [None, {}], ids=["absent", "empty"])
def test_a_call_returns_the_inbox_as_structured_content_and_as_text(arguments: object) -> None:
    result = _answer(_call(arguments))["result"]

    assert result["isError"] is False
    assert result["structuredContent"] == _INBOX
    assert json.loads(result["content"][0]["text"]) == _INBOX
    assert result["content"][0]["type"] == "text"


def _refusing() -> dict[str, object]:
    raise protocol.ClaimError("/config.toml does not exist")


def _failing() -> dict[str, object]:
    raise RuntimeError("boom")


@pytest.mark.parametrize(
    ("read_inbox", "reason"),
    [
        pytest.param(_refusing, "/config.toml does not exist", id="refusal-names-the-file"),
        pytest.param(_failing, "RuntimeError: boom", id="unexpected-exception"),
    ],
)
def test_a_failed_read_is_a_tool_error_carrying_its_reason(
    read_inbox: mcp_server.ReadInbox, reason: str
) -> None:
    result = _answer(_call(), read_inbox)["result"]

    assert result["isError"] is True
    assert result["content"] == [{"type": "text", "text": reason}]
    assert "structuredContent" not in result


@pytest.mark.parametrize(
    "message",
    [
        pytest.param(_call(name="write_inbox"), id="unknown-tool"),
        pytest.param(_request("tools/call"), id="no-name"),
        pytest.param(_call({"limit": 1}), id="arguments-given"),
        pytest.param(_call([]), id="arguments-not-an-object"),
    ],
)
def test_a_call_of_an_unknown_tool_or_with_bad_arguments_is_an_invalid_params_error(
    message: dict[str, object],
) -> None:
    error = _answer(message)["error"]

    assert error["code"] == -32602


@pytest.mark.parametrize("method", ["server/discover", "resources/list", "tools/unknown"])
def test_any_other_method_is_not_found(method: str) -> None:
    answer = _answer(_request(method, request_id=7))

    assert (answer["id"], answer["error"]["code"]) == (7, -32601)


@pytest.mark.parametrize(
    "message",
    [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}},
        {"jsonrpc": "2.0", "method": "server/discover"},
    ],
)
def test_a_notification_is_never_answered(message: dict[str, object]) -> None:
    assert mcp_server.reply(json.dumps(message), lambda: _INBOX) is None


@pytest.mark.parametrize(
    ("text", "code"),
    [
        pytest.param("{not json", -32700, id="unparsable"),
        pytest.param("[]", -32600, id="array"),
        pytest.param('[{"jsonrpc": "2.0", "id": 1, "method": "ping"}]', -32600, id="batch"),
        pytest.param('"ping"', -32600, id="string"),
        pytest.param("7", -32600, id="number"),
        pytest.param('{"id": 1, "method": "ping"}', -32600, id="no-version"),
        pytest.param('{"jsonrpc": "2.0", "id": 1}', -32600, id="no-method"),
        pytest.param('{"jsonrpc": "2.0", "id": 1, "method": 3}', -32600, id="method-not-text"),
        pytest.param('{"jsonrpc": "2.0", "id": true, "method": "ping"}', -32600, id="boolean-id"),
        pytest.param('{"jsonrpc": "2.0", "id": null, "method": "ping"}', -32600, id="null-id"),
        pytest.param('{"jsonrpc": "2.0", "id": [1], "method": "ping"}', -32600, id="list-id"),
    ],
)
def test_malformed_input_is_answered_with_its_error_and_a_null_id(text: str, code: int) -> None:
    answer = _answer(text)

    assert (answer["id"], cast("dict[str, Any]", answer["error"])["code"]) == (None, code)
