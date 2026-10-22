"""`aco check <n>` for issues and absent numbers, `aco check <sha>`, and the refusals
without an issue verdict, in the real GitHub world."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, REPOSITORY, block_body
from cli_fixtures import (
    CliRun,
    push_repository_trunk,
    real_git,
    run_cli,
    track_board_config,
)
from github_fixtures import ReaderOnlyForge, assert_github_world, serve_forge
from store_fixtures import claim_intent, publish_claims_from_a_second_clone, state_ref_tip

from aco import forge, github, protocol, workboard
from aco.github import GitHubForge

ISSUE = 81
Flags = list[str]
IN_BOTH_FORMS = pytest.mark.parametrize("flags", [[], ["--json"]], ids=["text", "json"])
STATE_REF_CONFIG = 'storage = "state-ref"\n'
GIT_DETAIL = "fatal: not a git repository (or any of the parent directories): .git"
NEEDS_A_CHECKOUT = (
    "this command reads the repository's body contract from .aco/board.toml "
    f"and needs a checkout (a shallow one is enough): {GIT_DETAIL}"
)
REPO_UNDER_STATE_REF = "--repo is meaningless under storage = state-ref"
FORGE_FAILURE = "gh: simulated network failure"


def dependency(
    number: int,
    repository: str = REPOSITORY,
    state: workboard.BlockerState = workboard.BlockerState.OPEN,
) -> workboard.IssueDependency:
    return workboard.IssueDependency(workboard.IssueReference(repository, number), state, False)


@dataclass(frozen=True)
class IssueWorld:
    body: str = block_body(MINIMAL_BLOCK_TOML)
    dependencies: tuple[workboard.IssueDependency, ...] = ()
    state: forge.ItemState = forge.ItemState.OPEN
    reference_failure: forge.ForgeError | None = None
    config: str = ""


SOUND_ISSUE = IssueWorld()


@dataclass(frozen=True)
class NumberCase:
    arguments: tuple[str, ...]
    exit: int
    stdout: str
    stderr: str
    envelope: dict[str, object]
    forge_requests: int
    world: IssueWorld
    json_stderr: str = ""

    def streams(self, flags: Flags) -> tuple[str, str]:
        if flags:
            return json.dumps(self.envelope) + "\n", self.json_stderr
        return self.stdout, self.stderr


@dataclass(frozen=True)
class Observation:
    exit: int | str | None
    stdout: str
    stderr: str
    forge_requests: int
    written: tuple[str, str]


def issue_answer(
    finding: str | None,
    reason: str,
    exit: int,
    forge_requests: int,
    world: IssueWorld,
    *,
    blocked_by: tuple[str, ...] = (),
    number: int = ISSUE,
) -> NumberCase:
    envelope: dict[str, object] = {
        "ok": exit == 0,
        "reason": reason,
        "kind": "missing" if reason == "missing" else "issue",
        "number": number,
    }
    if blocked_by:
        envelope["blocked_by"] = list(blocked_by)
    if finding is not None:
        envelope["message"] = finding
    sentence = f"ISSUE #{number} {finding or 'body ok'}\n"
    if reason == "missing":
        sentence = f"REFUSED: #{number} {finding}\n"
    return NumberCase(
        ("check", str(number)),
        exit,
        sentence if exit == 0 else "",
        "" if exit == 0 else sentence,
        envelope,
        forge_requests,
        world,
    )


def sound(world: IssueWorld = SOUND_ISSUE) -> NumberCase:
    return issue_answer(None, "valid", 0, 2, world)


def malformed(body_text: str, defect: str) -> NumberCase:
    return issue_answer(f"body malformed: {defect}", "malformed", 2, 1, IssueWorld(body_text))


def incomplete(toml_text: str, empty_sections: str) -> NumberCase:
    return issue_answer(
        f"body incomplete: {empty_sections}",
        "incomplete",
        2,
        1,
        IssueWorld(block_body(toml_text)),
    )


def blocked(
    dependencies: tuple[workboard.IssueDependency, ...], labels: tuple[str, ...]
) -> NumberCase:
    return issue_answer(
        f"blocked by {', '.join(labels)}",
        "blocked",
        3,
        2,
        IssueWorld(dependencies=dependencies),
        blocked_by=labels,
    )


def absent(number: int) -> NumberCase:
    return issue_answer(
        f"does not exist in {REPOSITORY}",
        "missing",
        2,
        1,
        IssueWorld(body="", state=forge.ItemState.MISSING),
        number=number,
    )


def unavailable(
    arguments: tuple[str, ...], message: str, reason: str, forge_requests: int, world: IssueWorld
) -> NumberCase:
    return NumberCase(
        arguments,
        2,
        "",
        f"ERROR: {message}\n",
        {"ok": False, "reason": reason, "message": message},
        forge_requests,
        world,
        json_stderr=f"ERROR: {message}\n",
    )


@dataclass(frozen=True)
class Repositories:
    clone: Path
    remote: Path


def refs_of(repositories: Repositories) -> tuple[str, str]:
    return (
        real_git(repositories.clone, "for-each-ref", "--format=%(refname) %(objectname)").stdout,
        real_git(repositories.remote, "for-each-ref").stdout,
    )


NumberCheck = Callable[[NumberCase, Flags], None]


@pytest.fixture
def repositories(github_clone: Path, bare_remote: Path) -> Repositories:
    """The GitHub world whose remote holds a claim in a state ref the clone does not:
    no mode of `check` but the pull-request one may fetch it."""
    assert_github_world(github_clone, bare_remote)
    intent = claim_intent(identity=protocol.IssueIdentity(ISSUE), branch="codex/issue-81-cut")
    publish_claims_from_a_second_clone(github_clone, bare_remote, (intent,))
    assert state_ref_tip(bare_remote) is not None
    assert "aco/state" not in real_git(github_clone, "for-each-ref").stdout
    return Repositories(github_clone, bare_remote)


@pytest.fixture
def check_number(
    repositories: Repositories,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> NumberCheck:
    clone = repositories.clone

    def check(case: NumberCase, flags: Flags) -> None:
        world = case.world
        number = int(case.arguments[-1])
        if world.config:
            track_board_config(clone, world.config)
        assert real_git(clone, "show", f"HEAD:{workboard.CONFIG_PATH}").stdout == world.config
        if world.reference_failure is None:
            reference = forge.ItemReference(world.state, "Work", world.body)
            served = ReaderOnlyForge(
                issue_references={number: reference},
                board_dependencies={number: world.dependencies},
            )
            assert (served.issue_references, served.board_dependencies) == (
                {number: reference},
                {number: world.dependencies},
            )
        else:
            run = Mock(side_effect=world.reference_failure)
            served = GitHubForge(github.repository_id(REPOSITORY), run=run)
            with pytest.raises(type(world.reference_failure)) as arranged:
                run([])
            assert arranged.value is world.reference_failure
            run.reset_mock()
        forge_world = serve_forge(monkeypatch, served)
        before = refs_of(repositories)
        result = run_cli([*case.arguments, *flags], capsys)
        observed = Observation(
            result.status,
            result.stdout,
            result.stderr,
            forge_world.requests,
            refs_of(repositories),
        )
        stdout, stderr = case.streams(flags)
        assert observed == Observation(case.exit, stdout, stderr, case.forge_requests, before)

    return check


NO_BLOCK = "## Now\nReady.\n\n## Next\nLand it.\n\n## Done when\nMerged."
ISSUES = {
    "sound-and-unblocked": sound(),
    "closed-blocker-is-ignored": sound(
        IssueWorld(dependencies=(dependency(62, state=workboard.BlockerState.CLOSED),))
    ),
}
MALFORMED = {
    "no-block": malformed(NO_BLOCK, "aco: no aco block"),
    "first-of-two-defects": malformed(
        block_body('version = 1\nnow = 1\nnext = 2\ndone_when = "D"\n'),
        "now: now must be a string",
    ),
}
INCOMPLETE = {
    "one-key-left-empty": incomplete(
        'version = 1\nnow = "Ready."\nnext = "Land it."\ndone_when = ""\n', "Done when"
    ),
}
BLOCKED = {
    "local-and-foreign": blocked(
        (dependency(7), dependency(9, "other/repo")), ("#7", "other/repo#9")
    ),
    "single-local": blocked((dependency(62),), ("#62",)),
    "local-before-foreign": blocked(
        (dependency(9, "other/repo"), dependency(7)), ("#7", "other/repo#9")
    ),
}
ABSENT = {"in-the-id-space": absent(ISSUE), "past-the-id-space": absent(16_777_216)}
REFUSALS_WITHOUT_ISSUE_VERDICT = {
    "forge-failure": unavailable(
        ("check", str(ISSUE)),
        FORGE_FAILURE,
        "unavailable",
        1,
        IssueWorld(reference_failure=forge.ForgeTransientError(FORGE_FAILURE)),
    ),
    "repo-under-state-ref": unavailable(
        ("--repo", "acme/items", "check", "258"),
        REPO_UNDER_STATE_REF,
        "invalid_usage",
        0,
        IssueWorld(config=STATE_REF_CONFIG),
    ),
}


# Requests read the dispatch reference; a sound or blocked issue also reads its
# blocked_by relation. Malformed or incomplete bodies stop before it; context
# refusals and trunk commits read no forge at all.
ISSUE_ROWS = {**ISSUES, **MALFORMED, **INCOMPLETE, **BLOCKED}


@IN_BOTH_FORMS
@pytest.mark.parametrize("case", ISSUE_ROWS.values(), ids=ISSUE_ROWS.keys())
def test_an_issue_is_judged_by_its_body_and_its_open_blockers(
    case: NumberCase, flags: Flags, check_number: NumberCheck
) -> None:
    """Spec: CHECK-04, CHECK-05, CHECK-06, CHECK-07, CHECK-08"""
    check_number(case, flags)


@IN_BOTH_FORMS
@pytest.mark.parametrize("case", ABSENT.values(), ids=ABSENT.keys())
def test_a_number_in_neither_number_space_is_named_missing(
    case: NumberCase, flags: Flags, check_number: NumberCheck
) -> None:
    """Spec: CHECK-02, CHECK-03"""
    check_number(case, flags)


@IN_BOTH_FORMS
@pytest.mark.parametrize(
    "case", REFUSALS_WITHOUT_ISSUE_VERDICT.values(), ids=REFUSALS_WITHOUT_ISSUE_VERDICT.keys()
)
def test_a_refusal_without_an_issue_verdict_is_reported_in_both_forms(
    case: NumberCase, flags: Flags, check_number: NumberCheck
) -> None:
    """Spec: CHECK-10, CHECK-11"""
    check_number(case, flags)


@IN_BOTH_FORMS
def test_check_outside_a_checkout_names_the_checkout_it_needs(
    flags: Flags,
    outside_a_checkout: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: CHECK-10"""
    forge_world = serve_forge(monkeypatch, ReaderOnlyForge())
    envelope = {"ok": False, "reason": "unavailable", "message": NEEDS_A_CHECKOUT}
    assert Path.cwd() == outside_a_checkout

    result = run_cli(["check", "12", *flags], capsys)

    expected_stdout = json.dumps(envelope) + "\n" if flags else ""
    observed = (result, forge_world.requests)
    assert observed == (
        CliRun(2, expected_stdout, f"ERROR: {NEEDS_A_CHECKOUT}\n"),
        0,
    )


