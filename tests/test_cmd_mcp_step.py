"""`aco mcp`'s step tool (`specs/mcp.spec.md`) through `cli.main(["mcp"])` over the
board's test forge: marking an item, opening one, finding the one a failed call
left, and what each refusal and each failure after a write leaves behind."""

import io
import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import board_forge
import pytest
from board_fixtures import complete_contract, write_repository_config
from cli_fixtures import run_cli
from discovery_fixtures import (
    configure_root,
    isolate_config_file,
    repository_with_card,
)

from aco import body, cli, forge, protocol, session, workboard

STEP = "Rotate the deploy key."
TITLE = "Rotate the deploy key"
_LABEL = workboard.NEEDS_OPERATOR_LABEL
_WRITES = (
    board_forge.ForgeOperation.WRITE_BODY,
    board_forge.ForgeOperation.CREATE_ISSUE,
    board_forge.ForgeOperation.ADD_LABEL,
)


@pytest.fixture(autouse=True)
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return isolate_config_file(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def _empty_global_git_config(isolated_global_git_config: Path) -> None:
    """Real git reads an empty global configuration."""


@pytest.fixture
def here(tmp_path: Path, config_file: Path) -> board_forge.BoardForge:
    root = configure_root(tmp_path, config_file)
    return repository_with_card(root / "here", 1, "Here")


class _Script:
    """Standard input that hands out its lines one by one."""

    def __init__(self, *lines: str) -> None:
        self._lines = lines

    @property
    def buffer(self) -> Iterator[bytes]:
        for line in self._lines:
            yield line.encode() + b"\n"


def _call_line(request_id: int, name: str, arguments: dict[str, object]) -> str:
    params = {"name": name, "arguments": arguments}
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": params}
    )


def _step_line(request_id: int = 1, /, **changes: object) -> str:
    arguments: dict[str, object | None] = {
        "repository": "board-forge/here",
        "step": STEP,
        "item": 1,
        **changes,
    }
    given = {key: value for key, value in arguments.items() if value is not None}
    return _call_line(request_id, "step", given)


def _inbox_line(request_id: int) -> str:
    return _call_line(request_id, "read_inbox", {})


def _serve(monkeypatch: pytest.MonkeyPatch, *lines: str) -> list[dict[str, Any]]:
    """The results of every line `aco mcp` answers."""
    replies = io.StringIO()
    with monkeypatch.context() as served:
        served.setattr(session, "run_context", board_forge.run_context)
        served.setattr(sys, "stdin", _Script(*lines))
        served.setattr(sys, "stdout", replies)
        exit_code = cli.main(["mcp"])
    assert exit_code == 0
    return [json.loads(line)["result"] for line in replies.getvalue().splitlines()]


def _text(result: dict[str, Any]) -> str:
    return result["content"][0]["text"]


def _writes(checkout: board_forge.BoardForge) -> list[tuple[str, int | None]]:
    return [
        (request.operation.value, request.item)
        for request in checkout.request_log()
        if request.operation in _WRITES
    ]


def _steps_of(inbox: dict[str, Any]) -> list[dict[str, Any]]:
    return inbox["structuredContent"]["repositories"][0]["steps"]


def _fail_once(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    error: protocol.ClaimError,
    *,
    after_real_call: bool,
) -> None:
    """The first call of `operation` on the forge raises `error`, after the
    real call when `after_real_call`; the next calls are real."""
    real = getattr(board_forge.BoardForge, operation)
    failed: list[bool] = []

    def wrapper(self: board_forge.BoardForge, *args: object, **kwargs: object) -> object:
        if failed:
            return real(self, *args, **kwargs)
        failed.append(True)
        if after_real_call:
            real(self, *args, **kwargs)
        raise error

    monkeypatch.setattr(board_forge.BoardForge, operation, wrapper)


def _witness_lock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, operation: str) -> list[bool]:
    """Whether the item lock is held at each call of `operation` on the forge."""
    real: Callable[..., None] = getattr(board_forge.BoardForge, operation)
    held: list[bool] = []

    def witnessed(self: board_forge.BoardForge, *args: object, **kwargs: object) -> None:
        held.append(board_forge.item_lock_is_held(tmp_path))
        real(self, *args, **kwargs)

    monkeypatch.setattr(board_forge.BoardForge, operation, witnessed)
    return held


