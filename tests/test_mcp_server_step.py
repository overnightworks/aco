"""The `step` tool's arguments (`specs/mcp.spec.md`, MCP-67 to MCP-70, MCP-89 to MCP-93),
driven without a process: a message in, the answer line out, the writer a function the
test passes."""

import json
from collections.abc import Mapping
from typing import Any, NoReturn

import pytest

from aco import item_step, mcp_server

_ONE_LINE = "paste must be one line; write a script and paste its one call"
_LINK = "paste is a link and must start with https:// or http://127.0.0.1, without spaces"


def _unused(*_: object) -> NoReturn:
    pytest.fail("a call that is no step call reached a writer")


def _refused_step(*_: object) -> NoReturn:
    pytest.fail("a defective step call reached the writer")


def _recorded_step(
    label: str, step: str, target: int | str, card: item_step.StepCard
) -> Mapping[str, object]:
    return {"repository": label, "step": step, "target": target, "paste": card.paste}


def _arguments(**changes: object) -> dict[str, object]:
    return {
        "repository": "owner/repo",
        "step": "Rotate the key.",
        "item": 7,
        "purpose": "Why.",
        "paste": "make rotate",
        "expected": "See that.",
        **changes,
    }


def _tools(step: mcp_server.Step) -> mcp_server.Tools:
    return mcp_server.Tools(lambda: {}, _unused, _unused, step, _unused)


def _reply(message: dict[str, object], step: mcp_server.Step = _refused_step) -> dict[str, Any]:
    line = mcp_server.reply(json.dumps(message), _tools(step))
    assert line is not None
    return json.loads(line)["result"]


def _step_call(arguments: dict[str, object]) -> dict[str, object]:
    params = {"name": "step", "arguments": arguments}
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}


def _refusal(arguments: dict[str, object]) -> str:
    result = _reply(_step_call(arguments))
    assert result["isError"] is True
    return result["content"][0]["text"]


def test_the_step_schema_requires_the_repository_the_step_and_its_card() -> None:
    """Spec: MCP-67"""
    listing = _reply({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
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
    assert _refusal(_arguments(**changes)) == sentence


def test_every_broken_rule_is_named_in_one_refusal() -> None:
    """Spec: MCP-90, MCP-91"""
    arguments = _arguments(step="Do a\nthen b.", paste="a\nb")

    assert _refusal(arguments) == f"step must be one line; {_ONE_LINE}"


@pytest.mark.parametrize("key", ["actions", "answer"])
def test_the_older_card_fields_are_unknown_arguments(key: str) -> None:
    """Spec: MCP-55, MCP-67"""
    assert _refusal(_arguments(**{key: "Say."})) == f"unknown argument: {key}"


@pytest.mark.parametrize(
    ("arguments", "sentence"),
    [
        pytest.param(
            {"paste": None},
            "paste must be a string",
            id="paste-no-string",
        ),
        pytest.param({"paste": " \n"}, "paste must not be blank", id="paste-blank"),
    ],
)
def test_a_paste_that_is_no_text_is_refused_naming_the_field(
    arguments: dict[str, object], sentence: str
) -> None:
    """Spec: MCP-70"""
    assert _refusal(_arguments(**arguments)) == sentence


def test_the_missing_paste_is_refused_saying_what_it_is_for() -> None:
    """Spec: MCP-70"""
    arguments = _arguments()
    del arguments["paste"]

    assert _refusal(arguments).startswith("paste is required: the one command line to copy")


@pytest.mark.parametrize(
    "paste",
    [
        pytest.param("  make rotate\n", id="padded"),
        pytest.param("cd ~/repo && make rotate", id="cd-and-command"),
        pytest.param("https://example.test/run", id="link"),
    ],
)
def test_a_step_that_keeps_every_rule_reaches_the_writer_with_its_stripped_paste(
    paste: str,
) -> None:
    """Spec: MCP-49, MCP-89"""
    result = _reply(_step_call(_arguments(paste=paste)), _recorded_step)

    assert result["structuredContent"]["paste"] == paste.strip()
