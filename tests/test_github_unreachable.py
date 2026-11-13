"""The GitHub adapter types a forge `gh` could not reach as transient."""

import pytest

from aco import forge, github, process


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
    monkeypatch: pytest.MonkeyPatch, gh_output: str
) -> None:
    monkeypatch.setattr(
        process, "run_bounded", lambda *args, **kwargs: process.BoundedResult(1, gh_output.encode())
    )
    client = github.GitHubForge(github.repository_id("example/agent-coordination"))

    with pytest.raises(forge.ForgeTransientError) as excinfo:
        client.default_branch()

    assert str(excinfo.value) == gh_output