@dataclass(frozen=True)
class TrunkWorld:
    trailers: tuple[str, ...] = ("Work-Item: #20", "No-Item: docs", "No-Item: deps")
    config: str = ""


DEFAULT_TRUNK = TrunkWorld()


@dataclass(frozen=True)
class TrunkCase:
    landing: str | None
    line: str
    reason: str
    message: str | None
    exit: int
    world: TrunkWorld = DEFAULT_TRUNK

    def streams(self, sha: str, flags: Flags) -> tuple[str, str]:
        if flags:
            envelope: dict[str, object] = {
                "ok": self.message is None,
                "reason": self.reason,
                "kind": "trunk_commit",
                "sha": sha,
            }
            if self.message is not None:
                envelope["message"] = self.message
            return json.dumps(envelope) + "\n", ""
        line = self.line.format(sha=sha) + "\n"
        return ("", line) if self.message is not None else (line, "")


UNWALKED_SHA = "0" * 40
NOT_ON_TRUNK = "is not on the first-parent trunk"
NO_TRAILER = "carries no `Work-Item:` or `No-Item:` trailer"
BOTH_KINDS = (
    "carries both `Work-Item:` and `No-Item:` trailers; a landed commit is one or the other"
)
CONTROL_BYTE_TRAILER = "Work-Item: #12\x1f#13"
UNREADABLE_TRAILER = (
    f"carries `{CONTROL_BYTE_TRAILER}`; a trunk trailer names #n, aco-xxxxxx, or the bare number n"
)
REPEATED_NO_ITEM = "carries more than one `No-Item:` trailer"
PAST_THE_ID_SPACE = (
    "carries `Work-Item:` 16777216, which names no state-ref item; an item id ends at aco-ffffff"
)


