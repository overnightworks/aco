"""The MCP server's replies (`specs/mcp.spec.md`): one decoded JSON-RPC message
in, the line to answer with out. Free of I/O: the inbox read, the card write and
the answer write are passed in.

Speaks the `initialize` era of the protocol: `initialize`, `ping`, `tools/list`
and `tools/call`, with the tools `read_inbox`, `ask` and `record_answer`.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, cast

from . import __version__, expectation_grammar, expectations, protocol

SUPPORTED_PROTOCOL_VERSIONS: Final = ("2025-11-25", "2025-06-18")
"""Newest first: the first is the answer to a client that asks for another."""

READ_INBOX: Final = "read_inbox"
ASK: Final = "ask"
RECORD_ANSWER: Final = "record_answer"

type ReadInbox = Callable[[], Mapping[str, object]]
"""The inbox as JSON; raises `protocol.ClaimError` when it cannot be read."""

type Ask = Callable[[str, int, Mapping[str, object]], Mapping[str, object]]
"""Puts a card on an item of a repository, named as `read_inbox` lists it, and
answers as JSON; raises `protocol.ClaimError` when it refuses."""

type RecordAnswer = Callable[
    [str, int, int, str, str | expectations.OtherAnswer], Mapping[str, object]
]
"""Records the operator's chat answer, a letter or his own words, on a line of an
item of a repository, named as `read_inbox` lists it, given the card's hash, and
answers as JSON; raises `protocol.ClaimError` when it refuses."""


@dataclass(frozen=True)
class Tools:
    """What each tool does, passed in by the process that serves them."""

    read_inbox: ReadInbox
    ask: Ask
    record_answer: RecordAnswer


_PARSE_ERROR: Final = -32700
_INVALID_REQUEST: Final = -32600
_METHOD_NOT_FOUND: Final = -32601
_INVALID_PARAMS: Final = -32602

_INSTRUCTIONS: Final = (
    "Read the decisions waiting on the operator across every repository on this machine "
    f"with {READ_INBOX}, put a decision card of your own on an item with {ASK}, and record "
    f"the answer the operator gave in this chat with {RECORD_ANSWER}."
)
_ENVELOPE_KEYS: Final = ("repository", "item")
_OPTION: Final = "option"
_OTHER: Final = "other"
_RECORD_KEYS: Final = (*_ENVELOPE_KEYS, "line", "card_hash", _OPTION, _OTHER)


def _string(description: str | None = None) -> dict[str, object]:
    return (
        {"type": "string"}
        if description is None
        else {"type": "string", "description": description}
    )


def _option_property(key: str) -> dict[str, object]:
    if key == expectation_grammar.SAME_AS_TODAY:
        return {"const": True}
    if key == expectation_grammar.UNDO:
        return {"type": "string", "enum": [undo.value for undo in expectation_grammar.Undo]}
    return _string()


def _line_property(key: str) -> dict[str, object]:
    if key == expectation_grammar.DECISION_KIND:
        kinds = [kind.value for kind in expectation_grammar.DecisionKind]
        return {"type": "string", "enum": kinds}
    if key == expectation_grammar.RECOMMENDED:
        return {"type": "string", "enum": list(expectation_grammar.OPTION_LETTERS)}
    return _string()


def _ask_schema() -> dict[str, object]:
    grammar = expectation_grammar
    options = {
        "type": "array",
        "minItems": grammar.OPTION_COUNT_MINIMUM,
        "maxItems": len(grammar.OPTION_LETTERS),
        "items": {
            "type": "object",
            "properties": {key: _option_property(key) for key in grammar.OPTION_KEYS},
            "required": list(grammar.OPTION_REQUIRED_KEYS),
            "additionalProperties": False,
        },
    }
    return {
        "type": "object",
        "properties": {
            "repository": _string("the repository as read_inbox lists it, owner/repo"),
            "item": {"type": "integer", "description": "the number of an open item"},
            **{key: _line_property(key) for key in grammar.CARD_LINE_KEYS},
            grammar.OPTIONS: options,
        },
        "required": [
            *_ENVELOPE_KEYS,
            *(
                key
                for key in grammar.CARD_LINE_KEYS
                if key not in grammar.OPTION_LINE_OPTIONAL_KEYS
            ),
            grammar.OPTIONS,
        ],
        "additionalProperties": False,
    }


def _record_answer_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "repository": _string("the repository as read_inbox lists it, owner/repo"),
            "item": {"type": "integer", "description": "the number of the item"},
            "line": {"type": "integer", "minimum": 1, "description": "the line's index"},
            "card_hash": _string("the line's card_hash"),
            _OPTION: {
                "type": "string",
                "enum": list(expectation_grammar.OPTION_LETTERS),
                "description": "the option the operator chose; give this or other",
            },
            _OTHER: _string("the operator's own words instead of an option; give this or option"),
        },
        "required": [*_ENVELOPE_KEYS, "line", "card_hash"],
        "additionalProperties": False,
    }


_TOOLS: Final = (
    {
        "name": READ_INBOX,
        "title": "Read the operator's inbox",
        "description": (
            "The option lines that wait on the operator, across every repository found under "
            "the configured root: each item with its waiting lines, the repositories that "
            "could not be read, and the checkouts that could not be scanned."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": ASK,
        "title": "Ask the operator a decision",
        "description": (
            "Puts one decision card, an option line with 2 to 4 options, on an open item the "
            "operator's repository holds, and answers the line with its index and card_hash. "
            "The card then shows in read_inbox, aco rulings and the board. The same card asked "
            "again writes nothing and answers the line that stands, with the operator's ruling "
            "once there is one; revise a card sent back by withdrawing it and asking again. "
            "An item whose body is incomplete is refused. A refusal that says a body was "
            "written, not verified, is safe to repeat; one that says it was written over a "
            "change means the card stands."
        ),
        "inputSchema": _ask_schema(),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    },
    {
        "name": RECORD_ANSWER,
        "title": "Record the operator's answer",
        "description": (
            "Records the answer the operator gave in this chat on one option line, as a "
            "letter or in his own words; use it only for an answer he gave, never for your "
            "own choice. The line and its card_hash come from read_inbox or, for a line sent "
            "back to its head, which read_inbox leaves out, from aco rulings --json. The "
            "answer binds like a ruling on the board and shows in read_inbox, aco rulings "
            "and the board; a line already ruled stays as it is and the call is refused. "
            "A refusal that says a body was written means the answer reached the item, "
            "unless it says it was overwritten in the meantime."
        ),
        "inputSchema": _record_answer_schema(),
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True},
    },
)


def reply(text: str, tools: Tools) -> str | None:
    """The line answering the message `text`, or None for a notification."""
    try:
        message = json.loads(text)
    except ValueError, RecursionError:
        # Past the parser's limits (digit count, nesting) it raises these, not JSONDecodeError.
        return unparsable_reply()
    invalid = _invalid_request(message)
    if invalid is not None:
        return _error(None, _INVALID_REQUEST, invalid)
    if "id" not in message:
        return None
    return _answer(message["id"], message["method"], message.get("params"), tools)


def unparsable_reply() -> str:
    """The line answering a message that cannot be parsed as JSON."""
    return _error(None, _PARSE_ERROR, "invalid JSON")


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


def _answer(request_id: int | str, method: str, params: object, tools: Tools) -> str:
    arguments = params if isinstance(params, dict) else {}
    match method:
        case "initialize":
            return _result(request_id, _initialized(arguments))
        case "ping":
            return _result(request_id, {})
        case "tools/list":
            return _result(request_id, {"tools": list(_TOOLS)})
        case "tools/call":
            return _call(request_id, arguments, tools)
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


@dataclass(frozen=True)
class _Handler:
    """One tool: the defects of its arguments, which it judges before anything is
    read, and what it does with sound ones."""

    defects: Callable[[Mapping[str, object]], list[str]]
    run: Callable[[Mapping[str, object]], Mapping[str, object]]


def _handlers(tools: Tools) -> dict[str, _Handler]:
    return {
        READ_INBOX: _Handler(_read_inbox_defects, lambda arguments: tools.read_inbox()),
        ASK: _Handler(_ask_defects, lambda arguments: _ask(tools.ask, arguments)),
        RECORD_ANSWER: _Handler(
            _record_answer_defects, lambda arguments: _record_answer(tools.record_answer, arguments)
        ),
    }


def _call(request_id: int | str, params: Mapping[str, object], tools: Tools) -> str:
    name = params.get("name")
    arguments = params.get("arguments", {})
    handler = _handlers(tools).get(name) if isinstance(name, str) else None
    if handler is None:
        return _error(request_id, _INVALID_PARAMS, f"unknown tool: {name}")
    if not isinstance(arguments, dict):
        return _error(request_id, _INVALID_PARAMS, f"{name} takes its arguments as an object")
    defects = handler.defects(arguments)
    if defects:
        return _result(request_id, _tool_error("; ".join(defects)))
    return _answered(request_id, lambda: handler.run(arguments))


def _ask(ask: Ask, arguments: Mapping[str, object]) -> Mapping[str, object]:
    card = {key: value for key, value in arguments.items() if key not in _ENVELOPE_KEYS}
    return ask(cast(str, arguments["repository"]), cast(int, arguments["item"]), card)


def _record_answer(
    record_answer: RecordAnswer, arguments: Mapping[str, object]
) -> Mapping[str, object]:
    """The call of a writer with arguments whose defects were already refused."""
    answer = (
        expectations.OtherAnswer(cast(str, arguments[_OTHER]))
        if _OTHER in arguments
        else cast(str, arguments[_OPTION])
    )
    return record_answer(
        cast(str, arguments["repository"]),
        cast(int, arguments["item"]),
        cast(int, arguments["line"]),
        cast(str, arguments["card_hash"]),
        answer,
    )


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _read_inbox_defects(arguments: Mapping[str, object]) -> list[str]:
    return [f"{READ_INBOX} takes no arguments"] if arguments else []


def _envelope_defects(arguments: Mapping[str, object], allowed: tuple[str, ...]) -> list[str]:
    """The defects both writing tools share: an unknown key, a `repository` that
    is no string, an `item` that is no integer."""
    defects = [f"unknown argument: {key}" for key in arguments if key not in allowed]
    if not isinstance(arguments.get("repository"), str):
        defects.append("repository must be a string")
    if not _is_integer(arguments.get("item")):
        defects.append("item must be an integer")
    return defects


def _ask_defects(arguments: Mapping[str, object]) -> list[str]:
    """Every defect of the envelope of `ask`'s arguments. The card's values are
    the grammar's to judge."""
    return _envelope_defects(arguments, (*_ENVELOPE_KEYS, *expectation_grammar.CARD_KEYS))


