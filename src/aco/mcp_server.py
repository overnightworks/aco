"""The MCP server's replies (`specs/mcp.spec.md`): one decoded JSON-RPC message
in, the line to answer with out. Free of I/O: the inbox read, the card write, the
answer write, the step write and the step answer write are passed in.

Speaks the `initialize` era of the protocol: `initialize`, `ping`, `tools/list`
and `tools/call`, with the tools `read_inbox`, `ask`, `record_answer`, `step`,
`answer_step` and `read_next`.
"""

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, TextIO, cast

from . import __version__, expectation_grammar, expectations, item_step, protocol

SUPPORTED_PROTOCOL_VERSIONS: Final = ("2025-11-25", "2025-06-18")
"""Newest first: the first is the answer to a client that asks for another."""

READ_INBOX: Final = "read_inbox"
ASK: Final = "ask"
RECORD_ANSWER: Final = "record_answer"
STEP: Final = "step"
ANSWER_STEP: Final = "answer_step"
READ_NEXT: Final = "read_next"

type ReadInbox = Callable[[], Mapping[str, object]]
"""The inbox as JSON; raises `protocol.ClaimError` when it cannot be read."""

type ReadNext = Callable[[], Mapping[str, object]]
"""What `aco next --json` answers in every repository, as JSON; raises
`protocol.ClaimError` when no repository can be found."""

type Ask = Callable[[str, int, Mapping[str, object]], Mapping[str, object]]
"""Puts a card on an item of a repository, named as `read_inbox` lists it, and
answers as JSON; raises `protocol.ClaimError` when it refuses."""

type RecordAnswer = Callable[
    [str, int, int, str, str | expectations.OtherAnswer], Mapping[str, object]
]
"""Records the operator's chat answer, a letter or his own words, on a line of an
item of a repository, named as `read_inbox` lists it, given the card's hash, and
answers as JSON; raises `protocol.ClaimError` when it refuses."""

type Step = Callable[[str, str, int | str, item_step.StepCard], Mapping[str, object]]
"""Marks a step only the operator can take, given as text and detailed by a card, in
a repository named as `read_inbox` lists it: on the item whose number is the third
argument, or, when that is a title, on the open item holding it or on a new one;
answers as JSON; raises `protocol.ClaimError` when it refuses."""

type AnswerStep = Callable[[str, int, str, item_step.StepResult], Mapping[str, object]]
"""Records the operator's chat answer to the step of an item of a repository, named as
`read_inbox` lists it, given the step line `read_inbox` showed; answers as JSON; raises
`protocol.ClaimError` when the step changed, the item holds none or the answer does not
fit it."""


@dataclass(frozen=True)
class Tools:
    """What each tool does, passed in by the process that serves them."""

    read_inbox: ReadInbox
    ask: Ask
    record_answer: RecordAnswer
    step: Step
    answer_step: AnswerStep
    read_next: ReadNext


_PARSE_ERROR: Final = -32700
_INVALID_REQUEST: Final = -32600
_METHOD_NOT_FOUND: Final = -32601
_INTERNAL_ERROR: Final = -32603
_INVALID_PARAMS: Final = -32602

_INSTRUCTIONS: Final = (
    "Read the decisions and the steps waiting on the operator across every repository on "
    f"this machine with {READ_INBOX}, put a decision card of your own on an item with {ASK}, "
    f"record the answer the operator gave in this chat with {RECORD_ANSWER}, and mark a step "
    f"only the operator can take with {STEP}; record the operator's chat answer to such a step "
    f"with {ANSWER_STEP}. Read what runs next on every board with {READ_NEXT}."
)
_REPOSITORY: Final = "repository"
_REPOSITORY_DESCRIPTION: Final = "the repository as read_inbox lists it, owner/repo"
_ITEM: Final = "item"
_ENVELOPE_KEYS: Final = (_REPOSITORY, _ITEM)
_TITLE: Final = "title"
_STEP_CARD_PURPOSES: Final = {
    item_step.PURPOSE_KEY: "why the operator takes the step, in a sentence",
    item_step.PASTE_KEY: (
        "the one command line to copy (an optional cd and the command, nothing to fill in) "
        "or the one link to open (https, or http to 127.0.0.1)"
    ),
    item_step.EXPECTED_KEY: "what the operator sees when it worked",
}
_STEP_KEYS: Final = (_REPOSITORY, STEP, _ITEM, _TITLE, *_STEP_CARD_PURPOSES)
_RULED_KEYS: Final = (STEP, *item_step.REQUIRED_KEYS)
_OPTION: Final = "option"
_OTHER: Final = "other"
_RESULT: Final = "result"
_TEXT: Final = "text"
_SUCCEEDED: Final = "Erfolgreich"
_FAILED: Final = "Fehlgeschlagen"
_RESULT_KINDS: Final = (_SUCCEEDED, _FAILED)
_ANSWER_STEP_KEYS: Final = (*_ENVELOPE_KEYS, STEP, _RESULT, _TEXT)
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
            "repository": _string(_REPOSITORY_DESCRIPTION),
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
            "repository": _string(_REPOSITORY_DESCRIPTION),
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


