"""`aco mcp` (`specs/mcp.spec.md`) as a real child process over pipes, its forge
the board's test forge."""

import io
import json
import os
import select
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import IO, Any, cast

import board_forge
import pytest
from board_fixtures import board_issue, complete_contract
from cli_fixtures import run_cli
from discovery_fixtures import (
    configure_root,
    isolate_config_file,
    repository_with_card,
    write_config,
)
from github_fixtures import FakeForge, serve_forge
from mcp_lines import Script, call_line
from option_cards import GOLDEN_CARD_HASH, ask_card, open_option_entry

from aco import body_fence, cli, expectations, forge, session, workboard
from aco.board.aco_source import AcoSource

_WAIT_SECONDS = 30
_CHILD_PROGRAM = (
    "import board_forge, sys; from aco import cli, session; "
    "session.run_context = board_forge.run_context; raise SystemExit(cli.main(['mcp']))"
)


@pytest.fixture(autouse=True)
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return isolate_config_file(tmp_path, monkeypatch)


@pytest.fixture
def root(tmp_path: Path, config_file: Path) -> Path:
    return configure_root(tmp_path, config_file)


@pytest.fixture(autouse=True)
def _empty_global_git_config(isolated_global_git_config: Path) -> None:
    """Real git in the child reads an empty global configuration."""


@dataclass
class _Child:
    process: subprocess.Popen[str]

    @property
    def stdin(self) -> IO[str]:
        return cast("IO[str]", self.process.stdin)

    @property
    def stdout(self) -> IO[str]:
        return cast("IO[str]", self.process.stdout)

    def send(self, message: dict[str, object] | str) -> None:
        self.stdin.write((message if isinstance(message, str) else json.dumps(message)) + "\n")
        self.stdin.flush()

    def receive(self) -> dict[str, Any]:
        ready, _, _ = select.select([self.stdout], [], [], _WAIT_SECONDS)
        assert ready, "the child answered nothing in time"
        return json.loads(self.stdout.readline())

    def ask(
        self, request_id: int, method: str, params: dict[str, object] | None = None
    ) -> dict[str, Any]:
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        answer = self.receive()
        assert answer["id"] == request_id
        return answer

    def read_inbox(self, request_id: int) -> dict[str, Any]:
        answer = self.ask(request_id, "tools/call", {"name": "read_inbox", "arguments": {}})
        return answer["result"]


@contextmanager
def _started() -> Iterator[_Child]:
    child_environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(Path(board_forge.__file__).parent), os.environ.get("PYTHONPATH", "")]
        ),
    }
    process = subprocess.Popen(  # noqa: S603 - the interpreter running these tests
        [sys.executable, "-c", _CHILD_PROGRAM],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_environment,
    )
    child = _Child(process)
    try:
        yield child
    finally:
        process.kill()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        process.wait(timeout=_WAIT_SECONDS)


def _finish(child: _Child) -> tuple[int, str, str]:
    """End the child by closing its stdin: its exit code, the rest of its
    stdout and its stderr."""
    child.stdin.close()
    rest = child.stdout.read()
    stderr = cast("IO[str]", child.process.stderr).read()
    return child.process.wait(timeout=_WAIT_SECONDS), rest, stderr


def test_a_session_lists_the_tool_and_reads_the_waiting_lines_of_every_repository(
    root: Path,
) -> None:
    repository_with_card(root / "here", 1, "Here")
    elsewhere = repository_with_card(root / "group" / "elsewhere", 2, "Elsewhere")
    ruled = {**open_option_entry(), "ruling": "A", "ruled_on": date(2026, 10, 28), "via": "board"}
    elsewhere.put_item(3, board_forge.item_body(ruled), title="Ruled")

    with _started() as child:
        initialized = child.ask(1, "initialize", {"protocolVersion": "2025-06-18"})
        child.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        child.send("")
        listed = child.ask(2, "tools/list")
        inbox = child.read_inbox(3)
        exit_code, rest, stderr = _finish(child)

    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    assert [tool["name"] for tool in listed["result"]["tools"]] == [
        "read_inbox",
        "ask",
        "record_answer",
        "step",
    ]
    assert inbox["isError"] is False
    structured = inbox["structuredContent"]
    assert structured["root"] == str(root)
    assert [
        (entry["repository"], [item["number"] for item in entry["items"]])
        for entry in structured["repositories"]
    ] == [("board-forge/elsewhere", [2]), ("board-forge/here", [1])]
    assert structured["unreadable"] == []
    assert (exit_code, rest, stderr) == (0, "", "")