def declared(landing: str, line: str, world: TrunkWorld = DEFAULT_TRUNK) -> TrunkCase:
    return TrunkCase(landing, "{sha} declares " + line, "valid", None, 0, world)


def refused_trunk(
    landing: str | None,
    message: str,
    reason: str = "invalid_classification",
    world: TrunkWorld = DEFAULT_TRUNK,
) -> TrunkCase:
    return TrunkCase(landing, "REFUSED: {sha} " + message, reason, message, 2, world)


def tip_trailed(trailer: str, config: str = "") -> TrunkWorld:
    return TrunkWorld((trailer,), config)


TRUNK = {
    "work-item": declared("main~2", "Work-Item: #20"),
    "no-item": declared("main~1", "No-Item: docs"),
    "deps": declared("main", "No-Item: deps"),
    "no-trailer": refused_trunk("main~3", NO_TRAILER),
    "off-trunk": refused_trunk("side", NOT_ON_TRUNK, "not_on_trunk"),
    "unknown-sha": refused_trunk(None, NOT_ON_TRUNK, "not_on_trunk"),
    "work-item-and-no-item": refused_trunk(
        "main", BOTH_KINDS, world=tip_trailed("Work-Item: #20\nNo-Item: docs")
    ),
    "repeated-no-item": refused_trunk(
        "main", REPEATED_NO_ITEM, world=tip_trailed("No-Item: docs\nNo-Item: fix")
    ),
    "control-byte-in-a-trailer": refused_trunk(
        "main", UNREADABLE_TRAILER, world=tip_trailed(CONTROL_BYTE_TRAILER)
    ),
}
PAST_THE_ID_SPACE_ROWS = {
    "hash-state-ref": refused_trunk(
        "main", PAST_THE_ID_SPACE, world=tip_trailed("Work-Item: #16777216", STATE_REF_CONFIG)
    ),
    "hash-github": declared("main", "Work-Item: #16777216", tip_trailed("Work-Item: #16777216")),
    "bare-state-ref": refused_trunk(
        "main", PAST_THE_ID_SPACE, world=tip_trailed("Work-Item: 16777216", STATE_REF_CONFIG)
    ),
    "bare-github": declared("main", "Work-Item: #16777216", tip_trailed("Work-Item: 16777216")),
}


