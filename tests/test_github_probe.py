"""The GitHub adapter of the board probe (`specs/wait.spec.md`, WAIT-18, WAIT-20),
driven with a fake `gh` process."""

import pytest

from aco import forge, github, github_probe, process, protocol

REPOSITORY_TARGET = forge.ProbeTarget("owner/repo")
ISSUE_TARGET = forge.ProbeTarget("owner/other", 8)
ETAG = 'W/"4f9c"'


class _Gh:
    """A `gh` that answers as given, an exception being raised, and keeps every command."""

    def __init__(self, answer: process.BoundedResult | Exception) -> None:
        self._answer = answer
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **_options: object) -> process.BoundedResult:
        self.commands.append(command)
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def _answer(exit_status: int, text: str) -> process.BoundedResult:
    return process.BoundedResult(exit_status, text.encode())


def _serve(monkeypatch: pytest.MonkeyPatch, answer: process.BoundedResult | Exception) -> _Gh:
    gh = _Gh(answer)
    monkeypatch.setattr(process, "run_bounded", gh)
    return gh


def test_a_200_is_changed_and_carries_the_etag_as_it_came(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec: WAIT-20 -- a 200 means changed, its ETag is sent back as-is."""
    head = f"HTTP/2.0 200 OK\r\nContent-Type: text/plain\r\nEtag: {ETAG}\r\n\r\n[]"
    _serve(monkeypatch, _answer(0, head))
    answer = github_probe.GitHubBoardProbe(github.response_command).changed_since(
        REPOSITORY_TARGET, None
    )
    assert answer == forge.ProbeAnswer(changed=True, token=ETAG)


def test_a_304_is_unchanged_whatever_the_exit_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec: WAIT-20 -- `gh` exits 1 on a 304; the status line decides."""
    _serve(monkeypatch, _answer(1, f"HTTP/2.0 304 Not Modified\r\nEtag: {ETAG}\r\n\r\n"))
    answer = github_probe.GitHubBoardProbe(github.response_command).changed_since(
        REPOSITORY_TARGET, ETAG
    )
    assert answer == forge.ProbeAnswer(changed=False, token=ETAG)


@pytest.mark.parametrize(
    ("target", "token", "path", "conditional"),
    [
        pytest.param(
            REPOSITORY_TARGET,
            ETAG,
            "repos/owner/repo/issues?state=all&sort=updated&direction=desc&per_page=1",
            ["-H", f"If-None-Match: {ETAG}"],
            id="newest-updated-issue-of-the-repository",
        ),
        pytest.param(ISSUE_TARGET, None, "repos/owner/other/issues/8", [], id="one-issue"),
    ],
)
def test_the_request_is_conditional_on_the_token_it_is_given(
    monkeypatch: pytest.MonkeyPatch,
    target: forge.ProbeTarget,
    token: str | None,
    path: str,
    conditional: list[str],
) -> None:
    """Spec: WAIT-18 -- one conditional request for the newest updated issue, one per blocker."""
    gh = _serve(monkeypatch, _answer(0, f"HTTP/2.0 200 OK\nEtag: {ETAG}\n\n[]"))
    github_probe.GitHubBoardProbe(github.response_command).changed_since(target, token)
    assert gh.commands == [["gh", "api", "-i", *conditional, path]]


@pytest.mark.parametrize(
    ("exit_status", "text", "token", "failure"),
    [
        pytest.param(
            1,
            "HTTP/2.0 502 Bad Gateway\n\ngh: Bad Gateway (HTTP 502)",
            ETAG,
            forge.ForgeTransientError,
            id="server-error",
        ),
        pytest.param(
            1, "error connecting to api.github.com", ETAG, forge.ForgeTransientError, id="no-status"
        ),
        pytest.param(
            1,
            "HTTP/2.0 404 Not Found\n\ngh: Not Found (HTTP 404)",
            ETAG,
            forge.ForgeNotFoundError,
            id="not-found",
        ),
        pytest.param(1, "", ETAG, forge.ForgeError, id="no-output"),
        pytest.param(
            1, "HTTP/2.0 304 Not Modified\n\n", None, forge.ForgeError, id="304-to-an-unconditional"
        ),
        pytest.param(
            0,
            "HTTP/2.0 200 OK\n\n[]",
            None,
            forge.ForgeMalformedResponseError,
            id="200-without-an-etag",
        ),
    ],
)
def test_any_other_answer_fails_as_a_failed_gh_call_does(
    monkeypatch: pytest.MonkeyPatch,
    exit_status: int,
    text: str,
    token: str | None,
    failure: type[forge.ForgeError],
) -> None:
    """Spec: WAIT-20 -- a status line that is neither 200 nor 304, or none, is classified."""
    _serve(monkeypatch, _answer(exit_status, text))
    probe = github_probe.GitHubBoardProbe(github.response_command)
    with pytest.raises(failure):
        probe.changed_since(REPOSITORY_TARGET, token)


@pytest.mark.parametrize(
    ("failing", "failure"),
    [
        pytest.param(process.ProcessTimedOutError(), forge.ForgeTransientError, id="timeout"),
        pytest.param(process.ExecutableMissingError("gh"), protocol.ClaimError, id="gh-missing"),
    ],
)
def test_a_gh_that_cannot_run_to_the_end_fails_by_kind(
    monkeypatch: pytest.MonkeyPatch, failing: process.ProcessError, failure: type[Exception]
) -> None:
    """Spec: WAIT-20 -- a timeout is transient; a missing `gh` is not."""
    _serve(monkeypatch, failing)
    probe = github_probe.GitHubBoardProbe(github.response_command)
    with pytest.raises(protocol.ClaimError) as raised:
        probe.changed_since(REPOSITORY_TARGET, None)
    assert type(raised.value) is failure
