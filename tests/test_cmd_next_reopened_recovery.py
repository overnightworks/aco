"""`aco next` and `aco board` leave an item out of RECOVERY once it was reopened after
the last merge that declared it (LAND-81). The forge is the only fake."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from board_fixtures import board_issue, complete_contract
from cli_fixtures import freeze_cli_now, run_cli
from github_fixtures import FakeForge, serve_forge

from aco import workboard

ITEM = 90
MERGED_AT = datetime(2026, 8, 20, tzinfo=UTC)
ONE_HOUR = timedelta(hours=1)


@pytest.fixture(autouse=True)
def _freeze_clock(monkeypatch: pytest.MonkeyPatch, github_world: Path) -> None:
    freeze_cli_now(monkeypatch)


def declaring_merge(number: int, merged_at: datetime) -> workboard.PullRequest:
    return workboard.PullRequest(
        number,
        "Lands it",
        f"Work-Item: #{ITEM}\n\nCloses #{ITEM}",
        "branch",
        merged_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def serve_item(
    monkeypatch: pytest.MonkeyPatch,
    *,
    merges: tuple[workboard.PullRequest, ...],
    reopened: dict[int, datetime] | None = None,
) -> FakeForge:
    issue = board_issue(ITEM, "Landed but open", complete_contract("Close it."))
    return serve_forge(
        monkeypatch,
        FakeForge(
            board_issues=(issue,),
            board_merged_pull_requests=merges,
            board_reopened=reopened or {},
        ),
    )


def board_item(capsys: pytest.CaptureFixture[str]) -> tuple[object, ...]:
    """The item's stage, score and position in the ranked list."""
    items = json.loads(run_cli(["board", "--json"], capsys).stdout)["items"]
    position, row = next((at, row) for at, row in enumerate(items) if row["number"] == ITEM)
    return (row["stage"], row["score"], position)


def board_requests(capsys: pytest.CaptureFixture[str]) -> int:
    """The forge's running request count after one more board read."""
    return json.loads(run_cli(["board", "--json"], capsys).stdout)["requests"]


@pytest.mark.parametrize(
    ("reopened", "later_merges", "in_recovery"),
    [
        pytest.param(MERGED_AT + ONE_HOUR, (), False, id="reopened-after-the-merge"),
        pytest.param(MERGED_AT - ONE_HOUR, (), True, id="reopened-before-the-merge"),
        pytest.param(MERGED_AT, (), True, id="reopened-at-the-merge"),
        pytest.param(None, (), True, id="never-reopened"),
        pytest.param(
            MERGED_AT + ONE_HOUR, (MERGED_AT + 2 * ONE_HOUR,), True, id="declared-again-after"
        ),
    ],
)
def test_next_names_recovery_unless_reopened_after_the_last_declaring_merge(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reopened: datetime | None,
    later_merges: tuple[datetime, ...],
    in_recovery: bool,
) -> None:
    """Spec: LAND-81."""
    merges = tuple(
        declaring_merge(140 + offset, merged_at)
        for offset, merged_at in enumerate((MERGED_AT, *later_merges))
    )
    serve_item(monkeypatch, merges=merges, reopened={} if reopened is None else {ITEM: reopened})

    result = run_cli(["next"], capsys)

    assert ("RECOVERY" in result.stdout) is in_recovery


def test_a_reopen_after_the_merge_leaves_stage_and_rank_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LAND-81."""
    served = serve_item(
        monkeypatch,
        merges=(declaring_merge(140, MERGED_AT),),
        reopened={ITEM: MERGED_AT + ONE_HOUR},
    )
    reopened = board_item(capsys)
    served.board_reopened = {}

    never_reopened = board_item(capsys)

    assert reopened == never_reopened
    assert reopened[0] == "code-landed"


def test_the_reopen_read_costs_one_request_and_only_for_a_declared_open_item(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LAND-81 -- BOARD-11's `requests` counts the read."""
    served = serve_item(monkeypatch, merges=())
    without_candidate = board_requests(capsys)
    served.board_merged_pull_requests = (declaring_merge(140, MERGED_AT),)

    with_candidate = board_requests(capsys) - without_candidate

    assert with_candidate - without_candidate == 1
