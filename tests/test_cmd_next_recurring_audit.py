"""`aco next` and the repository's recurring audits (NEXT-62..68, E-NEXT-19) against a
real git trunk and a GitHub forge fake, one case per row of the due rule's table."""

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from board_fixtures import board_issue, complete_contract
from cli_fixtures import (
    FROZEN_CLI_NOW,
    CliRun,
    freeze_cli_now,
    head_sha,
    real_git,
    run_cli,
    track_board_config,
)
from github_fixtures import FakeForge

from aco import checkout, github, protocol, recurring_audit
from aco.recurring_audit import Reason

LABEL = "audit-scenario"
NAME = "scenario"
RUN = "Run the audit skill with its tests lens."
ANCHOR_NUMBER = 20
FOREIGN_SHA = "b" * 40
TOP_WORK_LINES = (
    "#11 score -10: Top work\nNext: Claim #11.\n"
    "Run: aco start 11 --slug=top-work --scope <paths>\nscope unknown\n"
    "parallel: unknown (first action names no scope)\nclose: none\n"
)
NO_ACTION_LINES = "No actionable item.\nparallel: none\nscope unknown: none\nclose: none\n"
REAL_FETCH = checkout.fetch_remote


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
    fetches: list[str]
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

    def fetching(self, *, works: bool) -> None:
        def fetch(remote: str, *, directory: Path) -> None:
            self.fetches.append(remote)
            if not works:
                raise protocol.ClaimError("fetch refused for the scenario")
            REAL_FETCH(remote, directory=directory)

        self.monkeypatch.setattr(checkout, "fetch_remote", fetch)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, github_clone: Path, github_world: Path) -> World:
    freeze_cli_now(monkeypatch)
    own = FakeForge(board_issues=(board_issue(11, "Top work", complete_contract("Claim #11.")),))
    monkeypatch.setattr(github, "GitHubForge", lambda repository: own)
    made = World(github_clone, monkeypatch, own, [])
    made.fetching(works=False)
    return made


def next_both(capsys: pytest.CaptureFixture[str]) -> tuple[CliRun, CliRun, dict[str, Any]]:
    printed = run_cli(["next"], capsys)
    result = run_cli(["next", "--json"], capsys)
    return printed, result, json.loads(result.stdout)


def trunk_name() -> str:
    return checkout.remote_tracking_ref("origin", "main")


@dataclass(frozen=True)
class Scenario:
    body: str
    anchor_days_ago: int
    commits_after: int
    headline: str
    reason: Reason
    anchor: int | None
    names_sha: bool
    landings_since: int | None
    days_since: int | None


SCENARIOS = {
    "landings reached": Scenario(
        "audited through {sha}",
        0,
        3,
        "audit_due scenario: 3 landings since #20, audited through {sha7}",
        Reason.LANDINGS,
        ANCHOR_NUMBER,
        True,
        3,
        0,
    ),
    "days passed with a landing": Scenario(
        "audited through {sha}",
        10,
        1,
        "audit_due scenario: 10 days and 1 landing(s) since #20, audited through {sha7}",
        Reason.DAYS,
        ANCHOR_NUMBER,
        True,
        1,
        10,
    ),
    "no audited through line": Scenario(
        "no line here",
        0,
        0,
        "audit_due scenario: no item labelled audit-scenario holds an audited through line",
        Reason.NO_ANCHOR,
        None,
        False,
        None,
        None,
    ),
    "a line naming no full commit": Scenario(
        "audited through abc1234",
        0,
        0,
        "audit_due scenario: #20's audited through line names no full commit",
        Reason.ANCHOR_MALFORMED,
        ANCHOR_NUMBER,
        False,
        None,
        None,
    ),
}


@pytest.mark.parametrize("scenario", SCENARIOS.values(), ids=SCENARIOS.keys())
def test_a_due_audit_is_printed_before_the_work_item_and_carried_with_its_reason(
    world: World, capsys: pytest.CaptureFixture[str], scenario: Scenario
) -> None:
    """Spec: NEXT-62, NEXT-63, NEXT-64."""
    world.configure(entry_toml())
    sha = world.anchor_at(days_ago=scenario.anchor_days_ago, commits_after=scenario.commits_after)
    world.label_issue(scenario.body.format(sha=sha))
    headline = scenario.headline.format(sha7=sha[:7])

    printed, result, payload = next_both(capsys)

    assert (printed.status, printed.stdout) == (
        0,
        f"{headline}\nNext: {RUN}\n\n{TOP_WORK_LINES}",
    )
    assert (result.status, payload["reason"], payload["audits"]) == (
        0,
        "work_item",
        [
            {
                "name": NAME,
                "reason": scenario.reason,
                "anchor": scenario.anchor,
                "sha": sha if scenario.names_sha else None,
                "landings_since": scenario.landings_since,
                "days_since": scenario.days_since,
                "run": RUN,
                "error": None,
            }
        ],
    )


@pytest.mark.parametrize(
    ("anchor_days_ago", "commits_after"),
    [(0, 2), (6, 2), (30, 0)],
    ids=["landings short", "days short", "no landing since"],
)
def test_an_audit_that_is_not_due_prints_nothing_and_carries_no_entry(
    world: World,
    capsys: pytest.CaptureFixture[str],
    anchor_days_ago: int,
    commits_after: int,
) -> None:
    """Spec: NEXT-63, NEXT-65."""
    world.configure(entry_toml())
    sha = world.anchor_at(days_ago=anchor_days_ago, commits_after=commits_after)
    world.label_issue(f"audited through {sha}")

    printed, _result, payload = next_both(capsys)

    assert (printed.stdout, payload["audits"], world.fetches) == (TOP_WORK_LINES, [], [])


