"""`aco status` over a trunk whose committed board configuration cannot be read."""

import json
from pathlib import Path

import pytest
from cli_fixtures import push_repository_trunk, real_git, run_cli
from store_fixtures import claim_intent, publish_claims_from_a_second_clone

from aco import protocol, workboard


@pytest.mark.parametrize(
    "argv",
    [
        ["status"],
        ["status", "--json"],
        ["status", "--path", "src"],
        ["status", "--path", "src", "--json"],
    ],
    ids=["text", "json", "path", "path-json"],
)
def test_status_refuses_whole_when_the_trunk_holds_a_directory_at_the_board_configuration(
    argv: list[str], clone: Path, bare_remote: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: STAT-33"""
    claim = claim_intent(
        identity=protocol.IssueIdentity(7), agent="Ada", branch="ada/issue-7", scope=("src",)
    )
    publish_claims_from_a_second_clone(clone, bare_remote, (claim,))
    configuration = clone / workboard.CONFIG_PATH
    configuration.unlink()
    configuration.mkdir()
    (configuration / "inner.toml").write_text("")
    real_git(clone, "add", "-A")
    real_git(clone, "commit", "-q", "-m", "a directory where the configuration was")
    push_repository_trunk(clone, "origin")
    real_git(clone, "reset", "-q", "--hard", "HEAD~1")

    result = run_cli(argv, capsys)

    assert result.status == 2
    if "--json" in argv:
        payload = json.loads(result.stdout)
        assert (payload["ok"], payload["reason"]) == (False, "unavailable")
        assert workboard.CONFIG_PATH.as_posix() in payload["message"]
    else:
        assert result.stdout == ""
        assert result.stderr.startswith("ERROR: ")
        assert workboard.CONFIG_PATH.as_posix() in result.stderr
