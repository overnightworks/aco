"""The MCP server's replies (`specs/mcp.spec.md`): one decoded JSON-RPC message
in, the line to answer with out. Free of I/O: the inbox read is passed in.

Speaks the `initialize` era of the protocol: `initialize`, `ping`, `tools/list`
and `tools/call`, with `read_inbox` the one tool.
"""

import json
from collections.abc import Callable, Mapping
from typing import Final

from . import __version__, protocol

SUPPORTED_PROTOCOL_VERSIONS: Final = ("2025-11-25", "2025-06-18")
"""Newest first: the first is the answer to a client that asks for another."""

TOOL_NAME: Final = "read_inbox"

type ReadInbox = Callable[[], Mapping[str, object]]
"""The inbox as JSON; raises `protocol.ClaimError` when it cannot be read."""

_PARSE_ERROR: Final = -32700
_INVALID_REQUEST: Final = -32600
_METHOD_NOT_FOUND: Final = -32601
_INVALID_PARAMS: Final = -32602

_INSTRUCTIONS: Final = (
    "Read the decisions waiting on the operator across every repository on this machine."
)
_TOOL: Final = {
    "name": TOOL_NAME,
    "title": "Read the operator's inbox",
    "description": (
        "The option lines that wait on the operator, across every repository found under "
        "the configured root: each item with its waiting lines, the repositories that "
        "could not be read, and the checkouts that could not be scanned."
    ),
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "annotations": {"readOnlyHint": True},
}


def reply(text: str, read_inbox: ReadInbox) -> str | None:
    """The line answering the message `text`, or None for a notification."""
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        return _error(None, _PARSE_ERROR, "invalid JSON")
    invalid = _invalid_request(message)
    if invalid is not None:
        return _error(None, _INVALID_REQUEST, invalid)
    if "id" not in message:
        return None
    return _answer(message["id"], message["method"], message.get("params"), read_inbox)


def _invalid_request(message: object) -> str | None:
    """Why `message` is no JSON-RPC 2.0 request, or None when it is one."""
    if not isinstance(message, dict):
        return "a request is one JSON object"
    if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return "not a JSON-RPC 2.0 request"
    request_id = message.get("id")
    if "id" in message and (isinstance(request_id, bool) or not isinstance(request_id, int | str)):
        return "the id is a string or an integer"
    return None


def _answer(request_id: int | str, method: str, params: object, read_inbox: ReadInbox) -> str:
    arguments = params if isinstance(params, dict) else {}
    match method:
        case "initialize":
            return _result(request_id, _initialized(arguments))
        case "ping":
            return _result(request_id, {})
        case "tools/list":
            return _result(request_id, {"tools": [_TOOL]})
        case "tools/call":
            return _call(request_id, arguments, read_inbox)
        case _:
            return _error(request_id, _METHOD_NOT_FOUND, f"method not found: {method}")


def _initialized(params: Mapping[str, object]) -> dict[str, object]:
    asked = params.get("protocolVersion")
    version = asked if asked in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "aco", "version": __version__},
        "instructions": _INSTRUCTIONS,
    }


def _call(request_id: int | str, params: Mapping[str, object], read_inbox: ReadInbox) -> str:
    if params.get("name") != TOOL_NAME:
        return _error(request_id, _INVALID_PARAMS, f"unknown tool: {params.get('name')}")
    if params.get("arguments", {}) != {}:
        return _error(request_id, _INVALID_PARAMS, f"{TOOL_NAME} takes no arguments")
    try:
        inbox = dict(read_inbox())
    except protocol.ClaimError as refusal:
        return _result(request_id, _tool_error(str(refusal)))
    except Exception as failure:
        return _result(request_id, _tool_error(f"{type(failure).__name__}: {failure}"))
    return _result(
        request_id,
        {
            "content": [{"type": "text", "text": json.dumps(inbox)}],
            "structuredContent": inbox,
            "isError": False,
        },
    )


def _tool_error(reason: str) -> dict[str, object]:
    return {"content": [{"type": "text", "text": reason}], "isError": True}


def _result(request_id: int | str, result: Mapping[str, object]) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id: int | str | None, code: int, message: str) -> str:
    error = {"code": code, "message": message}
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "error": error})
