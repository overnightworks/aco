"""`aco status --path` over a trunk whose board configuration lists `lane_shared` directories."""

import json
from pathlib import Path

import pytest
from cli_fixtures import push_repository_trunk, run_cli, track_board_config
from store_fixtures import claim_intent, publish_claims_from_a_second_clone

from aco import protocol


@pytest.mark.parametrize(
    ("lane_shared", "path", "answer", "tracked"),
    [
        pytest.param(
            ".aco/", ".aco/board.toml", "LANE-SHARED", True, id="under-a-tracked-directory"
        ),
        pytest.param(
            ".aco/", ".aco-other/file.toml", "UNCLAIMED", True, id="beside-a-tracked-directory"
        ),
        pytest.param(".aco", ".aco/board.toml", "UNCLAIMED", False, id="under-a-bare-directory"),
        pytest.param(
            "docs/", "docs/guide.md", "UNCLAIMED", False, id="under-an-untracked-directory"
        ),
    ],
)
@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_only_a_path_under_a_tracked_lane_shared_directory_entry_is_lane_shared(
    lane_shared: str,
    path: str,
    answer: str,
    tracked: bool,
    as_json: bool,
    clone: Path,
    bare_remote: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: STAT-22, STAT-23, PIN-41"""
    claim = claim_intent(
        identity=protocol.IssueIdentity(72), agent="Ada", branch="ada/issue-72", scope=("src",)
    )
    publish_claims_from_a_second_clone(clone, bare_remote, (claim,))
    track_board_config(clone, f'lane_shared = ["{lane_shared}"]\n')
    push_repository_trunk(clone, "origin")

    result = run_cli(["status", "--path", path, *(["--json"] if as_json else [])], capsys)

    assert result.status == 0
    if as_json:
        payload = json.loads(result.stdout)
        assert payload["reason"] == "unclaimed"
        assert payload["lane_shared"] == [{"path": lane_shared, "tracked": tracked}]
    else:
        assert result.stdout == f"{answer} {path}\n"
