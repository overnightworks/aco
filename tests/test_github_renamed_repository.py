"""The GitHub adapter notices a canonical remote that still names a renamed
repository: GitHub answers a reference with its canonical name, and the adapter
asks once what GitHub calls the run's repository only when an answer names
another. The GitHub CLI is the only fake."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, board_issue, complete_contract
from cli_fixtures import real_git, set_agent_identity_env
from github_fixtures import FakeForge, serve_forge
from store_fixtures import publish_claims_from_a_second_clone, state_ref_tip

from aco import board_read, checkout, forge, github, workboard
from aco import cli as issue_claim
from aco.github import GitHubForge

STALE = "overnightworks/agent-providers"
CURRENT = "overnightworks/agent-runtime"
OTHER = "overnightworks/other-repo"
RENAMED_SENTENCE = f"GitHub renamed {STALE} to {CURRENT}; point the canonical remote at {CURRENT}"


@dataclass(frozen=True)
class Site:
    """One adapter entry point that turns a GitHub answer into a repository name."""

    reply: Callable[[str], str]
    read: Callable[[GitHubForge], object]


def _reference_url(repository: str) -> str:
    return f"https://api.github.com/repos/{repository}"


def _pull_request_reply(repository: str) -> str:
    owner, _, name = repository.partition("/")
    return json.dumps(
        {
            "number": 12,
            "title": "Land it",
            "body": "Work-Item: #72",
            "baseRefName": "main",
            "headRefName": "claude/issue-72-land",
            "headRefOid": "a" * 40,
            "headRepository": {"name": name},
            "headRepositoryOwner": {"login": owner},
            "author": {"login": "ada"},
            "mergedAt": None,
            "mergeCommit": None,
        }
    )


def _blocker_reply(repository: str, number: int = 7) -> str:
    return json.dumps(
        {
            "number": number,
            "state": "open",
            "closedAt": None,
            "repository": repository,
            "isPullRequest": False,
        }
    )


SITES = {
    "sub-issue": Site(
        lambda repository: json.dumps(
            {"number": 72, "repository": _reference_url(repository), "state": "open"}
        ),
        lambda client: client.list_children(79),
    ),
    "parent": Site(
        lambda repository: json.dumps(
            {"number": 79, "repository": _reference_url(repository), "body": ""}
        ),
        lambda client: client.parent_issue(72),
    ),
    "blocker": Site(_blocker_reply, lambda client: client.list_board_dependencies(72)),
    "pull-request": Site(_pull_request_reply, lambda client: client.landing(12)),
}


@dataclass
class ScriptedGitHub:
    """A `gh` that answers every data call with `reply` and the repository
    lookup with `canonical`, recording each lookup."""

    canonical: str
    reply: str
    lookups: int = 0

    def __call__(self, arguments: list[str], *, input_data: bytes | None = None) -> str:
        if arguments[-2:] == ["--jq", ".full_name"]:
            self.lookups += 1
            return self.canonical
        return self.reply


def _stale_client(site: Site, canonical: str = CURRENT) -> tuple[GitHubForge, ScriptedGitHub]:
    gh = ScriptedGitHub(canonical, site.reply(CURRENT))
    return GitHubForge(github.repository_id(STALE), run=gh), gh


@pytest.mark.parametrize("site", SITES.values(), ids=SITES.keys())
def test_a_reference_to_the_renamed_repository_refuses_naming_cause_and_fix(site: Site) -> None:
    client, gh = _stale_client(site)

    with pytest.raises(forge.ForgeRepositoryRenamedError) as refusal:
        site.read(client)

    assert (str(refusal.value), gh.lookups) == (RENAMED_SENTENCE, 1)


@pytest.mark.parametrize("site", SITES.values(), ids=SITES.keys())
def test_a_run_with_only_its_own_references_asks_github_nothing_extra(site: Site) -> None:
    gh = ScriptedGitHub(STALE, site.reply(STALE))
    client = GitHubForge(github.repository_id(STALE), run=gh)

    site.read(client)

    assert gh.lookups == 0


def test_a_case_only_difference_refuses_the_same_way() -> None:
    gh = ScriptedGitHub("overnightworks/aco", SITES["parent"].reply("overnightworks/aco"))
    client = GitHubForge(github.repository_id("Overnightworks/Aco"), run=gh)

    with pytest.raises(forge.ForgeRepositoryRenamedError) as refusal:
        client.parent_issue(72)

    assert str(refusal.value) == (
        "GitHub renamed Overnightworks/Aco to overnightworks/aco; "
        "point the canonical remote at overnightworks/aco"
    )


def test_two_differing_references_cost_one_lookup() -> None:
    reply = "\n".join((_blocker_reply(OTHER, 7), _blocker_reply(OTHER, 8)))
    gh = ScriptedGitHub(STALE, reply)
    client = GitHubForge(github.repository_id(STALE), run=gh)

    dependencies = client.list_board_dependencies(72)

    assert (len(dependencies), gh.lookups) == (2, 1)


def test_a_foreign_blocker_is_returned_as_foreign_after_one_agreeing_lookup() -> None:
    gh = ScriptedGitHub(STALE, _blocker_reply(OTHER))
    client = GitHubForge(github.repository_id(STALE), run=gh)

    dependencies = client.list_board_dependencies(150)

    assert (dependencies[0].reference, gh.lookups) == (workboard.IssueReference(OTHER, 7), 1)


def test_a_fork_branch_is_read_as_its_own_repository_after_one_agreeing_lookup() -> None:
    gh = ScriptedGitHub(STALE, _pull_request_reply("fork/agent-providers"))
    client = GitHubForge(github.repository_id(STALE), run=gh)

    source_repository = client.landing(12).source_repository

    assert (source_repository, gh.lookups) == (github.repository_id("fork/agent-providers"), 1)


def test_a_sub_issue_from_another_repository_is_still_refused_after_one_agreeing_lookup() -> None:
    gh = ScriptedGitHub(STALE, SITES["sub-issue"].reply(OTHER))
    client = GitHubForge(github.repository_id(STALE), run=gh)

    with pytest.raises(forge.ForgeMalformedResponseError, match="sub-issue from another repo"):
        client.list_children(79)

    assert gh.lookups == 1


def test_a_lookup_answer_that_names_no_repository_becomes_the_board_read_hint() -> None:
    client, _gh = _stale_client(SITES["parent"], canonical="overnightworks")

    outcome = board_read.board_read_after_write(lambda: client.parent_issue(72))

    assert isinstance(outcome, str)
    assert outcome.startswith(
        "hint: could not read the board to report what this write freed "
        "(GitHub returned a malformed repository name)"
    )


def test_a_lookup_answer_that_names_no_repository_is_a_malformed_forge_response() -> None:
    client, _gh = _stale_client(SITES["parent"], canonical="overnightworks")

    with pytest.raises(forge.ForgeMalformedResponseError, match="malformed repository name"):
        client.parent_issue(72)


@dataclass(kw_only=True)
class _ForgeWhoseParentsAreGitHubs(FakeForge):
    """`start`'s fake forge, its parent read answered by the real adapter over `gh`."""

    parents_over_gh: GitHubForge

    def parent_issue(self, number: int) -> workboard.ParentIssue | None:
        return self.parents_over_gh.parent_issue(number)


