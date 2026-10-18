"""Land message literals and Git trailer interpretation on a real claimed lane."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import pytest
from cli_fixtures import real_git, run_cli
from github_fixtures import (
    LANDING_BRANCH,
    FakeForge,
    LaneLandingWorld,
    RefusalLength,
    assert_github_world,
    landing_effects,
    lane_landing_world,
    refusal_observations,
)

from agent_coordination import board, forge, process, protocol, store


class TrailerKey(Enum):
    DEFAULT = ""
    RENAMED = "WORK-ITEM"


class GitNoise(Enum):
    NONE = "none"
    TRACE = "trace"
    CONFIGURATION_WARNING = "configuration-warning"


class GitTrailerRead(Enum):
    READS = "reads"
    EXITS_NONZERO = "nonzero-exit"
    TIMES_OUT = "launch-failure"


@dataclass(frozen=True)
class Message:
    body: str
    keys: list[str]
    committed: str | None = None


@dataclass(frozen=True)
class Landed:
    message: Message
    method: board.MergeMethod = board.MergeMethod.MERGE
    title: str = "Merge pull request #12"
    parents: int = 2
    closed: frozenset[int] = frozenset({72})
    release: str = "RELEASED issue #72: landing\n"


@dataclass(frozen=True)
class MessageCase:
    body: str
    outcome: Landed | str
    trailer_key: TrailerKey = TrailerKey.DEFAULT
    noise: GitNoise = GitNoise.NONE
    trailer_read: GitTrailerRead = GitTrailerRead.READS
    branch: str = LANDING_BRANCH
    identity: protocol.ClaimIdentity = field(default_factory=lambda: protocol.IssueIdentity(72))
    body_trailers: str | None = None


@dataclass
class MessageWorld(LaneLandingWorld):
    case: MessageCase


def trailer_keys(clone: Path, message: str) -> list[str]:
    path = clone.parent / "trailer-message"
    path.write_text(message)
    parsed = real_git(clone, "interpret-trailers", "--parse", "--no-divider", str(path))
    return [line.split(":", 1)[0] for line in parsed.stdout.splitlines()]


def arrange_trailer_read(
    case: MessageCase, github_clone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_git = process.run_git
    probe = github_clone.parent / "probe-message"
    probe.write_text("Title\n\nProbe: value\n")
    arguments = ["interpret-trailers", "--parse", "--no-divider", str(probe)]
    parsed = run_git(arguments, directory=github_clone)
    observed = (parsed.exit_status, parsed.stdout, bool(parsed.stderr))
    expected = (0, b"Probe: value\n", case.noise is not GitNoise.NONE)
    assert observed == expected
    if case.body_trailers is not None:
        assert isinstance(case.outcome, Landed)
        observed = trailer_keys(github_clone, case.outcome.title + "\n\n" + case.body_trailers)
        expected = case.outcome.message.keys[:-1]
        assert observed == expected

    def read(arguments: list[str], *, directory: Path | None = None) -> process.CapturedResult:
        if arguments[0] == "interpret-trailers":
            if case.trailer_read is GitTrailerRead.EXITS_NONZERO:
                return process.CapturedResult(128, b"", b"fatal: bad trailer\n")
            if case.trailer_read is GitTrailerRead.TIMES_OUT:
                raise process.ProcessTimedOutError()
        return run_git(arguments, directory=directory)

    monkeypatch.setattr(process, "run_git", read)
    if case.trailer_read is GitTrailerRead.TIMES_OUT:
        with pytest.raises(process.ProcessTimedOutError):
            read(arguments, directory=github_clone)
    elif case.trailer_read is GitTrailerRead.EXITS_NONZERO:
        observed = read(arguments, directory=github_clone)
        expected = process.CapturedResult(128, b"", b"fatal: bad trailer\n")
        assert observed == expected
    else:
        captured = read(arguments, directory=github_clone)
        observed = (captured.exit_status, captured.stdout, bool(captured.stderr))
        expected = (0, b"Probe: value\n", case.noise is not GitNoise.NONE)
        assert observed == expected
    observed = read(["rev-parse", "HEAD"], directory=github_clone).stdout.decode()
    expected = real_git(github_clone, "rev-parse", "main").stdout
    assert observed == expected


@pytest.fixture
def world(
    request: pytest.FixtureRequest,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_global_git_config: Path,
) -> MessageWorld:
    case: MessageCase = request.param
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("GIT_DISCOVERY_ACROSS_FILESYSTEM", "1")
    monkeypatch.delenv("GIT_TRACE", raising=False)
    observed = (
        os.environ.get("LC_ALL"),
        os.environ.get("GIT_DISCOVERY_ACROSS_FILESYSTEM"),
        os.environ.get("GIT_CONFIG_GLOBAL"),
    )
    expected = ("C", "1", str(isolated_global_git_config))
    assert observed == expected
    assert_github_world(github_clone, bare_remote)
    run_git = process.run_git

    def arrange(client: FakeForge, head: str) -> None:
        detail = client.landings[12]
        readiness = client.readiness_by_number[12]
        observed = (
            detail.number,
            detail.body,
            detail.source_branch,
            detail.target_branch,
            detail.title,
            detail.head_sha,
            detail.merged,
            readiness.number,
            readiness.open,
            readiness.head_sha,
            readiness.mergeable_state,
            readiness.checks,
            client.allowed_methods,
            client.branch_rules,
            client.landings[13].number,
            client.board_open_pull_requests,
        )
        expected = (
            12,
            case.body,
            case.branch,
            "main",
            "feat: land the lane",
            head,
            False,
            12,
            True,
            head,
            forge.MERGEABLE_STATE_CLEAN,
            (forge.CheckRun("ci", forge.CHECK_CONCLUSION_SUCCESS),),
            frozenset({method}),
            {"main": ()},
            13,
            (),
        )
        assert observed == expected
        observed = (
            real_git(github_clone, "rev-parse", case.branch).stdout.strip(),
            real_git(bare_remote, "rev-parse", case.branch).stdout.strip(),
            bool(real_git(github_clone, "diff", "main", case.branch).stdout),
            real_git(github_clone, "status", "--porcelain").stdout,
            real_git(github_clone, "branch", "--show-current").stdout,
        )
        expected = (head, head, True, "", "main\n")
        assert observed == expected
        if case.trailer_key is TrailerKey.RENAMED:
            real_git(github_clone, "config", "trailer.work-item.key", case.trailer_key.value)
        configured = run_git(["config", "--get", "trailer.work-item.key"], directory=github_clone)
        observed = configured.stdout.decode()
        expected = case.trailer_key.value + "\n" if case.trailer_key is TrailerKey.RENAMED else ""
        assert observed == expected
        if case.noise is GitNoise.CONFIGURATION_WARNING:
            real_git(github_clone, "config", "trailer.foo.where", "bogus")
        if case.noise is GitNoise.TRACE:
            monkeypatch.setenv("GIT_TRACE", "1")
        warning = run_git(["config", "--get", "trailer.foo.where"], directory=github_clone)
        observed = (warning.stdout, os.environ.get("GIT_TRACE"))
        expected = (
            b"bogus\n" if case.noise is GitNoise.CONFIGURATION_WARNING else b"",
            "1" if case.noise is GitNoise.TRACE else None,
        )
        assert observed == expected
        arrange_trailer_read(case, github_clone, monkeypatch)

    method = case.outcome.method if isinstance(case.outcome, Landed) else board.MergeMethod.MERGE
    shared = lane_landing_world(
        github_clone,
        bare_remote,
        monkeypatch,
        identity=case.identity,
        branch=case.branch,
        body=case.body,
        methods=frozenset({method}),
        arrange=arrange,
    )
    return MessageWorld(
        shared.clone,
        shared.remote,
        shared.forge,
        shared.unchanged,
        shared.head,
        shared.entry_lineage,
        case,
    )


class TestLandMessage:
    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                MessageCase(
                    "Closes #72\n\nWork-Item: #72\nCo-Authored-By: Ada <ada@example.com>",
                    Landed(
                        Message(
                            "Closes #72\n\nCo-Authored-By: Ada <ada@example.com>\nWork-Item: #72\n",
                            ["Co-Authored-By", "Work-Item"],
                        )
                    ),
                ),
                id="merge-mixed-trailer-block",
            ),
            pytest.param(
                MessageCase(
                    "Closes #72\r\n\r\nWork-Item: #72\r\nCo-Authored-By: Ada <ada@example.com>",
                    Landed(
                        Message(
                            "Closes #72\n\nCo-Authored-By: Ada <ada@example.com>\nWork-Item: #72\n",
                            ["Co-Authored-By", "Work-Item"],
                        ),
                        method=board.MergeMethod.SQUASH,
                        title="feat: land the lane (#12)",
                        parents=1,
                    ),
                ),
                id="squash-mixed-trailer-block",
            ),
            pytest.param(
                MessageCase(
                    "Work-Item: #72\n\nCloses #72",
                    Landed(Message("Closes #72\n\nWork-Item: #72\n", ["Work-Item"])),
                ),
                id="prose-ending",
            ),
            pytest.param(
                MessageCase(
                    "Fixes it.\n\nWork-Item: #72\n\nCloses #72",
                    Landed(Message("Fixes it.\n\nCloses #72\n\nWork-Item: #72\n", ["Work-Item"])),
                ),
                id="classification-mid-body",
            ),
            pytest.param(
                MessageCase(
                    "Closes #72\n\n---\n\nWork-Item: #72\nCo-Authored-By: Ada <ada@example.com>",
                    Landed(
                        Message(
                            "Closes #72\n\n---\n\n"
                            "Co-Authored-By: Ada <ada@example.com>\nWork-Item: #72\n",
                            ["Co-Authored-By", "Work-Item"],
                        )
                    ),
                ),
                id="markdown-rule-before-trailer-block",
            ),
            pytest.param(
                MessageCase(
                    "Fixes it.\n \nWork-Item: #72\n\t\nCloses #72",
                    Landed(
                        Message(
                            "Fixes it.\n\t\nCloses #72\n\nWork-Item: #72\n",
                            ["Work-Item"],
                            "Fixes it.\n\nCloses #72\n\nWork-Item: #72\n",
                        )
                    ),
                ),
                id="classification-between-whitespace-only-lines",
            ),
            pytest.param(
                MessageCase(
                    "Fixes it.\n\n\n\nWork-Item: #72\n\nCloses #72",
                    Landed(Message("Fixes it.\n\nCloses #72\n\nWork-Item: #72\n", ["Work-Item"])),
                ),
                id="classification-after-a-blank-line-run",
            ),
            pytest.param(
                MessageCase(
                    "Fixes it.\n\nWork-Item: #72\n\n\n\nCloses #72",
                    Landed(Message("Fixes it.\n\nCloses #72\n\nWork-Item: #72\n", ["Work-Item"])),
                ),
                id="classification-before-a-blank-line-run",
            ),
            pytest.param(
                MessageCase(
                    "Closes #72\n\nWork-Item: #72\n"
                    "Co-Authored-By: Ada <ada@example.com>\n\n# Notes",
                    Landed(
                        Message(
                            "Closes #72\n\nCo-Authored-By: Ada <ada@example.com>\n"
                            "\n# Notes\n\nWork-Item: #72\n",
                            ["Work-Item"],
                        )
                    ),
                ),
                id="comment-line-after-trailer-block",
            ),
            pytest.param(
                MessageCase(
                    "Closes #72\n\nWork-Item: #72\nCo-authored-by:A <a@x>",
                    Landed(
                        Message(
                            "Closes #72\n\nCo-authored-by:A <a@x>\nWork-Item: #72\n",
                            ["Co-authored-by", "Work-Item"],
                        )
                    ),
                    body_trailers="Closes #72\n\nCo-authored-by:A <a@x>",
                ),
                id="no-space-after-colon",
            ),
            pytest.param(
                MessageCase(
                    "Closes #72\n\nWork-Item: #72\nReviewed-by : A <a@x>",
                    Landed(
                        Message(
                            "Closes #72\n\nReviewed-by : A <a@x>\nWork-Item: #72\n",
                            ["Reviewed-by", "Work-Item"],
                        )
                    ),
                    body_trailers="Closes #72\n\nReviewed-by : A <a@x>",
                ),
                id="space-before-colon",
            ),
            pytest.param(
                MessageCase(
                    "Closes #72\n\nWork-Item: #72\nCo-authored-by: A\n  folded <a@x>",
                    Landed(
                        Message(
                            "Closes #72\n\nCo-authored-by: A\n  folded <a@x>\nWork-Item: #72\n",
                            ["Co-authored-by", "Work-Item"],
                        )
                    ),
                    body_trailers="Closes #72\n\nCo-authored-by: A\n  folded <a@x>",
                ),
                id="folded-continuation",
            ),
            pytest.param(
                MessageCase(
                    "Closes #72\n\nWork-Item: #72\nAcked-by:",
                    Landed(
                        Message(
                            "Closes #72\n\nAcked-by:\nWork-Item: #72\n", ["Acked-by", "Work-Item"]
                        )
                    ),
                    body_trailers="Closes #72\n\nAcked-by:",
                ),
                id="empty-value",
            ),
            pytest.param(
                MessageCase(
                    "Closes #72\n\nWork-Item: #72\nhttps://x.example/a\nCo-authored-by: A <a@x>",
                    Landed(
                        Message(
                            "Closes #72\n\nhttps://x.example/a\n"
                            "Co-authored-by: A <a@x>\nWork-Item: #72\n",
                            ["https", "Co-authored-by", "Work-Item"],
                        )
                    ),
                    body_trailers="Closes #72\n\nhttps://x.example/a\nCo-authored-by: A <a@x>",
                ),
                id="url-beside-trailer",
            ),
            pytest.param(
                MessageCase(
                    "Closes #72\n\nWork-Item: #72\nSigned-off-by: A <a@x>\nOne prose line.",
                    Landed(
                        Message(
                            "Closes #72\n\nSigned-off-by: A <a@x>\n"
                            "One prose line.\nWork-Item: #72\n",
                            ["Signed-off-by", "Work-Item"],
                        )
                    ),
                    body_trailers="Closes #72\n\nSigned-off-by: A <a@x>\nOne prose line.",
                ),
                id="quarter-trailers",
            ),
            pytest.param(
                MessageCase(
                    "Closes #72\n\nWork-Item: #72\nSigned-off-by: A <a@x>\n"
                    "(cherry picked from commit 0123abc)",
                    Landed(
                        Message(
                            "Closes #72\n\nSigned-off-by: A <a@x>\n"
                            "(cherry picked from commit 0123abc)\nWork-Item: #72\n",
                            ["Signed-off-by", "Work-Item"],
                        )
                    ),
                    body_trailers=(
                        "Closes #72\n\nSigned-off-by: A <a@x>\n(cherry picked from commit 0123abc)"
                    ),
                ),
                id="cherry-picked",
            ),
            pytest.param(
                MessageCase(
                    "Closes #72\n\nWork-Item: #72\nCo-Authored-By: Ada <ada@example.com>",
                    Landed(
                        Message(
                            "Closes #72\n\nCo-Authored-By: Ada <ada@example.com>\nWork-Item: #72\n",
                            ["Co-Authored-By", "WORK-ITEM"],
                        )
                    ),
                    trailer_key=TrailerKey.RENAMED,
                ),
                id="configured-key",
            ),
            pytest.param(
                MessageCase(
                    "Work-Item: #72\n\nCloses #72",
                    Landed(Message("Closes #72\n\nWork-Item: #72\n", ["Work-Item"])),
                    noise=GitNoise.TRACE,
                ),
                id="git-trace",
            ),
            pytest.param(
                MessageCase(
                    "Work-Item: #72\n\nCloses #72",
                    Landed(Message("Closes #72\n\nWork-Item: #72\n", ["Work-Item"])),
                    noise=GitNoise.CONFIGURATION_WARNING,
                ),
                id="trailer-configuration-warning",
            ),
            pytest.param(
                MessageCase(
                    "No-Item: fix",
                    Landed(
                        Message("No-Item: fix\n", ["No-Item"]),
                        closed=frozenset(),
                        release="RELEASED lane fix/x: landing\n",
                    ),
                    branch="fix/x",
                    identity=protocol.LaneIdentity(),
                ),
                id="classification-only-body",
            ),
            pytest.param(
                MessageCase(
                    "No-Item: docs\nCo-Authored-By: A <a@x>",
                    Landed(
                        Message(
                            "Co-Authored-By: A <a@x>\nNo-Item: docs\n",
                            ["Co-Authored-By", "No-Item"],
                        ),
                        closed=frozenset(),
                        release="RELEASED lane fix/x: landing\n",
                    ),
                    branch="fix/x",
                    identity=protocol.LaneIdentity(),
                ),
                id="no-item-classification-joins-the-block",
            ),
            pytest.param(
                MessageCase(
                    "Closes #72\n\nCo-Authored-By: A <a@x>\nWork-Item: #72\nSigned-off-by: A <a@x>",
                    Landed(
                        Message(
                            "Closes #72\n\nCo-Authored-By: A <a@x>\n"
                            "Signed-off-by: A <a@x>\nWork-Item: #72\n",
                            ["Co-Authored-By", "Signed-off-by", "Work-Item"],
                        )
                    ),
                ),
                id="classification-between-two-trailers",
            ),
            pytest.param(
                MessageCase(
                    "Closes #72\n\nWork-Item: #72\nCo-Authored-By: Ada <ada@example.com>",
                    Landed(
                        Message(
                            "Closes #72\n\nCo-Authored-By: Ada <ada@example.com>\nWork-Item: #72\n",
                            ["Co-Authored-By", "WORK-ITEM"],
                        ),
                        method=board.MergeMethod.SQUASH,
                        title="feat: land the lane (#12)",
                        parents=1,
                    ),
                    trailer_key=TrailerKey.RENAMED,
                ),
                id="configured-key-under-a-squash",
            ),
        ],
        indirect=True,
    )
    def test_lands(self, world: MessageWorld, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: LANDCMD-13, classification as the last line, merge and squash alike.
        Spec: LANDCMD-34, classification joins the trailer paragraph where git reads both.
        Spec: LANDCMD-35, removing classification leaves no blank-line run.
        Spec: LANDCMD-36, any other body has a blank line before classification.
        """
        outcome = world.case.outcome
        assert isinstance(outcome, Landed)
        capsys.readouterr()
        result = run_cli(["land", "12"], capsys)
        effects = landing_effects(world)
        calls = world.forge.merge_calls
        merge = calls[0] if calls else (None, None, None, None, "")
        entry = world.entry_lineage[0] if world.entry_lineage else ("missing", "missing")
        trunk = real_git(world.clone, "rev-parse", "main").stdout.strip()
        message = real_git(world.clone, "log", "-1", "--format=%B", "main").stdout
        keys = trailer_keys(world.clone, message)
        topology = tuple(
            line
            for line in real_git(world.clone, "worktree", "list", "--porcelain").stdout.splitlines()
            if line.startswith(("worktree ", "branch "))
        )
        branches = set(
            real_git(
                world.clone, "for-each-ref", "--format=%(refname:short)", "refs/heads"
            ).stdout.splitlines()
        )
        observed = {
            "exit": result.status,
            "stderr": result.stderr,
            "stdout.release": outcome.release in result.stdout,
            "merge.count": len(calls),
            "merge.number": merge[0],
            "merge.head": merge[1],
            "merge.method": merge[2],
            "merge.title": merge[3],
            "message": merge[4],
            "trunk.message": message,
            "trunk.parents": len(
                real_git(world.clone, "rev-list", "--parents", "-n", "1", trunk).stdout.split()
            )
            - 1,
            "keys": keys,
            "delete": effects["delete"],
            "close": effects["close"],
            "body writes": effects["body"],
            "remote.moved": effects["remote"] != world.unchanged["remote"],
            "claims": store.peek_state(worktree=world.clone, remote=str(world.remote)).claims,
            "local": effects["local"],
            "worktrees": topology,
            "branches": branches,
            "trunk.changed": trunk + "\n" != world.unchanged["trunk"],
            "trunk.same": trunk == world.forge.landings[12].merge_commit,
            "stamp": effects["stamp"] is not None,
            "anchor": effects["anchor"] is not None,
            "entry.stamp": entry[0],
            "entry.anchor": entry[1],
        }
        committed = (
            outcome.message.body if outcome.message.committed is None else outcome.message.committed
        )
        expected = {
            "exit": 0,
            "stderr": "",
            "stdout.release": True,
            "merge.count": 1,
            "merge.number": 12,
            "merge.head": world.head,
            "merge.method": outcome.method,
            "merge.title": outcome.title,
            "message": outcome.message.body,
            "trunk.message": outcome.title + "\n\n" + committed + "\n",
            "trunk.parents": outcome.parents,
            "keys": outcome.message.keys,
            "delete": [world.case.branch],
            "close": set(outcome.closed),
            "body writes": [],
            "remote.moved": True,
            "claims": {},
            "local": None,
            "worktrees": (f"worktree {world.clone}", "branch refs/heads/main"),
            "branches": {"main", world.case.branch},
            "trunk.changed": True,
            "trunk.same": True,
            "stamp": True,
            "anchor": True,
            "entry.stamp": None,
            "entry.anchor": None,
        }
        assert observed == expected

    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(
                MessageCase(
                    "Work-Item: #72\n\nCloses #72",
                    "fatal: bad trailer",
                    trailer_read=GitTrailerRead.EXITS_NONZERO,
                ),
                id="nonzero-exit",
            ),
            pytest.param(
                MessageCase(
                    "Work-Item: #72\n\nCloses #72",
                    "git interpret-trailers timed out",
                    trailer_read=GitTrailerRead.TIMES_OUT,
                ),
                id="launch-failure",
            ),
        ],
        indirect=True,
    )
    def test_refusal(self, world: MessageWorld, capsys: pytest.CaptureFixture[str]) -> None:
        """Spec: keine (Lücke, #17). Git read failures refuse before merging."""
        assert isinstance(world.case.outcome, str)
        capsys.readouterr()
        result = run_cli(["land", "12"], capsys)
        observed, expected = refusal_observations(
            world, result, world.case.outcome, length=RefusalLength.WITHIN_LIMIT
        )
        observed["merge requests"] = world.forge.merge_requests
        expected["merge requests"] = []
        assert observed == expected
