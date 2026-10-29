"""`aco_cli`'s own process boundary: what the board makes of `aco`'s output,
failures and argv (specs/serve.spec.md: ABRD-07, ABRD-60, ABRD-78).

Every test here answers `aco` from a canned answer the launcher replays, or
breaks the process itself; no other board test sets a canned answer or reads
the launcher's argv log. The JSON rows below are `aco rulings --json` rows
written by hand, for shapes a real body cannot hold.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from aco_board_fixtures import (
    DEFAULT_LABEL,
    BoardClient,
    Response,
    assert_guarded,
    serving,
    serving_two,
)
from board_forge import BoardForge, CannedAnswer, logged_calls, set_canned_answer

from aco.board.aco_cli import AcoCli
from aco.board.ports import (
    CardDecision,
    CardLine,
    DecisionResult,
    DecisionSourceUnavailableError,
    DecisionStatus,
)

_SVG = '<svg xmlns="http://www.w3.org/2000/svg"/>'
_ITEM = 7
_ANSWER = "Nur auf dem Desktop offen lassen."


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


def line(index: int, text: str, *, ruling: str | None = None, **card: str) -> dict[str, object]:
    ruled_on = "2026-10-01" if ruling is not None else None
    return {"index": index, "text": text, "ruling": ruling, "ruled_on": ruled_on, **card}


def row(number: int, title: str, *lines: dict[str, object]) -> dict[str, object]:
    open_count = sum(1 for entry in lines if entry["ruling"] is None)
    return {
        "number": number,
        "title": title,
        "open": open_count,
        "total": len(lines),
        "lines": list(lines),
    }


def _answer_rulings(directory: Path, *rows: dict[str, object]) -> None:
    listed = {"ok": True, "reason": "listed", "rulings": list(rows)}
    set_canned_answer(directory, "rulings", CannedAnswer(stdout=json.dumps(listed)))


def _rule_calls(directory: Path) -> list[list[str]]:
    return [call for call in logged_calls(directory) if call[0] == "rule"]


def _repos(response: Response) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], response.json()["repos"])


# --- aco answering a listing the board cannot read (ABRD-07) ---


@pytest.mark.parametrize(
    ("stdout", "error"),
    [
        ("not json", "aco rulings failed: exit 0 without a message"),
        ('{"ok": true, "rulings": {}}', "aco rulings --json is unreadable: rulings is not a list"),
        (
            '{"ok": true, "rulings": [1]}',
            "aco rulings --json is unreadable: a rulings row is not an object",
        ),
        (
            '{"ok": true, "rulings": [{"number": true, "title": "T", "lines": []}]}',
            "aco rulings --json is unreadable: number is not a int",
        ),
        (
            '{"ok": true, "rulings": [{"number": 1, "title": "T"}]}',
            "aco rulings --json is unreadable: #1 lines is not a list",
        ),
        (
            '{"ok": true, "rulings": [{"number": 1, "title": "T", "lines": [2]}]}',
            "aco rulings --json is unreadable: #1 has a line that is not an object",
        ),
        (
            '{"ok": true, "rulings": [{"number": 1, "title": "T", "lines": '
            '[{"index": 1, "text": "Q?", "ruling": "yes", "ruled_on": "2026-10-01", '
            '"question": 3}]}]}',
            "aco rulings --json is unreadable: question is not text",
        ),
        (
            '{"ok": true, "rulings": [{"number": 1, "title": "T", "lines": '
            '[{"index": 1, "text": "Q?", "ruled_on": null}]}]}',
            "aco rulings --json is unreadable: #1 line has no ruling",
        ),
        (
            '{"ok": true, "rulings": [{"number": 1, "title": "T", "lines": '
            '[{"index": 1, "text": "Q?", "ruling": "yes"}]}]}',
            "aco rulings --json is unreadable: #1 line has no ruled_on",
        ),
        (
            '{"ok": true, "rulings": [{"number": 1, "title": "T", "lines": '
            '[{"index": 1, "text": "Q?", "ruling": "perhaps", "ruled_on": "2026-10-01"}]}]}',
            "aco rulings --json is unreadable: ruling is not an outcome",
        ),
        (
            '{"ok": true, "rulings": [{"number": 1, "title": "T", "lines": '
            '[{"index": 1, "text": "Q?", "ruling": "yes", "ruled_on": "gestern"}]}]}',
            "aco rulings --json is unreadable: ruled_on is not a date",
        ),
        (
            '{"ok": true, "rulings": [{"number": 7, "title": "T", "lines": '
            '[{"index": 2, "text": "Q?", "default": null, "ruling": null, "ruled_on": null}]}]}',
            "aco rulings --json is unreadable: #7 line 2 is an open yes/no line; "
            "write an option card",
        ),
    ],
    ids=[
        "not-json",
        "rulings-not-a-list",
        "row-not-an-object",
        "number-not-an-int",
        "lines-not-a-list",
        "line-not-an-object",
        "question-not-text",
        "ruling-missing",
        "ruled-on-missing",
        "ruling-not-an-outcome",
        "ruled-on-not-a-date",
        "open-yes-no-line",
    ],
)
def test_unreadable_rulings_json_answers_502_with_why(
    repository: BoardForge, board: BoardClient, stdout: str, error: str
) -> None:
    set_canned_answer(repository.directory, "rulings", CannedAnswer(stdout=stdout))

    response = board.get_board_json()

    assert response.status == 502
    assert response.json() == {"repos": [{"name": DEFAULT_LABEL, "error": error, "items": []}]}
    assert response.headers["Content-Type"] == "application/json"
    assert_guarded(response)


_OPTION_LINE_KEYS = [
    "index",
    "form",
    "text",
    "question",
    "problem",
    "picture",
    "caption",
    "decision_kind",
    "area",
    "topic",
    "recommended",
    "reason",
    "options",
    "ruling",
    "ruled_on",
    "via",
    "other",
    "returned_on",
    "returned_note",
    "fingerprint",
]


def _without_key(stored: dict[str, object], key: str) -> dict[str, object]:
    return {name: value for name, value in stored.items() if name != key}


def test_an_unknown_key_and_a_default_on_an_option_line_do_not_matter(
    repository: BoardForge, board: BoardClient
) -> None:
    _answer_rulings(
        repository.directory, row(12, "Song jump", option_line(default="yes", provenance="x"))
    )

    [repo] = _repos(board.get_board_json())

    assert list(repo["items"][0]["lines"][0]) == _OPTION_LINE_KEYS


def _fingerprint_of(board: BoardClient, repository: BoardForge, stored: dict[str, object]) -> str:
    _answer_rulings(repository.directory, row(12, "Song jump", stored))
    [repo] = _repos(board.get_board_json())
    return cast(str, repo["items"][0]["lines"][0]["fingerprint"])


@pytest.mark.parametrize(
    "changes",
    [
        {"stored_card_hash": "sha256:other"},
        {"default": "yes"},
        {"provenance": "x"},
        {"text": "Another wording."},
    ],
    ids=["stored-card-hash", "default", "unknown-key", "text-not-in-the-hash"],
)
def test_an_option_lines_fingerprint_ignores_what_its_card_hash_does_not_cover(
    repository: BoardForge, board: BoardClient, changes: dict[str, object]
) -> None:
    """ABRD-35."""
    before = _fingerprint_of(board, repository, option_line())

    after = _fingerprint_of(board, repository, option_line(**changes))

    assert after == before


@pytest.mark.parametrize(
    "malformed",
    [
        option_line(ruling="C"),
        option_line(ruling="yes"),
        option_line(ruling=7),
        option_line(recommended="C"),
        option_line(recommended="E"),
        option_line(recommended=None),
        option_line(options=[picture_option("B"), same_as_today_option("A")]),
        option_line(options=[picture_option("A"), same_as_today_option("C")]),
        option_line(options=[]),
        option_line(options=[picture_option(letter) for letter in "ABCDE"]),
        option_line(options="none"),
        option_line(options=["A"]),
        option_line(options=[picture_option(), same_as_today_option(cost=5)]),
        option_line(options=[picture_option(), same_as_today_option(same_as_today=False)]),
        option_line(problem=5),
        option_line(picture=5),
        option_line(options=[picture_option(picture=5), same_as_today_option()]),
        option_line(ruling="A", ruled_on="tomorrow"),
        option_line(form="cards"),
        option_line(form=None),
        _without_key(option_line(), "via"),
        option_line(ruling="A", via="phone"),
        option_line(ruling="A", via="Board"),
        option_line(ruling="A", via=5),
        option_line(ruling="other", via="chat"),
        option_line(ruling="other", via="chat", other="  "),
        option_line(ruling="other", via="chat", other=5),
        option_line(ruling="A", other="x"),
        option_line(other="x"),
    ],
    ids=[
        "ruling-not-a-letter-of-the-options",
        "yes-no-ruling",
        "ruling-not-text",
        "recommended-not-a-letter-of-the-options",
        "recommended-no-letter",
        "recommended-null",
        "letters-swapped",
        "letter-out-of-position",
        "no-options",
        "more-options-than-letters",
        "options-not-a-list",
        "option-not-an-object",
        "option-field-wrong-type",
        "option-neither-picture-nor-same-as-today",
        "line-field-wrong-type",
        "picture-wrong-type",
        "option-picture-wrong-type",
        "ruled-on-not-a-date",
        "unknown-form",
        "form-null",
        "via-missing",
        "via-unknown-value",
        "via-wrong-case",
        "via-not-text",
        "other-missing-on-a-line-ruled-other",
        "other-blank",
        "other-not-text",
        "other-beside-a-letter",
        "other-on-an-open-line",
    ],
)
def test_a_malformed_option_line_makes_only_its_repository_unreadable(
    two_repositories: tuple[BoardForge, BoardForge], malformed: dict[str, object]
) -> None:
    """ABRD-07, ABRD-53."""
    error_in_a = _error_in_a_beside_a_usable_b(two_repositories, malformed)

    assert error_in_a.startswith("aco rulings --json is unreadable: ")


def test_an_open_yes_no_line_makes_only_its_repository_unreadable_with_its_sentence(
    two_repositories: tuple[BoardForge, BoardForge],
) -> None:
    """ABRD-07, ABRD-15: no writer is left for it, and it is never skipped silently."""
    error_in_a = _error_in_a_beside_a_usable_b(two_repositories, line(3, "Guests?"))

    assert error_in_a == (
        "aco rulings --json is unreadable: #12 line 3 is an open yes/no line; write an option card"
    )


def _error_in_a_beside_a_usable_b(
    two_repositories: tuple[BoardForge, BoardForge], line_in_a: dict[str, object]
) -> str:
    """Repo `a`'s error with item 12 holding `line_in_a`, once `b` listed beside it."""
    repository_a, repository_b = two_repositories
    _answer_rulings(repository_a.directory, row(12, "Song jump", line_in_a))
    _answer_rulings(
        repository_b.directory, row(42, "Share page", option_line(index=1, text="Guests?"))
    )

    with serving_two(two_repositories) as board:
        response = board.get_board_json()

    repos = _repos(response)
    assert response.status == 200
    assert repos[0]["items"] == []
    assert repos[1]["error"] is None
    assert [item["number"] for item in repos[1]["items"]] == [42]
    return cast(str, repos[0]["error"])


