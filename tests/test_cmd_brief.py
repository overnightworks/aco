"""`aco brief` on a real lane worktree and the real state ref. The forge is the only fake."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, write_repository_config
from cli_fixtures import (
    FROZEN_CLI_NOW,
    GIT_FAILURE_INJECTIONS,
    CliRun,
    forbid_github_construction,
    freeze_cli_now,
    real_git,
    recorded_head_read,
    run_cli,
    stub_one_git_call,
    track_board_config,
)
from github_fixtures import FakeForge, serve_forge
from store_fixtures import claim_intent, publish_claims_from_a_second_clone

from aco import forge, protocol, workboard

ITEM = 258
LANE_BRANCH = "codex/issue-258-brief"
BODY = "The item's own body."
CLAIM_AGE = timedelta(hours=24)
BRIEF_TOML = '[build]\nrules = ["Stay in scope."]\nchecks = ["ruff check ."]\n'
ALL_STEPS_TOML = (
    BRIEF_TOML
    + '\n[review]\nrules = ["Mark every finding blocking or follow-up."]\nchecks = []\n'
    + '\n[fix]\nrules = ["Resolve only what the review marked blocking."]\n'
    + 'checks = ["ruff check ."]\n'
    + "\n[land]\nrules = []\nchecks = []\n"
)


@dataclass(frozen=True)
class Lane:
    """Issue 258's claim on the state ref and its lane branch, one commit past `main`."""

    clone: Path
    directory: Path
    base: str
    tip: str


@pytest.fixture
def served_body(monkeypatch: pytest.MonkeyPatch) -> FakeForge:
    freeze_cli_now(monkeypatch)
    served = FakeForge(
        issue_references={ITEM: forge.ItemReference(forge.ItemState.OPEN, "Brief", BODY)}
    )
    return serve_forge(monkeypatch, served)


def commit_file(directory: Path, name: str, text: str) -> str:
    (directory / name).write_text(text)
    real_git(directory, "add", name)
    real_git(directory, "commit", "-q", "-m", f"add {name}")
    return real_git(directory, "rev-parse", "HEAD").stdout.strip()


def publish(
    clone: Path, remote: Path, *claims: protocol.ClaimIntent, opened: timedelta = CLAIM_AGE
) -> None:
    publish_claims_from_a_second_clone(
        clone, remote, claims, bootstrapped_at=(FROZEN_CLI_NOW - opened).isoformat()
    )


def issue_claim_of(item: int, base: str, *, whole: str | None = None) -> protocol.ClaimIntent:
    return claim_intent(
        identity=protocol.IssueIdentity(item),
        agent="Codex Sol",
        branch=LANE_BRANCH,
        scope=("README.md",),
        base=protocol.ObjectId(base),
        whole_reason=whole,
        claim_id=f"claim-{item}",
        operation_id=f"op-{item}",
    )


def make_lane(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    clone: Path,
    bare_remote: Path,
    *,
    whole: str | None = None,
    claimed: bool = True,
) -> Lane:
    base = real_git(clone, "rev-parse", "HEAD").stdout.strip()
    publish(clone, bare_remote, *([issue_claim_of(ITEM, base, whole=whole)] if claimed else []))
    directory = tmp_path / "lane"
    real_git(clone, "worktree", "add", "-q", "-b", LANE_BRANCH, str(directory))
    tip = commit_file(directory, "README.md", "hello\nbrief\n")
    monkeypatch.chdir(directory)
    return Lane(clone, directory, base, tip)


@pytest.fixture
def lane(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    github_clone: Path,
    bare_remote: Path,
    served_body: FakeForge,
) -> Lane:
    return make_lane(monkeypatch, tmp_path, github_clone, bare_remote)


def brief(capsys: pytest.CaptureFixture[str], *flags: str) -> CliRun:
    return run_cli(["--repo", REPOSITORY, "brief", str(ITEM), *flags], capsys)


def claim_lines(world: Lane, *, whole: str | None = None) -> list[str]:
    return [
        f"Codex Sol (builder) branch={LANE_BRANCH} base={world.base} 24h 0m old",
        "  README.md",
        *([f"  whole: {whole}"] if whole else []),
    ]


