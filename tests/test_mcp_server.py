"""The MCP server's replies (`specs/mcp.spec.md`), driven without a process: a
message in, the answer line out, the inbox read a function the test passes."""

import json
from collections.abc import Mapping
from typing import Any, cast

import pytest

from aco import __version__, expectation_grammar, expectations, mcp_server, protocol

_INBOX: dict[str, object] = {"root": "/work", "repositories": [], "unreadable": []}


def _echoing(label: str, number: int, card: Mapping[str, object]) -> Mapping[str, object]:
    return {"repository": label, "item": number, "written": True, "card": dict(card)}


def _echoing_record(
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


def _answer(
    message: object,
    read_inbox: mcp_server.ReadInbox = lambda: _INBOX,
    ask: mcp_server.Ask = _echoing,
    record_answer: mcp_server.RecordAnswer = _echoing_record,
) -> dict[str, Any]:
    tools = mcp_server.Tools(read_inbox, ask, record_answer)
    line = mcp_server.reply(message if isinstance(message, str) else json.dumps(message), tools)
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


def test_the_instructions_name_every_tool_the_server_lists() -> None:
    instructions = _answer(_request("initialize"))["result"]["instructions"]

    named = {name for name in _tools() if name in instructions}

    assert named == set(_tools())


def test_initialize_without_params_still_answers() -> None:
    result = _answer(_request("initialize"))["result"]

    assert result["protocolVersion"] == mcp_server.SUPPORTED_PROTOCOL_VERSIONS[0]


def test_ping_answers_an_empty_result() -> None:
    assert _answer(_request("ping", request_id="p")) == {"jsonrpc": "2.0", "id": "p", "result": {}}


def _tools() -> dict[str, dict[str, Any]]:
    tools = _answer(_request("tools/list"))["result"]["tools"]
    return {tool["name"]: tool for tool in tools}


def test_tools_list_offers_the_read_only_inbox_tool_without_arguments() -> None:
    tool = _tools()["read_inbox"]

    assert tool["annotations"] == {"readOnlyHint": True}
    assert tool["inputSchema"]["type"] == "object"
    assert tool["inputSchema"]["properties"] == {}


def test_tools_list_offers_ask_as_a_repeatable_write_that_destroys_nothing() -> None:
    tool = _tools()["ask"]

    assert list(_tools()) == ["read_inbox", "ask", "record_answer"]
    assert tool["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    }
    assert tool["title"]
    assert tool["description"]


def test_tools_list_offers_record_answer_as_a_repeatable_write_that_replaces_a_note() -> None:
    tool = _tools()["record_answer"]

    assert tool["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
    }
    assert tool["title"]
    assert tool["description"]


def test_the_record_answer_schema_takes_its_letters_from_the_grammar_and_offers_no_via() -> None:
    schema = _tools()["record_answer"]["inputSchema"]

    assert set(schema["properties"]) == {
        "repository",
        "item",
        "line",
        "card_hash",
        "option",
        "other",
    }
    assert set(schema["required"]) == {"repository", "item", "line", "card_hash"}
    assert schema["properties"]["option"]["enum"] == list(expectation_grammar.OPTION_LETTERS)
    assert schema["properties"]["line"]["minimum"] == 1
    assert schema["additionalProperties"] is False


def test_no_tool_schema_carries_a_combinator_at_its_top() -> None:
    combinators = {"oneOf", "anyOf", "allOf"}

    carried = {name for name, tool in _tools().items() if combinators & set(tool["inputSchema"])}

    assert carried == set()


def test_the_ask_schema_takes_its_keys_and_values_from_the_card_grammar() -> None:
    grammar = expectation_grammar
    schema = _tools()["ask"]["inputSchema"]
    option = schema["properties"]["options"]["items"]

    assert set(schema["properties"]) == {
        "repository",
        "item",
        "text",
        *grammar.OPTION_LINE_KEYS,
        "options",
    }
    assert set(schema["required"]) == {
        "repository",
        "item",
        "text",
        *(set(grammar.OPTION_LINE_KEYS) - grammar.OPTION_LINE_OPTIONAL_KEYS),
        "options",
    }
    assert set(option["properties"]) == set(grammar.OPTION_KEYS)
    assert option["required"] == list(grammar.OPTION_REQUIRED_KEYS)
    assert option["properties"][grammar.SAME_AS_TODAY] == {"const": True}
    assert option["properties"]["undo"]["enum"] == [undo.value for undo in grammar.Undo]
    assert schema["properties"]["decision_kind"]["enum"] == [
        kind.value for kind in grammar.DecisionKind
    ]
    assert schema["properties"]["recommended"]["enum"] == list(grammar.OPTION_LETTERS)
    assert (schema["additionalProperties"], option["additionalProperties"]) == (False, False)


@pytest.mark.parametrize(
    "state_key",
    [
        "asked_on",
        "ruling",
        "ruled_on",
        "via",
        "other",
        "returned_on",
        "returned_note",
        "withdrawn_on",
        "card_hash",
    ],
)
def test_the_ask_schema_offers_no_state_key(state_key: str) -> None:
    properties = _tools()["ask"]["inputSchema"]["properties"]

    assert state_key not in properties


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


def _card_arguments(**changes: object) -> dict[str, object]:
    return {"repository": "owner/repo", "item": 7, "text": "Frage", "options": [], **changes}


def test_an_ask_call_hands_the_card_without_its_envelope_to_the_writer_and_answers_its_json() -> (
    None
):
    result = _answer(_call(_card_arguments(), name="ask"))["result"]

    expected = {
        "repository": "owner/repo",
        "item": 7,
        "written": True,
        "card": {"text": "Frage", "options": []},
    }
    assert result["isError"] is False
    assert result["structuredContent"] == expected
    assert json.loads(result["content"][0]["text"]) == expected


def _refusing_ask(label: str, number: int, card: Mapping[str, object]) -> Mapping[str, object]:
    raise protocol.ClaimError("item 7 is closed")


def _failing_ask(label: str, number: int, card: Mapping[str, object]) -> Mapping[str, object]:
    raise RuntimeError("boom")


@pytest.mark.parametrize(
    ("ask", "reason"),
    [
        pytest.param(_refusing_ask, "item 7 is closed", id="refusal"),
        pytest.param(_failing_ask, "RuntimeError: boom", id="unexpected-exception"),
    ],
)
def test_a_refused_ask_is_a_tool_error_carrying_its_reason(
    ask: mcp_server.Ask, reason: str
) -> None:
    result = _answer(_call(_card_arguments(), name="ask"), ask=ask)["result"]

    assert result["isError"] is True
    assert result["content"] == [{"type": "text", "text": reason}]
    assert "structuredContent" not in result


def _writes_nothing(label: str, number: int, card: Mapping[str, object]) -> Mapping[str, object]:
    pytest.fail("an ask with a defective envelope reached the writer")


@pytest.mark.parametrize(
    ("arguments", "sentence"),
    [
        pytest.param(_card_arguments(extra=1), "unknown argument: extra", id="unknown-key"),
        pytest.param(
            _card_arguments(asked_on="2026-11-08"), "unknown argument: asked_on", id="state"
        ),
        pytest.param(_card_arguments(item=True), "item must be an integer", id="item-boolean"),
        pytest.param(_card_arguments(item="7"), "item must be an integer", id="item-string"),
        pytest.param(_card_arguments(item=7.5), "item must be an integer", id="item-float"),
        pytest.param(_card_arguments(repository=3), "repository must be a string", id="repository"),
        pytest.param({"text": "Frage"}, "repository must be a string", id="no-repository"),
    ],
)
def test_an_argument_defect_is_a_tool_error_naming_it_and_nothing_is_written(
    arguments: dict[str, object], sentence: str
) -> None:
    result = _answer(_call(arguments, name="ask"), ask=_writes_nothing)["result"]

    assert result["isError"] is True
    assert sentence in result["content"][0]["text"]


def test_every_envelope_defect_is_named_in_one_error() -> None:
    arguments = _card_arguments(repository=3, item="x", extra=1)

    result = _answer(_call(arguments, name="ask"), ask=_writes_nothing)["result"]

    text = result["content"][0]["text"]
    assert [
        sentence in text
        for sentence in ("unknown argument: extra", "repository must be", "item must be")
    ] == [True, True, True]


def _record_arguments(**changes: object) -> dict[str, object]:
    return {
        "repository": "owner/repo",
        "item": 7,
        "line": 2,
        "card_hash": "abc",
        "option": "A",
        **changes,
    }


def _without(arguments: dict[str, object], *keys: str) -> dict[str, object]:
    return {key: value for key, value in arguments.items() if key not in keys}


def test_a_record_answer_call_hands_the_letter_to_the_writer_and_answers_its_json() -> None:
    result = _answer(_call(_record_arguments(), name="record_answer"))["result"]

    expected = {
        "repository": "owner/repo",
        "item": 7,
        "line": 2,
        "card_hash": "abc",
        "answer": "A",
        "own_words": False,
    }
    assert result["isError"] is False
    assert result["structuredContent"] == expected
    assert json.loads(result["content"][0]["text"]) == expected


def test_a_record_answer_call_hands_the_operators_words_to_the_writer_verbatim() -> None:
    words = "  lieber morgen \u2028 \n"
    arguments = _without(_record_arguments(other=words), "option")

    result = _answer(_call(arguments, name="record_answer"))["result"]

    assert result["structuredContent"]["answer"] == words
    assert result["structuredContent"]["own_words"] is True


def _refusing_record(
    label: str, number: int, line: int, card_hash: str, answer: str | expectations.OtherAnswer
) -> Mapping[str, object]:
    raise protocol.ClaimError("line 2 is already ruled")


def _failing_record(
    label: str, number: int, line: int, card_hash: str, answer: str | expectations.OtherAnswer
) -> Mapping[str, object]:
    raise RuntimeError("boom")


@pytest.mark.parametrize(
    ("record_answer", "reason"),
    [
        pytest.param(_refusing_record, "line 2 is already ruled", id="refusal"),
        pytest.param(_failing_record, "RuntimeError: boom", id="unexpected-exception"),
    ],
)
def test_a_refused_record_answer_is_a_tool_error_carrying_its_reason(
    record_answer: mcp_server.RecordAnswer, reason: str
) -> None:
    arguments = _record_arguments()

    result = _answer(_call(arguments, name="record_answer"), record_answer=record_answer)["result"]

    assert result["isError"] is True
    assert result["content"] == [{"type": "text", "text": reason}]
    assert "structuredContent" not in result


def _writes_no_record(
    label: str, number: int, line: int, card_hash: str, answer: str | expectations.OtherAnswer
) -> Mapping[str, object]:
    pytest.fail("a record_answer with a defective envelope reached the writer")


@pytest.mark.parametrize(
    ("arguments", "sentence"),
    [
        pytest.param(_record_arguments(via="chat"), "unknown argument: via", id="via"),
        pytest.param(_record_arguments(extra=1), "unknown argument: extra", id="unknown-key"),
        pytest.param(_record_arguments(repository=3), "repository must be a string", id="repo"),
        pytest.param(_record_arguments(item=True), "item must be an integer", id="item-boolean"),
        pytest.param(_record_arguments(item="7"), "item must be an integer", id="item-string"),
        pytest.param(_record_arguments(line=True), "line must be an integer", id="line-boolean"),
        pytest.param(_record_arguments(line=2.5), "line must be an integer", id="line-float"),
        pytest.param(_record_arguments(line=None), "line must be an integer", id="line-null"),
        pytest.param(_record_arguments(card_hash=5), "card_hash must be a string", id="hash-int"),
        pytest.param(
            _without(_record_arguments(), "card_hash"), "card_hash must be a string", id="no-hash"
        ),
        pytest.param(
            _record_arguments(other="own"), "give exactly one of option and other", id="both"
        ),
        pytest.param(
            _without(_record_arguments(), "option"),
            "give exactly one of option and other",
            id="none",
        ),
        pytest.param(_record_arguments(option=1), "option must be a string", id="option-int"),
        pytest.param(
            _without(_record_arguments(other=4), "option"), "other must be a string", id="other-int"
        ),
        pytest.param(
            _without(_record_arguments(other=""), "option"), "other must not be blank", id="empty"
        ),
        pytest.param(
            _without(_record_arguments(other=" \t\n"), "option"),
            "other must not be blank",
            id="whitespace",
        ),
    ],
)
def test_a_record_answer_argument_defect_is_a_tool_error_naming_it_and_nothing_is_written(
    arguments: dict[str, object], sentence: str
) -> None:
    result = _answer(_call(arguments, name="record_answer"), record_answer=_writes_no_record)[
        "result"
    ]

    assert result["isError"] is True
    assert sentence in result["content"][0]["text"]


def test_every_record_answer_envelope_defect_is_named_in_one_error() -> None:
    arguments = {"repository": 3, "item": "x", "line": "y", "option": 1, "other": 2, "extra": 1}

    result = _answer(_call(arguments, name="record_answer"), record_answer=_writes_no_record)[
        "result"
    ]

    text = result["content"][0]["text"]
    assert [
        sentence in text
        for sentence in (
            "unknown argument: extra",
            "repository must be",
            "item must be",
            "line must be",
            "card_hash must be",
            "give exactly one",
            "option must be",
            "other must be",
        )
    ] == [True] * 8


@pytest.mark.parametrize("name", ["read_inbox", "ask", "record_answer"])
@pytest.mark.parametrize("arguments", [[], "card", 3, None], ids=["list", "string", "int", "null"])
def test_arguments_that_are_no_object_are_an_invalid_params_error_for_every_tool(
    name: str, arguments: object
) -> None:
    message = _request("tools/call", {"name": name, "arguments": arguments})

    error = _answer(message)["error"]

    assert error["code"] == -32602


def test_read_inbox_called_with_a_key_is_a_tool_error_naming_it() -> None:
    result = _answer(_call({"limit": 1}))["result"]

    assert result["isError"] is True
    assert result["content"] == [{"type": "text", "text": "read_inbox takes no arguments"}]


@pytest.mark.parametrize(
    "message",
    [
        pytest.param(_call(name="write_inbox"), id="unknown-tool"),
        pytest.param(_request("tools/call"), id="no-name"),
    ],
)
def test_a_call_of_an_unknown_tool_is_an_invalid_params_error(
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
    tools = mcp_server.Tools(lambda: _INBOX, _echoing, _echoing_record)

    assert mcp_server.reply(json.dumps(message), tools) is None


@pytest.mark.parametrize(
    ("text", "code"),
    [
        pytest.param("{not json", -32700, id="unparsable"),
        pytest.param("[" * 100_000, -32700, id="nested-past-the-recursion-limit"),
        pytest.param("1" * 5_000, -32700, id="integer-past-the-digit-limit"),
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
