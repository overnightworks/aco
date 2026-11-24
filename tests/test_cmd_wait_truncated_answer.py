"""`aco wait` without an item over a forge that answers cut short (`specs/wait.spec.md`,
WAIT-29, WAIT-30), through the real entry and the real GitHub probe over a fake `gh` runner,
with only the forge, the pause and the clock injected."""

from dataclasses import dataclass

import pytest
from board_fixtures import block_dependency, blocked_issue
from cli_fixtures import FROZEN_CLI_NOW, run_cli
from github_fixtures import FakeForge, serve_forge
from wait_fixtures import ITEM, OTHER_ITEM, free_item, install, open_reference, waiting_card

from aco import board_wait, cmd_wait, github, workboard

FOREIGN = "other/repo"
FOREIGN_BLOCKER = 3
PAUSES_PER_PROBE = int(board_wait.PROBE_SECONDS / cmd_wait.SIGNAL_POLL_SECONDS)
FIRST_PAUSE_AFTER_THE_READ = 5
STILL_WAITING = "WARNING: the board could not be read, still waiting: "
CUT_SHORT = "unexpected end of JSON input"
BAD_GATEWAY_HEAD = (
    "HTTP/2.0 502 Bad Gateway\r\n"
    "Content-Type: text/html\r\n"
    "X-Github-Request-Id: 8F3A:1B2C:3D4E\r\n"
    "X-Xss-Protection: 0\r\n"
    "\r\n"
)
NOT_MODIFIED = "HTTP/2.0 304 Not Modified\r\n\r\n"
HEAD_LINES = ("X-Xss-Protection", "HTTP/2.0", "Content-Type")

pytestmark = pytest.mark.usefixtures("frozen_wait_world")


@dataclass
class Resource:
    """What the forge answers for one probed path: its tag and body, or the text of a failed
    call."""

    etag: str
    body: str = "[]"
    failure: str | None = None


@dataclass
class FakeGh:
    """A `ResponseRunner` over two resources: the repository's newest issue and the foreign
    blocker; it answers a 304 to a request that sends the current tag."""

    repository: Resource
    blocker: Resource

    def __call__(self, command: list[str], *, purpose: str, repository: str) -> tuple[str, int]:
        resource = (
            self.blocker if command[-1].endswith(f"issues/{FOREIGN_BLOCKER}") else self.repository
        )
        if resource.failure is not None:
            return resource.failure, 1
        if f"If-None-Match: {resource.etag}" in command:
            return NOT_MODIFIED, 1
        return f"HTTP/2.0 200 OK\r\nEtag: {resource.etag}\r\n\r\n{resource.body}", 0


@pytest.fixture
def gh(monkeypatch: pytest.MonkeyPatch) -> FakeGh:
    runner = FakeGh(Resource("A"), Resource("B", '{"state": "open"}'))
    monkeypatch.setattr(github, "response_command", runner)
    return runner


def assert_one_warning_without_a_header_line(stderr: str) -> None:
    assert stderr.startswith(STILL_WAITING)
    assert stderr.count(STILL_WAITING) == 1
    assert not any(line in stderr for line in HEAD_LINES)


@pytest.mark.parametrize("failed_probes", [1, 3], ids=["one-probe", "three-probes"])
def test_a_probe_answered_cut_short_is_one_warning_and_the_wait_goes_on(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    gh: FakeGh,
    failed_probes: int,
) -> None:
    """Spec: WAIT-29, WAIT-30 -- a 502 with the cut-short text warns once without its head
    however long it lasts; the first probe that answers ends the wait by WAIT-14."""
    client = serve_forge(
        monkeypatch,
        FakeForge(
            board_issues=(waiting_card(),),
            issue_references={ITEM: open_reference(waiting_card().body)},
        ),
    )
    ticks = install(monkeypatch, lambda: 0)

    def fail() -> None:
        gh.repository.failure = f"{BAD_GATEWAY_HEAD}{CUT_SHORT}"

    def answer_with_a_new_card() -> None:
        gh.repository = Resource("A+")
        client.board_issues = (waiting_card(), free_item())

    ticks.afterwards[FIRST_PAUSE_AFTER_THE_READ] = fail
    ticks.afterwards[failed_probes * PAUSES_PER_PROBE + FIRST_PAUSE_AFTER_THE_READ] = (
        answer_with_a_new_card
    )
    result = run_cli(["wait"], capsys)
    assert (result.status, result.stdout) == (0, f"ACTIONABLE #{OTHER_ITEM}\n")
    assert result.stderr == f"{STILL_WAITING}{CUT_SHORT}\n"
    assert_one_warning_without_a_header_line(result.stderr)
    assert len(ticks.pauses) == (failed_probes + 1) * PAUSES_PER_PROBE


def test_a_blocker_answered_with_a_cut_body_is_one_warning_and_the_wait_goes_on(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    gh: FakeGh,
) -> None:
    """Spec: WAIT-29, WAIT-30 -- a 200 whose body does not parse warns once; the next probe
    that shows the blocker closed wakes its dependent."""
    dependent, dependencies = blocked_issue(
        OTHER_ITEM, "Alpha", block_dependency(FOREIGN_BLOCKER, repository=FOREIGN)
    )
    client = serve_forge(
        monkeypatch, FakeForge(board_issues=(dependent,), board_dependencies=dependencies)
    )
    ticks = install(monkeypatch, lambda: 0)

    def cut_the_answer() -> None:
        gh.blocker = Resource("B+", '{"sta')

    def close_the_blocker() -> None:
        gh.blocker = Resource("B++", '{"state": "closed"}')
        client.board_dependencies = {
            OTHER_ITEM: (
                block_dependency(
                    FOREIGN_BLOCKER,
                    repository=FOREIGN,
                    state=workboard.BlockerState.CLOSED,
                    closed_at=FROZEN_CLI_NOW,
                ),
            )
        }

    ticks.afterwards[FIRST_PAUSE_AFTER_THE_READ] = cut_the_answer
    ticks.afterwards[PAUSES_PER_PROBE + FIRST_PAUSE_AFTER_THE_READ] = close_the_blocker
    result = run_cli(["wait"], capsys)
    assert (result.status, result.stdout) == (0, f"ACTIONABLE #{OTHER_ITEM}\n")
    assert_one_warning_without_a_header_line(result.stderr)
    assert len(ticks.pauses) == 2 * PAUSES_PER_PROBE