@pytest.mark.parametrize(
    "stored",
    [
        option_line(returned_note="Which jump?"),
        option_line(returned_on="2026-10-27", returned_note=""),
        option_line(returned_on="2026-10-27", returned_note="  "),
        option_line(returned_on="2026-10-27", returned_note=5),
        option_line(returned_on="27.10.2026"),
        option_line(returned_on=20261027),
        option_line(ruling="A", returned_on="2026-10-27"),
        option_line(ruling="A", returned_note="Which jump?"),
        _without_key(option_line(), "returned_on"),
        _without_key(option_line(), "returned_note"),
    ],
    ids=[
        "note-without-date",
        "note-empty",
        "note-blank",
        "note-not-text",
        "date-not-iso",
        "date-not-text",
        "ruled-and-returned",
        "ruled-with-a-note",
        "date-key-missing",
        "note-key-missing",
    ],
)
def test_a_returned_pair_aco_refuses_makes_the_repository_unreadable(
    repository: BoardForge, board: BoardClient, stored: dict[str, object]
) -> None:
    """ABRD-07, ABRD-62."""
    _answer_rulings(repository.directory, row(12, "Song jump", stored))

    [repo] = _repos(board.get_board_json())

    assert repo["error"].startswith("aco rulings --json is unreadable: ")
    assert repo["items"] == []


