"""The size class a released lane records from its work item (LANREC-28)."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from board_fixtures import REPOSITORY, block_body, standing_active_claim, write_repository_config
from cli_fixtures import FROZEN_CLI_NOW, fresh_observation, real_git, run_cli
from github_fixtures import WORK_ITEM_ISSUE
from merged_release import arrange_merged_pull_request
from store_fixtures import item_record

from aco import body, forge, items, protocol, store, workboard
from aco.lane_record import release_subject
from aco.session import RunContext

LANE_BRANCH = "docs/tidy-readme"


def item_text(size: body.Size | None, *, record: dict[str, object] | None = None) -> str:
    """The text of a work item that declares `size`, or none; `record` makes it a state-ref one."""
    data: dict[str, object] = {
        "version": 1,
        "now": "Ship it.",
        "next": "none",
        "done_when": "Merged.",
    }
    if size is not None:
        data["size"] = size.value
    if record is not None:
        data["record"] = record
    return block_body(body.render_block(data).removesuffix("\n"), before="Prose.\n\n", after="")


def seed_sized_item(clone: Path, remote: Path, size: body.Size | None) -> None:
    """The work item as an open record on the real state ref, declaring `size` or none."""
    content = item_text(size, record=item_record(title="Item", state="open", kind="task"))
    item_id = items.format_item_id(WORK_ITEM_ISSUE)
    store.commit_transition(
        observed=fresh_observation(clone, remote),
        subject=store.TransitionSubject(f"seed item {item_id}"),
        intent=protocol.ItemWriteIntent(
            item_id=item_id,
            expected=None,
            new_oid=store.hash_blob(clone, content.encode()),
            operation_id="seed-item",
        ),
    )


def recorded_size_lines(remote: Path) -> list[str]:
    message = real_git(remote, "log", "-1", "--format=%B", store.STATE_REF).stdout
    return [line for line in message.splitlines() if line.startswith("lane_size")]


def served_item(size: body.Size | None) -> forge.ItemReference:
    return forge.ItemReference(forge.ItemState.OPEN, "Item", item_text(size))


def release_trailers(
    tmp_path: Path, outcome: protocol.ReleaseOutcome, item: forge.ItemReference | None
) -> tuple[str, ...]:
    """The trailers `release_subject` puts on a lane's release that read `item`; the merge is
    unknown, so no repository history is read."""
    context = SimpleNamespace(
        toplevel=tmp_path,
        config=workboard.BoardConfig(),
        observation=SimpleNamespace(tip=None),
        now=lambda: FROZEN_CLI_NOW,
    )
    claim = standing_active_claim(lane=True)

    return release_subject(cast(RunContext, context), claim, outcome, None, item).trailers


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        pytest.param(body.Size.SMALL, ("lane_outcome: landed", "lane_size: S"), id="small"),
        pytest.param(body.Size.MEDIUM, ("lane_outcome: landed", "lane_size: M"), id="medium"),
        pytest.param(body.Size.LARGE, ("lane_outcome: landed", "lane_size: L"), id="large"),
        pytest.param(None, ("lane_outcome: landed",), id="unsized"),
    ],
)
def test_a_landed_release_records_the_size_its_item_declares(
    tmp_path: Path, size: body.Size | None, expected: tuple[str, ...]
) -> None:
    """Spec: LANREC-28."""
    trailers = release_trailers(tmp_path, protocol.MergedRelease(12), served_item(size))

    assert trailers == expected


@pytest.mark.parametrize(
    ("outcome", "item", "expected"),
    [
        pytest.param(
            protocol.AbandonedRelease("stopped"),
            served_item(body.Size.MEDIUM),
            "lane_outcome: abandoned",
            id="abandoned",
        ),
        pytest.param(protocol.MergedRelease(12), None, "lane_outcome: landed", id="no-item"),
        pytest.param(
            protocol.MergedRelease(12),
            forge.ItemReference(forge.ItemState.OPEN, "Item", None),
            "lane_outcome: landed",
            id="an-item-with-no-body",
        ),
        pytest.param(
            protocol.MergedRelease(12),
            forge.ItemReference(forge.ItemState.OPEN, "Item", "No block here."),
            "lane_outcome: landed",
            id="an-item-without-a-block",
        ),
    ],
)
def test_an_abandoned_release_or_one_without_a_declared_size_has_no_size_line(
    tmp_path: Path,
    outcome: protocol.ReleaseOutcome,
    item: forge.ItemReference | None,
    expected: str,
) -> None:
    """Spec: LANREC-28."""
    trailers = release_trailers(tmp_path, outcome, item)

    assert trailers == (expected,)


@pytest.mark.parametrize(
    ("item_state", "size", "expected"),
    [
        pytest.param(forge.ItemState.OPEN, body.Size.MEDIUM, ["lane_size: M"], id="open-sized"),
        pytest.param(
            forge.ItemState.CLOSED, body.Size.SMALL, ["lane_size: S"], id="closed-by-the-merge"
        ),
    ],
)
def test_a_github_release_of_an_item_records_its_size_from_the_one_read_it_makes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
    item_state: forge.ItemState,
    size: body.Size,
    expected: list[str],
) -> None:
    """Spec: LANREC-21, LANREC-28."""
    merged = arrange_merged_pull_request(
        monkeypatch,
        github_clone,
        bare_remote,
        identity=protocol.IssueIdentity(WORK_ITEM_ISSUE),
        trailers=(f"Work-Item: #{WORK_ITEM_ISSUE}",),
        pull_request_body=f"Closes #{WORK_ITEM_ISSUE}",
        branch=LANE_BRANCH,
    )
    merged.forge.issue_references[WORK_ITEM_ISSUE] = forge.ItemReference(
        item_state, "Item", item_text(size)
    )
    real_git(github_clone, "checkout", "-q", LANE_BRANCH)

    result = run_cli(
        ["--repo", REPOSITORY, "release", str(WORK_ITEM_ISSUE), "--merged", "12"], capsys
    )

    assert (result.status, result.stderr) == (0, "")
    assert recorded_size_lines(bare_remote) == expected
    assert merged.forge.issue_reference_lookups == [WORK_ITEM_ISSUE]


def test_a_state_ref_release_of_an_item_records_the_size_its_record_declares(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: LANREC-28."""
    merged = arrange_merged_pull_request(
        monkeypatch,
        github_clone,
        bare_remote,
        identity=protocol.IssueIdentity(WORK_ITEM_ISSUE),
        trailers=(f"Work-Item: #{WORK_ITEM_ISSUE}",),
        pull_request_body="",
        branch=LANE_BRANCH,
    )
    seed_sized_item(github_clone, bare_remote, body.Size.LARGE)
    real_git(github_clone, "pull", "-q", "--ff-only", "origin", "main")
    write_repository_config(github_clone, 'storage = "state-ref"\n')
    real_git(github_clone, "checkout", "-q", LANE_BRANCH)

    result = run_cli(
        ["release", str(WORK_ITEM_ISSUE), "--agent", "Ada", "--merged", merged.merge_commit],
        capsys,
    )

    assert (result.status, result.stderr) == (0, "")
    assert recorded_size_lines(bare_remote) == ["lane_size: L"]