def test_an_anchor_only_the_fetched_trunk_holds_is_counted_after_the_one_fetch(
    world: World, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Spec: NEXT-66."""
    world.configure(entry_toml())
    real_git(world.clone, "push", "-q", "origin", "main")
    other = tmp_path / "other"
    real_git(tmp_path, "clone", "-q", str(world.clone.parent / "remote.git"), str(other))
    sha = commit_on_trunk(other, world.monkeypatch, days_ago=0, message="audited elsewhere")
    for index in range(3):
        commit_on_trunk(other, world.monkeypatch, days_ago=0, message=f"later {index}")
    real_git(other, "push", "-q", "origin", "main")
    world.label_issue(f"audited through {sha}")
    world.fetching(works=True)

    printed, _result, payload = next_both(capsys)

    assert printed.stdout == (
        f"audit_due {NAME}: 3 landings since #{ANCHOR_NUMBER}, audited through {sha[:7]}\n"
        f"Next: {RUN}\n\n{TOP_WORK_LINES}"
    )
    assert [(entry["reason"], entry["landings_since"]) for entry in payload["audits"]] == [
        (Reason.LANDINGS, 3)
    ]


def test_an_anchor_the_fetched_trunk_lacks_too_is_due_as_off_the_trunk(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: NEXT-66."""
    world.configure(entry_toml())
    real_git(world.clone, "push", "-q", "origin", "main")
    world.label_issue(f"audited through {FOREIGN_SHA}")
    world.fetching(works=True)

    printed, _result, payload = next_both(capsys)

    assert printed.stdout == (
        f"audit_due {NAME}: #{ANCHOR_NUMBER} audited through {FOREIGN_SHA[:7]}, which is not "
        f"among the last {recurring_audit.MAX_LANDINGS} landings on {trunk_name()}\n"
        f"Next: {RUN}\n\n{TOP_WORK_LINES}"
    )
    assert [entry["reason"] for entry in payload["audits"]] == [Reason.ANCHOR_OFF_TRUNK]


def test_a_failed_fetch_leaves_the_audit_unavailable_and_the_work_item_as_it_was(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: NEXT-67 (E-NEXT-19)."""
    world.configure(entry_toml())
    real_git(world.clone, "push", "-q", "origin", "main")
    world.label_issue(f"audited through {FOREIGN_SHA}")

    printed, result, payload = next_both(capsys)

    unavailable = f"audit {NAME}: unavailable (fetch refused for the scenario)"
    assert (printed.status, printed.stdout, result.status) == (
        0,
        f"{unavailable}\n\n{TOP_WORK_LINES}",
        0,
    )
    assert [(entry["reason"], entry["error"]) for entry in payload["audits"]] == [
        (Reason.UNAVAILABLE, "fetch refused for the scenario")
    ]


def test_a_failed_listing_leaves_the_audit_unavailable_and_the_work_item_as_it_was(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: NEXT-67 (E-NEXT-19)."""
    world.configure(entry_toml())
    world.own.labelled_listing_error = protocol.ClaimError("GitHub is down")

    printed, result, payload = next_both(capsys)

    assert (printed.stdout, result.status, payload["reason"]) == (
        f"audit {NAME}: unavailable (GitHub is down)\n\n{TOP_WORK_LINES}",
        0,
        "work_item",
    )
    assert [(entry["reason"], entry["error"]) for entry in payload["audits"]] == [
        (Reason.UNAVAILABLE, "GitHub is down")
    ]


def test_a_due_audit_alone_leaves_the_exit_status_and_reason_of_an_empty_board(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: NEXT-68."""
    world.configure(entry_toml())
    world.own.board_issues = ()
    world.label_issue("nothing audited yet")

    printed, result, payload = next_both(capsys)

    headline = f"audit_due {NAME}: no item labelled {LABEL} holds an audited through line"
    assert (printed.status, printed.stdout, result.status, payload["reason"]) == (
        3,
        f"{headline}\nNext: {RUN}\n\n{NO_ACTION_LINES}",
        3,
        "nothing_actionable",
    )


def test_the_entrys_text_is_printed_escaped_and_carried_as_written(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: NEXT-64."""
    world.configure(entry_toml(run="clear \\u001b[2J then stop"))
    world.label_issue("no line")

    printed, _result, payload = next_both(capsys)

    assert printed.stdout.splitlines()[1] == "Next: clear \\x1b[2J then stop"
    assert [entry["run"] for entry in payload["audits"]] == ["clear \x1b[2J then stop"]


def test_each_entry_costs_one_listing_and_none_without_an_entry_is_read(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: NEXT-65."""
    run_cli(["next"], capsys)
    without_entry = list(world.own.labelled_listings)
    world.configure(entry_toml() + entry_toml(name="second", label="audit-second"))
    sha = world.anchor_at(days_ago=0, commits_after=0)
    world.label_issue(f"audited through {sha}")

    run_cli(["next"], capsys)

    assert (without_entry, world.own.labelled_listings) == ([], [LABEL, "audit-second"])


def test_without_an_entry_the_output_has_no_audit_line_and_an_empty_audits_key(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: NEXT-62, NEXT-63."""
    printed, _result, payload = next_both(capsys)

    assert (printed.stdout, payload["audits"]) == (TOP_WORK_LINES, [])
