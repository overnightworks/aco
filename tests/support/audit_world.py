"""A GitHub-hosted board with one open item, one configured recurring audit and a real git
trunk, for the tests of the commands that read the audits."""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from board_fixtures import board_issue, complete_contract
from cli_fixtures import (
    FROZEN_CLI_NOW,
    freeze_cli_now,
    head_sha,
    real_git,
    track_board_config,
)
from github_fixtures import FakeForge, serve_forge

LABEL = "audit-scenario"
NAME = "scenario"
RUN = "Run the audit skill with its tests lens."
ANCHOR_NUMBER = 20


def entry_toml(
    *, name: str = NAME, label: str = LABEL, run: str = RUN, landings: int = 3, days: int = 7
) -> str:
    return (
        f'[[audit]]\nname = "{name}"\nlabel = "{label}"\n'
        f'landings = {landings}\ndays = {days}\nrun = "{run}"\n'
    )


def commit_on_trunk(
    repository: Path, monkeypatch: pytest.MonkeyPatch, *, days_ago: int, message: str
) -> str:
    moment = (FROZEN_CLI_NOW - timedelta(days=days_ago)).isoformat()
    monkeypatch.setenv("GIT_COMMITTER_DATE", moment)
    monkeypatch.setenv("GIT_AUTHOR_DATE", moment)
    real_git(repository, "commit", "--allow-empty", "-q", "-m", message)
    return head_sha(repository)


@dataclass
class World:
    """A GitHub-hosted board with one open item, `#11`, one configured audit and a trunk
    whose anchor commit is `anchor_sha`; `own` serves this repository."""

    clone: Path
    monkeypatch: pytest.MonkeyPatch
    own: FakeForge
    anchor_sha: str = ""

    def configure(self, toml: str) -> None:
        track_board_config(self.clone, toml)

    def land(self, *, days_ago: int, count: int = 1) -> None:
        for index in range(count):
            commit_on_trunk(
                self.clone, self.monkeypatch, days_ago=days_ago, message=f"land {index}"
            )
        real_git(self.clone, "push", "-q", "origin", "main")

    def anchor_at(self, *, days_ago: int, commits_after: int) -> str:
        self.anchor_sha = commit_on_trunk(
            self.clone, self.monkeypatch, days_ago=days_ago, message="audited"
        )
        self.land(days_ago=0, count=commits_after)
        return self.anchor_sha

    def label_issue(self, body: str) -> None:
        issue = board_issue(ANCHOR_NUMBER, "Audit findings", body, labels=(LABEL,))
        self.own.labelled_issues = {LABEL: (issue,)}

    def break_fetch(self) -> None:
        """Makes `origin`'s fetch ask for a branch it lacks: any later fetch is refused,
        while the remote's other reads still work."""
        real_git(
            self.clone,
            "config",
            "remote.origin.fetch",
            "+refs/heads/absent:refs/remotes/origin/absent",
        )


def build_world(monkeypatch: pytest.MonkeyPatch, github_clone: Path) -> World:
    freeze_cli_now(monkeypatch)
    own = serve_forge(
        monkeypatch,
        FakeForge(board_issues=(board_issue(11, "Top work", complete_contract("Claim #11.")),)),
    )
    return World(github_clone, monkeypatch, own)
