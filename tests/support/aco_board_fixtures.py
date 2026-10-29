"""A fake `aco` on PATH and a client for the decision board.

The fake parses its arguments with argparse the way aco does, answers
`aco rulings --json` from `rulings.json` in its working directory, and applies
`aco rule` to that same file with aco's own refusals (specs/rule.spec.md:
already ruled, out of range, unknown item), so a test drives the board's real
adapter and server against state it controls. Every invocation is appended to
`aco-calls.jsonl`.
"""

from __future__ import annotations

import errno
import http.client
import json
import os
import secrets
import select
import socket
import stat
import struct
import sys
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest

from aco.board.aco_cli import AcoCli
from aco.board.board import Board, Boards
from aco.board.ports import DecisionPort
from aco.board.server import TOKEN_HEADER, start_board

DEFAULT_LABEL = "repo"
"""The one repo label a single-repo test gets when it does not name its own."""

_FAKE_ACO = """\
import argparse, json, pathlib, sys, time

repository = pathlib.Path.cwd()
with (repository / "aco-calls.jsonl").open("a", encoding="utf-8") as calls:
    calls.write(json.dumps(sys.argv[1:]) + "\\n")
rulings = repository / "rulings.json"


class NamedLine(argparse.Action):
    def __call__(self, parser, namespace, value, option_string=None):
        namespace.named.append({"line": int(value), "option": None, "card_hash": None})


class OfLastLine(argparse.Action):
    def __call__(self, parser, namespace, value, option_string=None):
        if not namespace.named:
            parser.error(option_string + " follows its --line")
        namespace.named[-1][self.dest] = value


parser = argparse.ArgumentParser(prog="aco")
commands = parser.add_subparsers(dest="command", required=True)
listing = commands.add_parser("rulings")
listing.add_argument("--json", action="store_true")
rule = commands.add_parser("rule")
rule.add_argument("item")
rule.set_defaults(named=[])
rule.add_argument("--line", action=NamedLine, required=True)
rule.add_argument("--option", action=OfLastLine)
rule.add_argument("--card-hash", dest="card_hash", action=OfLastLine)
outcomes = rule.add_mutually_exclusive_group()
for outcome in ("yes", "no", "later"):
    outcomes.add_argument("--" + outcome, dest="ruling", action="store_const", const=outcome)
outcomes.add_argument("--other")
outcomes.add_argument("--unclear", action="store_true")
rule.add_argument("--via")
rule.add_argument("--note")
rule.add_argument("--json", action="store_true")
arguments = parser.parse_args()
if arguments.command == "rule":
    picks = [named["option"] is not None for named in arguments.named]
    if getattr(arguments, "ruling", None) is None and not any(picks) and (
        getattr(arguments, "other", None) is None and not getattr(arguments, "unclear", False)
    ):
        parser.error("name an outcome")
    if any(picks) and not all(picks):
        parser.error("--option belongs to every --line or to none")
    if any(picks):
        arguments.ruling = "option"
all_hashed = all(named["card_hash"] is not None for named in getattr(arguments, "named", []))
if getattr(arguments, "other", None) is not None:
    arguments.ruling = "other"
    if arguments.via != "board" or not all_hashed or arguments.note is not None:
        parser.error("--other needs --via board and --card-hash, and takes no --note")
if getattr(arguments, "unclear", False) and (
    arguments.via is not None
    or not all_hashed
    or (arguments.note is not None and not arguments.note.strip())
):
    parser.error("--unclear needs --card-hash and takes no --via and no blank --note")


def refuse(reason, message):
    print("ERROR: " + message, file=sys.stderr)
    print(json.dumps({"ok": False, "reason": reason, "message": message}))
    sys.exit(2)


def wait_if_asked(name):
    delay = repository / name
    if delay.exists():
        time.sleep(float(delay.read_text(encoding="utf-8")))


if arguments.command == "rulings":
    wait_if_asked("rulings-delay-seconds")
    failure = repository / "rulings-failure.txt"
    if failure.exists():
        print(failure.read_text(encoding="utf-8"), file=sys.stderr)
        sys.exit(2)
    stdout = repository / "rulings-stdout.txt"
    if stdout.exists():
        print(stdout.read_text(encoding="utf-8"))
        sys.exit(0)
    rows = json.loads(rulings.read_text(encoding="utf-8"))
    print(json.dumps({"ok": True, "reason": "listed", "rulings": rows}))
    sys.exit(0)

refusal = repository / "rule-refusal.json"
if refusal.exists():
    envelope = json.loads(refusal.read_text(encoding="utf-8"))
    refuse(envelope["reason"], envelope["message"])
rows = json.loads(rulings.read_text(encoding="utf-8"))
wait_if_asked("rule-delay-seconds")
row = next((row for row in rows if str(row["number"]) == arguments.item), None)
if row is None:
    refuse("invalid_item", "#" + arguments.item + " does not exist")
targets = []
for named in arguments.named:
    line = next((line for line in row["lines"] if line["index"] == named["line"]), None)
    if line is None:
        refuse("line_out_of_range", "line %d out of range: this item has %d expectation line(s)"
               % (named["line"], len(row["lines"])))
    if line["ruling"] is not None:
        refuse("already_ruled",
               "line %d is already ruled; a changed ruling is a new line" % named["line"])
    if getattr(arguments, "unclear", False) and line["returned_on"] is not None:
        refuse("with_head", "line %d is already with its head; it comes back once revised"
               % named["line"])
    targets.append((named, line))
indexes = [named["line"] for named in arguments.named]
still_open = sum(1 for entry in row["lines"] if entry["ruling"] is None)
if getattr(arguments, "unclear", False):
    for named, line in targets:
        line["returned_on"], line["returned_note"] = "2026-10-03", arguments.note
    rulings.write_text(json.dumps(rows), encoding="utf-8")
    print(json.dumps({"ok": True, "reason": "returned", "item": row["number"],
                      "index": indexes[0], "lines": indexes, "returned_on": "2026-10-03",
                      "open": still_open}))
    sys.exit(0)
for named, line in targets:
    line["ruling"] = named["option"] or arguments.ruling
    line["ruled_on"] = "2026-10-03"
    if "returned_on" in line:
        line["returned_on"], line["returned_note"] = None, None
    if arguments.via is not None:
        line["via"] = arguments.via
    if arguments.other is not None:
        line["other"] = arguments.other
    if arguments.note is not None:
        line["text"] += " Anmerkung: " + arguments.note
rulings.write_text(json.dumps(rows), encoding="utf-8")
print(json.dumps({"ok": True, "reason": "ruled", "item": row["number"],
                  "index": indexes[0], "lines": indexes,
                  "ruling": targets[0][0]["option"] or arguments.ruling,
                  "ruled_on": "2026-10-03", "open": still_open - len(targets)}))
"""