# --- a withdrawn line (ABRD-60): aco writes no withdrawn form yet ---


def _withdrawn(index: int, **keys: object) -> dict[str, object]:
    return {"index": index, "form": "withdrawn", "ruling": None, **keys}


def _board_repo(board: BoardClient) -> dict[str, Any]:
    response = board.get_board_json()
    assert response.status == 200
    [repo] = _repos(response)
    return repo


def test_a_withdrawn_line_is_skipped_and_its_neighbours_keep_their_indexes(
    repository: BoardForge, board: BoardClient
) -> None:
    _answer_rulings(
        repository.directory,
        row(
            12,
            "Song jump",
            option_line(index=1, text="Guests?"),
            _withdrawn(2, text=7, unknown={"nested": True}),
            line(3, "Share page?", ruling="yes"),
        ),
    )

    repo = _board_repo(board)

    assert repo["error"] is None
    [item] = repo["items"]
    assert [(entry["index"], entry["text"]) for entry in item["lines"]] == [
        (1, "Guests?"),
        (3, "Share page?"),
    ]


def test_an_item_with_only_withdrawn_lines_is_absent(
    repository: BoardForge, board: BoardClient
) -> None:
    _answer_rulings(
        repository.directory,
        row(12, "Song jump", _withdrawn(1)),
        row(42, "Share page", option_line(index=1, text="Guests?")),
    )

    repo = _board_repo(board)

    assert repo["error"] is None
    assert [item["number"] for item in repo["items"]] == [42]


