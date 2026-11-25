"""The `step` tool's arguments (`specs/mcp.spec.md`, MCP-67 to MCP-70, MCP-89 to MCP-93),
driven without a process: a message in, the answer line out, the writer a function the
test passes."""

import pytest
from mcp_echoes import reaches_nothing, rpc_request, serve, step_arguments, tool_call, without

_ONE_LINE = "paste must be one line; write a script and paste its one call"
_LINK = "paste is a link and must start with https:// or http://127.0.0.1, without spaces"


def _refusal(arguments: dict[str, object]) -> str:
    result = serve(tool_call(arguments, name="step"), step=reaches_nothing)["result"]
    assert result["isError"] is True
    return result["content"][0]["text"]


def test_the_step_schema_requires_the_repository_the_step_and_its_card() -> None:
    """Spec: MCP-67"""
    listing = serve(rpc_request("tools/list"))["result"]
    schema = next(tool for tool in listing["tools"] if tool["name"] == "step")["inputSchema"]

    assert set(schema["properties"]) == {
        "repository",
        "step",
        "item",
        "title",
        "purpose",
        "paste",
        "expected",
    }
    assert set(schema["required"]) == {"repository", "step", "purpose", "paste", "expected"}
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    ("changes", "sentence"),
    [
        pytest.param({"step": " ".join(["word"] * 16)}, "step must be at most 15 words", id="step"),
        pytest.param(
            {"purpose": " ".join(["word"] * 21)}, "purpose must be at most 20 words", id="purpose"
        ),
        pytest.param(
            {"expected": " ".join(["word"] * 21)},
            "expected must be at most 20 words",
            id="expected",
        ),
        pytest.param({"step": "Do a\nthen b."}, "step must be one line", id="step-lines"),
        pytest.param({"purpose": "Why a\nand b."}, "purpose must be one line", id="purpose-lines"),
        pytest.param(
            {"expected": "See a\nand b."}, "expected must be one line", id="expected-lines"
        ),
        pytest.param({"paste": "a\nb"}, _ONE_LINE, id="paste-lines"),
        pytest.param({"paste": "ftp://host/x"}, _LINK, id="paste-foreign-link"),
        pytest.param({"paste": "http://127.0.0.1.example.test/x"}, _LINK, id="paste-lookalike"),
        pytest.param(
            {"paste": "make build; make test"},
            'paste must be one command, it holds ";"; write a script and paste its one call',
            id="paste-chain",
        ),
    ],
)
def test_a_step_that_breaks_a_rule_is_refused_with_its_sentence(
    changes: dict[str, object], sentence: str
) -> None:
    """Spec: MCP-90, MCP-91, MCP-92, MCP-93. Example: E-MCP-22."""
    assert _refusal(step_arguments(**changes)) == sentence


def test_every_broken_rule_is_named_in_one_refusal() -> None:
    """Spec: MCP-90, MCP-91"""
    arguments = step_arguments(step="Do a\nthen b.", paste="a\nb")

    assert _refusal(arguments) == f"step must be one line; {_ONE_LINE}"


@pytest.mark.parametrize("key", ["actions", "answer"])
def test_the_older_card_fields_are_unknownstep_arguments(key: str) -> None:
    """Spec: MCP-55, MCP-67"""
    assert _refusal(step_arguments(**{key: "Say."})) == f"unknown argument: {key}"


@pytest.mark.parametrize(
    ("arguments", "sentence"),
    [
        pytest.param(
            without(step_arguments(), "purpose"),
            "purpose is required: why the operator takes the step",
            id="no-purpose",
        ),
        pytest.param(
            without(step_arguments(), "paste"),
            "paste is required: the one command line to copy",
            id="no-paste",
        ),
        pytest.param(
            without(step_arguments(), "expected"),
            "expected is required: what the operator sees",
            id="no-expected",
        ),
        pytest.param(step_arguments(paste=None), "paste must be a string", id="paste-no-string"),
        pytest.param(step_arguments(expected=3), "expected must be a string", id="expected-int"),
        pytest.param(
            step_arguments(purpose=" \n"), "purpose must not be blank", id="blank-purpose"
        ),
        pytest.param(step_arguments(paste=" \n"), "paste must not be blank", id="blank-paste"),
        pytest.param(
            step_arguments(expected=" \n"), "expected must not be blank", id="blank-expected"
        ),
    ],
)
def test_a_missing_or_blank_card_field_is_refused_naming_the_field(
    arguments: dict[str, object], sentence: str
) -> None:
    """Spec: MCP-70"""
    assert sentence in _refusal(arguments)


@pytest.mark.parametrize(
    "paste",
    [
        pytest.param("cd ~/repo && make rotate", id="cd-and-command"),
        pytest.param("https://example.test/run", id="link"),
    ],
)
def test_a_step_that_keeps_every_rule_reaches_the_writer_with_its_paste(
    paste: str,
) -> None:
    """Spec: MCP-49, MCP-89"""
    result = serve(tool_call(step_arguments(paste=paste), name="step"))["result"]

    assert result["structuredContent"]["card"]["paste"] == paste