def _ask_line(request_id: int, repository: str = "board-forge/here", item: int = 1) -> str:
    card = ask_card(question="Soll der Take danach markiert bleiben?")
    arguments = {"repository": repository, "item": item, **card}
    return call_line(request_id, "ask", arguments)


def _arrive(root: Path) -> None:
    repository_with_card(root / "arrived", 1, "Arrived")


def _serve_in_process(
    monkeypatch: pytest.MonkeyPatch, *steps: str | bytes | Callable[[], None]
) -> tuple[int, list[dict[str, Any]]]:
    """`aco mcp` through its entry point over the board's test forge: the exit
    code and every answer line."""
    replies = io.StringIO()
    monkeypatch.setattr(session, "run_context", board_forge.run_context)
    monkeypatch.setattr(sys, "stdin", Script(*steps))
    monkeypatch.setattr(sys, "stdout", replies)
    exit_code = cli.main(["mcp"])
    return exit_code, [json.loads(line) for line in replies.getvalue().splitlines()]


def test_every_call_scans_afresh_and_a_refusal_is_a_tool_error_the_next_call_recovers_from(
    root: Path, config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_text = config_file.read_text(encoding="utf-8")
    config_file.unlink()

    exit_code, answers = _serve_in_process(
        monkeypatch,
        "",
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        call_line(1),
        lambda: write_config(config_file, config_text),
        call_line(2),
        lambda: _arrive(root),
        call_line(3),
    )

    missing, empty, found = (answer["result"] for answer in answers)
    assert (exit_code, missing["isError"]) == (0, True)
    assert str(config_file) in missing["content"][0]["text"]
    assert empty["isError"] is True
    assert str(root) in empty["content"][0]["text"]
    assert [entry["repository"] for entry in found["structuredContent"]["repositories"]] == [
        "board-forge/arrived"
    ]


def test_a_root_holding_only_unreadable_directories_is_a_tool_error_naming_the_root_and_the_reasons(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (root / "broken" / ".git").mkdir(parents=True)

    _, [answer] = _serve_in_process(monkeypatch, call_line(1))

    result = answer["result"]
    assert result["isError"] is True
    assert str(root) in result["content"][0]["text"]
    assert str(root / "broken") in result["content"][0]["text"]


@pytest.mark.parametrize(
    "bad_line", [b"\xff\xfe", b"[" * 100_000, b"1" * 5_000], ids=["not-utf-8", "nested", "digits"]
)
def test_a_line_the_parser_cannot_handle_is_answered_and_the_next_request_still_is(
    bad_line: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    exit_code, [bad, ping] = _serve_in_process(
        monkeypatch, bad_line, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    )

    assert (exit_code, bad["id"], bad["error"]["code"], ping["id"]) == (0, None, -32700, 1)


def test_a_repository_whose_read_fails_is_listed_as_unavailable_beside_the_others(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_with_card(root / "good", 1, "Good")
    repository_with_card(root / "broken", 2, "Broken").fail_listing("the forge is down")

    _, [answer] = _serve_in_process(monkeypatch, call_line(1))

    assert [
        (entry["repository"], entry.get("unavailable"))
        for entry in answer["result"]["structuredContent"]["repositories"]
    ] == [("board-forge/broken", "the forge is down"), ("board-forge/good", None)]


@dataclass(frozen=True)
class _LabelledForge(board_forge.BoardForge):
    """The board's test forge, whose listing carries `needs-operator` on the
    items numbered in `labelled`."""

    labelled: frozenset[int] = frozenset()

    def list_open_board_issues(self) -> tuple[workboard.Issue, ...]:
        return tuple(
            replace(issue, labels=("needs-operator",)) if issue.number in self.labelled else issue
            for issue in super().list_open_board_issues()
        )


def test_a_step_shows_in_the_inbox_read_and_each_repository_is_listed_once(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = repository_with_card(root / "here", 1, "Here")
    here.put_item(2, complete_contract("Rotate the key."), title="Key")
    here.put_item(3, complete_contract("Not a step."), title="Plain")
    elsewhere = repository_with_card(root / "elsewhere", 4, "Elsewhere")

    def build_forge(context: session.RunContext) -> board_forge.BoardForge:
        return _LabelledForge(context.toplevel, frozenset({1, 2}))

    monkeypatch.setattr(
        session,
        "run_context",
        lambda repo: session.RunContext(
            repo, build_forge=build_forge, today=lambda: board_forge.RULING_DAY
        ),
    )
    monkeypatch.setattr(sys, "stdin", Script(call_line(1)))
    replies = io.StringIO()
    monkeypatch.setattr(sys, "stdout", replies)

    exit_code = cli.main(["mcp"])

    [answer] = [json.loads(line) for line in replies.getvalue().splitlines()]
    entries = {
        entry["repository"]: entry
        for entry in answer["result"]["structuredContent"]["repositories"]
    }
    assert exit_code == 0
    assert entries["board-forge/here"]["steps"] == [
        {"number": 2, "title": "Key", "step": "Rotate the key."},
        {"number": 1, "title": "Here", "step": "X"},
    ]
    assert [item["number"] for item in entries["board-forge/here"]["items"]] == [1]
    assert entries["board-forge/elsewhere"]["steps"] == []
    for checkout in (here, elsewhere):
        listings = [
            request
            for request in checkout.request_log()
            if request.operation == board_forge.ForgeOperation.LIST_OPEN_ISSUES
        ]
        assert len(listings) == 1


def test_an_asked_card_shows_in_the_inbox_read_and_is_stored_once(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = repository_with_card(root / "here", 1, "Here")

    _, [asked, repeated, inbox] = _serve_in_process(
        monkeypatch, _ask_line(1), _ask_line(2), call_line(3)
    )

    written, again = asked["result"], repeated["result"]
    line = written["structuredContent"]["line"]
    assert (written["isError"], written["structuredContent"]["written"]) == (False, True)
    assert written["structuredContent"]["repository"] == "board-forge/here"
    assert (line["index"], line["asked_on"]) == (2, board_forge.RULING_DAY.isoformat())
    assert (again["structuredContent"]["written"], again["structuredContent"]["line"]) == (
        False,
        line,
    )
    [item] = inbox["result"]["structuredContent"]["repositories"][0]["items"]
    assert [shown["index"] for shown in item["lines"]] == [1, 2]
    assert item["lines"][1] == line
    assert here.body_writes() == [1]


@pytest.mark.parametrize(
    ("ask_line", "sentence"),
    [
        pytest.param(_ask_line(1, repository="board-forge/nowhere"), "no repository", id="unknown"),
        pytest.param(_ask_line(1, item=9), "9", id="missing-item"),
    ],
)
def test_a_card_for_an_undiscovered_repository_or_item_is_a_tool_error_that_writes_nothing(
    ask_line: str, sentence: str, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = repository_with_card(root / "here", 1, "Here")

    _, [answer] = _serve_in_process(monkeypatch, ask_line)

    result = answer["result"]
    assert result["isError"] is True
    assert sentence in result["content"][0]["text"]
    assert here.body_writes() == []


class _ClosedPipe(io.StringIO):
    """Standard output whose reader is gone, over a descriptor the test owns."""

    def __init__(self, descriptor: int) -> None:
        super().__init__()
        self._descriptor = descriptor

    def write(self, text: str) -> int:
        raise BrokenPipeError

    def fileno(self) -> int:
        return self._descriptor


def test_a_broken_pipe_ends_the_server_with_exit_0(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_with_card(root / "here", 1, "Here")
    read_end, write_end = os.pipe()
    os.close(read_end)
    monkeypatch.setattr(session, "run_context", board_forge.run_context)
    monkeypatch.setattr(sys, "stdin", Script(call_line(1)))
    monkeypatch.setattr(sys, "stdout", _ClosedPipe(write_end))
    try:
        exit_code = cli.main(["mcp"])
    finally:
        os.close(write_end)

    assert exit_code == 0


def test_a_host_that_closed_its_pipe_ends_the_server_without_a_traceback() -> None:
    with _started() as child:
        child.stdout.close()
        child.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        child.stdin.close()
        stderr = cast("IO[str]", child.process.stderr).read()
        exit_code = child.process.wait(timeout=_WAIT_SECONDS)

    assert (exit_code, stderr) == (0, "")


def test_the_global_repo_is_refused_before_anything_is_served(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(["--repo", "owner/name", "mcp"])

    captured = capsys.readouterr()
    assert (exit_code, captured.out) == (2, "")
    assert (
        captured.err
        == "ERROR: aco mcp finds its repositories itself; --repo does not apply to it\n"
    )


def test_an_unwritable_lock_directory_is_a_tool_error_that_writes_nothing(
    root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    here = repository_with_card(root / "here", 1, "Here")
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker))

    _, [answer] = _serve_in_process(monkeypatch, _ask_line(1))

    result = answer["result"]
    assert result["isError"] is True
    assert "cannot lock the item" in result["content"][0]["text"]
    assert here.body_writes() == []


@pytest.fixture
def here(root: Path) -> board_forge.BoardForge:
    return repository_with_card(root / "here", 1, "Here")


def _record_line(request_id: int = 1, /, **changes: object) -> str:
    arguments: dict[str, object | None] = {
        "repository": "board-forge/here",
        "item": 1,
        "line": 1,
        "card_hash": GOLDEN_CARD_HASH,
        "option": "A",
        **changes,
    }
    given = {key: value for key, value in arguments.items() if value is not None}
    return call_line(request_id, "record_answer", given)


def _stored_item(**changes: object) -> dict[str, object]:
    return {**open_option_entry(), **changes}


def test_a_chat_answer_is_one_write_in_the_items_turn_that_answers_the_ruled_line(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before = here.stored_body(1)
    lock_held_at_writes: list[bool] = []
    write = board_forge.BoardForge.update_item_body

    def witnessed(self: board_forge.BoardForge, number: int, body: str, *, replacing: str) -> None:
        lock_held_at_writes.append(board_forge.item_lock_is_held(tmp_path))
        write(self, number, body, replacing=replacing)

    monkeypatch.setattr(board_forge.BoardForge, "update_item_body", witnessed)

    _, [answer] = _serve_in_process(monkeypatch, _record_line())

    result = answer["result"]
    [entry] = here.stored_entries(1)
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    structured = result["structuredContent"]
    assert (structured["repository"], structured["item"], structured["open"]) == (
        "board-forge/here",
        1,
        0,
    )
    assert (
        structured["line"]["index"],
        structured["line"]["ruling"],
        structured["line"]["via"],
    ) == (
        1,
        "A",
        "chat",
    )
    assert structured["line"]["ruled_on"] == board_forge.RULING_DAY.isoformat()
    assert (entry["ruling"], entry["via"], entry["card_hash"]) == ("A", "chat", GOLDEN_CARD_HASH)
    assert here.body_writes() == [1]
    assert here.body_replacings() == [before]
    assert lock_held_at_writes == [True]


@pytest.mark.parametrize(
    "words",
    [
        "lieber morgen",
        "  \N{LINE SEPARATOR}\n```\n[[expectation]]\n",
        "\N{NEXT LINE}\N{PARAGRAPH SEPARATOR}```aco",
        "x\N{LINE SEPARATOR}```\N{LINE SEPARATOR}y",
        "x\N{NEXT LINE}```\N{NEXT LINE}y",
        "x\N{PARAGRAPH SEPARATOR}```\N{PARAGRAPH SEPARATOR}y",
    ],
)
def test_an_answer_in_the_operators_words_is_stored_verbatim_and_reads_back_equal(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch, words: str
) -> None:
    _, [answer, inbox] = _serve_in_process(
        monkeypatch, _record_line(option=None, other=words), call_line(2)
    )

    [entry] = here.stored_entries(1)
    fences = body_fence.walk_fences(here.stored_body(1)).fences
    assert answer["result"]["isError"] is False
    assert [fence.info for fence in fences] == ["aco"]
    assert (entry["ruling"], entry["other"], entry["via"]) == ("other", words, "chat")
    assert answer["result"]["structuredContent"]["line"]["ruling"] == "other"
    assert inbox["result"]["structuredContent"]["repositories"][0].get("items", []) == []


@pytest.mark.usefixtures("github_world")
def test_a_chat_answer_binds_like_a_board_ruling(
    here: board_forge.BoardForge,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    unruled = here.stored_body(1)
    with monkeypatch.context() as served:
        _, [inbox_before, _, inbox_after] = _serve_in_process(
            served, call_line(1), _record_line(2), call_line(3)
        )
    ruled = here.stored_body(1)
    serve_forge(monkeypatch, FakeForge(board_issues=(board_issue(1, "Here", unruled),)))
    next_before = run_cli(["next"], capsys).expect_success()
    serve_forge(monkeypatch, FakeForge(board_issues=(board_issue(1, "Here", ruled),)))
    rulings = json.loads(run_cli(["rulings", "--json"], capsys).expect_success())
    shown = json.loads(run_cli(["board", "--json"], capsys).expect_success())["items"][0]
    [decision_row] = AcoSource(here.directory).rows()
    next_after = run_cli(["next"], capsys).expect_success()

    listed = inbox_before["result"]["structuredContent"]["repositories"][0]["items"]
    assert [line["index"] for item in listed for line in item["lines"]] == [1]
    assert inbox_after["result"]["structuredContent"]["repositories"][0].get("items", []) == []
    [ruled_line] = rulings["rulings"][0]["lines"]
    assert (ruled_line["ruling"], ruled_line["via"]) == ("A", "chat")
    assert shown["expectation_state"] == "ruled"
    [decision_line] = decision_row.lines
    assert isinstance(decision_line, expectations.OptionLine)
    decided = decision_line.decision
    assert decided is not None
    assert (decided.answer, decided.via.value) == ("A", "chat")
    assert "expectations unruled" in next_before
    assert "expectations unruled" not in next_after


def test_a_repeat_is_refused_and_writes_nothing(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, [first, repeated] = _serve_in_process(
        monkeypatch, _record_line(1), _record_line(2, option="B")
    )

    assert first["result"]["isError"] is False
    assert repeated["result"]["isError"] is True
    assert "already ruled" in repeated["result"]["content"][0]["text"]
    assert here.stored_entries(1)[0]["ruling"] == "A"
    assert here.body_writes() == [1]


@pytest.mark.parametrize("arrange", ["close", "stranger"])
def test_a_closed_item_and_an_item_a_non_member_wrote_are_ruled(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch, arrange: str
) -> None:
    if arrange == "close":
        here.close_item(1)
    else:
        here.put_item(1, here.stored_body(1), author_is_member=False)

    _, [answer] = _serve_in_process(monkeypatch, _record_line())

    assert answer["result"]["isError"] is False
    assert here.stored_entries(1)[0]["ruling"] == "A"


def test_a_line_with_its_head_is_ruled_and_loses_its_returned_keys(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    returned = _stored_item(returned_on=date(2026, 10, 2), returned_note="unklar")
    here.put_item(1, board_forge.item_body(returned))

    _, [answer] = _serve_in_process(monkeypatch, _record_line())

    [entry] = here.stored_entries(1)
    assert answer["result"]["isError"] is False
    assert (entry["ruling"], "returned_on" in entry, "returned_note" in entry) == (
        "A",
        False,
        False,
    )


_YES_NO = {"text": "Alt", "ruling": "no", "ruled_on": date(2026, 10, 1)}


@pytest.mark.parametrize(
    ("stored", "changes", "sentence"),
    [
        pytest.param([_stored_item()], {"item": 9}, "does not exist", id="missing-item"),
        pytest.param([_stored_item()], {"line": 0}, "line 0 out of range", id="line-zero"),
        pytest.param([_stored_item()], {"line": 3}, "line 3 out of range", id="line-past-the-end"),
        pytest.param([_stored_item()], {"card_hash": "sha256:0"}, "changed since", id="card-hash"),
        pytest.param([_stored_item()], {"option": "D"}, "has no option D", id="letter-off-card"),
        pytest.param([_YES_NO], {}, "yes/no line", id="yes-no-line"),
        pytest.param(
            [{"text": "Weg", "withdrawn_on": date(2026, 10, 2)}], {}, "withdrawn", id="withdrawn"
        ),
        pytest.param(
            [_stored_item(asked_on=date(2026, 12, 1))], {}, "after today", id="asked-after-today"
        ),
    ],
)
def test_a_refusal_of_the_ruling_is_a_tool_error_with_its_sentence_and_writes_nothing(
    here: board_forge.BoardForge,
    monkeypatch: pytest.MonkeyPatch,
    stored: list[dict[str, object]],
    changes: dict[str, object],
    sentence: str,
) -> None:
    here.put_item(1, board_forge.item_body(*stored))

    _, [answer] = _serve_in_process(monkeypatch, _record_line(**changes))

    result = answer["result"]
    assert result["isError"] is True
    assert sentence in result["content"][0]["text"]
    assert here.body_writes() == []


def test_a_malformed_body_is_a_tool_error_that_writes_nothing(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    here.put_item(1, "no block in this body")

    _, [answer] = _serve_in_process(monkeypatch, _record_line())

    assert answer["result"]["isError"] is True
    assert "no aco block" in answer["result"]["content"][0]["text"]
    assert here.body_writes() == []


def test_an_undiscovered_repository_is_a_tool_error_that_writes_nothing(
    here: board_forge.BoardForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, [answer] = _serve_in_process(monkeypatch, _record_line(repository="board-forge/nowhere"))

    result = answer["result"]
    assert result["isError"] is True
    assert "no repository" in result["content"][0]["text"]
    assert here.body_writes() == []


@pytest.mark.parametrize(
    "check_answer",
    [
        pytest.param(
            forge.ForgeBodyOverwrittenError(1, "2026-11-08T10:05:00Z", "ghost", kept=True),
            id="overwritten-kept",
        ),
        pytest.param(
            forge.ForgeBodyOverwrittenError(1, "2026-11-08T10:05:00Z", "ghost", kept=False),
            id="overwritten-lost",
        ),
        pytest.param(forge.ForgeBodyNotVerifiedError(1, "timeout"), id="not-verified"),
    ],
)
def test_the_body_write_checks_answer_passes_through_as_the_calls_error(
    here: board_forge.BoardForge,
    monkeypatch: pytest.MonkeyPatch,
    check_answer: forge.ForgeBodyOverwrittenError | forge.ForgeBodyNotVerifiedError,
) -> None:
    here.answer_next_write(check_answer)

    _, [answer] = _serve_in_process(monkeypatch, _record_line())

    result = answer["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"] == str(check_answer)
    assert here.stored_entries(1)[0]["ruling"] == "A"