def _record_answer_defects(arguments: Mapping[str, object]) -> list[str]:
    """Every defect of `record_answer`'s arguments: the envelope's, a `line` that
    is no integer, a `card_hash` that is no string, not exactly one of `option`
    and `other`, either of them no string, a blank `other`. Whether the line,
    the hash and the letter fit the item is the ruling's to judge."""
    defects = _envelope_defects(arguments, _RECORD_KEYS)
    if not _is_integer(arguments.get("line")):
        defects.append("line must be an integer")
    if not isinstance(arguments.get("card_hash"), str):
        defects.append("card_hash must be a string")
    given = [key for key in (_OPTION, _OTHER) if key in arguments]
    if len(given) != 1:
        defects.append(f"give exactly one of {_OPTION} and {_OTHER}")
    defects.extend(
        f"{key} must be a string" for key in given if not isinstance(arguments[key], str)
    )
    other = arguments.get(_OTHER)
    if isinstance(other, str) and not other.strip():
        defects.append(f"{_OTHER} must not be blank")
    return defects


def _answered(request_id: int | str, produce: Callable[[], Mapping[str, object]]) -> str:
    """The tool result of `produce`'s JSON, or the tool error of its refusal."""
    try:
        answer = dict(produce())
    except protocol.ClaimError as refusal:
        return _result(request_id, _tool_error(str(refusal)))
    except Exception as failure:
        return _result(request_id, _tool_error(f"{type(failure).__name__}: {failure}"))
    return _result(
        request_id,
        {
            "content": [{"type": "text", "text": json.dumps(answer)}],
            "structuredContent": answer,
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