def assert_trunk_arranged(clone: Path, world: TrunkWorld) -> None:
    first_parent = ["--first-parent", "--reverse", "--format=%b%x00", "main"]
    trailers = [
        message.strip() for message in real_git(clone, "log", *first_parent).stdout.split("\0")[:-1]
    ]
    trunk = real_git(clone, "rev-list", "--first-parent", "main").stdout.split()
    reachable = real_git(clone, "rev-list", "main").stdout.split()
    side = real_git(clone, "rev-parse", "side").stdout.strip()
    pushed = real_git(clone, "rev-parse", "origin/main").stdout.strip()
    tracked = real_git(clone, "show", f"HEAD:{workboard.CONFIG_PATH}").stdout
    expected_length = len(world.trailers) + (2 if world.config else 1)
    assert (len(trunk), side in trunk, side in reachable, pushed, tracked) == (
        expected_length,
        False,
        True,
        trunk[0],
        world.config,
    )
    assert trailers[-len(world.trailers) :] == list(world.trailers)
    assert real_git(clone, "show", "-s", "--format=%b", side).stdout.strip() == "Work-Item: #21"


TrunkCheck = Callable[[TrunkCase, Flags], None]


@pytest.fixture
def check_trunk(
    repositories: Repositories,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> TrunkCheck:
    clone = repositories.clone

    def check(case: TrunkCase, flags: Flags) -> None:
        world = case.world
        if world.config:
            track_board_config(clone, world.config)
        # The last trailer rides the merge that brings in `side`: a commit reachable from
        # `main`, yet off its first-parent trunk.
        *earlier, merged = world.trailers
        for position, trailer in enumerate(earlier):
            (clone / f"change-{position}.txt").write_text("change\n")
            real_git(clone, "add", f"change-{position}.txt")
            real_git(clone, "commit", "-q", "-m", f"change {position}", "-m", trailer)
        real_git(clone, "checkout", "-q", "-b", "side")
        (clone / "side.txt").write_text("side\n")
        real_git(clone, "add", "side.txt")
        real_git(clone, "commit", "-q", "-m", "side change", "-m", "Work-Item: #21")
        real_git(clone, "checkout", "-q", "main")
        real_git(clone, "merge", "-q", "--no-ff", "side", "-m", "merge side", "-m", merged)
        push_repository_trunk(clone, "origin")
        assert_trunk_arranged(clone, world)
        sha = (
            UNWALKED_SHA
            if case.landing is None
            else real_git(clone, "rev-parse", case.landing).stdout.strip()
        )
        forge_world = serve_forge(monkeypatch, ReaderOnlyForge())
        before = refs_of(repositories)
        result = run_cli(["check", sha, *flags], capsys)
        observed = Observation(
            result.status,
            result.stdout,
            result.stderr,
            forge_world.requests,
            refs_of(repositories),
        )
        assert observed == Observation(case.exit, *case.streams(sha, flags), 0, before)

    return check


@IN_BOTH_FORMS
@pytest.mark.parametrize("case", TRUNK.values(), ids=TRUNK.keys())
def test_a_trunk_commit_is_classified_by_its_own_trailer(
    case: TrunkCase, flags: Flags, check_trunk: TrunkCheck
) -> None:
    """Spec: LAND-03, LAND-48, LAND-57, LAND-58, LAND-60, CHECK-12, CHECK-13, CHECK-14"""
    check_trunk(case, flags)


@IN_BOTH_FORMS
@pytest.mark.parametrize("case", PAST_THE_ID_SPACE_ROWS.values(), ids=PAST_THE_ID_SPACE_ROWS.keys())
def test_a_trailer_number_past_the_id_space_is_refused_only_under_state_ref(
    case: TrunkCase, flags: Flags, check_trunk: TrunkCheck
) -> None:
    """Spec: LAND-68, CHECK-12, CHECK-13"""
    check_trunk(case, flags)