def test_brief_prints_body_claim_lane_tip_and_touched_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    github_clone: Path,
    bare_remote: Path,
    served_body: FakeForge,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: BRIEF-01, BRIEF-02, BRIEF-05, BRIEF-11, BRIEF-26."""
    track_board_config(github_clone, 'lane_shared = ["scripts/registry.txt"]\n')
    real_git(github_clone, "push", "-q", "origin", "main")
    world = make_lane(monkeypatch, tmp_path, github_clone, bare_remote, whole="too wide")
    write_repository_config(world.directory, 'lane_shared = ["scripts/registry.txt", "src/x.py"]\n')

    result = brief(capsys)

    assert (result.status, result.stderr) == (0, "")
    assert result.stdout.splitlines() == [
        BODY,
        "",
        "CLAIM",
        *claim_lines(world, whole="too wide"),
        "  lane-shared: scripts/registry.txt (names no file)",
        "",
        "TIP",
        world.tip,
        "",
        "TOUCHED",
        "README.md",
    ]


def test_brief_names_no_claim_beside_the_claims_of_other_items_and_of_lanes(
    monkeypatch: pytest.MonkeyPatch,
    github_clone: Path,
    bare_remote: Path,
    served_body: FakeForge,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: BRIEF-03, Never: a lane claim is never an item's claim."""
    base = protocol.ObjectId(real_git(github_clone, "rev-parse", "HEAD").stdout.strip())
    other_item = claim_intent(
        identity=protocol.IssueIdentity(ITEM + 1), base=base, scope=("src",), claim_id="other"
    )
    a_lane = claim_intent(
        identity=protocol.LaneIdentity(),
        branch=LANE_BRANCH,
        base=base,
        scope=("docs",),
        claim_id="lane",
        operation_id="op-lane",
    )
    publish(github_clone, bare_remote, other_item, a_lane)

    result = brief(capsys)

    assert (result.status, result.stderr) == (0, "")
    assert result.stdout.splitlines() == [
        BODY,
        "",
        "CLAIM",
        "no active claim",
        "",
        "TIP",
        "",
        "TOUCHED",
    ]