@pytest.mark.parametrize("form", ["Withdrawn", "cards", None], ids=["case", "other", "null"])
def test_any_other_unknown_form_still_makes_the_repository_unreadable(
    repository: BoardForge, board: BoardClient, form: object
) -> None:
    """ABRD-07."""
    _answer_rulings(repository.directory, row(12, "Song jump", _withdrawn(1, form=form)))

    response = board.get_board_json()

    [repo] = _repos(response)
    assert response.status == 502
    assert repo["error"] == "aco rulings --json is unreadable: #12 line has an unknown form"
    assert repo["items"] == []


# --- an aco that fails, hangs, is missing or cannot be run ---


def test_aco_failing_with_only_stderr_is_relayed_with_that_sentence(
    repository: BoardForge, board: BoardClient
) -> None:
    """E-ABRD-06's shape: no `--json` envelope, so stderr is the reason."""
    failure = CannedAnswer(stderr="ERROR: no forge adapter for host\n", exit_status=2)
    set_canned_answer(repository.directory, "rulings", failure)

    response = board.get_board_json()

    assert response.status == 502
    assert response.json() == {
        "repos": [
            {
                "name": DEFAULT_LABEL,
                "error": "aco rulings failed: ERROR: no forge adapter for host",
                "items": [],
            }
        ]
    }
    assert response.headers["Content-Type"] == "application/json"
    assert_guarded(response)


def test_a_hung_aco_rulings_answers_502_with_its_timeout(repository: BoardForge) -> None:
    set_canned_answer(repository.directory, "rulings", CannedAnswer(wait_seconds=30))

    with serving(AcoCli(directory=repository.directory, timeout_seconds=1.0)) as board:
        response = board.get_board_json()

    assert response.status == 502
    assert response.json() == {
        "repos": [
            {
                "name": DEFAULT_LABEL,
                "error": "aco rulings did not answer within 1 seconds",
                "items": [],
            }
        ]
    }
    assert response.headers["Content-Type"] == "application/json"
    assert_guarded(response)


