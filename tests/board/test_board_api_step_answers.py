"""The operator answering a step on the board through the real server, wire form and
`aco` adapter against the real `aco` over a fake forge (specs/serve.spec.md, ABRD-163 to
ABRD-171): Erfolgreich, Fehlgeschlagen with a note and a report clear the step's wait,
step table and label in the item's turn and write the outcome into `now`."""

from collections.abc import Callable

import pytest
from aco_board_fixtures import BoardClient, RecordedPort, first_listed_line
from board_fixtures import OPERATOR_WAIT, complete_contract
from board_forge import (
    RULING_DAY,
    BoardForge,
    ForgeOperation,
    ForgeRequest,
)
from option_cards import open_option_entry

from aco import body, forge, workboard
from aco.board.aco_source import WRITTEN_OVER_NOTE

_ITEM = 7
_REPORT_STEP = {
    "purpose": "Release the build.",
    "actions": "open https://example.test/run\nclick Run",
    "expected": "The page shows green.",
    "answer": "the run report",
}
_YES_NO_STEP = {key: value for key, value in _REPORT_STEP.items() if key != "answer"}
_READ = ForgeRequest(ForgeOperation.READ_ITEM, _ITEM)
_WRITE = ForgeRequest(ForgeOperation.WRITE_BODY, _ITEM)
_UNLABEL = ForgeRequest(ForgeOperation.REMOVE_LABEL, _ITEM)
_SLICE_PLAN = "S1 Prepare the run.\nS2 Run it.\nS3 Read the result."
_STEP_CHANGED = {"status": "failed", "message": "This step changed; reload."}
_BAD_REQUEST = (400, {"error": "bad request: step"})
_ANSWERED = {"status": "answered", "message": None}
_LABEL = workboard.NEEDS_OPERATOR_LABEL
_ANSWER_KEYS = ("wait", "step", "now")


def _put_step(
    repository: BoardForge,
    table: dict[str, str] = _YES_NO_STEP,
    *,
    author_is_member: bool = True,
) -> None:
    repository.put_item(
        _ITEM,
        complete_contract(_SLICE_PLAN, wait=OPERATOR_WAIT, step=table),
        title="Release",
        labels=(_LABEL,),
        author_is_member=author_is_member,
    )


def _block(raw_body: str) -> dict[str, object]:
    return body.locate_block(raw_body).data


def _outcome(text: str) -> str:
    return (
        f'The operator answered "{OPERATOR_WAIT["operator"]}" on the board '
        f"on {RULING_DAY.isoformat()}: {text}"
    )


def _unchanged(block: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in block.items() if key not in _ANSWER_KEYS}


@pytest.mark.parametrize(
    ("table", "result", "text", "now"),
    [
        (_YES_NO_STEP, "yes", None, _outcome("Erfolgreich")),
        (_YES_NO_STEP, "no", "Stayed red.", _outcome("Fehlgeschlagen: Stayed red.")),
        (_REPORT_STEP, "no", "No report.", _outcome("Fehlgeschlagen: No report.")),
        (_REPORT_STEP, "report", "All 12 passed.", _outcome("All 12 passed.")),
    ],
    ids=["erfolgreich", "fehlgeschlagen-with-a-note", "fehlgeschlagen-on-a-report", "a-report"],
)
def test_an_answer_ends_the_wait_writes_the_outcome_and_removes_the_label_after_the_body(
    repository: BoardForge,
    board: BoardClient,
    table: dict[str, str],
    result: str,
    text: str | None,
    now: str,
) -> None:
    """ABRD-168, ABRD-169, ABRD-171, #859 line 5."""
    _put_step(repository, table)
    before = _block(repository.stored_body(_ITEM))

    answer = board.answer_step_through_api(_ITEM, result, text)

    block = _block(repository.stored_body(_ITEM))
    assert answer.json() == _ANSWERED
    assert (block["now"], block["next"]) == (now, _SLICE_PLAN)
    assert not {"wait", "step"} & block.keys()
    assert _unchanged(block) == _unchanged(before)
    assert repository.item_requests() == (_READ, _WRITE, _UNLABEL)
    assert repository.stored_item(_ITEM).labels == []
    assert repository.item_reference(_ITEM).state is forge.ItemState.OPEN