def test_brief_reports_branch_not_found_when_the_claim_branch_is_gone(
    monkeypatch: pytest.MonkeyPatch,
    github_clone: Path,
    bare_remote: Path,
    served_body: FakeForge,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: BRIEF-04."""
    base = real_git(github_clone, "rev-parse", "HEAD").stdout.strip()
    publish(github_clone, bare_remote, issue_claim_of(ITEM, base))

    result = brief(capsys)

    assert (result.status, result.stderr) == (0, "")
    assert result.stdout.splitlines() == [
        BODY,
        "",
        "CLAIM",
        f"Codex Sol (builder) branch={LANE_BRANCH} base={base} 24h 0m old",
        "  README.md",
        "",
        "TIP",
        "branch not found",
        "",
        "TOUCHED",
    ]


def test_brief_refuses_with_gits_text_when_the_lane_tip_read_fails_outright(
    monkeypatch: pytest.MonkeyPatch, lane: Lane, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BRIEF-18. `rev-parse --verify --quiet`'s exit 1 alone means "does not
    resolve"; any other exit is a tool failure and refuses."""
    answered = stub_one_git_call(
        monkeypatch,
        ["rev-parse", "--verify", "--quiet", LANE_BRANCH],
        exit_status=128,
        stderr="simulated git failure",
    )

    result = brief(capsys)

    assert (result.status, result.stdout, result.stderr) == (
        2,
        "",
        "ERROR: simulated git failure\n",
    )
    assert answered


def test_brief_json_names_a_failing_item_read_unavailable(
    lane: Lane, served_body: FakeForge, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BRIEF-19."""
    served_body.scripted_item_reads = [forge.ForgeError("simulated forge read failure")]

    result = brief(capsys, "--json")

    assert (result.status, result.stderr) == (2, "ERROR: simulated forge read failure\n")
    assert (
        result.stdout
        == json.dumps(
            {"ok": False, "reason": "unavailable", "message": "simulated forge read failure"}
        )
        + "\n"
    )


def test_brief_json_prints_one_object_with_body_claim_tip_and_touched(
    lane: Lane, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BRIEF-06, BRIEF-10, BRIEF-27."""
    result = brief(capsys, "--json")

    expected = {
        "ok": True,
        "reason": "composed",
        "body": BODY,
        "claim": {
            "agent": "Codex Sol",
            "role": "builder",
            "branch": LANE_BRANCH,
            "base": lane.base,
            "scope": ["README.md"],
            "whole": None,
            "age": "24h 0m",
            "lane_shared": [],
            "lane_shared_unavailable": None,
        },
        "tip": lane.tip,
        "touched": ["README.md"],
        "outside_claim": [],
    }
    assert (result.status, result.stderr, result.stdout) == (0, "", json.dumps(expected) + "\n")


@pytest.mark.parametrize(("claimed", "outside_claim"), [(True, ["board.py"]), (False, None)])
def test_brief_json_names_touched_paths_the_claim_scope_does_not_cover(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    github_clone: Path,
    bare_remote: Path,
    served_body: FakeForge,
    capsys: pytest.CaptureFixture[str],
    claimed: bool,
    outside_claim: list[str] | None,
) -> None:
    """Spec: BRIEF-27."""
    world = make_lane(monkeypatch, tmp_path, github_clone, bare_remote, claimed=claimed)
    commit_file(world.directory, "board.py", "print()\n")

    result = brief(capsys, "--json")

    assert (result.status, result.stderr) == (0, "")
    payload = json.loads(result.stdout)
    assert (payload["claim"] is None, payload["outside_claim"]) == (not claimed, outside_claim)


@pytest.mark.parametrize("flags", [(), ("--json",)], ids=["text", "json"])
@pytest.mark.parametrize("pulled", [False, True], ids=["trunk-moved-on", "trunk-pulled-in"])
def test_brief_touched_lists_only_the_lane_own_change_whatever_trunk_landed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    github_clone: Path,
    bare_remote: Path,
    served_body: FakeForge,
    capsys: pytest.CaptureFixture[str],
    flags: tuple[str, ...],
    pulled: bool,
) -> None:
    """Spec: BRIEF-05. TOUCHED diffs from the merge base with trunk, never from the
    claim's base and never from trunk's tip."""
    world = make_lane(monkeypatch, tmp_path, github_clone, bare_remote)
    commit_file(github_clone, "b.py", "landed elsewhere\n")
    real_git(github_clone, "push", "-q", "origin", "main")
    if pulled:
        real_git(world.directory, "merge", "-q", "--no-edit", "origin/main")

    result = brief(capsys, *flags)

    touched = (
        json.loads(result.stdout)["touched"]
        if flags
        else result.stdout.splitlines()[result.stdout.splitlines().index("TOUCHED") + 1 :]
    )
    assert (result.status, result.stderr, touched) == (0, "", ["README.md"])


@pytest.mark.parametrize("flags", [(), ("--json",)], ids=["text", "json"])
def test_brief_refuses_naming_every_trunk_candidate_when_none_resolves(
    lane: Lane, capsys: pytest.CaptureFixture[str], flags: tuple[str, ...]
) -> None:
    """Spec: BRIEF-17, BRIEF-20. A branchless remote and no local `main` or `master`."""
    real_git(lane.clone, "remote", "set-head", "origin", "-d")
    real_git(lane.clone, "update-ref", "-d", "refs/remotes/origin/main")
    real_git(lane.clone, "branch", "-m", "main", "trunk")
    sentence = (
        "cannot determine the trunk: none of origin/HEAD, origin/main, origin/master,"
        " main or master resolves"
    )

    result = brief(capsys, *flags)

    refusal = {"ok": False, "reason": "unavailable", "message": sentence}
    assert (result.status, result.stderr) == (2, f"ERROR: {sentence}\n")
    assert result.stdout == (json.dumps(refusal) + "\n" if flags else "")


def track_brief_config(directory: Path, content: str) -> None:
    write_repository_config(directory, content, path=workboard.BRIEF_CONFIG_PATH)
    real_git(directory, "add", workboard.BRIEF_CONFIG_PATH.as_posix())


@pytest.mark.parametrize(
    ("step", "step_lines"),
    [
        ("build", ("", "RULES", "Stay in scope.", "", "CHECKS", "ruff check .")),
        ("review", ("", "RULES", "Mark every finding blocking or follow-up.", "", "CHECKS")),
        (
            "fix",
            (
                "",
                "RULES",
                "Resolve only what the review marked blocking.",
                "",
                "CHECKS",
                "ruff check .",
            ),
        ),
        ("land", ("", "RULES", "", "CHECKS")),
    ],
)
def test_brief_step_prints_this_repositorys_own_rules_and_checks_by_step(
    lane: Lane, capsys: pytest.CaptureFixture[str], step: str, step_lines: tuple[str, ...]
) -> None:
    """Spec: BRIEF-12, BRIEF-13."""
    track_brief_config(lane.directory, ALL_STEPS_TOML)

    result = brief(capsys, "--step", step)

    assert (result.status, result.stderr) == (0, "")
    assert result.stdout.splitlines() == [
        BODY,
        "",
        "CLAIM",
        *claim_lines(lane),
        "",
        "TIP",
        lane.tip,
        "",
        "TOUCHED",
        "README.md",
        *step_lines,
    ]


def test_brief_without_step_ignores_the_tracked_brief_config(
    lane: Lane, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BRIEF-16."""
    track_brief_config(lane.directory, BRIEF_TOML)

    result = brief(capsys)

    assert (result.status, result.stderr) == (0, "")
    assert result.stdout.splitlines() == [
        BODY,
        "",
        "CLAIM",
        *claim_lines(lane),
        "",
        "TIP",
        lane.tip,
        "",
        "TOUCHED",
        "README.md",
    ]


def test_brief_step_json_adds_rules_and_checks_to_the_object(
    lane: Lane, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BRIEF-14."""
    track_brief_config(lane.directory, BRIEF_TOML)

    result = brief(capsys, "--step", "build", "--json")

    payload = json.loads(result.stdout)
    assert (result.status, result.stderr) == (0, "")
    assert (list(payload)[-2:], payload["rules"], payload["checks"]) == (
        ["rules", "checks"],
        ["Stay in scope."],
        ["ruff check ."],
    )


@pytest.mark.parametrize("on_disk", [False, True], ids=["missing", "untracked"])
def test_brief_step_refuses_before_reading_the_item_when_the_brief_config_is_not_tracked(
    lane: Lane, served_body: FakeForge, capsys: pytest.CaptureFixture[str], on_disk: bool
) -> None:
    """Spec: BRIEF-15, BRIEF-17."""
    if on_disk:
        write_repository_config(lane.directory, BRIEF_TOML, path=workboard.BRIEF_CONFIG_PATH)

    result = brief(capsys, "--step", "build", "--json")

    assert (result.status, result.stderr) == (2, "ERROR: no .aco/brief.toml in the repository\n")
    assert (
        result.stdout
        == json.dumps(
            {
                "ok": False,
                "reason": "unavailable",
                "message": "no .aco/brief.toml in the repository",
            }
        )
        + "\n"
    )
    assert served_body.issue_reference_lookups == []


def test_brief_refuses_a_canonical_remote_whose_host_has_no_forge_adapter(
    monkeypatch: pytest.MonkeyPatch, clone: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BRIEF-07, BRIEF-17."""
    real_git(clone, "remote", "set-url", "origin", "file:///srv/git/agent-coordination.git")
    forbid_github_construction(monkeypatch)

    result = brief(capsys, "--json")

    assert (result.status, result.stderr) == (2, "ERROR: no forge adapter for host file\n")
    assert (
        result.stdout
        == json.dumps(
            {"ok": False, "reason": "unavailable", "message": "no forge adapter for host file"}
        )
        + "\n"
    )


def test_brief_names_repo_as_invalid_usage_under_state_ref_storage(
    clone: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BRIEF-09, BRIEF-17, PIN-04."""
    track_board_config(clone, 'storage = "state-ref"\n')

    result = brief(capsys, "--json")

    assert (result.status, result.stderr) == (
        2,
        "ERROR: --repo is meaningless under storage = state-ref\n",
    )
    assert (
        result.stdout
        == json.dumps(
            {
                "ok": False,
                "reason": "invalid_usage",
                "message": "--repo is meaningless under storage = state-ref",
            }
        )
        + "\n"
    )


@pytest.mark.parametrize(("inject", "detail"), GIT_FAILURE_INJECTIONS)
def test_brief_refuses_with_gits_text_when_reading_the_remote_head_fails(
    monkeypatch: pytest.MonkeyPatch,
    github_clone: Path,
    served_body: FakeForge,
    capsys: pytest.CaptureFixture[str],
    inject: Callable[[pytest.MonkeyPatch, list[str]], list[list[str]]],
    detail: str,
) -> None:
    """Spec: BRIEF-17, Never: a failed read of `<remote>/HEAD` never guesses a trunk, so it
    never reads as a trunk that names no lane-shared file."""
    injected = inject(monkeypatch, list(recorded_head_read("origin")))

    result = brief(capsys)

    assert (result.status, result.stdout, result.stderr) == (2, "", f"ERROR: {detail}\n")
    assert injected
