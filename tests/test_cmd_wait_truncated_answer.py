"""`aco wait` without an item over a forge that answers cut short (`specs/wait.spec.md`,
WAIT-29, WAIT-30), through the real entry and the real GitHub probe over a fake `gh` runner,
with only the forge, the pause and the clock injected and a `gh` on `PATH`."""

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import pytest
from board_fixtures import block_dependency, blocked_issue
from cli_fixtures import FROZEN_CLI_NOW, run_cli
from github_fixtures import FakeForge, serve_forge
from wait_fixtures import ITEM, OTHER_ITEM, free_item, install, open_reference, waiting_card

from aco import board_wait, cmd_wait, workboard

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
    """What the forge answers for one probed path: its tag and body, or the head and the text
    of a failed call."""

    etag: str
    body: str = "[]"
    failure: tuple[str, str] | None = None


# Reads the answer for the repository's newest issue or the foreign blocker from the file the
# test last wrote, as `gh api -i` prints it: the head on stdout, a failure's text on stderr.
FAKE_GH = """#!{python}
import json, os, sys

arguments = sys.argv[1:]
name = "blocker" if arguments[-1].endswith("issues/{blocker}") else "repository"
with open(os.path.join(os.environ["FAKE_GH_ANSWERS"], name)) as answer_file:
    answer = json.load(answer_file)
if answer["failure"] is not None:
    head, text = answer["failure"]
    sys.stdout.write(head)
    sys.stdout.flush()
    print(text, file=sys.stderr)
    sys.exit(1)
if "If-None-Match: " + answer["etag"] in arguments:
    sys.stdout.write({not_modified!r})
    sys.exit(1)
sys.stdout.write("HTTP/2.0 200 OK\\r\\nEtag: " + answer["etag"] + "\\r\\n\\r\\n" + answer["body"])
"""


@dataclass
class FakeGh:
    """A `gh` on `PATH` over two resources, the repository's newest issue and the foreign
    blocker; it answers a 304 to a request that sends the current tag."""

    answers: Path

    def answer(self, name: str, resource: Resource) -> None:
        (self.answers / name).write_text(json.dumps(asdict(resource)))


@pytest.fixture
def gh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeGh:
    shims = tmp_path / "gh-bin"
    shims.mkdir()
    fake_gh = shims / "gh"
    fake_gh.write_text(
        FAKE_GH.format(python=sys.executable, blocker=FOREIGN_BLOCKER, not_modified=NOT_MODIFIED)
    )
    fake_gh.chmod(0o755)
    answers = tmp_path / "gh-answers"
    answers.mkdir()
    monkeypatch.setenv("PATH", f"{shims}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_ANSWERS", str(answers))
    runner = FakeGh(answers)
    runner.answer("repository", Resource("A"))
    runner.answer("blocker", Resource("B", '{"state": "open"}'))
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
        gh.answer("repository", Resource("A", failure=(BAD_GATEWAY_HEAD, CUT_SHORT)))

    def answer_with_a_new_card() -> None:
        gh.answer("repository", Resource("A+"))
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
        gh.answer("blocker", Resource("B+", '{"sta'))

    def close_the_blocker() -> None:
        gh.answer("blocker", Resource("B++", '{"state": "closed"}'))
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