def test_an_answered_step_leaves_the_board_listing(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-168."""
    _put_step(repository)
    board.answer_step_through_api(_ITEM, "yes")

    assert board.listed_steps() == []


_BASE: dict[str, object] = {"item": _ITEM, "result": "yes"}
_ABSENT = object()


@pytest.mark.parametrize(
    "change",
    [
        {"fingerprint": _ABSENT},
        {"fingerprint": None},
        {"fingerprint": 5},
        {"repo": ""},
        {"repo": 3},
        {"item": 0},
        {"item": True},
        {"item": "7"},
        {"result": "maybe"},
        {"result": None},
        {"result": "no"},
        {"result": "no", "text": "   "},
        {"result": "no", "text": "x" * 281},
        {"result": "no", "text": "nul\0byte"},
        {"result": "no", "text": "\ud800"},
        {"result": "no", "text": 5},
        {"result": "report"},
        {"result": "yes", "text": "Erfolgreich"},
        {"result": "yes", "text": None},
        {"extra": 1},
    ],
    ids=[
        "no-fingerprint",
        "null-fingerprint",
        "fingerprint-not-text",
        "empty-repo",
        "repo-not-text",
        "item-not-positive",
        "item-a-boolean",
        "item-text",
        "unknown-result",
        "result-null",
        "failure-without-a-note",
        "failure-with-a-blank-note",
        "note-over-the-limit",
        "note-with-a-nul",
        "note-with-a-lone-surrogate",
        "note-not-text",
        "report-without-text",
        "text-beside-success",
        "null-text-beside-success",
        "unknown-key",
    ],
)
def test_a_step_post_that_breaks_the_key_rules_is_refused_before_any_forge_request(
    repository: BoardForge,
    board: BoardClient,
    port: RecordedPort,
    change: dict[str, object],
) -> None:
    """ABRD-164, ABRD-165."""
    _put_step(repository)
    shown = board.listed_step(_ITEM)
    posted = {"repo": board.repo, "fingerprint": shown["fingerprint"], **_BASE, **change}
    payload = {key: value for key, value in posted.items() if value is not _ABSENT}
    arranged = (repository.request_log(), port.calls())

    response = board.post_step(payload)

    refusal = (response.status, response.json())
    requests_since = (repository.request_log(), port.calls())
    assert refusal == _BAD_REQUEST
    assert requests_since == arranged


def test_a_step_post_naming_no_configured_repo_is_refused_before_any_forge_request(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-16."""
    _put_step(repository)
    shown = board.listed_step(_ITEM)
    arranged = repository.request_log()

    response = board.post_step({**_BASE, "repo": "nowhere", "fingerprint": shown["fingerprint"]})

    refusal = (response.status, response.json())
    assert refusal == _BAD_REQUEST
    assert repository.request_log() == arranged


def _changed_step(repository: BoardForge) -> None:
    repository.put_item(
        _ITEM,
        complete_contract(
            "Run it.", wait=OPERATOR_WAIT, step={**_YES_NO_STEP, "expected": "It is red."}
        ),
        labels=(_LABEL,),
    )


def _another_step_marked(repository: BoardForge) -> None:
    repository.put_item(
        _ITEM,
        complete_contract("Run it.", wait={**OPERATOR_WAIT, "operator": "Another."}),
        labels=(_LABEL,),
    )


def _no_wait_left(repository: BoardForge) -> None:
    repository.put_item(_ITEM, complete_contract("Run it."), labels=(_LABEL,))


def _closed(repository: BoardForge) -> None:
    repository.close_item(_ITEM)


def _written_by_a_non_member(repository: BoardForge) -> None:
    repository.put_item(
        _ITEM,
        complete_contract("Run it.", wait=OPERATOR_WAIT, step=_YES_NO_STEP),
        labels=(_LABEL,),
        author_is_member=False,
    )


def _gone(repository: BoardForge) -> None:
    repository.remove_item(_ITEM)


@pytest.mark.parametrize(
    "happens_after_the_page_read",
    [
        _changed_step,
        _another_step_marked,
        _no_wait_left,
        _closed,
        _written_by_a_non_member,
        _gone,
    ],
    ids=[
        "step-table-changed",
        "step-marked-again",
        "wait-cleared",
        "item-closed",
        "item-by-a-non-member",
        "item-gone",
    ],
)
def test_a_step_that_changed_since_the_page_read_it_is_refused_and_nothing_is_written(
    repository: BoardForge,
    board: BoardClient,
    happens_after_the_page_read: Callable[[BoardForge], None],
) -> None:
    """ABRD-166."""
    _put_step(repository)
    shown = board.listed_step(_ITEM)
    happens_after_the_page_read(repository)

    response = board.post_step({**_BASE, "repo": board.repo, "fingerprint": shown["fingerprint"]})

    assert response.json() == _STEP_CHANGED
    assert repository.body_writes() == []
    assert ForgeOperation.REMOVE_LABEL not in {r.operation for r in repository.request_log()}


def test_a_second_answer_for_the_same_step_is_refused_and_writes_nothing_more(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-166."""
    _put_step(repository)
    shown = board.listed_step(_ITEM)
    payload = {**_BASE, "repo": board.repo, "fingerprint": shown["fingerprint"]}
    first = board.post_step(payload)

    second = board.post_step(payload)

    assert (first.json(), second.json()) == (_ANSWERED, _STEP_CHANGED)
    assert repository.body_writes() == [_ITEM]


@pytest.mark.parametrize(
    ("table", "result", "text"),
    [(_REPORT_STEP, "yes", None), (_YES_NO_STEP, "report", "A report.")],
    ids=["erfolgreich-on-a-report-step", "a-report-on-a-yes-no-step"],
)
def test_an_answer_the_step_does_not_ask_for_is_refused_and_nothing_is_written(
    repository: BoardForge, board: BoardClient, table: dict[str, str], result: str, text: str | None
) -> None:
    """ABRD-167."""
    _put_step(repository, table)

    answer = board.answer_step_through_api(_ITEM, result, text)

    assert answer.json()["status"] == "failed"
    assert repository.body_writes() == []
    assert repository.stored_item(_ITEM).labels == [_LABEL]


def test_an_unrelated_ruling_between_the_page_read_and_the_post_leaves_the_answer_stored(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-166: the fingerprint covers the step alone."""
    repository.put_item(
        _ITEM,
        complete_contract(
            "Run it.",
            wait=OPERATOR_WAIT,
            step=_YES_NO_STEP,
            expectation=[open_option_entry()],
        ),
        labels=(_LABEL,),
    )
    shown = board.listed_step(_ITEM)
    card = board.decide_card_through_api(_ITEM, [first_listed_line(board)], ["A"])

    answer = board.post_step({**_BASE, "repo": board.repo, "fingerprint": shown["fingerprint"]})

    assert (card.json()["status"], answer.json()) == ("ruled", _ANSWERED)
    assert "wait" not in _block(repository.stored_body(_ITEM))


def test_a_write_kept_over_a_foreign_change_answers_with_that_note_and_removes_the_label(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-170."""
    _put_step(repository)
    repository.answer_next_write(
        forge.ForgeBodyOverwrittenError(_ITEM, "2026-10-03T08:00:00Z", "ada", kept=True)
    )

    answer = board.answer_step_through_api(_ITEM, "yes")

    assert answer.json() == {**_ANSWERED, "note": WRITTEN_OVER_NOTE}
    assert repository.stored_item(_ITEM).labels == []


@pytest.mark.parametrize(
    "unsure",
    [
        forge.ForgeBodyOverwrittenError(_ITEM, "2026-10-03T08:00:00Z", "ada", kept=False),
        forge.ForgeBodyNotVerifiedError(_ITEM, "the history was unreadable"),
    ],
    ids=["lost", "not-verified"],
)
def test_a_lost_or_unverified_write_answers_failed_and_never_touches_the_label(
    repository: BoardForge,
    board: BoardClient,
    unsure: forge.ForgeBodyOverwrittenError | forge.ForgeBodyNotVerifiedError,
) -> None:
    """ABRD-170."""
    _put_step(repository)
    repository.answer_next_write(unsure)

    answer = board.answer_step_through_api(_ITEM, "yes")

    assert (answer.json()["status"], answer.json()["message"]) == ("failed", str(unsure))
    assert ForgeOperation.REMOVE_LABEL not in {r.operation for r in repository.request_log()}
    assert repository.stored_item(_ITEM).labels == [_LABEL]


def test_a_label_that_cannot_be_removed_keeps_the_answer_and_names_the_repair(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-169."""
    _put_step(repository)
    repository.fail_label_removals("the forge said no")

    answer = board.answer_step_through_api(_ITEM, "yes")

    assert answer.json() == {
        **_ANSWERED,
        "note": (
            f"The label {_LABEL} was not removed: the forge said no; "
            f"remove it with gh issue edit {_ITEM} --remove-label {_LABEL}"
        ),
    }
    assert "wait" not in _block(repository.stored_body(_ITEM))


def test_a_forge_that_cannot_read_the_item_during_a_step_post_answers_failed_and_writes_nothing(
    repository: BoardForge, board: BoardClient
) -> None:
    """ABRD-166."""
    _put_step(repository)
    shown = board.listed_step(_ITEM)
    repository.fail_item_reads("no forge adapter for host")

    response = board.post_step({**_BASE, "repo": board.repo, "fingerprint": shown["fingerprint"]})

    assert response.json() == {"status": "failed", "message": "no forge adapter for host"}
    assert repository.body_writes() == []