def test_a_hung_aco_rule_keeps_the_line_undecided(repository: BoardForge) -> None:
    _answer_rulings(repository.directory, row(42, "Share page", option_line()))
    set_canned_answer(repository.directory, "rule", CannedAnswer(wait_seconds=30))

    with serving(AcoCli(directory=repository.directory, timeout_seconds=5)) as board:
        [repo] = _repos(board.get_board_json())
        answer = board.decide_card_through_api(42, repo["items"][0]["lines"], ["A"])
        [repo_after] = _repos(board.get_board_json())

    assert answer.json() == {
        "status": "failed",
        "message": "aco rule did not answer within 5 seconds",
    }
    assert [item["number"] for item in repo_after["items"]] == [42]


def test_aco_missing_from_path_during_a_card_post_keeps_the_line_undecided(
    repository: BoardForge, board: BoardClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answer_rulings(repository.directory, row(42, "Share page", option_line()))
    [repo] = _repos(board.get_board_json())
    monkeypatch.setenv("PATH", str(tmp_path / "no-aco-here"))

    answer = board.decide_card_through_api(42, repo["items"][0]["lines"], ["A"])

    assert answer.json() == {"status": "failed", "message": "aco is not installed on PATH"}
    assert _rule_calls(repository.directory) == []


def _aco_without_execute_permission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_directory = tmp_path / "bin-without-execute"
    bin_directory.mkdir()
    (bin_directory / "aco").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(bin_directory))
    return tmp_path


def _working_directory_that_is_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    del monkeypatch
    file_instead_of_directory = tmp_path / "repository"
    file_instead_of_directory.write_text("", encoding="utf-8")
    return file_instead_of_directory


def _working_directory_that_cannot_be_entered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    del monkeypatch
    unenterable = tmp_path / "repository"
    unenterable.mkdir(mode=0o000)
    return unenterable


def _aco_answering_bytes_that_are_not_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_directory = tmp_path / "bin-not-utf8"
    bin_directory.mkdir()
    executable = bin_directory / "aco"
    executable.write_text("#!/bin/sh\nprintf '\\377\\376'\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_directory}{os.pathsep}{os.environ['PATH']}")
    return tmp_path


_ACO_CANNOT_BE_RUN = pytest.mark.parametrize(
    ("arrange", "reason"),
    [
        (_aco_without_execute_permission, "could not be run: Permission denied"),
        (_working_directory_that_is_a_file, "could not be run: Not a directory"),
        (_working_directory_that_cannot_be_entered, "could not be run: Permission denied"),
        (_aco_answering_bytes_that_are_not_utf8, "answered output that is not UTF-8"),
    ],
    ids=[
        "no-execute-permission",
        "working-directory-is-a-file",
        "working-directory-not-enterable",
        "output-not-utf8",
    ],
)


@pytest.fixture
def restore_permissions(tmp_path: Path) -> Iterator[None]:
    """Lets pytest remove a directory a test made unenterable."""
    yield
    for directory in tmp_path.iterdir():
        if directory.is_dir():
            directory.chmod(0o755)


@_ACO_CANNOT_BE_RUN
@pytest.mark.usefixtures("restore_permissions")
def test_an_aco_that_cannot_be_run_makes_the_rulings_read_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arrange: Callable[[Path, pytest.MonkeyPatch], Path],
    reason: str,
) -> None:
    decisions = AcoCli(directory=arrange(tmp_path, monkeypatch))

    with pytest.raises(DecisionSourceUnavailableError) as unavailable:
        decisions.expectation_lines()

    assert str(unavailable.value) == f"aco rulings {reason}"


@_ACO_CANNOT_BE_RUN
@pytest.mark.usefixtures("restore_permissions")
def test_an_aco_that_cannot_be_run_fails_the_card_with_one_sentence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arrange: Callable[[Path, pytest.MonkeyPatch], Path],
    reason: str,
) -> None:
    decisions = AcoCli(directory=arrange(tmp_path, monkeypatch))
    card_hash = cast(str, option_line()["card_hash"])
    decision = CardDecision(42, (CardLine(1, card_hash, "A"),), None)

    result = decisions.rule_card(decision)

    assert result == DecisionResult(DecisionStatus.FAILED, f"aco rule {reason}")


