"""`aco next` and the list of code built ahead of its caller: the lines and the two
`--json` keys (NEXT-49..55) against a real git trunk and forge fakes, one case per
row of the list's scenario matrix."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, board_issue, complete_contract
from cli_fixtures import CliRun, freeze_cli_now, real_git, run_cli
from github_fixtures import FakeForge

from aco import ahead_of_caller, board_read, forge, github, session

LIST_PATH = ".aco/ahead-of-caller.toml"
# `gh api <endpoint> ...` answers with the file named after the endpoint, else HTTP 404.
FAKE_GH = (
    "#!/bin/sh\n"
    'answer="$FAKE_GH_ANSWERS/$(printf %s "$2" | tr / _)"\n'
    '[ -f "$answer" ] && exec cat "$answer"\n'
    'echo "gh: Not Found (HTTP 404)" >&2\n'
    "exit 1\n"
)
TOP_WORK_LINES = (
    "#11 score -10: Top work\nNext: Claim #11.\n"
    "Run: aco start 11 --slug=top-work --scope <paths>\nscope unknown\n"
    "parallel: unknown (first action names no scope)\nclose: none\n"
)
NO_ACTION_LINES = "No actionable item.\nparallel: none\nscope unknown: none\nclose: none\n"


def code(path: str, item: str, reason: str = "kept for later") -> str:
    return f'[[code]]\npath = "{path}"\nitem = "{item}"\nreason = "{reason}"\n'


@dataclass
class World:
    """A GitHub-hosted board with one open item, `#11`, and whatever the trunk's list says;
    `own` serves this repository, a `gh` on `PATH` the other ones."""

    clone: Path
    monkeypatch: pytest.MonkeyPatch
    answers: Path
    own: FakeForge = field(
        default_factory=lambda: FakeForge(
            board_issues=(board_issue(11, "Top work", complete_contract("Claim #11.")),)
        )
    )

    def commit_list(self, text: str | bytes) -> None:
        self.write_list(text)
        real_git(self.clone, "add", "-f", LIST_PATH)
        real_git(self.clone, "commit", "-q", "-m", "list code built ahead of its caller")
        real_git(self.clone, "push", "-q", "origin", "main")

    def write_list(self, text: str | bytes) -> None:
        target = self.clone / LIST_PATH
        if isinstance(text, bytes):
            target.write_bytes(text)
        else:
            target.write_text(text)

    def foreign_issue(self, repository: str, number: int, *, state: str) -> None:
        answer = f'{{"state":"{state}","title":"Other","body":"","is_landing":false}}'
        endpoint = f"repos/{repository}/issues/{number}".replace("/", "_")
        (self.answers / endpoint).write_text(answer)

    def serve(self) -> None:
        adapter = github.GitHubForge
        self.monkeypatch.setattr(
            github,
            "GitHubForge",
            lambda repository: self.own if repository.path == REPOSITORY else adapter(repository),
        )


@pytest.fixture
def world(
    monkeypatch: pytest.MonkeyPatch, github_clone: Path, github_world: Path, tmp_path: Path
) -> World:
    freeze_cli_now(monkeypatch)
    shims = tmp_path / "gh-bin"
    answers = tmp_path / "gh-answers"
    shims.mkdir()
    answers.mkdir()
    fake_gh = shims / "gh"
    fake_gh.write_text(FAKE_GH)
    fake_gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shims}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_ANSWERS", str(answers))
    return World(github_clone, monkeypatch, answers)


def next_both(
    capsys: pytest.CaptureFixture[str],
) -> tuple[CliRun, int | str | None, dict[str, object]]:
    """The text run, then the `--json` run's exit status and payload."""
    printed = run_cli(["next"], capsys)
    result = run_cli(["next", "--json"], capsys)
    return printed, result.status, json.loads(result.stdout)


def entry(path: str, item: int | str, state: str, error: str | None = None) -> dict[str, object]:
    return {"path": path, "item": item, "reason": "kept for later", "state": state, "error": error}


