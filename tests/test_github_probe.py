"""The GitHub adapter of the board probe (`specs/wait.spec.md`, WAIT-18, WAIT-20),
driven with a fake `ResponseRunner`."""

import pytest

from aco import forge, github_probe

REPOSITORY_TARGET = forge.ProbeTarget("owner/repo")
ISSUE_TARGET = forge.ProbeTarget("owner/other", 8)
ETAG = 'W/"4f9c"'


class _Gh:
    """A `ResponseRunner` that answers as given and keeps every command."""

    def __init__(self, exit_status: int, text: str) -> None:
        self._answer = (text, exit_status)
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], *, purpose: str, repository: str) -> tuple[str, int]:
        self.commands.append(command)
        return self._answer


@pytest.mark.parametrize(
    "header",
    [
        pytest.param(f"Etag: {ETAG}", id="canonical"),
        pytest.param(f"ETAG:  {ETAG} \t", id="upper-case-and-padded"),
        pytest.param(f"etag:{ETAG}", id="without-a-space"),
    ],
)
def test_a_200_is_changed_and_carries_the_etag_as_it_came(header: str) -> None:
    """Spec: WAIT-20 -- a 200 means changed, its ETag is sent back as-is."""
    head = f"HTTP/2.0 200 OK\r\nContent-Type: text/plain\r\n{header}\r\n\r\n[]"
    answer = github_probe.GitHubBoardProbe(_Gh(0, head)).changed_since(REPOSITORY_TARGET, None)
    assert answer == forge.ProbeAnswer(changed=True, token=ETAG)


def test_a_304_is_unchanged_whatever_the_exit_status() -> None:
    """Spec: WAIT-20 -- `gh` exits 1 on a 304; the status line decides."""
    gh = _Gh(1, f"HTTP/2.0 304 Not Modified\r\nEtag: {ETAG}\r\n\r\n")
    answer = github_probe.GitHubBoardProbe(gh).changed_since(REPOSITORY_TARGET, ETAG)
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
    target: forge.ProbeTarget,
    token: str | None,
    path: str,
    conditional: list[str],
) -> None:
    """Spec: WAIT-18 -- one conditional request for the newest updated issue, one per blocker."""
    gh = _Gh(0, f'HTTP/2.0 200 OK\nEtag: {ETAG}\n\n{{"state": "open"}}')
    github_probe.GitHubBoardProbe(gh).changed_since(target, token)
    assert gh.commands == [["gh", "api", "-i", *conditional, path]]


@pytest.mark.parametrize(
    ("exit_status", "text", "token", "failure"),
    [
        pytest.param(
            1,
            "HTTP/2.0 502 Bad Gateway\n\ngh: Bad Gateway (HTTP 502)",
            ETAG,
            forge.ForgeTransientError,
            id="other-status-is-classified-as-a-failed-gh-call",
        ),
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
        pytest.param(
            0,
            "HTTP/2.0 200 OK\nEtag:  \n\n[]",
            None,
            forge.ForgeMalformedResponseError,
            id="200-with-a-blank-etag",
        ),
    ],
)
def test_an_answer_that_is_not_a_usable_200_or_304_fails(
    exit_status: int, text: str, token: str | None, failure: type[forge.ForgeError]
) -> None:
    """Spec: WAIT-20 -- a status that is neither 200 nor 304, or a 200 without an ETag, fails."""
    probe = github_probe.GitHubBoardProbe(_Gh(exit_status, text))
    with pytest.raises(failure):
        probe.changed_since(REPOSITORY_TARGET, token)


@pytest.mark.parametrize(
    ("state", "closed"),
    [pytest.param("open", False, id="open"), pytest.param("closed", True, id="closed")],
)
def test_the_answer_for_an_issue_target_carries_whether_the_issue_is_closed(
    state: str, closed: bool
) -> None:
    """Spec: WAIT-28 -- a blocker is judged from the `state` of the issue the probe answered."""
    text = f'HTTP/2.0 200 OK\nEtag: {ETAG}\n\n{{"state": "{state}"}}'
    answer = github_probe.GitHubBoardProbe(_Gh(0, text)).changed_since(ISSUE_TARGET, None)
    assert (answer.changed, answer.closed) == (True, closed)


def test_a_repository_target_never_reads_its_body() -> None:
    """Spec: WAIT-28 -- the newest updated issue is no blocker; its body is not judged."""
    text = f'HTTP/2.0 200 OK\nEtag: {ETAG}\n\n[{{"state": "closed"}}]'
    answer = github_probe.GitHubBoardProbe(_Gh(0, text)).changed_since(REPOSITORY_TARGET, None)
    assert answer.closed is False


@pytest.mark.parametrize(
    "body",
    [
        pytest.param('{"state": "merged"}', id="another-state"),
        pytest.param("{}", id="no-state"),
        pytest.param("[]", id="not-an-issue"),
    ],
)
def test_an_issue_answer_without_a_state_of_open_or_closed_fails(body: str) -> None:
    """Spec: WAIT-28 -- a malformed answer for a blocker fails loud."""
    probe = github_probe.GitHubBoardProbe(_Gh(0, f"HTTP/2.0 200 OK\nEtag: {ETAG}\n\n{body}"))
    with pytest.raises(forge.ForgeMalformedResponseError):
        probe.changed_since(ISSUE_TARGET, None)


@pytest.mark.parametrize(
    "body",
    [pytest.param("not json", id="not-json"), pytest.param('{"state": "clo', id="cut-short")],
)
def test_an_issue_answer_that_does_not_parse_is_a_transient_failure(body: str) -> None:
    """Spec: WAIT-29 -- a 200 whose body is cut short may be cured by a retry."""
    probe = github_probe.GitHubBoardProbe(_Gh(0, f"HTTP/2.0 200 OK\nEtag: {ETAG}\n\n{body}"))
    with pytest.raises(forge.ForgeTransientError):
        probe.changed_since(ISSUE_TARGET, None)


def test_a_failed_probe_is_transient_and_its_message_holds_no_header_line() -> None:
    """Spec: WAIT-29, WAIT-30 -- a 502 that gh follows with its own cut-short message."""
    text = "HTTP/2.0 502 Bad Gateway\r\nX-Xss-Protection: 0\r\n\r\nunexpected end of JSON input"
    probe = github_probe.GitHubBoardProbe(_Gh(1, text))
    with pytest.raises(forge.ForgeTransientError) as raised:
        probe.changed_since(REPOSITORY_TARGET, ETAG)
    assert str(raised.value) == "unexpected end of JSON input"