# --- ABRD-78: the argv `AcoCli.rule_card` gives `aco rule` per answer kind ---


def _hash(index: int) -> str:
    return f"sha256:{index:064x}"


def _expected_line(index: int, letter: str) -> list[str]:
    picked = ["--option", letter] if letter else []
    return ["--line", str(index), *picked, f"--card-hash={_hash(index)}"]


def _expected_call(
    indexes: Sequence[int], options: Sequence[str], tail: Sequence[str]
) -> list[str]:
    lines = [_expected_line(index, letter) for index, letter in zip(indexes, options, strict=True)]
    return ["rule", str(_ITEM), *(part for entry in lines for part in entry), *tail, "--json"]


@pytest.mark.parametrize(
    ("indexes", "options", "answer", "tail", "status"),
    [
        ((2, 3), ("A", "B"), {}, ("--via", "board"), "ruled"),
        ((2, 3, 4, 5), ("B", "A", "B", "A"), {}, ("--via", "board"), "ruled"),
        ((2, 3, 4, 5), ("A",) * 4, {}, ("--via", "board"), "ruled"),
        ((2,), ("B",), {}, ("--via", "board"), "ruled"),
        (
            (2, 3),
            ("", ""),
            {"other": f"  {_ANSWER}\n"},
            (f"--other={_ANSWER}", "--via", "board"),
            "ruled",
        ),
        (
            (2, 3),
            ("", ""),
            {"other": " -n starts like an option "},
            ("--other=-n starts like an option", "--via", "board"),
            "ruled",
        ),
        ((2, 3), ("", ""), {"other": 'a\n"b" ä'}, ('--other=a\n"b" ä', "--via", "board"), "ruled"),
        (
            (2, 3),
            ("", ""),
            {"other": f" {'x' * 280} "},
            (f"--other={'x' * 280}", "--via", "board"),
            "ruled",
        ),
        ((2, 3), ("", ""), {"unclear": True}, ("--unclear",), "returned"),
        (
            (2, 3),
            ("", ""),
            {"unclear": True, "note": " Was kostet B? "},
            ("--unclear", "--note=Was kostet B?"),
            "returned",
        ),
        ((2, 3), ("", ""), {"unclear": True, "note": "  \n"}, ("--unclear",), "returned"),
        (
            (2, 3),
            ("", ""),
            {"unclear": True, "note": "a\nb"},
            ("--unclear", "--note=a\nb"),
            "returned",
        ),
    ],
    ids=[
        "picks",
        "four-picks",
        "accept-all",
        "one-line-card",
        "other",
        "other-like-an-option-flag",
        "other-with-a-newline-and-quote",
        "other-at-the-bound",
        "unclear",
        "unclear-note",
        "unclear-blank-note",
        "unclear-note-with-a-newline",
    ],
)
def test_a_card_post_runs_one_aco_rule_naming_every_line(
    repository: BoardForge,
    board: BoardClient,
    indexes: tuple[int, ...],
    options: tuple[str, ...],
    answer: dict[str, object],
    tail: tuple[str, ...],
    status: str,
) -> None:
    """ABRD-78."""
    lines = [option_line(index=index, card_hash=_hash(index)) for index in indexes]
    _answer_rulings(repository.directory, row(_ITEM, "Karte", line(1, "Alt", ruling="yes"), *lines))
    stored = {"ok": True, "reason": status}
    set_canned_answer(repository.directory, "rule", CannedAnswer(stdout=json.dumps(stored)))
    [repo] = _repos(board.get_board_json())
    shown = {entry["index"]: entry for entry in repo["items"][0]["lines"]}

    answered = board.decide_card_through_api(
        _ITEM, [shown[index] for index in indexes], None if answer else options, answer
    )

    assert answered.json() == {"status": status, "message": None}
    assert _rule_calls(repository.directory) == [_expected_call(indexes, options, tail)]