def test_an_open_item_prints_no_line_and_is_carried_open(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: NEXT-49, NEXT-51 (matrix row 1)."""
    world.commit_list(code("src/token.py", "#12"))
    world.serve()

    printed, status, payload = next_both(capsys)

    assert (printed.status, printed.stdout) == (0, TOP_WORK_LINES)
    assert (status, payload["ahead_of_caller"], payload["ahead_of_caller_unavailable"]) == (
        0,
        [entry("src/token.py", 12, "open")],
        None,
    )


@pytest.mark.parametrize(
    ("reference", "phrase", "state"),
    [
        (forge.ItemReference(forge.ItemState.CLOSED), "is closed", "closed"),
        (
            forge.ItemReference(forge.ItemState.MISSING),
            "is not found or not accessible",
            "missing",
        ),
        (
            forge.ItemReference(forge.ItemState.OPEN, is_landing=True),
            "is a pull request",
            "pull_request",
        ),
    ],
)
def test_an_item_that_is_not_open_turns_its_entry_red(
    world: World,
    capsys: pytest.CaptureFixture[str],
    reference: forge.ItemReference,
    phrase: str,
    state: str,
) -> None:
    """Spec: NEXT-49, NEXT-51, NEXT-55 (matrix rows 2, 4, 5)."""
    world.commit_list(code("src/token.py", "12"))
    world.own.issue_references[12] = reference
    world.serve()

    printed, status, payload = next_both(capsys)

    assert (printed.status, printed.stdout) == (
        0,
        TOP_WORK_LINES + f"ahead of caller: src/token.py: item 12 {phrase} (kept for later)\n",
    )
    assert (status, payload["ahead_of_caller"]) == (0, [entry("src/token.py", 12, state)])


def test_a_closed_item_of_another_repository_is_read_from_that_repository(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: AHEAD-11, NEXT-54 (matrix row 3)."""
    world.commit_list(code("src/mcp.py", "owner/other#5"))
    world.foreign_issue("owner/other", 5, state="closed")
    world.serve()

    printed, status, payload = next_both(capsys)

    assert printed.stdout == (
        TOP_WORK_LINES
        + "ahead of caller: src/mcp.py: item owner/other#5 is closed (kept for later)\n"
    )
    assert (status, payload["ahead_of_caller"]) == (
        0,
        [entry("src/mcp.py", "owner/other#5", "closed")],
    )
    assert world.own.issue_reference_lookups == []


def test_a_forge_error_on_one_item_leaves_the_other_entry_judged_and_the_exit_unchanged(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: AHEAD-14, NEXT-49, NEXT-51 (matrix row 6)."""
    world.commit_list(code("src/a.py", "20") + code("src/b.py", "21"))
    timed_out = forge.ForgeTransientError("GitHub timed out")
    world.own.scripted_item_reads = [timed_out, None, timed_out, None]
    world.own.closed_issues = {21}
    world.serve()

    printed, status, payload = next_both(capsys)

    assert (printed.status, printed.stdout) == (
        0,
        TOP_WORK_LINES
        + "ahead of caller: src/a.py: item 20 is unreadable: GitHub timed out (kept for later)\n"
        + "ahead of caller: src/b.py: item 21 is closed (kept for later)\n",
    )
    assert (status, payload["ahead_of_caller"]) == (
        0,
        [
            entry("src/a.py", 20, "unreadable", "GitHub timed out"),
            entry("src/b.py", 21, "closed"),
        ],
    )


def test_two_entries_naming_one_item_read_it_once_and_are_both_judged(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: AHEAD-13 (matrix row 7)."""
    world.commit_list(code("src/a.py", "12") + code("src/b.py", "#12"))
    world.own.closed_issues = {12}
    world.serve()

    printed, status, payload = next_both(capsys)

    assert world.own.issue_reference_lookups == [12, 12]
    assert printed.stdout.splitlines()[-2:] == [
        "ahead of caller: src/a.py: item 12 is closed (kept for later)",
        "ahead of caller: src/b.py: item 12 is closed (kept for later)",
    ]
    assert (status, payload["ahead_of_caller"]) == (
        0,
        [entry("src/a.py", 12, "closed"), entry("src/b.py", 12, "closed")],
    )


@pytest.mark.parametrize("text", [None, "", "# nothing yet\n", "code = []\n"])
def test_no_entries_print_no_line_and_carry_empty_keys(
    world: World, capsys: pytest.CaptureFixture[str], text: str | None
) -> None:
    """Spec: AHEAD-01, NEXT-51, NEXT-52 (matrix rows 8, 9)."""
    if text is not None:
        world.commit_list(text)
    world.serve()

    printed, status, payload = next_both(capsys)

    assert (printed.stdout, status) == (TOP_WORK_LINES, 0)
    assert (payload["ahead_of_caller"], payload["ahead_of_caller_unavailable"]) == ([], None)


@pytest.mark.parametrize(
    ("text", "sentence"),
    [
        ("[[cod]]\n", f"{LIST_PATH} has the unknown top-level key 'cod'"),
        ("code = 3\n", f"{LIST_PATH}: 'code' must be an array of tables"),
        (
            code("a.py", "#1").replace('reason = "kept for later"\n', ""),
            f"{LIST_PATH}: code entry 1 lacks 'reason'",
        ),
        (
            code("a.py", "#1") + 'more = "x"\n',
            f"{LIST_PATH}: code entry 1 has the unknown key 'more'",
        ),
        (
            code("/a.py", "#1"),
            f"{LIST_PATH}: code entry 1 has a path that is not repository-relative with "
            "forward slashes",
        ),
        (
            code("a/../b.py", "#1"),
            f"{LIST_PATH}: code entry 1 has a path that holds a '..' segment",
        ),
        (
            code("a.py", "#1", reason="a\\nb"),
            f"{LIST_PATH}: code entry 1 has a reason that is not one non-empty line",
        ),
        (
            code("a.py", "x1"),
            f"{LIST_PATH}: code entry 1 has an item 'x1' that is not aco-xxxxxx, #n, n or "
            "OWNER/REPO#n",
        ),
        (
            code("a.py", "#1") + code("a.py", "1"),
            f"{LIST_PATH}: code entry 2 repeats the path and item of an earlier entry",
        ),
    ],
)
def test_a_malformed_file_prints_the_unavailable_line_and_the_rest_of_the_output(
    world: World, capsys: pytest.CaptureFixture[str], text: str, sentence: str
) -> None:
    """Spec: AHEAD-04..AHEAD-09, NEXT-50, NEXT-52 (matrix row 10)."""
    world.commit_list(text)
    world.serve()

    printed, status, payload = next_both(capsys)

    carried = payload["ahead_of_caller_unavailable"]
    assert isinstance(carried, str)
    assert carried == sentence
    assert (printed.status, printed.stdout) == (
        0,
        TOP_WORK_LINES + f"ahead of caller: unavailable ({carried})\n",
    )
    assert (status, payload["ahead_of_caller"]) == (0, [])


def test_a_file_only_in_the_worktree_is_ignored(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: AHEAD-03 (matrix row 11)."""
    world.write_list(code("src/token.py", "12"))
    world.own.closed_issues = {12}
    world.serve()

    printed, status, payload = next_both(capsys)

    assert printed.stdout == TOP_WORK_LINES
    assert (status, payload["ahead_of_caller"], payload["ahead_of_caller_unavailable"]) == (
        0,
        [],
        None,
    )


def test_a_trunk_that_cannot_be_resolved_refuses_next_whole_never_reads_no_file(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: AHEAD-15 (matrix row 12)."""
    world.commit_list(code("src/token.py", "12"))
    real_git(world.clone, "update-ref", "refs/remotes/origin/renamed", "refs/remotes/origin/main")
    real_git(world.clone, "update-ref", "-d", "refs/remotes/origin/main")
    real_git(world.clone, "symbolic-ref", "-d", "refs/remotes/origin/HEAD")
    world.serve()

    printed, status, payload = next_both(capsys)

    assert (printed.status, printed.stdout) == (2, "")
    assert printed.stderr.startswith("ERROR: cannot determine the trunk")
    assert (status, payload["ok"], payload["reason"]) == (2, False, "unavailable")
    assert "ahead_of_caller" not in payload


def test_a_trunk_git_cannot_show_makes_the_list_unavailable_never_no_file(world: World) -> None:
    """Spec: AHEAD-02."""
    world.commit_list(code("src/token.py", "12"))
    real_git(world.clone, "update-ref", "refs/remotes/origin/renamed", "refs/remotes/origin/main")
    real_git(world.clone, "update-ref", "-d", "refs/remotes/origin/main")
    real_git(world.clone, "symbolic-ref", "-d", "refs/remotes/origin/HEAD")

    reading = board_read.ahead_of_caller_reading(session.run_context(None))

    assert isinstance(reading, ahead_of_caller.Unavailable)
    assert reading.sentence.startswith(f"{LIST_PATH} cannot be read: cannot determine the trunk")


def test_a_trunk_path_that_is_a_directory_is_unavailable_never_no_file(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: AHEAD-02 (matrix row 13)."""
    (world.clone / LIST_PATH).mkdir(parents=True)
    (world.clone / LIST_PATH / "inner.txt").write_text("x\n")
    real_git(world.clone, "add", "-f", LIST_PATH)
    real_git(world.clone, "commit", "-q", "-m", "a directory where the list belongs")
    real_git(world.clone, "push", "-q", "origin", "main")
    world.serve()

    printed, status, payload = next_both(capsys)

    carried = payload["ahead_of_caller_unavailable"]
    assert isinstance(carried, str)
    assert carried.startswith(f"{LIST_PATH} is not valid TOML: ")
    assert (printed.status, printed.stdout) == (
        0,
        TOP_WORK_LINES + f"ahead of caller: unavailable ({carried})\n",
    )
    assert (status, payload["ahead_of_caller"]) == (0, [])


def test_a_red_entry_beside_no_actionable_item_prints_and_keeps_exit_three(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: NEXT-53 (matrix row 15)."""
    world.commit_list(code("src/token.py", "12"))
    world.own.board_issues = ()
    world.own.closed_issues = {12}
    world.serve()

    printed, status, payload = next_both(capsys)

    assert (printed.status, printed.stdout) == (
        3,
        NO_ACTION_LINES + "ahead of caller: src/token.py: item 12 is closed (kept for later)\n",
    )
    assert (status, payload["ahead_of_caller"]) == (3, [entry("src/token.py", 12, "closed")])


def test_control_characters_in_a_path_and_an_error_are_escaped_in_text_only(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: NEXT-50 (matrix row 16)."""
    world.commit_list(code("a\\u001b[2J.py", "20", "why\\u202e"))
    unreadable = forge.ForgeTransientError("bad\x1b[2J")
    world.own.scripted_item_reads = [unreadable, unreadable]
    world.serve()

    printed, status, payload = next_both(capsys)

    assert printed.stdout.splitlines()[-1] == (
        "ahead of caller: a\\x1b[2J.py: item 20 is unreadable: bad\\x1b[2J (why\\u202e)"
    )
    assert (status, payload["ahead_of_caller"]) == (
        0,
        [
            {
                "path": "a\x1b[2J.py",
                "item": 20,
                "reason": "why" + chr(0x202E),
                "state": "unreadable",
                "error": "bad\x1b[2J",
            }
        ],
    )


def test_a_list_that_is_no_utf8_is_unavailable_and_the_rest_of_the_output_prints(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: AHEAD-02 (matrix row 10)."""
    world.commit_list(b"\xff\xfe[[code]]\n")
    world.serve()

    printed, status, payload = next_both(capsys)

    sentence = (
        f"{LIST_PATH} cannot be read: 'utf-8' codec can't decode byte 0xff in position 0: "
        "invalid start byte"
    )
    assert (printed.status, printed.stdout) == (
        0,
        TOP_WORK_LINES + f"ahead of caller: unavailable ({sentence})\n",
    )
    assert (status, payload["ahead_of_caller"], payload["ahead_of_caller_unavailable"]) == (
        0,
        [],
        sentence,
    )
