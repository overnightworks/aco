"""`aco mcp`'s answer_step tool (`specs/mcp.spec.md`) through `cli.main(["mcp", "--direct"])` over
the board's test forge: an answer given in chat takes the writer of the board's
`POST /api/step`, and a step that changed, an item without one or an answer the step does
not ask for is refused with nothing written."""

from typing import Any

import board_forge
import pytest
from board_fixtures import OPERATOR_WAIT, complete_contract
from mcp_lines import call_line, serve_mcp

from aco import body, workboard

_STEP = OPERATOR_WAIT["operator"]
_REPORT_STEP = {
    "purpose": "Release the build.",
    "actions": "open https://example.test/run\nclick Run",
    "expected": "The page shows green.",
    "answer": "the run report",
}
_YES_NO_STEP = {key: value for key, value in _REPORT_STEP.items() if key != "answer"}
_WRITES = (
    board_forge.ForgeOperation.WRITE_BODY,
    board_forge.ForgeOperation.REMOVE_LABEL,
)


pytestmark = pytest.mark.usefixtures("config_file", "isolated_global_git_config")


def _put_step(here: board_forge.BoardForge, table: dict[str, str] = _YES_NO_STEP) -> None:
    here.put_item(
        1,
        complete_contract("S1 Prepare the run.\nS2 Run it.", wait=OPERATOR_WAIT, step=table),
        title="Release",
        labels=(workboard.NEEDS_OPERATOR_LABEL,),
    )


def _answer_line(**changes: object) -> str:
    arguments: dict[str, object] = {
        "repository": "board-forge/here",
        "item": 1,
        "step": _STEP,
        "result": "Erfolgreich",
        **changes,
    }
    return call_line(1, "answer_step", arguments)


def _serve(monkeypatch: pytest.MonkeyPatch, line: str) -> dict[str, Any]:
    [reply] = serve_mcp(monkeypatch, line)
    return reply["result"]


def _writes(here: board_forge.BoardForge) -> list[str]:
    return [
        request.operation.value for request in here.request_log() if request.operation in _WRITES
    ]


@pytest.mark.parametrize(
    ("table", "arguments", "outcome"),
    [
        (_YES_NO_STEP, {"result": "Erfolgreich"}, "Erfolgreich"),
        (
            _YES_NO_STEP,
            {"result": "Fehlgeschlagen", "text": "Stayed red."},
            "Fehlgeschlagen: Stayed red.",
        ),
        (_REPORT_STEP, {"result": "report", "text": "All 12 passed."}, "All 12 passed."),
    ],
    ids=["erfolgreich", "fehlgeschlagen-with-a-note", "a-report"],
)
def test_a_chat_answer_clears_the_wait_and_the_step_writes_now_and_keeps_the_item_open(
    here: board_forge.BoardForge,
    monkeypatch: pytest.MonkeyPatch,
    table: dict[str, str],
    arguments: dict[str, object],
    outcome: str,
) -> None:
    _put_step(here, table)
    before = body.locate_block(here.stored_body(1)).data

    answered = _serve(monkeypatch, _answer_line(**arguments))

    block = body.locate_block(here.stored_body(1)).data
    assert answered["isError"] is False
    assert answered["structuredContent"] == {
        "repository": "board-forge/here",
        "item": 1,
        "answered": True,
    }
    day = board_forge.RULING_DAY.isoformat()
    assert block["now"] == f'The operator answered "{_STEP}" in chat on {day}: {outcome}'
    assert block["next"] == before["next"]
    assert not {"wait", "step"} & block.keys()
    assert here.stored_item(1).labels == []
    assert _writes(here) == ["update_item_body", "remove_label"]


def test_a_label_the_forge_refuses_to_remove_keeps_the_answer_and_names_the_repair(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    _put_step(here)
    here.fail_label_removals("the forge said no")

    answered = _serve(monkeypatch, _answer_line())

    assert answered["isError"] is False
    assert answered["structuredContent"]["answered"] is True
    assert "gh issue edit 1 --remove-label needs-operator" in answered["structuredContent"]["note"]
    assert "wait" not in body.locate_block(here.stored_body(1)).data


def _refusal_cases() -> list[tuple[dict[str, str], dict[str, object], str]]:
    return [
        (_YES_NO_STEP, {"step": "Another step."}, "no longer"),
        (_YES_NO_STEP, {"result": "report", "text": "Done."}, "does not fit"),
        (_REPORT_STEP, {"result": "Erfolgreich"}, "does not fit"),
    ]


@pytest.mark.parametrize(
    ("table", "arguments", "reason"),
    _refusal_cases(),
    ids=[
        "changed-step",
        "report-unasked",
        "report-missing",
    ],
)
def test_a_chat_answer_that_does_not_fit_is_refused_with_nothing_written(
    here: board_forge.BoardForge,
    monkeypatch: pytest.MonkeyPatch,
    table: dict[str, str],
    arguments: dict[str, object],
    reason: str,
) -> None:
    _put_step(here, table)
    before = here.stored_body(1)

    refused = _serve(monkeypatch, _answer_line(**arguments))

    assert reason in refused["content"][0]["text"]
    assert refused["isError"] is True
    assert here.stored_body(1) == before
    assert _writes(here) == []


def test_a_chat_answer_on_an_item_without_a_step_is_refused_with_nothing_written(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = here.stored_body(1)

    refused = _serve(monkeypatch, _answer_line())

    assert "no longer" in refused["content"][0]["text"]
    assert refused["isError"] is True
    assert here.stored_body(1) == before
    assert _writes(here) == []
