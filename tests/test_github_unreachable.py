"""The GitHub adapter types a forge `gh` could not reach as transient."""

import os
from pathlib import Path

import pytest

from aco import forge, github

FAKE_GH_FAILING = '#!/bin/sh\nprintf "%s" "$FAKE_GH_OUTPUT" >&2\nexit 1\n'


@pytest.mark.parametrize(
    "gh_output",
    [
        pytest.param(
            "error connecting to api.github.com\ncheck your internet connection",
            id="dns-failure",
        ),
        pytest.param(
            'Get "https://api.github.com/repos/o/r": dial tcp 140.82.121.6:443: '
            "connect: connection refused",
            id="connect-failure",
        ),
    ],
)
def test_gh_failing_to_connect_is_a_transient_forge_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, gh_output: str
) -> None:
    shims = tmp_path / "gh-bin"
    shims.mkdir()
    fake_gh = shims / "gh"
    fake_gh.write_text(FAKE_GH_FAILING)
    fake_gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shims}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_OUTPUT", gh_output)
    client = github.GitHubForge(github.repository_id("example/agent-coordination"))

    with pytest.raises(forge.ForgeTransientError) as excinfo:
        client.default_branch()

    assert str(excinfo.value) == gh_output