def install_fake_aco(bin_directory: Path) -> None:
    bin_directory.mkdir(parents=True, exist_ok=True)
    executable = bin_directory / "aco"
    executable.write_text(f"#!{sys.executable}\n{_FAKE_ACO}", encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)


def path_with(bin_directory: Path) -> str:
    return f"{bin_directory}{os.pathsep}{os.environ.get('PATH', '')}"


def empty_repository_with_fake_aco(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> FakeAcoRepository:
    """A repository without expectation lines, its fake `aco` first on PATH."""
    install_fake_aco(tmp_path / "bin")
    monkeypatch.setenv("PATH", path_with(tmp_path / "bin"))
    return named_repository(tmp_path, "repository")


def named_repository(tmp_path: Path, name: str) -> FakeAcoRepository:
    """A further repository directory without expectation lines, sharing
    whichever fake `aco` is already on PATH."""
    directory = tmp_path / name
    directory.mkdir()
    fake = FakeAcoRepository(directory)
    fake.set_rulings()
    return fake


def line(index: int, text: str, *, ruling: str | None = None, **card: str) -> dict[str, object]:
    ruled_on = "2026-10-01" if ruling is not None else None
    return {
        "index": index,
        "text": text,
        "default": None,
        "ruling": ruling,
        "ruled_on": ruled_on,
        **card,
    }


def row(number: int, title: str, *lines: dict[str, object]) -> dict[str, object]:
    open_count = sum(1 for entry in lines if entry["ruling"] is None)
    return {
        "number": number,
        "title": title,
        "open": open_count,
        "total": len(lines),
        "lines": list(lines),
    }


@dataclass(frozen=True)
class FakeAcoRepository:
    directory: Path

    def set_rulings(self, *rows: dict[str, object]) -> None:
        (self.directory / "rulings.json").write_text(json.dumps(list(rows)), encoding="utf-8")

    def refuse_rule(self, reason: str, message: str) -> None:
        envelope = {"ok": False, "reason": reason, "message": message}
        (self.directory / "rule-refusal.json").write_text(json.dumps(envelope), encoding="utf-8")

    def fail_rulings(self, stderr: str) -> None:
        (self.directory / "rulings-failure.txt").write_text(stderr, encoding="utf-8")

    def answer_rulings_with(self, stdout: str) -> None:
        (self.directory / "rulings-stdout.txt").write_text(stdout, encoding="utf-8")

    def delay(self, command: str, seconds: float) -> None:
        """Hold every later `aco <command>` for `seconds` (rule: between read and write)."""
        (self.directory / f"{command}-delay-seconds").write_text(str(seconds), encoding="utf-8")

    def rulings_state(self) -> bytes:
        return (self.directory / "rulings.json").read_bytes()

    def stored_line(self, item: int, index: int) -> dict[str, object]:
        rows = json.loads(self.rulings_state())
        return next(
            line
            for row in rows
            if row["number"] == item
            for line in row["lines"]
            if line["index"] == index
        )

    def calls(self) -> list[list[str]]:
        log = self.directory / "aco-calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(entry) for entry in log.read_text(encoding="utf-8").splitlines()]

    def rule_calls(self) -> list[list[str]]:
        return [call for call in self.calls() if call[0] == "rule"]


@contextmanager
def serving(
    decisions: DecisionPort, *, label: str = DEFAULT_LABEL, **board_options: float
) -> Iterator[BoardClient]:
    """The real board server for one repository labelled `label`, stopped on exit."""
    with serving_many({label: decisions}, **board_options) as client:
        yield client


@contextmanager
def serving_many(
    decisions_by_label: Mapping[str, DecisionPort], **board_options: float
) -> Iterator[BoardClient]:
    """The real board server for every labelled repository, stopped on exit."""
    boards = Boards({label: Board(decisions) for label, decisions in decisions_by_label.items()})
    running = start_board(0, boards, secrets.token_urlsafe(32), **board_options)
    server_thread = threading.Thread(
        target=running.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    server_thread.start()
    try:
        yield BoardClient.from_url(running.url, repos=tuple(decisions_by_label))
    finally:
        running.httpd.shutdown()
        running.httpd.server_close()
        server_thread.join()


def serving_two(
    repositories: tuple[FakeAcoRepository, FakeAcoRepository],
) -> AbstractContextManager[BoardClient]:
    """The real board server for two repositories labelled `a` and `b` -- the
    arrangement every `two_repositories`-backed test shares."""
    repository_a, repository_b = repositories
    return serving_many(
        {
            "a": AcoCli(directory=repository_a.directory),
            "b": AcoCli(directory=repository_b.directory),
        }
    )


@dataclass(frozen=True)
class Response:
    status: int
    body: str
    headers: Message
    """Case-insensitive, as HTTP header names are."""

    @property
    def content_security_policy(self) -> str | None:
        return self.headers.get("Content-Security-Policy")

    def json(self) -> dict[str, object]:
        parsed: dict[str, object] = json.loads(self.body)
        return parsed

    @classmethod
    def from_raw(cls, answer: bytes) -> Response:
        """An answer read straight off the socket, beneath any HTTP client."""
        head, _, body = answer.partition(b"\r\n\r\n")
        status_line, *header_lines = head.decode("latin-1").split("\r\n")
        headers = Message()
        for header_line in header_lines:
            name, _, value = header_line.partition(":")
            headers[name] = value.strip()
        return cls(int(status_line.split(" ")[1]), body.decode("utf-8"), headers)


# A board that refuses a request on its headers answers and closes without
# reading the rest; the kernel then resets the connection. The answer already
# arrived, so the reset ends the conversation instead of failing it.
_PEER_ALREADY_CLOSED = frozenset({errno.ENOTCONN, errno.EPIPE, errno.ECONNRESET})


@contextmanager
def _unless_the_peer_already_closed() -> Iterator[None]:
    try:
        yield
    except OSError as error:
        if error.errno not in _PEER_ALREADY_CLOSED:
            raise


def _received_until_closed(connection: socket.socket) -> bytes:
    received = b""
    with _unless_the_peer_already_closed():
        while chunk := connection.recv(65536):
            received += chunk
    return received


@dataclass(frozen=True)
class BoardClient:
    host: str
    port: int
    token: str
    repos: tuple[str, ...] = (DEFAULT_LABEL,)
    """Every repo label this board was started with, in configured order."""

    @property
    def repo(self) -> str:
        """The one repo most single-repo tests mean when they say none."""
        return self.repos[0]

    @classmethod
    def from_url(cls, url: str, *, repos: tuple[str, ...] = (DEFAULT_LABEL,)) -> BoardClient:
        split = urlsplit(url)
        assert split.hostname is not None
        assert split.port is not None
        return cls(split.hostname, split.port, parse_qs(split.fragment)["t"][0], repos)

    def get_shell(self) -> Response:
        """`GET /`, the SPA shell every board answers with, no token needed."""
        return self._request("GET", "/")

    def send_raw(self, request: bytes) -> bytes:
        """Send bytes as they are, beneath any HTTP client's own checks."""
        with self._connection() as connection:
            with _unless_the_peer_already_closed():
                connection.sendall(request)
                connection.shutdown(socket.SHUT_WR)
            return _received_until_closed(connection)

    def send_unfinished(self, request: bytes) -> bytes:
        """Send the start of a request, keep the connection open, and return
        whatever the board answers before it closes the connection."""
        with self._connection() as connection:
            connection.sendall(request)
            return _received_until_closed(connection)

    def send_dripping(self, head: bytes, body: bytes, interval_seconds: float) -> bytes:
        """Send `head`, then `body` one byte per interval, never pausing long
        enough to look stalled; return the answer once the board sends one."""
        with self._connection() as connection:
            connection.sendall(head)
            for byte in body:
                answer_waiting, _, _ = select.select([connection], [], [], interval_seconds)
                if answer_waiting:
                    break
                connection.sendall(bytes([byte]))
            return _received_until_closed(connection)

    @contextmanager
    def holding_unfinished(self, request: bytes) -> Iterator[None]:
        """Keep a connection open on the start of a request while inside."""
        with self._connection() as connection:
            connection.sendall(request)
            yield

    @contextmanager
    def holding_unread(self, request: bytes) -> Iterator[None]:
        """Send a whole request, then read none of the answer while inside."""
        with socket.socket() as connection:
            # A small receive window set before connecting, so the board's
            # write blocks instead of filling the kernel's buffers.
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            connection.connect((self.host, self.port))
            connection.sendall(request)
            yield

    def send_and_reset(self, request: bytes) -> None:
        """Send a whole request, then hang up with a reset before any answer."""
        with self._connection() as connection:
            connection.sendall(request)
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))

    def _connection(self) -> socket.socket:
        return socket.create_connection((self.host, self.port), timeout=30)

    def call_api(
        self,
        method: str,
        path: str,
        body: str | None = None,
        *,
        presented: str | None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """Send `presented` as the API token header, or no such header for None."""
        token_header = {} if presented is None else {TOKEN_HEADER: presented}
        return self._request(method, path, body, {**token_header, **(headers or {})})

    def get_board_json(self) -> Response:
        return self.call_api("GET", "/api/board", presented=self.token)

    def decide_through_api(
        self,
        line: Mapping[str, object],
        item: int,
        outcome: str,
        *,
        repo: str | None = None,
        note: str | None = None,
    ) -> Response:
        """Post `outcome` for a line exactly as `GET /api/board` listed it."""
        payload = {
            "repo": self.repo if repo is None else repo,
            "item": item,
            "line": line["index"],
            "fingerprint": line["fingerprint"],
            "outcome": outcome,
            "note": note,
        }
        return self.post_rule(payload)

    def decide_card_through_api(
        self,
        item: int,
        lines: Sequence[Mapping[str, object]],
        options: Sequence[str] | None = None,
        answer: Mapping[str, object] | None = None,
        *,
        repo: str | None = None,
    ) -> Response:
        """Post a card for `lines` exactly as `GET /api/board` listed them: a letter
        from `options` per line, or `answer` (`other` or `unclear`) for all of them."""
        letters: Sequence[Mapping[str, str]] = (
            [{} for _ in lines] if options is None else [{"option": letter} for letter in options]
        )
        return self.post_rule(
            {
                "repo": self.repo if repo is None else repo,
                "item": item,
                "lines": [
                    {"line": shown["index"], "fingerprint": shown["fingerprint"], **letter}
                    for shown, letter in zip(lines, letters, strict=True)
                ],
                **(answer or {}),
            }
        )

    def post_rule(self, payload: Mapping[str, object]) -> Response:
        """Post `payload` to `/api/rule` with the board token, as given."""
        return self.call_api("POST", "/api/rule", json.dumps(payload), presented=self.token)

    def _request(
        self,
        method: str,
        path: str,
        body: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=30)
        try:
            connection.request(method, path, body=body, headers=dict(headers or {}))
            response = connection.getresponse()
            return Response(
                status=response.status,
                body=response.read().decode("utf-8"),
                headers=response.headers,
            )
        finally:
            connection.close()


_SVG = '<svg xmlns="http://www.w3.org/2000/svg"/>'


def picture_option(letter: str = "A", **changes: object) -> dict[str, object]:
    return {
        "letter": letter,
        "name": "Song stays open",
        "effect": "The app jumps itself.",
        "picture": _SVG,
        "caption": "Still open",
        "notice": "You stay in your song.",
        "cost": "More code.",
        "undo": "reversible",
        "undo_how": "Any time.",
        "contract": "The song stays open.",
        **changes,
    }


def same_as_today_option(letter: str = "B", **changes: object) -> dict[str, object]:
    return {
        "letter": letter,
        "name": "As today",
        "effect": "The browser jumps.",
        "same_as_today": True,
        "notice": "You pick the song again.",
        "cost": "None.",
        "undo": "final",
        "undo_how": "Nothing is built.",
        "contract": "The link stays a link.",
        **changes,
    }


def first_listed_line(board: BoardClient) -> dict[str, Any]:
    [listed_repo] = cast(list[dict[str, Any]], board.get_board_json().json()["repos"])
    return cast(dict[str, Any], listed_repo["items"][0]["lines"][0])


def option_line(*, ruling: object = None, **changes: object) -> dict[str, object]:
    """RUL-13's option line, E-RUL-07's card, open unless `ruling` is a letter or `other`."""
    card_hash = "sha256:b3f1720e7b5b083f5ae59eaf99559b438d1e729dc9034e3ea534cf5806f23b8a"
    return {
        "index": 1,
        "form": "options",
        "text": "The song stays open on the jump.",
        "ruling": ruling,
        "ruled_on": "2026-10-28" if ruling is not None else None,
        "via": "board" if ruling is not None else None,
        "other": None,
        "returned_on": None,
        "returned_note": None,
        "default": None,
        "card_hash": card_hash,
        "stored_card_hash": card_hash if ruling is not None else None,
        "question": "Keep the song open?",
        "problem": "The jump closes your song.",
        "picture": _SVG,
        "caption": "Today",
        "decision_kind": "product",
        "area": "Song page",
        "topic": "Jump",
        "recommended": "A",
        "reason": "Ends the loss.",
        "options": [picture_option(), same_as_today_option()],
        **changes,
    }