def _step_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            _REPOSITORY: _string(_REPOSITORY_DESCRIPTION),
            STEP: _string("what the operator must do"),
            _ITEM: {"type": "integer", "description": "the number of an open item; or give title"},
            _TITLE: _string("the title of a new item; give this or item"),
            **{key: _string(purpose) for key, purpose in _STEP_CARD_PURPOSES.items()},
        },
        "required": [_REPOSITORY, STEP, *item_step.REQUIRED_KEYS],
        "additionalProperties": False,
    }


def _answer_step_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            _REPOSITORY: _string(_REPOSITORY_DESCRIPTION),
            _ITEM: {"type": "integer", "description": "the number of the item"},
            STEP: _string("the step line read_inbox showed for that item"),
            _RESULT: {
                "type": "string",
                "enum": list(_RESULT_KINDS),
                "description": (
                    f"{_SUCCEEDED}: it worked; {_FAILED}: it failed, with text saying how"
                ),
            },
            _TEXT: _string(f"the note of {_FAILED}; give it for that result only"),
        },
        "required": [*_ENVELOPE_KEYS, STEP, _RESULT],
        "additionalProperties": False,
    }


_TOOLS: Final = (
    {
        "name": READ_INBOX,
        "title": "Read the operator's inbox",
        "description": (
            "The option lines and the steps that wait on the operator, across every repository "
            "found under the configured root: each item with its waiting lines, each item "
            "whose wait names the operator with its step, the repositories that could not be read, "
            "and the checkouts that could not be scanned."
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
            "The answer also carries earlier: up to five lines the operator ruled in the "
            "same area in any repository found, closed items included, newest first, each "
            "with its question, answer, day and item, and earlier_more, the count beyond "
            "five. They are shown, never applied: the card stands, and you decide whether "
            "the question is already answered. They come from the forge's search index, so "
            "a ruling of the last minutes can be missing; when the search cannot answer, "
            "earlier_unavailable says why instead. "
            "The answer's link opens the card on the board (null when no board is "
            "configured): give the operator that link and one line. "
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
            "answer binds like a ruling on the board: the line leaves read_inbox and shows as "
            "ruled in aco rulings and the board; a line already ruled stays as it is and the "
            "call is refused. "
            "A refusal that says a body was written means the answer reached the item, "
            "unless it says it was overwritten in the meantime."
        ),
        "inputSchema": _record_answer_schema(),
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True},
    },
    {
        "name": STEP,
        "title": "Mark a step only the operator can take",
        "description": (
            "Marks a step that only the operator can take, such as a secret to set or an "
            "approval to give: the item gets that wait and the label needs-operator, its next "
            "stays as it is, so the step shows in read_inbox "
            "under steps. The step is a short line of at most 15 words, the one short action; "
            "purpose, paste and expected are required, each one line, stored on the item "
            "and shown in read_inbox: the paste is one command or one link, a script's one "
            "call for anything longer, and a step that breaks a rule is refused. "
            "Give an open item's number as item, or a title to open a new item "
            "for the step; a title that an open item of the operator's already holds with "
            "this step marks that item instead. An answer on the board clears the wait, "
            "the step and the label; an answer in chat goes through answer_step. The "
            "answer's link opens the step on the board (null when no board is configured): "
            "give the operator that link and one line. A refusal "
            "that says the step "
            "was written or the item was opened is finished by repeating the same call."
        ),
        "inputSchema": _step_schema(),
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True},
    },
    {
        "name": ANSWER_STEP,
        "title": "Record the operator's answer to a step",
        "description": (
            "Records the answer the operator gave in this chat to the step an item waits "
            "on, as the board records it: Erfolgreich, or Fehlgeschlagen with the note that "
            "says how. Use it only for an answer he gave, never for your own. Give the step "
            "line exactly as read_inbox shows it; a step that changed since or an item "
            "without a step is refused and nothing is written. The item's wait, step and "
            "label needs-operator go and the answer is written into now; the item stays open."
        ),
        "inputSchema": _answer_step_schema(),
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False},
    },
    {
        "name": READ_NEXT,
        "title": "Read what runs next on every board",
        "description": (
            "What aco next --json answers in the main checkout of every repository found under "
            "the configured root: per repository its next object, or the sentence of the refusal "
            "when its board could not be read, and the checkouts that could not be scanned. "
            "Nothing is written."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True},
    },
)


