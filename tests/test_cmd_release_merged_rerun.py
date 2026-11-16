"""`aco release --merged <commit>` rerun from the default branch under
`storage = "state-ref"`, on real temporary git worktrees and the real state
ref. The forge is the only fake."""

import json
from pathlib import Path

import pytest
from board_fixtures import block_body, write_repository_config
from cli_fixtures import fresh_observation, real_git, run_cli
from github_fixtures import LANDING_BRANCH, WORK_ITEM_ISSUE
from merged_release import arrange_merged_pull_request
from store_fixtures import item_record, state_ref_tip

from aco import body, items, protocol, store


def seed_open_item(clone: Path, remote: Path) -> None:
    """The work item as an open record on the real state ref."""
    data = {
        "version": 1,
        "now": "Ship it.",
        "next": "none",
        "done_when": "Merged.",
        "record": item_record(title="Item", state="open", kind="task"),
    }
    content = block_body(body.render_block(data).removesuffix("\n"), before="Prose.\n\n", after="")
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


@pytest.mark.parametrize(
    "branch_flags", [(), ("--branch", "main")], ids=["no-branch", "trunk-branch"]
)
@pytest.mark.parametrize("output_flags", [(), ("--json",)], ids=["text", "json"])
def test_a_merged_rerun_from_the_trunk_leaves_the_lane_worktree_alone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    github_clone: Path,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
    output_flags: tuple[str, ...],
    branch_flags: tuple[str, ...],
) -> None:
    """Spec: REL-47, REL-50, REL-65. A rerun with no claim, run from the
    default branch with or without `--branch` naming it, has no lane branch: it
    prints no `worktree:` line and removes nothing, the lane's worktree and
    branch included."""
    landing = arrange_merged_pull_request(
        monkeypatch,
        github_clone,
        bare_remote,
        identity=None,
        trailers=(f"Work-Item: #{WORK_ITEM_ISSUE}",),
        pull_request_body="",
    )
    seed_open_item(github_clone, bare_remote)
    real_git(github_clone, "pull", "-q", "--ff-only", "origin", "main")
    lane_worktree = tmp_path / "lane"
    real_git(github_clone, "worktree", "add", "-q", str(lane_worktree), LANDING_BRANCH)
    write_repository_config(github_clone, 'storage = "state-ref"\n')
    monkeypatch.chdir(github_clone)
    tip_before = state_ref_tip(bare_remote)

    result = run_cli(
        [
            "release",
            str(WORK_ITEM_ISSUE),
            "--agent",
            "Ada",
            "--merged",
            landing.merge_commit,
            *branch_flags,
            *output_flags,
        ],
        capsys,
    )

    assert (result.status, result.stderr) == (0, "")
    assert (json.loads(result.stdout)["worktree"] if output_flags else result.stdout) in (
        None,
        f"LANDED commit {landing.merge_commit} already; nothing left to release\n",
    )
    assert state_ref_tip(bare_remote) == tip_before
    assert lane_worktree.is_dir()
    assert real_git(github_clone, "branch", "--list", LANDING_BRANCH).stdout.strip()