def test_start_on_a_sub_issue_of_a_stale_clone_refuses_and_builds_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    github_clone: Path,
    bare_remote: Path,
) -> None:
    """Spec: PIN-52 (E-PIN-42)."""
    run_repository = github.repository_id(REPOSITORY)
    title = "Port the thing (#434 slice 13)"
    site = SITES["parent"]
    over_gh = GitHubForge(run_repository, run=ScriptedGitHub(CURRENT, site.reply(CURRENT)))
    fake = _ForgeWhoseParentsAreGitHubs(
        board_issues=(board_issue(437, title, complete_contract("Build it.", scope=["base.txt"])),),
        issue_references={437: forge.ItemReference(forge.ItemState.OPEN, title, "")},
        parents_over_gh=over_gh,
    )
    serve_forge(monkeypatch, fake)
    set_agent_identity_env(monkeypatch, {checkout.ACO_AGENT_ENV: "Ada"})
    monkeypatch.chdir(github_clone)
    publish_claims_from_a_second_clone(github_clone, bare_remote, ())
    tip_before = state_ref_tip(bare_remote)

    status = issue_claim.main(["--repo", REPOSITORY, "start", "437"])

    captured = capsys.readouterr()
    assert (status, captured.out, captured.err) == (
        2,
        "",
        f"ERROR: GitHub renamed {REPOSITORY} to {CURRENT}; "
        f"point the canonical remote at {CURRENT}\n",
    )
    assert state_ref_tip(bare_remote) == tip_before
    assert not (github_clone.parent / f"{github_clone.name}-worktrees").exists()
    assert real_git(github_clone, "worktree", "list").stdout.count("\n") == 1