def test_a_step_on_an_item_is_one_body_write_then_one_label_both_in_the_items_turn(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    here.put_item(1, complete_contract("Old step."), title="Key")
    lock_held_at_body = _witness_lock(monkeypatch, tmp_path, "update_item_body")
    lock_held_at_label = _witness_lock(monkeypatch, tmp_path, "add_label")

    marked, inbox = _serve(monkeypatch, _step_line(1), _inbox_line(2))

    assert marked["isError"] is False
    assert json.loads(_text(marked)) == marked["structuredContent"]
    assert marked["structuredContent"] == {
        "repository": "board-forge/here",
        "item": 1,
        "step": STEP,
        "created": False,
    }
    assert body.locate_block(here.stored_body(1)).data["next"] == STEP
    assert here.stored_item(1).labels == [_LABEL]
    assert _writes(here) == [("update_item_body", 1), ("add_label", 1)]
    assert (lock_held_at_body, lock_held_at_label) == ([True], [True])
    assert _steps_of(inbox) == [{"number": 1, "title": "Key", "step": STEP}]


def test_the_same_call_again_writes_no_body_and_calls_the_label_again(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, again = _serve(monkeypatch, _step_line(1), _step_line(2))

    assert again["structuredContent"] == first["structuredContent"]
    assert _writes(here) == [("update_item_body", 1), ("add_label", 1), ("add_label", 1)]
    assert here.stored_item(1).labels == [_LABEL]


def test_a_title_opens_a_labelled_task_whose_body_is_complete_and_the_inbox_lists_it(
    here: board_forge.BoardForge,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    opened, inbox = _serve(monkeypatch, _step_line(1, item=None, title=TITLE), _inbox_line(2))

    created = here.stored_item(2)
    monkeypatch.chdir(here.directory)
    checked = run_cli(["check", "-", "--json"], capsys, stdin=created.body)
    data = body.locate_block(created.body).data
    assert opened["structuredContent"] == {
        "repository": "board-forge/here",
        "item": 2,
        "step": STEP,
        "created": True,
    }
    assert (created.title, created.kind, created.labels) == (TITLE, "task", [_LABEL])
    assert (checked.status, json.loads(checked.stdout)["ok"]) == (0, True)
    assert data["next"] == STEP
    assert board_forge.RULING_DAY.isoformat() in str(data["now"])
    assert _writes(here) == [("create_issue", 2), ("add_label", 2)]
    assert {"number": 2, "title": TITLE, "step": STEP} in _steps_of(inbox)


def test_the_same_title_call_again_opens_no_second_item_and_calls_the_label_again(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, again = _serve(
        monkeypatch, _step_line(1, item=None, title=TITLE), _step_line(2, item=None, title=TITLE)
    )

    assert first["structuredContent"]["created"] is True
    assert again["structuredContent"] == {**first["structuredContent"], "created": False}
    assert _writes(here) == [("create_issue", 2), ("add_label", 2), ("add_label", 2)]


def _standing(
    number: int, step: str = STEP, *, member: bool = True
) -> dict[int, board_forge.StoredItem]:
    return {number: board_forge.StoredItem(TITLE, complete_contract(step), author_is_member=member)}


@pytest.mark.parametrize(
    ("standing", "title_given", "expected_item", "created"),
    [
        pytest.param(_standing(2), TITLE, 2, False, id="same-title-and-step-without-the-label"),
        pytest.param(_standing(2), f"  {TITLE}\n", 2, False, id="padded-title"),
        pytest.param(
            {**_standing(2), **_standing(4), **_standing(3)}, TITLE, 4, False, id="highest"
        ),
        pytest.param(_standing(2, "Another step."), TITLE, 3, True, id="same-title-another-step"),
        pytest.param(_standing(2, member=False), TITLE, 3, True, id="a-non-members-item"),
        pytest.param(
            {2: board_forge.StoredItem(TITLE, "no block here")}, TITLE, 3, True, id="unreadable"
        ),
    ],
)
def test_the_lookup_marks_the_item_a_member_wrote_with_that_title_and_step_or_opens_one(
    standing: dict[int, board_forge.StoredItem],
    title_given: str,
    expected_item: int,
    created: bool,
    here: board_forge.BoardForge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for number, item in standing.items():
        here.put_item(number, item.body, title=item.title, author_is_member=item.author_is_member)

    [result] = _serve(monkeypatch, _step_line(1, item=None, title=title_given))

    assert result["structuredContent"]["item"] == expected_item
    assert result["structuredContent"]["created"] is created
    assert here.stored_item(expected_item).labels == [_LABEL]
    assert [operation for operation, _ in _writes(here)].count("create_issue") == int(created)


def test_a_title_with_another_step_leaves_the_first_item_as_it_was(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    here.put_item(2, complete_contract("Another step."), title=TITLE)
    before = here.stored_item(2)

    _serve(monkeypatch, _step_line(1, item=None, title=TITLE))

    assert here.stored_item(2) == before


@pytest.mark.parametrize("arrange", ["close", "stranger", "missing", "malformed", "unknown"])
def test_a_refused_target_is_a_tool_error_with_its_sentence_and_writes_nothing(
    arrange: str, here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    changes: dict[str, object] = {}
    match arrange:
        case "close":
            here.close_item(1)
        case "stranger":
            here.put_item(1, here.stored_body(1), author_is_member=False)
        case "missing":
            changes = {"item": 9}
        case "malformed":
            here.put_item(1, "no block in this body")
        case _:
            changes = {"repository": "board-forge/nowhere"}

    [result] = _serve(monkeypatch, _step_line(1, **changes))

    assert result["isError"] is True
    assert _text(result)
    assert _writes(here) == []


@pytest.mark.parametrize(
    "changes",
    [pytest.param({}, id="item"), pytest.param({"item": None, "title": TITLE}, id="title")],
)
def test_a_state_ref_repository_refuses_before_any_lookup_or_write(
    changes: dict[str, object], here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_repository_config(here.directory, 'storage = "state-ref"\n')

    [result] = _serve(monkeypatch, _step_line(1, **changes))

    assert result["isError"] is True
    assert "aco item edit" in _text(result)
    assert here.request_log() == ()


def test_a_body_check_that_fails_is_the_calls_error_and_a_repeat_sets_the_label(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    check_answer = forge.ForgeBodyNotVerifiedError(1, "timeout")
    here.answer_next_write(check_answer)

    failed, repeated = _serve(monkeypatch, _step_line(1), _step_line(2))

    assert (failed["isError"], _text(failed)) == (True, str(check_answer))
    assert repeated["isError"] is False
    assert _writes(here) == [("update_item_body", 1), ("add_label", 1)]
    assert here.stored_item(1).labels == [_LABEL]


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(forge.ForgeError("HTTP 403: forbidden"), id="forge-error"),
        pytest.param(
            forge.ForgeMalformedResponseError("HTTP 403: forbidden"), id="answer-without-label"
        ),
        pytest.param(protocol.ClaimError("HTTP 403: forbidden"), id="gh-did-not-start"),
    ],
)
def test_a_failed_label_after_the_body_says_the_step_stands_and_a_repeat_sets_the_label(
    error: protocol.ClaimError, here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_once(monkeypatch, "add_label", error, after_real_call=False)

    failed, repeated = _serve(monkeypatch, _step_line(1), _step_line(2))

    assert failed["isError"] is True
    assert "HTTP 403: forbidden" in _text(failed)
    assert "label" in _text(failed)
    assert repeated["isError"] is False
    assert here.stored_item(1).labels == [_LABEL]
    assert [operation for operation, _ in _writes(here)].count("update_item_body") == 1


@pytest.mark.parametrize(
    ("operation", "error", "after_real_call", "names_the_item"),
    [
        pytest.param("add_label", forge.ForgeError("HTTP 403: forbidden"), False, True, id="label"),
        pytest.param(
            "create_issue",
            forge.ForgeIssueTypeNotSetError(created=2, type_name="Task"),
            True,
            True,
            id="type-not-set",
        ),
        pytest.param(
            "create_issue", forge.ForgeError("connection reset"), True, False, id="answer-lost"
        ),
    ],
)
def test_a_failure_after_the_item_exists_is_finished_by_the_same_call_without_a_second_item(
    operation: str,
    error: protocol.ClaimError,
    after_real_call: bool,
    names_the_item: bool,
    here: board_forge.BoardForge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fail_once(monkeypatch, operation, error, after_real_call=after_real_call)
    line = _step_line(1, item=None, title=TITLE)

    failed, repeated = _serve(monkeypatch, line, line)

    assert failed["isError"] is True
    assert str(error) in _text(failed)
    assert ("#2" in _text(failed)) is names_the_item
    assert repeated["structuredContent"]["item"] == 2
    assert here.stored_item(2).labels == [_LABEL]
    assert [operation for operation, _ in _writes(here)].count("create_issue") == 1