def answer_lines(
    requests: Iterable[bytes], replies: TextIO, answer: Callable[[bytes], str | None]
) -> None:
    """Write `answer` of each non-blank line of `requests` on `replies`, one line
    each and flushed, until the lines end; None is no answer (a notification)."""
    for request in requests:
        if not request.strip():
            continue
        text = answer(request)
        if text is not None:
            replies.write(text if text.endswith("\n") else text + "\n")
            replies.flush()


def reply(text: str, tools: Tools) -> str | None:
    """The line answering the message `text`, or None for a notification."""
    message, refusal = _parsed(text)
    if message is None:
        return refusal
    if "id" not in message:
        return None
    return _answer(message["id"], message["method"], message.get("params"), tools)


def unanswered_reply(text: str, reason: str) -> str | None:
    """The line answering the message `text` when no tool code could: a tool error
    with `reason` for a `tools/call`, error `-32603` for another request, and what
    `reply` gives for a message that is no request or a notification."""
    message, refusal = _parsed(text)
    if message is None:
        return refusal
    if "id" not in message:
        return None
    if message["method"] == "tools/call":
        return _result(message["id"], _tool_error(reason))
    return _error(message["id"], _INTERNAL_ERROR, reason)


def _parsed(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """The message `text` holds, or the line refusing it."""
    try:
        message = json.loads(text)
    except ValueError, RecursionError:
        # Past the parser's limits (digit count, nesting) it raises these, not JSONDecodeError.
        return None, unparsable_reply()
    invalid = _invalid_request(message)
    if invalid is not None:
        return None, _error(None, _INVALID_REQUEST, invalid)
    return message, None


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
        READ_INBOX: _Handler(_no_arguments(READ_INBOX), lambda arguments: tools.read_inbox()),
        READ_NEXT: _Handler(_no_arguments(READ_NEXT), lambda arguments: tools.read_next()),
        ASK: _Handler(_ask_defects, lambda arguments: _ask(tools.ask, arguments)),
        RECORD_ANSWER: _Handler(
            _record_answer_defects, lambda arguments: _record_answer(tools.record_answer, arguments)
        ),
        STEP: _Handler(_step_defects, lambda arguments: _step(tools.step, arguments)),
        ANSWER_STEP: _Handler(
            _answer_step_defects, lambda arguments: _answer_step(tools.answer_step, arguments)
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


def _step(step: Step, arguments: Mapping[str, object]) -> Mapping[str, object]:
    """The call of the step writer with arguments whose defects were already refused;
    the item number, or the title stripped, is its target."""
    target = arguments[_ITEM] if _ITEM in arguments else cast(str, arguments[_TITLE]).strip()
    return step(
        cast(str, arguments[_REPOSITORY]),
        cast(str, arguments[STEP]).strip(),
        cast(int | str, target),
        _step_card(arguments),
    )


def _answer_step(answer_step: AnswerStep, arguments: Mapping[str, object]) -> Mapping[str, object]:
    """The call of the step answer writer with arguments whose defects were already
    refused."""
    text = cast(str, arguments[_TEXT]).strip() if _TEXT in arguments else ""
    result: item_step.StepResult = (
        item_step.StepFailed(text) if arguments[_RESULT] == _FAILED else item_step.StepSucceeded()
    )
    return answer_step(
        cast(str, arguments[_REPOSITORY]),
        cast(int, arguments[_ITEM]),
        cast(str, arguments[STEP]).strip(),
        result,
    )


def _step_card(arguments: Mapping[str, object]) -> item_step.StepCard:
    """The card of `step` arguments whose defects were already refused."""
    purpose, paste, expected = (
        cast(str, arguments[key]).strip() for key in item_step.REQUIRED_KEYS
    )
    return item_step.StepCard(purpose, paste, expected)


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _no_arguments(tool: str) -> Callable[[Mapping[str, object]], list[str]]:
    """The defects of a call of `tool`, which takes none: any argument."""

    def defects(arguments: Mapping[str, object]) -> list[str]:
        return [f"{tool} takes no arguments"] if arguments else []

    return defects


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


def _step_defects(arguments: Mapping[str, object]) -> list[str]:
    """Every defect of `step`'s arguments: an unknown key, a `repository`, `step`
    or `title` that is no string, an `item` that is no integer, not exactly one of
    `item` and `title`, a blank `step` or `title`. Whether the item or the
    repository exists is the writer's to judge."""
    defects = [f"unknown argument: {key}" for key in arguments if key not in _STEP_KEYS]
    given = [key for key in (_ITEM, _TITLE) if key in arguments]
    named = (_REPOSITORY, STEP, *(key for key in given if key == _TITLE))
    defects.extend(
        f"{key} must be a string" for key in named if not isinstance(arguments.get(key), str)
    )
    if _ITEM in given and not _is_integer(arguments[_ITEM]):
        defects.append(f"{_ITEM} must be an integer")
    if len(given) != 1:
        defects.append(f"give exactly one of {_ITEM} and {_TITLE}")
    defects.extend(
        f"{key} must not be blank"
        for key in (STEP, *given, *_STEP_CARD_PURPOSES)
        if _is_blank(arguments, key)
    )
    defects.extend(_step_card_defects(arguments))
    defects.extend(
        item_step.step_rule_defects(*(_stripped_text(arguments, key) for key in _RULED_KEYS))
    )
    return defects


def _answer_step_defects(arguments: Mapping[str, object]) -> list[str]:
    """Every defect of `answer_step`'s arguments: the envelope's, a `step` that is no
    string or blank, a `result` that is neither of the two, a `text` that is no string,
    blank where `result` needs one, or given with Erfolgreich. Whether the step fits the
    item is the writer's to judge."""
    defects = _envelope_defects(arguments, _ANSWER_STEP_KEYS)
    if not isinstance(arguments.get(STEP), str) or _is_blank(arguments, STEP):
        defects.append(f"{STEP} must be the non-blank step line read_inbox showed")
    kind = arguments.get(_RESULT)
    if kind not in _RESULT_KINDS:
        defects.append(f"{_RESULT} must be one of {', '.join(_RESULT_KINDS)}")
    text = arguments.get(_TEXT)
    if _TEXT in arguments and not isinstance(text, str):
        defects.append(f"{_TEXT} must be a string")
    elif kind == _SUCCEEDED and _TEXT in arguments:
        defects.append(f"{_TEXT} must not be given with {_SUCCEEDED}")
    elif kind == _FAILED and (text is None or _is_blank(arguments, _TEXT)):
        defects.append(f"{_TEXT} is required with {kind} and must not be blank")
    return defects


def _step_card_defects(arguments: Mapping[str, object]) -> list[str]:
    """The required card field that is missing, naming what it is for, and the card
    field that is no string."""
    defects = [
        f"{key} is required: {_STEP_CARD_PURPOSES[key]}"
        for key in item_step.REQUIRED_KEYS
        if key not in arguments
    ]
    defects.extend(
        f"{key} must be a string"
        for key in _STEP_CARD_PURPOSES
        if key in arguments and not isinstance(arguments[key], str)
    )
    return defects


def _stripped_text(arguments: Mapping[str, object], key: str) -> str:
    """The stripped string `key` holds, empty when it is none, which no rule refuses."""
    value = arguments.get(key)
    return value.strip() if isinstance(value, str) else ""


def _is_blank(arguments: Mapping[str, object], key: str) -> bool:
    value = arguments.get(key)
    return isinstance(value, str) and not value.strip()


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
